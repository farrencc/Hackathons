"""Tests for the realism check.

Most of this runs against ``data/validation/format_fixture.csv``, which is
**not historical data**: evenly spaced hand-made values, labelled as such in
every row, so that the reader and the overlap metric can be exercised with no
network.  The one test that would say something about realism -
``test_marginals_overlap_history`` - needs real history and skips, with the
reason, when there is none.  It does not fall back on the fixture.
"""

import os

import numpy as np
import pandas as pd
import pytest

import validate as m

HERE = os.path.dirname(os.path.abspath(__file__))


def test_fixture_is_labelled_in_every_row():
    frame = m.read_fixture(os.path.join(HERE, m.FIXTURE))
    assert frame["source"].str.contains(m.FIXTURE_MARK).all()


def test_the_fixture_is_refused_as_history():
    """It exercises the code; it must never stand in for a validation."""
    history = m.fixture_history(os.path.join(HERE, m.FIXTURE))
    scenarios = pd.DataFrame({"snsp": [0.3, 0.8], "E_pre_mws": [30e3, 20e3]})
    with pytest.raises(m.Unavailable):
        m.validate(scenarios, history)
    out = m.validate(scenarios, history, allow_fixture=True)
    assert set(out) == {"snsp", "inertia"}


def test_overlap_is_one_for_identical_and_zero_for_disjoint():
    x = np.linspace(0, 1, 200)
    same = m.overlap(x, x)
    assert same["overlap_coefficient"] == pytest.approx(1.0)
    assert same["ks_statistic"] == pytest.approx(0.0)
    apart = m.overlap(x, x + 5.0)
    assert apart["overlap_coefficient"] == pytest.approx(0.0)
    assert apart["share_inside_history_range"] == 0.0


def test_share_beyond_the_limits_is_counted_both_sides():
    history = m.fixture_history(os.path.join(HERE, m.FIXTURE))
    scenarios = pd.DataFrame({"snsp": [0.5, 0.8, 0.9, 0.2],
                              "E_pre_mws": [30e3, 20e3, 18e3, 40e3]})
    out = m.validate(scenarios, history, allow_fixture=True)
    assert out["snsp"]["ensemble_share_above_limit"] == 0.5
    assert out["inertia"]["ensemble_share_below_limit"] == 0.5
    # The fixture stays inside both limits by construction.
    assert out["snsp"]["history_share_above_limit"] == 0.0


def test_percent_snsp_is_read_as_a_fraction(tmp_path):
    path = tmp_path / "snsp_2024.csv"
    pd.DataFrame({"DateTime": ["01-01-2024 00:00", "01-01-2024 00:15"],
                  "Value": [45.0, 60.0]}).to_csv(path, index=False)
    series = m.read_series(str(path), "snsp")
    assert series.max() == pytest.approx(0.60)


def test_implausible_inertia_is_refused(tmp_path):
    path = tmp_path / "inertia_2024.csv"
    pd.DataFrame({"DateTime": ["01-01-2024 00:00"], "Value": [23.0]}) \
        .to_csv(path, index=False)
    with pytest.raises(m.Unavailable):
        m.read_series(str(path), "inertia")


def test_unreachable_dashboard_is_unavailable_not_invented(monkeypatch):
    import requests

    def refuse(*a, **k):
        raise requests.exceptions.ProxyError("403 Forbidden")

    monkeypatch.setattr(requests, "get", refuse)
    with pytest.raises(m.Unavailable, match="unreachable"):
        m.fetch_live()


def test_marginals_overlap_history():
    """The realism check proper: needs real history, skips without it."""
    import ensemble

    directory = os.path.join(HERE, ensemble.ENSEMBLE_DIR,
                             f"{ensemble.DEFAULT_VINTAGE}_seed{ensemble.SEED}"
                             f"_n{ensemble.DEFAULT_N}")
    if not os.path.isdir(directory):
        pytest.skip("no solved ensemble")
    try:
        history = m.find_history()
    except m.Unavailable as exc:
        pytest.skip(f"no historical SNSP/inertia data: {exc}")
    out = m.validate(ensemble.load(directory)["scenarios"], history)
    for kind, r in out.items():
        assert r["overlap_coefficient"] > 0.2, (kind, r)
        assert r["share_inside_history_range"] > 0.5, (kind, r)
