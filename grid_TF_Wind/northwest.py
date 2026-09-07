"""The North-West subnetwork of the TYTFS cases, and its two views.

What this is
------------
EirGrid's Wind Dispatch Tool groups the island's wind farms into constraint
groups; groups 1-3 are the North West, the Donegal and north Connacht 110 kV
network that exports through Srananagh.  This module extracts that region from
a TYTFS case, in two views, and reconciles it against a hand-built 15-node
dataset.

The two views exist because the hand-built dataset and TYTFS draw the boundary
of a "station" differently.  A hand-built node list folds a generator's
connection point into the substation it hangs off; TYTFS gives several of them
110 kV buses of their own.  Neither is wrong, and a reconciliation that does
not say which it is using will disagree with itself:

``native``
    TYTFS as it stands: 20 stations, with Golagh, Mulreavy, Cliff, Meentycat
    and Lenalea as 110 kV stations in their own right.
``aggregated``
    those five folded into the station that feeds them, giving the 15 nodes
    the hand-built dataset has.

The region is not radial
------------------------
Srananagh is the region's principal export path and the one the hand-built
dataset models, but it is not the only way out.  Removing the Srananagh
110/220 transformer leaves every North-West bus still connected to the 220 kV
network, through Corderry and Arigna towards Flagford, and through Letterkenny
and Corraclassy into Northern Ireland.  :func:`boundary` lists every tie, and
the extraction holds them all as fixed injections rather than pretending they
are not there.

Usage
-----
    python northwest.py circuits            # the circuit table, both views
    python northwest.py balance             # supply, demand and boundary flow
    python northwest.py extract             # -> data/pypsa/northwest_*/
    python northwest.py verify              # the extract against the full case
"""

from __future__ import annotations

import argparse
import glob
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

import psse
import pypsa_net

# --------------------------------------------------------------------------- #
# The region
#
# Named rather than derived, because a constraint group is a published grouping
# and not a property of the network - and because, as the docstring says, the
# region is not the radial island behind Srananagh that a purely topological
# definition would find.  Every bus is listed, so what is in and what is out is
# a thing you can read rather than infer.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Station:
    """One station: the buses it is, and the station it folds into."""

    name: str
    buses: tuple[int, ...]
    kv: float
    parent: str | None = None      # where the aggregated view puts it
    note: str = ""


#: The North-West, station by station, as ``nodes.xlsx`` has it.  ``parent``
#: is set on the nine stations the 15-node view folds away; everything else
#: stands in both views.  The hand-built file holds both views itself - a
#: 24-node list with generation as nodes of its own, and a "substation-only
#: nodal representation" of 15 - and these are those two lists, with the one
#: correction Phase 3 found: Clady is not in TYTFS, and TYTFS splits Srananagh
#: into two busbars that the hand-built file has as one node.
STATIONS = (
    # -- the export path ---------------------------------------------------- #
    Station("Srananagh 220", (5042,), 220.0,
            note="the region's connection to the 220 kV network, and the "
                 "boundary this extraction slacks at.  nodes.xlsx has one "
                 "Srananagh node, at 220 kV, so the 110 kV busbar folds into "
                 "it and the transformer becomes internal"),
    Station("Srananagh 110", (5041,), 110.0, parent="Srananagh 220",
            note="TYTFS's 110 kV busbar at the same station"),
    # -- the Erne ----------------------------------------------------------- #
    Station("Cathaleen's Fall", (1701, 17010, 17061), 110.0,
            note="two 110 kV busbars (1701 CATH_FALL, 17010 CATH FALL) and a "
                 "capacitor (17061 CATH_CAP), joined by zero-impedance "
                 "branches; one station"),
    Station("Cliff", (1761,), 110.0, parent="Cathaleen's Fall",
            note="the Erne's upper station, 5.5 km from Cathaleen's Fall"),
    # -- Donegal ------------------------------------------------------------ #
    Station("Binbane", (1341,), 110.0),
    Station("Tievebrack", (5191,), 110.0),
    Station("Ardnagappary", (1571,), 110.0,
            note="nodes.xlsx folds Clady into this station; TYTFS has no "
                 "Clady bus at any voltage - see the reconciliation"),
    Station("Clogher", (2870, 2871, 28710, 28712), 110.0,
            note="four 110 kV busbars at one site, joined by zero-impedance "
                 "couplers"),
    Station("Golagh", (2801, 28019), 110.0, parent="Clogher",
            note="Golagh and the tee point on the Letterkenny-Clogher line"),
    Station("Mulreavy", (4091,), 110.0, parent="Clogher"),
    Station("Croaghonagh", (51911,), 110.0),
    Station("Drumkeen", (2321,), 110.0),
    Station("Meentycat", (4071,), 110.0, parent="Drumkeen"),
    Station("Letterkenny", (3581, 35861, 35862), 110.0,
            note="with its capacitor and SVC"),
    Station("Lenalea", (3591,), 110.0, parent="Letterkenny"),
    Station("Trillick", (5361,), 110.0),
    Station("Sorne Hill", (4991,), 110.0),
    # -- the southern edge -------------------------------------------------- #
    Station("Corderry", (1631,), 110.0),
    Station("Garvagh", (2671,), 110.0, parent="Corderry"),
    Station("Sligo", (4981, 49861), 110.0, note="with its capacitor"),
    Station("Cunghill", (1931,), 110.0, parent="Sligo"),
    # -- north Mayo --------------------------------------------------------- #
    Station("Glenree", (4371,), 110.0),
    Station("Moy", (4041, 40461, 40462), 110.0, note="with its two capacitors"),
    Station("Tawnaghmore", (5241, 5251), 110.0, parent="Moy",
            note="Tawnaghmore and its second busbar TAWN_B"),
)

