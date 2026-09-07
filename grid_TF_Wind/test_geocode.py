"""Regression tests for the OpenStreetMap geocoding.

The normalisation and the matching rules are tested on their own, because a
matcher that gets looser is a matcher that quietly starts putting stations in
the wrong place, and nothing downstream would notice.

The three cases in the module docstring - Cathaleen's Fall, Clady and
Clogher - are tested against the real data, because they are the three the
work was asked to solve and each of them turned out to be a different kind of
problem: a spelling, an absence, and a split busbar.
"""

import os

import numpy as np
import pandas as pd
import pytest

import geocode as m
import psse

WP2024 = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"
RESULT = "data/pypsa/geocoding/TYTFS2024_WP2024_V35.csv"


@pytest.fixture(scope="module")
def candidates():
    if not os.path.exists(m.CANDIDATES_PATH):
        pytest.skip("OSM candidate table not present; run geocode.py fetch")
    return m.load_candidates()


@pytest.fixture(scope="module")
def result():
    if not os.path.exists(RESULT):
        pytest.skip("geocoding not run; run geocode.py match")
    return pd.read_csv(RESULT)


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

def test_normalise_strips_what_is_not_the_name():
    assert m.normalise("Cashla 220 kV Substation") == "CASHLA"
    assert m.normalise("110kV Kilbarry Electrical Substation") == "KILBARRY"
    assert m.normalise("Turlough Hill Power Station") == "TURLOUGH HILL"
    assert m.normalise("Cathleen's Fall 110kV Substation") == "CATHLEENS FALL"


def test_normalise_agrees_across_the_two_sources_spelling_choices():
    assert m.normalise("Liberty St") == m.normalise("Liberty Saint")
    assert m.normalise("A & B") == m.normalise("A and B")


def test_normalise_is_empty_for_nothing():
    assert m.normalise("") == ""
    assert m.normalise(None) == ""


# --------------------------------------------------------------------------- #
# The matching rules
# --------------------------------------------------------------------------- #

def test_subsequence_span_measures_how_tightly_a_contraction_sits():
    """LARN is Larne's first four letters and is scattered over Lisnabreeny."""
    assert m._subsequence_span("LARN", "LARNE") == 3
    assert m._subsequence_span("LARN", "LISNABREENY") == 9
    assert m._subsequence_span("BAME", "BALLYMENA") == 6
    assert m._subsequence_span("LARN", "OMAGH") is None
    assert m._subsequence_span("MAGF", "AMAGHERAFELT") is None  # wrong start


def test_a_silent_voltage_tag_is_not_a_disagreement():
    assert m._voltage_verdict({110.0}, "") == ("silent", True)
    assert m._voltage_verdict({110.0}, "110;38")[1] is True
    assert m._voltage_verdict({110.0}, "33")[1] is False


def test_380kv_matches_osm_s_400kv():
    """The cases put the 400 kV network on a 380 kV base; OSM tags nominal."""
    verdict, ok = m._voltage_verdict({380.0}, "400;220")
    assert ok and "380" in verdict


def test_the_ni_code_digit_is_the_voltage_class():
    assert m.NI_CODE_KV["1"] == 110.0
    assert m.NI_CODE_KV["2"] == 275.0
    assert m.NI_CODE.match("BAFD2").groups() == ("BAFD", "2")
    assert m.NI_CODE.match("BROCK1").groups() == ("BROCK", "1")
    assert m.NI_CODE.match("CLOGHER") is None


# --------------------------------------------------------------------------- #
# The three hard cases
# --------------------------------------------------------------------------- #

def test_cathaleens_fall_is_in_tytfs_under_a_truncated_name():
    """It is there - as CATH_FALL and CATH FALL - and OSM spells it without
    the second 'a'."""
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    case = psse.read_raw(WP2024)
    names = set(case.bus["NAME"].str.strip())
    assert {"CATH_FALL", "CATH FALL", "CATH_CAP"} <= names
    assert "CATHALEENS FALL" not in {m.normalise(n) for n in names}


