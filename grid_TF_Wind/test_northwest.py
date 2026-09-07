"""Regression tests for the North-West extraction.

Three things are guarded.

The **counts**, because they are the thing being reconciled against a
hand-built dataset and a change to any of them is a change to the
reconciliation: 20 stations native and 15 aggregated, 23 circuits on 21 routes
native and 19 on 16 aggregated, and the three routes that carry two circuits
each.

The **folding**, because the aggregated view exists only to match the
hand-built one and gets its answer wrong if it folds a different five
stations.

The **extraction**, because it is only an extraction if it reproduces the
circuit flows the full network puts on the same circuits.  The native view
agrees to a hundredth of a megawatt; the aggregated one does not, and the
size of that disagreement is the price of the 15-node topology.
"""

import os

import numpy as np
import pandas as pd
import pytest

import northwest as m
import psse
import pypsa_net

WP2024 = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"


@pytest.fixture(scope="module")
def case():
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    return psse.read_raw(WP2024)


@pytest.fixture(scope="module")
def model(case):
    pytest.importorskip("pypsa")
    return m._reference_flows(case)


# --------------------------------------------------------------------------- #
# The region
# --------------------------------------------------------------------------- #

def test_the_two_views_have_24_and_15_stations():
    """nodes.xlsx holds both: a 24-row list and a 15-row folded one."""
    assert len(m.station_table("native")) == 24
    assert len(m.station_table("aggregated")) == 15


def test_the_aggregated_view_folds_exactly_what_nodes_xlsx_folds():
    assert m.FOLDED == {
        "Cliff": "Cathaleen's Fall",
        "Golagh": "Clogher",
        "Mulreavy": "Clogher",
        "Meentycat": "Drumkeen",
        "Lenalea": "Letterkenny",
        "Garvagh": "Corderry",
        "Cunghill": "Sligo",
        "Tawnaghmore": "Moy",
        "Srananagh 110": "Srananagh 220",
    }


def test_every_region_bus_is_a_real_bus_at_the_right_voltage(case):
    kv = case.bus.set_index("I")["BASKV"]
    for station in m.STATIONS:
        for bus in station.buses:
            assert bus in kv.index, (station.name, bus)
            assert float(kv[bus]) == station.kv, (station.name, bus)


def test_srananagh_is_two_busbars_natively_and_one_node_folded(case):
    native, folded = m.bus_map("native"), m.bus_map("aggregated")
    assert native[5041] == "Srananagh 110"
    assert native[5042] == "Srananagh 220"
    assert folded[5041] == folded[5042] == "Srananagh 220"
    tx = m.circuits(case, "native")
    tx = tx[tx["kind"] == "transformer"]
    assert len(tx) == 1
    assert set(tx.iloc[0][["from", "to"]]) == {"Srananagh 110",
                                               "Srananagh 220"}
    assert tx.iloc[0]["rate1_mva"] == 250.0
    # nodes.xlsx has one Srananagh node, so the transformer is inside it.
    assert (m.circuits(case, "aggregated")["kind"] == "transformer").sum() == 0


def test_the_srananagh_transformer_is_three_winding_with_an_idle_tertiary(case):
    """It is a 220/110/10.5 kV unit; the 10.5 kV winding carries nothing."""
    t = case.transformer
    row = t[(t["I"] == 5042) & (t["J"] == 5041)]
    assert len(row) == 1
    assert int(row.iloc[0]["WINDINGS"]) == 3
    assert int(row.iloc[0]["K"]) == 50421
    assert case.generator[case.generator["I"] == 50421].empty
    assert case.load[case.load["I"] == 50421].empty


# --------------------------------------------------------------------------- #
# The circuit table
# --------------------------------------------------------------------------- #

def test_the_aggregated_view_is_15_stations_on_16_routes(case):
    """The count the hand-built dataset reports."""
    frame = m.circuits(case, "aggregated")
    assert len(m.station_table("aggregated")) == 15
    assert len(m.routes(frame)) == 16


