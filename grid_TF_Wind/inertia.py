"""Kinetic energy, the reference incident, and initial RoCoF.

The largest assumption in the study
-----------------------------------
**The inertia constants below are assumptions, not data.**  A PSS/E ``.raw``
file is a load-flow case: it carries each machine's MVA rating (``MBASE``) and
nothing about its rotor.  Inertia constants live in the ``.dyr`` dynamics
file, which EirGrid does not publish.  So every H here is a typical value for
the technology, applied to every machine of that technology, and the system
kinetic energy that the whole comparison turns on is only as good as that
table.  It is the first thing to replace if the dynamics data ever becomes
available, and the first thing to vary if it does not.

This module holds the only inertia numbers in the codebase.  Nothing else
defines an H, a condenser rating in MWs, or the inertia floor; they import
them from here, so changing an assumption changes it everywhere at once.

What is computed
----------------
System kinetic energy, synchronised machines only::

    E = sum_i H_i * S_i                                    [MWs]

with ``S_i`` the machine MVA (``MBASE``), plus the MWs of every synchronous
condenser online.  Wind, solar, batteries and HVDC contribute nothing: they
are coupled through converters and have no rotor the grid can see.

Initial RoCoF from the swing equation, in its dimensionally explicit form::

    df/dt|0+ = f0 * dP / (2 E)                             [Hz/s]

At the published 23,000 MWs floor, a 500 MW infeed loss gives 0.543 Hz/s -
just above the 0.5 Hz/s limit the brief works to.  The floor and the limit
are consistent, which is a check on the units.  (The Grid Code limit has since
moved to 1 Hz/s measured over 500 ms - see ``papers/MPID229a`` - against which
the same floor is conservative.)

The reference incident
----------------------
dP is the **reference incident** in the EU System Operation Guideline sense
EirGrid works to: the largest imbalance from an instantaneous change of active
power from a single generating module, single demand facility or single HVDC
interconnector, determined separately for each direction.  ``RI+ = LSI +
C_loss``.  The largest single infeed (LSI) is computed **per scenario**, as
the maximum over each committed synchronous module's output and each
interconnector's import.  It is not a constant: EirGrid forecasts it
day-ahead because it moves with dispatch, and it falls as wind rises and
residual load falls.

Post-trip inertia
-----------------
A tripping **unit** takes its kinetic energy with it::

    E_post = E_pre - H_trip * S_trip

A tripping **HVDC import** takes none.  Two scenarios with the same dP
therefore have different RoCoF depending on what tripped, which is why the
incident type is a scenario variable and stays in the output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# The table.  One place.
# --------------------------------------------------------------------------- #

#: Nominal frequency, Hz.
F0 = 50.0

#: Inertia constant H, seconds, on machine MVA (MBASE), by technology.
#: **Assumed, not measured** - see the module docstring.  Typical values:
#: a CCGT's gas and steam shafts together are heavy; an aeroderivative or
#: industrial OCGT is lighter; hydro and pumped-storage machines are slow,
#: large-diameter rotors with modest H on their rating.
H_SECONDS = {
    "CCGT": 6.0,
    "OCGT": 4.5,
    "steam": 4.0,              # coal and peat steam plant
    "hydro": 3.0,
    "pumped_storage": 3.0,
}

#: Synchronous condensers are given directly in MWs, per unit, because their
#: MVA and H are the vendor's and a condenser's inertia is what is procured.
#: **Chosen, not published**: a representative figure for a large condenser
#: with a flywheel.  The count online is sampled (0 to LCIS_UNITS).
SYNC_CONDENSER_MWS = 2000.0

#: The six Low Carbon Inertia Services condensers the sampler draws from.
LCIS_UNITS = 6

#: Technologies that have no rotor coupled to the grid.
NON_SYNCHRONOUS = ("wind", "solar", "battery", "hvdc")

#: The published operational inertia floor, MWs.  **Used for reporting and
#: for tests only.  It is not a constraint anywhere** - see ensemble.py.
OPERATIONAL_INERTIA_FLOOR_MWS = 23_000.0

# --------------------------------------------------------------------------- #
# The reference incident
# --------------------------------------------------------------------------- #

#: C_loss in RI+ = LSI + C_loss, as a fraction of the LSI.  Zero by default:
#: the loss of load that follows an infeed loss (embedded generation tripping
#: on RoCoF or vector shift) is exactly what this study does not want to
#: assume in advance.
C_LOSS_FRACTION = 0.0

#: Plausibility bounds on the LSI, MW - for tests and warnings, never used as
#: the value.  Around 500 MW today, roughly 700 MW once Celtic is in service,
#: against an all-island peak of about 7.5 GW.
LSI_TODAY_MW = 500.0
LSI_CELTIC_MW = 700.0
ISLAND_PEAK_MW = 7500.0

#: A machine producing less than this, MW, is taken to be off even if its
#: commitment status says otherwise.  Solver tolerance, not physics.
ONLINE_TOLERANCE_MW = 1e-3


def machine_h(technology: str) -> float:
    """H in seconds for one machine, or 0 for a non-synchronous one."""
    if technology in NON_SYNCHRONOUS:
        return 0.0
    if technology not in H_SECONDS:
        raise KeyError(
            f"no inertia constant for technology {technology!r}.  Add it to "
            "H_SECONDS rather than letting it default to zero: a synchronous "
            "machine with no inertia would lower E silently.")
    return H_SECONDS[technology]


def machine_energy(units: pd.DataFrame, online: pd.Series) -> pd.Series:
    """Kinetic energy, MWs, of each machine that is synchronised.

    ``units`` needs ``technology`` and ``mbase`` columns; ``online`` is a
    boolean Series on the same index.  A machine that is off contributes zero
    and is kept in the result, so the components always line up with the
    fleet.
    """
    h = units["technology"].map(machine_h).astype(float)
    s = units["mbase"].astype(float)
    on = online.reindex(units.index).fillna(False).astype(bool)
    return (h * s).where(on, 0.0).rename("E_mws")


def system_energy(units: pd.DataFrame, online: pd.Series,
                  condensers: int = 0,
                  condenser_mws: float = SYNC_CONDENSER_MWS) -> dict:
    """System kinetic energy, MWs, and where it comes from."""
    per_machine = machine_energy(units, online)
    e_sc = float(condensers) * float(condenser_mws)
    return {
        "E_mws": float(per_machine.sum()) + e_sc,
        "E_machines_mws": float(per_machine.sum()),
        "E_condensers_mws": e_sc,
        "components": per_machine,
    }


def initial_rocof(dp_mw, e_mws, f0: float = F0):
    """``f0 * dP / (2 E)``, Hz/s.  Vectorised; E must be positive."""
    dp = np.asarray(dp_mw, dtype=float)
    e = np.asarray(e_mws, dtype=float)
    if np.any(e <= 0):
        raise ValueError("system kinetic energy must be positive")
    return f0 * dp / (2.0 * e)


def reference_incident(unit_output: pd.Series, flows: dict,
                       pump_load: pd.Series | None = None,
                       c_loss_fraction: float = C_LOSS_FRACTION) -> dict:
    """The largest instantaneous imbalance, each direction.

    ``unit_output``  MW of each *synchronised* module (off units excluded)
    ``flows``        interconnector -> MW at the island end, + import
    ``pump_load``    MW each pumping unit is drawing, as a positive number

    RI+ (the under-frequency incident) is the largest of any module's output
    and any interconnector's import.  RI- (over-frequency) is the largest of
    any interconnector's export and any single pump's load.  Both are
    returned with the element and its type; only RI+ is simulated here.
    """
    candidates = [(float(p), str(name), "unit")
                  for name, p in unit_output.items()
                  if float(p) > ONLINE_TOLERANCE_MW]
    candidates += [(float(mw), str(link), "hvdc")
                   for link, mw in flows.items() if float(mw) > 0]
    if not candidates:
        raise ValueError("no infeed online: nothing can trip")
    lsi, element, kind = max(candidates)
    down = [(-float(mw), str(link), "hvdc") for link, mw in flows.items()
            if float(mw) < 0]
    if pump_load is not None:
        down += [(float(p), str(name), "pump") for name, p in
                 pump_load.items() if float(p) > ONLINE_TOLERANCE_MW]
    ri_minus, minus_element, minus_kind = max(down) if down else (0.0, "", "")
    return {
        "lsi_mw": lsi,
        "c_loss_mw": c_loss_fraction * lsi,
        "ri_plus_mw": lsi * (1.0 + c_loss_fraction),
        "incident_element": element,
        "incident_type": kind,
        "ri_minus_mw": ri_minus,
        "ri_minus_element": minus_element,
        "ri_minus_type": minus_kind,
    }


def post_trip_energy(e_pre: float, components: pd.Series, element: str,
                     kind: str) -> float:
    """E after the incident: a unit takes its rotor with it, HVDC does not."""
    if kind == "hvdc":
        return float(e_pre)
    if kind != "unit":
        raise ValueError(f"unknown incident type {kind!r}")
    if element not in components.index:
        raise KeyError(f"{element} is not a machine in this scenario")
    return float(e_pre) - float(components[element])