#: The stations the hand-built dataset folds, and where each one goes.  Most
#: are generation connection points whose only 110 kV neighbour is the parent,
#: so folding them moves an injection and removes a dead end.  Three are not:
#: Lenalea sits between Letterkenny and Tievebrack, Cunghill between Sligo and
#: Glenree, and Srananagh's 110 kV busbar between the 220 kV one and half the
#: region.  Folding those three moves a circuit rather than removing one, and
#: that is where the aggregated view's flow error comes from.
FOLDED = {s.name: s.parent for s in STATIONS if s.parent}

VIEWS = ("native", "aggregated")


def station_table(view: str = "native") -> pd.DataFrame:
    """The region's stations under one view, one row each."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}, not {view!r}")
    if view == "native":
        rows = [{"station": s.name, "kv": s.kv,
                 "buses": ",".join(str(b) for b in s.buses),
                 "folds_into": "", "note": s.note} for s in STATIONS]
    else:
        merged: dict[str, dict] = {}
        for s in STATIONS:
            target = s.parent or s.name
            entry = merged.setdefault(target, {"station": target, "kv": s.kv,
                                               "buses": [], "folded": [],
                                               "note": ""})
            entry["buses"].extend(s.buses)
            if s.parent:
                entry["folded"].append(s.name)
            else:
                entry["kv"], entry["note"] = s.kv, s.note
        rows = [{"station": e["station"], "kv": e["kv"],
                 "buses": ",".join(str(b) for b in sorted(e["buses"])),
                 "folds_into": "+".join(sorted(e["folded"])),
                 "note": e["note"]} for e in merged.values()]
    return pd.DataFrame(rows).sort_values("station").reset_index(drop=True)


def bus_map(view: str = "native") -> dict[int, str]:
    """Every region bus, mapped to the station it belongs to in ``view``."""
    out = {}
    for s in STATIONS:
        target = s.name if view == "native" else (s.parent or s.name)
        for bus in s.buses:
            out[bus] = target
    return out


# --------------------------------------------------------------------------- #
# The circuits
#
# What counts as "a circuit" is the thing the two datasets disagree about, so
# both counts are produced and neither is called the answer.  A hand-built node
# and edge list has one edge per pair of stations that are joined; a PSS/E case
# has one record per circuit, and three of the region's routes are double
# circuits.
# --------------------------------------------------------------------------- #

def circuits(case: psse.Case, view: str = "native",
             in_service: bool = True) -> pd.DataFrame:
    """Every circuit between two distinct stations of the region.

    Includes the Srananagh 110/220 transformer, which is a branch of the
    region's graph in every sense that matters here: it is the export path.
    Excludes anything internal to a station - the busbar couplers at Clogher,
    Cathaleen's Fall, Letterkenny and Sligo - because a coupler joins a
    station to itself.
    """
    members = bus_map(view)
    name = pypsa_net._clean(case.bus.set_index("I")["NAME"])
    rows = []

    branch = case.branch
    if in_service:
        branch = branch[branch["STAT"] == 1]
    for _, e in branch.iterrows():
        i, j = int(e["I"]), int(e["J"])
        if i not in members or j not in members:
            continue
        if members[i] == members[j]:
            continue
        rows.append({
            "from": members[i], "to": members[j],
            "kind": "line", "ckt": str(e["CKT"]).strip(),
            "bus_i": i, "bus_i_name": name.get(i, ""),
            "bus_j": j, "bus_j_name": name.get(j, ""),
            "km": float(e["LEN"] or 0.0),
            "r_pu": float(e["R"]), "x_pu": float(e["X"]),
            "b_pu": float(e["B"]), "rate1_mva": float(e["RATE1"]),
            "in_service": int(e["STAT"]) == 1,
        })

    transformer = case.transformer
    if in_service:
        transformer = transformer[transformer["STAT"] != 0]
    for _, t in transformer.iterrows():
        ends = [int(t["I"]), int(t["J"])]
        if int(t["WINDINGS"]) == 3:
            ends.append(int(t["K"]))
        ends = [e for e in ends if e in members]
        if len(ends) < 2 or len({members[e] for e in ends}) < 2:
            continue
        i, j = ends[0], ends[1]
        rows.append({
            "from": members[i], "to": members[j],
            "kind": "transformer", "ckt": str(t["CKT"]).strip(),
            "bus_i": i, "bus_i_name": name.get(i, ""),
            "bus_j": j, "bus_j_name": name.get(j, ""),
            "km": 0.0,
            "r_pu": float(t["R1_2"]), "x_pu": float(t["X1_2"]),
            "b_pu": 0.0, "rate1_mva": float(t["RATE1_1"]),
            "in_service": int(t["STAT"]) != 0,
        })

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    pair = frame[["from", "to"]].apply(
        lambda r: " - ".join(sorted(r)), axis=1)
    frame.insert(0, "route", pair)
    return frame.sort_values(["route", "ckt"]).reset_index(drop=True)


def routes(frame: pd.DataFrame) -> pd.DataFrame:
    """The circuit table collapsed to one row per pair of stations."""
    if frame.empty:
        return frame
    grouped = frame.groupby("route")
    return pd.DataFrame({
        "route": list(grouped.groups),
        "circuits": grouped.size().values,
        "km": grouped["km"].max().values,
        "rate1_mva": grouped["rate1_mva"].sum().values,
        "kinds": grouped["kind"].agg(lambda s: "+".join(sorted(set(s)))).values,
    }).sort_values("route").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# The boundary
# --------------------------------------------------------------------------- #

def boundary(case: psse.Case, view: str = "native") -> pd.DataFrame:
    """Every circuit with one end inside the region and one end outside.

    These are what make the region a subnetwork rather than an island, and
    what an extraction has to hold fixed.  Srananagh's transformer is *not*
    among them - both its ends are inside - because the 220 kV busbar is part
    of the region and is where the extraction slacks.
    """
    members = bus_map(view)
    name = pypsa_net._clean(case.bus.set_index("I")["NAME"])
    kv = case.bus.set_index("I")["BASKV"]
    rows = []
    for _, e in case.branch[case.branch["STAT"] == 1].iterrows():
        i, j = int(e["I"]), int(e["J"])
        inside_i, inside_j = i in members, j in members
        if inside_i == inside_j:
            continue
        near, far = (i, j) if inside_i else (j, i)
        rows.append({"station": members[near], "bus": near,
                     "outside_bus": far, "outside_name": name.get(far, ""),
                     "outside_kv": float(kv.get(far, np.nan)),
                     "ckt": str(e["CKT"]).strip(), "km": float(e["LEN"] or 0),
                     "rate1_mva": float(e["RATE1"])})
    for _, t in case.transformer[case.transformer["STAT"] != 0].iterrows():
        ends = [int(t["I"]), int(t["J"])]
        if int(t["WINDINGS"]) == 3:
            ends.append(int(t["K"]))
        if not any(e in members for e in ends):
            continue
        if all(e in members for e in ends):
            continue
        if all(float(kv.get(e, 0.0)) < pypsa_net.TRANSMISSION_KV
               for e in ends if e not in members):
            continue          # a step-down inside the station, not a tie
        near = next(e for e in ends if e in members)
        far = next(e for e in ends if e not in members)
        rows.append({"station": members[near], "bus": near,
                     "outside_bus": far, "outside_name": name.get(far, ""),
                     "outside_kv": float(kv.get(far, np.nan)),
                     "ckt": str(t["CKT"]).strip(), "km": 0.0,
                     "rate1_mva": float(t["RATE1_1"])})
    return pd.DataFrame(rows).sort_values(["station", "outside_name"]
                                          ).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Supply and demand
# --------------------------------------------------------------------------- #

def _homes(case: psse.Case, view: str) -> dict[int, str]:
    """Every bus in the case that belongs to the region, mapped to a station.

    Includes the sub-110 kV buses, resolved through the same least-reactance
    aggregation the transmission network uses, so that a wind farm at 690 V
    lands at the station it is connected to and nowhere else.
    """
    members = bus_map(view)
    stars, el = pypsa_net.elements(case)
    el = pypsa_net._fill_unrated(el)
    keep = pypsa_net._retained(case, stars, el, pypsa_net.TRANSMISSION_KV)
    aggregation = pypsa_net._aggregate_to(case, el, keep)
    parent = dict(zip(aggregation["bus"], aggregation["parent"]))
    out = {}
    for bus in case.bus["I"]:
        key = str(int(bus))
        home = key if key in keep else parent.get(key, "")
        if home and not home.startswith("star:") and int(home) in members:
            out[int(bus)] = members[int(home)]
    return out


def balance(case: psse.Case, view: str = "aggregated") -> pd.DataFrame:
    """Supply capacity, dispatched generation and demand, station by station.

    Three different numbers get called "generation" and they differ by a
    factor of ten here, so all three are reported:

    ``capacity_mw``
        the sum of ``PT`` over every generator record at the station,
        in service or not.  This is the connected capacity, and it is what a
        hand-built dataset's "supply" column means.
    ``dispatched_mw``
        the sum of ``PG`` over the records with ``STAT = 1``.  This is what
        the case actually runs, and in a winter-peak case the region's wind is
        almost entirely switched out.
    ``demand_mw``
        in-service ``PL``.
    """
    homes = _homes(case, view)
    gen = case.generator.copy()
    gen["station"] = gen["I"].astype(int).map(homes)
    gen = gen[gen["station"].notna()]
    load = case.load.copy()
    load["station"] = load["I"].astype(int).map(homes)
    load = load[load["station"].notna()]

    stations = station_table(view)["station"]
    rows = []
    for name in stations:
        g = gen[gen["station"] == name]
        l = load[load["station"] == name]
        rows.append({
            "station": name,
            "machines": len(g),
            "machines_in_service": int((g["STAT"] == 1).sum()),
            "capacity_mw": float(g["PT"].sum()),
            "dispatched_mw": float(g.loc[g["STAT"] == 1, "PG"].sum()),
            "demand_mw": float(l.loc[l["STAT"] == 1, "PL"].sum()),
        })
    frame = pd.DataFrame(rows)
    frame["net_mw"] = frame["dispatched_mw"] - frame["demand_mw"]
    return frame.sort_values("capacity_mw", ascending=False).reset_index(
        drop=True)


# --------------------------------------------------------------------------- #
# The hand-built dataset
#
# nodes.xlsx holds both views itself, one under the other in a single sheet:
# a 24-row list with generation as nodes of its own, then a header row reading
# "Substation-only nodal representation", then the 15-row list with generation
# folded into the substation it hangs off.  Both are read here, because the
# 24-row one is the only place the folding is written down.
# --------------------------------------------------------------------------- #

HANDBUILT = "data/handbuilt/nodes.xlsx"

#: The hand-built name for a station, where it differs from the one used here.
HANDBUILT_ALIASES = {"Srananagh": "Srananagh 220"}


def handbuilt(path: str = HANDBUILT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The 24-node and 15-node tables from ``nodes.xlsx``.

    Returns ``(detailed, folded)``.  ``detailed`` has one row per node with
    its type, its capacity and - for the generation nodes - the substation it
    is assigned to.  ``folded`` has one row per substation with a supply and a
    demand capacity.
    """
    raw = pd.read_excel(path)
    raw.columns = ["node_type", "node_name", "capacity", "assigned_to"]
    split = raw.index[raw["node_type"].astype(str).str.startswith(
        "Substation-only")]
    cut = int(split[0]) if len(split) else len(raw)

    detailed = raw.iloc[:cut].copy()
    detailed = detailed[detailed["node_name"].notna()]
    detailed["capacity"] = pd.to_numeric(detailed["capacity"],
                                         errors="coerce")

    folded = raw.iloc[cut + 2:].copy()
    folded.columns = ["node_type", "station", "supply_mw", "demand_mw"]
    folded = folded[folded["station"].notna()]
    for column in ("supply_mw", "demand_mw"):
        folded[column] = pd.to_numeric(folded[column], errors="coerce")
    folded["station"] = folded["station"].replace(HANDBUILT_ALIASES)
    return detailed.reset_index(drop=True), folded.reset_index(drop=True)


