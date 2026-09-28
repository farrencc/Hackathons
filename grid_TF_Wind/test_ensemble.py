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
