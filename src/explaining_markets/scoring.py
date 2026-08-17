"""ΔR² scoring and prediction diagnostics.

This is the measurement layer. Nothing in the rulebook or the prompt should be
changed without a number from here first — every revision between Aug 6 and
Aug 12 optimised the shape of the prediction distribution without once measuring
the objective, and the shape improved while the objective did not.

WHAT THE COMPETITION ACTUALLY SCORES
------------------------------------
Submissions are ranked by ΔR²: the explanatory power a submission's predictions
add *over the earnings surprise alone*, on the common set of scored events, with
missing predictions imputed by the submission's own mean.

    R²_base = R² of  realized ~ 1 + surprise
    R²_full = R² of  realized ~ 1 + surprise + prediction
    ΔR²     = R²_full − R²_base

Two properties of this metric drive everything else in this module:

1. **R² is invariant to affine transformation of the prediction.** Adding a
   constant to every prediction, or scaling them all by a factor, changes the
   score by exactly zero — OLS absorbs both. Systematic bias is free. Only the
   *ordering and relative spacing* of predictions can move the score. Any
   proposed change that amounts to "shift everything up/down" or "shrink
   everything toward 0.5" is, provably, worth nothing.

2. **It is NOT invariant to monotone nonlinear transformation.** Re-spacing
   predictions while preserving their order does change R². So calibration is
   worth testing — but see :func:`isotonic_cv_r2`, which tests it honestly
   out-of-sample rather than fitting the answer to the data.

SAMPLE-SIZE HONESTY
-------------------
Early in a quarter these estimates are extremely noisy. :func:`bootstrap_ci`
exists because an observed ΔR² difference of 0.02 on 127 events is not evidence
of anything, and the failure mode this project is most exposed to — documented in
its own notes — is promoting a rule off a sample that was a coin flip. Report the
interval, not just the point estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# Canonical ledger column names. A CSV needs at minimum PREDICTION, REALIZED and
# SURPRISE; everything else enriches the diagnostics and degrades gracefully.
COL_PREDICTION = "predicted_percentile"
COL_REALIZED = "realized_percentile"
COL_SURPRISE = "earnings_surprise_pct"
COL_TICKER = "ticker"
COL_DATE = "event_date"
COL_RULES = "rules_applied"
COL_RETURN_EST = "expected_abnormal_return_pct"
COL_CAR = "car1_pct"
COL_CONFIDENCE = "confidence"

REQUIRED_COLUMNS = (COL_PREDICTION, COL_REALIZED)

# Separator used inside the rules_applied cell of a flat CSV.
RULE_SEPARATOR = ";"


# ---------------------------------------------------------------------------
# Core regression primitives
# ---------------------------------------------------------------------------


def _design_matrix(regressors: list[np.ndarray], n: int) -> np.ndarray:
    """Stack an intercept column in front of the supplied regressors."""
    return np.column_stack([np.ones(n)] + list(regressors))


def ols_r2(y: np.ndarray, *regressors: np.ndarray) -> float:
    """R² of ``y`` regressed on an intercept plus ``regressors``.

    Returns 0.0 when ``y`` has no variance, which is the correct degenerate
    answer: nothing can explain a constant.
    """
    y = np.asarray(y, dtype=float)
    n = y.size
    total_ss = float(((y - y.mean()) ** 2).sum())
    if total_ss == 0.0 or n == 0:
        return 0.0
    if not regressors:
        return 0.0

    design = _design_matrix([np.asarray(r, dtype=float) for r in regressors], n)
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    residual_ss = float(((y - design @ coefficients) ** 2).sum())
    return 1.0 - residual_ss / total_ss


def impute_missing(values: np.ndarray) -> np.ndarray:
    """Fill NaNs with the mean of the observed values, as the leaderboard does.

    A submission that skips events is not rewarded for skipping the hard ones:
    the missing slots are filled with that submission's own mean, which by
    construction adds no explanatory power.
    """
    values = np.asarray(values, dtype=float)
    observed = values[~np.isnan(values)]
    if observed.size == 0:
        return np.zeros_like(values)
    filled = values.copy()
    filled[np.isnan(filled)] = observed.mean()
    return filled


# ---------------------------------------------------------------------------
# The headline metric
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreReport:
    """The leaderboard metric and the pieces it decomposes into."""

    n_events: int
    n_predicted: int
    r2_surprise_only: float
    r2_full: float
    delta_r2: float
    r2_prediction_only: float
    slope: float
    intercept: float
    pearson_r: float
    spearman_rho: float

    @property
    def coverage(self) -> float:
        """Share of scored events for which we actually submitted."""
        return self.n_predicted / self.n_events if self.n_events else 0.0

    def format(self) -> str:
        return "\n".join([
            f"  events scored            {self.n_events}",
            f"  predictions submitted    {self.n_predicted} "
            f"({100 * self.coverage:.0f}%)",
            f"  R² surprise only         {self.r2_surprise_only:.4f}",
            f"  R² surprise + prediction {self.r2_full:.4f}",
            f"  ΔR²                      {self.delta_r2:.4f}   <- ranked on this",
            "",
            f"  R² prediction alone      {self.r2_prediction_only:.4f}",
            f"  OLS slope / intercept    {self.slope:.3f} / {self.intercept:.3f}",
            f"  Pearson r                {self.pearson_r:.3f}",
            f"  Spearman rho             {self.spearman_rho:.3f}",
        ])


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation, computed without a scipy dependency."""
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def score(
    frame: pd.DataFrame,
    *,
    prediction_col: str = COL_PREDICTION,
    realized_col: str = COL_REALIZED,
    surprise_col: str = COL_SURPRISE,
) -> ScoreReport:
    """Compute ΔR² in the competition's form on a frame of scored events.

    Rows missing a realized outcome are dropped — they are not yet scoreable.
    Rows missing a *prediction* are retained and imputed, matching the
    leaderboard. Rows missing a *surprise* are retained with the surprise
    imputed at its own mean, so that events the data vendor failed to cover do
    not silently shrink the sample and flatter the baseline.
    """
    missing = [c for c in (prediction_col, realized_col) if c not in frame.columns]
    if missing:
        raise KeyError(f"ledger is missing required column(s): {missing}")

    scored = frame[frame[realized_col].notna()].copy()
    if scored.empty:
        raise ValueError("no rows with a realized outcome — nothing to score")

    realized = scored[realized_col].to_numpy(dtype=float)
    raw_prediction = scored[prediction_col].to_numpy(dtype=float)
    prediction = impute_missing(raw_prediction)

    if surprise_col in scored.columns:
        surprise = impute_missing(scored[surprise_col].to_numpy(dtype=float))
    else:
        # No surprise column at all: the baseline is an intercept, i.e. zero.
        surprise = np.zeros_like(realized)

    r2_base = ols_r2(realized, surprise)
    r2_full = ols_r2(realized, surprise, prediction)

    design = _design_matrix([prediction], realized.size)
    coefficients, *_ = np.linalg.lstsq(design, realized, rcond=None)

    pearson = (
        float(np.corrcoef(prediction, realized)[0, 1])
        if prediction.std() > 0
        else float("nan")
    )

    return ScoreReport(
        n_events=int(realized.size),
        n_predicted=int((~np.isnan(raw_prediction)).sum()),
        r2_surprise_only=r2_base,
        r2_full=r2_full,
        delta_r2=r2_full - r2_base,
        r2_prediction_only=ols_r2(realized, prediction),
        intercept=float(coefficients[0]),
        slope=float(coefficients[1]),
        pearson_r=pearson,
        spearman_rho=_spearman(prediction, realized),
    )


