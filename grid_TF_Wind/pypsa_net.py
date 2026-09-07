"""TYTFS PSS/E cases as PyPSA networks.

What this is
------------
The layer between :mod:`psse`, which reads EirGrid's TYTFS 2024 v35 raw files
into DataFrames and does nothing else, and PyPSA, which wants physical units,
a slack bus per synchronous island, and no three-winding transformers.  It
builds one :class:`pypsa.Network` per case at a chosen voltage floor, and a
set of report tables that say what it did to every record it touched.

Every conversion decision is written down in ``docs/PHASE2_PYPSA.md`` with the
measurement behind it.  The short version, because these are the ones that
silently change results:

System base
    100 MVA, read from the case header (``SBASE``) and asserted, not assumed.
    PSS/E branch impedances are pu on that base and the bus base kV; PyPSA
    wants line impedances in ohms and transformer impedances in pu on the
    transformer's own rating, so both conversions are explicit below.

Ratings
    ``RATE1`` is the continuous rating and the only one used for ``s_nom``.
    ``RATE2`` equals ``RATE1`` in every record of every case; ``RATE3`` is
    1.1 x ``RATE1`` where it differs at all.  That is the normal / long-term
    emergency / short-term emergency triple, with the long-term emergency
    rating not distinguished from normal.  All three are carried into
    ``branch_ratings.csv`` so a contingency study can pick a different one.

Unrated elements
    ``9999`` and ``0`` both mean "no limit stated".  All 18 of them in
    WP2024's transmission network are zero-impedance station couplers -
    busbar sections, capacitor and reactor stubs, generator terminal ties -
    not circuits with a forgotten rating.  They get a bound derived from what
    is actually attached to them, and every one is listed in
    ``rating_exceptions.csv``.

The sub-110 kV tail
    ``min_kv`` chooses.  ``110`` gives the transmission network - 547 buses in
    one AC island, plus the GB terminal of Moyle - with every sub-threshold
    load and generator moved to the nearest retained bus by series reactance,
    because 100% of generation and 99.8% of load sits below 110 kV and a
    network that merely drops those buses has nothing in it.  ``0`` gives the
    whole case.

DC links
    Moyle is the case's only ``two_terminal_dc`` record - two of them, one per
    pole.  East-West and Greenlink are PV buses with generator records
    instead.  All three become :class:`pypsa.Link`, so the exchange is a
    controllable flow on a branch rather than a machine.

Not carried
    Fixed and switched shunts.  :mod:`psse` skips both sections, so this
    network has no reactive compensation and a full AC power flow will not
    reproduce the case's voltages.  DC power flow and LOPF ignore reactive
    power and are unaffected.  ``psse.py`` says which sections it skips;
    nothing here silently invents them.

Usage
-----
    import psse, pypsa_net

    case = psse.read_raw("data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw")
    model = pypsa_net.build(case, min_kv=110.0)     # transmission only
    model = pypsa_net.build(case, min_kv=0.0)       # the whole case
    model.network                                    # pypsa.Network
    model.reports                                    # dict of DataFrames

    python pypsa_net.py build                        # every case, both scopes
    python pypsa_net.py verify                       # connectivity, DC PF, LOPF
"""

from __future__ import annotations

import argparse
import glob
import math
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import psse

# --------------------------------------------------------------------------- #
# Conversion constants
#
# Anything here that could have been read from the file is read from the file
# and checked against the constant instead of replacing it.
# --------------------------------------------------------------------------- #

#: The system MVA base the per-unit quantities are on.  Asserted against every
#: case's SBASE field rather than assumed: PSS/E allows any value, and a case
#: on a different base would put every impedance out by that ratio.
SYSTEM_MVA = 100.0

#: The voltage floor that separates transmission from the distribution stub
#: the transmission model carries to hang load off.
TRANSMISSION_KV = 110.0

#: The rating column used for ``s_nom``.  See the module docstring.
CONTINUOUS_RATE = "RATE1"

#: Rating values that mean "no limit stated" rather than a number.
UNRATED = (0.0, 9999.0)

#: What an unrated element keeps when no bound can be derived for it: the
#: file's own non-answer.  Large enough never to bind, finite so that an LOPF
#: stays bounded, and flagged in every report so it is never mistaken for a
#: rating.
UNRATED_FALLBACK_MVA = 9999.0

#: An element at or below this series reactance, with no length, is a station
#: coupler rather than a circuit: a busbar section, a capacitor or reactor
#: stub, a generator terminal tie.  Every unrated element in the transmission
#: network is one of these, and none of them is anywhere near the threshold -
#: they run to 0.0001 pu, with one SVC tie at 0.01.
COUPLER_X_PU = 0.01

#: PSS/E bus type codes.
PQ_BUS, PV_BUS, SWING_BUS, ISOLATED_BUS = 1, 2, 3, 4

#: The three cross-border links, keyed by the PSS/E name of the converter bus
#: on the island side of the interconnector.  Moyle is the only one in the
#: two-terminal DC section; East-West and Greenlink are modelled as PV buses
#: with a generator record, so their far terminal does not exist in the case
#: and is created here.  ``far`` is None where the case already has the far
#: bus (Moyle's SCOTLAND).  Ratings come from the case's own generator record
#: for that bus - PT for import, |PB| for export - and are checked on build.
INTERCONNECTORS = {
    "SCOTLAND": dict(link="Moyle", far=None, dc_section=True),
    "EASTWEST": dict(link="EWIC", far="GB_EWIC", dc_section=False),
    "GREENLINK": dict(link="Greenlink", far="GB_GREENLINK", dc_section=False),
}

#: Carrier inferred from the generator's bus name.  The raw format carries no
#: fuel type, so this is the file's own naming convention and nothing more:
#: prefixes first, then whole-name keywords.  Everything else is "unknown",
#: which is most of the fleet and is reported as such.
CARRIER_PREFIXES = {"W_": "wind", "PV_": "solar", "HY_": "hydro",
                    "BS_": "biomass"}
CARRIER_KEYWORDS = (("CCGT", "gas"), ("OCGT", "gas"), ("GT", "gas"),
                    ("WIND", "wind"), ("HYDRO", "hydro"), ("PV", "solar"))

#: Marginal costs, EUR/MWh, by inferred carrier.  **Not from the file** - the
#: raw format has no cost data at all.  They exist so that an LOPF is a
#: well-posed problem with a merit order in roughly the right order, and are
#: written into the exported CSVs so that whatever a downstream study does
#: with them, it is doing it to numbers it can see.
PLACEHOLDER_COST = {"wind": 0.0, "solar": 0.0, "hydro": 1.0, "biomass": 40.0,
                    "gas": 90.0, "unknown": 60.0, "import": 150.0,
                    "export": 0.0}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _clean(series: pd.Series) -> pd.Series:
    """Strip PSS/E's fixed-width padding off a text column."""
    return series.fillna("").astype(str).str.strip()


def _rated(value: float) -> bool:
    """Is this rating a number, or one of PSS/E's two ways of saying none?"""
    return bool(np.isfinite(value)) and float(value) not in UNRATED


def carrier_of(bus_name: str) -> str:
    """Infer a generator's carrier from the name of the bus it sits on."""
    name = bus_name.strip().upper()
    for prefix, carrier in CARRIER_PREFIXES.items():
        if name.startswith(prefix):
            return carrier
    for keyword, carrier in CARRIER_KEYWORDS:
        if keyword in name:
            return carrier
    return "unknown"


