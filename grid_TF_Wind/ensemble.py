"""An ensemble of committed dispatch states, for the SNSP vs. RoCoF comparison.

What this is for
----------------
The question is whether **SNSP** - the dispatch limit EirGrid operates to - or
**dP / H_COI** - initial RoCoF from the swing equation - better predicts a
frequency-security violation on the all-island system.  Answering it needs a
population of *realistic* system states, each carrying both metrics and each
subjected to a contingency.  This module makes the states; :mod:`inertia`
prices their kinetic energy and their reference incident, :mod:`frequency`
trips them, and :mod:`compare` scores the two predictors.

Why unit commitment, and why individual units
---------------------------------------------
H_COI depends on *which* machines are synchronised, and dP on the largest
single one online.  An economic dispatch over aggregated plant gives neither:
it runs every CCGT at a fraction of output, where a real system runs some at
full load and leaves the others cold.  So every conventional unit here is its
own committable generator with a minimum stable level, minimum up and down
times, ramp limits and a start-up cost, and the dispatch is a MILP solved over
a short rolling window so that those constraints actually bite.

A multi-shaft CCGT - gas turbines and a steam turbine on separate shafts, but
one plant that trips as one - is the only thing merged, into a single
*module*, because that is the unit the reference incident is defined over.  Its
kinetic energy is the sum of its machines', so merging loses nothing.

**The network is clustered; the generators are not.**  The COI metrics barely
care about topology and the MILP cost does, so the 646-bus transmission model
is reduced to a few tens of nodes, while each unit keeps its own identity and
its own bus on the clustered network so that a locality extension stays
possible.  Wind and solar, which are neither committable nor synchronous, are
aggregated per cluster.

What is deliberately NOT a constraint
-------------------------------------
**SNSP, inertia and RoCoF are not constrained anywhere in the optimisation.**
They are the outcomes this study measures.  An SNSP <= 75% or inertia >=
23,000 MWs constraint would stop the ensemble ever reaching the insecure
region and cut the interesting half off every scatter plot by construction.
What *is* enforced is what bounds the real system from outside that
comparison: the minimum number of large units on load (the Operational
Constraints Update rule), interconnector limits, and primary reserve cover for
the largest infeed.

Usage
-----
    import psse, ensemble
    case = psse.read_raw("data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw")
    topo = ensemble.topology(case)          # clustered network, busmap
    units = ensemble.fleet(case, topo)      # one row per committable module
    python ensemble.py time                 # one scenario, wall-clock timed
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import zlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import psse
import pypsa_net

# --------------------------------------------------------------------------- #
# Where the network comes from
# --------------------------------------------------------------------------- #

STUDY_DIR = "data/TYTFS2024_studyfiles"

#: One vintage is one pair of TYTFS cases: a winter peak and a summer valley.
#: The WP case supplies the network and the generator register, and the pair
#: supplies the demand envelope that the sampler draws from.  2024 is the
#: default because it is the system the published 23,000 MWs floor, the
#: ~500 MW largest infeed and the two operating interconnectors belong to.
VINTAGES = {
    "2024": ("TYTFS2024_WP2024_V35", "TYTFS2024_SV2024_V35"),
    "2033": ("TYTFS2024_WP2033_V35", "TYTFS2024_SV2033_V35"),
}
DEFAULT_VINTAGE = "2024"

GEOCODING_DIR = "data/pypsa/geocoding"

SEED = 42

# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #

#: Nodes per jurisdiction after clustering.  40 in all, inside the 30-60 band:
#: large enough that the North-West, Dublin and the Cork/Shannon generation
#: pockets stay distinct nodes, small enough that the MILP's cost is in the
#: commitment and not in the flow constraints.  The HVDC far terminals are
#: kept as their own nodes on top of this.
CLUSTERS = {"IE": 32, "NI": 8}

# --------------------------------------------------------------------------- #
# The dispatch window
# --------------------------------------------------------------------------- #

#: Hours in each scenario's unit-commitment problem.  A single snapshot cannot
#: express a minimum up time or a start-up cost, so each scenario solves a
#: window of hours and reads its state off one of them.
WINDOW_H = 24

#: Which hour of the window is the scenario.  Seventeen hours of lead-in, so
#: that the commitment at the target hour is not an artefact of the window's
#: cold start (every unit begins the window off, and free to start).
TARGET_HOUR = 17

# --------------------------------------------------------------------------- #
# Technology table
#
# Dispatch parameters by technology.  None of these is in the TYTFS file: the
# raw format carries PT, PB and MBASE and nothing about how a machine behaves
# in time.  They are typical values for the plant types on the island, chosen
# so the merit order and the commitment dynamics are in the right order; they
# are not any unit's contracted parameters.  Inertia constants are NOT here -
# they live in inertia.py and nowhere else.
#
#   p_min_pu        minimum stable generation, fraction of p_nom
#   min_up/down     hours
#   ramp            fraction of p_nom per hour, both directions
#   start_up_cost   EUR per MW of p_nom per start
#   marginal_cost   EUR/MWh
#   por             primary reserve (5-15 s) a synchronised unit can give,
#                   fraction of p_nom, before headroom is considered
#   sor             secondary reserve (15-90 s), same basis
# --------------------------------------------------------------------------- #

TECHNOLOGY = {
    "CCGT": dict(p_min_pu=0.45, min_up=4, min_down=4, ramp=0.50,
                 start_up_cost=60.0, marginal_cost=85.0, por=0.10, sor=0.15),
    "OCGT": dict(p_min_pu=0.30, min_up=1, min_down=1, ramp=1.00,
                 start_up_cost=20.0, marginal_cost=140.0, por=0.20, sor=0.35),
    "steam": dict(p_min_pu=0.40, min_up=8, min_down=8, ramp=0.30,
                  start_up_cost=90.0, marginal_cost=100.0, por=0.06, sor=0.10),
    "hydro": dict(p_min_pu=0.20, min_up=1, min_down=1, ramp=1.00,
                  start_up_cost=0.0, marginal_cost=10.0, por=0.30, sor=0.50),
}

#: Deterministic per-unit spread on marginal cost, +-5%, so that two identical
#: units are not a tie the solver breaks arbitrarily.  Keyed on the module
#: name, so it does not change with the seed.
COST_SPREAD = 0.05

#: Turlough Hill, the island's pumped storage.  Modelled as four storage units
#: rather than committable generators: a committable machine has no energy
#: balance, and one that can pump for free will.  A unit is synchronised
#: whenever it is generating or pumping.  ``por`` and ``sor`` apply to a
#: generating unit's headroom; a pumping unit's reserve is its pump load.
PUMPED_STORAGE = dict(max_hours=5.0, efficiency_store=0.85,
                      efficiency_dispatch=0.85, marginal_cost=2.0, por=0.30,
                      sor=0.50)

#: Below this a synchronous record is left out of the dispatch.  In WP2024 the
#: excluded records sum to a few tens of MW, mostly embedded CHP and biogas
#: engines, and are listed in the fleet report.
SMALL_UNIT_MW = 10.0

# --------------------------------------------------------------------------- #
# System constraints that ARE enforced
# --------------------------------------------------------------------------- #

#: Interconnector limits, MW, positive = import to the island.  EWIC and Moyle
#: from the brief's operational figures; Greenlink is out for the 2024
#: vintage (it is STAT = 0 in the case and commissioned in 2025).
INTERCONNECTOR_LIMITS = {
    "2024": {"EWIC": (-526.0, 504.0), "Moyle": (-400.0, 442.0),
             "Greenlink": (0.0, 0.0)},
    "2033": {"EWIC": (-526.0, 504.0), "Moyle": (-400.0, 442.0),
             "Greenlink": (-500.0, 500.0)},
}

#: Minimum units on load, from the Operational Constraints Update: at least
#: five large conventional machines in Ireland and three in Northern Ireland,
#: or the relaxed all-island figure of seven.  This is a real floor under
#: H_COI and is part of the system being modelled, not a thumb on the scale.
MIN_UNITS = {"IE": 5, "NI": 3}
MIN_UNITS_ALL_ISLAND = 7
MIN_UNITS_RULE = "split"            # or "all_island"

#: What counts as a "large conventional unit" for that rule: a thermal module
#: at or above this rating.  The OCU names specific units; this threshold
#: selects the same class of plant from the register without a name list.
LARGE_UNIT_MW = 100.0

#: Primary operating reserve held against the largest infeed, as a fraction
#: of it.  Imposed per contingency element: the reserve left once a unit has
#: tripped (it cannot cover its own loss) must cover this fraction of what
#: that unit was producing.
POR_REQUIREMENT_FRACTION = 0.75

#: Penalties that keep every scenario feasible and make a shortfall visible
#: rather than an infeasibility.  Both are recorded per scenario.
VOLL = 10000.0                      # EUR/MWh unserved energy
RESERVE_SHORTFALL_COST = 2000.0     # EUR/MW-h of POR short

SOLVER = "highs"
SOLVER_OPTIONS = {"mip_rel_gap": 0.005, "time_limit": 120.0, "threads": 1,
                  "output_flag": False}

# --------------------------------------------------------------------------- #
# The fleet
#
# The raw format has no fuel type.  pypsa_net.carrier_of reads the bus-name
# convention (W_, PV_, HY_, BS_) and calls most of the thermal fleet
# "unknown"; that is honest for its purposes and not enough for these,
# because p_min, minimum up time and H all differ by technology.  So the
# large units are named here, by the PSS/E bus names the case uses.  This is
# a reading of which station is which, checked against the case's PT, PB and
# MBASE; it is not in the file.
# --------------------------------------------------------------------------- #

#: Name prefixes of the thermal plant, by technology.  Matched against the
#: PSS/E bus name, first match wins.
STATION_TECHNOLOGY = (
    # Combined cycle.  Single-shaft blocks and the members of multi-shaft ones.
    ("GI CCGT", "CCGT"), ("AGH_CCGT", "CCGT"), ("WHITEGATE", "CCGT"),
    ("DUBLIN_BAY", "CCGT"), ("BS_HUNTSTOWN", "CCGT"), ("HUNT_CT", "CCGT"),
    ("HUNT_ST", "CCGT"), ("TYNAGH", "CCGT"), ("PBEGG4", "CCGT"),
    ("PBEGG5", "CCGT"), ("PBEGG6", "CCGT"), ("GEN_COOL", "CCGT"),
    ("BAFD_GA", "CCGT"), ("BAFD_GB", "CCGT"), ("BAFD_GC", "CCGT"),
    # Steam: Moneypoint coal, Edenderry peat/biomass, waste and biomass plant.
    ("MNYPG", "steam"), ("EDENDERRY", "steam"), ("DUBLIN_WASTE", "steam"),
    ("MEATH_WASTE", "steam"), ("BIO_", "steam"),
    # Open cycle, aeroderivative and peaking plant, including the temporary
    # emergency generation (TEG) and the new flexible gas units.
    ("KIL_OCGT", "OCGT"), ("KILSHANE", "OCGT"), ("CUSHALING", "OCGT"),
    ("AGH_G1", "OCGT"), ("SEAL_ROCK", "OCGT"), ("BAFD", "OCGT"),
    ("COOLG", "OCGT"), ("TAW_PEAK", "OCGT"), ("DERRYIRON", "OCGT"),
    ("TEG", "OCGT"), ("PBEGG_FLEX", "OCGT"), ("RINGSEND FLE", "OCGT"),
    ("CORDUFF_FLEX", "OCGT"), ("GEN_KILR", "OCGT"), ("KILR_AU", "OCGT"),
    ("AUGT", "OCGT"), ("BALLYMAKAILY", "OCGT"),
)

#: Multi-shaft CCGTs: several generator records, one plant, one trip.  Keyed
#: on the PSS/E bus-name prefix of each member.
MODULES = {
    "HUNT_CT": "Huntstown 1", "HUNT_ST": "Huntstown 1",
    "TYNAGH": "Tynagh",
    "PBEGG4": "Poolbeg CCGT", "PBEGG5": "Poolbeg CCGT",
    "PBEGG6": "Poolbeg CCGT",
    "GEN_COOL": "Coolkeeragh CCGT",
    "BAFD_GA": "Ballylumford C", "BAFD_GB": "Ballylumford C",
    "BAFD_GC": "Ballylumford C",
}

#: Northern Ireland's small renewable clusters are not on W_ buses; they carry
#: PB = 0 and a site name.  Anything left after the thermal table, in NI,
#: with PB = 0 and not a biomass plant, is taken to be one of these.
NI_RENEWABLE_PREFIXES = ("RENEW_", "GARVAGH", "GLEN_ALT", "EGLISH",
                         "ORA MORE", "CREA", "BAME", "BALYKEEL")

SYNCHRONOUS = ("CCGT", "OCGT", "steam", "hydro", "pumped_storage")


def _technology(name: str, ident: str, pt: float, pb: float, area: int
                ) -> str:
    """What a generator record is, from its bus name and its limits."""
    upper = name.strip().upper()
    if upper in pypsa_net.INTERCONNECTORS:
        return "hvdc"
    if pt <= 0:
        # Zero-output machines: STATCOMs, SVCs, and Moneypoint 2's condenser
        # mode (ID "SC").  None of them generates real power.
        return "sync_condenser_record" if ident.strip() == "SC" \
            else "reactive"
    if upper.startswith("W_") or "WIND" in upper:
        return "wind"
    if upper.startswith("PV_"):
        return "solar"
    if upper.startswith("TURLG"):
        return "pumped_storage"
    if upper.startswith("HY_"):
        return "hydro"
    if pb < 0 and (abs(pb) >= 0.9 * pt or upper.startswith("BS_RENEW")):
        return "battery"
    for prefix, tech in STATION_TECHNOLOGY:
        if upper.startswith(prefix):
            return tech
    if psse.jurisdiction(pd.Series([area])).iloc[0] == "NI" and pb == 0 \
            and upper.startswith(NI_RENEWABLE_PREFIXES):
        return "wind"
    if pt < SMALL_UNIT_MW:
        return "small"
    return "unclassified"


def register(case: psse.Case) -> pd.DataFrame:
    """Every generator record in the case, in or out of service, classified.

    The whole register, not just the machines the case happens to run: the
    ensemble is over dispatch states, and a unit the winter-peak case left off
    is still a unit the optimiser may commit.
    """
    name = pypsa_net._clean(case.bus.set_index("I")["NAME"])
    area = case.bus.set_index("I")["AREA"].astype(int)
    g = case.generator.copy()
    g["bus_name"] = g["I"].astype(int).map(name)
    g["area"] = g["I"].astype(int).map(area)
    g["jurisdiction"] = psse.jurisdiction(g["area"]).values
    g["generator"] = [f"{int(i)}-{str(d).strip()}" for i, d in
                      zip(g["I"], g["ID"])]
    g["technology"] = [
        _technology(nm, str(i), float(pt), float(pb), int(a))
        for nm, i, pt, pb, a in zip(g["bus_name"], g["ID"], g["PT"], g["PB"],
                                    g["area"])]
    g["module"] = [
        next((MODULES[p] for p in MODULES if nm.upper().startswith(p)), gen)
        for nm, gen in zip(g["bus_name"], g["generator"])]
    return g


# --------------------------------------------------------------------------- #
# The clustered network
# --------------------------------------------------------------------------- #

@dataclass
class Topology:
    """A clustered network with no machines on it, and where everything goes.

    ``busmap`` maps every PSS/E bus number in the case - retained or
    aggregated away below 110 kV - to its cluster, so a generator or load
    record can be placed without knowing how it got there.
    """

    network: object
    busmap: dict
    case_name: str
    reports: dict = field(default_factory=dict)

    def cluster_of(self, psse_bus) -> str:
        return self.busmap[str(int(psse_bus))]


def _fill_coordinates(n) -> None:
    """Give every unplaced bus the position of its nearest placed neighbour.

    Star points of three-winding transformers and a few unmatched stations
    have no coordinate.  They are all within a hop or two of one that does,
    and for clustering, "same place as the busbar it hangs off" is right.
    """
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(n.buses.index)
    for comp in (n.lines, n.transformers):
        graph.add_edges_from(zip(comp["bus0"], comp["bus1"]))
    placed = n.buses.index[n.buses["x"].notna() & (n.buses["x"] != 0)]
    for bus in n.buses.index[~n.buses.index.isin(placed)]:
        lengths = nx.single_source_shortest_path_length(graph, bus)
        near = [b for b, _ in sorted(lengths.items(), key=lambda kv: kv[1])
                if b in placed]
        if near:
            n.buses.loc[bus, ["x", "y"]] = n.buses.loc[near[0], ["x", "y"]]


def _kmeans(points: np.ndarray, k: int, seed: int) -> np.ndarray:
    """Seeded k-means labels, with scipy rather than a new dependency."""
    from scipy.cluster.vq import kmeans2

    k = min(k, len(np.unique(points, axis=0)))
    _, labels = kmeans2(points, k, seed=seed, minit="++", iter=50)
    return labels


#: The per-unit base the reduced network is written on.  Every cluster node
#: is given this nominal voltage and every equivalent branch its reactance on
#: it, so that PyPSA's ohms-and-kV bookkeeping reproduces the system per-unit
#: values exactly.  It is a bookkeeping device, not a claim about voltages.
REDUCED_KV = 380.0


def _reduce(n, busmap: pd.Series):
    """Collapse a network onto its clusters, for a DC flow.

    Every line and transformer with its ends in two different clusters is
    kept, as its system per-unit series reactance; all the branches between
    one pair of clusters are then combined in parallel, reactances
    harmonically and ratings additively.  Branches inside a cluster vanish.
    This is what a geographical clustering does to a DC model and no more:
    it is not a Kron reduction, and the flows it gives are indicative.  They
    are not what this study measures.
    """
    import pypsa

    branches = []
    for _, line in n.lines.iterrows():
        z_base = float(n.buses.at[line["bus0"], "v_nom"]) ** 2 \
            / pypsa_net.SYSTEM_MVA
        branches.append((line["bus0"], line["bus1"],
                         float(line["x"]) / z_base, float(line["s_nom"])))
    for _, tr in n.transformers.iterrows():
        branches.append((tr["bus0"], tr["bus1"],
                         float(tr["x"]) * pypsa_net.SYSTEM_MVA
                         / float(tr["s_nom"]), float(tr["s_nom"])))
    frame = pd.DataFrame(branches, columns=["bus0", "bus1", "x_pu", "s_nom"])
    frame["c0"] = frame["bus0"].map(busmap)
    frame["c1"] = frame["bus1"].map(busmap)
    frame = frame[frame["c0"] != frame["c1"]].copy()
    frame["x_pu"] = frame["x_pu"].abs().clip(lower=1e-5)
    pair = [tuple(sorted(p)) for p in zip(frame["c0"], frame["c1"])]
    frame["a"], frame["b"] = zip(*pair)
    grouped = frame.groupby(["a", "b"]).agg(
        y=("x_pu", lambda x: (1.0 / x).sum()), s_nom=("s_nom", "sum"),
        count=("x_pu", "size")).reset_index()

    nc = pypsa.Network()
    nc.name = f"{n.name} clustered"
    xy = n.buses[["x", "y"]].astype(float).groupby(busmap).mean()
    jur = n.buses["jurisdiction"].groupby(busmap).agg(
        lambda s: s[s.isin(["IE", "NI"])].mode().iloc[0]
        if s.isin(["IE", "NI"]).any() else "XX")
    names = sorted(set(busmap))
    nc.add("Bus", names, v_nom=REDUCED_KV, carrier="AC",
           x=xy.reindex(names)["x"].values, y=xy.reindex(names)["y"].values)
    nc.buses["jurisdiction"] = ["XX" if c.startswith("HVDC") else jur[c]
                                for c in names]
    nc.buses["members"] = busmap.groupby(busmap).size().reindex(names).values
    z_base = REDUCED_KV ** 2 / pypsa_net.SYSTEM_MVA
    nc.add("Line", [f"{a}-{b}" for a, b in zip(grouped["a"], grouped["b"])],
           bus0=grouped["a"].values, bus1=grouped["b"].values,
           x=(1.0 / grouped["y"] * z_base).values, r=0.0,
           s_nom=grouped["s_nom"].values, carrier="AC")
    nc.lines["circuits"] = grouped["count"].values
    for name, link in n.links.iterrows():
        nc.add("Link", name, bus0=busmap[link["bus0"]],
               bus1=busmap[link["bus1"]], carrier="DC",
               p_nom=float(link["p_nom"]), p_min_pu=float(link["p_min_pu"]),
               p_max_pu=float(link["p_max_pu"]),
               efficiency=float(link["efficiency"]))
    nc.add("Carrier", ["AC", "DC"])
    return nc


def topology(case: psse.Case, clusters: dict = CLUSTERS, seed: int = SEED
             ) -> Topology:
    """The case's transmission network, clustered, with its machines removed.

    Built through the existing conversion path, :func:`pypsa_net.build` at
    the 110 kV floor, and clustered geographically within each jurisdiction
    so that no node straddles the border.  The HVDC far terminals and Moyle's
    Scottish end stay nodes of their own.
    """
    model = pypsa_net.build(case, min_kv=pypsa_net.TRANSMISSION_KV)
    found = os.path.join(GEOCODING_DIR, f"{case.name}.csv")
    if os.path.exists(found):
        pypsa_net._place(model, pd.read_csv(found))
    n = model.network
    _fill_coordinates(n)

    # Nothing is clustered but the wires.  Machines and loads are added back
    # afterwards, individually, from the register.
    n.remove("Generator", n.generators.index)
    n.remove("Load", n.loads.index)

    link_ends = set(n.links["bus0"]) | set(n.links["bus1"])
    far = [b for b in n.buses.index
           if n.buses.at[b, "jurisdiction"] == "XX"
           or (b in link_ends and pd.isna(n.buses.at[b, "x"]))]
    busmap = pd.Series("", index=n.buses.index, dtype=object)
    for b in far:
        busmap[b] = f"HVDC {n.buses.at[b, 'psse_name']}".strip()

    # Star buses carry jurisdiction "--"; they go with their neighbours.
    jur = n.buses["jurisdiction"].replace("--", np.nan)
    for bus in jur.index[jur.isna()]:
        near = n.transformers.loc[(n.transformers["bus0"] == bus)
                                  | (n.transformers["bus1"] == bus),
                                  ["bus0", "bus1"]].values.ravel()
        near = [b for b in near if b != bus and pd.notna(jur.get(b))]
        jur[bus] = jur[near[0]] if near else "IE"

    for j, k in clusters.items():
        members = [b for b in n.buses.index
                   if jur.get(b) == j and busmap[b] == ""]
        xy = n.buses.loc[members, ["x", "y"]].to_numpy(dtype=float)
        # Degrees of longitude are about 0.6 of a degree of latitude here.
        xy = xy * np.array([math.cos(math.radians(53.5)), 1.0])
        labels = _kmeans(xy, k, seed)
        for b, lab in zip(members, labels):
            busmap[b] = f"{j}{int(lab):02d}"

    nc = _reduce(n, busmap)

    full = {str(b): busmap[b] for b in busmap.index}
    aggregation = model.reports["aggregation"]
    for bus, parent in zip(aggregation["bus"], aggregation["parent"]):
        if str(parent) in full:
            full[str(bus)] = full[str(parent)]

    missing = [b for b in n.buses.index if not busmap[b]]
    if missing:
        raise ValueError(f"{len(missing)} buses were not assigned a cluster")
    return Topology(network=nc, busmap=full, case_name=case.name,
                    reports={"clustering": busmap.rename("cluster"),
                             "links": model.reports["links"]})


# --------------------------------------------------------------------------- #
# Committable modules
# --------------------------------------------------------------------------- #

def fleet(case: psse.Case, topo: Topology) -> pd.DataFrame:
    """The dispatchable synchronous fleet, one row per committable module.

    Records of one multi-shaft CCGT are summed: ``p_nom`` over their PT and
    ``mbase`` over their MBASE, so the module's kinetic energy is exactly the
    sum of its machines'.  Everything else is one record, one module.
    """
    reg = register(case)
    sync = reg[reg["technology"].isin(SYNCHRONOUS)
               & (reg["PT"].astype(float) >= SMALL_UNIT_MW)]
    rows = []
    for module, members in sync.groupby("module", sort=False):
        lead = members.sort_values("PT", ascending=False).iloc[0]
        rows.append({
            "module": module,
            "technology": lead["technology"],
            "members": ";".join(members["generator"]),
            "psse_bus": int(lead["I"]),
            "psse_bus_name": lead["bus_name"],
            "bus": topo.cluster_of(lead["I"]),
            "jurisdiction": lead["jurisdiction"],
            "p_nom": float(members["PT"].astype(float).sum()),
            "p_pump": float(-members["PB"].astype(float).clip(upper=0).sum()),
            "mbase": float(members["MBASE"].astype(float).sum()),
            "in_case": bool((members["STAT"].astype(int) == 1).any()),
        })
    units = pd.DataFrame(rows).set_index("module")
    units["large"] = (units["technology"].isin(("CCGT", "OCGT", "steam"))
                      & (units["p_nom"] >= LARGE_UNIT_MW))
    return units


def renewables(case: psse.Case, topo: Topology) -> pd.DataFrame:
    """Wind and solar records, with their cluster, for per-node aggregation."""
    reg = register(case)
    ren = reg[reg["technology"].isin(("wind", "solar"))].copy()
    ren["bus"] = [topo.cluster_of(i) for i in ren["I"]]
    ren["p_nom"] = ren["PT"].astype(float)
    return ren[["generator", "bus_name", "technology", "bus", "jurisdiction",
                "p_nom"]].reset_index(drop=True)


def load_shares(case: psse.Case, topo: Topology) -> pd.Series:
    """Each cluster's share of island demand, from the case's own load split."""
    import profiles

    w = profiles.load_weights(case)
    w["bus"] = [topo.cluster_of(i) for i in w["psse_bus"]]
    return w.groupby("bus")["weight"].sum()


def _cost_jitter(name: str) -> float:
    """A fixed +-COST_SPREAD factor per unit, from its name."""
    u = (zlib.crc32(name.encode()) % 10_000) / 10_000.0
    return 1.0 + COST_SPREAD * (2.0 * u - 1.0)


# --------------------------------------------------------------------------- #
# One scenario's dispatch problem
# --------------------------------------------------------------------------- #

@dataclass
class Window:
    """The hourly inputs to one scenario's commitment problem.

    ``wind`` and ``solar`` are capacity factors per cluster, ``hydro`` the
    run-of-river availability, all indexed by the window's snapshots.
    """

    snapshots: pd.DatetimeIndex
    demand: pd.Series
    wind: pd.DataFrame
    solar: pd.DataFrame
    hydro: pd.Series

    @property
    def target(self) -> pd.Timestamp:
        return self.snapshots[TARGET_HOUR]


@dataclass
class Setting:
    """The sampled, non-weather part of a scenario."""

    interconnectors: dict           # link -> MW, + import
    outages: tuple = ()             # modules forced out for the whole window
    condensers: int = 0             # synchronous condensers online


def dispatch_network(topo: Topology, units: pd.DataFrame,
                     ren: pd.DataFrame, shares: pd.Series, window: Window,
                     setting: Setting):
    """A PyPSA network ready to solve for one scenario."""
    n = topo.network.copy()
    n.remove("Generator", n.generators.index)
    n.remove("Load", n.loads.index)
    n.set_snapshots(window.snapshots)

    for carrier in ("wind", "solar", "shed", "import", "export", "AC", "DC",
                    *SYNCHRONOUS):
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)

    # -- demand, split by the case's own load pattern --------------------- #
    shares = shares / shares.sum()
    loads = pd.DataFrame(np.outer(window.demand.to_numpy(), shares.to_numpy()),
                         index=window.snapshots, columns=shares.index)
    n.add("Load", [f"load {b}" for b in shares.index], bus=shares.index,
          p_set=loads.set_axis([f"load {b}" for b in shares.index], axis=1))
    buses = list(shares.index)
    n.add("Generator", [f"shed {b}" for b in buses], bus=buses,
          carrier="shed", p_nom=1e5, marginal_cost=VOLL)

    # -- wind and solar, aggregated per cluster --------------------------- #
    for tech, cf in (("wind", window.wind), ("solar", window.solar)):
        cap = ren[ren["technology"] == tech].groupby("bus")["p_nom"].sum()
        cap = cap[cap > 0]
        names = [f"{tech} {b}" for b in cap.index]
        profile = cf.reindex(columns=cap.index).fillna(0.0).clip(0.0, 1.0)
        n.add("Generator", names, bus=cap.index, carrier=tech,
              p_nom=cap.values, marginal_cost=0.0,
              p_max_pu=profile.set_axis(names, axis=1))

    # -- committable modules ------------------------------------------------ #
    gen = units[(units["technology"] != "pumped_storage")
                & ~units.index.isin(setting.outages)]
    for tech, group in gen.groupby("technology"):
        t = TECHNOLOGY[tech]
        ramp_start = max(t["ramp"], t["p_min_pu"])
        kwargs = dict(
            bus=group["bus"].values, carrier=tech, p_nom=group["p_nom"].values,
            committable=True, p_min_pu=t["p_min_pu"],
            min_up_time=t["min_up"], min_down_time=t["min_down"],
            ramp_limit_up=t["ramp"], ramp_limit_down=t["ramp"],
            ramp_limit_start_up=ramp_start, ramp_limit_shut_down=ramp_start,
            # Every unit starts the window cold and free to start, so the
            # lead-in hours are the only place initial conditions show.
            up_time_before=0, down_time_before=WINDOW_H,
            start_up_cost=(t["start_up_cost"] * group["p_nom"]).values,
            marginal_cost=[t["marginal_cost"] * _cost_jitter(m)
                           for m in group.index])
        if tech == "hydro":
            kwargs["p_max_pu"] = pd.DataFrame(
                {m: window.hydro.clip(0.0, 1.0).values for m in group.index},
                index=window.snapshots)
        n.add("Generator", group.index, **kwargs)

    pumped = units[(units["technology"] == "pumped_storage")
                   & ~units.index.isin(setting.outages)]
    if len(pumped):
        ps = PUMPED_STORAGE
        n.add("StorageUnit", pumped.index, bus=pumped["bus"].values,
              carrier="pumped_storage", p_nom=pumped["p_nom"].values,
              p_min_pu=(-pumped["p_pump"] / pumped["p_nom"]).values,
              max_hours=ps["max_hours"],
              efficiency_store=ps["efficiency_store"],
              efficiency_dispatch=ps["efficiency_dispatch"],
              marginal_cost=ps["marginal_cost"], cyclic_state_of_charge=True)

    # -- interconnectors, pinned at the sampled setpoint ------------------- #
    for link, mw in setting.interconnectors.items():
        poles = n.links.index[n.links.index.str.startswith(link)]
        for pole in poles:
            share = float(mw) / len(poles)
            pu = share / float(n.links.at[pole, "p_nom"])
            n.links.loc[pole, ["p_min_pu", "p_max_pu"]] = pu
    # Far-end supply and sink for the pinned flows.
    for far in n.buses.index[n.buses["jurisdiction"] == "XX"]:
        cap = float(n.links.loc[(n.links["bus0"] == far)
                                | (n.links["bus1"] == far), "p_nom"].sum())
        n.add("Generator", f"{far} import", bus=far, carrier="import",
              p_nom=cap, marginal_cost=0.0)
        n.add("Generator", f"{far} export", bus=far, carrier="export",
              p_nom=cap, sign=-1.0, marginal_cost=0.0)
    return n


def _extra_functionality(units: pd.DataFrame, setting: Setting):
    """Minimum units on load and primary reserve cover, as linopy constraints.

    **SNSP, inertia and RoCoF are deliberately absent.**  They are outcomes to
    be measured, not constraints to be imposed: constraining any of them
    would stop the ensemble reaching the insecure region the comparison is
    about.  Do not add them here.
    """

    def extra(n, snapshots):
        m = n.model
        committed = [u for u in units.index if u in n.generators.index]
        status = m["Generator-status"].sel(name=committed)
        p = m["Generator-p"].sel(name=committed)

        # -- minimum units on load (OCU) ---------------------------------- #
        large = units.loc[committed]
        large = large[large["large"]]
        if MIN_UNITS_RULE == "split":
            for j, k in MIN_UNITS.items():
                names = list(large.index[large["jurisdiction"] == j])
                m.add_constraints(status.sel(name=names).sum("name") >= k,
                                  name=f"min_units_{j}")
        else:
            m.add_constraints(
                status.sel(name=list(large.index)).sum("name")
                >= MIN_UNITS_ALL_ISLAND, name="min_units_all_island")

        # -- primary operating reserve ------------------------------------ #
        tech = units.loc[committed, "technology"]
        cap = np.array([TECHNOLOGY[t]["por"] for t in tech]) \
            * units.loc[committed, "p_nom"].to_numpy()
        p_nom = units.loc[committed, "p_nom"].to_numpy()
        pmax = n.get_switchable_as_dense("Generator", "p_max_pu",
                                         snapshots)[committed]
        import xarray as xr
        coords = {"snapshot": snapshots, "name": committed}
        cap_da = xr.DataArray(np.broadcast_to(cap, (len(snapshots),
                                                    len(committed))),
                              coords=coords, dims=("snapshot", "name"))
        head_da = xr.DataArray(pmax.to_numpy() * p_nom, coords=coords,
                               dims=("snapshot", "name"))
        snap_ix = pd.Index(snapshots, name="snapshot")
        r = m.add_variables(lower=0, coords=[snap_ix,
                                             pd.Index(committed, name="name")],
                            name="Generator-por")
        m.add_constraints(r - cap_da * status <= 0, name="por_capability")
        m.add_constraints(r + p - head_da * status <= 0, name="por_headroom")
        total = r.sum("name")

        stores = [u for u in units.index if u in n.storage_units.index]
        if stores:
            store = m["StorageUnit-p_store"].sel(name=stores)
            rs = m.add_variables(lower=0, coords=[snap_ix,
                                                  pd.Index(stores, name="name")],
                                 name="StorageUnit-por")
            # Only a pumping unit is counted: it gives POR by dropping its
            # pump load.  A standstill unit cannot reach output inside 5 s
            # and the storage model has no status to say it is spinning, so
            # a generating unit's headroom is left out here (conservative)
            # and counted in the post-hoc volume, where "online" is known.
            m.add_constraints(rs - store <= 0, name="ps_pump_trip")
            total = total + rs.sum("name")

        short = m.add_variables(lower=0, coords=[snap_ix],
                                name="por_shortfall")
        # Each unit's own reserve cannot cover its own trip.
        m.add_constraints(total - r + short - POR_REQUIREMENT_FRACTION * p
                          >= 0, name="por_unit_cover")
        largest_import = max([0.0] + [float(v) for v in
                                      setting.interconnectors.values()])
        m.add_constraints(total + short >= POR_REQUIREMENT_FRACTION
                          * largest_import, name="por_import_cover")
        m.objective = m.objective + RESERVE_SHORTFALL_COST * short.sum()

    return extra


def solve(n, units: pd.DataFrame, setting: Setting,
          solver_options: dict | None = None) -> dict:
    """Solve one scenario's commitment problem; return status and timing."""
    import logging
    import warnings

    for name in ("pypsa", "linopy"):
        logging.getLogger(name).setLevel(logging.ERROR)
    # PyPSA 1.x announces default changes coming in 2.0 on every solve.
    # They do not change this model; the defaults in force are used.
    warnings.filterwarnings("ignore", category=FutureWarning,
                            module="pypsa")
    options = dict(SOLVER_OPTIONS, **(solver_options or {}))
    start = time.perf_counter()
    status, condition = n.optimize(
        solver_name=SOLVER, solver_options=options, log_to_console=False,
        progress=False,
        extra_functionality=_extra_functionality(units, setting))
    elapsed = time.perf_counter() - start
    info = {"status": status, "condition": condition, "solve_s": elapsed}
    if status == "ok" or condition in ("optimal", "time_limit"):
        sol = n.model.solution
        info["por_shortfall_mw"] = float(
            sol["por_shortfall"].sel(snapshot=n.snapshots[TARGET_HOUR]))
        info["objective"] = float(n.objective)
    return info


