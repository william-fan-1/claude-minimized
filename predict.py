"""★ THIS IS THE ONLY FILE YOU NEED TO EDIT. ★

`predict(event)` is called once per competition event, after the webhook has
already been verified for you. Return one prediction per focal asset. Everything
else in this repo (webhook verification, dedupe, submission) is plumbing.

The default implementation asks the provider-qualified model configured below for
a calibrated percentile. If that provider's API key is not set, it returns a 0.5
baseline so the full deploy → receive → submit round-trip still works without
burning credits. Replace the body of `predict` with whatever strategy you like —
the only contract is the return shape documented below.
"""

from __future__ import annotations

import json
import os

import httpx
from litellm import completion
from pydantic import AliasChoices, BaseModel, Field

from prompt_construction import construct_prompt, PROMPT_VERSION

# This is the only value to change when switching models. The provider prefix
# selects both the LiteLLM backend and the corresponding environment variable.
# Examples: "openai/gpt-5.4", "anthropic/claude-sonnet-4-5"
MODEL = "gemini/gemini-2.5-flash"

PROVIDER_API_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

_missing_key_warnings: set[str] = set()

# Timeouts, sized against the 5-minute prediction window that opens when your
# handler ACKs the webhook. Worst case is 15 + (120 x 2) + 15 = 270s, which
# fits with ~30s to spare. Nothing upstream retries a failed prediction — once
# the delivery is ACKed the platform considers it done — so the one retry here
# is the only one you get. Raising either value can push you past the deadline.
SUMMARY_TIMEOUT_SECONDS = 15.0
LLM_TIMEOUT_SECONDS = 120.0
LLM_MAX_RETRIES = 1


def predict(event: dict) -> list[dict]:
    """Return predictions for one Explaining Markets event.

    `event` is the verified webhook payload. Useful fields:
      event["event_type"]          e.g. "EARNINGS_RELEASE"
      event["focal_assets"]        list of {"identifier_type", "identifier_value"}
      event["information_url"]     short-lived signed URL with the event summary JSON
      event["prediction_deadline"] ISO timestamp; submit before this fires

    Required return: a list of dicts, one per focal asset:
      [{"identifier_value": "AAPL", "predicted_percentile": 0.71}, ...]

    `predicted_percentile` is a float in [0, 1] — where you predict the asset's
    next-day abnormal (market-adjusted) return will rank across all of the
    quarter's event outcomes: 0 = the quarter's most negative reaction,
    0.50 = median, 1 = its most positive. It's a cross-sectional rank across the
    quarter's events, not a percentile within the asset's own history.
    """
    summary = httpx.get(event["information_url"], timeout=SUMMARY_TIMEOUT_SECONDS)
    summary.raise_for_status()
    summary_json = summary.json()

    # One model call per focal asset, in series — so the LLM budget below is
    # per asset, not per event. Today every event carries a single asset; if
    # that changes and you need several, run them concurrently rather than
    # raising the timeout.
    return [
        {
            "identifier_value": row["identifier_value"],
            "predicted_percentile": row["predicted_percentile"],
        }
        for row in _predict_rows(
            event=event,
            summary=summary_json,
        )
    ]


def predict_with_metadata(event: dict) -> list[dict]:
    """Return predictions plus audit fields for the persistent ledger."""
    summary = httpx.get(event["information_url"], timeout=SUMMARY_TIMEOUT_SECONDS)
    summary.raise_for_status()
    return _predict_rows(event=event, summary=summary.json())


def _predict_rows(*, event: dict, summary: dict) -> list[dict]:
    rows = []
    for asset in event["focal_assets"]:
        result = _ask_llm_details(
            summary=summary,
            ticker=asset["identifier_value"],
            event_type=event["event_type"],
        )
        rows.append({
            "identifier_value": asset["identifier_value"],
            "predicted_percentile": result.predicted_percentile,
            "confidence": result.confidence,
            "rules_applied": result.rules_applied,
            "prompt_version": PROMPT_VERSION,
        })
    return rows


# ----------------------------------------------------------------------
# Default strategy: a single calibrated LLM call per asset.
# Swap this out, or rewrite `predict` entirely, to enter your own model.
# ----------------------------------------------------------------------


class Prediction(BaseModel):
    """Structured response shape for the LLM call.

    Every provider response is validated locally. This keeps the competition-facing
    contract identical even when providers differ in their structured-output support.
    """

    predicted_percentile: float = Field(
        validation_alias=AliasChoices(
            "predicted_percentile",
            "percentile",
            "prediction",
        )
    )
    confidence: str = "low"
    rules_applied: list[str] = Field(default_factory=list)

# Normalization function as a safeguard 
def _normalize_percentile(value: float) -> float:
    """Check if 0 <= prediction <= 1. Normalize if not."""
    value = float(value)

    if value > 1:
        value /= 100.0

    return max(0.0, min(1.0, value))

def _ask_llm(*, summary: dict, ticker: str, event_type: str) -> float:
    """Compatibility wrapper returning only the competition percentile."""
    return _ask_llm_details(
        summary=summary, ticker=ticker, event_type=event_type
    ).predicted_percentile

def _ask_llm_details(*, summary: dict, ticker: str, event_type: str) -> Prediction:
    """Ask MODEL for a percentile and the metadata needed by the ledger."""
    api_key_name = _required_api_key(MODEL)
    if not os.environ.get(api_key_name):
        if api_key_name not in _missing_key_warnings:
            print(
                f"[WARN] {api_key_name} not set for {MODEL} — submitting 0.5 "
                "placeholder. Set the key in .env and re-deploy for real predictions."
            )
            _missing_key_warnings.add(api_key_name)
        return Prediction(predicted_percentile=0.5)

    summary_text = summary.get("summary") if isinstance(summary, dict) else None
    if not summary_text:
        summary_text = json.dumps(summary)
    summary_text = summary_text[:8000]

    user_prompt = construct_prompt(summary_text, ticker)

    try:
        resp = completion(
            model=MODEL,
            messages=[
                {"role": "system", "content": user_prompt},
            ],
            # JSON mode is supported across the three target providers. Pydantic
            # below remains the source of truth for shape and numeric bounds.
            response_format={"type": "json_object"},
            temperature=0,
            timeout=LLM_TIMEOUT_SECONDS,
            num_retries=LLM_MAX_RETRIES,
        )
        content = resp.choices[0].message.content
        result = Prediction.model_validate_json(content)
        result.predicted_percentile = _normalize_percentile(
            result.predicted_percentile
        )
        return result
    except Exception as exc:
        # A prediction must always be submitted, even on a provider outage,
        # refusal, malformed response, timeout, or schema violation.
        print(f"[ERROR] {MODEL} prediction failed: {type(exc).__name__}: {exc}")
        return Prediction(predicted_percentile=0.5)

def _required_api_key(model: str) -> str:
    """Return the environment variable used by a provider-qualified model name."""
    if not isinstance(model, str) or "/" not in model:
        raise ValueError(
            "MODEL must be provider-qualified, for example "
            "'gemini/gemini-2.5-flash'"
        )
    provider, model_name = model.split("/", 1)
    if not model_name:
        raise ValueError("MODEL must include a model name after the provider prefix")
    try:
        return PROVIDER_API_KEYS[provider]
    except KeyError as exc:
        supported = ", ".join(sorted(PROVIDER_API_KEYS))
        raise ValueError(
            f"Unsupported MODEL provider {provider!r}; choose one of: {supported}"
        ) from exc
