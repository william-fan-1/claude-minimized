"""Score an outcomes ledger and print the ΔR² diagnostic report.

    uv run python score_ledger.py
    uv run python score_ledger.py --ledger knowledge/outcomes/scored_2026Q3.csv
    uv run python score_ledger.py --include-missing-data --no-bootstrap

Reads the flat CSV written from the submission dashboard's per-prediction export
and reports the number the competition ranks on, plus the diagnostics that say
where the score is coming from. Run this before and after any rulebook change.

Ledger schema — required:
    predicted_percentile   what we submitted, [0, 1]
    realized_percentile    the scored outcome, [0, 1]

Strongly recommended:
    earnings_surprise_pct  the baseline regressor; without it ΔR² collapses to R²
    event_date             ISO date, enables the chronological held-out split
    status                 'scored' or 'missing_data'

Optional, and each one unlocks a section of the report:
    rules_applied                  ';'-separated rule IDs  -> per-rule attribution
    expected_abnormal_return_pct   the model's return estimate before conversion
    ticker, car1_pct, confidence, prompt_version
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from explaining_markets import scoring


def _print_score(title: str, report: scoring.ScoreReport) -> None:
    print(f"\n{title}")
    print(report.format())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ΔR² report for an Explaining Markets outcomes ledger."
    )
    parser.add_argument(
        "--ledger",
        default="knowledge/outcomes/scored_2026Q3.csv",
        help="path to the ledger CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--include-missing-data",
        action="store_true",
        help=(
            "keep rows the platform marked 'missing_data'. They have a realized "
            "outcome but no earnings surprise, so they flatter the baseline."
        ),
    )
    parser.add_argument(
        "--bootstrap-draws",
        type=int,
        default=2000,
        help="bootstrap resamples for the ΔR² interval (0 to skip)",
    )
    args = parser.parse_args(argv)

    try:
        ledger = scoring.load_ledger(args.ledger)
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if "status" in ledger.columns and not args.include_missing_data:
        before = len(ledger)
        ledger = ledger[ledger["status"] == "scored"]
        dropped = before - len(ledger)
        if dropped:
            print(
                f"note: dropped {dropped} row(s) not marked 'scored' "
                "(pass --include-missing-data to keep them)"
            )

    report = scoring.full_report(ledger, bootstrap_draws=args.bootstrap_draws)

    print("=" * 68)
    print(f"ΔR² REPORT — {args.ledger}")
    print("=" * 68)
    _print_score("HEADLINE", report.headline)
    if args.bootstrap_draws:
        low, high = report.ci
        print(f"  ΔR² 90% bootstrap CI     [{low:.3f}, {high:.3f}]")
        print(
            "  ^ if a rule change moves ΔR² by less than this width, "
            "it has not been shown to work."
        )

    print("\nCALIBRATION — read for monotonicity, not level")
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(report.calibration.to_string())

    print("\nWHERE THE SIGNAL LIVES")
    for collapse in report.collapses:
        print(
            f"  flatten predictions >= {collapse['threshold']:.2f} "
            f"({collapse['n_in_region']} events, "
            f"{100 * collapse['share_in_region']:.0f}% of sample) "
            f"-> ΔR² {collapse['delta_r2_collapsed']:.4f} "
            f"(loses {collapse['information_in_region']:.4f})"
        )
    print(
        f"  {report.coarsening['n_levels']}-level step function "
        f"-> ΔR² {report.coarsening['delta_r2_coarsened']:.4f} "
        f"vs continuous {report.coarsening['delta_r2_continuous']:.4f}"
    )
    print(
        f"  monotone re-spacing (isotonic, 5-fold CV) "
        f"-> R² {report.isotonic['r2_isotonic_cv']:.4f} "
        f"vs raw {report.isotonic['r2_raw']:.4f}"
    )

    if report.early is not None and report.late is not None:
        _print_score("EARLY SLICE (fit rules here)", report.early)
        _print_score("LATE SLICE (validate here)", report.late)

    if report.rules.empty:
        print(
            "\nRULE ATTRIBUTION\n"
            "  unavailable — the ledger has no populated 'rules_applied' column.\n"
            "  predict.py returns rules_applied per prediction; persist it into\n"
            "  the ledger to switch this section on."
        )
    else:
        print("\nRULE ATTRIBUTION — leave-one-rule-out")
        with pd.option_context(
            "display.float_format", "{:.3f}".format, "display.width", 200
        ):
            print(report.rules.to_string(index=False))
        print(
            "  a rule whose 'delta_r2_without' EXCEEDS the full-sample ΔR² is "
            "costing score on the events where it fires."
        )

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