def reconcile(case: psse.Case, path: str = HANDBUILT) -> pd.DataFrame:
    """The hand-built table against TYTFS, station by station.

    Supply is compared against **capacity** - the sum of ``PT`` over every
    machine at the station, in service or not - because that is what a
    hand-built "supply capacity" column means.  Comparing it against a case's
    dispatch would be comparing a fleet with a winter-peak security run, and
    the answer would be a factor of ten.
    """
    _, folded = handbuilt(path)
    mine = balance(case, "aggregated")
    merged = folded.merge(mine, on="station", how="outer")
    merged["supply_difference_mw"] = (merged["capacity_mw"]
                                      - merged["supply_mw"])
    merged["demand_difference_mw"] = (merged["demand_mw_y"]
                                      - merged["demand_mw_x"]) \
        if "demand_mw_y" in merged else np.nan
    merged = merged.rename(columns={"demand_mw_x": "handbuilt_demand_mw",
                                    "demand_mw_y": "tytfs_demand_mw",
                                    "supply_mw": "handbuilt_supply_mw",
                                    "capacity_mw": "tytfs_capacity_mw"})
    return merged[["station", "handbuilt_supply_mw", "tytfs_capacity_mw",
                   "supply_difference_mw", "handbuilt_demand_mw",
                   "tytfs_demand_mw", "demand_difference_mw", "machines",
                   "dispatched_mw"]].sort_values("station").reset_index(
                       drop=True)