def test_cathaleens_fall_is_placed_through_the_alias_table(result):
    rows = result[result["station"].isin(["CATH_FALL", "CATH FALL"])]
    assert len(rows) == 2
    assert (rows["method"] == "alias").all()
    assert (rows["osm_name"] == "Cathleen's Fall 110kV Substation").all()
    assert rows["lat"].round(2).eq(54.50).all()
    assert rows["lon"].round(2).eq(-8.18).all()


def test_the_cathaleens_fall_capacitor_is_placed_from_the_station(result):
    stub = result[result["psse_names"] == "CATH_CAP"]
    assert len(stub) == 1
    assert stub["method"].iloc[0] == "coupled"
    assert stub["lat"].iloc[0] == pytest.approx(54.4988, abs=0.01)


def test_clady_is_absent_from_tytfs_because_it_is_a_38kv_station(candidates):
    """Not a naming problem: OSM has Clady at 38 kV, below the model's floor."""
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    case = psse.read_raw(WP2024)
    assert not case.bus["NAME"].str.contains("CLAD", case=False,
                                             na=False).any()
    clady = candidates[candidates["name"].str.contains("Clady", na=False)]
    assert len(clady) >= 1
    voltages = set()
    for v in clady["voltage_kv"]:
        voltages |= {float(x) for x in str(v).split(";") if x}
    assert voltages and max(voltages) < 110.0


def test_clogher_is_four_buses_and_one_place(result):
    rows = result[result["station"] == "CLOGHER"]
    assert len(rows) == 4
    assert sorted(rows["bus"]) == [2870, 2871, 28710, 28712]
    assert (rows["method"] == "exact").all()
    assert rows["osm"].nunique() == 1
    assert rows["lat"].nunique() == 1


# --------------------------------------------------------------------------- #
# The result as a whole
# --------------------------------------------------------------------------- #

def test_no_coordinate_without_an_accepted_method(result):
    placed = result["method"].isin(m.ACCEPTED)
    assert result.loc[placed, "lat"].notna().all()
    assert result.loc[~placed, "lat"].isna().all()
    assert result.loc[~placed, "lon"].isna().all()


def test_every_failure_carries_a_reason(result):
    failures = result[~result["method"].isin(m.ACCEPTED)]
    assert len(failures) > 0
    assert failures["method"].astype(bool).all()
    assert failures["note"].notna().all()
    assert (failures["note"].str.len() > 0).all()


def test_every_coordinate_is_on_the_island(result):
    placed = result[result["method"].isin(m.ACCEPTED)]
    assert placed["lat"].between(51.3, 55.5).all()
    assert placed["lon"].between(-10.8, -5.3).all()


def test_the_gb_end_of_moyle_is_left_unplaced_on_purpose(result):
    row = result[result["station"] == "SCOTLAND"].iloc[0]
    assert row["method"] == "deliberately-unplaced"
    assert np.isnan(row["lat"])


def test_most_buses_are_placed(result):
    """A floor, not a target.  It moves when OSM or the matcher moves, and it
    is here so that a change that halves the match rate has to be noticed."""
    placed = result["method"].isin(m.ACCEPTED)
    assert placed.mean() > 0.80


def test_the_crosscheck_against_eirgrid_agrees(result):
    """The strongest evidence the matching is right: 134 of the placed
    stations are in EirGrid's own register too, and the two sources put them
    in the same place to within a few metres."""
    path = RESULT.replace(".csv", "_crosscheck.csv")
    if not os.path.exists(path):
        pytest.skip("cross-check not run")
    checks = pd.read_csv(path)
    assert len(checks) > 100
    assert checks["distance_km"].median() < 0.05
    assert checks["distance_km"].quantile(0.95) < 1.0
    # One station disagrees, and the disagreement is EirGrid's: its register
    # puts Tandragee at the Republic's end of the interconnector, in Co.
    # Louth, 36 km from the substation itself in Co. Armagh.
    assert (~checks["agrees"]).sum() <= 1