def test_tytfs_has_19_circuits_on_those_16_routes(case):
    """The disagreement: three of the routes are double circuits."""
    frame = m.circuits(case, "aggregated")
    assert len(frame) == 19
    doubled = m.routes(frame)
    doubled = doubled[doubled["circuits"] > 1]
    assert set(doubled["route"]) == {
        "Cathaleen's Fall - Clogher",
        "Cathaleen's Fall - Srananagh 220",
        "Sligo - Srananagh 220",
    }
    assert (doubled["circuits"] == 2).all()


def test_the_native_view_has_29_circuits_on_25_routes(case):
    """28 lines and the Srananagh transformer."""
    frame = m.circuits(case, "native")
    assert len(frame) == 29
    assert (frame["kind"] == "line").sum() == 28
    assert (frame["kind"] == "transformer").sum() == 1
    assert len(m.routes(frame)) == 25


def test_folding_lenalea_moves_a_circuit_rather_than_removing_it(case):
    """Four of the five folds are radial spurs; Lenalea is not.

    Lenalea sits between Letterkenny and Tievebrack, so folding it into
    Letterkenny drops the Letterkenny-Lenalea circuit and turns the
    Lenalea-Tievebrack one into a Letterkenny-Tievebrack circuit that has lost
    an impedance.  That is where most of the aggregated view's flow error is.
    """
    native = set(m.routes(m.circuits(case, "native"))["route"])
    aggregated = set(m.routes(m.circuits(case, "aggregated"))["route"])
    assert "Lenalea - Letterkenny" in native
    assert "Lenalea - Tievebrack" in native
    assert "Letterkenny - Tievebrack" in aggregated
    assert not any("Lenalea" in r for r in aggregated)


def test_couplers_inside_a_station_are_not_circuits(case):
    """Clogher's four busbars and Cathaleen's Fall's three are one station
    each, so the zero-impedance branches between them are not routes."""
    frame = m.circuits(case, "native")
    assert not (frame["from"] == frame["to"]).any()
    for _, row in frame.iterrows():
        assert not (row["x_pu"] == 0.0001 and row["km"] == 0.0), row["route"]


# --------------------------------------------------------------------------- #
# The boundary
# --------------------------------------------------------------------------- #

def test_the_region_has_six_ties_and_is_not_radial(case):
    """Srananagh is the principal export path, not the only one."""
    ties = m.boundary(case, "native")
    assert len(ties) == 6
    assert set(ties["outside_name"]) == {
        "ARIGNA_T", "CORRACLASSY", "STRA_PST", "BELLACORICK", "FLAGFORD"}
    assert (ties["station"] == m.SLACK_STATION).sum() == 1


def test_one_of_the_ties_leaves_the_jurisdiction(case):
    """Letterkenny to Strabane, in Co. Tyrone."""
    ties = m.boundary(case, "native")
    northern = ties[ties["outside_name"] == "STRA_PST"]
    assert len(northern) == 1
    area = case.bus.set_index("I")["AREA"]
    for bus in northern["outside_bus"]:
        assert int(area[int(bus)]) in psse.NI_AREAS


# --------------------------------------------------------------------------- #
# Supply and demand
# --------------------------------------------------------------------------- #

def test_capacity_dispatch_and_demand_are_three_different_numbers(case):
    frame = m.balance(case, "aggregated")
    assert frame["capacity_mw"].sum() == pytest.approx(1154.76, abs=0.5)
    assert frame["dispatched_mw"].sum() == pytest.approx(69.3, abs=0.5)
    assert frame["demand_mw"].sum() == pytest.approx(212.64, abs=0.5)


