"""Synthetic hourly profiles for the TYTFS fleet, anchored on the real cases.

Why this exists alongside profiles.py
-------------------------------------
Two reasons, and they are different.

**Insurance.**  :mod:`profiles` needs Open-Meteo and EirGrid, and a sandbox can
be cut off from both.  This module needs nothing but the case file.

**Counterfactuals.**  A reanalysis year is one year that happened.  A study of
what a 2033 build-out does under a *worse* wind year, or a higher-penetration
scenario, or 20% demand growth, is asking about a year that did not happen,
and no historical archive contains it.

What it does not do is replace ERA5.  A synthetic year has the right
statistics because it was built to; a reanalysis year has them because the
atmosphere had them.  Where both are available, use ERA5 and use this to
perturb it.  ``docs/SYNTHETIC_DATA.md`` is the line between what is real here
and what is fabricated, and it is worth reading before any number from this
module leaves the building.

The one detail that matters
---------------------------
**Wind is a spatially correlated field, not independent noise per bus.**
Independent noise makes the fleet's aggregate output far too smooth - the
central limit theorem flattens 400 independent sites into a nearly constant
series - and it destroys the only thing a dispatch-down study is about.  Real
calms and real storm fronts are hundreds of kilometres across, so Donegal's
farms are at rated output in the same hours and at zero in the same hours, and
*that* is what loads the Letterkenny-Strabane tie.

So the wind here is a Gaussian random field with an exponential spatial
correlation, ``rho(d) = exp(-d / L)`` with ``L = 400 km``, driven through a
temporally correlated process with a synoptic timescale of 36 hours, mapped
onto a Weibull wind speed by a Gaussian copula, and then put through **the
same power curve as** :mod:`profiles`.  The two paths differ only in where the
wind speed came from, which is what makes them comparable.

Anchoring on TYTFS
------------------
The four cases are two conditions: WP is a winter-peak weekday evening, SV is
a summer-valley night.  The generated year is made to pass through them:
demand is scaled so its annual maximum and minimum are the WP and SV totals,
and the fleet capacity factors are tapered onto the case's own values in a
window around each anchor hour.  Everywhere else the weather is free, which is
the point - a winter peak with the wind switched out is a security assumption,
not a climatology, and a year in which every cold evening is calm would be a
worse lie than the one this module is replacing.

Usage
-----
    python synthetic.py build --case <raw> --year 2030 --seed 42
    python synthetic.py check --case <raw>       # correlation vs distance
    python synthetic.py binding --case <raw>     # does WP2033 actually bind?
"""

from __future__ import annotations

import argparse
import glob
import math
import os

import numpy as np
import pandas as pd

import profiles
import psse
import pypsa_net

# --------------------------------------------------------------------------- #
# The constants that make it a field rather than noise
# --------------------------------------------------------------------------- #

#: The methodology's seed convention, from nodes_24hr.xlsx's own README.
SEED = 42

#: Wind's spatial correlation length, km.  ``rho(d) = exp(-d / L)``.  A
#: synoptic system over Ireland is comparable with the island itself, so at
#: 400 km the far ends of the country - Malin Head to Mizen, about 450 km -
#: still correlate at about 0.32, and two farms 40 km apart at 0.90.  That is
#: the shape the aggregate depends on: too short and the fleet smooths into a
#: constant, too long and every site becomes the same site.
WIND_CORRELATION_KM = 400.0

#: How long a weather pattern lasts, hours.  The lag-1 autocorrelation of the
#: driving process is exp(-1 / 36) = 0.973, so a calm takes days to clear,
#: which is what makes a *duration* curve rather than a histogram.
WIND_TIMESCALE_H = 36.0

#: Cloud is a smaller, faster thing than a depression.
CLOUD_CORRELATION_KM = 150.0
CLOUD_TIMESCALE_H = 6.0

#: Temperature is the largest and slowest field of the three.
TEMPERATURE_CORRELATION_KM = 600.0
TEMPERATURE_TIMESCALE_H = 72.0

#: Weibull shape for hourly wind speed.  k = 2 is the Rayleigh case and is the
#: usual first approximation for a temperate maritime site.
WEIBULL_K = 2.0

#: The fleet-mean annual load factor the wind scale is solved for.  Ireland's
#: published onshore figure sits in the high twenties to low thirties; the
#: scale is fitted to this rather than assumed, and it is a parameter.
TARGET_WIND_LOAD_FACTOR = 0.30

#: Wind is stronger in winter.  A multiplier on the Weibull scale, peaking on
#: 1 January and troughing on 1 July.
WIND_SEASONAL_AMPLITUDE = 0.22

#: Hours either side of an anchor over which the case's own state is blended
#: in.  Wide enough not to be a spike, narrow enough to leave the year alone.
ANCHOR_WINDOW_H = 18

#: The two conditions the four cases represent, as (month, day, hour) in the
#: generated year.  WP is a winter weekday evening peak, SV a summer night.
ANCHOR_POINTS = {"WP": (1, 17, 18), "SV": (7, 9, 5)}


# --------------------------------------------------------------------------- #
# Anchors, read from the cases
# --------------------------------------------------------------------------- #