def reconcile_plants(case: psse.Case, path: str = HANDBUILT) -> pd.DataFrame:
    """Each generation node of the 24-node list against TYTFS's own station.

    The hand-built file names nine generation sites and assigns each to a
    substation.  This is what TYTFS has at the same place, and it is where the
    reconciliation is most informative: four of the nine agree to within 1%,
    and the three hydro entries agree with nothing.
    """
    detailed, _ = handbuilt(path)
    plants = detailed[detailed["assigned_to"].notna()].copy()
    homes = _homes(case, "native")
    register = case.generator.copy()
    register["station"] = register["I"].astype(int).map(homes)
    by_station = register.groupby("station")["PT"].agg(["sum", "size"])

    rows = []
    for _, plant in plants.iterrows():
        station = HANDBUILT_ALIASES.get(plant["node_name"],
                                        plant["node_name"])
        here = by_station.loc[station] if station in by_station.index else None
        rows.append({
            "handbuilt_node": plant["node_name"],
            "type": plant["node_type"],
            "assigned_to": plant["assigned_to"],
            "handbuilt_mw": float(plant["capacity"]),
            "tytfs_station": station if here is not None else "",
            "tytfs_capacity_mw": float(here["sum"]) if here is not None
            else 0.0,
            "tytfs_machines": int(here["size"]) if here is not None else 0,
        })
    frame = pd.DataFrame(rows)
    frame["difference_mw"] = (frame["tytfs_capacity_mw"]
                              - frame["handbuilt_mw"])
    frame["ratio"] = (frame["tytfs_capacity_mw"]
                      / frame["handbuilt_mw"].replace(0, np.nan))
    return frame.sort_values("handbuilt_mw", ascending=False).reset_index(
        drop=True)


