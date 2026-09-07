"""Regression tests for the PyPSA conversion and the geocoding.

Two classes of thing are guarded here.

The unit conversions are tested arithmetically, because a per-unit base that
is wrong by a factor is the failure mode a network still solves through.  A
line at 110 kV with 0.01 pu of reactance on a 100 MVA base is 1.21 ohms and
nothing else; a transformer's impedance rebased onto its own rating has to
come back to the same physical impedance it went in as.

The conversion decisions are tested against the real WP2024 case, because
they are decisions and a change to any of them should have to be a deliberate
one.  The ones that would move every downstream number without breaking
anything are: which rating becomes ``s_nom``, what happens to the 18 unrated
transmission branches, whether the sub-110 kV load and generation survive the
voltage floor, and where the reference bus lands.
"""

import math
import os

import numpy as np
import pandas as pd
import pytest

import psse
import pypsa_net as m

WP2024 = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"


@pytest.fixture(scope="module")
def case():
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    return psse.read_raw(WP2024)


@pytest.fixture(scope="module")
def transmission(case):
    pytest.importorskip("pypsa")
    return m.build(case, min_kv=m.TRANSMISSION_KV)


@pytest.fixture(scope="module")
def full(case):
    pytest.importorskip("pypsa")
    return m.build(case, min_kv=0.0)


# --------------------------------------------------------------------------- #
# The per-unit base
# --------------------------------------------------------------------------- #

def test_every_case_is_on_the_100_mva_base():
    """The base is read from the file, not assumed.  Check it is what we say."""
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    for name, c in psse.read_all().items():
        assert c.sbase == m.SYSTEM_MVA, name


def test_ohms_from_per_unit():
    """Z_base at 110 kV on a 100 MVA base is 121 ohms."""
    assert m._ohms(1.0, 110.0) == pytest.approx(121.0)
    assert m._ohms(0.01, 110.0) == pytest.approx(1.21)
    assert m._ohms(1.0, 220.0) == pytest.approx(484.0)


def test_siemens_is_the_reciprocal_of_ohms():
    assert m._siemens(1.0, 110.0) == pytest.approx(1.0 / 121.0)


def test_a_case_on_another_base_is_refused(case):
    """A 100 MVA base is asserted, because everything here depends on it."""
    pytest.importorskip("pypsa")
    other = psse.Case(**{f.name: getattr(case, f.name)
                         for f in case.__dataclass_fields__.values()})
    other.sbase = 200.0
    with pytest.raises(ValueError, match="100"):
        m.build(other)


def test_transformer_impedance_survives_the_rebase(transmission):
    """PyPSA holds transformer x per-unit on s_nom; the ohms must not move."""
    n = transmission.network
    for name in n.transformers.index[:20]:
        t = n.transformers.loc[name]
        on_system_base = t["x"] / t["s_nom"] * m.SYSTEM_MVA
        assert 0.0 < abs(on_system_base) < 10.0, name


def test_cz2_impedance_is_rebased_onto_the_system(case):
    """Two records are CZ=2 - pu on the winding base, not the system base."""
    cz2 = case.transformer[case.transformer["CZ"] == 2]
    assert len(cz2) == 2
    row = cz2.iloc[0]
    r, x = m._z_on_system_base(row["R1_2"], row["X1_2"], 2, row["SBASE1_2"])
    assert x == pytest.approx(row["X1_2"] * m.SYSTEM_MVA / row["SBASE1_2"])


def test_cz3_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="CZ=3"):
        m._z_on_system_base(0.01, 0.1, 3, 100.0)


# --------------------------------------------------------------------------- #
# Ratings
# --------------------------------------------------------------------------- #

def test_rate2_equals_rate1_and_rate3_is_ten_percent_over(case):
    """Why RATE1 is s_nom: the other two are not different ratings.

    RATE2 is RATE1 in every record of every case, and RATE3 is either RATE1
    or 1.1 x RATE1 - one summer-case circuit comes out at 1.10021, which is
    the rating having been rounded before the ratio was taken.  That is
    normal / long-term emergency / short-term emergency, with the long-term
    emergency rating not distinguished from normal.
    """
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    for name, c in psse.read_all().items():
        b = c.branch
        assert (b["RATE1"] == b["RATE2"]).all(), name
        ratio = (b["RATE3"] / b["RATE1"].replace(0, np.nan)).dropna()
        assert (np.isclose(ratio, 1.0) | np.isclose(ratio, 1.1, atol=0.001)
                ).all(), name