def case_state(case: psse.Case) -> dict:
    """The condition one TYTFS case represents, as capacity factors.

    Everything here is read from the file: the demand is its in-service ``PL``
    total, and each carrier's factor is its dispatched ``PG`` over its register
    ``PT``.  Nothing is chosen.
    """
    name = pypsa_net._clean(case.bus.set_index("I")["NAME"])
    gen = case.generator.copy()
    gen["carrier"] = [pypsa_net.carrier_of(name.get(int(i), ""))
                      for i in gen["I"]]
    label = case.name.split("_")[1] if "_" in case.name else case.name
    state = {"case": case.name,
             "condition": label[:2],
             "vintage": label[2:],
             "demand_mw": float(psse.loads(case)["PL"].sum()),
             "dispatch_mw": float(gen.loc[gen["STAT"] == 1, "PG"].sum()),
             "register_mw": float(gen["PT"].sum())}
    state["headroom"] = 1.0 - state["dispatch_mw"] / state["register_mw"]
    for carrier in ("wind", "solar", "hydro"):
        here = gen[gen["carrier"] == carrier]
        capacity = float(here["PT"].sum())
        running = float(here.loc[here["STAT"] == 1, "PG"].sum())
        state[f"{carrier}_capacity_mw"] = capacity
        state[f"{carrier}_cf"] = running / capacity if capacity else 0.0
    return state


def anchors(pattern: str = "data/TYTFS2024_studyfiles/*_V35.raw"
            ) -> pd.DataFrame:
    """One row per case, with the state the generated year is pinned to."""
    return pd.DataFrame([case_state(c)
                         for c in (psse.read_raw(p)
                                   for p in sorted(glob.glob(pattern)))])


def vintage_pair(states: pd.DataFrame, case: psse.Case
                 ) -> tuple[pd.Series, pd.Series]:
    """The winter-peak and summer-valley cases of one scenario vintage.

    A generated year belongs to a scenario, not to the whole set: WP2024's
    year should span WP2024's peak and SV2024's valley, and WP2033's should
    span the 2033 pair.  Taking the peak from whichever case happens to be
    largest would put 2033's demand into 2024's year.
    """
    mine = states[states["case"] == case.name]
    vintage = mine["vintage"].iloc[0] if len(mine) else ""
    family = states[states["vintage"] == vintage]
    if family.empty:
        family = states
    winter = family[family["condition"] == "WP"]
    summer = family[family["condition"] == "SV"]
    return (winter.iloc[0] if len(winter) else states.iloc[0],
            summer.iloc[0] if len(summer) else states.iloc[0])


def anchor_index(index: pd.DatetimeIndex, condition: str) -> pd.Timestamp:
    """The hour of the generated year that stands for a case's condition."""
    month, day, hour = ANCHOR_POINTS[condition]
    year = int(index[0].year)
    stamp = pd.Timestamp(year=year, month=month, day=day, hour=hour)
    return index[index.get_indexer([stamp], method="nearest")[0]]


def taper(index: pd.DatetimeIndex, centre: pd.Timestamp,
          window: int = ANCHOR_WINDOW_H) -> np.ndarray:
    """A raised-cosine window, 1 at the anchor and 0 by ``window`` hours out."""
    hours = (index - centre).total_seconds().to_numpy() / 3600.0
    weight = np.where(np.abs(hours) < window,
                      0.5 * (1.0 + np.cos(math.pi * hours / window)), 0.0)
    return weight


# --------------------------------------------------------------------------- #
# The fields
# --------------------------------------------------------------------------- #

