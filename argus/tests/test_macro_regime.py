"""TDD tests for FRED macro regime integration with scorer."""
import pytest
from argus.collectors.fred import macro_regime_score, macro_prior


# ── macro_regime_score ────────────────────────────────────────────────────────

def _latest(**kwargs):
    """Build latest-macro dict with sensible defaults."""
    defaults = {
        "DFF":      {"value": 4.0},
        "T10Y2Y":   {"value": 0.4},
        "M2SL":     {"value": 22000.0},
        "DTWEXBGS": {"value": 115.0},
    }
    for k, v in kwargs.items():
        defaults[k] = {"value": v}
    return defaults


def test_neutral_regime():
    score = macro_regime_score(_latest())
    assert -0.3 <= score <= 0.3


def test_risk_off_high_rates_inverted_curve():
    score = macro_regime_score(_latest(DFF=6.0, T10Y2Y=-0.5))
    assert score < -0.2


def test_risk_on_low_rates_positive_curve():
    score = macro_regime_score(_latest(DFF=2.0, T10Y2Y=1.0))
    assert score > 0.2


def test_strong_usd_is_bearish():
    score_weak = macro_regime_score(_latest(DTWEXBGS=105.0))
    score_strong = macro_regime_score(_latest(DTWEXBGS=130.0))
    assert score_weak > score_strong


def test_score_clamped():
    score = macro_regime_score(_latest(DFF=0.1, T10Y2Y=2.0, DTWEXBGS=90.0))
    assert -1.0 <= score <= 1.0
    score2 = macro_regime_score(_latest(DFF=9.0, T10Y2Y=-2.0, DTWEXBGS=145.0))
    assert -1.0 <= score2 <= 1.0


def test_missing_series_doesnt_crash():
    score = macro_regime_score({})
    assert -1.0 <= score <= 1.0


# ── macro_prior ───────────────────────────────────────────────────────────────

def test_prior_neutral_returns_base():
    a, b = macro_prior(regime=0.0)
    assert a == pytest.approx(2.0)
    assert b == pytest.approx(2.0)


def test_prior_risk_on_shifts_alpha_up():
    a, b = macro_prior(regime=1.0)
    assert a > 2.0
    assert b < 2.0


def test_prior_risk_off_shifts_beta_up():
    a, b = macro_prior(regime=-1.0)
    assert a < 2.0
    assert b > 2.0


def test_prior_always_positive():
    for r in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        a, b = macro_prior(regime=r)
        assert a > 0
        assert b > 0


def test_prior_symmetric():
    a_pos, b_pos = macro_prior(regime=0.5)
    a_neg, b_neg = macro_prior(regime=-0.5)
    assert a_pos == pytest.approx(b_neg, abs=1e-9)
    assert b_pos == pytest.approx(a_neg, abs=1e-9)
