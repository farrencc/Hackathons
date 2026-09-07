"""Regression tests for the ERA5 profile pipeline.

The parts that can be tested without the network are tested here, and they are
most of the module: the power curve, the shear correction, the solar geometry,
the panel model, the demand allocation and the validation arithmetic.  The
fetch is the only thing that needs Open-Meteo, and what is tested about it is
that it caches, that it never asks twice, and that **every path that cannot
get real data raises instead of inventing one**.

The end-to-end test builds its profiles from a fixture cache written into a
temporary directory.  That fixture is a test input, not data: it is a
sawtooth, it is labelled as one, and nothing writes it anywhere the real
pipeline reads from.
"""

import json
import math
import os

import numpy as np
import pandas as pd
import pytest

import profiles as m
import psse

WP2024 = "data/TYTFS2024_studyfiles/TYTFS2024_WP2024_V35.raw"


@pytest.fixture(scope="module")
def case():
    if not os.path.exists(WP2024):
        pytest.skip("TYTFS study files not present")
    return psse.read_raw(WP2024)


# --------------------------------------------------------------------------- #
# The power curve
# --------------------------------------------------------------------------- #

def test_the_turbine_curve_is_the_curve_the_docstring_claims():
    assert m.turbine_curve([0.0])[0] == 0.0
    assert m.turbine_curve([m.CUT_IN - 0.01])[0] == 0.0
    assert m.turbine_curve([m.CUT_IN])[0] == pytest.approx(0.0)
    assert m.turbine_curve([m.RATED])[0] == pytest.approx(1.0)
    assert m.turbine_curve([m.CUT_OUT - 0.01])[0] == pytest.approx(1.0)
    assert m.turbine_curve([m.CUT_OUT])[0] == 0.0
    assert m.turbine_curve([40.0])[0] == 0.0


def test_the_ramp_is_the_cubic():
    v = 6.0
    expected = (v ** 3 - m.CUT_IN ** 3) / (m.RATED ** 3 - m.CUT_IN ** 3)
    assert m.turbine_curve([v])[0] == pytest.approx(expected)


def test_the_curve_is_monotonic_up_to_cut_out():
    v = np.arange(0.0, m.CUT_OUT, 0.1)
    p = m.turbine_curve(v)
    assert (np.diff(p) >= -1e-12).all()


def test_the_farm_curve_softens_both_knees():
    """A cell is 10 km across; a farm does not reach rated all at once, and it
    does not cut out all at once either."""
    speeds, power = m.farm_curve(spread=1.5)
    at = lambda v: float(np.interp(v, speeds, power))
    assert 0.0 < at(m.CUT_IN) < 0.05          # a little output below cut-in
    assert 0.80 < at(m.RATED) < 0.95          # not yet at rated
    assert 0.35 < at(m.CUT_OUT) < 0.65        # about half cut out
    assert at(32.0) < 0.05                    # all of it gone by 32 m/s
    assert (np.diff(power[:int(m.RATED / 0.05)]) >= -1e-9).all()


def test_zero_spread_gives_the_turbine_curve_back():
    speeds, power = m.farm_curve(spread=0.0)
    assert np.allclose(power, m.turbine_curve(speeds))


# --------------------------------------------------------------------------- #
# Hub height
# --------------------------------------------------------------------------- #

def test_the_shear_exponent_inverts_the_power_law():
    """v100 = v10 * 10**alpha by construction, so alpha comes back out."""
    for alpha in (0.10, 0.14, 0.25, 0.40):
        v10 = np.array([7.0])
        v100 = v10 * (100.0 / 10.0) ** alpha
        assert m.shear_exponent(v10, v100)[0] == pytest.approx(alpha)


def test_the_shear_exponent_is_clipped_not_infinite():
    """A calm hour with a near-zero 10 m wind must not produce nonsense."""
    alpha = m.shear_exponent(np.array([0.0, 1e-9]), np.array([12.0, 12.0]))
    assert np.isfinite(alpha).all()
    assert (alpha <= 0.60).all()


def test_a_hundred_metre_hub_is_a_no_op():
    v100 = np.array([3.0, 9.0, 18.0])
    assert np.allclose(m.hub_speed(v100, np.full(3, 0.2), 100.0), v100)