def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km, vectorised over the last axis."""
    r, p = 6371.0088, math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = (np.sin(dlat / 2) ** 2
         + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin(dlon / 2) ** 2)
    return 2 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def distance_matrix(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Pairwise great-circle distances, km."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])


def correlation_matrix(distance: np.ndarray, length: float,
                       nugget: float = 0.02) -> np.ndarray:
    """``rho(d) = (1 - nugget) * exp(-d / L)``, with 1 on the diagonal.

    The nugget is the part of a site's variability that is genuinely its own -
    terrain, turbulence, a passing shower - and it is small on purpose.  It is
    also what keeps the matrix positive definite when two sites sit in the
    same place, which happens whenever two farms share a substation.
    """
    rho = (1.0 - nugget) * np.exp(-distance / length)
    np.fill_diagonal(rho, 1.0)
    return rho


def _chol(rho: np.ndarray) -> np.ndarray:
    """Cholesky factor, with a jitter ladder for a near-singular matrix."""
    for jitter in (0.0, 1e-10, 1e-8, 1e-6, 1e-4):
        try:
            return np.linalg.cholesky(rho + jitter * np.eye(len(rho)))
        except np.linalg.LinAlgError:
            continue
    values, vectors = np.linalg.eigh(rho)
    return vectors * np.sqrt(np.clip(values, 1e-12, None))


def gaussian_field(hours: int, rho: np.ndarray, timescale: float,
                   rng: np.random.Generator) -> np.ndarray:
    """A spatially correlated, temporally persistent standard normal field.

    Shape ``(hours, sites)``.  Built as an Ornstein-Uhlenbeck process in time,
    one per site, driven by innovations that are correlated in space by the
    Cholesky factor of ``rho``.  The result has unit variance at every site
    and the requested correlation between every pair, at every hour - which is
    the property the whole module turns on.
    """
    factor = _chol(rho)
    phi = math.exp(-1.0 / timescale)
    innovation = math.sqrt(1.0 - phi ** 2)
    white = rng.standard_normal((hours, len(rho))) @ factor.T
    field = np.empty_like(white)
    field[0] = white[0]
    for t in range(1, hours):
        field[t] = phi * field[t - 1] + innovation * white[t]
    return field


def _seasonal(index: pd.DatetimeIndex, amplitude: float,
              peak_day: int = 1) -> np.ndarray:
    """A sinusoid over the year, 1 + amplitude at ``peak_day``."""
    day = index.dayofyear.to_numpy(dtype=float)
    return 1.0 + amplitude * np.cos(2 * math.pi * (day - peak_day) / 365.25)


def weibull_from_normal(z: np.ndarray, scale: np.ndarray | float,
                        k: float = WEIBULL_K) -> np.ndarray:
    """Gaussian copula: standard normal to Weibull, preserving rank order.

    The spatial correlation is imposed on the normal field and carried through
    this monotone map, so the wind speeds are correlated too - a little less
    than the normals, which is the usual and correct consequence of a copula
    transform.
    """
    from scipy.special import ndtr

    u = np.clip(ndtr(z), 1e-12, 1.0 - 1e-12)
    return scale * (-np.log1p(-u)) ** (1.0 / k)


def wind_speed_field(site_frame: pd.DataFrame, index: pd.DatetimeIndex,
                     rng: np.random.Generator,
                     correlation_km: float = WIND_CORRELATION_KM,
                     timescale: float = WIND_TIMESCALE_H,
                     scale: float | np.ndarray = 9.0,
                     seasonal: float = WIND_SEASONAL_AMPLITUDE
                     ) -> pd.DataFrame:
    """Hourly 100 m wind speed at every site, m/s."""
    rho = correlation_matrix(
        distance_matrix(site_frame["lat"].to_numpy(),
                        site_frame["lon"].to_numpy()), correlation_km)
    z = gaussian_field(len(index), rho, timescale, rng)
    seasonal_factor = _seasonal(index, seasonal)[:, None]
    speed = weibull_from_normal(z, scale) * seasonal_factor
    return pd.DataFrame(speed, index=index,
                        columns=site_frame["cell"].to_numpy())


def clearness_field(site_frame: pd.DataFrame, index: pd.DatetimeIndex,
                    rng: np.random.Generator) -> pd.DataFrame:
    """The hourly clearness index at every site, in (0.03, 0.78).

    Cloud is a smaller and faster field than a depression, so it gets its own
    correlation length and timescale.  The mapping from the normal field is a
    logistic, which gives the bimodal look real clearness has - mostly overcast
    or mostly clear, comparatively little in between - without needing a
    mixture model.
    """
    rho = correlation_matrix(
        distance_matrix(site_frame["lat"].to_numpy(),
                        site_frame["lon"].to_numpy()), CLOUD_CORRELATION_KM)
    z = gaussian_field(len(index), rho, CLOUD_TIMESCALE_H, rng)
    # Irish annual mean clearness is around 0.4; the logistic is centred to
    # give that and clipped to the physical range.
    kt = 0.03 + 0.75 / (1.0 + np.exp(-(z * 1.1 - 0.45)))
    return pd.DataFrame(kt, index=index, columns=site_frame["cell"].to_numpy())


def temperature_field(site_frame: pd.DataFrame, index: pd.DatetimeIndex,
                      rng: np.random.Generator, mean: float = 9.8,
                      seasonal: float = 6.0, diurnal: float = 3.0,
                      noise: float = 2.5) -> pd.DataFrame:
    """Hourly 2 m temperature, degrees C.

    Ireland's annual mean is close to 10 C with a small seasonal range for the
    latitude, which is the maritime climate.  Only the panel temperature
    derating uses this, so it does not need to be more than plausible.
    """
    rho = correlation_matrix(
        distance_matrix(site_frame["lat"].to_numpy(),
                        site_frame["lon"].to_numpy()),
        TEMPERATURE_CORRELATION_KM)
    z = gaussian_field(len(index), rho, TEMPERATURE_TIMESCALE_H, rng)
    day = index.dayofyear.to_numpy(dtype=float)
    hour = index.hour.to_numpy(dtype=float)
    shape = (mean
             - seasonal * np.cos(2 * math.pi * (day - 15) / 365.25)
             - diurnal * np.cos(2 * math.pi * (hour - 15) / 24.0))
    return pd.DataFrame(shape[:, None] + noise * z, index=index,
                        columns=site_frame["cell"].to_numpy())


def _erbs(kt: np.ndarray) -> np.ndarray:
    """Diffuse fraction from the clearness index - the Erbs correlation.

    The standard piecewise fit, and the reason the module can produce a DNI at
    all: ERA5 gives one and a clearness index does not.
    """
    kt = np.asarray(kt, dtype=float)
    out = np.where(
        kt <= 0.22,
        1.0 - 0.09 * kt,
        np.where(kt <= 0.80,
                 0.9511 - 0.1604 * kt + 4.388 * kt ** 2
                 - 16.638 * kt ** 3 + 12.336 * kt ** 4,
                 0.165))
    return np.clip(out, 0.0, 1.0)


def weather(site_frame: pd.DataFrame, index: pd.DatetimeIndex,
            rng: np.random.Generator, wind_scale: float | np.ndarray = 9.0
            ) -> dict[str, pd.DataFrame]:
    """Synthetic ERA5, cell by cell, in exactly the columns ERA5 comes in.

    The point of returning this shape is that it goes straight through
    :func:`profiles.wind_capacity_factor` and
    :func:`profiles.solar_capacity_factor` unchanged.  The synthetic and the
    reanalysis paths then differ in one place only - where the weather came
    from - and any comparison between them is a comparison of the weather and
    not of two different power curves.
    """
    speed = wind_speed_field(site_frame, index, rng, scale=wind_scale)
    kt = clearness_field(site_frame, index, rng)
    temperature = temperature_field(site_frame, index, rng)

    out = {}
    for position, cell in enumerate(site_frame["cell"]):
        lat = float(site_frame["lat"].iloc[position])
        lon = float(site_frame["lon"].iloc[position])
        zenith, _ = profiles.solar_position(index, lat, lon)
        cos_zenith = np.clip(np.cos(np.radians(zenith)), 0.0, None)
        # Extraterrestrial normal irradiance, with the earth-sun distance.
        day = index.dayofyear.to_numpy(dtype=float)
        e0 = 1367.0 * (1.0 + 0.033 * np.cos(2 * math.pi * day / 365.25))
        ghi = kt[cell].to_numpy() * e0 * cos_zenith
        diffuse = _erbs(kt[cell].to_numpy())
        with np.errstate(divide="ignore", invalid="ignore"):
            dni = np.where(cos_zenith > 0.01,
                           ghi * (1.0 - diffuse) / cos_zenith, 0.0)
        out[cell] = pd.DataFrame({
            "wind_speed_100m": speed[cell].to_numpy(),
            # A 100 m to 10 m ratio consistent with a shear exponent of 0.16,
            # so profiles.shear_exponent recovers that and a hub-height
            # correction behaves the same way as it does on ERA5.
            "wind_speed_10m": speed[cell].to_numpy() / 10.0 ** 0.16,
            "shortwave_radiation": np.maximum(ghi, 0.0),
            "direct_normal_irradiance": np.clip(dni, 0.0, 1100.0),
            "temperature_2m": temperature[cell].to_numpy(),
        }, index=index)
    return out


# --------------------------------------------------------------------------- #
# Demand
# --------------------------------------------------------------------------- #

#: The winter-weekday shape, hour by hour, before any scaling: an overnight
#: trough, a morning ramp, a midday plateau and a sharp evening peak at 17:30
#: to 18:30.  Normalised so the peak hour is 1.0.
WEEKDAY_SHAPE = np.array([
    0.72, 0.69, 0.67, 0.66, 0.66, 0.68,      # 00-05 overnight trough
    0.74, 0.83, 0.90, 0.92, 0.92, 0.91,      # 06-11 morning ramp
    0.90, 0.89, 0.88, 0.89, 0.94, 1.00,      # 12-17 midday, evening rise
    1.00, 0.96, 0.91, 0.86, 0.81, 0.76,      # 18-23 evening peak and fall
])

#: Saturdays and Sundays are lower and flatter, and the evening peak is later
#: and softer.
WEEKEND_FACTOR = 0.88

#: Demand's seasonal swing.  Solved against the cases rather than assumed -
#: see demand_series, which scales the whole year so its maximum and minimum
#: are the WP and SV totals.
DEMAND_SEASONAL_AMPLITUDE = 0.20

#: Day-to-day variation that is not the calendar: weather, holidays, industry.
DEMAND_NOISE = 0.03


def demand_series(index: pd.DatetimeIndex, peak_mw: float, trough_mw: float,
                  rng: np.random.Generator,
                  seasonal: float = DEMAND_SEASONAL_AMPLITUDE,
                  noise: float = DEMAND_NOISE,
                  peak_at: pd.Timestamp | None = None,
                  trough_at: pd.Timestamp | None = None) -> pd.Series:
    """All-island demand for the year, in MW, pinned to the two cases.

    The shape is the winter weekday above, modulated by a seasonal sinusoid, a
    weekend factor and a small AR(1) day-to-day wobble.  It is then affinely
    rescaled so that its **annual maximum is the winter-peak case's demand and
    its annual minimum is the summer-valley case's**, which is the sense in
    which the year passes through the TYTFS states.

    ``peak_at`` and ``trough_at`` put those two extremes on the anchor hours
    rather than wherever the noise happened to leave them, so that the
    snapshot the case describes is the snapshot the year reproduces.
    """
    hour = index.hour.to_numpy()
    shape = WEEKDAY_SHAPE[hour]
    weekend = index.dayofweek.to_numpy() >= 5
    shape = np.where(weekend, shape * WEEKEND_FACTOR, shape)
    shape = shape * _seasonal(index, seasonal)

    days = int(np.ceil(len(index) / 24)) + 1
    wobble = np.empty(days)
    wobble[0] = rng.normal()
    for d in range(1, days):
        wobble[d] = 0.7 * wobble[d - 1] + math.sqrt(1 - 0.49) * rng.normal()
    daily = np.repeat(wobble, 24)[:len(index)]
    shape = shape * (1.0 + noise * daily)

    # Put the extremes on the anchors.  Nudged rather than replaced, so the
    # surrounding hours still slope into them.
    frame = pd.Series(shape, index=index)
    if peak_at is not None:
        frame = _apply_anchor(frame, index, peak_at,
                              float(frame.max()) * 1.02)
    if trough_at is not None:
        frame = _apply_anchor(frame, index, trough_at,
                              float(frame.min()) * 0.98)
    shape = frame.to_numpy()

    low, high = float(shape.min()), float(shape.max())
    scaled = trough_mw + (shape - low) * (peak_mw - trough_mw) / (high - low)
    series = pd.Series(scaled, index=index, name="demand_mw")
    series.index.name = "snapshot"
    return series


# --------------------------------------------------------------------------- #
# The dispatchable carriers
# --------------------------------------------------------------------------- #

def hydro_profile(index: pd.DatetimeIndex, winter_cf: float,
                  summer_cf: float, evening_boost: float = 0.25
                  ) -> pd.Series:
    """Steady seasonal baseload with an evening boost.

    Irish hydro is run-of-river and small reservoir: the seasonal swing is
    the catchment's, and the daily swing is the operator's, holding water for
    the evening peak.  The two levels come from the cases - WP2024 has its
    hydro at 0.94 of capacity and SV2024 at 0.00 - and the boost is a shape,
    not a measurement.
    """
    day = index.dayofyear.to_numpy(dtype=float)
    season = 0.5 * (1.0 + np.cos(2 * math.pi * (day - 15) / 365.25))
    base = summer_cf + (winter_cf - summer_cf) * season
    hour = index.hour.to_numpy()
    evening = np.isin(hour, (17, 18, 19, 20))
    profile = base * np.where(evening, 1.0 + evening_boost, 1.0)
    return pd.Series(np.clip(profile, 0.0, 1.0), index=index, name="hydro")


def thermal_profile(demand: pd.Series, wind_fleet_cf: pd.Series,
                    floor: float = 0.15, ceiling: float = 1.0) -> pd.Series:
    """Dispatchable: rises with demand and is backed off when wind is high.

    A residual-load shape, normalised to [floor, ceiling].  This is an
    **availability envelope**, not a dispatch: in an optimisation the solver
    decides, and a study running LOPF should probably set thermal
    ``p_max_pu`` to 1 and let it.  It is here because the brief asks for it and
    because a merit-order-shaped envelope is a reasonable stand-in for a
    scenario where thermal plant is committed ahead of the day.
    """
    residual = (demand / demand.max()) - 0.6 * wind_fleet_cf.reindex(
        demand.index).fillna(0.0)
    low, high = float(residual.min()), float(residual.max())
    scaled = floor + (residual - low) * (ceiling - floor) / (high - low)
    return pd.Series(np.clip(scaled, 0.0, 1.0), index=demand.index,
                     name="thermal")


# --------------------------------------------------------------------------- #
# Building a year
# --------------------------------------------------------------------------- #

def _scale_for_load_factor(target: float, hub_height: float, spread: float,
                           availability: float, rng: np.random.Generator,
                           seasonal: float = WIND_SEASONAL_AMPLITUDE) -> float:
    """The Weibull scale, in m/s, whose fleet load factor is ``target``.

    Solved by bisection against the same power curve the profiles use, rather
    than picked, so that changing the curve changes the scale and the target
    load factor stays the target.
    """
    hours = 8760
    index = pd.date_range("2030-01-01", periods=hours, freq="1h")
    z = rng.standard_normal(hours)
    season = _seasonal(index, seasonal)

    def factor(scale: float) -> float:
        speed = weibull_from_normal(z, scale) * season
        frame = pd.DataFrame({
            "wind_speed_100m": speed,
            "wind_speed_10m": speed / 10.0 ** 0.16,
        }, index=index)
        return float(profiles.wind_capacity_factor(
            frame, hub_height, spread, availability).mean())

    low, high = 1.0, 25.0
    for _ in range(60):
        middle = 0.5 * (low + high)
        if factor(middle) < target:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def _apply_anchor(series: pd.Series, index: pd.DatetimeIndex,
                  centre: pd.Timestamp, target: float,
                  window: int = ANCHOR_WINDOW_H) -> pd.Series:
    """Blend a series onto ``target`` at ``centre``, tapering to nothing.

    A raised-cosine blend rather than a substitution, so the anchor hour hits
    the case's value exactly and the hours either side move smoothly towards
    it and back.  The rest of the year is untouched.
    """
    weight = taper(index, centre, window)
    return pd.Series(series.to_numpy() * (1.0 - weight) + target * weight,
                     index=index, name=series.name)


def build(case: psse.Case, year: int = 2030, seed: int = SEED,
          hub_height: float = profiles.DEFAULT_HUB_HEIGHT,
          spread: float = profiles.FARM_SPREAD,
          availability: float = profiles.WIND_AVAILABILITY,
          target_load_factor: float = TARGET_WIND_LOAD_FACTOR,
          anchor_frame: pd.DataFrame | None = None) -> dict:
    """A synthetic year for one case: ``p_max_pu``, demand, and the workings.

    Returns a dict with

    ``p_max_pu``    wide, snapshot index, one column per generator, in [0, 1]
    ``demand``      all-island MW by snapshot
    ``loads``       that demand allocated over the case's load records
    ``sites``       every generator, its cell and coordinate
    ``fleet``       the fleet capacity factor of each carrier, for checking
    ``anchors``     where in the year each case's state was pinned
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="1h")

    frame = profiles.sites(case, carriers=("wind", "solar", "hydro", "gas",
                                           "biomass", "unknown"))
    placed = frame[frame["cell"] != ""].copy()
    cells = placed.drop_duplicates("cell")[["cell", "lat", "lon"]] \
        .reset_index(drop=True)

    scale = _scale_for_load_factor(target_load_factor, hub_height, spread,
                                   availability,
                                   np.random.default_rng(seed + 1))
    fields = weather(cells, index, rng, wind_scale=scale)

    wind_cf = {c: profiles.wind_capacity_factor(fields[c], hub_height, spread,
                                                availability)
               for c in cells["cell"]}
    solar_cf = {}
    for row in cells.itertuples():
        solar_cf[row.cell] = profiles.solar_capacity_factor(
            fields[row.cell], row.lat, row.lon)

    states = anchor_frame if anchor_frame is not None else anchors()
    placement = {}
    for _, state in states.iterrows():
        centre = anchor_index(index, state["condition"])
        placement[state["case"]] = centre

    # Pin the fleet capacity factors onto this case's own state.  Only this
    # case's condition is pinned in its own year; the other cases' anchors are
    # reported so a scenario built from several of them lines up.
    mine = states[states["case"] == case.name]
    anchor_notes = []
    if len(mine):
        state = mine.iloc[0]
        centre = placement[case.name]
        for carrier, table in (("wind", wind_cf), ("solar", solar_cf)):
            members = placed[placed["carrier"] == carrier]
            if not len(members) or not state[f"{carrier}_capacity_mw"]:
                continue
            weights = members.groupby("cell")["p_nom"].sum()
            weights = weights / weights.sum()
            fleet = sum(table[c] * w for c, w in weights.items())
            target = float(state[f"{carrier}_cf"])
            natural = float(fleet.loc[centre])
            if target > 1e-9 and natural <= 1e-9:
                # The case asks for output the sky cannot give at that hour.
                # WP2033 dispatches 373 MW of solar at a winter-peak evening;
                # at 18:00 in January the sun is well down.  A TYTFS case is a
                # security state, not a timestamped instant, and forcing it
                # would put daylight in the profile at midnight.
                anchor_notes.append({
                    "case": case.name, "carrier": carrier,
                    "target_cf": target, "achievable_cf": natural,
                    "snapshot": centre,
                    "note": "not applied: the case's value is unreachable at "
                            "this hour of this date"})
                continue
            wanted = _apply_anchor(fleet, index, centre, target)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(fleet.to_numpy() > 1e-9,
                                 wanted.to_numpy() / fleet.to_numpy(), 1.0)
            for c in table:
                table[c] = pd.Series(
                    np.clip(table[c].to_numpy() * ratio, 0.0, 1.0),
                    index=index, name=carrier)
            anchor_notes.append({
                "case": case.name, "carrier": carrier, "target_cf": target,
                "achievable_cf": natural, "snapshot": centre,
                "note": "applied"})

    winter_state, summer_state = vintage_pair(states, case)
    demand = demand_series(
        index,
        peak_mw=float(winter_state["demand_mw"]),
        trough_mw=float(summer_state["demand_mw"]),
        rng=rng,
        peak_at=anchor_index(index, "WP"),
        trough_at=anchor_index(index, "SV"))

    wind_members = placed[placed["carrier"] == "wind"]
    if len(wind_members):
        weights = wind_members.groupby("cell")["p_nom"].sum()
        weights = weights / weights.sum()
        fleet_wind = sum(wind_cf[c] * w for c, w in weights.items())
    else:
        fleet_wind = pd.Series(0.0, index=index)

    hydro = hydro_profile(index, float(winter_state["hydro_cf"]),
                          float(summer_state["hydro_cf"]))
    if len(mine):
        # Hydro is dispatched rather than driven by weather, so its anchor is
        # always reachable and is applied without the check the two weather
        # carriers need.
        hydro = _apply_anchor(hydro, index, placement[case.name],
                              float(mine.iloc[0]["hydro_cf"]))
        hydro = hydro.clip(0.0, 1.0)
        hydro.name = "hydro"
    thermal = thermal_profile(demand, fleet_wind)

    columns = {}
    for site in placed.itertuples():
        if site.carrier == "wind":
            columns[site.generator] = wind_cf[site.cell]
        elif site.carrier == "solar":
            columns[site.generator] = solar_cf[site.cell]
        elif site.carrier == "hydro":
            columns[site.generator] = hydro
        else:
            columns[site.generator] = thermal
    p_max_pu = pd.DataFrame(columns, index=index)
    p_max_pu.index.name = "snapshot"

    fleet = pd.DataFrame({"demand_mw": demand, "wind": fleet_wind,
                          "hydro": hydro, "thermal": thermal})
    if len(placed[placed["carrier"] == "solar"]):
        weights = placed[placed["carrier"] == "solar"].groupby("cell")["p_nom"].sum()
        weights = weights / weights.sum()
        fleet["solar"] = sum(solar_cf[c] * w for c, w in weights.items())

    return {
        "p_max_pu": p_max_pu,
        "demand": demand,
        "loads": profiles.allocate_demand(case, demand),
        "sites": frame,
        "fleet": fleet,
        "anchors": pd.DataFrame(
            [{"case": k, "snapshot": v} for k, v in placement.items()]),
        "anchor_report": pd.DataFrame(anchor_notes),
        "wind_scale_ms": scale,
    }