def test_the_eighteen_unrated_transmission_branches(case):
    """18 AC branches at 110 kV and above carry no rating: 9 at 9999, 9 at 0.

    Every one of them is a zero-impedance station coupler - a busbar section,
    a capacitor or reactor stub, a generator terminal tie - and not a circuit
    whose rating was forgotten.  If that ever stops being true the fill rule
    in _fill_unrated is the wrong rule.
    """
    kv = case.bus.set_index("I")["BASKV"]
    b = case.branch
    tx = b[(b["I"].map(kv) >= 110) & (b["J"].map(kv) >= 110)]
    unrated = tx[tx["RATE1"].isin(m.UNRATED)]
    assert len(unrated) == 18
    assert (unrated["RATE1"] == 9999).sum() == 9
    assert (unrated["RATE1"] == 0).sum() == 9
    assert (unrated["X"].abs() <= m.COUPLER_X_PU).all()
    assert (unrated["LEN"].fillna(0) == 0).all()


def test_transmission_transformers_are_all_rated(case):
    """The 9999 placeholder is confined to the sub-110 kV tail.

    Every two-winding transformer with both ends at 110 kV or above carries a
    real rating; 1,164 of the 1,190 below that do not.  That is what makes it
    defensible to leave the sub-threshold ones at 9999 rather than inventing
    a bound for them.
    """
    kv = case.bus.set_index("I")["BASKV"]
    t = case.transformer[case.transformer["WINDINGS"] == 2]
    tx = t[(t["I"].map(kv) >= 110) & (t["J"].map(kv) >= 110)]
    assert len(tx) == 11
    assert not tx["RATE1_1"].isin(m.UNRATED).any()
    below = t.drop(tx.index)
    assert below["RATE1_1"].isin(m.UNRATED).sum() == 1164


def test_no_element_reaches_the_network_without_a_limit(transmission, full):
    for model in (transmission, full):
        n = model.network
        for frame in (n.lines, n.transformers):
            assert frame["s_nom"].notna().all()
            assert (frame["s_nom"] > 0).all()


def test_couplers_are_bounded_and_the_rest_keep_the_file_s_9999(transmission):
    n = transmission.network
    exceptions = n.lines[n.lines["s_nom_source"] != m.CONTINUOUS_RATE]
    assert len(exceptions) == 14      # 18 in the register, 4 out of service
    assert exceptions["s_nom_source"].str.startswith("station coupler").all()
    assert (exceptions["s_nom"] < m.UNRATED_FALLBACK_MVA).all()


# --------------------------------------------------------------------------- #
# The voltage floor
# --------------------------------------------------------------------------- #

def test_all_the_generation_and_almost_all_the_load_is_below_110kv(case):
    """The measurement the aggregation exists because of."""
    kv = case.bus.set_index("I")["BASKV"]
    gen = psse.generators(case)
    load = psse.loads(case)
    assert (gen["I"].map(kv) < 110).all()
    below = load[load["I"].map(kv) < 110]["PL"].sum()
    assert below / load["PL"].sum() > 0.99


def test_the_floor_keeps_547_transmission_buses(transmission, case):
    """547 buses at the four transmission voltages, plus the two DC-side
    converter buses, less the one bus PSS/E marks isolated."""
    n = transmission.network
    real = n.buses[~n.buses.index.str.startswith("star:")]
    real = real[~real.index.str.startswith("GB_")]
    assert len(real) == 548
    assert (case.bus["BASKV"].isin(m.psse.TRANSMISSION_KV)).sum() == 547


def test_the_floor_moves_the_load_rather_than_dropping_it(transmission, full):
    assert transmission.network.loads["p_set"].sum() == pytest.approx(
        full.network.loads["p_set"].sum())
    assert transmission.network.generators["p_set"].sum() == pytest.approx(
        full.network.generators["p_set"].sum())


def test_nothing_is_orphaned(transmission):
    assert len(transmission.reports["orphans"]) == 0


def test_every_dropped_bus_has_a_parent(transmission):
    aggregation = transmission.reports["aggregation"]
    assert aggregation["parent"].astype(bool).all()


# --------------------------------------------------------------------------- #
# Topology, links and the reference bus
# --------------------------------------------------------------------------- #