# --------------------------------------------------------------------------- #
# Weather and demand for a window
# --------------------------------------------------------------------------- #

def weather_year(case: psse.Case, year: int = 2024, seed: int = SEED
                 ) -> dict:
    """A synthetic year from :mod:`synthetic`, needing no network access.

    Open-Meteo is the better source where it is reachable (see
    ``profiles.py``); in this sandbox it is refused at the proxy, and the
    synthetic path is the documented stand-in.  See docs/ENSEMBLE.md.
    """
    import synthetic

    return synthetic.build(case, year=year, seed=seed)


def cluster_profiles(year: dict, ren: pd.DataFrame) -> tuple:
    """Per-cluster wind and solar capacity factors, capacity-weighted.

    A record with no synthetic profile - unplaced sites, and NI's renewable
    clusters that are not on W_ buses - gets its technology's fleet mean,
    which is the honest answer to "we do not know where this farm is".
    """
    pmax = year["p_max_pu"]
    out = {}
    for tech in ("wind", "solar"):
        members = ren[ren["technology"] == tech]
        fleet_mean = year["fleet"][tech] if tech in year["fleet"] \
            else pd.Series(0.0, index=pmax.index)
        cols = {}
        for bus, grp in members.groupby("bus"):
            series = [pmax[g] if g in pmax.columns else fleet_mean
                      for g in grp["generator"]]
            weights = grp["p_nom"].to_numpy()
            if weights.sum() <= 0:
                continue
            cols[bus] = sum(s * w for s, w in zip(series, weights)) \
                / weights.sum()
        out[tech] = pd.DataFrame(cols, index=pmax.index)
    return out["wind"], out["solar"]