# --------------------------------------------------------------------------- #
# Checking that it is a field and not noise
# --------------------------------------------------------------------------- #

def spatial_check(result: dict, bins=(0, 25, 50, 100, 150, 200, 300, 400, 600)
                  ) -> pd.DataFrame:
    """Measured wind correlation against distance, from the output itself.

    The single check that says whether this module did the one thing it exists
    to do.  If the measured correlation does not fall with distance - if it is
    flat and near zero - the profiles are independent noise and every
    dispatch-down number computed from them is wrong.
    """
    sites = result["sites"]
    placed = sites[(sites["cell"] != "") & (sites["carrier"] == "wind")]
    cells = placed.drop_duplicates("cell").reset_index(drop=True)
    profile = result["p_max_pu"]
    columns = placed.drop_duplicates("cell")["generator"].to_numpy()
    values = profile[columns].to_numpy()
    correlation = np.corrcoef(values, rowvar=False)
    distance = distance_matrix(cells["lat"].to_numpy(),
                               cells["lon"].to_numpy())

    upper = np.triu_indices(len(cells), k=1)
    d, r = distance[upper], correlation[upper]
    rows = []
    for low, high in zip(bins[:-1], bins[1:]):
        mask = (d >= low) & (d < high)
        if mask.sum():
            rows.append({"km_from": low, "km_to": high, "pairs": int(mask.sum()),
                         "measured_correlation": float(np.nanmean(r[mask])),
                         "target_correlation": float(
                             math.exp(-0.5 * (low + high)
                                      / WIND_CORRELATION_KM))})
    return pd.DataFrame(rows)


