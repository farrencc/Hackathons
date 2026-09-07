"""Checks on the kit itself.  Run it before you trust a result:

    python test_kit.py                 # no pytest needed
    pytest test_kit.py                 # if you have it

Two of these matter more than the rest.  ``test_ptdf_matches_a_power_flow``
rebuilds every branch flow from ``PTDF x injections`` and compares it against
what PyPSA's own ``lpf`` produced - two routes to the same number that share
no code.  ``test_susceptibility_matches_finite_differences`` perturbs one
branch's susceptance by a thousandth and checks the analytic derivative
against the difference it actually makes.  If either of those drifts, nothing
built on ``flowmath`` means anything.

The whole file runs on the 15-node North-West network, which solves in a
second or two.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import flowmath
import gridkit

SCENARIO, SCOPE = "WP2033", "north-west"
_cache: dict[str, object] = {}


def solved():
    """One solved network, reused - the solve is the slow part."""
    if "network" not in _cache:
        n = gridkit.load(SCENARIO, SCOPE)
        n.optimize(n.snapshots, solver_name="highs")
        gridkit.freeze_dispatch(n)
        n.lpf(n.snapshots)
        _cache["network"] = n
    return _cache["network"]


# --------------------------------------------------------------------------- #
# The networks
# --------------------------------------------------------------------------- #

def test_every_network_in_the_catalogue_loads():
    listed = gridkit.catalogue()
    assert len(listed) == 8
    for _, row in listed.iterrows():
        n = gridkit.load(row["scenario"], row["scope"])
        assert len(n.buses) == row["buses"]
        assert len(n.snapshots) == 168


def test_every_network_solves():
    for scenario in gridkit.SCENARIOS:
        n = gridkit.load(scenario, "north-west")
        n.optimize(n.snapshots, solver_name="highs")
        assert len(n.generators_t.p), f"{scenario} produced no dispatch"


def test_demand_is_met_or_explicitly_shed():
    n = solved()
    served = n.generators_t.p.sum(axis=1) + (
        n.storage_units_t.p.sum(axis=1) if len(n.storage_units_t.p) else 0.0)
    demand = n.loads_t.p_set.sum(axis=1)
    # Boundary injections are generators too, and can be negative; the point
    # is only that nothing has vanished.
    assert np.allclose(served, demand, atol=1.0), "energy is not balanced"


def test_wind_and_solar_carry_a_profile():
    """A weather generator without a p_max_pu series runs flat out all week.

    That is how 7.8 GW of "wind" once turned into must-run baseload in
    WP2033, and every dispatch-down number computed from it was wrong.
    """
    for scenario in gridkit.SCENARIOS:
        for scope in gridkit.SCOPES:
            n = gridkit.load(scenario, scope)
            weather = n.generators.index[
                n.generators["carrier"].isin(("wind", "solar"))]
            missing = set(weather) - set(n.generators_t.p_max_pu.columns)
            assert not missing, f"{scenario} {scope}: {len(missing)} without"


def test_profiles_stay_inside_the_unit_interval():
    n = gridkit.load(SCENARIO, SCOPE)
    values = n.generators_t.p_max_pu.to_numpy()
    assert values.min() >= 0.0 and values.max() <= 1.0


# --------------------------------------------------------------------------- #
# flowmath
# --------------------------------------------------------------------------- #

def test_laplacian_is_symmetric_and_rows_sum_to_zero():
    n = gridkit.load(SCENARIO, SCOPE)
    L, _, _ = flowmath.laplacian(n)
    assert np.allclose(L, L.T)
    assert np.abs(L.sum(axis=1)).max() < 1e-9


def test_pseudoinverse_satisfies_the_moore_penrose_conditions():
    n = gridkit.load(SCENARIO, SCOPE)
    L, _, _ = flowmath.laplacian(n)
    Lp = flowmath.pseudoinverse(L)
    assert np.abs(L @ Lp @ L - L).max() < 1e-6
    assert np.abs(Lp @ L @ Lp - Lp).max() < 1e-6
    assert np.allclose(L @ Lp, (L @ Lp).T)


def test_ptdf_rows_sum_to_zero():
    """Injecting 1 MW at every bus at once moves no power anywhere."""
    n = gridkit.load(SCENARIO, SCOPE)
    assert flowmath.ptdf(n).sum(axis=1).abs().max() < 1e-9


def test_ptdf_matches_a_power_flow():
    n = solved()
    snapshot = n.snapshots[len(n.snapshots) // 2]
    frame = flowmath.branches(n)
    mine = flowmath.flows(n, snapshot, frame)
    theirs = pd.concat([
        n.lines_t.p0.loc[snapshot],
        n.transformers_t.p0.loc[snapshot] if len(n.transformers)
        else pd.Series(dtype=float)]).reindex(mine.index)
    error = (mine - theirs).abs().max()
    assert error < 1e-6, f"PTDF and lpf disagree by {error} MW"


def test_susceptibility_matches_finite_differences():
    n = solved()
    snapshot = n.snapshots[len(n.snapshots) // 2]
    frame = flowmath.branches(n).copy()
    analytic = flowmath.susceptibility(n, snapshot, frame)

    K, buses, edges = flowmath.incidence(n, frame)
    p = flowmath.injections(n, snapshot).reindex(buses).fillna(0.0).to_numpy()

    phi = frame["phase_shift"].to_numpy(dtype=float)

    def flows_with(b):
        L = (K * b) @ K.T
        theta = flowmath.pseudoinverse(L) @ (p + K @ (b * phi))
        return b * (K.T @ theta - phi)

    base = frame["susceptance"].to_numpy(dtype=float).copy()
    reference = flows_with(base)
    for column in range(0, len(edges), 5):          # every fifth is plenty
        step = base[column] * 1e-4
        bumped = base.copy()
        bumped[column] += step
        numeric = (flows_with(bumped) - reference) / step
        predicted = analytic.iloc[:, column].to_numpy()
        # The natural scale is MW per MW/radian.  Some columns are exactly
        # zero - a radial stub's susceptance changes no flow anywhere - so
        # the column's own magnitude is not a usable denominator on its own.
        scale = max(np.abs(predicted).max(),
                    np.abs(reference).max() / base[column])
        assert np.abs(numeric - predicted).max() / scale < 1e-4, (
            f"column {edges[column]} disagrees with finite differences")


def test_shift_factors_are_reference_independent_in_their_differences():
    """The value depends on the reference; the *difference* between two
    generators does not.  That invariance is why a ranking is meaningful."""
    n = gridkit.load(SCENARIO, SCOPE)
    monitored = n.lines.index[0]
    a = flowmath.shift_factors(n, monitored, reference="load")["shift_factor"]
    b = flowmath.shift_factors(n, monitored, reference="uniform")["shift_factor"]
    assert not np.allclose(a, b)                       # they really do differ
    assert np.allclose((a - a.iloc[0]), (b - b.iloc[0]), atol=1e-9)


def test_shift_factor_predicts_a_real_redispatch():
    """Move 10 MW from one bus to another and see the circuit respond."""
    n = solved()
    snapshot = n.snapshots[len(n.snapshots) // 2]
    frame = flowmath.branches(n)
    monitored = gridkit.line_loading(n).loc[snapshot].idxmax()
    matrix = flowmath.ptdf(n, frame)
    row = matrix.loc[monitored]

    source, sink = row.idxmax(), row.idxmin()
    before = flowmath.flows(n, snapshot, frame)[monitored]
    shifted = flowmath.injections(n, snapshot)
    shifted[source] += 10.0
    shifted[sink] -= 10.0
    after = float(matrix.loc[monitored] @ shifted.reindex(matrix.columns)
                  .fillna(0.0))
    predicted = 10.0 * (row[source] - row[sink])
    assert abs((after - before) - predicted) < 1e-6


# --------------------------------------------------------------------------- #
# gridkit's editing
# --------------------------------------------------------------------------- #

def test_add_and_remove_a_line():
    n = gridkit.load(SCENARIO, SCOPE)
    count = len(n.lines)
    bus0, bus1 = n.buses.index[0], n.buses.index[-1]
    name = gridkit.add_line(n, bus0, bus1, s_nom=150.0, length=40.0)
    assert len(n.lines) == count + 1
    assert n.lines.at[name, "x"] == 40.0 * gridkit.OHMS_PER_KM
    gridkit.remove_line(n, name)
    assert len(n.lines) == count


def test_set_rating():
    n = gridkit.load(SCENARIO, SCOPE)
    name = n.lines.index[0]
    gridkit.set_rating(n, name, 999.0)
    assert n.lines.at[name, "s_nom"] == 999.0


def test_add_a_battery_and_solve_with_it():
    n = gridkit.load(SCENARIO, SCOPE)
    name = gridkit.add_battery(n, n.buses.index[0], p_nom=50.0, hours=4.0)
    assert n.storage_units.at[name, "max_hours"] == 4.0
    n.optimize(n.snapshots, solver_name="highs")
    assert len(n.storage_units_t.p)


def test_reset_gives_back_the_baseline():
    n = gridkit.load(SCENARIO, SCOPE)
    original = len(n.lines)
    gridkit.remove_line(n, n.lines.index[0])
    assert len(n.lines) == original - 1
    n = gridkit.reset(n)
    assert len(n.lines) == original


def test_removing_a_line_changes_the_flows():
    n = gridkit.load(SCENARIO, SCOPE)
    n.optimize(n.snapshots, solver_name="highs")
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)
    before = n.lines_t.p0.abs().sum().sum()

    m = gridkit.load(SCENARIO, SCOPE)
    busiest = gridkit.line_loading(n).max().idxmax()
    gridkit.remove_line(m, busiest)
    m.optimize(m.snapshots, solver_name="highs")
    gridkit.freeze_dispatch(m)
    m.lpf(m.snapshots)
    assert m.lines_t.p0.abs().sum().sum() != before


# --------------------------------------------------------------------------- #
# The traps the README warns about
# --------------------------------------------------------------------------- #

def test_freeze_dispatch_refuses_before_a_solve():
    n = gridkit.load(SCENARIO, SCOPE)
    try:
        gridkit.freeze_dispatch(n)
    except RuntimeError:
        return
    raise AssertionError("freeze_dispatch should refuse an unsolved network")


def test_placed_buses_drops_the_gulf_of_guinea():
    for scenario in gridkit.SCENARIOS:
        n = gridkit.load(scenario, "all-island")
        placed = gridkit.placed_buses(n)
        assert len(placed) < len(n.buses)          # some really are unplaced
        assert placed["x"].between(-11.0, -5.0).all()
        assert placed["y"].between(51.0, 56.0).all()


def test_dispatch_down_reports_the_renamed_columns():
    """The kit reports economic dispatch-down, not SEM/EirGrid curtailment.

    Named and columned accordingly: there is no SNSP constraint in this model,
    so nothing here is curtailment in that sense.
    """
    n = solved()
    lost = gridkit.dispatch_down(n)
    assert list(lost.columns) == ["offered_mwh", "dispatched_mwh",
                                  "dispatch_down_mwh", "dispatch_down_pct",
                                  "carrier"]
    assert not hasattr(gridkit, "curtailment"), "the old name must be gone"
    assert (lost["dispatch_down_mwh"] >= -1e-6).all()
    assert np.allclose(lost["offered_mwh"] - lost["dispatched_mwh"],
                       lost["dispatch_down_mwh"], atol=1.0)
    assert lost["dispatch_down_mwh"].is_monotonic_decreasing


def test_dispatch_down_refuses_before_a_solve():
    n = gridkit.load(SCENARIO, SCOPE)
    try:
        gridkit.dispatch_down(n)
    except RuntimeError:
        return
    raise AssertionError("dispatch_down should refuse an unsolved network")


def test_load_shedding_exists_at_every_load_bus():
    n = gridkit.load(SCENARIO, SCOPE)
    shed = {g.replace("shed ", "") for g in n.generators.index
            if g.startswith("shed ")}
    assert set(n.loads["bus"]) <= shed
    assert (n.generators.loc[[f"shed {b}" for b in shed],
                             "marginal_cost"] == gridkit.VOLL).all()


def main() -> int:
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = []
    for name, test in tests:
        try:
            test()
        except Exception as problem:                 # noqa: BLE001
            failed.append((name, problem))
            print(f"FAIL  {name}\n        {problem}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