def bootstrap_ci(
    frame: pd.DataFrame,
    *,
    draws: int = 2000,
    level: float = 0.90,
    seed: int = 0,
    **score_kwargs,
) -> tuple[float, float]:
    """Percentile bootstrap interval for ΔR².

    Use this before claiming a rule change helped. On a hundred-odd events the
    sampling interval on ΔR² is wide enough to swallow most of the differences
    this project has been reasoning about.
    """
    rng = np.random.default_rng(seed)
    n = len(frame)
    estimates = []
    for _ in range(draws):
        sample = frame.iloc[rng.integers(0, n, n)]
        try:
            estimates.append(score(sample, **score_kwargs).delta_r2)
        except (ValueError, np.linalg.LinAlgError):
            continue
    if not estimates:
        return (float("nan"), float("nan"))
    tail = (1.0 - level) / 2.0
    return (
        float(np.quantile(estimates, tail)),
        float(np.quantile(estimates, 1.0 - tail)),
    )


# ---------------------------------------------------------------------------
# Diagnostics — where the signal lives, and where it doesn't
# ---------------------------------------------------------------------------

DEFAULT_BUCKETS = (0.0, 0.15, 0.30, 0.50, 0.70, 0.85, 0.93, 1.0001)


def calibration_table(
    frame: pd.DataFrame,
    *,
    buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    prediction_col: str = COL_PREDICTION,
    realized_col: str = COL_REALIZED,
) -> pd.DataFrame:
    """Mean realized outcome per predicted bucket.

    Read this for *monotonicity*, not for level. A bucket sequence that stops
    rising is a range the model is emitting without discriminating inside it.
    """
    scored = frame[frame[realized_col].notna()].copy()
    scored["bucket"] = pd.cut(
        scored[prediction_col], list(buckets), right=False
    )
    grouped = scored.groupby("bucket", observed=True).agg(
        n=(realized_col, "size"),
        share_of_events=(realized_col, lambda s: len(s)),
        mean_realized=(realized_col, "mean"),
        median_realized=(realized_col, "median"),
    )
    grouped["share_of_events"] = grouped["share_of_events"] / len(scored)
    return grouped