def fleet_variability(result: dict) -> dict:
    """How much the aggregate actually moves - the other half of the check.

    Independent noise across 400 sites gives a fleet series that barely leaves
    its mean.  A correlated field gives one that spends real time near zero and
    real time near capacity, and that is what a constraint study needs.
    """
    fleet = result["fleet"]["wind"]
    return {
        "mean": float(fleet.mean()),
        "std": float(fleet.std()),
        "p05": float(fleet.quantile(0.05)),
        "p95": float(fleet.quantile(0.95)),
        "hours_below_0.05": int((fleet < 0.05).sum()),
        "hours_above_0.80": int((fleet > 0.80).sum()),
        "longest_calm_hours": int(_longest_run(fleet.to_numpy() < 0.10)),
    }


def _longest_run(mask: np.ndarray) -> int:
    best = run = 0
    for value in mask:
        run = run + 1 if value else 0
        best = max(best, run)
    return best


# --------------------------------------------------------------------------- #
# Does it bind?
#
# The requirement the hackathon turns on.  WP2033 has 32.1 GW of registered
# capacity against 9.0 GW of dispatch - 72% headroom - and if the generated
# profiles do not produce hours where the network cannot take what the wind is
# offering, the central problem does not appear and the exercise is pointless.
# --------------------------------------------------------------------------- #

