"""Tests for the universe dossier builder.

The network calls can't run in CI, so everything here exercises the logic
against synthetic data. The point is that when the long scrape does run, the
maths and the output schema are already known-good — a bug found at hour three
of a six-hour run is expensive.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import build_dossiers as bd  # noqa: E402


def _sessions(n=40, start="2026-01-02"):
    return pd.DatetimeIndex(pd.bdate_range(start=start, periods=n))


def _prices(index, start=100.0, step=0.0):
    return pd.Series([start + step * i for i in range(len(index))], index=index)


# ---------------------------------------------------------------------------
# Timing classification — decides WHICH day's return the announcement moves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2026-03-04 07:30:00-05:00", "before_market_open"),
        ("2026-03-04 09:30:00-05:00", "before_market_open"),
        ("2026-03-04 16:05:00-05:00", "after_market_close"),
        ("2026-03-04 21:00:00-05:00", "after_market_close"),
        ("2026-03-04 12:00:00-05:00", "unknown"),   # mid-session: unusable
        ("2026-03-04 00:00:00-05:00", "unknown"),   # midnight = no time given
        (None, "unknown"),
    ],
)
def test_earnings_timing_classification(stamp, expected):
    assert bd.classify_earnings_time(stamp) == expected


def test_before_open_reacts_same_day_after_close_reacts_next_day():
    sessions = _sessions()
    day = sessions[10]
    assert bd.reaction_session(day, "before_market_open", sessions) == day
    assert bd.reaction_session(day, "after_market_close", sessions) == sessions[11]


def test_reaction_session_returns_none_past_the_end_of_history():
    sessions = _sessions(5)
    assert bd.reaction_session(sessions[-1], "after_market_close", sessions) is None


def test_announcement_on_a_non_trading_day_rolls_to_the_next_session():
    sessions = _sessions()
    saturday = pd.Timestamp("2026-01-10")
    got = bd.reaction_session(saturday, "before_market_open", sessions)
    assert got is not None and got > saturday


# ---------------------------------------------------------------------------
# The abnormal return — this is what the competition actually scores
# ---------------------------------------------------------------------------


def test_abnormal_return_is_stock_minus_market():
    sessions = _sessions(10)
    stock = _prices(sessions, 100.0)
    market = _prices(sessions, 50.0)
    # engineer a known move on the reaction day
    stock.iloc[5] = stock.iloc[4] * 1.10      # +10%
    market.iloc[5] = market.iloc[4] * 1.02    # +2%

    earnings = pd.DataFrame([{
        "ticker": "TEST", "fiscal_quarter": None,
        "announcement_date": sessions[4],
        "timing": "after_market_close",
        "earnings_surprise_pct": 5.0, "surprise_source": "test",
    }])
    dossier = bd.build_dossier("TEST", stock, market, earnings)
    reaction = dossier["prior_reactions"][0]

    assert reaction["stock_return_pct"] == pytest.approx(10.0, abs=1e-6)
    assert reaction["vti_return_pct"] == pytest.approx(2.0, abs=1e-6)
    assert reaction["abnormal_return_pct"] == pytest.approx(8.0, abs=1e-6)


def test_missing_price_on_the_reaction_day_yields_nulls_not_garbage():
    sessions = _sessions(10)
    stock = _prices(sessions)
    stock.iloc[5] = np.nan
    earnings = pd.DataFrame([{
        "ticker": "TEST", "fiscal_quarter": None,
        "announcement_date": sessions[4], "timing": "after_market_close",
        "earnings_surprise_pct": None, "surprise_source": None,
    }])
    reaction = bd.build_dossier(
        "TEST", stock, _prices(sessions, 50.0), earnings
    )["prior_reactions"][0]
    assert reaction["abnormal_return_pct"] is None
    assert reaction["stock_return_pct"] is None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_reaction_statistics_split_beats_from_misses():
    reactions = [
        {"abnormal_return_pct": 10.0, "earnings_surprise_pct": 5.0},
        {"abnormal_return_pct": -4.0, "earnings_surprise_pct": 2.0},
        {"abnormal_return_pct": -8.0, "earnings_surprise_pct": -3.0},
        {"abnormal_return_pct": 2.0, "earnings_surprise_pct": None},
    ]
    stats = bd.reaction_statistics(reactions)
    assert stats["observations"] == 4
    assert stats["beat_observations"] == 2
    assert stats["miss_observations"] == 1
    assert stats["median_reaction_after_beat_pct"] == pytest.approx(3.0)
    assert stats["median_reaction_after_miss_pct"] == pytest.approx(-8.0)
    assert stats["positive_reaction_rate"] == pytest.approx(0.5)
    assert stats["median_absolute_reaction_pct"] == pytest.approx(6.0)


def test_statistics_on_an_empty_history_are_null_not_nan():
    stats = bd.reaction_statistics([])
    assert stats["observations"] == 0
    assert stats["median_abnormal_return_pct"] is None
    assert yaml.safe_dump(stats)  # must remain YAML-serialisable


# ---------------------------------------------------------------------------
# Output schema compatibility — the thing that breaks the live agent if wrong
# ---------------------------------------------------------------------------


def test_output_matches_what_the_live_loader_expects(tmp_path, monkeypatch):
    """A built dossier must satisfy prompt_construction.is_valid_dossier."""
    import prompt_construction as pc

    sessions = _sessions(10)
    stock = _prices(sessions, 100.0)
    stock.iloc[5] = stock.iloc[4] * 1.05
    earnings = pd.DataFrame([{
        "ticker": "HOLX", "fiscal_quarter": None,
        "announcement_date": sessions[4], "timing": "after_market_close",
        "earnings_surprise_pct": 1.0, "surprise_source": bd.SURPRISE_SOURCE,
    }])
    dossier = bd.build_dossier("HOLX", stock, _prices(sessions, 50.0), earnings)

    path = tmp_path / "HOLX.yaml"
    path.write_text(yaml.safe_dump(dossier, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(pc, "DOSSIER_PATH", tmp_path)

    text = pc.get_dossier("HOLX")
    assert text is not None
    assert pc.is_valid_dossier(text)
    assert "surprise_source" not in text   # filtered on the way into the prompt
    assert "fiscal_quarter" not in text


def test_forward_estimates_survive_the_prompt_filter(tmp_path, monkeypatch):
    """The new block must actually reach the model, not get filtered away."""
    import prompt_construction as pc

    path = tmp_path / "ZZZZ.yaml"
    path.write_text(yaml.safe_dump({
        "ticker": "ZZZZ",
        "prior_reactions": [{"abnormal_return_pct": 1.0}],
        "reaction_statistics": {"observations": 1},
        "forward_estimates": {
            "as_of": "2026-08-15",
            "current_quarter": {"eps_avg": 0.31, "analysts": 12},
        },
    }, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(pc, "DOSSIER_PATH", tmp_path)

    # A cutoff after the as_of stamp is required — the block is gated on
    # knowledge-cutoff compliance, not merely on being present on disk.
    text = pc.get_dossier("ZZZZ", knowledge_cutoff="2026-09-19T20:00:00Z")
    assert "forward_estimates" in text
    assert "eps_avg" in text
    assert "as_of" in text, "the as-of stamp is the cutoff audit trail"

    # ...and withheld when the cutoff has already passed.
    blocked = pc.get_dossier("ZZZZ", knowledge_cutoff="2026-08-14T20:00:00Z")
    assert "forward_estimates" not in blocked


# ---------------------------------------------------------------------------
# Resumability — a six-hour run must survive being interrupted
# ---------------------------------------------------------------------------


def _write(path: Path, payload: dict):
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_a_complete_dossier_is_skipped(tmp_path):
    path = tmp_path / "AAA.yaml"
    _write(path, {"ticker": "AAA", "reaction_statistics": {"observations": 4}})
    assert bd.dossier_needs_work(path, want_estimates=False) is False


def test_a_dossier_without_estimates_is_rebuilt_when_estimates_are_wanted(tmp_path):
    path = tmp_path / "AAA.yaml"
    _write(path, {"ticker": "AAA", "reaction_statistics": {"observations": 4}})
    assert bd.dossier_needs_work(path, want_estimates=True) is True
    _write(path, {"ticker": "AAA", "reaction_statistics": {"observations": 4},
                  "forward_estimates": {"as_of": "2026-08-15"}})
    assert bd.dossier_needs_work(path, want_estimates=True) is False


@pytest.mark.parametrize("payload", [
    {"ticker": "AAA", "reaction_statistics": {"observations": 0}},
    {"ticker": "AAA"},
    "not a mapping",
])
def test_unusable_dossiers_are_rebuilt(tmp_path, payload):
    path = tmp_path / "AAA.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert bd.dossier_needs_work(path, want_estimates=False) is True


def test_missing_and_corrupt_files_are_rebuilt(tmp_path):
    assert bd.dossier_needs_work(tmp_path / "NOPE.yaml", False) is True
    bad = tmp_path / "BAD.yaml"
    bad.write_text("{[not: valid: yaml", encoding="utf-8")
    assert bd.dossier_needs_work(bad, False) is True


# ---------------------------------------------------------------------------
# Universe filtering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol,keep", [
    ("AAPL", True), ("BRK.B", True), ("ACHR", True), ("F", True),
    ("ABCDW", False),   # warrant
    ("ABCDR", False),   # right
    ("ABCDU", False),   # unit
    ("ABCDP", False),   # preferred
    ("TOOLONGSYM", False),
    ("", False), ("$BAD", False),
])
def test_non_equity_instruments_are_excluded(symbol, keep):
    assert bd._is_plausible_equity(symbol) is keep


def test_five_letter_ordinary_symbols_are_kept():
    """Guard against over-filtering: not every 5-letter symbol is a warrant."""
    for symbol in ("GOOGL", "CSCOA", "ZYXWV"):
        assert bd._is_plausible_equity(symbol) is True


# ---------------------------------------------------------------------------
# Scalar coercion — YAML must never receive numpy types or NaN
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (np.float64(1.23456789), 1.2346),
    (np.int64(7), 7),
    (float("nan"), None),
    (None, None),
    (pd.Timestamp("2026-08-13"), "2026-08-13"),
    ("text", "text"),
])
def test_scalar_coercion(value, expected):
    assert bd.scalar(value) == expected


def test_built_dossier_is_pure_yaml_safe_types():
    sessions = _sessions(10)
    stock = _prices(sessions, 100.0)
    stock.iloc[5] = stock.iloc[4] * 1.03
    earnings = pd.DataFrame([{
        "ticker": "T", "fiscal_quarter": None,
        "announcement_date": sessions[4], "timing": "after_market_close",
        "earnings_surprise_pct": np.float64(2.5),
        "surprise_source": bd.SURPRISE_SOURCE,
    }])
    dossier = bd.build_dossier("T", stock, _prices(sessions, 50.0), earnings)
    # safe_dump raises on numpy scalars; round-tripping proves the types are clean
    assert yaml.safe_load(yaml.safe_dump(dossier)) == dossier


def test_unsafe_tickers_are_rejected():
    for bad in ("../etc/passwd", "a/b", "", "  "):
        with pytest.raises(ValueError):
            bd.canonical_ticker(bad)
