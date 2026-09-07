"""Hourly wind and solar profiles for the TYTFS fleet, from ERA5.

Why
---
A TYTFS case is four snapshots.  Anything that asks when the network is
constrained - dispatch-down, export limits, the value of a reinforcement -
needs a year, and the year has to have real weather in it.  A random walk
with the right marginal distribution gets the one thing that matters wrong:
**the spatial correlation**.  Calm anticyclones and storm fronts are hundreds
of kilometres across and cross Ireland in hours, so every wind farm in
Donegal is at rated output within the same six hours and at zero within the
same six hours, and the constraint on the Letterkenny-Strabane tie is a
consequence of that and of nothing else.  ERA5 has it because ERA5 is a
reanalysis of what the atmosphere actually did.

This module fetches ERA5 through Open-Meteo's historical archive - no key, no
account, plain HTTP GET - converts it to per-generator capacity factors, and
checks the result against EirGrid's published all-island wind generation.

**It will not invent a profile.**  Every path that cannot get real data raises.
The validation in :func:`validate_wind` is the point of the module, not a
postscript: an unvalidated profile is a fabrication that happens to be shaped
like data.

Sources
-------
============================ ==========================================
ERA5 / ERA5-Land, hourly     https://archive-api.open-meteo.com/v1/archive
                             CC BY 4.0, 1940 to about five days ago
All-island demand and wind   https://www.smartgriddashboard.com
                             and the bulk archives on cms.eirgrid.ie
============================ ==========================================

Usage
-----
    python profiles.py sites                    # what would be requested
    python profiles.py fetch --year 2023        # ERA5 -> data/raw/weather/
    python profiles.py build --year 2023        # -> data/profiles/
    python profiles.py validate --year 2023     # against EirGrid's actuals

Every step is cached on disk and none of them re-fetches a location-year it
already has.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

import psse
import pypsa_net

# --------------------------------------------------------------------------- #
# Source
# --------------------------------------------------------------------------- #

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

#: The variables the conversions need.  ``wind_speed_10m`` is not decoration:
#: with ``wind_speed_100m`` it gives the local shear exponent, which is what
#: makes a hub-height correction exact rather than a guess.
VARIABLES = (
    "wind_speed_100m",
    "wind_speed_10m",
    "shortwave_radiation",
    "direct_normal_irradiance",
    "temperature_2m",
)

#: ERA5-Land is 0.1 degrees and covers land only; ERA5 is 0.25 degrees and
#: covers everything.  Open-Meteo will fall back to ERA5 where ERA5-Land has
#: no value, which for an Irish onshore fleet is the coast and not much else.
MODELS = ("era5_land", "era5")

#: Locations per request.  Open-Meteo's archive endpoint takes comma-separated
#: coordinate lists; this is well inside what it accepts and keeps the whole
#: island to a handful of requests per year.
BATCH = 25

#: Seconds between requests.  The service is free and rate-limited, and the
#: brief is explicit: fetch once, never in a retry loop.
PAUSE = 2.0

CACHE_DIR = "data/raw/weather"
OUTPUT_DIR = "data/profiles"

#: ERA5-Land's grid.  Two sites in one cell get identical weather, so they are
#: requested once.  This is the only rounding applied to a coordinate.
CELL = 0.1


class Unavailable(RuntimeError):
    """The data is not there and this module will not make it up."""


# --------------------------------------------------------------------------- #
# Sites
#
# One row per generator record in the case's register - not per dispatched
# machine.  A year of weather is for running the fleet; the four published
# cases run between 3% and 21% of it.
# --------------------------------------------------------------------------- #

def sites(case: psse.Case, geocoding: str | None = None,
          carriers: tuple[str, ...] = ("wind", "solar")) -> pd.DataFrame:
    """Every wind and solar generator in the register, with a coordinate.

    The carrier comes from the bus-name convention Phase 2 established, and
    the coordinate from the station Phase 2 geocoded, resolved through the
    same least-reactance aggregation the transmission network uses.  A
    generator whose station could not be placed gets no coordinate and is
    reported rather than dropped silently.
    """
    geocoding = geocoding or os.path.join(
        "data/pypsa/geocoding", f"{case.name}.csv")
    if not os.path.exists(geocoding):
        raise Unavailable(
            f"no geocoding for {case.name}: run `python geocode.py match` "
            "first.  Without coordinates there is nowhere to ask about.")
    placed = pd.read_csv(geocoding)
    placed = placed[placed["lat"].notna()]
    lat = dict(zip(placed["bus"].astype(str), placed["lat"]))
    lon = dict(zip(placed["bus"].astype(str), placed["lon"]))
    station = dict(zip(placed["bus"].astype(str), placed["station"]))

    stars, el = pypsa_net.elements(case)
    el = pypsa_net._fill_unrated(el)
    keep = pypsa_net._retained(case, stars, el, pypsa_net.TRANSMISSION_KV)
    aggregation = pypsa_net._aggregate_to(case, el, keep)
    parent = dict(zip(aggregation["bus"], aggregation["parent"]))

    name = pypsa_net._clean(case.bus.set_index("I")["NAME"])
    rows = []
    for _, g in case.generator.iterrows():
        bus_name = name.get(int(g["I"]), "")
        carrier = pypsa_net.carrier_of(bus_name)
        if carrier not in carriers:
            continue
        key = str(int(g["I"]))
        home = key if key in keep else parent.get(key, "")
        rows.append({
            "generator": f"{int(g['I'])}-{str(g['ID']).strip()}",
            "psse_bus": int(g["I"]),
            "psse_bus_name": bus_name,
            "bus": home,
            "station": station.get(home, ""),
            "carrier": carrier,
            "p_nom": float(g["PT"]),
            "in_service": int(g["STAT"]) == 1,
            "lat": lat.get(home, np.nan),
            "lon": lon.get(home, np.nan),
        })
    frame = pd.DataFrame(rows)
    frame["cell_lat"] = (frame["lat"] / CELL).round() * CELL
    frame["cell_lon"] = (frame["lon"] / CELL).round() * CELL
    frame["cell"] = [cell_id(a, b) for a, b in
                     zip(frame["cell_lat"], frame["cell_lon"])]
    return frame


def cell_id(lat: float, lon: float) -> str:
    """A stable name for a grid cell, used as the cache key."""
    if not (np.isfinite(lat) and np.isfinite(lon)):
        return ""
    return f"{lat:+07.2f}_{lon:+08.2f}"


def cells(site_frame: pd.DataFrame) -> pd.DataFrame:
    """The distinct grid cells to ask about, with what sits in each."""
    placed = site_frame[site_frame["cell"] != ""]
    grouped = placed.groupby(["cell", "cell_lat", "cell_lon"])
    return pd.DataFrame({
        "cell": [c for c, _, _ in grouped.groups],
        "lat": [a for _, a, _ in grouped.groups],
        "lon": [b for _, _, b in grouped.groups],
        "generators": grouped.size().values,
        "p_nom": grouped["p_nom"].sum().values,
    }).sort_values("cell").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Fetching
#
# Batched, cached, and single-attempt.  A cache file is written only after the
# whole response has parsed, so a half-written year cannot be mistaken for a
# complete one.
# --------------------------------------------------------------------------- #

def cache_path(cell: str, year: int, model: str,
               directory: str = CACHE_DIR) -> str:
    return os.path.join(directory, f"{model}_{year}_{cell}.json")


def cached(cell: str, year: int, model: str = MODELS[0],
           directory: str = CACHE_DIR) -> bool:
    return os.path.exists(cache_path(cell, year, model, directory))


def fetch(cell_frame: pd.DataFrame, year: int, model: str = MODELS[0],
          directory: str = CACHE_DIR, batch: int = BATCH,
          pause: float = PAUSE) -> dict:
    """Download a year of hourly ERA5 for every cell not already cached.

    One request per batch of cells, one attempt each.  A failure aborts the
    run and says so; it does not retry, and it does not fall back to anything
    invented.  Cells already on disk are never requested again, so re-running
    this costs nothing.
    """
    import requests

    os.makedirs(directory, exist_ok=True)
    wanted = [c for c in cell_frame.itertuples()
              if not cached(c.cell, year, model, directory)]
    report = {"cells": len(cell_frame), "cached": len(cell_frame) - len(wanted),
              "requested": 0, "requests": 0, "failures": []}
    if not wanted:
        return report

    for start in range(0, len(wanted), batch):
        chunk = wanted[start:start + batch]
        params = {
            "latitude": ",".join(f"{c.lat:.4f}" for c in chunk),
            "longitude": ",".join(f"{c.lon:.4f}" for c in chunk),
            "start_date": f"{year}-01-01",
            "end_date": f"{year}-12-31",
            "hourly": ",".join(VARIABLES),
            "models": model,
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
        try:
            response = requests.get(ARCHIVE_URL, params=params, timeout=600)
        except Exception as exc:                            # noqa: BLE001
            raise Unavailable(
                f"Open-Meteo request failed: {type(exc).__name__}: {exc}. "
                "Nothing has been invented; fix the connection and re-run - "
                "the cells already cached will not be asked for again."
            ) from exc
        if response.status_code == 429:
            raise Unavailable(
                "Open-Meteo returned 429 (rate limited).  Stopping rather "
                f"than retrying; {report['requests']} requests succeeded and "
                "are cached.  Wait and re-run.")
        if response.status_code != 200:
            raise Unavailable(
                f"Open-Meteo returned {response.status_code}: "
                f"{response.text[:200]}")
        payload = response.json()
        blocks = payload if isinstance(payload, list) else [payload]
        if len(blocks) != len(chunk):
            raise Unavailable(
                f"asked for {len(chunk)} locations and got {len(blocks)} "
                "back; refusing to guess which is which")
        for block, c in zip(blocks, chunk):
            _check(block, c)
            with open(cache_path(c.cell, year, model, directory), "w") as fh:
                json.dump(block, fh)
            report["requested"] += 1
        report["requests"] += 1
        time.sleep(pause)
    return report


def _check(block: dict, cell) -> None:
    """Refuse a response that is not the year that was asked for."""
    hourly = block.get("hourly") or {}
    missing = [v for v in VARIABLES if v not in hourly]
    if missing:
        raise Unavailable(f"cell {cell.cell}: response has no {missing}")
    hours = len(hourly.get("time", []))
    if hours < 8000:
        raise Unavailable(
            f"cell {cell.cell}: {hours} hours in the response, which is not a "
            "year.  Not caching a partial year as if it were complete.")


def load_cell(cell: str, year: int, model: str = MODELS[0],
              directory: str = CACHE_DIR) -> pd.DataFrame:
    """One cell's cached year, as a DataFrame indexed by UTC hour."""
    path = cache_path(cell, year, model, directory)
    if not os.path.exists(path):
        raise Unavailable(
            f"no cached weather for cell {cell} in {year}.  Run "
            "`python profiles.py fetch` - this module does not simulate "
            "weather it has not got.")
    with open(path) as fh:
        block = json.load(fh)
    hourly = block["hourly"]
    frame = pd.DataFrame({v: hourly[v] for v in VARIABLES})
    frame.index = pd.DatetimeIndex(hourly["time"])
    frame.index.name = "snapshot"
    return frame.astype(float)