#: What a renewable is paid to run in the dispatch-down optimisation.  Negative
#: so the solver runs every available MW unless the network stops it, which
#: turns "what does the LOPF choose" into "what will the network take".
RENEWABLE_BID = -1.0


def binding(case: psse.Case, result: dict, top: int = 120,
            solver: str = "highs", min_kv: float = pypsa_net.TRANSMISSION_KV
            ) -> dict:
    """Run the case's network over the windiest hours and count what binds.

    Renewables are offered at a negative price and may be held back, so the
    optimisation maximises renewable output subject to the network and nothing
    else.  Dispatch-down is then available minus dispatched.  Because these
    are the windiest hours in a heavily over-built case, it is a mix of
    constraint-based (stranded behind a binding circuit) and surplus-based
    (more wind than the demand can absorb); the binding-circuit counts beside
    it are what say the network is doing some of the work.

    None of this is curtailment in the SEM/EirGrid sense - there is no SNSP
    or inertia constraint here, and no unit commitment - so nothing in this
    function reproduces EirGrid's curtailment mechanism.
    """
    model = pypsa_net.build(case, min_kv=min_kv)
    n = pypsa_net.for_optimisation(model.network)

    fleet = result["fleet"]["wind"]
    hours = fleet.sort_values(ascending=False).index[:top].sort_values()
    n.set_snapshots(pd.DatetimeIndex(hours))

    # Only wind and solar get a p_max_pu here.  Theirs is availability - the
    # weather has decided and the network can only refuse it.  Hydro and
    # thermal are dispatched, and their profiles in the output are envelopes;
    # imposing one as an upper bound on a machine that also carries a
    # must-run lower bound is how this study was infeasible the first time it
    # was run.
    profile = result["p_max_pu"]
    weather_driven = n.generators.index[
        n.generators["carrier"].isin(("wind", "solar"))]
    columns = [g for g in weather_driven if g in profile.columns]
    available = profile.loc[hours, columns]
    n.generators_t.p_max_pu = available

    loads = result["loads"]
    present = [l for l in n.loads.index if l in loads.columns]
    n.loads_t.p_set = loads.loc[hours, present]

    # A dispatch-down study, not a unit-commitment one: nothing is must-run,
    # so the only things that can stop a megawatt are the network and the
    # demand.
    n.generators["p_min_pu"] = 0.0
    cost = n.generators["marginal_cost"].copy()
    cost[columns] = RENEWABLE_BID
    n.generators["marginal_cost"] = cost.values

    status, condition = n.optimize(solver_name=solver)
    if condition != "optimal":
        return {"status": f"{status}/{condition}", "hours": len(hours)}

    dispatched = n.generators_t.p[columns]
    capacity = n.generators.loc[columns, "p_nom"]
    offered = available * capacity
    taken = dispatched.clip(lower=0.0)
    withheld = (offered - taken).clip(lower=0.0)

    flows = n.lines_t.p0.abs()
    limits = n.lines["s_nom"]
    loading = flows / limits
    tight = loading > 0.999

    return {
        "status": f"{status}/{condition}",
        "hours": int(len(hours)),
        "offered_gwh": float(offered.to_numpy().sum() / 1000.0),
        "dispatch_down_gwh": float(withheld.to_numpy().sum() / 1000.0),
        "dispatch_down_pct": float(withheld.to_numpy().sum()
                                   / max(offered.to_numpy().sum(), 1e-9)
                                   * 100.0),
        "hours_with_dispatch_down": int(
            (withheld.sum(axis=1) > 1.0).sum()),
        "hours_with_a_binding_circuit": int((tight.sum(axis=1) > 0).sum()),
        "binding_circuit_hours": int(tight.to_numpy().sum()),
        "distinct_binding_circuits": int((tight.sum(axis=0) > 0).sum()),
        "max_loading": float(loading.to_numpy().max()),
        "worst_circuits": loading.max().sort_values(
            ascending=False).head(10).round(3).to_dict(),
        "dispatch_down_by_station": withheld.sum().sort_values(
            ascending=False).head(10).round(1).to_dict(),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

DEFAULT_CASE = "data/TYTFS2024_studyfiles/TYTFS2024_WP2033_V35.raw"
OUTPUT_DIR = "data/profiles"


def run_build(path: str, year: int, seed: int, out: str) -> int:
    case = psse.read_raw(path)
    result = build(case, year=year, seed=seed)
    os.makedirs(out, exist_ok=True)
    stem = os.path.join(out, f"{case.name}_synthetic_{year}_seed{seed}")
    result["p_max_pu"].round(5).to_csv(f"{stem}_p_max_pu.csv")
    result["loads"].round(3).to_csv(f"{stem}_loads_p_set.csv")
    result["fleet"].round(5).to_csv(f"{stem}_fleet.csv")
    result["sites"].to_csv(f"{stem}_sites.csv", index=False)
    result["anchor_report"].to_csv(f"{stem}_anchors.csv", index=False)
    print(f"{result['p_max_pu'].shape[0]} hours x "
          f"{result['p_max_pu'].shape[1]} generators -> {stem}_p_max_pu.csv")
    print(f"wind Weibull scale {result['wind_scale_ms']:.2f} m/s")
    print(result["fleet"].describe().round(3).to_string())
    return 0


def run_check(path: str, year: int, seed: int) -> int:
    case = psse.read_raw(path)
    result = build(case, year=year, seed=seed)
    print("\nWind correlation against distance - the check that says whether "
          "this is a field or noise:")
    print(spatial_check(result).to_string(index=False))
    print("\nFleet variability:")
    for key, value in fleet_variability(result).items():
        print(f"  {key:<22} "
              + (f"{value:.4f}" if isinstance(value, float) else str(value)))
    print("\nAnchors:")
    print(result["anchor_report"].to_string(index=False))
    return 0


def run_binding(path: str, year: int, seed: int, top: int,
                solver: str) -> int:
    case = psse.read_raw(path)
    result = build(case, year=year, seed=seed)
    report = binding(case, result, top=top, solver=solver)
    for key, value in report.items():
        if isinstance(value, dict):
            print(f"  {key}:")
            for k, v in value.items():
                print(f"      {k:<28} {v}")
        else:
            print(f"  {key:<32} "
                  + (f"{value:,.3f}" if isinstance(value, float)
                     else str(value)))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("build", "check", "binding"):
        s = sub.add_parser(cmd)
        s.add_argument("--case", default=DEFAULT_CASE)
        s.add_argument("--year", type=int, default=2030)
        s.add_argument("--seed", type=int, default=SEED)
        if cmd == "build":
            s.add_argument("--out", default=OUTPUT_DIR)
        if cmd == "binding":
            s.add_argument("--top", type=int, default=120)
            s.add_argument("--solver", default="highs")
    args = p.parse_args(argv)
    if args.cmd == "build":
        return run_build(args.case, args.year, args.seed, args.out)
    if args.cmd == "check":
        return run_check(args.case, args.year, args.seed)
    return run_binding(args.case, args.year, args.seed, args.top, args.solver)


if __name__ == "__main__":
    raise SystemExit(main())
