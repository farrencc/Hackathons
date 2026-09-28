"""The frequency layer: trip each solved scenario and watch what happens.

PyPSA is steady-state and has no notion of frequency.  This module
post-processes each scenario record analytically, with the single-mass
centre-of-inertia swing equation::

    (2 E_post / f0) * d(df)/dt = P_response(t) - dP - D * df

where ``df`` is the deviation from 50 Hz, ``E_post`` the kinetic energy left
after the incident, ``dP`` the reference incident, and ``D`` load damping.

Why the measured outcome is not the predictor
---------------------------------------------
``f0 * dP / (2 E_post)`` is not a *predictor* of initial RoCoF; it *is*
initial RoCoF, analytically.  If the outcome measured here were the
instantaneous value at t = 0+, comparing it against SNSP would be comparing a
number with itself and something else.  So the primary outcome is the
operational measurement - **RoCoF averaged over a 500 ms window** - and the
frequency nadir, in a system where load damping, fast frequency response and
primary reserve all act inside that window.  Those three are the only things
that can make the analytic value wrong, and nothing here may collapse them:
the FFR ramp in particular is the default for that reason.

``ffr_mode = "instant"`` exists for comparison and is **degenerate**: at 0+ it
simply subtracts the FFR volume from dP, so the closed form with dP replaced
by dP - FFR is exact at 0+, and the 500 ms value converges on it.  It is the
control that shows what the ramp is doing, not a model of anything.

The response, from published delivery definitions
-------------------------------------------------
Reserve is modelled from the service timings, not from governor models: that
is auditable against documents, and it avoids inventing turbine parameters
that nobody here has.

**FFR** (DS3 System Services).  An open-loop ramp to full volume over a full
activation time, default 0.3 s - Category 2 of the DASSA categories, which
span 0.15 s to 1 s - sustained to 10 s, then released.  Volume defaults to 70%
of the reference incident, inside the 60-80% band.

**Primary operating reserve** (Operational Constraints Update).  Available
volume ramps to full by 5 s and is held to 15 s.  **Secondary reserve** is
available from 15 s to 90 s; between 5 s and 15 s the available volume moves
from the POR to the SOR figure.  Both volumes come from the scenario record:
what the synchronised units still spinning can deliver from their headroom.

Governors deliver reserve *in proportion to the frequency deviation*, up to
their volume: a droop characteristic, saturating at the deviation the service
volume is defined against.  Without that, a POR volume delivered open-loop
on top of FFR would drive the frequency above 50 Hz after every trip.

**Load damping** is linear, 1.5% of connected load per Hz by default.

Integration is over 20 s at 1 ms, vectorised across scenarios with Heun's
method, in blocks so a 2,000-scenario ensemble never holds more than a block
of trajectories in memory.

Extension: a multi-mass version
-------------------------------
The COI model is global by construction: every machine sees the same
frequency.  In the first cycles after a trip, local RoCoF near the disturbance
exceeds the COI value, and that is where the locality question and the
synchronous-condenser siting problem live.  :func:`multi_mass` is the hook for
it, and the scenario record already carries what it needs - the cluster bus
of every unit and its kinetic energy, and the clustered network's reactances.
It is not built.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

import inertia

# --------------------------------------------------------------------------- #
# The constants that decide the answer
# --------------------------------------------------------------------------- #

#: Load damping, percent of connected load per Hz.
DAMPING_PCT_PER_HZ = 1.5

#: FFR: default mode, full activation time (s), sustain (s), release (s), and
#: volume as a fraction of the reference incident.
FFR_MODE = "ramp"
FFR_FULL_ACTIVATION_S = 0.3
FFR_SUSTAIN_S = 10.0
#: FFR is released linearly over this long after FFR_SUSTAIN_S, rather than
#: stepped off, so the hand-over to POR does not create an artificial RoCoF
#: spike that the 500 ms measurement would then report.
FFR_RELEASE_S = 2.0
FFR_FRACTION_OF_RI = 0.70
FFR_MODES = ("ramp", "instant")

#: POR ramps to full by POR_FULL_S and is held to POR_HOLD_S; SOR is held from
#: POR_HOLD_S to SOR_END_S.
POR_FULL_S = 5.0
POR_HOLD_S = 15.0
SOR_END_S = 90.0

#: The frequency deviation, Hz, at which governor response reaches the full
#: service volume.  0.5 Hz: reserve volumes are assessed against a fall to
#: 49.5 Hz.  **An assumption about how the contracted volume maps onto droop.**
RESERVE_FULL_DEVIATION_HZ = 0.5

#: Integration.
T_END_S = 20.0
DT_S = 0.001
BLOCK = 256

#: The measurement window for the operational RoCoF.
ROCOF_WINDOW_S = 0.5

#: Violation thresholds.  0.5 Hz/s is the brief's limit; the Grid Code has
#: since moved to 1 Hz/s over 500 ms (papers/MPID229a), reported alongside.
ROCOF_LIMIT_HZ_S = 0.5
ROCOF_LIMIT_GRID_CODE_HZ_S = 1.0
NADIR_LIMIT_HZ = 49.5
NADIR_LFDD_HZ = 49.0


@dataclass
class Parameters:
    """Every knob of the dynamic layer, defaulting to the constants above."""

    ffr_mode: str = FFR_MODE
    ffr_full_activation_s: float = FFR_FULL_ACTIVATION_S
    ffr_sustain_s: float = FFR_SUSTAIN_S
    ffr_release_s: float = FFR_RELEASE_S
    ffr_fraction: float = FFR_FRACTION_OF_RI
    damping_pct_per_hz: float = DAMPING_PCT_PER_HZ
    por_full_s: float = POR_FULL_S
    por_hold_s: float = POR_HOLD_S
    sor_end_s: float = SOR_END_S
    reserve_full_deviation_hz: float = RESERVE_FULL_DEVIATION_HZ
    t_end_s: float = T_END_S
    dt_s: float = DT_S
    rocof_window_s: float = ROCOF_WINDOW_S
    f0: float = inertia.F0

    def __post_init__(self):
        if self.ffr_mode not in FFR_MODES:
            raise ValueError(f"ffr_mode must be one of {FFR_MODES}")


# --------------------------------------------------------------------------- #
# The response profiles, as functions of time
# --------------------------------------------------------------------------- #

def ffr_fraction(t: float, p: Parameters) -> float:
    """Fraction of the FFR volume being delivered at time t (open loop)."""
    if p.ffr_mode == "instant":
        ramp = 1.0
    else:
        ramp = min(1.0, t / p.ffr_full_activation_s)
    if t > p.ffr_sustain_s:
        ramp *= max(0.0, 1.0 - (t - p.ffr_sustain_s) / p.ffr_release_s)
    return ramp


def reserve_available(t: float, v_por, v_sor, p: Parameters):
    """Governor reserve available at time t, MW, before droop is applied."""
    if t <= p.por_full_s:
        return v_por * (t / p.por_full_s)
    if t <= p.por_hold_s:
        w = (t - p.por_full_s) / (p.por_hold_s - p.por_full_s)
        return v_por + w * np.maximum(v_sor - v_por, 0.0)
    if t <= p.sor_end_s:
        return np.maximum(v_por, v_sor)
    return np.zeros_like(v_por)


# --------------------------------------------------------------------------- #
# Integration
# --------------------------------------------------------------------------- #

def simulate(e_post, dp, load, v_por, v_sor, params: Parameters | None = None,
             keep: bool = False) -> dict:
    """Integrate the swing equation for a batch of scenarios.

    All arguments are 1-D arrays of the same length: kinetic energy after the
    trip (MWs), the incident (MW), connected load (MW), and POR and SOR
    volumes (MW).  Returns the outcome arrays, and the trajectories if
    ``keep``.
    """
    p = params or Parameters()
    e_post = np.asarray(e_post, float)
    dp = np.asarray(dp, float)
    load = np.asarray(load, float)
    v_por = np.asarray(v_por, float)
    v_sor = np.asarray(v_sor, float)
    if np.any(e_post <= 0):
        raise ValueError("E_post must be positive")

    m = 2.0 * e_post / p.f0                      # MW per (Hz/s)
    d = p.damping_pct_per_hz / 100.0 * load     # MW per Hz
    v_ffr = p.ffr_fraction * dp
    steps = int(round(p.t_end_s / p.dt_s))
    h = p.dt_s

    def rhs(t, df):
        droop = np.clip(-df / p.reserve_full_deviation_hz, 0.0, 1.0)
        response = v_ffr * ffr_fraction(t, p) \
            + reserve_available(t, v_por, v_sor, p) * droop
        return (response - dp - d * df) / m

    traj = np.empty((len(dp), steps + 1))
    df = np.zeros(len(dp))
    traj[:, 0] = 0.0
    initial = rhs(0.0, df)                  # the 0+ slope under this model
    for k in range(steps):
        t = k * h
        k1 = rhs(t, df)
        k2 = rhs(t + h, df + h * k1)
        df = df + 0.5 * h * (k1 + k2)
        traj[:, k + 1] = df

    out = outcomes(traj, p)
    out["rocof_initial_model_hz_s"] = -initial
    out["rocof_analytic_hz_s"] = inertia.initial_rocof(dp, e_post, p.f0)
    out["rocof_analytic_net_ffr_hz_s"] = inertia.initial_rocof(
        np.maximum(dp - v_ffr, 0.0), e_post, p.f0)
    if keep:
        out["trajectory_hz"] = p.f0 + traj
        out["time_s"] = np.arange(steps + 1) * h
    return out


def outcomes(traj: np.ndarray, p: Parameters) -> dict:
    """What an operator would measure, from deviation trajectories.

    **RoCoF_500ms** is the largest fall in any 500 ms window over the run,
    divided by 0.5 s - the operational measurement, reported positive for a
    falling frequency.  It differs from ``f0 dP / 2E`` by however much
    damping, FFR and reserve bite inside the window, and that difference is
    the whole point of the study.
    """
    w = int(round(p.rocof_window_s / p.dt_s))
    fall = traj[:, :-w] - traj[:, w:]
    rocof = fall.max(axis=1) / p.rocof_window_s
    k_nadir = traj.argmin(axis=1)
    nadir = p.f0 + traj[np.arange(len(traj)), k_nadir]
    return {
        "rocof_500ms_hz_s": rocof,
        "rocof_500ms_start_s": fall.argmax(axis=1) * p.dt_s,
        "nadir_hz": nadir,
        "nadir_depth_hz": p.f0 - nadir,
        "t_nadir_s": k_nadir * p.dt_s,
        "settling_hz": p.f0 + traj[:, -1],
        "rocof_violation": rocof > ROCOF_LIMIT_HZ_S,
        "rocof_violation_grid_code": rocof > ROCOF_LIMIT_GRID_CODE_HZ_S,
        "nadir_violation": nadir < NADIR_LIMIT_HZ,
        "nadir_lfdd": nadir < NADIR_LFDD_HZ,
    }


def evaluate(scenarios: pd.DataFrame, params: Parameters | None = None
             ) -> pd.DataFrame:
    """The frequency outcome of every scenario, in blocks.

    Reads only the scenario record: ``E_post_mws``, ``ri_plus_mw``,
    ``demand_mw`` plus ``pump_load_mw`` as connected load, and the POR and
    SOR volumes the synchronised fleet can still deliver.
    """
    p = params or Parameters()
    rows = []
    for start in range(0, len(scenarios), BLOCK):
        s = scenarios.iloc[start:start + BLOCK]
        out = simulate(s["E_post_mws"], s["ri_plus_mw"],
                       s["demand_mw"] + s["pump_load_mw"],
                       s["por_available_mw"], s["sor_available_mw"], p)
        frame = pd.DataFrame(out, index=s.index)
        frame.insert(0, "scenario", s["scenario"].values)
        rows.append(frame)
    result = pd.concat(rows) if rows else pd.DataFrame()
    result["ffr_mode"] = p.ffr_mode
    result["ffr_mw"] = p.ffr_fraction * scenarios["ri_plus_mw"].values
    return result


def run(directory: str, modes=FFR_MODES) -> dict:
    """Evaluate a solved ensemble in each FFR mode, next to its records."""
    import ensemble

    scenarios = ensemble.load(directory)["scenarios"]
    paths = {}
    for mode in modes:
        params = Parameters(ffr_mode=mode)
        result = evaluate(scenarios, params)
        path = os.path.join(directory, f"frequency_{mode}.parquet")
        result.to_parquet(path, index=False)
        pd.Series(asdict(params)).to_json(
            os.path.join(directory, f"frequency_{mode}.json"), indent=2)
        paths[mode] = path
    return paths


# --------------------------------------------------------------------------- #
# The hook for a locality study
# --------------------------------------------------------------------------- #

def multi_mass(scenario: int, units: pd.DataFrame, network,
               params: Parameters | None = None):
    """Bus-level frequency after a trip - **not built; the hook for it.**

    What it would do: one swing equation per cluster, with each cluster's
    inertia the sum of ``units.E_mws`` over the synchronised machines on it
    (the record already carries both), coupled by synchronising power
    coefficients from the clustered network's line reactances linearised at
    the scenario's angles.  The disturbance enters at the incident element's
    bus.  The COI frequency is the inertia-weighted mean of the bus
    frequencies, so :func:`simulate` is its one-mass limit and the two can be
    checked against each other.

    Local RoCoF near the trip exceeds the COI value in the first cycles; that
    is the locality question, and where a condenser is sited starts to matter.
    """
    raise NotImplementedError(
        "multi-mass bus-level frequency is a documented extension, not built; "
        "see this function's docstring and docs/ENSEMBLE.md")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("ensemble", help="an ensemble directory")
    args = parser.parse_args(argv)
    for mode, path in run(args.ensemble).items():
        print(f"{mode}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
