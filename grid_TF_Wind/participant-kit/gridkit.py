"""Load and modify the all-island and North-West networks.

Everything here is a thin, obvious wrapper over PyPSA.  Nothing is hidden: if
you would rather work with ``pypsa.Network`` directly, or open the CSVs in a
spreadsheet, that is a supported way to use this kit and this module will not
get in your way.

    import gridkit

    n = gridkit.load("WP2033", "north-west")
    gridkit.set_rating(n, "3581-89516-1", 200)      # widen the NI tie
    n.optimize(n.snapshots[:24], solver_name="highs")
    print(gridkit.dispatch_down(n))

Every network carries a week of hourly snapshots, generator ``p_max_pu`` for
wind and solar, and load ``p_set``.  Read the README's LIMITATIONS section
before quoting a number from any of it.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
NETWORKS = os.path.join(HERE, "networks")

SCENARIOS = ("WP2024", "SV2024", "WP2033", "SV2033")
SCOPES = ("all-island", "north-west")

#: Marginal cost of unserved energy, EUR/MWh.  Every bus with load carries a
#: "shed <bus>" generator at this price, so a network you have broken gives
#: you a number and a location instead of the word "infeasible".
VOLL = 10000.0


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def catalogue() -> pd.DataFrame:
    """What is in the kit: one row per network, with its size and its peak."""
    return pd.read_csv(os.path.join(NETWORKS, "manifest.csv"))


def load(scenario: str = "WP2033", scope: str = "all-island"):
    """Load one network.

    ``scenario`` is one of WP2024, SV2024, WP2033, SV2033 - winter peak or
    summer valley, 2024 or 2033.  ``scope`` is ``all-island`` (the whole
    110 kV-and-above transmission network) or ``north-west`` (the 15-node
    Donegal and north Connacht region).
    """
    import pypsa

    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    path = os.path.join(NETWORKS, f"{scenario}_{scope}.nc")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} is missing.  The kit ships eight networks; if this one "
            "is not there the download is incomplete.")
    return pypsa.Network(path)


def quiet() -> None:
    """Turn down PyPSA's, linopy's and HiGHS's logging.

    The libraries are chatty by default - consistency warnings on every load,
    a progress bar per constraint block, and the full simplex log - and the
    interesting output of an example scrolls off the top.  Nothing here
    changes a result; it only changes what gets printed.
    """
    import logging
    import warnings

    for name in ("pypsa", "linopy", "pypsa.consistency", "pypsa.optimization"):
        logging.getLogger(name).setLevel(logging.ERROR)
    # PyPSA and pandas both warn about a dtype change coming in pandas 3;
    # the warning prints a line of PyPSA's own source into the middle of the
    # output and there is nothing a participant can do about it.
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)


def solve(network, snapshots=None, **kwargs):
    """``network.optimize`` with the solver's own noise turned off.

    Takes and returns exactly what ``optimize`` does, so anything you would
    pass to it works here.  Use ``network.optimize`` directly if you want the
    HiGHS log - it is worth reading when a solve goes wrong.
    """
    options = {"output_flag": False}
    options.update(kwargs.pop("solver_options", {}))
    return network.optimize(
        network.snapshots if snapshots is None else snapshots,
        solver_name=kwargs.pop("solver_name", "highs"),
        solver_options=options, progress=False, **kwargs)


def reset(network):
    """A fresh copy of the network this one was loaded from.

    Modifications are not undone in place - you get a new object, so keep the
    return value::

        n = gridkit.reset(n)
    """
    meta = getattr(network, "meta", {}) or {}
    scenario = meta.get("scenario")
    scope = meta.get("scope")
    if not scenario or not scope:
        raise ValueError(
            "this network has no scenario/scope metadata, so there is no "
            "baseline to go back to.  Load one with gridkit.load().")
    return load(scenario, scope)


def save(network, path: str) -> str:
    """Write a modified network out, as netCDF or as a folder of CSVs."""
    if path.endswith(".nc"):
        network.export_to_netcdf(path)
    else:
        network.export_to_csv_folder(path)
    return path


# --------------------------------------------------------------------------- #
# Modifying
# --------------------------------------------------------------------------- #

#: A 110 kV double circuit is around 0.4 ohms per km of reactance; this is a
#: usable default for a new line when you have not got a real impedance.  It
#: is a placeholder, and a study that turns on it should say so.
OHMS_PER_KM = 0.4


def add_line(network, bus0: str, bus1: str, s_nom: float,
             x: float | None = None, r: float = 0.0,
             length: float | None = None, name: str | None = None) -> str:
    """Add an AC line and return its name.

    Give either ``x`` in ohms or ``length`` in km; with ``length`` the
    reactance is ``length * 0.4`` ohms, which is a rule of thumb for a 110 kV
    double circuit and nothing more.  With neither, the great-circle distance
    between the two buses is used, if both have coordinates.
    """
    for bus in (bus0, bus1):
        if bus not in network.buses.index:
            raise KeyError(f"no bus named {bus!r}")
    if x is None:
        if length is None:
            length = _distance_km(network, bus0, bus1)
        x = max(length * OHMS_PER_KM, 1e-3)
    name = name or f"new {bus0}-{bus1}"
    if name in network.lines.index:
        raise ValueError(f"a line named {name!r} already exists")
    network.add("Line", name, bus0=bus0, bus1=bus1, x=float(x), r=float(r),
                s_nom=float(s_nom), length=float(length or 0.0), carrier="AC")
    return name


def remove_line(network, name: str) -> None:
    """Remove an AC line or a transformer by name."""
    if name in network.lines.index:
        network.remove("Line", name)
    elif name in network.transformers.index:
        network.remove("Transformer", name)
    else:
        raise KeyError(f"no line or transformer named {name!r}")


def set_rating(network, name: str, s_nom: float) -> None:
    """Change one branch's continuous rating, in MVA."""
    if name in network.lines.index:
        network.lines.loc[name, "s_nom"] = float(s_nom)
    elif name in network.transformers.index:
        network.transformers.loc[name, "s_nom"] = float(s_nom)
    else:
        raise KeyError(f"no line or transformer named {name!r}")