# --------------------------------------------------------------------------- #
# Extraction
#
# Built from the case rather than sliced out of the full network, because the
# aggregated view merges buses and there is no honest way to merge a bus in a
# solved network after the fact.  The boundary is held at the flows the full
# network's DC solve puts on the ties, so the extract is the region as the
# whole system sees it rather than the region on its own.
# --------------------------------------------------------------------------- #

SLACK_STATION = "Srananagh 220"

#: What an import through Srananagh costs an optimisation of the region, in
#: EUR/MWh.  A placeholder, like every other cost in this repo: it exists so
#: that a min-cost dispatch runs the region's own fleet before it imports, and
#: it is written into the exported CSVs.
IMPORT_PRICE = 100.0


def _reference_flows(case: psse.Case):
    """The full transmission network, solved, and its DC flows by element."""
    model = pypsa_net.build(case, min_kv=pypsa_net.TRANSMISSION_KV)
    model.network.lpf()
    return model


def boundary_flows(case: psse.Case, view: str = "native",
                   model=None) -> pd.DataFrame:
    """The MW crossing each boundary tie, from the full network's DC solve.

    Positive is into the region.  These are the injections the extraction
    fixes; without them the region does not balance, because it is not an
    island.
    """
    model = model or _reference_flows(case)
    n = model.network
    ties = boundary(case, view)
    lines = n.lines_t.p0.loc["now"] if len(n.lines) else pd.Series(dtype=float)
    trafo = (n.transformers_t.p0.loc["now"] if len(n.transformers)
             else pd.Series(dtype=float))
    flows = []
    for _, t in ties.iterrows():
        inside, outside = int(t["bus"]), int(t["outside_bus"])
        found, mw = "", np.nan
        for a, b in ((inside, outside), (outside, inside)):
            key = f"{a}-{b}-{t['ckt']}"
            if key in lines.index:
                found, mw = key, float(lines[key])
                if a == inside:
                    mw = -mw          # p0 leaves bus0; flip to "into region"
                break
            key = f"T{a}-{b}-{t['ckt']}"
            if key in trafo.index:
                found, mw = key, float(trafo[key])
                if a == inside:
                    mw = -mw
                break
        flows.append({**t.to_dict(), "element": found, "into_region_mw": mw})
    return pd.DataFrame(flows)


