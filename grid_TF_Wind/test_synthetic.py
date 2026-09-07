"""Regression tests for the synthetic profile generator.

The tests that matter most are the ones about **spatial correlation**, because
that is the single thing this module exists to get right and the single thing
that is invisible in a plot of any one bus.  Independent noise per bus would
pass every other test in this file: the profiles would be in [0, 1], the load
factor would be 30%, the demand shape would have an evening peak.  It would
also make the fleet aggregate nearly constant and produce no dispatch-down at
all, and the two tests below would fail.

The anchors are tested against the case files themselves, so a change to the
anchoring that stops the year passing through the TYTFS states is caught.
"""

import math
import os

import numpy as np
import pandas as pd
import pytest

import profiles
import psse
import synthetic as m

WP2033 = "data/TYTFS2024_studyfiles/TYTFS2024_WP2033_V35.raw"
WP2024 = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"


@pytest.fixture(scope="module")
def case():
    if not os.path.exists(WP2033):
        pytest.skip("TYTFS study files not present")
    return psse.read_raw(WP2033)


@pytest.fixture(scope="module")
def states():
    if not os.path.exists(WP2033):
        pytest.skip("TYTFS study files not present")
    return m.anchors()


@pytest.fixture(scope="module")
def result(case, states):
    return m.build(case, year=2030, seed=m.SEED, anchor_frame=states)


# --------------------------------------------------------------------------- #
# The thing this module is for
# --------------------------------------------------------------------------- #

def test_wind_correlation_falls_with_distance(result):
    """The whole point.  Independent noise would be flat and near zero."""
    check = m.spatial_check(result)
    assert len(check) >= 5
    measured = check["measured_correlation"].to_numpy()
    assert (np.diff(measured) < 0).all(), "correlation must decay with distance"
    assert measured[0] > 0.85, "neighbouring sites must move together"
    assert measured[-1] < 0.5, "opposite ends of the island must not"


def test_the_measured_correlation_tracks_the_target(result):
    """Within a tolerance, because a copula and a power curve both soften it."""
    check = m.spatial_check(result)
    error = (check["measured_correlation"]
             - check["target_correlation"]).abs()
    assert error.max() < 0.10


def test_the_fleet_aggregate_actually_moves(result):
    """The other half of the check, and the one a plot would show.

    400 independent sites average out: the fleet series would sit near its
    mean with a standard deviation of a couple of points and never approach
    either rail.  A correlated field spends real time at both.
    """
    stats = m.fleet_variability(result)
    assert stats["std"] > 0.15
    assert stats["p05"] < 0.10
    assert stats["p95"] > 0.65
    assert stats["hours_below_0.05"] > 200
    assert stats["hours_above_0.80"] > 100


def test_calms_last_days_not_hours(result):
    """A synoptic timescale of 36 hours means a blocking high sits for days,
    which is what makes a duration curve rather than a histogram."""
    assert m.fleet_variability(result)["longest_calm_hours"] > 48


def test_correlation_survives_the_copula(monkeypatch):
    """The spatial correlation is imposed on the normal field; this checks it
    is still there after the map to a Weibull wind speed."""
    rng = np.random.default_rng(0)
    rho = np.array([[1.0, 0.9], [0.9, 1.0]])
    z = m.gaussian_field(20000, rho, timescale=1.0, rng=rng)
    speed = m.weibull_from_normal(z, 9.0)
    assert np.corrcoef(z, rowvar=False)[0, 1] == pytest.approx(0.9, abs=0.02)
    assert np.corrcoef(speed, rowvar=False)[0, 1] == pytest.approx(0.9,
                                                                   abs=0.04)


def test_the_correlation_matrix_is_the_stated_function():
    distance = np.array([[0.0, 400.0], [400.0, 0.0]])
    rho = m.correlation_matrix(distance, 400.0, nugget=0.0)
    assert rho[0, 0] == 1.0
    assert rho[0, 1] == pytest.approx(math.exp(-1.0))


def test_a_field_has_unit_variance_at_every_site():
    rng = np.random.default_rng(1)
    lat = np.array([53.0, 53.5, 54.5]);  lon = np.array([-6.0, -8.0, -7.0])
    rho = m.correlation_matrix(m.distance_matrix(lat, lon), 400.0)
    field = m.gaussian_field(20000, rho, 24.0, rng)
    assert np.allclose(field.std(axis=0), 1.0, atol=0.08)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #

def test_the_same_seed_gives_the_same_year(case, states):
    a = m.build(case, year=2030, seed=42, anchor_frame=states)
    b = m.build(case, year=2030, seed=42, anchor_frame=states)
    pd.testing.assert_frame_equal(a["p_max_pu"], b["p_max_pu"])
    pd.testing.assert_series_equal(a["demand"], b["demand"])