def add_battery(network, bus: str, p_nom: float, hours: float = 4.0,
                efficiency: float = 0.92, name: str | None = None) -> str:
    """Add a battery as a PyPSA ``StorageUnit`` and return its name.

    ``p_nom`` is the power rating in MW and ``hours`` the energy in hours at
    that rating, so a 50 MW / 4 h battery is ``p_nom=50, hours=4``.  The
    round-trip efficiency is split evenly between charging and discharging.
    """
    if bus not in network.buses.index:
        raise KeyError(f"no bus named {bus!r}")
    name = name or f"battery {bus}"
    if name in network.storage_units.index:
        raise ValueError(f"a storage unit named {name!r} already exists")
    one_way = float(efficiency) ** 0.5
    network.add("StorageUnit", name, bus=bus, p_nom=float(p_nom),
                max_hours=float(hours), efficiency_store=one_way,
                efficiency_dispatch=one_way, cyclic_state_of_charge=True,
                carrier="battery", marginal_cost=0.5)
    if "battery" not in network.carriers.index:
        network.add("Carrier", "battery")
    return name


def _distance_km(network, bus0: str, bus1: str) -> float:
    """Great-circle distance between two buses, or 50 km if unplaced."""
    a, b = network.buses.loc[bus0], network.buses.loc[bus1]
    if not all(np.isfinite([a["x"], a["y"], b["x"], b["y"]])):
        return 50.0
    radius, degree = 6371.0088, np.pi / 180.0
    dlat = (b["y"] - a["y"]) * degree
    dlon = (b["x"] - a["x"]) * degree
    h = (np.sin(dlat / 2) ** 2 + np.cos(a["y"] * degree)
         * np.cos(b["y"] * degree) * np.sin(dlon / 2) ** 2)
    return float(2 * radius * np.arcsin(np.sqrt(np.clip(h, 0, 1))))


# --------------------------------------------------------------------------- #
# Reading results
# --------------------------------------------------------------------------- #

def placed_buses(network) -> pd.DataFrame:
    """The buses that have a usable coordinate, for drawing.

    PyPSA's netCDF writer turns a missing coordinate into 0.0 rather than NaN,
    and 0 N 0 E is in the Gulf of Guinea - left in, it stretches the extent of
    every map from the Atlantic to the equator and squashes Ireland into a
    corner.  Use this rather than filtering on NaN.
    """
    frame = network.buses
    keep = np.isfinite(frame["x"]) & np.isfinite(frame["y"])
    keep &= ~((frame["x"].abs() < 1e-9) & (frame["y"].abs() < 1e-9))
    if "coordinate_source" in frame.columns:
        keep &= frame["coordinate_source"].astype(str) != "none"
    return frame[keep]


def summary(network) -> pd.Series:
    """The shape of a network in one glance."""
    meta = getattr(network, "meta", {}) or {}
    return pd.Series({
        "scenario": meta.get("scenario", "?"),
        "scope": meta.get("scope", "?"),
        "buses": len(network.buses),
        "lines": len(network.lines),
        "transformers": len(network.transformers),
        "links": len(network.links),
        "generators": len(network.generators),
        "storage_units": len(network.storage_units),
        "loads": len(network.loads),
        "snapshots": len(network.snapshots),
        "peak_demand_mw": round(float(
            network.loads_t.p_set.sum(axis=1).max()), 1),
        "generation_capacity_mw": round(float(
            network.generators["p_nom"].sum()), 1),
    })


