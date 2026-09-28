"""Tests for the frequency layer.

Two kinds.  The first checks the integrator against closed forms it must
reproduce - no response at all, and damping alone - so that a disagreement
later is the physics and not the arithmetic.

The second is the acceptance test the whole comparison rests on
(``test_ramp_ffr_does_not_collapse_onto_the_closed_form``).  ``f0 dP / 2E`` is
initial RoCoF, not a predictor of it; the comparison is only meaningful if the
measured 500 ms outcome is *not* just the closed form rescaled.  That test is
written from what "collapsed" means for the metrics compare.py reports -
Spearman and ROC AUC are rank statistics, and a ratio that barely varies is a
rescaling - and **it is not to be adjusted until it passes.**  If it fails,
the comparison is circular under the parameters in use, and the answer is to
report that, not to move the threshold.
"""

import os

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

import frequency as m
import inertia

HERE = os.path.dirname(os.path.abspath(__file__))


def _none(**kw):
    """Parameters with every response switched off."""
    base = dict(ffr_fraction=0.0, damping_pct_per_hz=0.0)
    base.update(kw)
    return m.Parameters(**base)


# --------------------------------------------------------------------------- #
# The integrator against closed forms
# --------------------------------------------------------------------------- #

def test_no_response_reproduces_the_swing_equation_exactly():
    """With nothing responding, RoCoF is constant and equals f0 dP / 2E."""
    e, dp = np.array([23_000.0, 40_000.0]), np.array([500.0, 300.0])
    out = m.simulate(e, dp, np.full(2, 5000.0), np.zeros(2), np.zeros(2),
                     _none())
    analytic = inertia.initial_rocof(dp, e)
    assert np.allclose(out["rocof_500ms_hz_s"], analytic, rtol=1e-9)
    assert np.allclose(out["nadir_hz"], 50.0 - analytic * m.T_END_S,
                       rtol=1e-9)


def test_damping_alone_matches_the_exponential_solution():
    """df(t) = -(dP / D) (1 - exp(-t D f0 / 2E)) for pure load damping."""
    e, dp, load = 23_000.0, 500.0, 5000.0
    p = _none(damping_pct_per_hz=1.5)
    out = m.simulate([e], [dp], [load], [0.0], [0.0], p, keep=True)
    d = 0.015 * load
    tau = 2 * e / (m.inertia.F0 * d)
    t = out["time_s"]
    exact = 50.0 - dp / d * (1 - np.exp(-t / tau))
    assert np.max(np.abs(out["trajectory_hz"][0] - exact)) < 1e-6
    rocof = (exact[0] - exact[500]) / 0.5
    assert out["rocof_500ms_hz_s"][0] == pytest.approx(rocof, rel=1e-6)


def test_timestep_is_converged():
    args = ([30_000.0], [480.0], [5000.0], [360.0], [480.0])
    a = m.simulate(*args, m.Parameters())
    b = m.simulate(*args, m.Parameters(dt_s=0.0005))
    assert a["rocof_500ms_hz_s"][0] == pytest.approx(b["rocof_500ms_hz_s"][0],
                                                     abs=1e-4)
    assert a["nadir_hz"][0] == pytest.approx(b["nadir_hz"][0], abs=1e-4)


def test_vectorised_equals_one_at_a_time():
    rng = np.random.default_rng(0)
    e = rng.uniform(15e3, 60e3, 8)
    dp = rng.uniform(200, 500, 8)
    load = rng.uniform(3500, 7300, 8)
    por = rng.uniform(250, 500, 8)
    sor = por * 1.4
    batch = m.simulate(e, dp, load, por, sor)
    for k in range(8):
        one = m.simulate(e[k:k + 1], dp[k:k + 1], load[k:k + 1],
                         por[k:k + 1], sor[k:k + 1])
        assert one["rocof_500ms_hz_s"][0] == pytest.approx(
            batch["rocof_500ms_hz_s"][k])
        assert one["nadir_hz"][0] == pytest.approx(batch["nadir_hz"][k])


# --------------------------------------------------------------------------- #
# The response model
# --------------------------------------------------------------------------- #

def test_ramp_starts_from_the_full_imbalance_and_instant_does_not():
    """At 0+ a ramping FFR has delivered nothing; an instant one, all of it."""
    args = ([23_000.0], [500.0], [5000.0], [300.0], [400.0])
    ramp = m.simulate(*args, m.Parameters(ffr_mode="ramp"))
    inst = m.simulate(*args, m.Parameters(ffr_mode="instant"))
    assert ramp["rocof_initial_model_hz_s"][0] == pytest.approx(
        ramp["rocof_analytic_hz_s"][0])
    assert inst["rocof_initial_model_hz_s"][0] == pytest.approx(
        inst["rocof_analytic_net_ffr_hz_s"][0])


def test_instant_mode_is_exact_at_0_plus():
    """The degenerate control: shrink the window and the net form is exact."""
    p = m.Parameters(ffr_mode="instant", rocof_window_s=0.002)
    out = m.simulate([23_000.0], [500.0], [5000.0], [300.0], [400.0], p)
    net = out["rocof_analytic_net_ffr_hz_s"][0]
    first = out["rocof_initial_model_hz_s"][0]
    assert first == pytest.approx(net, rel=1e-12)