def window(year: dict, wind: pd.DataFrame, solar: pd.DataFrame,
           hour: int, demand_mw: float | None = None) -> Window:
    """The window of hours whose TARGET_HOUR is hour-of-year ``hour``.

    ``demand_mw`` rescales the window's demand so that the target hour sits
    at the sampled level, keeping the synthetic year's shape around it.
    """
    index = year["demand"].index
    start = int(np.clip(hour - TARGET_HOUR, 0, len(index) - WINDOW_H))
    snaps = index[start:start + WINDOW_H]
    demand = year["demand"].loc[snaps].astype(float)
    if demand_mw is not None:
        demand = demand * (float(demand_mw) / float(demand.iloc[TARGET_HOUR]))
    return Window(snapshots=snaps, demand=demand, wind=wind.loc[snaps],
                  solar=solar.loc[snaps], hydro=year["fleet"]["hydro"]
                  .loc[snaps])


# --------------------------------------------------------------------------- #
# SNSP, EirGrid's way
# --------------------------------------------------------------------------- #

def snsp(wind_mw: float, solar_mw: float, flows: dict, demand_mw: float,
         pump_load_mw: float = 0.0, other_nonsync_mw: float = 0.0) -> float:
    """System non-synchronous penetration, as EirGrid defines it::

        SNSP = (non-synchronous generation + net interconnector imports)
               / (demand + net interconnector exports)

    with demand including pumped-storage consumption while pumping.  Wind,
    solar and HVDC imports are the non-synchronous sources.  It is not the
    wind/demand ratio: that omits imports from the top and pumping and
    exports from the bottom, and it biases the comparison against SNSP by
    making it a noisier function of the state than EirGrid's number is.
    """
    net = float(sum(flows.values()))
    num = float(wind_mw) + float(solar_mw) + float(other_nonsync_mw) \
        + max(net, 0.0)
    den = float(demand_mw) + float(pump_load_mw) + max(-net, 0.0)
    if den <= 0:
        raise ValueError("SNSP denominator must be positive")
    return num / den