def collapse_test(
    frame: pd.DataFrame,
    *,
    threshold: float,
    above: bool = True,
    **score_kwargs,
) -> dict[str, float]:
    """How much ΔR² is lost by flattening one region to a single value?

    This is the sharpest question available on a small sample. If replacing
    every prediction above 0.85 with the constant 0.85 barely moves ΔR², then
    all the ordering inside that region is noise, and no amount of re-sorting it
    will help — the mass has to leave the region instead.
    """
    prediction_col = score_kwargs.get("prediction_col", COL_PREDICTION)
    baseline = score(frame, **score_kwargs).delta_r2

    flattened = frame.copy()
    values = flattened[prediction_col].to_numpy(dtype=float)
    region = values >= threshold if above else values <= threshold
    values = values.copy()
    values[region] = threshold
    flattened[prediction_col] = values

    collapsed = score(flattened, **score_kwargs).delta_r2
    return {
        "threshold": threshold,
        "n_in_region": int(region.sum()),
        "share_in_region": float(region.mean()),
        "delta_r2": baseline,
        "delta_r2_collapsed": collapsed,
        "information_in_region": baseline - collapsed,
    }


def coarsening_test(
    frame: pd.DataFrame,
    *,
    edges: tuple[float, ...] = (0.15, 0.30, 0.85),
    **score_kwargs,
) -> dict[str, float]:
    """ΔR² of a step function built from the predictions.

    If a handful of buckets beats the continuous prediction, the fine-grained
    values are contributing noise rather than resolution.
    """
    prediction_col = score_kwargs.get("prediction_col", COL_PREDICTION)
    baseline = score(frame, **score_kwargs).delta_r2

    stepped = frame.copy()
    values = stepped[prediction_col].to_numpy(dtype=float)
    levels = np.zeros_like(values)
    for edge in edges:
        levels += (values >= edge).astype(float)
    stepped[prediction_col] = levels

    return {
        "n_levels": len(edges) + 1,
        "delta_r2_continuous": baseline,
        "delta_r2_coarsened": score(stepped, **score_kwargs).delta_r2,
    }