def test_reserve_does_not_overshoot_fifty_hertz():
    """Droop-limited reserve cannot push frequency above nominal."""
    rng = np.random.default_rng(1)
    n = 16
    out = m.simulate(rng.uniform(15e3, 60e3, n), rng.uniform(200, 500, n),
                     rng.uniform(3500, 7300, n), rng.uniform(300, 800, n),
                     rng.uniform(400, 1000, n), keep=True)
    assert out["trajectory_hz"].max() <= 50.0 + 1e-9


def test_reserve_timings_follow_the_service_definitions():
    p = m.Parameters()
    assert m.ffr_fraction(0.0, p) == 0.0
    assert m.ffr_fraction(p.ffr_full_activation_s, p) == pytest.approx(1.0)
    assert m.ffr_fraction(p.ffr_sustain_s, p) == pytest.approx(1.0)
    assert m.ffr_fraction(p.ffr_sustain_s + p.ffr_release_s, p) == 0.0
    v = np.array([100.0])
    assert m.reserve_available(p.por_full_s, v, 2 * v, p)[0] == \
        pytest.approx(100.0)
    assert m.reserve_available(p.por_hold_s, v, 2 * v, p)[0] == \
        pytest.approx(200.0)


def test_violation_flags_follow_the_thresholds():
    out = m.simulate([12_000.0, 60_000.0], [500.0, 200.0], [3500.0, 7000.0],
                     [100.0, 600.0], [150.0, 800.0])
    for k in range(2):
        assert out["rocof_violation"][k] == (out["rocof_500ms_hz_s"][k]
                                             > m.ROCOF_LIMIT_HZ_S)
        assert out["nadir_violation"][k] == (out["nadir_hz"][k]
                                             < m.NADIR_LIMIT_HZ)


def test_multi_mass_is_a_documented_hook_not_an_implementation():
    with pytest.raises(NotImplementedError):
        m.multi_mass(0, pd.DataFrame(), None)
    assert "COI" in m.multi_mass.__doc__


# --------------------------------------------------------------------------- #
# The acceptance test: is the comparison circular?
# --------------------------------------------------------------------------- #

#: Rank agreement at or above which a measured outcome is, for Spearman and
#: ROC AUC - both rank statistics - indistinguishable from the closed form.
COLLAPSE_SPEARMAN = 0.99
#: Spread of measured / closed-form below which the "gap" is a rescaling:
#: R^2 is invariant to it, and so is every rank metric.
COLLAPSE_CV = 0.05


def _collapsed(measured, closed_form) -> dict:
    ratio = np.asarray(measured) / np.asarray(closed_form)
    rho = spearmanr(measured, closed_form).statistic
    cv = float(np.std(ratio) / np.mean(ratio))
    return {"spearman": float(rho), "ratio_mean": float(np.mean(ratio)),
            "ratio_cv": cv,
            "collapsed": bool(rho >= COLLAPSE_SPEARMAN and cv < COLLAPSE_CV)}


@pytest.fixture(scope="module")
def scenarios():
    import ensemble

    directory = os.environ.get("ENSEMBLE_DIR", os.path.join(
        HERE, ensemble.ENSEMBLE_DIR,
        f"{ensemble.DEFAULT_VINTAGE}_seed{ensemble.SEED}"
        f"_n{ensemble.DEFAULT_N}"))
    s = ensemble.load(directory)["scenarios"] if os.path.isdir(directory) \
        else pd.DataFrame()
    if len(s) < 20:
        pytest.skip("no solved ensemble: run `python ensemble.py run` first")
    return s


def test_instant_ffr_converges_on_the_closed_form(scenarios):
    """With instant FFR the measured value is the net closed form, collapsed.

    ``f0 (dP - FFR) / 2E_post`` is exact at 0+ in this mode; the 500 ms
    measurement over the ensemble should be that number, rank for rank and
    to within a small, near-constant ratio.
    """
    out = m.evaluate(scenarios, m.Parameters(ffr_mode="instant"))
    got = _collapsed(out["rocof_500ms_hz_s"],
                     out["rocof_analytic_net_ffr_hz_s"])
    assert got["collapsed"], got
    assert abs(got["ratio_mean"] - 1.0) < 0.10, got


def test_ramp_ffr_does_not_collapse_onto_the_closed_form(scenarios):
    """**The proof that the comparison is not circular.  Do not adjust.**

    With the default FFR ramp, the measured 500 ms RoCoF must not be a
    rank-preserving rescaling of ``f0 dP / 2E_post``.  If it is, every
    continuous and binary metric compare.py would report for dP/H_COI
    against RoCoF_500ms is the closed form's own, and the comparison with
    SNSP is a comparison with a number that was always going to win.
    """
    out = m.evaluate(scenarios, m.Parameters(ffr_mode="ramp"))
    got = _collapsed(out["rocof_500ms_hz_s"], out["rocof_analytic_hz_s"])
    assert not got["collapsed"], got