def test_no_published_case_runs_the_region_s_fleet():
    """None of the four is a high-wind case, so none shows the export the
    region is constrained for.

    Two of them export - by 23 and 35 MW, against more than a gigawatt of
    connected capacity - and two import. What they have in common is that
    between 6% and 21% of the fleet's capacity is dispatched.
    """
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    pytest.importorskip("pypsa")
    for name, c in psse.read_all().items():
        frame = m.balance(c, "aggregated")
        share = frame["dispatched_mw"].sum() / frame["capacity_mw"].sum()
        assert 0.0 <= share < 0.25, (name, share)
        ties = m.boundary_flows(c, "native")
        assert abs(ties["into_region_mw"].sum()) < 0.2 * \
            frame["capacity_mw"].sum(), name


# --------------------------------------------------------------------------- #
# The extraction
# --------------------------------------------------------------------------- #

def test_the_native_extract_reproduces_the_full_network(case, model):
    """Same impedances, same injections, a different reference bus."""
    agreement = m.compare_with_full(case, "native", model=model)
    assert len(agreement) == 28
    assert agreement["difference_mw"].abs().max() < 0.02


def test_the_aggregated_extract_costs_twenty_megawatts(case, model):
    """The price of the 15-node topology, measured rather than asserted.

    Almost all of it is one fold: nodes.xlsx has a single Srananagh node, so
    the 250 MVA 220/110 kV transformer is inside it and its impedance is gone.
    """
    agreement = m.compare_with_full(case, "aggregated", model=model)
    worst = agreement["difference_mw"].abs().max()
    assert 15.0 < worst < 30.0


def test_both_views_solve(case, model):
    pytest.importorskip("highspy")
    for view in m.VIEWS:
        result = m.verify(case, view, model=model)
        assert result["connected"], view
        assert result["dc_pf"] == "solved", view
        assert str(result["lopf"]).startswith("ok"), view


def test_the_slack_is_the_220_kv_busbar(case, model):
    n, _ = m.extract(case, "native", model=model)
    assert n.buses.at[m.SLACK_STATION, "control"] == "Slack"
    assert (n.generators["control"] == "Slack").sum() == 1
    slack = n.generators.index[n.generators["control"] == "Slack"][0]
    assert n.generators.at[slack, "bus"] == m.SLACK_STATION


# --------------------------------------------------------------------------- #
# The two named stations
# --------------------------------------------------------------------------- #

def test_cathaleens_fall_is_three_busbars_and_two_hydro_units(case):
    station = next(s for s in m.STATIONS if s.name == "Cathaleen's Fall")
    assert station.buses == (1701, 17010, 17061)
    machines = case.generator[case.generator["I"].isin((17073, 17074))]
    assert len(machines) == 2
    assert (machines["STAT"] == 1).all()
    assert machines["PT"].sum() == pytest.approx(45.5)


def test_clady_is_in_no_source_as_a_transmission_station(case):
    """Absent from TYTFS at every voltage, and from EirGrid's 110 kV register.

    OpenStreetMap has it as a 38 kV ESB Networks station at Gweedore, which is
    why: it is below the transmission model's floor.
    """
    assert not case.bus["NAME"].str.contains("CLAD", case=False,
                                             na=False).any()
    candidates = "data/osm_substations.csv"
    if os.path.exists(candidates):
        osm = pd.read_csv(candidates, keep_default_na=False)
        clady = osm[osm["names"].str.contains("Clady", na=False)]
        assert len(clady) >= 1
        voltages = set()
        for value in clady["voltage_kv"]:
            voltages |= {float(v) for v in str(value).split(";") if v}
        assert voltages and max(voltages) < pypsa_net.TRANSMISSION_KV


def test_ardnagappary_is_the_gweedore_area_station_and_carries_no_hydro(case):
    """The nearest transmission station to Clady, 2 km away - and what it has
    is the Cronalaght wind farm, not a hydro unit."""
    name = case.bus.set_index("I")["NAME"].str.strip()
    machines = case.generator.copy()
    machines["bus_name"] = machines["I"].map(name)
    here = machines[machines["bus_name"].str.contains("CRONALAG", na=False)]
    assert len(here) == 3
    assert here["PT"].sum() == pytest.approx(22.94, abs=0.01)
    assert (here["STAT"] == 0).all()
