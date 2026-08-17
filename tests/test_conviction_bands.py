"""Tests for prompt v3: conviction bands, extraction capture, versioning.

Conviction is only meaningful if it constrains something. These tests pin the
constraint so a future prompt edit can't quietly turn it back into a label.
"""

from __future__ import annotations

import json

import pytest

import predict as predict_module
import prompt_construction as prompts


# ---------------------------------------------------------------------------
# Conviction bands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence", "raw", "expected"),
    [
        ("low", 0.95, 0.65),      # low conviction cannot reach the top decile
        ("low", 0.02, 0.35),
        ("low", 0.50, 0.50),      # inside the band, untouched
        ("medium", 0.95, 0.80),
        ("medium", 0.05, 0.20),
        ("medium", 0.60, 0.60),
        ("high", 0.95, 0.95),     # high conviction keeps the full range
        ("high", 0.001, 0.02),
    ],
)
def test_conviction_caps_distance_from_the_middle(confidence, raw, expected):
    assert predict_module._apply_conviction_band(raw, confidence) == pytest.approx(
        expected
    )


@pytest.mark.parametrize("confidence", [None, "", "  ", "very high", "unknown"])
def test_unstated_conviction_passes_through_unclamped(confidence):
    """The band must FAIL OPEN, and this is the most important test here.

    Our whole measured edge is the low tail — 0.05-0.15 calls on real
    disasters, 81% directionally accurate. If a schema regression dropped
    `confidence` and we defaulted to the "low" band, every one of those would
    be clamped up to 0.35 and the edge would disappear with no error anywhere.
    """
    assert predict_module._apply_conviction_band(0.97, confidence) == pytest.approx(
        0.97
    )
    assert predict_module._apply_conviction_band(0.06, confidence) == pytest.approx(
        0.06
    )


def test_a_high_conviction_disaster_call_survives_the_band():
    """The negative edge must be reachable."""
    assert predict_module._apply_conviction_band(0.08, "high") == pytest.approx(0.08)


def test_conviction_matching_is_case_and_whitespace_insensitive():
    assert predict_module._apply_conviction_band(0.97, " HIGH ") == pytest.approx(0.97)


def test_band_is_applied_after_scale_normalisation(monkeypatch):
    """A model emitting 0-100 must be rescaled BEFORE the band is applied.

    Otherwise 95 would clamp to the band ceiling and then never rescale.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        predict_module,
        "completion",
        _fake_completion({"predicted_percentile": 95, "confidence": "medium"}),
    )
    result = predict_module._ask_llm_details(
        summary={"summary": "x"}, ticker="AAPL", event_type="EARNINGS_RELEASE"
    )
    assert result.predicted_percentile == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# Extraction capture
# ---------------------------------------------------------------------------


def _fake_completion(payload: dict):
    from types import SimpleNamespace

    def _call(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload))
                )
            ]
        )

    return _call


def test_extraction_fields_are_captured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        predict_module,
        "completion",
        _fake_completion({
            "key_metrics": ["revenue +8% to $142M", "adj EPS $0.31"],
            "guidance": "reaffirmed",
            "result_quality": "clean, no material one-offs",
            "expectation_gap": "confirms the prior path; consensus unavailable",
            "rules_applied": ["GLB-EXPECT-01"],
            "expected_abnormal_return_pct": 0.5,
            "direction": "neutral",
            "confidence": "medium",
            "predicted_percentile": 0.52,
        }),
    )
    result = predict_module._ask_llm_details(
        summary={"summary": "x"}, ticker="AAPL", event_type="EARNINGS_RELEASE"
    )
    assert result.key_metrics == ["revenue +8% to $142M", "adj EPS $0.31"]
    assert result.guidance == "reaffirmed"
    assert result.result_quality.startswith("clean")
    assert "consensus unavailable" in result.expectation_gap
    assert result.predicted_percentile == pytest.approx(0.52)


def test_a_v2_era_response_still_validates(monkeypatch):
    """Backward compatibility: the old schema must not fall back to 0.5."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        predict_module,
        "completion",
        _fake_completion({
            "percentile": 0.28,
            "confidence": "high",
            "rules_applied": ["GLB-GUID-01"],
            "top_drivers": ["guidance cut"],
        }),
    )
    result = predict_module._ask_llm_details(
        summary={"summary": "x"}, ticker="AAPL", event_type="EARNINGS_RELEASE"
    )
    assert result.predicted_percentile == pytest.approx(0.28)
    assert result.key_metrics == []
    assert result.guidance is None


def test_malformed_response_still_falls_back_to_neutral(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        predict_module, "completion", _fake_completion({"nonsense": True})
    )
    result = predict_module._ask_llm_details(
        summary={"summary": "x"}, ticker="AAPL", event_type="EARNINGS_RELEASE"
    )
    assert result.predicted_percentile == 0.5


def test_ledger_row_carries_the_diagnostic_fields(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        predict_module,
        "completion",
        _fake_completion({
            "key_metrics": ["revenue +8%"],
            "guidance": "raised",
            "expected_abnormal_return_pct": 4.2,
            "direction": "up",
            "confidence": "medium",
            "predicted_percentile": 0.74,
        }),
    )
    rows = predict_module._predict_rows(
        event={
            "event_type": "EARNINGS_RELEASE",
            "focal_assets": [{"identifier_value": "AAPL"}],
        },
        summary={"summary": "x"},
    )
    row = rows[0]
    for field in (
        "expected_abnormal_return_pct", "direction", "key_metrics", "guidance",
        "result_quality", "expectation_gap", "prompt_version", "knowledge_version",
    ):
        assert field in row, f"ledger row is missing {field}"
    assert row["knowledge_version"] != "unknown"