def test_a_different_seed_gives_a_different_year(case, states):
    a = m.build(case, year=2030, seed=42, anchor_frame=states)
    b = m.build(case, year=2030, seed=43, anchor_frame=states)
    assert not np.allclose(a["p_max_pu"].to_numpy(),
                           b["p_max_pu"].to_numpy())
    # but both still pass through the anchor
    hour = a["anchors"].set_index("case").loc[case.name, "snapshot"]
    assert a["demand"].loc[hour] == pytest.approx(b["demand"].loc[hour])


def test_the_default_seed_is_the_methodologys(states):
    assert m.SEED == 42


# --------------------------------------------------------------------------- #
# Anchoring on TYTFS
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["WP2024", "SV2024", "WP2033", "SV2033"])
def test_every_case_passes_through_its_own_state(name, states):
    path = f"data/TYTFS2024_studyfiles/TYTFS2024_{name}_V35.raw"
    if not os.path.exists(path):
        pytest.skip("TYTFS study files not present")
    case = psse.read_raw(path)
    built = m.build(case, year=2030, seed=m.SEED, anchor_frame=states)
    state = states[states["case"] == case.name].iloc[0]
    hour = built["anchors"].set_index("case").loc[case.name, "snapshot"]
    assert built["demand"].loc[hour] == pytest.approx(state["demand_mw"])
    assert built["fleet"]["wind"].loc[hour] == pytest.approx(
        state["wind_cf"], abs=1e-6)
    assert built["fleet"]["hydro"].loc[hour] == pytest.approx(
        state["hydro_cf"], abs=1e-6)


def test_the_annual_extremes_are_the_two_cases_of_the_vintage(case, states):
    built = m.build(case, year=2030, seed=m.SEED, anchor_frame=states)
    winter, summer = m.vintage_pair(states, case)
    assert built["demand"].max() == pytest.approx(winter["demand_mw"])
    assert built["demand"].min() == pytest.approx(summer["demand_mw"])
    assert built["demand"].idxmax() == m.anchor_index(
        built["demand"].index, "WP")
    assert built["demand"].idxmin() == m.anchor_index(
        built["demand"].index, "SV")


def test_a_2024_year_does_not_borrow_2033s_peak(states):
    """Each vintage spans its own pair; taking the largest case would put
    2033's demand into 2024's year."""
    case = psse.read_raw(WP2024)
    built = m.build(case, year=2030, seed=m.SEED, anchor_frame=states)
    assert built["demand"].max() == pytest.approx(
        float(states.loc[states["case"] == case.name, "demand_mw"].iloc[0]))


def test_an_unreachable_anchor_is_reported_not_forced(result, states):
    """WP2033 dispatches 373 MW of solar at a winter-peak evening.  At 18:00
    in January the sun is down, and putting daylight there would be worse than
    missing the anchor."""
    report = result["anchor_report"]
    solar = report[report["carrier"] == "solar"].iloc[0]
    assert solar["target_cf"] > 0
    assert solar["achievable_cf"] == 0.0
    assert "not applied" in solar["note"]
    hour = result["anchors"].set_index("case").loc[
        "TYTFS2024_WP2033_V35", "snapshot"]
    assert result["fleet"]["solar"].loc[hour] == 0.0


def test_the_taper_is_one_at_the_anchor_and_zero_outside():
    index = pd.date_range("2030-01-01", periods=96, freq="1h")
    centre = index[48]
    weight = m.taper(index, centre, window=18)
    assert weight[48] == pytest.approx(1.0)
    assert weight[48 - 18] == pytest.approx(0.0, abs=1e-12)
    assert weight[0] == 0.0 and weight[-1] == 0.0


# --------------------------------------------------------------------------- #
# The shapes
# --------------------------------------------------------------------------- #

def test_the_demand_shape_has_an_evening_peak_and_an_overnight_trough():
    assert int(np.argmax(m.WEEKDAY_SHAPE)) in (17, 18)
    assert int(np.argmin(m.WEEKDAY_SHAPE)) in (3, 4)
    assert m.WEEKDAY_SHAPE.max() == pytest.approx(1.0)


def test_the_year_keeps_that_shape(result):
    """Averaged over the year, the evening is still the peak."""
    demand = result["demand"]
    weekday = demand[demand.index.dayofweek < 5]
    by_hour = weekday.groupby(weekday.index.hour).mean()
    assert by_hour.idxmax() in (17, 18)
    assert by_hour.idxmin() in (3, 4, 5)


def test_weekends_are_lower_than_weekdays(result):
    demand = result["demand"]
    weekday = demand[demand.index.dayofweek < 5].mean()
    weekend = demand[demand.index.dayofweek >= 5].mean()
    assert weekend < weekday