def _pava(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pool-adjacent-violators isotonic fit. Returns (sorted_x, fitted_y)."""
    order = np.argsort(x, kind="mergesort")
    xs, ys = x[order], y[order].astype(float).copy()
    weights = np.ones_like(ys)
    i = 0
    while i < len(ys) - 1:
        if ys[i] <= ys[i + 1]:
            i += 1
            continue
        total_weight = weights[i] + weights[i + 1]
        pooled = (ys[i] * weights[i] + ys[i + 1] * weights[i + 1]) / total_weight
        ys[i] = pooled
        weights[i] = total_weight
        ys = np.delete(ys, i + 1)
        weights = np.delete(weights, i + 1)
        xs_keep = np.ones(len(xs), dtype=bool)
        xs_keep[i + 1] = False
        xs = xs[xs_keep]
        i = max(i - 1, 0)
    return xs, ys


def isotonic_cv_r2(
    frame: pd.DataFrame,
    *,
    folds: int = 5,
    seed: int = 0,
    prediction_col: str = COL_PREDICTION,
    realized_col: str = COL_REALIZED,
) -> dict[str, float]:
    """Out-of-sample R² after a monotone re-spacing of the predictions.

    Fitted in-sample this always looks like a win, which is exactly why it is
    cross-validated here. If the CV number is below the raw number, there is no
    re-spacing to be had and the deficiency is in the ordering itself.
    """
    scored = frame[frame[realized_col].notna()]
    x = scored[prediction_col].to_numpy(dtype=float)
    y = scored[realized_col].to_numpy(dtype=float)
    x = impute_missing(x)

    rng = np.random.default_rng(seed)
    assignment = rng.permutation(np.arange(len(y)) % folds)
    out_of_fold = np.zeros_like(y)

    for fold in range(folds):
        train, test = assignment != fold, assignment == fold
        if train.sum() < 2 or test.sum() == 0:
            out_of_fold[test] = y[train].mean() if train.sum() else y.mean()
            continue
        knots_x, knots_y = _pava(x[train], y[train])
        out_of_fold[test] = np.interp(x[test], knots_x, knots_y)

    return {
        "r2_raw": ols_r2(y, x),
        "r2_isotonic_cv": ols_r2(y, out_of_fold),
    }


def holdout_split(
    frame: pd.DataFrame,
    *,
    date_col: str = COL_DATE,
    train_fraction: float = 0.6,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split chronologically into an early and a late slice.

    Rule changes must be validated on the late slice. Fitting and evaluating on
    the same events is how a coin flip becomes a rule.
    """
    if date_col not in frame.columns:
        raise KeyError(f"no {date_col!r} column to split on")
    ordered = frame.sort_values(date_col, kind="mergesort")
    cut = int(len(ordered) * train_fraction)
    return ordered.iloc[:cut].copy(), ordered.iloc[cut:].copy()


def rule_attribution(
    frame: pd.DataFrame,
    *,
    rules_col: str = COL_RULES,
    prediction_col: str = COL_PREDICTION,
    realized_col: str = COL_REALIZED,
    min_events: int = 5,
    **score_kwargs,
) -> pd.DataFrame:
    """Per-rule behaviour, and ΔR² with each rule's events removed.

    ``delta_r2_without`` is a leave-one-rule-out figure: score the ledger with
    every event on which that rule fired excluded. A rule whose removal *raises*
    ΔR² is costing us score on the events where it fires. This is correlational,
    not causal — rules co-fire — but it is the right place to look first.

    Returns an empty frame when the ledger has no ``rules_applied`` column,
    which is the current state until predict.py starts persisting it.
    """
    if rules_col not in frame.columns:
        return pd.DataFrame(
            columns=[
                "rule_id", "n_events", "share_of_events", "mean_predicted",
                "mean_realized", "mean_abs_error", "within_group_corr",
                "delta_r2_without",
            ]
        )

    scored = frame[frame[realized_col].notna()].copy()
    baseline = score(scored, **score_kwargs).delta_r2

    exploded = (
        scored.assign(
            **{
                rules_col: scored[rules_col]
                .fillna("")
                .astype(str)
                .str.split(RULE_SEPARATOR)
            }
        )
        .explode(rules_col)
    )
    exploded[rules_col] = exploded[rules_col].str.strip()
    exploded = exploded[exploded[rules_col] != ""]

    rows = []
    for rule_id, group in exploded.groupby(rules_col):
        if len(group) < min_events:
            continue
        predicted = group[prediction_col].to_numpy(dtype=float)
        realized = group[realized_col].to_numpy(dtype=float)
        remainder = scored.loc[~scored.index.isin(group.index)]

        try:
            without = score(remainder, **score_kwargs).delta_r2
        except (ValueError, KeyError):
            without = float("nan")

        rows.append({
            "rule_id": rule_id,
            "n_events": len(group),
            "share_of_events": len(group) / len(scored),
            "mean_predicted": float(np.nanmean(predicted)),
            "mean_realized": float(np.nanmean(realized)),
            "mean_abs_error": float(np.nanmean(np.abs(predicted - realized))),
            "within_group_corr": (
                float(np.corrcoef(predicted, realized)[0, 1])
                if len(group) > 2 and np.nanstd(predicted) > 0
                else float("nan")
            ),
            "delta_r2_without": without,
        })

    result = pd.DataFrame(rows)
    if not result.empty:
        result["delta_r2_full_sample"] = baseline
        result = result.sort_values("n_events", ascending=False)
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def load_ledger(path: str | Path) -> pd.DataFrame:
    """Read an outcomes ledger CSV and coerce the numeric columns."""
    frame = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise KeyError(
            f"{path}: ledger is missing required column(s) {missing}. "
            f"Expected at least {list(REQUIRED_COLUMNS)}."
        )
    for column in (
        COL_PREDICTION, COL_REALIZED, COL_SURPRISE, COL_RETURN_EST, COL_CAR
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


@dataclass
class LedgerReport:
    """Everything :func:`full_report` produces, held together for printing."""

    headline: ScoreReport
    ci: tuple[float, float]
    calibration: pd.DataFrame
    collapses: list[dict] = field(default_factory=list)
    coarsening: dict = field(default_factory=dict)
    isotonic: dict = field(default_factory=dict)
    rules: pd.DataFrame = field(default_factory=pd.DataFrame)
    early: ScoreReport | None = None
    late: ScoreReport | None = None


def full_report(
    frame: pd.DataFrame,
    *,
    collapse_thresholds: tuple[float, ...] = (0.70, 0.85),
    bootstrap_draws: int = 2000,
) -> LedgerReport:
    """Run the whole diagnostic battery on a ledger."""
    headline = score(frame)
    ci = bootstrap_ci(frame, draws=bootstrap_draws)

    early = late = None
    if COL_DATE in frame.columns:
        try:
            early_frame, late_frame = holdout_split(frame)
            early, late = score(early_frame), score(late_frame)
        except (ValueError, KeyError, np.linalg.LinAlgError):
            early = late = None

    return LedgerReport(
        headline=headline,
        ci=ci,
        calibration=calibration_table(frame),
        collapses=[
            collapse_test(frame, threshold=t) for t in collapse_thresholds
        ],
        coarsening=coarsening_test(frame),
        isotonic=isotonic_cv_r2(frame),
        rules=rule_attribution(frame),
        early=early,
        late=late,
    )