# ---------------------------------------------------------------------------
# Knowledge versioning
# ---------------------------------------------------------------------------


def test_knowledge_version_is_a_stable_short_hash():
    first = prompts.knowledge_version()
    assert isinstance(first, str) and len(first) == 12
    assert first == prompts.knowledge_version()


def test_knowledge_version_tracks_the_rulebook_not_the_version_string(tmp_path):
    """The defect this exists to fix: rules changing without a version bump."""
    original = prompts.GLOBAL_PATH.read_bytes()
    before = prompts.knowledge_version()
    try:
        prompts.GLOBAL_PATH.write_bytes(original + b"\n# an edit\n")
        prompts.knowledge_version.cache_clear()
        assert prompts.knowledge_version() != before
    finally:
        prompts.GLOBAL_PATH.write_bytes(original)
        prompts.knowledge_version.cache_clear()
    assert prompts.knowledge_version() == before


# ---------------------------------------------------------------------------
# Prompt structure
# ---------------------------------------------------------------------------


def test_the_announcement_precedes_the_rulebook_in_the_prompt():
    """The whole point of v3: facts before framework."""
    rendered = prompts.construct_prompt("SUMMARY_SENTINEL_TEXT", "AAON")
    assert rendered.index("SUMMARY_SENTINEL_TEXT") < rendered.index("GLB-NEUTRAL-01")


def test_every_placeholder_is_substituted():
    rendered = prompts.construct_prompt("some summary", "AAON")
    import re

    leftover = re.findall(r"\{(\w+)\}", rendered)
    assert leftover == [], f"unsubstituted placeholders: {leftover}"


def test_output_schema_orders_extraction_before_estimate():
    template = prompts.PROMPT_PATH.read_text(encoding="utf-8")
    order = [
        template.index(key)
        for key in (
            '"key_metrics"', '"guidance"', '"expectation_gap"',
            '"expected_abnormal_return_pct"', '"predicted_percentile"',
        )
    ]
    assert order == sorted(order), "output schema must extract before it estimates"


# ---------------------------------------------------------------------------
# Knowledge-cutoff guard on forward estimates (compliance control)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "cutoff", "permitted", "why"),
    [
        ("2026-08-15", "2026-09-19T20:00:00Z", True,
         "built weeks ahead of a September event"),
        ("2026-08-15", "2026-08-17T20:00:00Z", True,
         "built the 15th, cutoff the 17th"),
        ("2026-08-15", "2026-08-14T20:00:00Z", False,
         "THE TRAP: Monday's events, cutoff already past when we built"),
        ("2026-08-15", "2026-08-15T20:00:00Z", False,
         "same day — as_of has no time, so assume end of day"),
        (None, "2026-09-19T20:00:00Z", False, "no as_of stamp"),
        ("2026-08-15", None, False, "cutoff absent from the payload"),
        (None, None, False, "neither"),
        ("not-a-date", "2026-09-19T20:00:00Z", False, "unparseable"),
        ("2026-08-15", "garbage", False, "unparseable cutoff"),
    ],
)
def test_forward_estimates_cutoff_guard(as_of, cutoff, permitted, why):
    assert prompts.forward_estimates_permitted(as_of, cutoff) is permitted, why


def _dossier_with_estimates(tmp_path, as_of="2026-08-15"):
    import yaml
    (tmp_path / "ZZZZ.yaml").write_text(yaml.safe_dump({
        "ticker": "ZZZZ",
        "prior_reactions": [{"abnormal_return_pct": 1.0}],
        "reaction_statistics": {"observations": 4},
        "forward_estimates": {"as_of": as_of, "current_quarter": {"eps_avg": 0.31}},
    }, sort_keys=False), encoding="utf-8")
    return tmp_path


def test_estimates_reach_the_prompt_when_the_cutoff_is_later(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "DOSSIER_PATH", _dossier_with_estimates(tmp_path))
    text = prompts.get_dossier("ZZZZ", knowledge_cutoff="2026-09-19T20:00:00Z")
    assert "forward_estimates" in text and "eps_avg" in text


def test_estimates_are_withheld_when_the_cutoff_has_passed(tmp_path, monkeypatch):
    """The 217 events on Mon Aug 17 carry a cutoff of Aug 14 20:00Z."""
    monkeypatch.setattr(prompts, "DOSSIER_PATH", _dossier_with_estimates(tmp_path))
    text = prompts.get_dossier("ZZZZ", knowledge_cutoff="2026-08-14T20:00:00Z")
    assert "forward_estimates" not in text
    assert "eps_avg" not in text
    # the historical half must survive — it was never cutoff-sensitive
    assert "prior_reactions" in text
    assert prompts.is_valid_dossier(text)


def test_the_guard_fails_closed_when_no_cutoff_is_supplied(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "DOSSIER_PATH", _dossier_with_estimates(tmp_path))
    assert "forward_estimates" not in prompts.get_dossier("ZZZZ")


def test_construct_prompt_threads_the_cutoff_through(tmp_path, monkeypatch):
    """Assert on the VALUE, not the field name.

    The prompt template itself documents `eps_avg` and `as_of`, so searching
    the rendered prompt for a field name always matches and would make this
    test vacuous. The estimate value only appears if the block survived.
    """
    monkeypatch.setattr(prompts, "DOSSIER_PATH", _dossier_with_estimates(tmp_path))
    allowed = prompts.construct_prompt(
        "s", "ZZZZ", knowledge_cutoff="2026-09-19T20:00:00Z"
    )
    blocked = prompts.construct_prompt(
        "s", "ZZZZ", knowledge_cutoff="2026-08-14T20:00:00Z"
    )
    assert "0.31" in allowed and "2026-08-15" in allowed
    assert "0.31" not in blocked and "2026-08-15" not in blocked
