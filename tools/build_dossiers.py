"""Build the ticker dossier for the whole US-listed universe, once.

    # ALWAYS do this first — 20 tickers, ~1 minute, prints what it found
    uv run python tools/build_dossiers.py --limit 20 --verbose

    # then the real run (hours; resumable, safe to Ctrl-C and restart)
    uv run python tools/build_dossiers.py

WHY THIS EXISTS
---------------
`notebooks/create_dossier.ipynb` builds dossiers for whatever tickers happen to
be in `industry_map.csv`, which is derived from a 14-day slice of the events
calendar. That slice expires, and when it does every event past it silently
loses its dossier. This builds for the entire listed universe instead, so
coverage stops being something anyone has to manage.

The reaction logic is a faithful port of the notebook's — same fields, same
rounding, same timing classification — so output is byte-compatible with what
`prompt_construction.get_dossier()` and `is_valid_dossier()` already expect.

KNOWLEDGE-CUTOFF COMPLIANCE — READ THIS BEFORE RE-RUNNING
---------------------------------------------------------
Prior reactions are historical and always pre-cutoff, so building them is safe
at any time.

**Forward estimates are not.** yfinance returns estimates as of *now*, with no
as-of date of its own. Building them today for an event weeks away uses less
information than the rules permit, which is fine. But re-running this script
between an event's `knowledge_cutoff` and the event itself would write
post-cutoff estimates into a dossier that is about to be used for a live
prediction. That is a rules violation and prize eligibility requires a code
audit.

Every dossier is therefore stamped with `forward_estimates.as_of`. The rule is:

    build once, well before the events you intend to use it for, and do not
    re-run with --estimates inside a live prediction window.

`--no-estimates` is always safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = Path(__file__).resolve().parent.parent
DOSSIER_DIR = REPO_ROOT / "knowledge" / "dossier"
STATE_DIR = REPO_ROOT / "knowledge" / "dossier_build"
SURPRISE_SOURCE = "Yahoo Finance (via yfinance)"
ESTIMATE_SOURCE = "Yahoo Finance (via yfinance)"
MARKET_PROXY = "VTI"

# The competition scores stock return net of VTI, so VTI is the benchmark.
# Fetched once and reused for every ticker.
NASDAQ_TRADED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"

# Suffixes and classes that are not ordinary common stock. Kept deliberately
# short: the user asked for no liquidity floor, so we exclude only instruments
# that cannot have an earnings event at all.
NON_EQUITY_SUFFIXES = ("W", "R", "U", "P")


# ---------------------------------------------------------------------------
# Small helpers, ported verbatim in behaviour from create_dossier.ipynb
# ---------------------------------------------------------------------------


def canonical_ticker(value: Any) -> str:
    ticker = str(value).strip().upper()
    if not ticker or ticker == "NAN":
        raise ValueError("Ticker cannot be empty")
    if any(ch in ticker for ch in ("/", "\\")) or ticker in {".", ".."}:
        raise ValueError(f"Unsafe ticker identifier: {ticker!r}")
    return ticker


def scalar(value: Any, digits: int = 4):
    """Coerce to a plain YAML-safe scalar, rounding floats."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return round(float(value), digits)
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    return value


def empty_prices() -> pd.Series:
    return pd.Series(dtype=float, index=pd.DatetimeIndex([]))


def classify_earnings_time(timestamp: Any) -> str:
    if timestamp is None or pd.isna(timestamp):
        return "unknown"
    try:
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("America/New_York")
        minutes = ts.hour * 60 + ts.minute
    except (TypeError, ValueError):
        return "unknown"
    if minutes == 0:
        return "unknown"
    if minutes <= 9 * 60 + 30:
        return "before_market_open"
    if minutes >= 16 * 60:
        return "after_market_close"
    return "unknown"


def reaction_session(announcement_date: Any, timing: str, sessions: pd.DatetimeIndex):
    """The trading session whose return the announcement moves.

    Before the open, the move lands the same day; after the close, the next day.
    """
    if timing == "unknown" or pd.isna(announcement_date) or sessions.empty:
        return None
    day = pd.Timestamp(announcement_date).normalize()
    side = "left" if timing == "before_market_open" else "right"
    position = sessions.searchsorted(day, side=side)
    return sessions[position] if position < len(sessions) else None