# --------------------------------------------------------------------------- #
# Wind
#
# Three steps, each of which can be wrong on its own: get the wind to hub
# height, put it through a turbine, and then admit that a grid cell is not a
# turbine.  The third is the one people skip and it is the largest.
# --------------------------------------------------------------------------- #

#: The power curve, stated so it can be argued with.  A generic IEC Class II
#: onshore machine:
#:
#:     cut-in       3.0 m/s
#:     rated       12.0 m/s
#:     cut-out     25.0 m/s
#:
#: and between cut-in and rated, the cubic that a turbine's aerodynamics give:
#:
#:     P(v) = (v^3 - v_in^3) / (v_rated^3 - v_in^3)
#:
#: which is 0 at cut-in and 1 at rated by construction.
CUT_IN, RATED, CUT_OUT = 3.0, 12.0, 25.0

#: The correction that matters.  An ERA5 cell is 10 km across and a wind farm
#: is tens of turbines spread over it, so the single-turbine curve applied to
#: a cell-mean wind speed is far too sharp: it gives a farm that reaches rated
#: output all at once and cuts out all at once, and neither happens.  The
#: standard fix (Staffell and Pfenninger 2016) is to convolve the turbine
#: curve with a Gaussian, which is what a spread of wind speeds across a farm
#: does to it.  1.5 m/s is within the range that paper finds for aggregated
#: fleets; it is a parameter here because the validation is what should set
#: it.
FARM_SPREAD = 1.5

