"""Known-answer tests for the scoring layer.

The point of these is that a scoring bug is invisible: a metric that is quietly
wrong still prints a plausible number, and the team then steers the rulebook by
it. Every test below has an answer derivable without running the code.
"""

import numpy as np
import pandas as pd
import pytest

from explaining_markets import scoring


def _frame(predicted, realized, surprise=None, **extra):
    data = {
        scoring.COL_PREDICTION: predicted,
        scoring.COL_REALIZED: realized,
    }
    if surprise is not None:
        data[scoring.COL_SURPRISE] = surprise
    data.update(extra)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# ols_r2
# ---------------------------------------------------------------------------


def test_perfect_linear_relationship_is_r2_one():
    y = np.array([0.1, 0.4, 0.6, 0.9])
    assert scoring.ols_r2(y, 2 * y + 7) == pytest.approx(1.0)


def test_constant_regressor_explains_nothing():
    y = np.array([0.1, 0.4, 0.6, 0.9])
    assert scoring.ols_r2(y, np.ones(4)) == pytest.approx(0.0, abs=1e-12)


def test_constant_outcome_returns_zero_not_nan():
    """Nothing can explain a constant; the answer is 0.0, not a crash."""
    assert scoring.ols_r2(np.full(5, 0.5), np.arange(5.0)) == 0.0


def test_r2_equals_squared_correlation_in_the_single_regressor_case():
    rng = np.random.default_rng(1)
    x, noise = rng.normal(size=200), rng.normal(size=200)
    y = 0.5 * x + noise
    assert scoring.ols_r2(y, x) == pytest.approx(np.corrcoef(x, y)[0, 1] ** 2)


# ---------------------------------------------------------------------------
# The affine-invariance property the whole strategy rests on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scale,shift", [(2.0, 0.0), (1.0, 0.3), (0.25, -0.1)])
def test_delta_r2_is_invariant_to_affine_transforms_of_the_prediction(scale, shift):
    """Shifting or scaling every prediction is worth exactly zero.

    This is why 'our predictions are too high on average' is not a bug worth
    fixing, and why uniform shrinkage toward 0.5 cannot help.
    """
    rng = np.random.default_rng(2)
    predicted = rng.uniform(0, 1, 120)
    realized = np.clip(0.6 * predicted + rng.normal(0, 0.2, 120), 0, 1)
    surprise = rng.normal(0, 5, 120)

    base = scoring.score(_frame(predicted, realized, surprise))
    moved = scoring.score(_frame(scale * predicted + shift, realized, surprise))

    assert moved.delta_r2 == pytest.approx(base.delta_r2, abs=1e-10)


def test_delta_r2_is_not_invariant_to_monotone_nonlinear_transforms():
    """...but re-spacing while preserving order does move the score."""
    rng = np.random.default_rng(3)
    predicted = rng.uniform(0, 1, 200)
    realized = np.clip(predicted**3 + rng.normal(0, 0.05, 200), 0, 1)

    linear = scoring.score(_frame(predicted, realized)).delta_r2
    respaced = scoring.score(_frame(predicted**3, realized)).delta_r2
    assert respaced > linear + 0.05


# ---------------------------------------------------------------------------
# Imputation and the baseline
# ---------------------------------------------------------------------------


def test_missing_predictions_are_filled_with_the_submissions_own_mean():
    values = np.array([0.2, np.nan, 0.8])
    assert scoring.impute_missing(values) == pytest.approx([0.2, 0.5, 0.8])


def test_imputed_rows_add_no_explanatory_power():
    """Skipping events must not be a way to raise ΔR²."""
    rng = np.random.default_rng(4)
    predicted = rng.uniform(0, 1, 100)
    realized = np.clip(0.7 * predicted + rng.normal(0, 0.15, 100), 0, 1)

    full = scoring.score(_frame(predicted, realized)).n_predicted
    gapped = predicted.copy()
    gapped[:10] = np.nan
    partial = scoring.score(_frame(gapped, realized))

    assert full == 100
    assert partial.n_predicted == 90
    assert partial.n_events == 100  # the skipped events still count against us


def test_delta_r2_is_zero_when_the_prediction_is_a_relabelled_surprise():
    """A prediction that is just the baseline in disguise adds nothing."""
    rng = np.random.default_rng(5)
    surprise = rng.normal(0, 5, 150)
    realized = np.clip(0.5 + 0.02 * surprise + rng.normal(0, 0.2, 150), 0, 1)
    report = scoring.score(_frame(0.5 + 0.01 * surprise, realized, surprise))
    assert report.delta_r2 == pytest.approx(0.0, abs=1e-9)


def test_rows_without_a_realized_outcome_are_dropped():
    frame = _frame([0.2, 0.4, 0.9], [0.3, np.nan, 0.8])
    assert scoring.score(frame).n_events == 2