def test_a_taller_hub_sees_more_wind_and_a_shorter_one_less():
    v100 = np.array([8.0])
    alpha = np.array([0.20])
    assert m.hub_speed(v100, alpha, 150.0)[0] > 8.0
    assert m.hub_speed(v100, alpha, 80.0)[0] < 8.0
    # 150 m at alpha = 0.2 is 8 * 1.5**0.2
    assert m.hub_speed(v100, alpha, 150.0)[0] == pytest.approx(
        8.0 * 1.5 ** 0.2)


# --------------------------------------------------------------------------- #
# Solar geometry, against arithmetic that does not need this module
# --------------------------------------------------------------------------- #

def test_solar_noon_zenith_at_the_solstices():
    """At solar noon the zenith is |latitude - declination|, and the
    declination is +-23.44 degrees at the solstices."""
    lat, lon = 53.35, -6.26           # Dublin
    # Solar noon at 6.26 W is about 12:25 UTC.
    index = pd.DatetimeIndex(["2023-06-21 12:25", "2023-12-21 12:25"])
    zenith, _ = m.solar_position(index, lat, lon)
    assert zenith[0] == pytest.approx(lat - 23.44, abs=0.5)
    assert zenith[1] == pytest.approx(lat + 23.44, abs=0.5)


def test_the_sun_is_below_the_horizon_at_midnight():
    index = pd.DatetimeIndex(["2023-06-21 00:30", "2023-12-21 00:30"])
    zenith, _ = m.solar_position(index, 53.35, -6.26)
    assert (zenith > 90.0).all()


def test_the_sun_is_east_in_the_morning_and_west_in_the_afternoon():
    index = pd.DatetimeIndex(["2023-06-21 08:00", "2023-06-21 17:00"])
    _, azimuth = m.solar_position(index, 53.35, -6.26)
    assert 45.0 < azimuth[0] < 135.0
    assert 225.0 < azimuth[1] < 315.0


# --------------------------------------------------------------------------- #
# The panel model
# --------------------------------------------------------------------------- #

def test_a_horizontal_plane_sees_the_global_horizontal_irradiance():
    """With tilt 0 the three components collapse to GHI, whatever the sun is
    doing - which is the definition of GHI and a check on the sky model."""
    poa = m.plane_of_array(ghi=[800.0], dni=[600.0], zenith=[40.0],
                           azimuth=[180.0], tilt=0.0)
    assert poa[0] == pytest.approx(800.0, rel=1e-9)


def test_a_tilted_south_facing_plane_beats_horizontal_at_irish_latitudes():
    common = dict(ghi=[500.0], dni=[600.0], zenith=[60.0], azimuth=[180.0])
    assert (m.plane_of_array(tilt=35.0, **common)[0]
            > m.plane_of_array(tilt=0.0, **common)[0])


def test_night_produces_nothing():
    poa = m.plane_of_array(ghi=[0.0], dni=[0.0], zenith=[120.0],
                           azimuth=[0.0], tilt=35.0)
    assert poa[0] == 0.0


def test_the_capacity_factor_is_bounded_and_dark_at_night():
    index = pd.date_range("2023-06-21", periods=24, freq="1h", tz=None)
    weather = pd.DataFrame({
        "wind_speed_100m": np.full(24, 8.0),
        "wind_speed_10m": np.full(24, 6.0),
        "shortwave_radiation": np.clip(
            800 * np.sin((index.hour - 5) / 14 * np.pi), 0, None),
        "direct_normal_irradiance": np.clip(
            600 * np.sin((index.hour - 5) / 14 * np.pi), 0, None),
        "temperature_2m": np.full(24, 15.0),
    }, index=index)
    cf = m.solar_capacity_factor(weather, 53.35, -6.26)
    assert (cf >= 0).all() and (cf <= 1).all()
    assert cf.loc[index[1]] == 0.0            # 01:00
    assert cf.max() > 0.3