# --------------------------------------------------------------------------- #
# The sampling design
#
# The ensemble is over dispatch states.  dP is derived from each state rather
# than sampled, which keeps both predictors functions of system state and the
# comparison fair: neither gets an input the other cannot see.
# --------------------------------------------------------------------------- #

#: Probability that a large unit is on forced outage for a scenario.  Irish
#: thermal plant has run forced-outage rates well above the European norm in
#: recent years; 10% is a round figure in that range, not a statistic.
FORCED_OUTAGE_RATE = 0.10

#: Default ensemble size.  **A smoke test, not a result**: enough to run the
#: whole pipeline inside one session.  scripts/run_ensemble.py is for the
#: 500-2,000 scenario run.
DEFAULT_N = 50

ENSEMBLE_DIR = "data/ensemble"

#: The fixed dimensions of the Latin hypercube, in order.  One more dimension
#: per large unit follows them, for its outage.
LHS_DIMENSIONS = ("hour", "demand", "EWIC", "Moyle", "Greenlink",
                  "condensers")


@dataclass
class Draw:
    """One row of the design, decoded."""

    scenario: int
    seed: int
    hour: int
    demand_mw: float
    setting: Setting
    restored: tuple = ()
    u: dict = field(default_factory=dict)


def design(n: int, units: pd.DataFrame, demand_range: tuple,
           vintage: str = DEFAULT_VINTAGE, seed: int = SEED,
           hours: int = 8784) -> list[Draw]:
    """A seeded Latin hypercube over weather, demand, flows, condensers, outages.

    ``demand_range`` is the vintage's own (SV, WP) demand pair.  Outages are
    drawn per large unit; where a draw would leave a jurisdiction unable to
    meet the minimum-units rule, the units with the least-extreme draws are
    returned to service until it can, and that is recorded - a state the real
    system cannot be put in is not a state worth sampling.
    """
    from scipy.stats import qmc

    import inertia

    large = list(units.index[units["large"]])
    dims = len(LHS_DIMENSIONS) + len(large)
    sample = qmc.LatinHypercube(d=dims, seed=seed).random(n)
    limits = INTERCONNECTOR_LIMITS[vintage]
    lo, hi = demand_range
    draws = []
    for k, row in enumerate(sample):
        u = dict(zip(LHS_DIMENSIONS, row[:len(LHS_DIMENSIONS)]))
        flows = {}
        for link in ("EWIC", "Moyle", "Greenlink"):
            a, b = limits[link]
            flows[link] = float(a + u[link] * (b - a))
        out_u = dict(zip(large, row[len(LHS_DIMENSIONS):]))
        out = [m for m in large if out_u[m] < FORCED_OUTAGE_RATE]
        restored = []
        for j, need in (MIN_UNITS.items() if MIN_UNITS_RULE == "split"
                        else [("all", MIN_UNITS_ALL_ISLAND)]):
            pool = [m for m in large
                    if j == "all" or units.at[m, "jurisdiction"] == j]
            while len([m for m in pool if m not in out]) < need:
                back = max((m for m in out if m in pool), key=out_u.get)
                out.remove(back)
                restored.append(back)
        draws.append(Draw(
            scenario=k, seed=seed,
            hour=int(min(hours - 1, u["hour"] * hours)),
            demand_mw=float(lo + u["demand"] * (hi - lo)),
            setting=Setting(interconnectors=flows, outages=tuple(out),
                            condensers=int(min(inertia.LCIS_UNITS,
                                               u["condensers"]
                                               * (inertia.LCIS_UNITS + 1)))),
            restored=tuple(restored), u={**u, **{f"out:{m}": v for m, v in
                                                  out_u.items()}}))
    return draws


