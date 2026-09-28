"""Tests for the dispatch ensemble.

The ones that matter are the ones that would catch the ensemble quietly
becoming unable to answer the question: a constraint on SNSP, inertia or
RoCoF leaking into the optimisation (which would cut the insecure half off
every scatter), generators being aggregated (which would destroy both H_COI
and the largest infeed), or the minimum-units floor not holding (which would
put states in the ensemble that the real system cannot be in).

Every test that needs the TYTFS files skips cleanly when they are absent.
"""

import os

import numpy as np
import pandas as pd
import pytest

import ensemble as m
import psse

WP2024 = m.case_path("TYTFS2024_WP2024_V35")

needs_case = pytest.mark.skipif(not os.path.exists(WP2024),
                                reason="TYTFS study files not present")


@pytest.fixture(scope="module")
def case():
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    return psse.read_raw(WP2024)


@pytest.fixture(scope="module")
def topo(case):
    return m.topology(case)


@pytest.fixture(scope="module")
def units(case, topo):
    return m.fleet(case, topo)


@pytest.fixture(scope="module")
def inputs(case, topo):
    ren = m.renewables(case, topo)
    shares = m.load_shares(case, topo)
    year = m.weather_year(case)
    wind, solar = m.cluster_profiles(year, ren)
    return dict(ren=ren, shares=shares, year=year, wind=wind, solar=solar)


@pytest.fixture(scope="module")
def windy(topo, units, inputs):
    """The windiest low-demand hour of the synthetic year, solved."""
    year = inputs["year"]
    score = year["fleet"]["wind"] - year["demand"] / year["demand"].max()
    hour = int(np.argmax(score.to_numpy()))
    win = m.window(year, inputs["wind"], inputs["solar"], hour)
    setting = m.Setting(interconnectors={"EWIC": -300.0, "Moyle": 150.0,
                                         "Greenlink": 0.0})
    n = m.dispatch_network(topo, units, inputs["ren"], inputs["shares"], win,
                           setting)
    info = m.solve(n, units, setting)
    return dict(n=n, info=info, win=win, setting=setting)


# --------------------------------------------------------------------------- #
# The fleet
# --------------------------------------------------------------------------- #

def test_every_record_is_classified(case):
    """No generator record is left as 'unclassified'.

    A thermal unit the table does not know would be dropped from the
    dispatch silently and take its inertia with it.
    """
    reg = m.register(case)
    left = reg[reg["technology"] == "unclassified"]
    assert left.empty, left[["bus_name", "ID", "PT"]].to_string()


def test_excluded_small_units_are_small(case):
    """What is left out of the dispatch is a rounding error on the island."""
    reg = m.register(case)
    small = reg[reg["technology"] == "small"]
    assert small["PT"].astype(float).max() < m.SMALL_UNIT_MW
    assert small["PT"].astype(float).sum() < 100.0


def test_generators_are_individual_not_aggregated(units):
    """One committable module per unit - only multi-shaft CCGTs merge."""
    merged = units[units["members"].str.contains(";")]
    assert set(merged.index) <= set(m.MODULES.values())
    # Moneypoint's three units are three modules, not one 700 MW block.
    mny = units[units["psse_bus_name"].str.startswith("MNYPG")]
    assert len(mny) == 3
    assert units["p_nom"].max() < 700.0


def test_multi_shaft_module_keeps_every_machine(case, units):
    """A merged CCGT's MBASE is the sum of its machines', so E is unchanged."""
    reg = m.register(case).set_index("generator")
    for module, row in units[units["members"].str.contains(";")].iterrows():
        members = row["members"].split(";")
        assert row["mbase"] == pytest.approx(
            reg.loc[members, "MBASE"].astype(float).sum())


def test_both_jurisdictions_can_meet_the_minimum_units_rule(units):
    large = units[units["large"]].groupby("jurisdiction").size()
    for j, k in m.MIN_UNITS.items():
        assert large[j] >= k


# --------------------------------------------------------------------------- #
# The clustered network
# --------------------------------------------------------------------------- #

def test_cluster_count_is_in_band(topo):
    ac = topo.network.buses[topo.network.buses["jurisdiction"] != "XX"]
    assert 30 <= len(ac) <= 60
    assert len(ac) == sum(m.CLUSTERS.values())


def test_no_cluster_straddles_the_border(case, topo):
    area = case.bus.set_index("I")["AREA"].astype(int)
    jur = psse.jurisdiction(area)
    for bus, cluster in topo.busmap.items():
        if cluster.startswith("HVDC") or bus.startswith("star") \
                or not bus.isdigit() or int(bus) not in jur.index:
            continue
        if jur[int(bus)] in ("IE", "NI"):
            assert cluster[:2] == jur[int(bus)], (bus, cluster)