def test_a_hot_panel_makes_less_than_a_cold_one():
    index = pd.DatetimeIndex(["2023-06-21 12:25"])
    base = dict(wind_speed_100m=[8.0], wind_speed_10m=[6.0],
                shortwave_radiation=[900.0],
                direct_normal_irradiance=[800.0])
    cold = m.solar_capacity_factor(
        pd.DataFrame({**base, "temperature_2m": [5.0]}, index=index),
        53.35, -6.26)
    hot = m.solar_capacity_factor(
        pd.DataFrame({**base, "temperature_2m": [30.0]}, index=index),
        53.35, -6.26)
    assert cold.iloc[0] > hot.iloc[0]


# --------------------------------------------------------------------------- #
# Sites
# --------------------------------------------------------------------------- #

def test_sites_are_the_register_not_the_dispatch(case):
    """A year of weather is for running the fleet; WP2024 runs 6 machines."""
    frame = m.sites(case)
    assert len(frame) == 421
    assert frame["in_service"].sum() < 20
    assert set(frame["carrier"]) == {"wind", "solar"}


def test_cells_are_deduplicated_to_the_era5_land_grid(case):
    frame = m.sites(case)
    grid = m.cells(frame)
    assert len(grid) < len(frame)
    assert grid["generators"].sum() == (frame["cell"] != "").sum()
    for value in grid["lat"]:
        assert abs(value / m.CELL - round(value / m.CELL)) < 1e-9


def test_generators_without_coordinates_are_reported_not_dropped(case):
    frame = m.sites(case)
    missing = m.unplaced(frame)
    assert len(missing) == len(frame) - (frame["cell"] != "").sum()
    assert missing["p_nom"].sum() > 0


# --------------------------------------------------------------------------- #
# Demand
# --------------------------------------------------------------------------- #

def test_the_weights_come_from_the_in_service_load_and_sum_to_one(case):
    weights = m.load_weights(case)
    assert weights["weight"].sum() == pytest.approx(1.0)
    assert len(weights) == len(psse.loads(case))
    assert weights["tytfs_mw"].sum() == pytest.approx(
        psse.loads(case)["PL"].sum())


def test_allocation_preserves_the_island_total(case):
    island = pd.Series([3000.0, 4500.0, 5200.0],
                       index=pd.date_range("2023-01-01", periods=3, freq="1h"))
    allocated = m.allocate_demand(case, island)
    assert allocated.shape == (3, len(psse.loads(case)))
    assert np.allclose(allocated.sum(axis=1).to_numpy(), island.to_numpy())


def test_allocation_keeps_the_tytfs_spatial_shape(case):
    """Only the temporal shape comes from the dashboard."""
    island = pd.Series([1000.0], index=pd.date_range("2023-01-01", periods=1,
                                                     freq="1h"))
    allocated = m.allocate_demand(case, island)
    weights = m.load_weights(case).set_index("load")["weight"]
    share = allocated.iloc[0] / 1000.0
    assert np.allclose(share.to_numpy(), weights.loc[share.index].to_numpy())


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def test_validation_reports_correlation_and_error(case):
    index = pd.date_range("2023-01-01", periods=100, freq="1h")
    frame = m.sites(case)
    wind = frame[(frame["carrier"] == "wind") & (frame["cell"] != "")]
    profile = pd.DataFrame(
        {g: np.linspace(0.1, 0.6, 100) for g in wind["generator"]},
        index=index)
    modelled = m.fleet_wind(profile, frame)
    result = m.validate_wind(profile, frame, modelled)
    assert result["correlation"] == pytest.approx(1.0)
    assert result["mae_mw"] == pytest.approx(0.0, abs=1e-9)
    assert result["hours"] == 100


def test_validation_refuses_a_series_that_does_not_overlap(case):
    frame = m.sites(case)
    profile = pd.DataFrame(
        {g: [0.5] for g in frame["generator"][:3]},
        index=pd.date_range("2023-01-01", periods=1, freq="1h"))
    actual = pd.Series([100.0], index=pd.date_range("2019-01-01", periods=1,
                                                    freq="1h"))
    with pytest.raises(m.Unavailable, match="overlapping"):
        m.validate_wind(profile, frame, actual)


# --------------------------------------------------------------------------- #
# It refuses to invent
# --------------------------------------------------------------------------- #