# --------------------------------------------------------------------------- #
# The scenario record
#
# Enough to recompute every predictor and every outcome without re-solving:
# per-unit dispatch, commitment and kinetic energy, per-bus injection,
# demand, flows, both energies, SNSP, reserve by category, the reference
# incident and what it was, and the seed.
# --------------------------------------------------------------------------- #

@dataclass
class Context:
    """Everything a worker needs, built once per process."""

    vintage: str
    seed: int
    case_name: str
    topo: Topology
    units: pd.DataFrame
    ren: pd.DataFrame
    shares: pd.Series
    year: dict
    wind: pd.DataFrame
    solar: pd.DataFrame
    demand_range: tuple


def context(vintage: str = DEFAULT_VINTAGE, seed: int = SEED) -> Context:
    import synthetic

    wp, sv = VINTAGES[vintage]
    case = psse.read_raw(case_path(wp))
    topo = topology(case, seed=seed)
    units = fleet(case, topo)
    ren = renewables(case, topo)
    shares = load_shares(case, topo)
    year = weather_year(case, seed=seed)
    wind, solar = cluster_profiles(year, ren)
    states = synthetic.anchors()
    demand = states.set_index("case")["demand_mw"]
    return Context(vintage=vintage, seed=seed, case_name=case.name,
                   topo=topo, units=units, ren=ren, shares=shares, year=year,
                   wind=wind, solar=solar,
                   demand_range=(float(demand[sv]), float(demand[wp])))


