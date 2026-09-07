"""Build the standalone participant kit under participant-kit/.

Build tooling, deliberately kept out of the kit itself: participants get
networks, a loader and examples, and nothing that needs a PSS/E reader, an
Overpass client or a case file to run.

    python build_kit.py

Each of the four TYTFS scenarios is written at two scopes - the whole
transmission network and the North-West 15-node region - as a PyPSA netCDF
file and as a CSV folder beside it, each carrying a 168-hour week of synthetic
profiles containing that scenario's own anchor hour.
"""

from __future__ import annotations

import logging
import os
import shutil

import numpy as np
import pandas as pd

import northwest
import profiles
import psse
import pypsa_net
import synthetic

logging.getLogger("pypsa").setLevel(logging.ERROR)

KIT = "participant-kit"
NETWORKS = os.path.join(KIT, "networks")

#: A week is enough for every example, keeps the kit small enough to clone,
#: and - chosen this way - contains the scenario's own TYTFS anchor hour, so
#: the published snapshot is one of the snapshots participants can select.
WEEK_HOURS = 168

SCOPES = ("all-island", "north-west")


def scenario_name(case: psse.Case) -> str:
    """``WP2033`` from ``TYTFS2024_WP2033_V35``."""
    return case.name.split("_")[1]


def week_around(index: pd.DatetimeIndex, anchor: pd.Timestamp) -> pd.DatetimeIndex:
    """The 168 hours centred on the anchor, clipped into the year."""
    position = int(index.get_indexer([anchor], method="nearest")[0])
    start = max(0, min(position - WEEK_HOURS // 2, len(index) - WEEK_HOURS))
    return index[start:start + WEEK_HOURS]


def _station_profiles(result: dict, network, sites: pd.DataFrame,
                      hours: pd.DatetimeIndex,
                      homes: dict[int, str] | None = None) -> pd.DataFrame:
    """Aggregate per-record profiles onto a network's own generator names.

    The all-island network's generators are the case's records and map one to
    one, so its profiles come across unchanged.

    The North-West network's are one per station and carrier - "Meentycat
    wind" - and its buses are named for stations rather than numbered, so the
    profile for one of them is the capacity-weighted mean of every record of
    that carrier whose bus lands at that station.  ``homes`` is the bus-number
    to station-name mapping that does the landing; without it there is nothing
    to join on and the region would come out with no weather at all.
    """
    profile = result["p_max_pu"]
    direct = [g for g in network.generators.index if g in profile.columns]
    if len(direct) >= max(1, len(network.generators) // 2):
        return profile.loc[hours, direct]

    placed = sites[sites["cell"] != ""].copy()
    placed = placed[placed["generator"].isin(profile.columns)]
    if homes:
        placed["station"] = [homes.get(int(b), "") if str(b).isdigit() else ""
                             for b in placed["bus"]]
    else:
        placed["station"] = placed["bus"].astype(str)

    columns = {}
    for name, generator in network.generators.iterrows():
        members = placed[placed["station"] == str(generator["bus"])]
        if "carrier" in placed.columns and generator["carrier"] in (
                "wind", "solar"):
            members = members[members["carrier"] == generator["carrier"]]
        if members.empty:
            continue
        weights = members.set_index("generator")["p_nom"]
        weights = weights / weights.sum() if weights.sum() else weights
        block = profile.loc[hours, weights.index]
        columns[name] = (block * weights).sum(axis=1)
    return pd.DataFrame(columns, index=hours)


def _coordinates(network, geocoding: pd.DataFrame, scope: str) -> None:
    """Put longitude and latitude on every bus, and say where each came from.

    Four sources, recorded in a ``coordinate_source`` column so that nobody
    has to guess which is which:

    ``geocoded``       matched to an OpenStreetMap substation (Phase 2)
    ``star point``     a three-winding transformer's star bus, placed at the
                       station its own legs reach - it is a fiction that lives
                       inside a real fence
    ``neighbour mean`` no match, placed at the mean of the buses it connects
                       to.  **For drawing only.**  ``has_coordinates`` is
                       False for these
    ``none``           nothing to interpolate from

    The column matters because PyPSA's netCDF writer turns a missing
    coordinate into zero rather than NaN, and a bus at 0 N 0 E is in the Gulf
    of Guinea - it would wreck the first plot anybody drew and look like data
    while doing it.
    """
    placed = geocoding[geocoding["lat"].notna()]
    lon = dict(zip(placed["bus"].astype(str), placed["lon"]))
    lat = dict(zip(placed["bus"].astype(str), placed["lat"]))

    #: The North-West network's buses are named for stations, so they are
    #: mapped through the region's own bus list rather than by matching text.
    by_station: dict[str, list[str]] = {}
    if scope == "north-west":
        for station in northwest.STATIONS:
            target = station.parent or station.name
            by_station.setdefault(target, []).extend(
                str(b) for b in station.buses)

    x, y, source = {}, {}, {}
    for name in network.buses.index:
        key = str(name)
        if key in lon:
            x[name], y[name], source[name] = lon[key], lat[key], "geocoded"
            continue
        members = [b for b in by_station.get(key, []) if b in lon]
        if members:
            x[name] = float(np.mean([lon[b] for b in members]))
            y[name] = float(np.mean([lat[b] for b in members]))
            source[name] = "geocoded"
            continue
        x[name] = y[name] = np.nan
        source[name] = ""

    # A star point sits inside the station its transformer legs reach.
    for _ in range(3):
        for name in network.buses.index:
            if np.isfinite(x[name]) or not str(name).startswith("star:"):
                continue
            legs = network.transformers[
                (network.transformers["bus0"] == name)
                | (network.transformers["bus1"] == name)]
            ends = (set(legs["bus0"]) | set(legs["bus1"])) - {name}
            known = [(x[e], y[e]) for e in ends
                     if e in x and np.isfinite(x[e])]
            if known:
                x[name] = float(np.mean([a for a, _ in known]))
                y[name] = float(np.mean([b for _, b in known]))
                source[name] = "star point"

    # Anything still missing is placed among its neighbours, for drawing only.
    edges = pd.concat([
        network.lines[["bus0", "bus1"]],
        network.transformers[["bus0", "bus1"]],
    ]) if len(network.transformers) else network.lines[["bus0", "bus1"]]
    neighbours: dict[str, set] = {}
    for _, e in edges.iterrows():
        neighbours.setdefault(e["bus0"], set()).add(e["bus1"])
        neighbours.setdefault(e["bus1"], set()).add(e["bus0"])
    for _ in range(6):
        for name in network.buses.index:
            if np.isfinite(x[name]):
                continue
            known = [(x[e], y[e]) for e in neighbours.get(name, ())
                     if e in x and np.isfinite(x[e])]
            if known:
                x[name] = float(np.mean([a for a, _ in known]))
                y[name] = float(np.mean([b for _, b in known]))
                source[name] = "neighbour mean"

    network.buses["x"] = [x[b] if np.isfinite(x[b]) else np.nan
                          for b in network.buses.index]
    network.buses["y"] = [y[b] if np.isfinite(y[b]) else np.nan
                          for b in network.buses.index]
    network.buses["coordinate_source"] = [source[b] or "none"
                                          for b in network.buses.index]
    network.buses["has_coordinates"] = [source[b] == "geocoded"
                                        for b in network.buses.index]
    counts = pd.Series(list(source.values())).value_counts().to_dict()
    print("    coordinates: " + ", ".join(f"{k or 'none'} {v}"
                                          for k, v in counts.items()))


#: What unserved energy costs, EUR/MWh.  A value-of-lost-load figure, far
#: above any generator's marginal cost, so shedding is always the last resort.
VOLL = 10000.0


def _add_load_shedding(network) -> None:
    """A load-shedding generator at every bus with load.

    Three reasons, and the third is the one that matters for a hackathon.

    It makes every scenario solvable.  SV2033 has one bus - 1811 CLUTTERLAND -
    whose only connections are out of service in that case, so it is an island
    with 2 MW of load and no generation, and an optimisation over it is
    infeasible however much spare capacity the rest of the island has.

    It makes the answer diagnosable.  "Infeasible" tells you nothing about
    where or how much; 6.3 MWh of shedding at one named bus tells you both.

    And it means a participant who removes the wrong line gets a number rather
    than a crash, which is the difference between a result and a dead end.
    """
    if not len(network.loads_t.p_set):
        return
    by_bus = network.loads_t.p_set.T.groupby(network.loads["bus"]).sum().T
    peak = by_bus.max()
    buses = [b for b in network.buses.index if peak.get(b, 0.0) > 0]
    if not buses:
        return
    network.add("Generator", [f"shed {b}" for b in buses], bus=buses,
                carrier="load shedding",
                p_nom=[float(peak[b]) * 1.5 for b in buses],
                marginal_cost=VOLL, p_min_pu=0.0)
    if "load shedding" not in network.carriers.index:
        network.add("Carrier", "load shedding")


def _fill_unprofiled(network, available: pd.DataFrame) -> pd.DataFrame:
    """Give every wind and solar generator a profile, borrowing if it must.

    The synthetic weather is generated at the geocoded sites, so a wind farm
    at a bus that never matched OpenStreetMap comes out of
    :func:`_station_profiles` with no column at all.  Left that way it keeps
    the static ``p_max_pu`` of 1.0 that PyPSA defaults to, and since wind bids
    at zero it then runs flat out for all 168 hours - 7.8 GW of it in WP2033,
    which is more than the island's peak demand.  The dispatch chart looks
    fine and is nonsense: a fifth of the fleet is a must-run baseload station
    that happens to be labelled "wind".

    So each one borrows the profile of the nearest generator of its own
    carrier that does have one, by great-circle distance between their buses.
    That is a real approximation and it is worth its own line in the
    limitations: the borrowed site is typically tens of kilometres away, which
    is well inside the correlation length of the wind field, but two farms
    sharing a profile are perfectly correlated when they should not be.
    """
    placed = network.buses
    missing = [g for g, row in network.generators.iterrows()
               if row["carrier"] in ("wind", "solar")
               and g not in available.columns]
    if not missing:
        return available
    filled = dict(available)
    borrowed = 0
    for name in missing:
        carrier = network.generators.at[name, "carrier"]
        donors = [g for g in available.columns
                  if g in network.generators.index
                  and network.generators.at[g, "carrier"] == carrier]
        if not donors:
            continue
        bus = network.generators.at[name, "bus"]
        distance = {g: _great_circle(placed, bus,
                                     network.generators.at[g, "bus"])
                    for g in donors}
        nearest = min(distance, key=distance.get)
        filled[name] = available[nearest]
        borrowed += 1
    if borrowed:
        print(f"    {borrowed} wind/solar generators borrowed a nearby "
              f"profile (no geocoded site of their own)")
    return pd.DataFrame(filled, index=available.index)


def _great_circle(buses: pd.DataFrame, bus0: str, bus1: str) -> float:
    """Kilometres between two buses; a large number if either is unplaced."""
    try:
        a, b = buses.loc[bus0], buses.loc[bus1]
    except KeyError:
        return 1e6
    if not all(np.isfinite([a["x"], a["y"], b["x"], b["y"]])):
        return 1e6
    radius, degree = 6371.0088, np.pi / 180.0
    dlat = (b["y"] - a["y"]) * degree
    dlon = (b["x"] - a["x"]) * degree
    h = (np.sin(dlat / 2) ** 2 + np.cos(a["y"] * degree)
         * np.cos(b["y"] * degree) * np.sin(dlon / 2) ** 2)
    return float(2 * radius * np.arcsin(np.sqrt(np.clip(h, 0, 1))))


def _split_north_west_by_carrier(case: psse.Case, network) -> None:
    """Give the North-West stations real carriers instead of one lump each.

    :func:`northwest.extract` folds every machine at a station into a single
    generator with carrier ``AC``, which is right for the reconciliation work
    it was written for - the question there was how much capacity sits at a
    station, not what kind.  For the kit it is wrong: the region is 90% wind,
    and a wind fleet that carries no carrier gets no weather profile, so it
    would sit at a flat 100% availability all week and the one thing the
    North-West case is for - dispatch-down - could not happen.

    So each station's lump is replaced by one generator per carrier, using the
    case's own machine records for the split.  Capacity, dispatch and the bus
    are preserved exactly; only the labelling gets finer.
    """
    homes = northwest._homes(case, "aggregated")
    gen = case.generator.copy()
    gen["station"] = gen["I"].astype(int).map(homes)
    gen = gen[gen["station"].notna()]
    names = dict(zip(case.bus["I"].astype(int),
                     pypsa_net._clean(case.bus["NAME"])))
    gen["carrier"] = [pypsa_net.carrier_of(names.get(int(i), ""))
                      for i in gen["I"]]

    for name in [g for g in network.generators.index
                 if network.generators.at[g, "carrier"] == "AC"]:
        station = network.generators.at[name, "bus"]
        machines = gen[gen["station"] == station]
        if machines.empty:
            continue
        network.remove("Generator", name)
        for carrier, block in machines.groupby("carrier"):
            capacity = float(block["PT"].sum())
            if capacity <= 0:
                continue
            if carrier not in network.carriers.index:
                network.add("Carrier", carrier)
            network.add(
                "Generator", f"{station} {carrier}", bus=station,
                carrier=carrier, p_nom=capacity,
                p_set=float(block.loc[block["STAT"] == 1, "PG"].sum()),
                control="PV", p_min_pu=0.0,
                marginal_cost=pypsa_net.PLACEHOLDER_COST.get(carrier, 60.0))


def build_one(case: psse.Case, scope: str, result: dict,
              geocoding: pd.DataFrame, states: pd.DataFrame):
    """One scenario at one scope, with a week of profiles attached."""
    if scope == "all-island":
        model = pypsa_net.build(case, min_kv=pypsa_net.TRANSMISSION_KV)
        network = model.network
    else:
        network, _ = northwest.extract(case, "aggregated")
        _split_north_west_by_carrier(case, network)

    anchor = synthetic.anchor_index(
        result["p_max_pu"].index,
        states.loc[states["case"] == case.name, "condition"].iloc[0])
    hours = week_around(result["p_max_pu"].index, anchor)

    network.set_snapshots(pd.DatetimeIndex(hours))
    # Coordinates first: the profile fill below needs them.
    _coordinates(network, geocoding, scope)
    homes = (northwest._homes(case, "aggregated")
             if scope == "north-west" else None)
    available = _station_profiles(result, network, result["sites"], hours,
                                  homes)
    available = _fill_unprofiled(network, available)
    # Only the weather-driven carriers get a p_max_pu.  Theirs is availability
    # and the network can only refuse it.  Hydro and thermal are dispatched,
    # and imposing an envelope on a machine that also carries a must-run
    # p_min_pu from the case is how this was infeasible the first time.
    weather_driven = [g for g in available.columns
                      if g in network.generators.index
                      and network.generators.at[g, "carrier"] in
                      ("wind", "solar")]
    if weather_driven:
        network.generators_t.p_max_pu = available[weather_driven].clip(0.0, 1.0)
        # You cannot commit a wind farm to a minimum output.
        floor = network.generators["p_min_pu"].copy()
        floor[weather_driven] = 0.0
        network.generators["p_min_pu"] = floor.values

    loads = result["loads"]
    present = [l for l in network.loads.index if l in loads.columns]
    if present:
        network.loads_t.p_set = loads.loc[hours, present]
    else:
        # The North-West network's loads are one per station; scale each by
        # the island shape so the week has demand in it.
        shape = result["demand"].loc[hours] / result["demand"].loc[anchor]
        base = network.loads["p_set"]
        network.loads_t.p_set = pd.DataFrame(
            np.outer(shape.to_numpy(), base.to_numpy()),
            index=hours, columns=network.loads.index)

    # PyPSA 1.x turns a non-null p_set into an equality that pins the
    # dispatch, so a network carrying the TYTFS snapshot cannot be optimised
    # at all - it is the case's answer, asserted, and infeasible against a
    # lossless model.  The kit ships it released, with the case's own dispatch
    # kept in a column of its own so nothing is lost.
    for frame in (network.generators, network.links):
        if "p_set" in frame.columns:
            frame["p_set_tytfs"] = frame["p_set"].values
            frame["p_set"] = np.nan

    _add_load_shedding(network)
    network.meta = {
        "scenario": scenario_name(case),
        "scope": scope,
        "tytfs_case": case.name,
        "anchor_snapshot": str(anchor),
        "profiles": "synthetic, seed 42 - see LIMITATIONS in the README",
    }
    return network, anchor


def main() -> int:
    os.makedirs(NETWORKS, exist_ok=True)
    states = synthetic.anchors()
    manifest = []

    for path in sorted(psse.glob.glob("data/TYTFS2024_studyfiles/*_V35.raw")):
        case = psse.read_raw(path)
        scenario = scenario_name(case)
        geocoding = pd.read_csv(
            f"data/pypsa/geocoding/{case.name}.csv")
        result = synthetic.build(case, year=2030, seed=synthetic.SEED,
                                 anchor_frame=states)
        for scope in SCOPES:
            network, anchor = build_one(case, scope, result, geocoding, states)
            stem = f"{scenario}_{scope}"
            netcdf = os.path.join(NETWORKS, f"{stem}.nc")
            folder = os.path.join(NETWORKS, stem)
            if os.path.isdir(folder):
                shutil.rmtree(folder)
            network.export_to_netcdf(netcdf)
            network.export_to_csv_folder(folder)
            manifest.append({
                "scenario": scenario, "scope": scope,
                "buses": len(network.buses), "lines": len(network.lines),
                "transformers": len(network.transformers),
                "links": len(network.links),
                "generators": len(network.generators),
                "loads": len(network.loads),
                "snapshots": len(network.snapshots),
                "anchor_snapshot": str(anchor),
                "peak_demand_mw": round(float(
                    network.loads_t.p_set.sum(axis=1).max()), 1),
                "generation_capacity_mw": round(float(
                    network.generators["p_nom"].sum()), 1),
                "netcdf": f"networks/{stem}.nc",
                "csv_folder": f"networks/{stem}/",
            })
            print(f"{stem:<28} {len(network.buses):>5} buses  "
                  f"{len(network.lines):>5} lines  "
                  f"{len(network.snapshots):>4} snapshots")

    frame = pd.DataFrame(manifest)
    frame.to_csv(os.path.join(NETWORKS, "manifest.csv"), index=False)
    print(f"\n{len(frame)} networks -> {NETWORKS}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