def extract(case: psse.Case, view: str = "native", model=None):
    """Build the region as a PyPSA network of its own.

    One bus per station.  Within a station the case's own busbars are joined
    by zero-impedance couplers, so merging them is exact to the fourth decimal
    place and is what makes the aggregated view expressible at all.

    Srananagh 220 is the reference bus, which is what the region's own
    modelling convention says it is: the 220 kV busbar is where the North West
    meets the rest of the system, and everything upstream of it is somebody
    else's problem.  Every other tie is held at the MW the full network's DC
    solve puts on it, so the extract is the region as the whole system sees
    it.
    """
    import pypsa

    model = model or _reference_flows(case)
    stations = station_table(view)
    bal = balance(case, view).set_index("station")
    ties = boundary_flows(case, view, model=model)
    lines = circuits(case, view)

    n = pypsa.Network()
    n.name = f"{case.name} north-west ({view})"
    n.set_snapshots(["now"])
    n.add("Carrier", ["AC", "boundary"])
    n.add("Bus", stations["station"].values,
          v_nom=stations["kv"].values, carrier="AC")
    n.buses["station_buses"] = stations["buses"].values
    n.buses["folds_in"] = stations["folds_into"].values

    ac = lines[lines["kind"] == "line"]
    if len(ac):
        v = np.full(len(ac), pypsa_net.TRANSMISSION_KV)
        n.add("Line",
              [f"{r['bus_i']}-{r['bus_j']}-{r['ckt']}"
               for _, r in ac.iterrows()],
              bus0=ac["from"].values, bus1=ac["to"].values,
              r=[pypsa_net._ohms(p, kv) for p, kv in zip(ac["r_pu"], v)],
              x=[pypsa_net._ohms(p, kv) for p, kv in zip(ac["x_pu"], v)],
              b=[pypsa_net._siemens(p, kv) for p, kv in zip(ac["b_pu"], v)],
              s_nom=ac["rate1_mva"].values, length=ac["km"].values,
              carrier="AC")

    tx = lines[lines["kind"] == "transformer"]
    for _, t in tx.iterrows():
        s_nom = t["rate1_mva"] if t["rate1_mva"] not in pypsa_net.UNRATED \
            else pypsa_net.UNRATED_FALLBACK_MVA
        n.add("Transformer", f"T{t['bus_i']}-{t['bus_j']}-{t['ckt']}",
              bus0=t["from"], bus1=t["to"],
              r=t["r_pu"] * s_nom / pypsa_net.SYSTEM_MVA,
              x=t["x_pu"] * s_nom / pypsa_net.SYSTEM_MVA,
              s_nom=s_nom, tap_ratio=1.0, phase_shift=0.0)

    for name, row in bal.iterrows():
        if row["demand_mw"]:
            n.add("Load", f"{name} demand", bus=name,
                  p_set=float(row["demand_mw"]), carrier="AC")
        if row["capacity_mw"]:
            # Free at the margin: the region's fleet is wind and hydro, so an
            # optimisation should run it and import the shortfall, not the
            # other way round.
            n.add("Generator", f"{name} generation", bus=name, carrier="AC",
                  p_nom=float(row["capacity_mw"]),
                  p_set=float(row["dispatched_mw"]), control="PV",
                  p_min_pu=0.0, marginal_cost=0.0)

    # The boundary: one injection per tie, at the station it lands on.  Every
    # tie but Srananagh is pinned at the MW the full network puts on it - by
    # its bounds and not only by p_set, so that it stays pinned in an
    # optimisation, where p_set is released.  Srananagh is left free, because
    # it is the reference and has to absorb whatever the region does not.
    for _, t in ties.iterrows():
        mw = float(t["into_region_mw"])
        p_nom = max(float(t["rate1_mva"]), abs(mw), 1.0)
        free = t["station"] == SLACK_STATION
        n.add("Generator",
              f"boundary {t['station']} - {t['outside_name']} {t['ckt']}",
              bus=t["station"], carrier="boundary", p_nom=p_nom,
              p_min_pu=-1.0 if free else mw / p_nom,
              p_max_pu=1.0 if free else mw / p_nom,
              p_set=mw, control="PV",
              marginal_cost=IMPORT_PRICE if free else 0.0)

    slack = n.generators.index[n.generators["bus"] == SLACK_STATION]
    if len(slack):
        control = pd.Series("PV", index=n.generators.index)
        control[slack[0]] = "Slack"
        n.generators["control"] = control.values
    n.buses["control"] = np.where(n.buses.index == SLACK_STATION,
                                  "Slack", "PQ")
    return n, {"stations": stations, "circuits": lines,
               "routes": routes(lines), "balance": balance(case, view),
               "boundary": ties}


def compare_with_full(case: psse.Case, view: str = "native", model=None
                      ) -> pd.DataFrame:
    """The extract's internal flows against the full network's, circuit by circuit.

    The check that the extraction is an extraction: same impedances, same
    injections, a different reference bus, so a DC flow has to put the same MW
    on every circuit.  Anything else means a boundary tie was missed or a
    station was merged that should not have been.
    """
    model = model or _reference_flows(case)
    n, _ = extract(case, view, model=model)
    n.lpf()
    full = model.network.lines_t.p0.loc["now"]
    mine = n.lines_t.p0.loc["now"]
    rows = []
    for name, mw in mine.items():
        rows.append({"circuit": name, "extract_mw": float(mw),
                     "full_mw": float(full[name]) if name in full.index
                     else np.nan})
    frame = pd.DataFrame(rows)
    frame["difference_mw"] = frame["extract_mw"] - frame["full_mw"]
    return frame.sort_values("difference_mw", key=abs, ascending=False
                             ).reset_index(drop=True)


def windy(case: psse.Case, capacity_factor: float = 1.0, model=None):
    """The region with its wind running, on the *full* network.

    None of the four published cases is a high-wind case - the winter-peak
    ones switch the region's wind out almost entirely and the summer-valley
    ones switch out all of it - so the export the Wind Dispatch Tool exists to
    manage does not appear in any of them.  This puts the region's connected
    capacity to work at ``capacity_factor`` of ``PT`` and re-solves.

    It is run on the whole transmission network rather than on the extract,
    and deliberately.  The region has eight ties, not one; an extract holds
    seven of them where the case put them, so every extra megawatt has
    nowhere to go but Srananagh and the answer comes out both large and
    meaningless.  On the full network the flow divides the way the impedances
    say it should.

    It is a what-if and not a case.  The generation is the register at a flat
    capacity factor, the demand is the case's, and nothing outside the region
    is re-dispatched to make room - so the numbers say where the region's
    power would try to go, not what the system would actually do.
    """
    model = model or _reference_flows(case)
    n = model.network.copy()

    # The case's out-of-service machines are not in the network at all -
    # pypsa_net builds from STAT = 1 - and in a winter-peak case that is
    # almost the whole regional fleet.  So the region's generation is replaced
    # wholesale: the in-service machines are zeroed and one aggregate is added
    # at each retained bus carrying that bus's share of the register.
    stars, el = pypsa_net.elements(case)
    el = pypsa_net._fill_unrated(el)
    keep = pypsa_net._retained(case, stars, el, pypsa_net.TRANSMISSION_KV)
    aggregation = pypsa_net._aggregate_to(case, el, keep)
    parent = dict(zip(aggregation["bus"], aggregation["parent"]))
    members = bus_map("native")

    def retained(bus: int) -> str:
        key = str(int(bus))
        return key if key in keep else parent.get(key, "")

    register = case.generator.copy()
    register["home"] = [retained(i) for i in register["I"]]
    register = register[register["home"].map(
        lambda h: bool(h) and not h.startswith("star:")
        and int(h) in members)]
    by_bus = register.groupby("home")["PT"].sum()

    here = n.generators.index[n.generators["bus"].isin(by_bus.index)]
    p_set = n.generators["p_set"].copy()
    p_set[here] = 0.0
    n.generators["p_set"] = p_set.values
    n.add("Generator", [f"NW register {bus}" for bus in by_bus.index],
          bus=list(by_bus.index), carrier="unknown",
          p_nom=by_bus.values, p_set=by_bus.values * capacity_factor,
          control="PV", marginal_cost=0.0)

    n.lpf()
    return n