def reserve_available(units: pd.DataFrame, p: pd.Series, online: pd.Series,
                      pmax_pu: pd.Series, category: str,
                      exclude: str | None = None) -> float:
    """Reserve the synchronised fleet can physically give, MW.

    Each online unit gives the lesser of its headroom and its technology's
    capability for the category; the tripped unit, if named, gives nothing.
    This is the volume the frequency layer uses: what the governors of the
    machines still spinning can deliver, not merely what was scheduled.
    """
    total = 0.0
    for name, row in units.iterrows():
        if not online.get(name, False) or name == exclude:
            continue
        if row["technology"] == "pumped_storage":
            output = float(p.get(name, 0.0))
            if output < 0:
                # A pumping unit's reserve is its pump load, dropped.
                total += -output
                continue
            frac = PUMPED_STORAGE[category]
            head = row["p_nom"] - output
        else:
            frac = TECHNOLOGY[row["technology"]][category]
            head = row["p_nom"] * float(pmax_pu.get(name, 1.0)) \
                - float(p.get(name, 0.0))
        total += max(0.0, min(frac * row["p_nom"], head))
    return total


def record(ctx: Context, draw: Draw, n, info: dict) -> tuple:
    """The scenario row, its per-unit rows and its per-bus rows."""
    import inertia

    units = ctx.units
    t = n.snapshots[TARGET_HOUR]
    gp = n.generators_t.p.loc[t]
    gstatus = n.generators_t.status.loc[t] if len(
        n.generators_t.status.columns) else pd.Series(dtype=float)
    sp = n.storage_units_t.p.loc[t] if len(n.storage_units) else \
        pd.Series(dtype=float)
    pmax = n.get_switchable_as_dense("Generator", "p_max_pu").loc[t]

    p = pd.Series(0.0, index=units.index)
    online = pd.Series(False, index=units.index)
    for name in units.index:
        if name in gstatus.index:
            p[name] = float(gp[name])
            online[name] = bool(gstatus[name] > 0.5)
        elif name in sp.index:
            p[name] = float(sp[name])
            online[name] = abs(float(sp[name])) > inertia.ONLINE_TOLERANCE_MW
    pump = (-p[(units["technology"] == "pumped_storage") & (p < 0)])

    carrier = n.generators["carrier"]
    wind_mw = float(gp[carrier == "wind"].sum())
    solar_mw = float(gp[carrier == "solar"].sum())
    avail = pmax * n.generators["p_nom"]
    shed_mw = float(gp[carrier == "shed"].sum())
    flows = {}
    for link in draw.setting.interconnectors:
        poles = n.links.index[n.links.index.str.startswith(link)]
        # Flow at the island end, positive into the island.
        flows[link] = float(-n.links_t.p1.loc[t, poles].sum()) \
            if len(poles) else 0.0
    demand = float(n.loads_t.p_set.loc[t].sum())

    energy = inertia.system_energy(units, online, draw.setting.condensers)
    infeed = p[online & (units["technology"] != "pumped_storage")]
    infeed = pd.concat([infeed, p[online & (units["technology"]
                                            == "pumped_storage") & (p > 0)]])
    ri = inertia.reference_incident(infeed, flows, pump_load=pump)
    e_post = inertia.post_trip_energy(energy["E_mws"], energy["components"],
                                      ri["incident_element"],
                                      ri["incident_type"])
    trip = ri["incident_element"] if ri["incident_type"] == "unit" else None

    sol = n.model.solution
    por_sched = float(sol["Generator-por"].sel(snapshot=t).sum())
    if "StorageUnit-por" in sol:
        por_sched += float(sol["StorageUnit-por"].sel(snapshot=t).sum())

    large = units["large"] & online
    row = {
        "scenario": draw.scenario, "seed": draw.seed, "vintage": ctx.vintage,
        "case": ctx.case_name, "hour_of_year": draw.hour,
        "snapshot": str(t),
        **{f"u_{k}": float(v) for k, v in draw.u.items()
           if not k.startswith("out:")},
        "demand_mw": demand, "demand_sampled_mw": draw.demand_mw,
        "pump_load_mw": float(pump.sum()),
        "wind_mw": wind_mw, "wind_available_mw":
            float(avail[carrier == "wind"].sum()),
        "solar_mw": solar_mw, "solar_available_mw":
            float(avail[carrier == "solar"].sum()),
        "wind_cf": float(ctx.year["fleet"]["wind"].loc[t]),
        "sync_generation_mw": float(p[online & (p > 0)].sum()),
        **{f"flow_{k}_mw": v for k, v in flows.items()},
        "net_import_mw": float(sum(flows.values())),
        "shed_mw": shed_mw,
        "snsp": snsp(wind_mw, solar_mw, flows, demand, float(pump.sum())),
        "units_online": int(online.sum()),
        "large_online_IE": int((large & (units["jurisdiction"] == "IE")).sum()),
        "large_online_NI": int((large & (units["jurisdiction"] == "NI")).sum()),
        "condensers": draw.setting.condensers,
        "E_pre_mws": energy["E_mws"],
        "E_machines_mws": energy["E_machines_mws"],
        "E_condensers_mws": energy["E_condensers_mws"],
        "E_post_mws": e_post,
        **ri,
        "incident_mw": float(ri["lsi_mw"]),
        "incident_h_s": inertia.machine_h(units.at[trip, "technology"])
        if trip else 0.0,
        "incident_mbase": float(units.at[trip, "mbase"]) if trip else 0.0,
        "por_scheduled_mw": por_sched,
        "por_available_mw": reserve_available(units, p, online, pmax, "por",
                                              exclude=trip),
        "sor_available_mw": reserve_available(units, p, online, pmax, "sor",
                                              exclude=trip),
        "por_shortfall_mw": info.get("por_shortfall_mw", np.nan),
        "outages": ";".join(draw.setting.outages),
        "outages_restored": ";".join(draw.restored),
        "condition": info["condition"], "solve_s": info["solve_s"],
    }
    unit_rows = pd.DataFrame({
        "scenario": draw.scenario, "module": units.index,
        "technology": units["technology"].values,
        "jurisdiction": units["jurisdiction"].values,
        "bus": units["bus"].values, "p_nom": units["p_nom"].values,
        "mbase": units["mbase"].values, "p_mw": p.values,
        "online": online.values,
        "forced_out": units.index.isin(draw.setting.outages),
        "H_s": [inertia.machine_h(tc) for tc in units["technology"]],
        "E_mws": energy["components"].reindex(units.index).values,
    })
    bus_rows = pd.DataFrame({
        "scenario": draw.scenario, "bus": n.buses.index,
        "injection_mw": n.buses_t.p.loc[t].reindex(n.buses.index).values,
    })
    return row, unit_rows, bus_rows