#: Losses between the rotors and the meter: wake, array electrical, blade
#: soiling and icing, availability.  Ireland's published fleet load factors
#: are consistent with something in this region.  Also a parameter, also for
#: the validation to set.
WIND_AVAILABILITY = 0.90

#: Hub heights are not in a PSS/E raw file.  100 m makes the correction a
#: no-op, because ``wind_speed_100m`` is already at 100 m; give a site a real
#: hub height and the shear exponent below does the rest.
DEFAULT_HUB_HEIGHT = 100.0


def shear_exponent(wind_10m, wind_100m, floor: float = 0.05,
                   ceiling: float = 0.60):
    """The local power-law shear exponent, from the two heights ERA5 gives.

    ``v(z) = v(z_ref) * (z / z_ref) ** alpha``, so

        alpha = ln(v100 / v10) / ln(100 / 10)

    computed hour by hour rather than assumed, because it is not a constant:
    it collapses towards 0.1 in a well-mixed daytime boundary layer and rises
    past 0.4 in a stable night-time one, and that diurnal swing is worth tens
    of percent at hub height.  Clipped to a physical range so that a calm hour
    with a near-zero 10 m wind cannot produce nonsense.
    """
    v10 = np.asarray(wind_10m, dtype=float)
    v100 = np.asarray(wind_100m, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.log(np.maximum(v100, 1e-6) / np.maximum(v10, 1e-6)) \
            / math.log(100.0 / 10.0)
    return np.clip(np.nan_to_num(alpha, nan=0.14), floor, ceiling)


def hub_speed(wind_100m, alpha, hub_height: float = DEFAULT_HUB_HEIGHT):
    """Wind speed at hub height, from the 100 m speed and the local shear."""
    if hub_height == 100.0:
        return np.asarray(wind_100m, dtype=float)
    return np.asarray(wind_100m, dtype=float) * (hub_height / 100.0) ** alpha


def turbine_curve(speed, cut_in: float = CUT_IN, rated: float = RATED,
                  cut_out: float = CUT_OUT):
    """The single-turbine power curve, before any smoothing."""
    v = np.asarray(speed, dtype=float)
    out = np.zeros_like(v)
    ramp = (v >= cut_in) & (v < rated)
    out[ramp] = ((v[ramp] ** 3 - cut_in ** 3)
                 / (rated ** 3 - cut_in ** 3))
    out[(v >= rated) & (v < cut_out)] = 1.0
    return out


def farm_curve(spread: float = FARM_SPREAD, cut_in: float = CUT_IN,
               rated: float = RATED, cut_out: float = CUT_OUT,
               step: float = 0.05, top: float = 40.0):
    """The turbine curve convolved with a Gaussian spread of wind speeds.

    Returns ``(speeds, power)`` on a fine grid, ready to interpolate.  With
    ``spread = 0`` it is the turbine curve exactly.
    """
    speeds = np.arange(0.0, top + step, step)
    single = turbine_curve(speeds, cut_in, rated, cut_out)
    if spread <= 0:
        return speeds, single
    half = int(math.ceil(4.0 * spread / step))
    offsets = np.arange(-half, half + 1) * step
    kernel = np.exp(-0.5 * (offsets / spread) ** 2)
    kernel /= kernel.sum()
    padded = np.concatenate([np.zeros(half), single, np.zeros(half)])
    smoothed = np.convolve(padded, kernel, mode="same")[half:half + len(speeds)]
    return speeds, np.clip(smoothed, 0.0, 1.0)


def wind_capacity_factor(weather: pd.DataFrame,
                         hub_height: float = DEFAULT_HUB_HEIGHT,
                         spread: float = FARM_SPREAD,
                         availability: float = WIND_AVAILABILITY,
                         cut_in: float = CUT_IN, rated: float = RATED,
                         cut_out: float = CUT_OUT) -> pd.Series:
    """One cell's hourly wind capacity factor, in [0, 1]."""
    alpha = shear_exponent(weather["wind_speed_10m"],
                           weather["wind_speed_100m"])
    v = hub_speed(weather["wind_speed_100m"], alpha, hub_height)
    speeds, power = farm_curve(spread, cut_in, rated, cut_out)
    cf = np.interp(v, speeds, power, left=0.0, right=0.0)
    return pd.Series(np.clip(cf * availability, 0.0, 1.0),
                     index=weather.index, name="wind")


# --------------------------------------------------------------------------- #
# Solar
#
# Deliberately simple, and every assumption is written down.  A fixed-tilt
# south-facing array with an isotropic sky and a linear temperature
# derating - no tracking, no spectral or incidence-angle modifier, no
# shading.  For an Irish fleet at 53 degrees north the diffuse fraction is
# more than half the annual total, so the sky model matters more than any of
# the refinements left out.
# --------------------------------------------------------------------------- #

TILT = 35.0            #: degrees from horizontal, typical Irish fixed tilt
AZIMUTH = 180.0        #: degrees clockwise from north, so due south
ALBEDO = 0.20          #: ground reflectance, grass
NOCT = 45.0            #: nominal operating cell temperature, degrees C
GAMMA = -0.004         #: power temperature coefficient, per degree C
SYSTEM_LOSSES = 0.14   #: inverter, wiring, soiling, mismatch


def solar_position(index: pd.DatetimeIndex, lat: float, lon: float):
    """Solar zenith and azimuth in degrees, by the NOAA algorithm.

    Accurate to a fraction of a degree, which is far inside anything else in
    this model.  ``index`` is UTC.
    """
    times = pd.DatetimeIndex(index)
    day = times.dayofyear.to_numpy(dtype=float)
    hour = (times.hour.to_numpy(dtype=float)
            + times.minute.to_numpy(dtype=float) / 60.0)

    gamma = 2.0 * math.pi / 365.0 * (day - 1.0 + (hour - 12.0) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(gamma)
                       - 0.032077 * np.sin(gamma)
                       - 0.014615 * np.cos(2 * gamma)
                       - 0.040849 * np.sin(2 * gamma))
    declination = (0.006918 - 0.399912 * np.cos(gamma)
                   + 0.070257 * np.sin(gamma)
                   - 0.006758 * np.cos(2 * gamma)
                   + 0.000907 * np.sin(2 * gamma)
                   - 0.002697 * np.cos(3 * gamma)
                   + 0.00148 * np.sin(3 * gamma))

    time_offset = eqtime + 4.0 * lon              # minutes, UTC
    true_solar = hour * 60.0 + time_offset
    hour_angle = np.radians(true_solar / 4.0 - 180.0)

    phi = math.radians(lat)
    cos_zenith = (math.sin(phi) * np.sin(declination)
                  + math.cos(phi) * np.cos(declination) * np.cos(hour_angle))
    cos_zenith = np.clip(cos_zenith, -1.0, 1.0)
    zenith = np.degrees(np.arccos(cos_zenith))

    with np.errstate(invalid="ignore", divide="ignore"):
        cos_azimuth = ((np.sin(declination) * math.cos(phi)
                        - np.cos(declination) * math.sin(phi)
                        * np.cos(hour_angle))
                       / np.maximum(np.sin(np.radians(zenith)), 1e-9))
    azimuth = np.degrees(np.arccos(np.clip(cos_azimuth, -1.0, 1.0)))
    azimuth = np.where(hour_angle > 0, 360.0 - azimuth, azimuth)
    return zenith, azimuth


def plane_of_array(ghi, dni, zenith, azimuth, tilt: float = TILT,
                   surface_azimuth: float = AZIMUTH, albedo: float = ALBEDO):
    """Irradiance on a fixed tilted plane, W/m^2.

    Three components, isotropic sky:

        beam      DNI * cos(angle of incidence)
        diffuse   DHI * (1 + cos(tilt)) / 2
        ground    GHI * albedo * (1 - cos(tilt)) / 2

    with ``DHI = GHI - DNI * cos(zenith)``, floored at zero because the two
    ERA5 fields are not guaranteed to close exactly.
    """
    ghi = np.asarray(ghi, dtype=float)
    dni = np.asarray(dni, dtype=float)
    z = np.radians(np.asarray(zenith, dtype=float))
    beta = math.radians(tilt)
    delta_azimuth = np.radians(np.asarray(azimuth, dtype=float)
                               - surface_azimuth)

    cos_zenith = np.cos(z)
    dhi = np.maximum(ghi - dni * np.maximum(cos_zenith, 0.0), 0.0)
    cos_aoi = (np.cos(z) * math.cos(beta)
               + np.sin(z) * math.sin(beta) * np.cos(delta_azimuth))
    cos_aoi = np.maximum(cos_aoi, 0.0)
    night = cos_zenith <= 0.0

    beam = np.where(night, 0.0, dni * cos_aoi)
    sky = dhi * (1.0 + math.cos(beta)) / 2.0
    ground = ghi * albedo * (1.0 - math.cos(beta)) / 2.0
    return np.maximum(beam + sky + ground, 0.0)


def solar_capacity_factor(weather: pd.DataFrame, lat: float, lon: float,
                          tilt: float = TILT, surface_azimuth: float = AZIMUTH,
                          losses: float = SYSTEM_LOSSES) -> pd.Series:
    """One cell's hourly solar capacity factor, in [0, 1].

    The panel model, in full:

        cell temperature   T_cell = T_air + POA * (NOCT - 20) / 800
        DC output          POA / 1000 * (1 + gamma * (T_cell - 25))
        AC output          DC * (1 - losses), clipped to [0, 1]

    Capacity is taken as the inverter rating, so the clip at 1.0 stands in for
    an array oversized against its inverter, which every real plant is.
    """
    zenith, azimuth = solar_position(weather.index, lat, lon)
    poa = plane_of_array(weather["shortwave_radiation"],
                         weather["direct_normal_irradiance"],
                         zenith, azimuth, tilt, surface_azimuth)
    t_cell = weather["temperature_2m"].to_numpy() + poa * (NOCT - 20.0) / 800.0
    dc = poa / 1000.0 * (1.0 + GAMMA * (t_cell - 25.0))
    return pd.Series(np.clip(dc * (1.0 - losses), 0.0, 1.0),
                     index=weather.index, name="solar")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def cell_profiles(cell_frame: pd.DataFrame, year: int,
                  model: str = MODELS[0], directory: str = CACHE_DIR,
                  hub_height: float = DEFAULT_HUB_HEIGHT,
                  spread: float = FARM_SPREAD,
                  availability: float = WIND_AVAILABILITY,
                  tilt: float = TILT) -> dict[str, pd.DataFrame]:
    """Wind and solar capacity factors for every cell, keyed by cell id."""
    out = {}
    for c in cell_frame.itertuples():
        weather = load_cell(c.cell, year, model, directory)
        out[c.cell] = pd.DataFrame({
            "wind": wind_capacity_factor(weather, hub_height, spread,
                                         availability),
            "solar": solar_capacity_factor(weather, c.lat, c.lon, tilt),
        })
    return out


def p_max_pu(site_frame: pd.DataFrame, year: int, model: str = MODELS[0],
             directory: str = CACHE_DIR, **kwargs) -> pd.DataFrame:
    """``p_max_pu`` per generator, wide, indexed by snapshot.

    One column per wind or solar generator in the register, one row per hour
    of the year, values in [0, 1].  Generators in the same 0.1-degree cell
    share a column of weather and therefore a profile, which is the honest
    resolution of the source: ERA5-Land does not distinguish two farms 4 km
    apart, and pretending it does by adding noise would put back exactly the
    fabrication this module exists to avoid.
    """
    placed = site_frame[site_frame["cell"] != ""]
    by_cell = cell_profiles(cells(placed), year, model, directory, **kwargs)
    columns = {}
    for site in placed.itertuples():
        columns[site.generator] = by_cell[site.cell][site.carrier]
    frame = pd.DataFrame(columns)
    frame.index.name = "snapshot"
    return frame


def unplaced(site_frame: pd.DataFrame) -> pd.DataFrame:
    """The generators with no coordinate, which therefore get no profile."""
    return site_frame[site_frame["cell"] == ""][
        ["generator", "psse_bus_name", "carrier", "p_nom", "bus"]]


# --------------------------------------------------------------------------- #
# Demand
#
# The spatial allocation comes from the TSO's own model and only the temporal
# shape from the dashboard, which is the brief and is also the only defensible
# split: EirGrid publishes one number for the island, and TYTFS says where the
# load is.
# --------------------------------------------------------------------------- #

def load_weights(case: psse.Case, min_kv: float = pypsa_net.TRANSMISSION_KV
                 ) -> pd.DataFrame:
    """Each in-service load record's share of the case's total demand.

    Weights are taken over ``PL`` with the ``STAT`` filter applied, because
    the register double-counts: 34 of WP2024's 266 load records are switched
    out and sit at buses that already carry an in-service load.
    """
    load = psse.loads(case).copy()
    total = float(load["PL"].sum())
    if total <= 0:
        raise Unavailable(f"{case.name}: in-service load sums to {total}")
    name = pypsa_net._clean(case.bus.set_index("I")["NAME"])
    frame = pd.DataFrame({
        "load": [f"{int(i)}-{str(d).strip()}"
                 for i, d in zip(load["I"], load["ID"])],
        "psse_bus": load["I"].astype(int).values,
        "psse_bus_name": load["I"].astype(int).map(name).values,
        "tytfs_mw": load["PL"].astype(float).values,
    })
    frame["weight"] = frame["tytfs_mw"] / total
    return frame


def allocate_demand(case: psse.Case, island: pd.Series) -> pd.DataFrame:
    """All-island demand spread over the case's load records, wide format.

    ``island`` is a Series of MW indexed by snapshot - EirGrid's published
    all-island system demand.  Every column sums, across the row, back to the
    island total, so nothing is created or lost in the allocation.
    """
    weights = load_weights(case)
    values = np.outer(np.asarray(island, dtype=float),
                      weights["weight"].to_numpy())
    frame = pd.DataFrame(values, index=pd.DatetimeIndex(island.index),
                         columns=weights["load"])
    frame.index.name = "snapshot"
    return frame


# --------------------------------------------------------------------------- #
# EirGrid's published series
#
# The dashboard is a public web application over a JSON service; it also
# offers a CSV export, and the bulk archives sit on cms.eirgrid.ie.  Both a
# fetcher and a reader for a file downloaded by hand are provided, because
# the fetcher is the part that a network policy can take away.
# --------------------------------------------------------------------------- #

DASHBOARD_URL = "https://www.smartgriddashboard.com/DashboardService.svc/data"

#: The dashboard's names for the two series this needs.
AREAS = {"demand": "demandactual", "wind": "windactual"}

EIRGRID_DIR = "data/raw/eirgrid"


def eirgrid_url(area: str, year: int, region: str = "ALL") -> str:
    """The dashboard request for one series and one year, for the record."""
    if area not in AREAS:
        raise ValueError(f"area must be one of {sorted(AREAS)}")
    return (f"{DASHBOARD_URL}?area={AREAS[area]}&region={region}"
            f"&datefrom={year}-01-01+00%3A00&dateto={year}-12-31+23%3A59")


def fetch_eirgrid(area: str, year: int, region: str = "ALL",
                  directory: str = EIRGRID_DIR) -> str:
    """Download one dashboard series for one year, once, to disk."""
    import requests

    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{area}_{region}_{year}.json")
    if os.path.exists(path):
        return path
    try:
        response = requests.get(eirgrid_url(area, year, region), timeout=600)
    except Exception as exc:                                # noqa: BLE001
        raise Unavailable(
            f"EirGrid dashboard request failed: {type(exc).__name__}: {exc}.  "
            "Download the CSV from https://www.smartgriddashboard.com by hand "
            f"and put it in {directory}/ - read_eirgrid() will take it."
        ) from exc
    if response.status_code != 200:
        raise Unavailable(f"dashboard returned {response.status_code}")
    with open(path, "w") as fh:
        fh.write(response.text)
    return path


def read_eirgrid(path: str) -> pd.Series:
    """One dashboard series from a file, JSON or CSV, as MW by timestamp.

    Written to take either shape, because the dashboard's own export is CSV
    and its service is JSON, and a file downloaded by hand could be either.
    The column names are matched case-insensitively against what the
    dashboard uses; anything it cannot recognise raises rather than guessing
    which column is the megawatts.
    """
    if path.endswith(".json"):
        with open(path) as fh:
            payload = json.load(fh)
        rows = payload.get("Rows", payload) if isinstance(payload, dict) \
            else payload
        frame = pd.DataFrame(rows)
    else:
        frame = pd.read_csv(path)

    lower = {c.lower().strip(): c for c in frame.columns}
    time_key = next((lower[k] for k in lower
                     if k in ("effectivetime", "datetime", "date",
                              "time", "timestamp")), None)
    value_key = next((lower[k] for k in lower
                      if k in ("value", "mw", "generation", "demand",
                               "actualgeneration", "systemdemand")), None)
    if time_key is None or value_key is None:
        raise Unavailable(
            f"{path}: cannot tell which column is the timestamp and which the "
            f"megawatts.  Columns are {list(frame.columns)}.  Rename them or "
            "extend read_eirgrid rather than letting it guess.")
    series = pd.Series(
        pd.to_numeric(frame[value_key], errors="coerce").to_numpy(),
        index=pd.to_datetime(frame[time_key], errors="coerce",
                             dayfirst=True))
    series = series[series.index.notna()].sort_index()
    series.index.name = "snapshot"
    return series.dropna()


def to_hourly(series: pd.Series) -> pd.Series:
    """The dashboard's quarter-hours averaged to the hour ERA5 is on."""
    return series.resample("1h").mean().dropna()


# --------------------------------------------------------------------------- #
# Validation
#
# The point of the module.  A profile that has not been checked against a
# published series is a fabrication that happens to be shaped like data, and
# the check is cheap: sum the fleet, scale by capacity, and compare with what
# EirGrid says the island's wind actually did.
# --------------------------------------------------------------------------- #

def fleet_wind(profile: pd.DataFrame, site_frame: pd.DataFrame) -> pd.Series:
    """The modelled all-island wind output in MW, capacity-weighted."""
    wind = site_frame[(site_frame["carrier"] == "wind")
                      & (site_frame["cell"] != "")]
    columns = [g for g in wind["generator"] if g in profile.columns]
    capacity = wind.set_index("generator").loc[columns, "p_nom"]
    return (profile[columns] * capacity).sum(axis=1)


def validate_wind(profile: pd.DataFrame, site_frame: pd.DataFrame,
                  actual: pd.Series) -> dict:
    """Modelled fleet wind against EirGrid's published actuals.

    Reports the correlation and the mean absolute error, both in MW and as a
    percentage of the modelled fleet capacity, and the load factors either
    side.  What each number is telling you:

    ``correlation``
        whether the *timing* is right - whether the calms and the storms are
        in the same hours.  This is what ERA5 buys and what a random walk
        cannot have.  Below about 0.85 something is wrong with the site set
        or the coordinates, not with the power curve.
    ``bias`` and the two load factors
        whether the *level* is right.  A correlation of 0.95 with a load
        factor 10 points high means the power curve or the availability
        factor is wrong, and both are parameters of this module.
    ``mae_pct_of_capacity``
        the headline error, in units that mean something.
    """
    modelled = fleet_wind(profile, site_frame)
    actual = pd.Series(actual).astype(float)
    both = pd.DataFrame({"modelled": modelled, "actual": actual}).dropna()
    if len(both) < 24:
        raise Unavailable(
            f"only {len(both)} overlapping hours between the modelled series "
            "and EirGrid's; there is nothing to validate against")
    capacity = float(site_frame.loc[site_frame["carrier"] == "wind",
                                    "p_nom"].sum())
    error = both["modelled"] - both["actual"]
    return {
        "hours": int(len(both)),
        "modelled_capacity_mw": capacity,
        "correlation": float(both["modelled"].corr(both["actual"])),
        "r2": float(both["modelled"].corr(both["actual"]) ** 2),
        "mae_mw": float(error.abs().mean()),
        "mae_pct_of_capacity": float(error.abs().mean() / capacity * 100.0),
        "bias_mw": float(error.mean()),
        "rmse_mw": float(np.sqrt((error ** 2).mean())),
        "modelled_load_factor": float(both["modelled"].mean() / capacity),
        "actual_load_factor": float(both["actual"].mean() / capacity),
        "modelled_mean_mw": float(both["modelled"].mean()),
        "actual_mean_mw": float(both["actual"].mean()),
    }


def calibrate(profile_inputs, actual: pd.Series,
              spreads=(0.5, 1.0, 1.5, 2.0, 2.5),
              availabilities=(0.80, 0.85, 0.90, 0.95, 1.00)) -> pd.DataFrame:
    """What the validation says the two free parameters should be.

    ``profile_inputs`` is a callable taking ``(spread, availability)`` and
    returning the modelled fleet series, so the sweep can be run without
    re-reading the weather each time.  The result is every combination with
    its correlation and error; the correlation barely moves with either
    parameter and the bias moves a great deal, which is the point - the
    timing comes from ERA5 and only the level is being fitted.
    """
    rows = []
    for spread in spreads:
        for availability in availabilities:
            modelled = profile_inputs(spread, availability)
            both = pd.DataFrame({"m": modelled, "a": actual}).dropna()
            error = both["m"] - both["a"]
            rows.append({"spread": spread, "availability": availability,
                         "correlation": float(both["m"].corr(both["a"])),
                         "mae_mw": float(error.abs().mean()),
                         "bias_mw": float(error.mean())})
    return pd.DataFrame(rows).sort_values("mae_mw").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

DEFAULT_CASE = "data/TYTFS2024_studyfiles/TYTFS2024_WP2033_V35.raw"


def _case(path: str) -> psse.Case:
    return psse.read_raw(path)


def run_sites(path: str) -> None:
    case = _case(path)
    frame = sites(case)
    grid = cells(frame)
    print(f"{case.name}: {len(frame)} wind and solar generator records, "
          f"{frame['p_nom'].sum():,.0f} MW")
    print(frame.groupby("carrier").agg(
        records=("p_nom", "size"), mw=("p_nom", "sum"),
        placed=("cell", lambda s: (s != "").sum())).round(1).to_string())
    missing = unplaced(frame)
    print(f"\n{len(grid)} distinct {CELL}-degree cells to request "
          f"-> {math.ceil(len(grid) / BATCH)} requests per year")
    print(f"{len(missing)} records have no coordinate "
          f"({missing['p_nom'].sum():,.0f} MW) and get no profile")
    if len(missing):
        print(missing.groupby("psse_bus_name")["p_nom"].sum()
              .sort_values(ascending=False).head(10).round(1).to_string())


def run_fetch(path: str, year: int, model: str) -> int:
    case = _case(path)
    grid = cells(sites(case))
    print(f"{len(grid)} cells; "
          f"{sum(cached(c.cell, year, model) for c in grid.itertuples())} "
          "already cached")
    report = fetch(grid, year, model)
    print(f"requested {report['requested']} cells in {report['requests']} "
          f"requests; {report['cached']} were already on disk")
    return 0


def run_build(path: str, year: int, model: str, out: str,
              hub_height: float, spread: float, availability: float) -> int:
    case = _case(path)
    frame = sites(case)
    profile = p_max_pu(frame, year, model, hub_height=hub_height,
                       spread=spread, availability=availability)
    os.makedirs(out, exist_ok=True)
    stem = os.path.join(out, f"{case.name}_{year}")
    profile.to_csv(f"{stem}_p_max_pu.csv")
    frame.to_csv(f"{stem}_sites.csv", index=False)
    summary = pd.DataFrame({
        "carrier": frame.set_index("generator").loc[
            profile.columns, "carrier"].values,
        "p_nom": frame.set_index("generator").loc[
            profile.columns, "p_nom"].values,
        "load_factor": profile.mean().values,
    }, index=profile.columns)
    summary.to_csv(f"{stem}_load_factors.csv")
    print(f"{profile.shape[0]} hours x {profile.shape[1]} generators "
          f"-> {stem}_p_max_pu.csv")
    print(summary.groupby("carrier").apply(
        lambda d: pd.Series({
            "generators": len(d), "mw": d["p_nom"].sum(),
            "capacity_weighted_load_factor":
                float((d["load_factor"] * d["p_nom"]).sum()
                      / d["p_nom"].sum())}),
        include_groups=False).round(3).to_string())
    return 0


def run_validate(path: str, year: int, model: str, actual: str,
                 hub_height: float, spread: float,
                 availability: float) -> int:
    case = _case(path)
    frame = sites(case)
    profile = p_max_pu(frame, year, model, hub_height=hub_height,
                       spread=spread, availability=availability)
    series = to_hourly(read_eirgrid(actual))
    result = validate_wind(profile, frame, series)
    width = max(len(k) for k in result)
    for key, value in result.items():
        print(f"  {key:<{width}}  "
              + (f"{value:,.4f}" if isinstance(value, float) else str(value)))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("sites", "fetch", "build", "validate"):
        s = sub.add_parser(cmd)
        s.add_argument("path", nargs="?", default=DEFAULT_CASE)
        if cmd != "sites":
            s.add_argument("--year", type=int, required=True)
            s.add_argument("--model", choices=MODELS, default=MODELS[0])
        if cmd in ("build", "validate"):
            s.add_argument("--hub-height", type=float,
                           default=DEFAULT_HUB_HEIGHT)
            s.add_argument("--spread", type=float, default=FARM_SPREAD)
            s.add_argument("--availability", type=float,
                           default=WIND_AVAILABILITY)
        if cmd == "build":
            s.add_argument("--out", default=OUTPUT_DIR)
        if cmd == "validate":
            s.add_argument("--actual", required=True,
                           help="EirGrid wind generation, CSV or JSON")
    args = p.parse_args(argv)

    if args.cmd == "sites":
        run_sites(args.path)
        return 0
    if args.cmd == "fetch":
        return run_fetch(args.path, args.year, args.model)
    if args.cmd == "build":
        return run_build(args.path, args.year, args.model, args.out,
                         args.hub_height, args.spread, args.availability)
    return run_validate(args.path, args.year, args.model, args.actual,
                        args.hub_height, args.spread, args.availability)


if __name__ == "__main__":
    raise SystemExit(main())