def station_of(bus_name: str) -> str:
    """The station a bus belongs to, for grouping and for geocoding.

    PSS/E names are twelve characters, so a station's buses differ by a
    busbar suffix that the truncation makes inconsistent: CLOGHER four times,
    CAST1A and CAST1B, COOL1 and COOL1-, ENNK_PST twice.  This strips the
    decorations the file uses - trailing busbar letters and digits, the
    ``_CAP``/``_SVC``/``_PST`` device suffixes, the ``HY_``/``W_``/``PV_``
    generator prefixes - and leaves the station.  It is a grouping key, not a
    claim about what the station is called.
    """
    name = bus_name.strip().upper()
    for prefix in ("HY_", "W_", "PV_", "BS_", "TEG ", "GEN_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in ("_CAP", "_SVC", "_PST", "_DUM", "_ZER", " T", " ESS"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    # NIE's six-character codes: ANTR1A, COLE1-, KILL1-CL, MAGF2-.
    name = name.rstrip("-")
    while name and name[-1] in "AB" and len(name) > 4 and name[-2].isdigit():
        name = name[:-1]
    return name.strip()


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #

@dataclass
class Model:
    """A built network and the paper trail behind it."""

    network: object                       # pypsa.Network, imported lazily
    case_name: str
    min_kv: float
    reports: dict = field(default_factory=dict)

    @property
    def scope(self) -> str:
        """``transmission`` or ``full``, for naming output directories."""
        return "transmission" if self.min_kv > 0 else "full"

    def __repr__(self) -> str:
        n = self.network
        return (f"Model({self.case_name}/{self.scope}: buses={len(n.buses)} "
                f"lines={len(n.lines)} transformers={len(n.transformers)} "
                f"links={len(n.links)} generators={len(n.generators)} "
                f"loads={len(n.loads)})")


# --------------------------------------------------------------------------- #
# Stage 1: the electrical elements, in system per-unit
#
# Branches, two-winding transformers and the three legs of every three-winding
# transformer, all reduced to a single table of two-ended elements on the
# 100 MVA system base.  Everything after this stage works from that table, so
# the PSS/E conventions - CW, CZ, the star equivalent, the winding SBASEs -
# are handled exactly once, here.
# --------------------------------------------------------------------------- #

def _branch_elements(case: psse.Case, kv: pd.Series) -> pd.DataFrame:
    """AC branches as elements.  R, X, B are already pu on the system base."""
    df = case.branch
    live = df[df["STAT"] == 1]
    rate = live[CONTINUOUS_RATE].astype(float)
    return pd.DataFrame({
        "name": [f"{int(i)}-{int(j)}-{c.strip()}"
                 for i, j, c in zip(live["I"], live["J"], live["CKT"])],
        "kind": "line",
        "bus0": live["I"].astype(int).astype(str).values,
        "bus1": live["J"].astype(int).astype(str).values,
        "r_pu": live["R"].astype(float).values,
        "x_pu": live["X"].astype(float).values,
        "b_pu": live["B"].astype(float).values,
        "s_nom": np.where(rate.map(_rated), rate, np.nan),
        "tap_ratio": 1.0,
        "phase_shift": 0.0,
        "length": live["LEN"].astype(float).fillna(0.0).values,
        "v_nom": live["I"].astype(int).map(kv).values,
        "psse_i": live["I"].astype(int).values,
        "psse_j": live["J"].astype(int).values,
        "psse_ckt": _clean(live["CKT"]).values,
    })


def _winding_out(stat: float, winding: int) -> bool:
    """Is this winding out of service?

    ``STAT`` is 1 for a wholly in-service transformer and 0 for a wholly
    out-of-service one.  For a three-winding transformer 2, 3 and 4 take one
    winding out: 2 is winding 2, 3 is winding 3, 4 is winding 1.
    """
    stat = int(stat or 0)
    if stat == 0:
        return True
    return stat in (2, 3, 4) and winding == {2: 2, 3: 3, 4: 1}[stat]


def _z_on_system_base(r: float, x: float, cz: int, winding_mva: float
                      ) -> tuple[float, float]:
    """Convert a transformer impedance onto the system base.

    ``CZ`` says what base the record's R and X are on: 1 is already the
    system base, 2 is the winding's own MVA base (``SBASE``), 3 is a load
    loss in watts with |Z| in pu.  Only 1 and 2 occur in these cases - 1308
    and 2 records respectively - and 3 raises rather than being guessed at.
    """
    cz = int(cz)
    if cz == 1:
        return r, x
    if cz == 2:
        if not (winding_mva and np.isfinite(winding_mva)) or winding_mva <= 0:
            raise ValueError(f"CZ=2 transformer with winding base "
                             f"{winding_mva!r}: cannot rebase its impedance")
        scale = SYSTEM_MVA / float(winding_mva)
        return r * scale, x * scale
    raise ValueError(f"transformer impedance code CZ={cz} is not handled; "
                     "these cases only use 1 (system base) and 2 (winding "
                     "base), and CZ=3 is a load loss in watts, not an "
                     "impedance to be rescaled")


def _two_winding_elements(case: psse.Case, kv: pd.Series) -> pd.DataFrame:
    """Two-winding transformers as elements.

    ``CW`` is 1 in every record of every case, so ``WINDV`` is already pu of
    the bus base kV and the tap ratio is ``WINDV1 / WINDV2`` with no unit
    conversion.  ``CM`` is 1 and both magnetising terms are zero throughout,
    so there is no magnetising branch to carry.
    """
    df = case.transformer
    live = df[(df["WINDINGS"] == 2) & (df["STAT"] != 0)]
    rows = []
    for _, t in live.iterrows():
        if int(t["CW"]) != 1:
            raise ValueError(f"transformer {t['NAME']!r} has CW={t['CW']}; "
                             "only CW=1 (winding ratios in pu of bus base "
                             "kV) is handled")
        r, x = _z_on_system_base(float(t["R1_2"]), float(t["X1_2"]),
                                 t["CZ"], t["SBASE1_2"])
        rate = float(t["RATE1_1"])
        rows.append({
            "name": f"T{int(t['I'])}-{int(t['J'])}-{str(t['CKT']).strip()}",
            "kind": "transformer",
            "bus0": str(int(t["I"])), "bus1": str(int(t["J"])),
            "r_pu": r, "x_pu": x, "b_pu": 0.0,
            "s_nom": rate if _rated(rate) else np.nan,
            "tap_ratio": float(t["WINDV1"]) / float(t["WINDV2"]),
            "phase_shift": float(t["ANG1"] or 0.0),
            "length": 0.0,
            "v_nom": kv.get(int(t["I"]), np.nan),
            "psse_i": int(t["I"]), "psse_j": int(t["J"]),
            "psse_ckt": str(t["CKT"]).strip(),
        })
    return pd.DataFrame(rows)


def _three_winding_elements(case: psse.Case, kv: pd.Series
                            ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Three-winding transformers as a star bus and three legs.

    PyPSA has no three-winding transformer, so each record becomes the
    textbook star equivalent: a new bus at the star point and one two-winding
    transformer per winding, with

        Z1 = (Z12 + Z31 - Z23) / 2
        Z2 = (Z12 + Z23 - Z31) / 2
        Z3 = (Z31 + Z23 - Z12) / 2

    all on the system base.  Winding 1's leg reactance comes out negative in
    24 of WP2024's 109 records, which is what an autotransformer's star
    equivalent does and not an error; it is carried through as it stands.

    The star bus takes winding 1's base kV, which is what ``VMSTAR`` in the
    record is expressed on, and the record's solved star voltage and angle
    are carried onto it so the case's own answer survives the split.
    """
    df = case.transformer
    live = df[(df["WINDINGS"] == 3) & (df["STAT"] != 0)]
    stars, legs = [], []
    for _, t in live.iterrows():
        if int(t["CW"]) != 1:
            raise ValueError(f"transformer {t['NAME']!r} has CW={t['CW']}")
        tag = (f"{int(t['I'])}-{int(t['J'])}-{int(t['K'])}-"
               f"{str(t['CKT']).strip()}")
        star = f"star:{tag}"
        z = {}
        for label, (rc, xc, sb) in {
            "12": ("R1_2", "X1_2", "SBASE1_2"),
            "23": ("R2_3", "X2_3", "SBASE2_3"),
            "31": ("R3_1", "X3_1", "SBASE3_1"),
        }.items():
            z[label] = complex(*_z_on_system_base(
                float(t[rc] or 0.0), float(t[xc] or 0.0), t["CZ"], t[sb]))
        arm = {
            1: (z["12"] + z["31"] - z["23"]) / 2,
            2: (z["12"] + z["23"] - z["31"]) / 2,
            3: (z["31"] + z["23"] - z["12"]) / 2,
        }
        stars.append({
            "name": star,
            "v_nom": float(kv.get(int(t["I"]), np.nan)),
            "vm": float(t["VMSTAR"] or 1.0),
            "va": float(t["ANSTAR"] or 0.0),
            "of": tag,
        })
        for w, end in ((1, int(t["I"])), (2, int(t["J"])), (3, int(t["K"]))):
            if _winding_out(t["STAT"], w):
                continue
            rate = float(t[f"RATE{w}_1"])
            legs.append({
                "name": f"T{tag}-w{w}",
                "kind": "transformer",
                # bus0 is the star so that every leg's tap ratio is the
                # winding's own WINDV, referred to the star point.
                "bus0": star, "bus1": str(end),
                "r_pu": arm[w].real, "x_pu": arm[w].imag, "b_pu": 0.0,
                "s_nom": rate if _rated(rate) else np.nan,
                "tap_ratio": 1.0 / float(t[f"WINDV{w}"] or 1.0),
                "phase_shift": -float(t[f"ANG{w}"] or 0.0),
                "length": 0.0,
                "v_nom": float(kv.get(end, np.nan)),
                "psse_i": int(t["I"]), "psse_j": end,
                "psse_ckt": str(t["CKT"]).strip(),
            })
    columns = ["name", "kind", "bus0", "bus1", "r_pu", "x_pu", "b_pu",
               "s_nom", "tap_ratio", "phase_shift", "length", "v_nom",
               "psse_i", "psse_j", "psse_ckt"]
    return (pd.DataFrame(stars, columns=["name", "v_nom", "vm", "va", "of"]),
            pd.DataFrame(legs, columns=columns))


def elements(case: psse.Case) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every in-service two-ended element, and the star buses they need."""
    kv = case.bus.set_index("I")["BASKV"]
    stars, legs = _three_winding_elements(case, kv)
    parts = [_branch_elements(case, kv), _two_winding_elements(case, kv), legs]
    el = pd.concat([p for p in parts if len(p)], ignore_index=True)
    return stars, el


# --------------------------------------------------------------------------- #
# Stage 2: ratings
#
# 9999 and 0 both mean "no limit stated".  Neither can go into s_nom: 9999 MVA
# is not a rating, and 0 MVA would make the element unusable in an LOPF and
# is the more dangerous of the two because it looks like a number.
# --------------------------------------------------------------------------- #

def _is_coupler(element) -> bool:
    """Is this element a station coupler rather than a circuit?"""
    return (abs(float(element["x_pu"])) <= COUPLER_X_PU
            and float(element["length"] or 0.0) == 0.0)


def _fill_unrated(el: pd.DataFrame) -> pd.DataFrame:
    """Give every unrated element a limit, and say where the limit came from.

    Two different things are unrated, and they get different answers.

    Station couplers - every unrated element in the transmission network is
    one: busbar sections, capacitor and reactor stubs, generator terminal
    ties, all zero-impedance and zero-length - are bounded by what is attached
    to them.  A coupler can carry no more than the weaker of the two sides it
    joins can deliver, so the bound is the smaller of the two ends' rated
    incident capacity.  That is a real limit rather than a number picked to be
    large.

    Everything else keeps the file's ``9999``.  These are the sub-110 kV
    distribution transformers, 1,164 of them, and there is no honest way to
    infer a rating for a 110/38 kV transformer from the feeders leaving the
    38 kV bus - load taps off that bus directly, so the feeders bound nothing.
    Inventing a bound there produces constraints that bind on the case's own
    solved flows, which is how this rule was arrived at rather than the other
    one.
    """
    incident: dict[str, float] = {}
    for _, e in el.iterrows():
        if not np.isfinite(e["s_nom"]):
            continue
        for end in (e["bus0"], e["bus1"]):
            incident[end] = incident.get(end, 0.0) + float(e["s_nom"])

    filled, notes = [], []
    for _, e in el.iterrows():
        if np.isfinite(e["s_nom"]):
            filled.append(float(e["s_nom"]))
            notes.append("")
            continue
        sides = [incident.get(e["bus0"], 0.0), incident.get(e["bus1"], 0.0)]
        bound = min(sides) if all(s > 0 for s in sides) else max(sides)
        if _is_coupler(e) and bound > 0:
            filled.append(bound)
            notes.append("station coupler, bounded by the weaker end")
        else:
            filled.append(UNRATED_FALLBACK_MVA)
            notes.append("no rating in the file and none inferable; "
                         "kept the file's 9999")
    out = el.copy()
    out["s_nom_source"] = np.where(el["s_nom"].notna(), CONTINUOUS_RATE, notes)
    out["s_nom"] = filled
    return out


def rating_exceptions(case: psse.Case, el: pd.DataFrame) -> pd.DataFrame:
    """Every element the file left unrated, with what it is and what it got."""
    kv = case.bus.set_index("I")["BASKV"]
    name = _clean(case.bus.set_index("I")["NAME"])
    ex = el[el["s_nom_source"] != "RATE1"].copy()

    def label(bus: str) -> str:
        if bus.startswith("star:"):
            return "star point"
        return name.get(int(bus), "")

    ex["bus0_name"] = [label(b) for b in ex["bus0"]]
    ex["bus1_name"] = [label(b) for b in ex["bus1"]]
    ex["kv"] = ex["v_nom"]
    ex["coupler"] = [ _is_coupler(e) for _, e in ex.iterrows() ]
    ex["transmission"] = ex["kv"] >= TRANSMISSION_KV
    return ex[["name", "kind", "bus0", "bus0_name", "bus1", "bus1_name", "kv",
               "r_pu", "x_pu", "length", "coupler", "transmission",
               "s_nom", "s_nom_source"]].sort_values(
                   ["transmission", "kv"], ascending=False)


# --------------------------------------------------------------------------- #
# Stage 3: the voltage floor
#
# 100% of WP2024's dispatched generation and 99.8% of its in-service load sit
# below 110 kV.  A transmission network that drops those buses is empty, so
# the floor is a reduction, not a filter: sub-threshold buses go away and
# their machines and demand move to the retained bus nearest them by series
# reactance.
# --------------------------------------------------------------------------- #

def _retained(case: psse.Case, stars: pd.DataFrame, el: pd.DataFrame,
              min_kv: float) -> set[str]:
    """The buses the network keeps.

    Star buses are kept when at least two of their legs survive, because a
    star with one leg left is a dead end that carries nothing; a star with
    two is the exact two-winding equivalent of the original transformer
    between those two windings.
    """
    keep = {str(int(i)) for i, v in zip(case.bus["I"], case.bus["BASKV"])
            if v >= min_kv}
    keep -= {str(int(i)) for i, t in zip(case.bus["I"], case.bus["IDE"])
             if int(t) == ISOLATED_BUS}
    for _, s in stars.iterrows():
        legs = el[(el["bus0"] == s["name"]) | (el["bus1"] == s["name"])]
        ends = set(legs["bus0"]) | set(legs["bus1"]) - {s["name"]}
        if len({e for e in ends if e in keep}) >= 2:
            keep.add(s["name"])
    return keep


def _aggregate_to(case: psse.Case, el: pd.DataFrame, keep: set[str]
                  ) -> pd.DataFrame:
    """Map every dropped bus onto the retained bus nearest it.

    "Nearest" is the least total series reactance along a path that stays
    inside the dropped part of the network, which is the sense in which a
    load is fed from one station rather than another.  Paths through another
    retained bus do not count: a load reached only by going through a second
    transmission station belongs to that station, not to this one.

    Where a dropped component touches more than one retained bus - 137 of
    WP2024's 518 sub-threshold components do, carrying 23% of demand between
    them - the least-reactance one wins, and the runner-up and the ratio
    between them are recorded, so the arbitrariness is visible rather than
    averaged away.
    """
    import networkx as nx

    inner = nx.Graph()
    inner.add_nodes_from(b for b in set(el["bus0"]) | set(el["bus1"])
                         if b not in keep)
    boundary: dict[str, list[tuple[str, float]]] = {}
    for _, e in el.iterrows():
        a, b = e["bus0"], e["bus1"]
        w = max(abs(float(e["x_pu"])), 1e-9)
        if a in keep and b in keep:
            continue
        if a not in keep and b not in keep:
            if inner.has_edge(a, b):
                inner[a][b]["weight"] = min(inner[a][b]["weight"], w)
            else:
                inner.add_edge(a, b, weight=w)
        else:
            outer, dropped = (a, b) if a in keep else (b, a)
            boundary.setdefault(dropped, []).append((outer, w))

    name = _clean(case.bus.set_index("I")["NAME"])
    kv = case.bus.set_index("I")["BASKV"]

    def describe(bus: str) -> tuple[str, float]:
        if bus.startswith("star:"):
            return "star point", float("nan")
        return name.get(int(bus), ""), float(kv.get(int(bus), float("nan")))

    rows = []
    for component in nx.connected_components(inner):
        sub = inner.subgraph(component)
        # Distance into the component from each retained bus that touches it.
        reach: dict[str, dict[str, float]] = {}
        for entry, links in boundary.items():
            if entry not in component:
                continue
            lengths = nx.single_source_dijkstra_path_length(
                sub, entry, weight="weight")
            for outer, w in links:
                got = reach.setdefault(outer, {})
                for bus, d in lengths.items():
                    if d + w < got.get(bus, float("inf")):
                        got[bus] = d + w
        attachments = sorted(reach)
        for bus in sorted(component):
            options = sorted((reach[o][bus], o) for o in attachments
                             if bus in reach[o])
            first = options[0] if options else (float("nan"), "")
            second = options[1] if len(options) > 1 else (float("nan"), "")
            label, volts = describe(bus)
            parent_label, _ = describe(first[1]) if first[1] else ("", 0.0)
            runner_label, _ = describe(second[1]) if second[1] else ("", 0.0)
            rows.append({
                "bus": bus, "bus_name": label, "v_nom": volts,
                "parent": first[1], "parent_name": parent_label,
                "x_to_parent": first[0],
                "runner_up": second[1], "runner_up_name": runner_label,
                "x_to_runner_up": second[0],
                "attachments": len(attachments),
                "margin": (second[0] / first[0]) if options and len(options) > 1
                          and first[0] > 0 else float("nan"),
            })
    return pd.DataFrame(rows, columns=[
        "bus", "bus_name", "v_nom", "parent", "parent_name", "x_to_parent",
        "runner_up", "runner_up_name", "x_to_runner_up", "attachments",
        "margin"])


# --------------------------------------------------------------------------- #
# Stage 4: the PyPSA network
#
# PyPSA wants line impedances in ohms and transformer impedances in per-unit
# on the transformer's own s_nom, so the system-base per-unit table built
# above is converted twice, differently, here - and nowhere else.
# --------------------------------------------------------------------------- #

def _ohms(pu: float, v_nom: float) -> float:
    """Per-unit on the 100 MVA system base to ohms at ``v_nom`` kV."""
    return float(pu) * v_nom * v_nom / SYSTEM_MVA


def _siemens(pu: float, v_nom: float) -> float:
    """Per-unit shunt admittance on the system base to siemens."""
    return float(pu) * SYSTEM_MVA / (v_nom * v_nom)


def _slack_buses(network, case: psse.Case, aggregation: pd.DataFrame) -> dict:
    """Choose one reference bus per AC sub-network, and say why.

    The case names its own: five buses carry ``IDE = 3``, the four Turlough
    Hill machine terminals and SCOTLAND, which is the GB end of Moyle and is
    an island of one bus joined to nothing but the DC link.  Those choices are
    honoured wherever they survive the voltage floor - a swing bus that has
    been aggregated away hands the role to whatever retained bus absorbed it.

    Where a sub-network keeps no PSS/E swing bus at all, the bus carrying the
    most in-service generation takes the role, which is the same rule a solver
    would apply and is recorded rather than left implicit.
    """
    parent = dict(zip(aggregation["bus"], aggregation["parent"]))
    swing = [str(int(i)) for i, t in zip(case.bus["I"], case.bus["IDE"])
             if int(t) == SWING_BUS]
    wanted = {parent.get(b, b) for b in swing} & set(network.buses.index)

    chosen = {}
    network.determine_network_topology()
    for sub in network.sub_networks.index:
        buses = network.buses.index[network.buses["sub_network"] == sub]
        here = [b for b in buses if b in wanted]
        gens = network.generators[network.generators["bus"].isin(buses)]
        if here:
            bus, why = sorted(here)[0], "PSS/E swing bus (IDE=3)"
        elif len(gens):
            bus = gens.groupby("bus")["p_nom"].sum().idxmax()
            why = "largest generation in the sub-network; no IDE=3 bus here"
        else:
            bus, why = sorted(buses)[0], "no generation in the sub-network"
        chosen[bus] = (sub, why)
    return chosen


def build(case: psse.Case, min_kv: float = TRANSMISSION_KV,
          import_price: float = PLACEHOLDER_COST["import"],
          export_price: float = PLACEHOLDER_COST["export"]) -> Model:
    """Convert one case into a PyPSA network.

    ``min_kv`` is the voltage floor: :data:`TRANSMISSION_KV` builds the
    transmission network with everything below it aggregated onto the bus
    that feeds it, and ``0`` builds the case as it stands.
    """
    import pypsa

    if not math.isclose(case.sbase, SYSTEM_MVA, rel_tol=1e-9):
        raise ValueError(
            f"{case.name}: SBASE is {case.sbase} MVA, not {SYSTEM_MVA}. Every "
            "per-unit impedance in this module is on the 100 MVA base; a case "
            "on another base would come out wrong by exactly that ratio.")

    stars, el = elements(case)
    el = _fill_unrated(el)
    keep = _retained(case, stars, el, min_kv)
    aggregation = _aggregate_to(case, el, keep)
    parent = dict(zip(aggregation["bus"], aggregation["parent"]))

    def home(bus: int | str) -> str:
        """Where a record's bus ends up: itself, or whatever absorbed it."""
        bus = str(int(bus)) if not str(bus).startswith("star:") else str(bus)
        return bus if bus in keep else parent.get(bus, "")

    n = pypsa.Network()
    n.name = f"{case.name} ({'transmission' if min_kv else 'full'})"
    n.set_snapshots(["now"])

    # -- buses ------------------------------------------------------------- #
    bus = case.bus.copy()
    bus["NAME"] = _clean(bus["NAME"])
    bus = bus[[str(int(i)) in keep for i in bus["I"]]]
    n.add("Bus", bus["I"].astype(int).astype(str).values,
          v_nom=bus["BASKV"].astype(float).values,
          v_mag_pu_set=bus["VM"].astype(float).values,
          carrier="AC")
    n.buses["psse_name"] = bus["NAME"].values
    n.buses["station"] = [station_of(s) for s in bus["NAME"]]
    n.buses["psse_type"] = bus["IDE"].astype(int).values
    n.buses["area"] = bus["AREA"].astype(int).values
    n.buses["zone"] = bus["ZONE"].astype(int).values
    n.buses["jurisdiction"] = psse.jurisdiction(bus["AREA"]).values
    n.buses["v_ang_psse"] = bus["VA"].astype(float).values
    n.buses["x"] = np.nan
    n.buses["y"] = np.nan

    live_stars = stars[stars["name"].isin(keep)]
    if len(live_stars):
        n.add("Bus", live_stars["name"].values,
              v_nom=live_stars["v_nom"].values,
              v_mag_pu_set=live_stars["vm"].values, carrier="AC")
        n.buses.loc[live_stars["name"], "psse_name"] = "star of " + \
            live_stars["of"].values
        n.buses.loc[live_stars["name"], "station"] = "STAR"
        n.buses.loc[live_stars["name"], "psse_type"] = PQ_BUS
        n.buses.loc[live_stars["name"], "v_ang_psse"] = live_stars["va"].values
        n.buses.loc[live_stars["name"], "jurisdiction"] = "--"

    # -- lines and transformers -------------------------------------------- #
    inside = el[el["bus0"].isin(keep) & el["bus1"].isin(keep)]
    severed = el[~(el["bus0"].isin(keep) & el["bus1"].isin(keep))].copy()

    lines = inside[inside["kind"] == "line"]
    if len(lines):
        v = lines["v_nom"].astype(float).values
        n.add("Line", lines["name"].values,
              bus0=lines["bus0"].values, bus1=lines["bus1"].values,
              r=[_ohms(p, kvv) for p, kvv in zip(lines["r_pu"], v)],
              x=[_ohms(p, kvv) for p, kvv in zip(lines["x_pu"], v)],
              b=[_siemens(p, kvv) for p, kvv in zip(lines["b_pu"], v)],
              s_nom=lines["s_nom"].astype(float).values,
              length=lines["length"].astype(float).values, carrier="AC")
        n.lines["s_nom_source"] = lines["s_nom_source"].values
        n.lines["psse_ckt"] = lines["psse_ckt"].values

    trafos = inside[inside["kind"] == "transformer"]
    if len(trafos):
        # PyPSA holds transformer impedance per-unit on the transformer's own
        # s_nom, not on the system base, so each record is rebased by its own
        # rating.  The physical impedance is unchanged by this.
        scale = trafos["s_nom"].astype(float).values / SYSTEM_MVA
        n.add("Transformer", trafos["name"].values,
              bus0=trafos["bus0"].values, bus1=trafos["bus1"].values,
              r=trafos["r_pu"].astype(float).values * scale,
              x=trafos["x_pu"].astype(float).values * scale,
              b=0.0, g=0.0,
              s_nom=trafos["s_nom"].astype(float).values,
              tap_ratio=trafos["tap_ratio"].astype(float).values,
              phase_shift=trafos["phase_shift"].astype(float).values)
        n.transformers["s_nom_source"] = trafos["s_nom_source"].values
        n.transformers["psse_ckt"] = trafos["psse_ckt"].values

    # -- machines ----------------------------------------------------------- #
    name = _clean(case.bus.set_index("I")["NAME"])
    gen = psse.generators(case).copy()
    gen["bus_name"] = gen["I"].astype(int).map(name)
    gen["carrier"] = [carrier_of(s) for s in gen["bus_name"]]
    gen["home"] = [home(i) for i in gen["I"]]
    orphan_gen = gen[gen["home"] == ""]
    gen = gen[gen["home"] != ""]
    # PT is the machine's maximum output.  Seven in-service machines have
    # PT = 0 and PG = 0 with them; MBASE stands in so that a machine that is
    # in service is not silently given zero capability.
    p_nom = np.where(gen["PT"].astype(float) > 0, gen["PT"].astype(float),
                     gen["MBASE"].astype(float))
    p_min = np.where(p_nom > 0, gen["PB"].astype(float) / p_nom, 0.0)
    n.add("Generator", [f"{int(i)}-{d}" for i, d in
                        zip(gen["I"], _clean(gen["ID"]))],
          bus=gen["home"].values, carrier=gen["carrier"].values,
          p_nom=p_nom, p_min_pu=np.clip(p_min, -1.0, 1.0),
          p_set=gen["PG"].astype(float).values,
          q_set=gen["QG"].astype(float).values,
          control="PV",
          marginal_cost=[PLACEHOLDER_COST[c] for c in gen["carrier"]])
    n.generators["psse_bus"] = gen["I"].astype(int).values
    n.generators["psse_bus_name"] = gen["bus_name"].values
    n.generators["aggregated"] = (gen["home"].values !=
                                  gen["I"].astype(int).astype(str).values)

    load = psse.loads(case).copy()
    load["home"] = [home(i) for i in load["I"]]
    orphan_load = load[load["home"] == ""]
    load = load[load["home"] != ""]
    n.add("Load", [f"{int(i)}-{d}" for i, d in
                   zip(load["I"], _clean(load["ID"]))],
          bus=load["home"].values,
          p_set=load["PL"].astype(float).values,
          q_set=load["QL"].astype(float).values, carrier="AC")
    n.loads["psse_bus"] = load["I"].astype(int).values
    n.loads["psse_bus_name"] = load["I"].astype(int).map(name).values
    n.loads["aggregated"] = (load["home"].values !=
                             load["I"].astype(int).astype(str).values)

    for carrier in sorted(set(n.generators["carrier"]) | {"AC", "DC"}):
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)

    links = _add_links(n, case, keep, home, import_price,
                       export_price)

    slack = _slack_buses(n, case, aggregation)
    # Assigned as a whole column rather than one label at a time, because
    # determining the topology has already made PyPSA pick a slack of its own -
    # the first generator in each sub-network, which in WP2033 is a 21 MW hydro
    # unit behind its own step-up transformer, and which quietly absorbs the
    # case's whole 198 MW imbalance through it if it is left in place.
    control = pd.Series("PV", index=n.generators.index)
    for bus in slack:
        here = n.generators.index[n.generators["bus"] == bus]
        if len(here):
            control[here[0]] = "Slack"
    n.generators["control"] = control.values
    n.buses["control"] = np.where(n.buses.index.isin(slack), "Slack", "PQ")
    n.buses["psse_type"] = np.where(n.buses.index.isin(slack), SWING_BUS,
                                    n.buses["psse_type"])

    reports = {
        "aggregation": aggregation,
        "rating_exceptions": rating_exceptions(case, el),
        "severed": severed[["name", "kind", "bus0", "bus1", "v_nom",
                            "s_nom", "length"]],
        "slack": pd.DataFrame(
            [{"bus": b, "psse_name": n.buses.at[b, "psse_name"],
              "v_nom": n.buses.at[b, "v_nom"], "sub_network": s, "reason": w}
             for b, (s, w) in slack.items()]),
        "links": links,
        "orphans": pd.concat([
            orphan_gen.assign(kind="generator")[["I", "kind"]],
            orphan_load.assign(kind="load")[["I", "kind"]],
        ], ignore_index=True) if len(orphan_gen) or len(orphan_load)
        else pd.DataFrame(columns=["I", "kind"]),
    }
    return Model(network=n, case_name=case.name, min_kv=min_kv,
                 reports=reports)


# --------------------------------------------------------------------------- #
# Stage 5: the DC links
#
# Three interconnectors, in two different representations, neither of which is
# a branch.  Moyle is the only one in the two-terminal DC section - twice,
# once per pole - between SCOTLAND, a bus with no AC connection at all, and
# BALLYCRO.  East-West and Greenlink are PV buses with a generator record and
# no far terminal, because the case models an import as a machine.
#
# All three become Links, because that is what they are: a controllable flow
# between two points, not a machine whose output happens to be negative.  The
# two missing far terminals are created, with a generator on them that can run
# in both directions so that export is representable as well as import.
# --------------------------------------------------------------------------- #

def _moyle_efficiency(link: pd.Series, p_nom: float) -> float:
    """Resistive loss on a DC pole at its rated power.

    The record gives the pole resistance ``RDC`` in ohms and the scheduled DC
    voltage ``VSCHD`` in kV, which is enough for the line loss and nothing
    else.  Converter losses are not in the record and are not invented here,
    so this efficiency is the DC line alone and is optimistic by the roughly
    0.7% per station a real LCC converter costs.
    """
    rdc, vdc = float(link["RDC"]), float(link["VSCHD"])
    if not (rdc > 0 and vdc > 0 and p_nom > 0):
        return 1.0
    current_ka = p_nom / vdc
    loss_mw = current_ka ** 2 * rdc
    return float(max(0.0, 1.0 - loss_mw / p_nom))


def _add_links(n, case: psse.Case, keep: set[str], home, import_price: float,
               export_price: float) -> pd.DataFrame:
    """Add every interconnector as a Link, and describe what each one is."""
    name = _clean(case.bus.set_index("I")["NAME"])
    by_name = {v: int(k) for k, v in name.items()}
    gen = case.generator.set_index(["I"])
    rows = []

    for bus_name, spec in INTERCONNECTORS.items():
        if bus_name not in by_name:
            raise ValueError(
                f"{case.name}: no bus named {bus_name!r}. The interconnector "
                "table in this module is keyed on the case's own bus names; "
                "a case that renames one has to be looked at, not guessed at.")
        island_bus = by_name[bus_name]
        record = gen.loc[[island_bus]] if island_bus in gen.index \
            else pd.DataFrame()
        if record.empty:
            raise ValueError(f"{case.name}: {bus_name} carries no generator "
                             "record, so its rating cannot be read")
        pt = float(record["PT"].max())
        pb = float(record["PB"].min())

        if spec["dc_section"]:
            # Moyle: one Link per pole, both from the two-terminal DC section.
            poles = case.two_terminal_dc
            poles = poles[poles["IPR"].astype(int) == island_bus]
            if poles.empty:
                raise ValueError(f"{case.name}: {bus_name} is flagged as a "
                                 "two-terminal DC terminal but no DC record "
                                 "points at it")
            far = int(poles["IPI"].iloc[0])
            bus0, bus1 = home(island_bus), home(far)
            if not bus0 or not bus1:
                continue
            per_pole = pt / len(poles)
            for k, (_, pole) in enumerate(poles.iterrows(), start=1):
                link = f"{spec['link']} pole {k}"
                eff = _moyle_efficiency(pole, per_pole)
                n.add("Link", link, bus0=bus0, bus1=bus1, carrier="DC",
                      p_nom=per_pole, p_min_pu=-1.0, p_max_pu=1.0,
                      efficiency=eff, p_set=float(pole["SETVL"]))
                rows.append({
                    "link": link, "bus0": bus0, "bus1": bus1,
                    "bus0_name": bus_name, "bus1_name": name.get(far, ""),
                    "p_nom": per_pole, "p_set": float(pole["SETVL"]),
                    "efficiency": eff, "source": "two_terminal_dc record",
                    "far_terminal": "in the case",
                })
        else:
            # East-West and Greenlink: no far terminal in the case, so one is
            # created at the converter bus's own base kV.
            island = home(island_bus)
            if not island:
                continue
            far = spec["far"]
            n.add("Bus", far, v_nom=float(case.bus.set_index("I")
                                          .at[island_bus, "BASKV"]),
                  carrier="AC")
            n.buses.loc[far, ["psse_name", "station", "jurisdiction"]] = \
                [f"{spec['link']} far terminal", spec["link"].upper(), "XX"]
            n.buses.loc[far, "psse_type"] = PQ_BUS
            p_nom = max(abs(pb), pt)
            n.add("Link", spec["link"], bus0=far, bus1=island, carrier="DC",
                  p_nom=p_nom, p_min_pu=-1.0,
                  p_max_pu=float(pt / p_nom) if p_nom else 1.0,
                  efficiency=1.0,
                  p_set=float(record["PG"].max())
                  if int(record["STAT"].max()) == 1 else 0.0)
            rows.append({
                "link": spec["link"], "bus0": far, "bus1": island,
                "bus0_name": f"{spec['link']} far terminal",
                "bus1_name": bus_name,
                "p_nom": p_nom,
                "p_set": float(record["PG"].max())
                if int(record["STAT"].max()) == 1 else 0.0,
                "efficiency": 1.0,
                "source": "PV bus generator record (PT import, PB export)",
                "far_terminal": "created here",
            })

    # Something has to sit at the far end of each link for an optimisation to
    # have anywhere to import from or export to.  Two components rather than
    # one machine running both ways: a generator that sells into the island at
    # ``import_price``, above every domestic carrier so that it is the
    # marginal unit rather than the cheap one, and a sink that buys from it at
    # ``export_price``.  One bidirectional generator would be simpler and
    # wrong - a machine with a positive marginal cost and a negative output is
    # paid to run backwards, and an optimisation offered that will export
    # everything it can.
    for far in dict.fromkeys(r["bus0"] for r in rows):
        capacity = sum(r["p_nom"] for r in rows if r["bus0"] == far)
        n.add("Generator", f"{far} import", bus=far, carrier="import",
              p_nom=capacity, p_min_pu=0.0, control="PV",
              marginal_cost=import_price)
        n.add("Generator", f"{far} export", bus=far, carrier="export",
              p_nom=capacity, p_min_pu=0.0, control="PV", sign=-1.0,
              marginal_cost=-export_price)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Stage 6: the CSV schema
#
# PyPSA's own folder format, so that the export round-trips through
# pypsa.Network(<folder>) with nothing lost and nothing needing a reader of
# its own, plus one report table per decision this module made.
# --------------------------------------------------------------------------- #

#: The report tables written next to the network, and what each one answers.
REPORT_PURPOSE = {
    "aggregation": "every bus below the voltage floor, the retained bus its "
                   "load and generation moved to, the series reactance to it, "
                   "and the runner-up where there was one",
    "rating_exceptions": "every element the file left unrated (RATE1 of 0 or "
                         "9999), what it actually is, and the bound it was "
                         "given",
    "severed": "every element dropped because at least one end is below the "
               "voltage floor",
    "slack": "the reference bus of each AC sub-network and why it was chosen",
    "links": "the interconnectors, their ratings, and which of the case's two "
             "representations each came from",
    "orphans": "records whose bus survived neither the floor nor the "
               "aggregation, and so were dropped outright",
    "geocoding": "bus coordinates from OpenStreetMap, with the match method "
                 "and confidence for each, and a reason for each failure",
}


def export(model: Model, directory: str) -> str:
    """Write the network and its reports to ``directory``.

    The network goes out in PyPSA's CSV folder format -- ``buses.csv``,
    ``lines.csv``, ``transformers.csv``, ``links.csv``, ``generators.csv``,
    ``loads.csv``, ``carriers.csv``, ``network.csv``, ``snapshots.csv`` --
    which ``pypsa.Network(directory)`` reads straight back.  The reports go
    beside it under ``reports/``, one CSV per decision, and ``README.csv``
    lists them.
    """
    os.makedirs(directory, exist_ok=True)
    model.network.export_to_csv_folder(directory)
    reports = os.path.join(directory, "reports")
    os.makedirs(reports, exist_ok=True)
    written = []
    for key, frame in model.reports.items():
        path = os.path.join(reports, f"{key}.csv")
        frame.to_csv(path, index=False)
        written.append({"file": f"reports/{key}.csv", "rows": len(frame),
                        "answers": REPORT_PURPOSE.get(key, "")})
    pd.DataFrame(written).to_csv(os.path.join(reports, "README.csv"),
                                 index=False)
    return directory


# --------------------------------------------------------------------------- #
# Stage 7: verification
#
# Three questions, in the order that makes the next one worth asking: is the
# network one piece, does a linear power flow solve on it, and does an
# optimisation solve on it.
# --------------------------------------------------------------------------- #

def for_optimisation(network):
    """A copy of ``network`` with the case's dispatch released.

    The network carries the case's own answer: ``p_set`` on every generator is
    that machine's ``PG``, and on every link the scheduled DC transfer.  That
    is what a power flow needs, and it is what makes ``n.lpf()`` reproduce the
    case rather than invent a new one.

    It is also, in PyPSA 1.x, a constraint.  ``optimize`` turns a non-null
    ``p_set`` into an equality that pins the variable, so an optimisation run
    straight off this network is not an optimisation at all - it is the case's
    dispatch, asserted, and it is infeasible for the good reason that the
    case's dispatch is an AC solution carrying 87 MW of losses that a lossless
    linear model has nowhere to put.

    So dispatch is released here rather than never being set: the case's
    numbers stay in the exported CSVs where they can be read, and an
    optimisation gets a free variable.  Loads keep their ``p_set``, which is
    demand and not a dispatch decision.
    """
    n = network.copy()
    for frame in (n.generators, n.links):
        if "p_set" in frame.columns:
            frame["p_set"] = np.nan
    return n


def verify(model: Model, solver: str = "highs") -> dict:
    """Connectivity, DC power flow, and LOPF, with the numbers behind each."""
    n = model.network
    n.determine_network_topology()
    sizes = n.buses.groupby("sub_network").size().sort_values(ascending=False)
    result = {
        "case": model.case_name,
        "scope": model.scope,
        "buses": len(n.buses),
        "lines": len(n.lines),
        "transformers": len(n.transformers),
        "links": len(n.links),
        "generators": len(n.generators),
        "loads": len(n.loads),
        "load_mw": float(n.loads["p_set"].sum()),
        "generation_mw": float(n.generators["p_set"].sum()),
        "ac_sub_networks": int(len(sizes)),
        "largest_sub_network": int(sizes.iloc[0]) if len(sizes) else 0,
        "connected_including_links": _connected_with_links(n),
    }

    try:
        n.lpf()
        flows = n.lines_t.p0.loc["now"] if len(n.lines) else pd.Series(dtype=float)
        trafo = (n.transformers_t.p0.loc["now"] if len(n.transformers)
                 else pd.Series(dtype=float))
        result["dc_pf"] = "solved"
        result["dc_pf_max_line_mw"] = float(flows.abs().max()) if len(flows) else 0.0
        result["dc_pf_overloads"] = (
            int((flows.abs() > n.lines["s_nom"]).sum()) if len(flows) else 0) + (
            int((trafo.abs() > n.transformers["s_nom"]).sum())
            if len(trafo) else 0)
        # A limit this module inferred rather than read is only defensible if
        # the case's own flows fit inside it.  Any that do not are reported
        # rather than left to surface as an infeasible optimisation.
        inferred = 0
        for frame, flow in ((n.lines, flows), (n.transformers, trafo)):
            if not len(frame) or "s_nom_source" not in frame:
                continue
            made_up = frame["s_nom_source"] != CONTINUOUS_RATE
            inferred += int((flow.abs()[made_up] >
                             frame["s_nom"][made_up]).sum())
        result["dc_pf_inferred_limits_exceeded"] = inferred
        result["dc_pf_slack_mw"] = float(
            n.generators_t.p.loc["now"][
                n.generators.index[n.generators["control"] == "Slack"]].sum())
    except Exception as exc:                                # noqa: BLE001
        result["dc_pf"] = f"failed: {type(exc).__name__}: {exc}"

    try:
        # Measured on the transmission buses: the sub-threshold tail is full
        # of dead-end machine terminals whose angle carries no flow and is
        # not a check on anything.
        angles = angle_check(model)
        angles = angles[n.buses.loc[angles.index, "v_nom"] >= TRANSMISSION_KV]
        result["angle_buses"] = int(len(angles))
        result["angle_corr_vs_case"] = float(
            angles["dc_pf_deg"].corr(angles["psse_deg"]))
        result["angle_sd_deg"] = float(angles["centred_error_deg"].std())
        result["angle_max_deg"] = float(angles["centred_error_deg"].abs().max())
    except Exception as exc:                                # noqa: BLE001
        result["angle_corr_vs_case"] = f"failed: {exc}"

    try:
        free = for_optimisation(n)
        status, condition = free.optimize(solver_name=solver)
        result["lopf"] = f"{status}/{condition}"
        result["lopf_objective"] = float(free.objective) \
            if getattr(free, "objective", None) is not None else float("nan")
        # A generator's sign is -1 for the export sink, so injections have to
        # be summed with it or the sink is counted as generation.
        signed = free.generators_t.p.loc["now"] * free.generators["sign"]
        exchange = free.generators["carrier"].isin(("import", "export"))
        result["lopf_dispatch_mw"] = float(signed[~exchange.values].sum())
        result["lopf_net_import_mw"] = float(signed[exchange.values].sum())
        result["lopf_vs_case_mw"] = float(
            signed[~exchange.values].sum()
            - n.generators.loc[~exchange.values, "p_set"].sum())
    except Exception as exc:                                # noqa: BLE001
        result["lopf"] = f"failed: {type(exc).__name__}: {exc}"
    return result


def _connected_with_links(n) -> bool:
    """Is the network one piece once the DC links are counted as edges?

    PyPSA's sub-networks are synchronous islands, so a link never joins two of
    them.  The GB terminal of Moyle is deliberately its own island for that
    reason; this asks the other question, whether anything is unreachable.
    """
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(n.buses.index)
    for frame in (n.lines, n.transformers, n.links):
        g.add_edges_from(zip(frame["bus0"], frame["bus1"]))
    return nx.number_connected_components(g) == 1 if len(g) else False


def compare_scopes(case: psse.Case) -> dict:
    """What the voltage floor costs, measured on the case's own flows.

    Builds both scopes and compares the DC power flow on the 645 circuits they
    share.  The transmission network's demand is the full network's demand
    moved to whichever transmission bus feeds it, so the two agree exactly
    wherever the sub-threshold network is radial and differ wherever it is
    not.  The difference is the price of the reduction, in MW, on the circuits
    it is charged to.
    """
    full = build(case, min_kv=0.0)
    reduced = build(case, min_kv=TRANSMISSION_KV)
    full.network.lpf()
    reduced.network.lpf()
    a = reduced.network.lines_t.p0.loc["now"]
    b = full.network.lines_t.p0.loc["now"]
    common = a.index.intersection(b.index)
    diff = (a[common] - b[common]).abs()
    worst = diff.sort_values(ascending=False)
    return {
        "shared_circuits": int(len(common)),
        "mean_abs_diff_mw": float(diff.mean()),
        "max_abs_diff_mw": float(diff.max()),
        "circuits_over_1mw": int((diff > 1.0).sum()),
        "worst": worst.head(10),
    }


def angle_check(model: Model, case: psse.Case = None) -> pd.DataFrame:
    """Compare a DC power flow's bus angles with the case's own solved angles.

    The raw file records the solved voltage angle at every bus, so the
    conversion can be checked against the case rather than against itself: if
    the reactances or the phase-shift signs were wrong, the linear flow's
    angles would not track them.  A DC flow is not an AC flow and the two will
    not agree exactly - this looks for the correlation, not for equality.
    """
    n = model.network
    if "now" not in getattr(n.buses_t, "v_ang", pd.DataFrame()).index:
        n.lpf()
    got = np.degrees(n.buses_t.v_ang.loc["now"])
    want = n.buses["v_ang_psse"]
    both = pd.DataFrame({"dc_pf_deg": got, "psse_deg": want}).dropna()
    both = both[~both.index.astype(str).str.startswith("star:")]
    # Both are angles, so a difference of 359 degrees is a difference of one.
    error = (both["dc_pf_deg"] - both["psse_deg"] + 180.0) % 360.0 - 180.0
    both["error_deg"] = error
    # A DC flow's angles are measured from its own reference, and this model's
    # reference is not the one PSS/E solved against, so a constant offset
    # between the two says nothing.  The spread around it is the check.  The
    # offset is taken as the median rather than the mean because the reference
    # machine's own terminal is not comparable at all: a lossless linear flow
    # has nowhere to put the case's generation-minus-demand gap except the
    # slack, so that one machine's step-up transformer carries an imbalance it
    # was never sized for and its angle runs away.
    both["centred_error_deg"] = both["error_deg"] - both["error_deg"].median()
    return both


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

DEFAULT_PATTERN = "data/TYTFS2024_studyfiles/*_V35.raw"
DEFAULT_OUT = "data/pypsa"


def run_build(paths: list[str], out: str, scopes: list[str],
              geocode: bool = True) -> None:
    """Build and export each case at each scope.

    Coordinates are written onto the buses if ``geocode.py`` has already
    produced them; a bus it could not place keeps its NaN, and the network is
    exported either way.  The geocoding is a separate step because it needs
    the network, and because it should be possible to look at what it did
    before it is baked into anything.
    """
    for path in paths:
        case = psse.read_raw(path)
        matches = None
        if geocode:
            import geocode as geocode_module
            found = os.path.join(geocode_module.GEOCODING_DIR,
                                 f"{case.name}.csv")
            if os.path.exists(found):
                matches = pd.read_csv(found)
            else:
                print(f"(no coordinates for {case.name}: run "
                      f"`python geocode.py match` first)")
        for scope in scopes:
            min_kv = TRANSMISSION_KV if scope == "transmission" else 0.0
            model = build(case, min_kv=min_kv)
            if matches is not None:
                _place(model, matches)
            directory = os.path.join(out, f"{case.name}_{scope}")
            export(model, directory)
            placed = int(model.network.buses["x"].notna().sum())
            print(f"{model!r}\n  -> {directory}"
                  + (f"  ({placed} buses placed)" if matches is not None
                     else ""))


def _place(model: Model, matches: pd.DataFrame) -> None:
    """Write geocoded coordinates onto a built network's buses."""
    placed = matches[matches["lat"].notna()]
    lon = dict(zip(placed["bus"].astype(str), placed["lon"]))
    lat = dict(zip(placed["bus"].astype(str), placed["lat"]))
    how = dict(zip(placed["bus"].astype(str), placed["method"]))
    n = model.network
    n.buses["x"] = [lon.get(b, np.nan) for b in n.buses.index]
    n.buses["y"] = [lat.get(b, np.nan) for b in n.buses.index]
    n.buses["geocode_method"] = [how.get(b, "") for b in n.buses.index]
    model.reports["geocoding"] = matches


def run_verify(paths: list[str], scopes: list[str], solver: str) -> int:
    """Verify each case at each scope; exit non-zero on any failure."""
    bad = 0
    for path in paths:
        case = psse.read_raw(path)
        for scope in scopes:
            min_kv = TRANSMISSION_KV if scope == "transmission" else 0.0
            model = build(case, min_kv=min_kv)
            r = verify(model, solver=solver)
            ok = (r.get("dc_pf") == "solved"
                  and str(r.get("lopf", "")).startswith("ok")
                  and r["connected_including_links"])
            bad += not ok
            print(f"\n{r['case']} / {r['scope']}  {'ok' if ok else 'FAIL'}")
            for key in ("buses", "lines", "transformers", "links",
                        "generators", "loads", "load_mw", "generation_mw",
                        "ac_sub_networks", "largest_sub_network",
                        "connected_including_links", "dc_pf",
                        "dc_pf_max_line_mw", "dc_pf_overloads",
                        "dc_pf_inferred_limits_exceeded",
                        "angle_buses", "angle_corr_vs_case", "angle_sd_deg",
                        "angle_max_deg",
                        "dc_pf_slack_mw", "lopf", "lopf_objective",
                        "lopf_dispatch_mw", "lopf_net_import_mw",
                        "lopf_vs_case_mw"):
                if key in r:
                    value = r[key]
                    if isinstance(value, float):
                        value = (f"{value:.4f}" if key.startswith("angle_corr")
                                 else f"{value:,.2f}")
                    print(f"  {key:<26} {value}")
    return 1 if bad else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd, help_text in (("build", "convert and export"),
                           ("verify", "connectivity, DC power flow, LOPF")):
        s = sub.add_parser(cmd, help=help_text)
        s.add_argument("paths", nargs="*",
                       default=sorted(glob.glob(DEFAULT_PATTERN)))
        s.add_argument("--scope", choices=("transmission", "full", "both"),
                       default="both")
        if cmd == "build":
            s.add_argument("--out", default=DEFAULT_OUT)
            s.add_argument("--no-geocode", action="store_true",
                           help="export without bus coordinates")
        else:
            s.add_argument("--solver", default="highs")
    args = p.parse_args(argv)
    scopes = (["transmission", "full"] if args.scope == "both"
              else [args.scope])
    if args.cmd == "build":
        run_build(args.paths, args.out, scopes,
                  geocode=not args.no_geocode)
        return 0
    return run_verify(args.paths, scopes, args.solver)


if __name__ == "__main__":
    raise SystemExit(main())