def test_loading_a_cell_that_was_never_fetched_raises(tmp_path):
    with pytest.raises(m.Unavailable, match="does not simulate"):
        m.load_cell("+54.00_-008.00", 2023, directory=str(tmp_path))


def test_a_partial_year_is_not_cached_as_a_complete_one():
    block = {"hourly": {v: [1.0] * 100 for v in m.VARIABLES}}
    block["hourly"]["time"] = ["2023-01-01T00:00"] * 100

    class Cell:
        cell = "+54.00_-008.00"
    with pytest.raises(m.Unavailable, match="not a year"):
        m._check(block, Cell())


def test_a_response_missing_a_variable_is_refused():
    block = {"hourly": {"time": ["2023-01-01T00:00"] * 9000,
                        "wind_speed_100m": [5.0] * 9000}}

    class Cell:
        cell = "+54.00_-008.00"
    with pytest.raises(m.Unavailable, match="no "):
        m._check(block, Cell())


def test_an_unreadable_eirgrid_file_raises_rather_than_guessing(tmp_path):
    path = tmp_path / "mystery.csv"
    path.write_text("alpha,beta\n1,2\n")
    with pytest.raises(m.Unavailable, match="cannot tell"):
        m.read_eirgrid(str(path))


def test_the_eirgrid_url_is_the_documented_one():
    url = m.eirgrid_url("wind", 2023)
    assert url.startswith(m.DASHBOARD_URL)
    assert "area=windactual" in url and "region=ALL" in url
    assert "datefrom=2023-01-01" in url and "dateto=2023-12-31" in url


# --------------------------------------------------------------------------- #
# End to end, on a fixture cache
#
# The weather here is a sawtooth written into a temporary directory.  It is a
# test input and never touches data/raw/weather or data/profiles.
# --------------------------------------------------------------------------- #

def _fixture_year(directory, cell, year=2023, hours=8760):
    index = pd.date_range(f"{year}-01-01", periods=hours, freq="1h")
    ramp = np.linspace(0.0, 30.0, hours)
    block = {"hourly": {
        "time": [t.strftime("%Y-%m-%dT%H:%M") for t in index],
        "wind_speed_100m": list(ramp),
        "wind_speed_10m": list(ramp * 0.7),
        "shortwave_radiation": list(np.abs(np.sin(np.arange(hours))) * 600),
        "direct_normal_irradiance": list(np.abs(np.cos(np.arange(hours))) * 400),
        "temperature_2m": list(np.full(hours, 10.0)),
    }}
    os.makedirs(directory, exist_ok=True)
    with open(m.cache_path(cell, year, m.MODELS[0], directory), "w") as fh:
        json.dump(block, fh)


def test_end_to_end_through_a_fixture_cache(case, tmp_path):
    frame = m.sites(case)
    placed = frame[frame["cell"] != ""].head(40)
    directory = str(tmp_path / "weather")
    for cell in placed["cell"].unique():
        _fixture_year(directory, cell)

    profile = m.p_max_pu(placed, 2023, directory=directory)
    assert profile.shape[0] == 8760
    assert profile.shape[1] == len(placed)
    assert profile.min().min() >= 0.0 and profile.max().max() <= 1.0
    assert isinstance(profile.index, pd.DatetimeIndex)
    assert profile.index.name == "snapshot"
    # Two generators in one cell share a profile: that is the resolution of
    # the source, and adding noise to hide it would be the fabrication this
    # module exists to avoid.
    by_cell = placed.groupby(["cell", "carrier"])["generator"].apply(list)
    for members in by_cell:
        if len(members) > 1:
            first = profile[members[0]]
            for other in members[1:]:
                assert np.allclose(first, profile[other])


def test_fetch_never_asks_for_a_cell_it_already_has(case, tmp_path):
    frame = m.sites(case)
    grid = m.cells(frame).head(3)
    directory = str(tmp_path / "weather")
    for cell in grid["cell"]:
        _fixture_year(directory, cell)
    report = m.fetch(grid, 2023, directory=directory)
    assert report["requested"] == 0
    assert report["requests"] == 0
    assert report["cached"] == 3