# --------------------------------------------------------------------------- #
# Running it
# --------------------------------------------------------------------------- #

_CTX: Context | None = None


def _init_worker(vintage: str, seed: int) -> None:
    global _CTX
    _CTX = context(vintage, seed)


def run_draw(draw: Draw, ctx: Context | None = None) -> tuple:
    """Solve one scenario and return its three record tables."""
    ctx = ctx or _CTX
    win = window(ctx.year, ctx.wind, ctx.solar, draw.hour, draw.demand_mw)
    n = dispatch_network(ctx.topo, ctx.units, ctx.ren, ctx.shares, win,
                         draw.setting)
    info = solve(n, ctx.units, draw.setting)
    return record(ctx, draw, n, info)


def _write(directory: str, scenario: int, tables: tuple) -> None:
    row, unit_rows, bus_rows = tables
    for name, frame in (("scenarios", pd.DataFrame([row])),
                        ("units", unit_rows), ("buses", bus_rows)):
        path = os.path.join(directory, name)
        os.makedirs(path, exist_ok=True)
        frame.to_parquet(os.path.join(path, f"part-{scenario:05d}.parquet"),
                         index=False)


def done(directory: str) -> set:
    path = os.path.join(directory, "scenarios")
    if not os.path.isdir(path):
        return set()
    return {int(f[5:10]) for f in os.listdir(path)
            if f.startswith("part-") and f.endswith(".parquet")}