def region_flows(case: psse.Case, network, view: str = "native"
                 ) -> pd.DataFrame:
    """The MW on each of the region's boundary ties in a solved network."""
    ties = boundary(case, view)
    lines = network.lines_t.p0.loc["now"]
    trafo = (network.transformers_t.p0.loc["now"]
             if len(network.transformers) else pd.Series(dtype=float))
    rows = []
    for _, t in ties.iterrows():
        inside, outside = int(t["bus"]), int(t["outside_bus"])
        mw = np.nan
        for a, b in ((inside, outside), (outside, inside)):
            for prefix, series in (("", lines), ("T", trafo)):
                key = f"{prefix}{a}-{b}-{t['ckt']}"
                if key in series.index:
                    mw = float(series[key]) * (-1 if a == inside else 1)
                    break
            if np.isfinite(mw):
                break
        rows.append({**t.to_dict(), "into_region_mw": mw})
    return pd.DataFrame(rows)


def verify(case: psse.Case, view: str = "native", solver: str = "highs",
           model=None) -> dict:
    """Does the extract solve, and is it the region the full case contains?"""
    model = model or _reference_flows(case)
    n, reports = extract(case, view, model=model)
    result = {"case": case.name, "view": view,
              "stations": len(n.buses), "circuits": len(n.lines),
              "transformers": len(n.transformers),
              "routes": len(reports["routes"]),
              "capacity_mw": float(reports["balance"]["capacity_mw"].sum()),
              "dispatched_mw": float(reports["balance"]["dispatched_mw"].sum()),
              "demand_mw": float(reports["balance"]["demand_mw"].sum()),
              "boundary_ties": len(reports["boundary"]),
              "net_into_region_mw": float(
                  reports["boundary"]["into_region_mw"].sum())}

    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(n.buses.index)
    g.add_edges_from(zip(n.lines["bus0"], n.lines["bus1"]))
    g.add_edges_from(zip(n.transformers["bus0"], n.transformers["bus1"]))
    result["connected"] = nx.number_connected_components(g) == 1

    try:
        n.lpf()
        flows = n.lines_t.p0.loc["now"]
        result["dc_pf"] = "solved"
        result["max_loading"] = float(
            (flows.abs() / n.lines["s_nom"]).max())
        # Only the native view has a Srananagh transformer to measure: the
        # 15-node view has one Srananagh node, so the transformer is inside
        # it and its flow is not a variable any more.
        if len(n.transformers):
            result["srananagh_export_mw"] = float(
                -n.transformers_t.p0.loc["now"].iloc[0])
    except Exception as exc:                                # noqa: BLE001
        result["dc_pf"] = f"failed: {type(exc).__name__}: {exc}"

    try:
        free = pypsa_net.for_optimisation(n)
        status, condition = free.optimize(solver_name=solver)
        result["lopf"] = f"{status}/{condition}"
    except Exception as exc:                                # noqa: BLE001
        result["lopf"] = f"failed: {type(exc).__name__}: {exc}"

    agreement = compare_with_full(case, view, model=model)
    result["max_flow_difference_mw"] = float(
        agreement["difference_mw"].abs().max())
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

DEFAULT_CASE = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"
DEFAULT_OUT = "data/pypsa"


def run_circuits(case: psse.Case) -> None:
    for view in VIEWS:
        frame = circuits(case, view)
        route = routes(frame)
        print(f"\n{view}: {len(station_table(view))} stations, "
              f"{len(frame)} circuits on {len(route)} routes")
        print(route.to_string(index=False))
        doubles = route[route["circuits"] > 1]
        if len(doubles):
            print(f"  {len(doubles)} routes carry more than one circuit: "
                  + ", ".join(doubles["route"]))


def run_balance(paths: list[str]) -> None:
    for path in paths:
        case = psse.read_raw(path)
        frame = balance(case, "aggregated")
        ties = boundary_flows(case, "native")
        print(f"\n{case.name}")
        print(frame.to_string(index=False))
        print(f"  capacity {frame['capacity_mw'].sum():,.1f} MW   "
              f"dispatched {frame['dispatched_mw'].sum():,.1f} MW   "
              f"demand {frame['demand_mw'].sum():,.1f} MW")
        print(f"  net into the region {ties['into_region_mw'].sum():,.1f} MW, "
              f"of which {ties.loc[ties['station'] == SLACK_STATION, 'into_region_mw'].sum():,.1f} MW "
              "through Srananagh 220")