def reaction_statistics(reactions: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in reactions if r.get("abnormal_return_pct") is not None]
    values = np.array([r["abnormal_return_pct"] for r in usable], dtype=float)
    beats = np.array(
        [r["abnormal_return_pct"] for r in usable
         if r.get("earnings_surprise_pct") is not None
         and r["earnings_surprise_pct"] > 0],
        dtype=float,
    )
    misses = np.array(
        [r["abnormal_return_pct"] for r in usable
         if r.get("earnings_surprise_pct") is not None
         and r["earnings_surprise_pct"] < 0],
        dtype=float,
    )

    def stat(array: np.ndarray, fn):
        return round(float(fn(array)), 4) if array.size else None

    return {
        "observations": int(values.size),
        "median_abnormal_return_pct": stat(values, np.median),
        "mean_abnormal_return_pct": stat(values, np.mean),
        "positive_reaction_rate": stat(values, lambda x: np.mean(x > 0)),
        "median_absolute_reaction_pct": stat(values, lambda x: np.median(np.abs(x))),
        "beat_observations": int(beats.size),
        "median_reaction_after_beat_pct": stat(beats, np.median),
        "miss_observations": int(misses.size),
        "median_reaction_after_miss_pct": stat(misses, np.median),
    }


def call_with_retries(
    call: Callable[[], Any],
    label: str,
    attempts: int = 4,
    delay_seconds: float = 3.0,
    verbose: bool = False,
):
    """Retry with linear backoff. Yahoo rate-limits hard on a run this size."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if attempt == attempts:
                raise
            wait = delay_seconds * attempt
            if verbose:
                print(f"    {label} attempt {attempt}/{attempts} failed "
                      f"({type(exc).__name__}); retrying in {wait:.0f}s")
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def fetch_adjusted_prices(symbol: str, period: str = "10y") -> pd.Series:
    import yfinance as yf

    try:
        instrument = yf.Ticker(symbol)
        frame = instrument.history(
            period=period, interval="1d",
            auto_adjust=False, actions=False, repair=False,
        )
        column = "Adj Close"
        if frame is None or frame.empty or column not in frame.columns:
            frame = instrument.history(
                period=period, interval="1d",
                auto_adjust=True, actions=False, repair=False,
            )
            column = "Close"
        if frame is None or frame.empty or column not in frame.columns:
            return empty_prices()
        index = (
            pd.to_datetime(frame.index, errors="coerce", utc=True)
            .tz_convert(None)
            .normalize()
        )
        prices = pd.Series(
            pd.to_numeric(frame[column], errors="coerce").to_numpy(), index=index
        )
        prices = prices[~prices.index.isna() & prices.notna()]
        return prices.groupby(level=0).last().sort_index().astype(float)
    except Exception:
        return empty_prices()


def fetch_earnings_events(symbol: str, limit: int = 8) -> pd.DataFrame:
    import yfinance as yf

    columns = [
        "ticker", "fiscal_quarter", "announcement_date",
        "timing", "earnings_surprise_pct", "surprise_source",
    ]
    try:
        limit = max(1, min(int(limit), 100))
        raw = yf.Ticker(symbol).get_earnings_dates(limit=limit)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=columns)
        surprise_column = next(
            (c for c in ("Surprise(%)", "Surprise (%)", "surprisePercent")
             if c in raw.columns),
            None,
        )
        today = pd.Timestamp.now(tz="America/New_York").date()
        rows = []
        for position, timestamp in enumerate(raw.index):
            ts = pd.Timestamp(timestamp)
            local = ts.tz_convert("America/New_York") if ts.tzinfo else ts
            if local.date() > today:
                continue  # future/scheduled events have no reaction yet
            row = raw.iloc[position]
            surprise = (
                pd.to_numeric(row.get(surprise_column), errors="coerce")
                if surprise_column else np.nan
            )
            rows.append({
                "ticker": symbol,
                "fiscal_quarter": None,
                "announcement_date": local.normalize().tz_localize(None),
                "timing": classify_earnings_time(ts),
                "earnings_surprise_pct": scalar(surprise),
                "surprise_source": SURPRISE_SOURCE if pd.notna(surprise) else None,
            })
        events = pd.DataFrame(rows, columns=columns)
        return (
            events.sort_values("announcement_date", ascending=False)
            .head(limit)
            .sort_values("announcement_date")
        )
    except Exception:
        return pd.DataFrame(columns=columns)


def _estimate_row(frame: Any, period_key: str) -> dict | None:
    """Pull one period's row out of a yfinance estimate frame, defensively.

    yfinance's estimate accessors have changed shape across versions, so every
    field is optional and a miss returns None rather than raising.
    """
    if frame is None or not hasattr(frame, "empty") or frame.empty:
        return None
    try:
        if period_key not in frame.index:
            return None
        row = frame.loc[period_key]
    except Exception:
        return None

    def pick(*names):
        for name in names:
            try:
                if name in row.index:
                    return scalar(row[name])
            except Exception:
                continue
        return None

    return {
        "eps_avg": pick("avg", "epsAvg"),
        "eps_low": pick("low", "epsLow"),
        "eps_high": pick("high", "epsHigh"),
        "eps_year_ago": pick("yearAgoEps", "yearAgoEPS"),
        "analysts": pick("numberOfAnalysts", "numAnalysts"),
        "growth": pick("growth"),
    }


def fetch_forward_estimates(symbol: str) -> dict | None:
    """Consensus estimates as of now. See the cutoff warning in the docstring.

    This is the baseline roughly half the rulebook asks the model to compare
    against and which the pipeline has never supplied — without it the model
    infers "the market expected more" from tone, which is fabrication.

    Returns None when nothing usable came back, so an absent block is
    distinguishable from a zero one.
    """
    import yfinance as yf

    try:
        handle = yf.Ticker(symbol)
    except Exception:
        return None

    block: dict[str, Any] = {
        "as_of": date.today().isoformat(),
        "source": ESTIMATE_SOURCE,
    }

    def safe(getter):
        try:
            return getter()
        except Exception:
            return None

    earnings_est = safe(lambda: handle.earnings_estimate)
    revenue_est = safe(lambda: handle.revenue_estimate)

    # 0q = quarter in progress, +1q = next, 0y = current fiscal year.
    # NOTE: which of these lines up with the quarter actually being REPORTED
    # needs confirming against a live response — that's what --verbose is for.
    for label, key in (("current_quarter", "0q"),
                       ("next_quarter", "+1q"),
                       ("current_year", "0y")):
        row = _estimate_row(earnings_est, key)
        if row is None:
            continue
        revenue_row = _estimate_row(revenue_est, key) or {}
        row["revenue_avg"] = revenue_row.get("eps_avg")
        block[label] = {k: v for k, v in row.items() if v is not None}

    revisions = safe(lambda: handle.eps_revisions)
    if revisions is not None and hasattr(revisions, "empty") and not revisions.empty:
        try:
            row = revisions.loc["0q"]
            up = next((scalar(row[c]) for c in ("upLast30days", "upLast30Days")
                       if c in row.index), None)
            down = next((scalar(row[c]) for c in ("downLast30days", "downLast30Days")
                         if c in row.index), None)
            if up is not None or down is not None:
                block["eps_revisions_last_30d"] = {"up": up, "down": down}
        except Exception:
            pass

    has_content = any(k not in {"as_of", "source"} for k in block)
    return block if has_content else None


# ---------------------------------------------------------------------------
# Dossier assembly
# ---------------------------------------------------------------------------


def build_dossier(
    ticker: str,
    stock_prices: pd.Series,
    market_prices: pd.Series,
    earnings: pd.DataFrame,
) -> dict[str, Any]:
    ticker = canonical_ticker(ticker)
    sessions = stock_prices.index.intersection(market_prices.index).sort_values()
    stock_returns = stock_prices.reindex(sessions).pct_change(fill_method=None) * 100
    market_returns = market_prices.reindex(sessions).pct_change(fill_method=None) * 100

    reactions = []
    for _, event in earnings.sort_values("announcement_date").iterrows():
        timing = event.get("timing", "unknown")
        session = reaction_session(event.get("announcement_date"), timing, sessions)
        stock_return = stock_returns.get(session) if session is not None else None
        market_return = market_returns.get(session) if session is not None else None
        if (stock_return is None or market_return is None
                or pd.isna(stock_return) or pd.isna(market_return)):
            stock_return = market_return = abnormal = None
        else:
            abnormal = float(stock_return - market_return)
        reactions.append({
            "fiscal_quarter": scalar(event.get("fiscal_quarter")),
            "timing": timing,
            "reaction_date": scalar(session),
            "stock_return_pct": scalar(stock_return),
            "vti_return_pct": scalar(market_return),
            "abnormal_return_pct": scalar(abnormal),
            "earnings_surprise_pct": scalar(event.get("earnings_surprise_pct")),
            "surprise_source": scalar(event.get("surprise_source")),
        })

    return {
        "ticker": ticker,
        "prior_reactions": reactions,
        "reaction_statistics": reaction_statistics(reactions),
    }


def dossier_needs_work(path: Path, want_estimates: bool) -> bool:
    """True when the file is missing, unusable, or lacks a requested block."""
    if not path.exists():
        return True
    try:
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return True
    if not isinstance(existing, dict):
        return True
    stats = existing.get("reaction_statistics") or {}
    try:
        if float(stats.get("observations") or 0) <= 0:
            return True
    except (TypeError, ValueError):
        return True
    if want_estimates and not existing.get("forward_estimates"):
        return True
    return False


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


def load_universe_from_nasdaq(include_etfs: bool = False) -> list[str]:
    """Every symbol on the Nasdaq-traded file — the canonical free listing."""
    frame = pd.read_csv(NASDAQ_TRADED_URL, sep="|")
    frame = frame[frame.iloc[:, 0] != "File Creation Time"]  # trailing footer row
    if "Test Issue" in frame.columns:
        frame = frame[frame["Test Issue"] != "Y"]
    if not include_etfs and "ETF" in frame.columns:
        frame = frame[frame["ETF"] != "Y"]
    column = "NASDAQ Symbol" if "NASDAQ Symbol" in frame.columns else "Symbol"
    symbols = (
        frame[column].dropna().astype(str).str.strip().str.upper().unique().tolist()
    )
    return [s for s in symbols if _is_plausible_equity(s)]


def _is_plausible_equity(symbol: str) -> bool:
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        return False
    if len(symbol) > 6:
        return False
    # Five-letter Nasdaq symbols ending in W/R/U/P are warrants, rights, units
    # and preferreds — they have no earnings event of their own.
    if len(symbol) == 5 and symbol[-1] in NON_EQUITY_SUFFIXES:
        return False
    return True


def load_universe_from_file(path: Path) -> list[str]:
    frame = pd.read_csv(path)
    column = next(
        (c for c in ("ticker", "Ticker", "symbol", "Symbol") if c in frame.columns),
        frame.columns[0],
    )
    return frame[column].dropna().astype(str).str.strip().str.upper().unique().tolist()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    DOSSIER_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    failures_path = STATE_DIR / "failures.json"
    manifest_path = STATE_DIR / "manifest.json"

    known_failures: dict[str, str] = {}
    if failures_path.exists() and not args.retry_failures:
        try:
            known_failures = json.loads(failures_path.read_text())
        except Exception:
            known_failures = {}

    print("Loading universe...")
    if args.universe_file:
        universe = load_universe_from_file(Path(args.universe_file))
    else:
        universe = load_universe_from_nasdaq(include_etfs=args.include_etfs)
    # Never lose tickers we already care about.
    for extra in (REPO_ROOT / "knowledge" / "mappings" / "industry_map.csv",):
        if extra.exists():
            universe = sorted(set(universe) | set(load_universe_from_file(extra)))
    print(f"  {len(universe):,} symbols")

    todo = [
        t for t in universe
        if t not in known_failures
        and dossier_needs_work(DOSSIER_DIR / f"{t}.yaml", args.estimates)
    ]
    if args.limit:
        todo = todo[: args.limit]
    print(f"  {len(todo):,} to build "
          f"({len(known_failures):,} previously failed, skipped)\n")
    if not todo:
        print("Nothing to do.")
        return 0

    print(f"Fetching {MARKET_PROXY} benchmark...")
    market_prices = call_with_retries(
        lambda: fetch_adjusted_prices(MARKET_PROXY, period=args.period),
        MARKET_PROXY, verbose=args.verbose,
    )
    if market_prices.empty:
        print(f"FATAL: could not fetch {MARKET_PROXY}. Abnormal returns are "
              f"defined against it; aborting rather than writing wrong data.")
        return 1
    print(f"  {len(market_prices):,} sessions\n")

    built = skipped = failed = 0
    estimates_seen = 0
    started = time.time()

    for index, ticker in enumerate(todo, start=1):
        path = DOSSIER_DIR / f"{ticker}.yaml"
        try:
            prices = fetch_adjusted_prices(ticker, period=args.period)
            if prices.empty:
                raise RuntimeError("no price history")
            earnings = fetch_earnings_events(ticker, limit=args.earnings_limit)
            if earnings.empty:
                raise RuntimeError("no earnings history")

            dossier = build_dossier(ticker, prices, market_prices, earnings)
            if dossier["reaction_statistics"]["observations"] <= 0:
                raise RuntimeError("no usable reactions")

            if args.estimates:
                block = fetch_forward_estimates(ticker)
                if block:
                    dossier["forward_estimates"] = block
                    estimates_seen += 1

            path.write_text(
                yaml.safe_dump(dossier, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            built += 1
            if args.verbose:
                n = dossier["reaction_statistics"]["observations"]
                est = "+est" if dossier.get("forward_estimates") else ""
                print(f"  [{index}/{len(todo)}] {ticker:6s} {n} reactions {est}")
        except Exception as exc:
            failed += 1
            known_failures[ticker] = f"{type(exc).__name__}: {exc}"[:200]
            if args.verbose:
                print(f"  [{index}/{len(todo)}] {ticker:6s} FAILED: {exc}")

        if index % args.checkpoint_every == 0:
            failures_path.write_text(json.dumps(known_failures, indent=2))
            rate = index / max(time.time() - started, 1)
            remaining = (len(todo) - index) / max(rate, 1e-9) / 60
            print(f"  ... {index:,}/{len(todo):,}  built {built:,}  failed {failed:,}"
                  f"  ~{remaining:.0f} min left")

        time.sleep(args.sleep)

    failures_path.write_text(json.dumps(known_failures, indent=2))
    manifest_path.write_text(json.dumps({
        "built_on": date.today().isoformat(),
        "universe_size": len(universe),
        "attempted": len(todo),
        "built": built,
        "failed": failed,
        "with_forward_estimates": estimates_seen,
        "estimates_requested": bool(args.estimates),
        "earnings_limit": args.earnings_limit,
        "market_proxy": MARKET_PROXY,
    }, indent=2))

    elapsed = (time.time() - started) / 60
    print(f"\nDone in {elapsed:.0f} min. built {built:,}  failed {failed:,}  "
          f"skipped {skipped:,}")
    if args.estimates:
        print(f"forward estimates present on {estimates_seen:,} of {built:,} built")
        if built and estimates_seen == 0:
            print("WARNING: zero estimates came back. The yfinance accessors in "
                  "fetch_forward_estimates() likely need adjusting for this "
                  "version — re-run with --limit 5 --verbose and check.")
    print(f"total dossiers on disk: {len(list(DOSSIER_DIR.glob('*.yaml'))):,}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--limit", type=int, default=0,
                   help="only build N tickers — use for a smoke test")
    p.add_argument("--universe-file",
                   help="CSV with a ticker column, instead of the Nasdaq listing")
    p.add_argument("--include-etfs", action="store_true")
    p.add_argument("--estimates", dest="estimates", action="store_true", default=True,
                   help="fetch consensus estimates (default; see cutoff warning)")
    p.add_argument("--no-estimates", dest="estimates", action="store_false")
    p.add_argument("--earnings-limit", type=int, default=8)
    p.add_argument("--period", default="10y")
    p.add_argument("--sleep", type=float, default=0.4,
                   help="seconds between tickers; raise if Yahoo rate-limits")
    p.add_argument("--checkpoint-every", type=int, default=100)
    p.add_argument("--retry-failures", action="store_true",
                   help="ignore the failure log and retry everything")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    if args.estimates and not args.limit:
        print("NOTE: writing forward estimates stamped as of "
              f"{date.today().isoformat()}. Do not re-run with estimates inside "
              "a live prediction window — see the module docstring.\n")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