def run(n: int = DEFAULT_N, seed: int = SEED, vintage: str = DEFAULT_VINTAGE,
        directory: str | None = None, workers: int = 1,
        verbose: bool = True) -> str:
    """Solve the ensemble, writing each scenario as soon as it is solved.

    One parquet part per scenario per table, so a run that is stopped is a
    usable partial ensemble and a re-run with the same arguments resumes
    where it left off.  The design is computed up front from the seed, so a
    scenario's inputs do not depend on which worker solves it or when.
    """
    directory = directory or os.path.join(ENSEMBLE_DIR,
                                          f"{vintage}_seed{seed}_n{n}")
    os.makedirs(directory, exist_ok=True)
    ctx = context(vintage, seed)
    draws = design(n, ctx.units, ctx.demand_range, vintage, seed,
                   hours=len(ctx.year["demand"]))
    with open(os.path.join(directory, "design.json"), "w") as fh:
        json.dump({"n": n, "seed": seed, "vintage": vintage,
                   "case": ctx.case_name, "window_h": WINDOW_H,
                   "target_hour": TARGET_HOUR,
                   "forced_outage_rate": FORCED_OUTAGE_RATE,
                   "min_units_rule": MIN_UNITS_RULE,
                   "demand_range_mw": ctx.demand_range}, fh, indent=2)
    todo = [d for d in draws if d.scenario not in done(directory)]
    start = time.perf_counter()
    if workers <= 1:
        for k, d in enumerate(todo, 1):
            _write(directory, d.scenario, run_draw(d, ctx))
            if verbose:
                print(f"  {k}/{len(todo)} scenario {d.scenario} "
                      f"({time.perf_counter() - start:.0f} s)", flush=True)
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(workers, initializer=_init_worker,
                                 initargs=(vintage, seed)) as pool:
            futures = {pool.submit(run_draw, d): d for d in todo}
            for k, fut in enumerate(as_completed(futures), 1):
                d = futures[fut]
                _write(directory, d.scenario, fut.result())
                if verbose:
                    print(f"  {k}/{len(todo)} scenario {d.scenario} "
                          f"({time.perf_counter() - start:.0f} s)",
                          flush=True)
    return directory


def load(directory: str) -> dict:
    """Read an ensemble back, complete or partial."""
    out = {}
    for name in ("scenarios", "units", "buses"):
        path = os.path.join(directory, name)
        out[name] = pd.read_parquet(path) if os.path.isdir(path) \
            else pd.DataFrame()
    if len(out["scenarios"]):
        out["scenarios"] = out["scenarios"].sort_values("scenario") \
            .reset_index(drop=True)
    return out


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #

def case_path(name: str) -> str:
    return os.path.join(STUDY_DIR, f"{name}.raw")


def run_time(vintage: str, hour: int, out: str | None) -> int:
    """Build and solve one scenario, and report the wall-clock time."""
    wp, _ = VINTAGES[vintage]
    t0 = time.perf_counter()
    case = psse.read_raw(case_path(wp))
    topo = topology(case)
    units = fleet(case, topo)
    ren = renewables(case, topo)
    shares = load_shares(case, topo)
    year = weather_year(case)
    wind, solar = cluster_profiles(year, ren)
    t_build = time.perf_counter() - t0
    win = window(year, wind, solar, hour)
    setting = Setting(interconnectors={"EWIC": 300.0, "Moyle": 200.0,
                                       "Greenlink": 0.0})
    n = dispatch_network(topo, units, ren, shares, win, setting)
    info = solve(n, units, setting)
    target = win.target
    committed = n.generators_t.status.loc[target] if len(
        n.generators_t.status.columns) else pd.Series(dtype=float)
    result = {
        "vintage": vintage, "hour_of_year": hour, "target": str(target),
        "buses": len(n.buses), "lines": len(n.lines),
        "committable_units": int(n.generators["committable"].sum()),
        "storage_units": len(n.storage_units), "snapshots": len(n.snapshots),
        "build_s": round(t_build, 1), "solve_s": round(info["solve_s"], 2),
        "status": info["status"], "condition": info["condition"],
        "units_on_at_target": int((committed > 0.5).sum()),
        "demand_mw": round(float(win.demand.loc[target]), 1),
        "por_shortfall_mw": info.get("por_shortfall_mw"),
        "solver": SOLVER, "solver_options": SOLVER_OPTIONS,
        "cpu_count": os.cpu_count(),
    }
    print(json.dumps(result, indent=2))
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w") as fh:
            json.dump(result, fh, indent=2)
    return 0 if info["status"] == "ok" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("time", help="solve one scenario and time it")
    t.add_argument("--vintage", default=DEFAULT_VINTAGE, choices=VINTAGES)
    t.add_argument("--hour", type=int, default=400)
    t.add_argument("--out", default="docs/ensemble_timing.json")
    r = sub.add_parser("run", help="solve the ensemble")
    r.add_argument("--n", type=int, default=DEFAULT_N)
    r.add_argument("--seed", type=int, default=SEED)
    r.add_argument("--vintage", default=DEFAULT_VINTAGE, choices=VINTAGES)
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--out", default=None, help="output directory")
    args = parser.parse_args(argv)
    if args.command == "time":
        return run_time(args.vintage, args.hour, args.out)
    if args.command == "run":
        print(run(args.n, args.seed, args.vintage, args.out, args.workers))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