def test_every_machine_and_load_has_a_node(case, topo):
    reg = m.register(case)
    live = reg[~reg["technology"].isin(("hvdc", "reactive",
                                        "sync_condenser_record", "small"))]
    for bus in live["I"]:
        assert str(int(bus)) in topo.busmap
    for bus in psse.loads(case)["I"]:
        assert str(int(bus)) in topo.busmap


def test_ac_network_is_one_island(topo):
    n = topo.network.copy()
    n.determine_network_topology()
    ac = [s for s in n.sub_networks.index
          if not n.sub_networks.at[s, "slack_bus"].startswith("HVDC")]
    assert len(ac) == 1


# --------------------------------------------------------------------------- #
# The dispatch
# --------------------------------------------------------------------------- #

def test_no_security_metric_is_constrained(windy):
    """SNSP, inertia and RoCoF must be outcomes, never constraints."""
    names = " ".join(windy["n"].model.constraints).lower()
    for word in ("snsp", "inertia", "rocof", "kinetic"):
        assert word not in names


def test_minimum_units_hold_in_every_hour(windy, units):
    status = windy["n"].generators_t.status
    large = units[units["large"]]
    for j, k in m.MIN_UNITS.items():
        names = [u for u in large.index[large["jurisdiction"] == j]
                 if u in status.columns]
        assert (status[names].sum(axis=1) >= k - 1e-6).all()


def test_interconnectors_sit_at_their_setpoints(windy):
    n, setting = windy["n"], windy["setting"]
    t = windy["win"].target
    for link, mw in setting.interconnectors.items():
        poles = n.links.index[n.links.index.str.startswith(link)]
        assert n.links_t.p0.loc[t, poles].sum() == pytest.approx(mw, abs=1e-3)


def test_windy_hour_is_solved_without_shedding(windy):
    n = windy["n"]
    assert windy["info"]["condition"] == "optimal"
    shed = n.generators.index[n.generators["carrier"] == "shed"]
    assert n.generators_t.p[shed].to_numpy().max() < 1e-3


def test_windy_hour_runs_near_the_floor(windy, units):
    """The minimum-units rule, not an inertia floor, is what binds.

    With the wind up and demand down the optimiser keeps as few machines on
    as it is allowed to.  If this starts failing because many more are on,
    something other than the OCU rule is holding units on.
    """
    t = windy["win"].target
    status = windy["n"].generators_t.status.loc[t]
    floor = sum(m.MIN_UNITS.values())
    assert floor <= int((status > 0.5).sum()) <= floor + 4


# --------------------------------------------------------------------------- #
# SNSP, EirGrid's way
# --------------------------------------------------------------------------- #

def test_snsp_hand_worked_with_pumping():
    """(wind + solar + net import) / (demand + pumping + net export).

    2,000 MW wind, 100 MW solar, EWIC importing 300 and Moyle exporting 100
    (net import 200), 4,000 MW demand with Turlough Hill pumping 200 MW::

        (2000 + 100 + 200) / (4000 + 200 + 0) = 2300 / 4200 = 0.547619
    """
    got = m.snsp(2000.0, 100.0, {"EWIC": 300.0, "Moyle": -100.0}, 4000.0,
                 pump_load_mw=200.0)
    assert got == pytest.approx(2300.0 / 4200.0)


def test_snsp_net_export_goes_on_the_bottom():
    got = m.snsp(3000.0, 0.0, {"EWIC": -500.0, "Moyle": 100.0}, 4000.0)
    assert got == pytest.approx(3000.0 / 4400.0)


def test_snsp_is_not_the_naive_wind_ratio():
    naive = 2000.0 / 4000.0
    assert m.snsp(2000.0, 0.0, {"EWIC": 400.0}, 4000.0) != \
        pytest.approx(naive)


# --------------------------------------------------------------------------- #
# The design
# --------------------------------------------------------------------------- #

def test_same_seed_same_design(units):
    a = m.design(20, units, (3400.0, 7300.0), seed=11)
    b = m.design(20, units, (3400.0, 7300.0), seed=11)
    c = m.design(20, units, (3400.0, 7300.0), seed=12)
    key = lambda ds: [(d.hour, d.demand_mw, d.setting) for d in ds]  # noqa
    assert key(a) == key(b)
    assert key(a) != key(c)