def test_missing_required_column_raises_a_named_error():
    with pytest.raises(KeyError, match="realized_percentile"):
        scoring.score(pd.DataFrame({scoring.COL_PREDICTION: [0.5]}))


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_collapse_test_finds_no_information_in_a_flat_region():
    """A region whose ordering is pure noise loses nothing when flattened.

    Averaged over seeds rather than asserted on one draw: on any single sample
    of 60 the noisy ordering shifts ΔR² by a couple of points in either
    direction, and a test that pretends otherwise is the same mistake the
    module exists to prevent.
    """
    losses = []
    for seed in range(20):
        rng = np.random.default_rng(seed)
        lower = np.linspace(0.0, 0.5, 60)
        upper = rng.uniform(0.85, 0.98, 60)  # ordering unrelated to the outcome
        predicted = np.concatenate([lower, upper])
        realized = np.concatenate([lower, rng.uniform(0, 1, 60)])
        losses.append(
            scoring.collapse_test(
                _frame(predicted, realized), threshold=0.85
            )["information_in_region"]
        )

    assert abs(np.mean(losses)) < 0.02
    assert max(abs(loss) for loss in losses) < 0.10


def test_collapse_test_finds_information_in_an_informative_region():
    predicted = np.linspace(0, 1, 120)
    result = scoring.collapse_test(_frame(predicted, predicted), threshold=0.5)
    assert result["information_in_region"] > 0.1


def test_isotonic_cv_does_not_reward_fitting_noise():
    """On pure noise the CV number must not exceed the raw number."""
    rng = np.random.default_rng(7)
    predicted, realized = rng.uniform(0, 1, 150), rng.uniform(0, 1, 150)
    result = scoring.isotonic_cv_r2(_frame(predicted, realized))
    assert result["r2_isotonic_cv"] <= result["r2_raw"] + 0.05


def test_pava_produces_a_nondecreasing_fit():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([1.0, 3.0, 2.0, 5.0, 4.0])
    _, fitted = scoring._pava(x, y)
    assert np.all(np.diff(fitted) >= -1e-12)


def test_calibration_table_recovers_known_bucket_means():
    predicted = np.array([0.05, 0.10, 0.90, 0.95])
    realized = np.array([0.00, 0.20, 0.40, 0.60])
    table = scoring.calibration_table(
        _frame(predicted, realized), buckets=(0.0, 0.5, 1.0001)
    )
    assert table["n"].tolist() == [2, 2]
    assert table["mean_realized"].tolist() == pytest.approx([0.10, 0.50])


def test_holdout_split_is_chronological_and_disjoint():
    frame = _frame(
        np.linspace(0, 1, 10),
        np.linspace(0, 1, 10),
        event_date=[f"2026-08-{d:02d}" for d in range(10, 20)],
    )
    early, late = scoring.holdout_split(frame, train_fraction=0.6)
    assert len(early) == 6 and len(late) == 4
    assert early["event_date"].max() < late["event_date"].min()


def test_rule_attribution_is_empty_without_a_rules_column():
    result = scoring.rule_attribution(_frame([0.2, 0.8], [0.3, 0.7]))
    assert result.empty
    assert "delta_r2_without" in result.columns


def test_rule_attribution_reports_per_rule_behaviour():
    frame = _frame(
        [0.9, 0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1],
        [0.1, 0.2, 0.1, 0.2, 0.1, 0.1, 0.2, 0.1, 0.2, 0.1],
        rules_applied=["BAD-01"] * 5 + ["GOOD-01;BAD-01"] * 5,
    )
    result = scoring.rule_attribution(frame, min_events=5)
    assert set(result["rule_id"]) == {"BAD-01", "GOOD-01"}
    bad = result.loc[result.rule_id == "BAD-01"].iloc[0]
    assert bad["n_events"] == 10
    assert bad["mean_predicted"] == pytest.approx(0.5)


def test_bootstrap_ci_brackets_the_point_estimate():
    rng = np.random.default_rng(8)
    predicted = rng.uniform(0, 1, 150)
    realized = np.clip(0.7 * predicted + rng.normal(0, 0.2, 150), 0, 1)
    frame = _frame(predicted, realized, rng.normal(0, 5, 150))
    low, high = scoring.bootstrap_ci(frame, draws=300, seed=0)
    assert low < scoring.score(frame).delta_r2 < high


# ---------------------------------------------------------------------------
# Regression test against the seeded ledger
# ---------------------------------------------------------------------------


def test_seeded_q3_ledger_reproduces_the_aug13_diagnosis():
    """Pins the numbers the Aug 13 diagnostic was written from.

    If this test starts failing after new events are appended, that is expected —
    update the expected values and note the date. If it fails without the ledger
    changing, the metric changed underneath us.
    """
    ledger = scoring.load_ledger("knowledge/outcomes/scored_2026Q3.csv")
    ledger = ledger[ledger["status"] == "scored"]
    assert len(ledger) == 127

    report = scoring.score(ledger)
    assert report.r2_prediction_only == pytest.approx(0.169, abs=0.002)
    assert report.delta_r2 == pytest.approx(0.161, abs=0.002)
    assert report.slope == pytest.approx(0.362, abs=0.005)

    # The finding: the top bucket is one undifferentiated label.
    collapse = scoring.collapse_test(ledger, threshold=0.85)
    assert collapse["share_in_region"] > 0.5
    assert abs(collapse["information_in_region"]) < 0.005