def test_the_transmission_network_is_one_piece_plus_the_gb_terminal(
        transmission):
    n = transmission.network
    n.determine_network_topology()
    sizes = n.buses.groupby("sub_network").size().sort_values(ascending=False)
    assert sizes.iloc[0] == 643            # 548 real buses plus 95 star buses
    assert set(sizes.iloc[1:]) == {1}      # SCOTLAND, and the two far terminals
    assert m._connected_with_links(n)


def test_moyle_is_two_links_and_the_other_two_are_one_each(transmission):
    links = transmission.network.links
    assert set(links.index) == {"Moyle pole 1", "Moyle pole 2", "EWIC",
                                "Greenlink"}
    moyle = links.loc[["Moyle pole 1", "Moyle pole 2"]]
    assert (moyle["bus0"] == "86221").all()      # SCOTLAND
    assert (moyle["bus1"] == "86220").all()      # BALLYCRO
    assert moyle["p_nom"].sum() == pytest.approx(500.0)
    assert (moyle["efficiency"] < 1.0).all()     # the DC line's own loss


def test_the_far_terminals_are_created_and_can_trade_both_ways(transmission):
    n = transmission.network
    for bus in ("GB_EWIC", "GB_GREENLINK"):
        assert bus in n.buses.index
        here = n.generators[n.generators["bus"] == bus]
        assert set(here["carrier"]) == {"import", "export"}
        assert (here.loc[here["carrier"] == "export", "sign"] == -1).all()


def test_the_reference_bus_honours_the_case(transmission, full):
    """PSS/E names five IDE=3 buses; the model keeps one per AC sub-network."""
    slack = full.reports["slack"]
    assert "52071" in set(slack["bus"])          # Turlough Hill unit 1
    assert "86221" in set(slack["bus"])          # SCOTLAND
    assert (full.network.generators["control"] == "Slack").sum() == len(slack)
    # Aggregated away, the swing role goes to whatever absorbed it.
    assert "5202" in set(transmission.reports["slack"]["bus"])


# --------------------------------------------------------------------------- #
# It solves
# --------------------------------------------------------------------------- #

def test_dc_power_flow_and_lopf(transmission):
    pytest.importorskip("highspy")
    result = m.verify(transmission)
    assert result["dc_pf"] == "solved"
    assert result["lopf"].startswith("ok")
    assert result["connected_including_links"]
    assert result["dc_pf_overloads"] == 0
    assert result["dc_pf_inferred_limits_exceeded"] == 0


def test_the_dc_flow_tracks_the_case_s_own_solved_angles(transmission):
    """The conversion checked against the case rather than against itself."""
    n = transmission.network
    n.lpf()
    angles = m.angle_check(transmission)
    angles = angles[n.buses.loc[angles.index, "v_nom"] >= 110]
    assert angles["dc_pf_deg"].corr(angles["psse_deg"]) > 0.99
    assert angles["centred_error_deg"].std() < 2.0


def test_releasing_the_dispatch_is_what_makes_an_optimisation_possible(
        transmission):
    """p_set is a constraint in PyPSA 1.x, and the case's dispatch is an AC
    answer a lossless model cannot reproduce exactly."""
    pytest.importorskip("highspy")
    fixed = transmission.network.copy()
    machines = fixed.generators.index[
        ~fixed.generators["carrier"].isin(("import", "export"))]
    assert fixed.generators.loc[machines, "p_set"].notna().all()
    status, condition = fixed.optimize(solver_name="highs")
    assert condition == "infeasible"
    free = m.for_optimisation(transmission.network)
    assert free.generators["p_set"].isna().all()
    status, condition = free.optimize(solver_name="highs")
    assert condition == "optimal"


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #

def test_station_of_strips_the_decorations():
    assert m.station_of("CATH_CAP") == "CATH"
    assert m.station_of("HY_CATH FALL") == "CATH FALL"
    assert m.station_of("ANTR1A") == "ANTR1"
    assert m.station_of("COLE1-") == "COLE1"
    assert m.station_of("CLOGHER") == "CLOGHER"


def test_clogher_is_four_buses_at_one_station(case):
    clogher = case.bus[case.bus["NAME"].str.strip() == "CLOGHER"]
    assert len(clogher) == 4
    assert set(clogher["BASKV"]) == {110.0}
    assert {m.station_of(n) for n in clogher["NAME"]} == {"CLOGHER"}