def test_design_spans_every_dimension(units):
    draws = m.design(50, units, (3400.0, 7300.0))
    u_hour = np.array([d.u["hour"] for d in draws])
    demand = np.array([d.demand_mw for d in draws])
    ewic = np.array([d.setting.interconnectors["EWIC"] for d in draws])
    sc = np.array([d.setting.condensers for d in draws])
    # A Latin hypercube puts exactly one draw in each of n strata.
    assert len(np.unique(np.floor(u_hour * 50))) == 50
    assert demand.min() < 3500 and demand.max() > 7200
    assert ewic.min() < -400 and ewic.max() > 400
    assert set(sc) == set(range(0, 7))


def test_outages_never_break_the_minimum_units_rule(units):
    for d in m.design(200, units, (3400.0, 7300.0), seed=3):
        for j, k in m.MIN_UNITS.items():
            pool = units[units["large"] & (units["jurisdiction"] == j)]
            assert len([u for u in pool.index
                        if u not in d.setting.outages]) >= k


# --------------------------------------------------------------------------- #
# The ensemble itself
#
# These read the in-session ensemble if it has been run (python ensemble.py
# run), and otherwise solve a small one.  They are the acceptance tests.
# --------------------------------------------------------------------------- #

SMOKE = os.path.join(m.ENSEMBLE_DIR, f"{m.DEFAULT_VINTAGE}_seed{m.SEED}"
                     f"_n{m.DEFAULT_N}")


@pytest.fixture(scope="module")
def ens(tmp_path_factory):
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    directory = os.environ.get("ENSEMBLE_DIR", SMOKE)
    if len(m.done(directory)) < m.DEFAULT_N:
        directory = str(tmp_path_factory.mktemp("ensemble"))
        m.run(n=16, directory=directory, workers=os.cpu_count() or 1,
              verbose=False)
    return dict(directory=directory, **m.load(directory))


def test_every_scenario_solved(ens):
    s = ens["scenarios"]
    assert (s["condition"] == "optimal").all()
    assert (s["shed_mw"] < 1.0).all()


def test_minimum_units_online_in_every_scenario(ens):
    s = ens["scenarios"]
    assert (s["large_online_IE"] >= m.MIN_UNITS["IE"]).all()
    assert (s["large_online_NI"] >= m.MIN_UNITS["NI"]).all()


def test_ensemble_reaches_the_insecure_region(ens):
    """If this fails, a constraint has leaked into the optimisation.

    With no SNSP or inertia limit in the MILP, windy low-demand states run on
    the minimum-units floor and go past both operational limits.
    """
    import inertia

    s = ens["scenarios"]
    assert (s["snsp"] > 0.75).any()
    assert (s["E_pre_mws"] < inertia.OPERATIONAL_INERTIA_FLOOR_MWS).any()


def test_lsi_moves_and_falls_with_wind(ens):
    """LSI is a function of dispatch, not a constant."""
    import inertia
    from scipy.stats import spearmanr

    s = ens["scenarios"]
    assert s["lsi_mw"].std() > 25.0
    assert s["lsi_mw"].max() <= inertia.LSI_CELTIC_MW
    assert spearmanr(s["wind_mw"], s["lsi_mw"]).statistic < 0


def test_post_trip_inertia_by_incident_type(ens):
    s = ens["scenarios"]
    unit = s[s["incident_type"] == "unit"]
    hvdc = s[s["incident_type"] == "hvdc"]
    assert (unit["E_post_mws"] < unit["E_pre_mws"]).all()
    assert (hvdc["E_post_mws"] == hvdc["E_pre_mws"]).all()


def test_record_is_enough_to_recompute_inertia(ens):
    """E_pre from the per-unit rows equals the scenario row, to the MWs."""
    import inertia

    s = ens["scenarios"].set_index("scenario")
    u = ens["units"]
    machines = u[u["online"]].groupby("scenario")["E_mws"].sum()
    rebuilt = machines.reindex(s.index).fillna(0.0) \
        + s["condensers"] * inertia.SYNC_CONDENSER_MWS
    assert np.allclose(rebuilt, s["E_pre_mws"])


def test_same_seed_reproduces_the_ensemble(ens):
    """Re-solve two scenarios from scratch and compare every field."""
    ctx = m.context(m.DEFAULT_VINTAGE, m.SEED)
    s = ens["scenarios"].set_index("scenario")
    n = int(len(s)) if len(s) < m.DEFAULT_N else m.DEFAULT_N
    draws = m.design(n, ctx.units, ctx.demand_range,
                     hours=len(ctx.year["demand"]))
    for d in draws[:2]:
        row, _, _ = m.run_draw(d, ctx)
        for key, value in row.items():
            if key in ("solve_s", "scenario"):
                continue
            stored = s.at[d.scenario, key]
            if isinstance(value, float):
                assert value == pytest.approx(float(stored), rel=1e-6,
                                              abs=1e-6), key
            else:
                assert value == stored, key