def freeze_dispatch(network) -> None:
    """Copy an optimised dispatch into ``p_set``, ready for ``n.lpf()``.

    A trap worth knowing about.  ``n.optimize()`` writes its answer to
    ``generators_t.p``; ``n.lpf()`` reads ``generators_t.p_set``.  The kit
    ships ``p_set`` empty on purpose - in PyPSA 1.x a non-null ``p_set`` is an
    equality constraint that pins the dispatch and makes the optimisation
    infeasible - so running ``lpf`` straight after ``optimize`` gives a power
    flow with **no generation in it**, and the reference bus silently supplies
    the whole island.  You will see one circuit at 1600% of its rating and
    wonder what you broke.

    So: optimise, freeze, then flow.

        n.optimize(n.snapshots, solver_name="highs")
        gridkit.freeze_dispatch(n)
        n.lpf(n.snapshots)
    """
    if not len(network.generators_t.p.columns):
        raise RuntimeError("nothing to freeze: run n.optimize(...) first")
    network.generators_t.p_set = network.generators_t.p.copy()
    if len(network.storage_units_t.p.columns):
        network.storage_units_t.p_set = network.storage_units_t.p.copy()
    if len(network.links) and len(network.links_t.p0.columns):
        network.links_t.p_set = network.links_t.p0.copy()


def line_loading(network) -> pd.DataFrame:
    """|flow| / s_nom for every line at every snapshot, after a solve."""
    if not len(network.lines_t.p0.columns):
        raise RuntimeError("solve first: n.optimize(...) or n.lpf()")
    return network.lines_t.p0.abs().div(network.lines["s_nom"], axis=1)


def dispatch_down(network) -> pd.DataFrame:
    """Available minus dispatched, per weather-driven generator, in MWh.

    Only generators with a ``p_max_pu`` time series can be held back - wind
    and solar.  Everything else is dispatchable and not running is a decision
    rather than a loss.

    This is *not* curtailment in the SEM/EirGrid sense.  Curtailment there is
    a system-wide, pro-rata reduction of wind and solar output ordered to
    respect an SNSP or an inertia limit; this model carries no SNSP
    constraint, no inertia constraint and no unit commitment, so it cannot
    produce curtailment in that sense and nothing here reproduces EirGrid's
    mechanism.  What the LOPF withholds is plain economic dispatch-down, and
    it has exactly two causes:

    * **constraint-based** - the output is stranded behind a specific binding
      line rating, and lifting that rating would recover it;
    * **surplus-based** - there is more supply than the demand can absorb in
      that hour, so no network of any shape could take it.

    The two are separated by re-solving with every rating lifted; see
    ``examples/b_lopf_dispatch.py``.  Reported per generator, the split is not
    distinguished: the columns below are the total withheld.
    """
    if not len(network.generators_t.p.columns):
        raise RuntimeError("solve first: n.optimize(...)")
    available = network.generators_t.p_max_pu
    if not len(available.columns):
        return pd.DataFrame()
    columns = [c for c in available.columns if c in network.generators_t.p]
    offered = available[columns] * network.generators.loc[columns, "p_nom"]
    taken = network.generators_t.p[columns].clip(lower=0.0)
    lost = (offered - taken).clip(lower=0.0)
    return pd.DataFrame({
        "offered_mwh": offered.sum(),
        "dispatched_mwh": taken.sum(),
        "dispatch_down_mwh": lost.sum(),
        "dispatch_down_pct": (lost.sum() / offered.sum().replace(0, np.nan)
                              * 100.0),
        "carrier": network.generators.loc[columns, "carrier"],
    }).sort_values("dispatch_down_mwh", ascending=False)


def unserved(network) -> pd.Series:
    """Energy the network could not deliver, per bus, in MWh.

    Anything above zero means the network - not the generation - is the
    binding thing.  Look here first when a result surprises you.
    """
    if not len(network.generators_t.p.columns):
        raise RuntimeError("solve first: n.optimize(...)")
    shed = [g for g in network.generators_t.p.columns
            if str(g).startswith("shed ")]
    if not shed:
        return pd.Series(dtype=float)
    total = network.generators_t.p[shed].sum()
    total.index = [str(s).replace("shed ", "") for s in total.index]
    return total[total > 1e-6].sort_values(ascending=False)


def binding(network, threshold: float = 0.999) -> pd.Series:
    """How many snapshots each line spends at its rating."""
    loading = line_loading(network)
    hours = (loading >= threshold).sum()
    return hours[hours > 0].sort_values(ascending=False)