def test_hydro_is_a_winter_baseload_with_an_evening_boost():
    index = pd.date_range("2030-01-01", periods=8760, freq="1h")
    hydro = m.hydro_profile(index, winter_cf=0.8, summer_cf=0.1)
    winter = hydro[hydro.index.month == 1].mean()
    summer = hydro[hydro.index.month == 7].mean()
    assert winter > summer
    by_hour = hydro.groupby(hydro.index.hour).mean()
    assert by_hour.loc[18] > by_hour.loc[3]
    assert (hydro <= 1.0).all() and (hydro >= 0.0).all()


def test_thermal_rises_with_demand():
    index = pd.date_range("2030-01-01", periods=48, freq="1h")
    demand = pd.Series(np.linspace(3000, 8000, 48), index=index)
    calm = pd.Series(np.zeros(48), index=index)
    assert m.thermal_profile(demand, calm).corr(demand) > 0.99


def test_thermal_backs_off_when_wind_is_high():
    """Demand held flat, wind rising: the envelope has to fall.

    Asserted across hours within one series rather than between two series,
    because the profile is rescaled to [floor, ceiling] over whatever it is
    given - so the first and last hours always sit on the rails and comparing
    two series at one hour compares two normalisations.
    """
    index = pd.date_range("2030-01-01", periods=48, freq="1h")
    demand = pd.Series(np.full(48, 6000.0), index=index)
    rising_wind = pd.Series(np.linspace(0.0, 1.0, 48), index=index)
    thermal = m.thermal_profile(demand, rising_wind)
    assert (np.diff(thermal.to_numpy()) < 0).all()
    assert thermal.iloc[0] == pytest.approx(1.0)
    assert thermal.iloc[-1] == pytest.approx(0.15)


# --------------------------------------------------------------------------- #
# The output
# --------------------------------------------------------------------------- #

def test_p_max_pu_is_a_per_unit_year(result):
    profile = result["p_max_pu"]
    assert profile.shape[0] == 8760
    assert profile.shape[1] > 500
    assert profile.to_numpy().min() >= 0.0
    assert profile.to_numpy().max() <= 1.0
    assert isinstance(profile.index, pd.DatetimeIndex)
    assert profile.index.name == "snapshot"
    assert not profile.isna().to_numpy().any()


def test_the_load_factor_lands_on_the_target(result):
    """The Weibull scale is solved for it rather than assumed."""
    assert result["fleet"]["wind"].mean() == pytest.approx(
        m.TARGET_WIND_LOAD_FACTOR, abs=0.05)


def test_demand_is_allocated_over_the_tytfs_load_records(case, result):
    loads = result["loads"]
    assert len(loads.columns) == len(psse.loads(case))
    assert np.allclose(loads.sum(axis=1).to_numpy(),
                       result["demand"].to_numpy())


def test_the_conversion_is_the_same_one_the_era5_path_uses():
    """Synthetic weather goes through profiles.py's converters unchanged, so
    the two paths differ in the weather and nowhere else."""
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"cell": ["a"], "lat": [53.3], "lon": [-6.3]})
    index = pd.date_range("2030-06-01", periods=48, freq="1h")
    fields = m.weather(frame, index, rng, wind_scale=9.0)
    assert set(fields["a"].columns) == set(profiles.VARIABLES)
    assert profiles.wind_capacity_factor(fields["a"]).between(0, 1).all()
    assert profiles.solar_capacity_factor(
        fields["a"], 53.3, -6.3).between(0, 1).all()


def test_the_erbs_diffuse_fraction_is_bounded():
    kt = np.linspace(0.0, 1.0, 101)
    fraction = m._erbs(kt)
    assert (fraction >= 0).all() and (fraction <= 1).all()
    assert fraction[0] > 0.9          # overcast is nearly all diffuse
    assert fraction[-1] < 0.3         # a clear sky is nearly all beam


# --------------------------------------------------------------------------- #
# The requirement: WP2033 has to bind
# --------------------------------------------------------------------------- #

def test_wp2033_produces_binding_constraints_and_dispatch_down(case, result):
    """If this fails the hackathon's central problem does not appear."""
    pytest.importorskip("highspy")
    report = m.binding(case, result, top=12)
    assert report["status"].startswith("ok")
    assert report["dispatch_down_gwh"] > 0.0
    assert report["dispatch_down_pct"] > 1.0
    assert report["hours_with_dispatch_down"] == report["hours"]
    assert report["distinct_binding_circuits"] >= 1
    assert report["max_loading"] >= 0.999


def test_the_binding_circuit_is_the_one_phase_3_predicted(case, result):
    """Phase 3 found Letterkenny-Strabane binds first, from a DC flow with the
    boundary pinned.  A full LOPF over synthetic correlated weather finds the
    same circuit, which is two different methods agreeing."""
    pytest.importorskip("highspy")
    report = m.binding(case, result, top=12)
    worst = max(report["worst_circuits"], key=report["worst_circuits"].get)
    assert worst == "3581-89516-1"        # Letterkenny - STRA_PST