def run_extract(case: psse.Case, out: str) -> None:
    model = _reference_flows(case)
    for view in VIEWS:
        n, reports = extract(case, view, model=model)
        directory = os.path.join(out, f"northwest_{case.name}_{view}")
        os.makedirs(directory, exist_ok=True)
        n.export_to_csv_folder(directory)
        report_dir = os.path.join(directory, "reports")
        os.makedirs(report_dir, exist_ok=True)
        for key, frame in reports.items():
            frame.to_csv(os.path.join(report_dir, f"{key}.csv"), index=False)
        compare_with_full(case, view, model=model).to_csv(
            os.path.join(report_dir, "agreement_with_full.csv"), index=False)
        print(f"{view}: {len(n.buses)} stations, {len(n.lines)} circuits "
              f"-> {directory}")


def run_verify(paths: list[str], solver: str) -> int:
    bad = 0
    for path in paths:
        case = psse.read_raw(path)
        model = _reference_flows(case)
        for view in VIEWS:
            r = verify(case, view, solver=solver, model=model)
            ok = (r["connected"] and r["dc_pf"] == "solved"
                  and str(r["lopf"]).startswith("ok"))
            bad += not ok
            print(f"\n{r['case']} / {r['view']}  {'ok' if ok else 'FAIL'}")
            for key, value in r.items():
                if key in ("case", "view"):
                    continue
                print(f"  {key:<26} "
                      + (f"{value:,.4f}" if isinstance(value, float)
                         else str(value)))
    return 1 if bad else 0


def run_windy(paths: list[str], capacity_factor: float) -> None:
    for path in paths:
        case = psse.read_raw(path)
        model = _reference_flows(case)
        base = region_flows(case, model.network)
        n = windy(case, capacity_factor, model=model)
        after = region_flows(case, n)
        bal = balance(case, "aggregated")
        print(f"\n{case.name}: the region's wind at {capacity_factor:.0%} "
              "of connected capacity, on the full network")
        print(f"  capacity {bal['capacity_mw'].sum():,.1f} MW   "
              f"demand {bal['demand_mw'].sum():,.1f} MW   "
              f"case dispatch {bal['dispatched_mw'].sum():,.1f} MW")
        merged = base[["station", "outside_name", "ckt", "rate1_mva"]].copy()
        merged["case_mw"] = base["into_region_mw"].round(1)
        merged["windy_mw"] = after["into_region_mw"].round(1)
        merged["loading"] = (after["into_region_mw"].abs()
                             / base["rate1_mva"]).round(2)
        print(merged.to_string(index=False))
        print(f"  net into the region: case {base['into_region_mw'].sum():,.1f} MW"
              f"  ->  windy {after['into_region_mw'].sum():,.1f} MW")
        inside = set(circuits(case, "native")
                     .apply(lambda r: f"{r['bus_i']}-{r['bus_j']}-{r['ckt']}",
                            axis=1))
        flows = n.lines_t.p0.loc["now"]
        here = [i for i in flows.index if i in inside]
        loading = (flows[here].abs() / n.lines.loc[here, "s_nom"])
        over = loading[loading > 1.0].sort_values(ascending=False)
        print(f"  {len(over)} of {len(here)} internal circuits over their "
              f"continuous rating; worst {loading.max():.2f}x")
        for name, value in over.head(8).items():
            print(f"    {name:<16} {value:.2f}x")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("circuits", help="the circuit table, both views"
                   ).add_argument("path", nargs="?", default=DEFAULT_CASE)
    sub.add_parser("balance", help="supply, demand and boundary flow"
                   ).add_argument("paths", nargs="*",
                                  default=sorted(glob.glob(
                                      "data/TYTFS2024_studyfiles/*_V35.raw")))
    e = sub.add_parser("extract", help="export the region as PyPSA CSVs")
    e.add_argument("path", nargs="?", default=DEFAULT_CASE)
    e.add_argument("--out", default=DEFAULT_OUT)
    v = sub.add_parser("verify", help="connectivity, DC PF, LOPF, agreement")
    v.add_argument("paths", nargs="*", default=[DEFAULT_CASE])
    v.add_argument("--solver", default="highs")
    w = sub.add_parser("windy", help="the region with its wind running")
    w.add_argument("paths", nargs="*", default=[DEFAULT_CASE])
    w.add_argument("--capacity-factor", type=float, default=1.0)
    args = p.parse_args(argv)

    if args.cmd == "circuits":
        run_circuits(psse.read_raw(args.path))
        return 0
    if args.cmd == "balance":
        run_balance(args.paths)
        return 0
    if args.cmd == "extract":
        run_extract(psse.read_raw(args.path), args.out)
        return 0
    if args.cmd == "windy":
        run_windy(args.paths, args.capacity_factor)
        return 0
    return run_verify(args.paths, args.solver)


if __name__ == "__main__":
    raise SystemExit(main())
