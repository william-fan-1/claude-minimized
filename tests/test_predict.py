"""Offline tests for the provider-neutral prediction strategy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import predict as predict_module


SAMPLE_EVENT = {
    "id": "evt_test_1",
    "event_id": "11111111-1111-1111-1111-111111111111",
    "event_type": "EARNINGS_RELEASE",
    "timing_category": "SCHEDULED",
    "event_datetime": "2026-01-15T21:00:00Z",
    "focal_assets": [
        {"identifier_type": "TICKER", "identifier_value": "AAPL"},
        {"identifier_type": "TICKER", "identifier_value": "MSFT"},
    ],
    "information_url": "https://example.test/disclosure",
    "prediction_deadline": "2026-01-15T21:05:00Z",
}


class _FakeResponse:
    def raise_for_status(self) -> None:  # noqa: D401 - stub
        return None

    def json(self) -> dict:
        return {"summary": "Quarterly results in line with expectations."}


def test_predict_fallback_shape(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(predict_module.httpx, "get", lambda *a, **k: _FakeResponse())

    preds = predict_module.predict(SAMPLE_EVENT)

    assert isinstance(preds, list)
    assert len(preds) == len(SAMPLE_EVENT["focal_assets"])
    returned = {p["identifier_value"] for p in preds}
    assert returned == {"AAPL", "MSFT"}
    for p in preds:
        assert set(p) == {"identifier_value", "predicted_percentile"}
        assert 0.0 <= p["predicted_percentile"] <= 1.0
        assert p["predicted_percentile"] == 0.5  # fallback baseline


@pytest.mark.parametrize(
    ("model", "key_name"),
    [
        ("gemini/gemini-2.5-flash", "GEMINI_API_KEY"),
        ("openai/gpt-5.4", "OPENAI_API_KEY"),
        ("anthropic/claude-sonnet-4-5", "ANTHROPIC_API_KEY"),
    ],
)
def test_model_selects_provider_key(monkeypatch, model: str, key_name: str) -> None:
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content='{"predicted_percentile": 0.73}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(predict_module, "MODEL", model)
    monkeypatch.setenv(key_name, "test-key")
    monkeypatch.setattr(predict_module, "completion", fake_completion)

    result = predict_module._ask_llm(
        summary={"summary": "Strong beat and raised guidance."},
        ticker="TEST",
        event_type="EARNINGS_RELEASE",
    )

    assert result == 0.73
    assert calls[0]["model"] == model
    assert calls[0]["timeout"] == predict_module.LLM_TIMEOUT_SECONDS
    assert calls[0]["num_retries"] == predict_module.LLM_MAX_RETRIES


@pytest.mark.parametrize(
    "content",
    ["not json", '{}'],
)
def test_invalid_provider_response_falls_back(monkeypatch, content: str) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def fake_completion(**kwargs):
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(predict_module, "completion", fake_completion)

    result = predict_module._ask_llm(
        summary={"summary": "Results."},
        ticker="TEST",
        event_type="EARNINGS_RELEASE",
    )
    assert result == 0.5


def test_provider_error_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def fake_completion(**kwargs):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(predict_module, "completion", fake_completion)

    result = predict_module._ask_llm(
        summary={"summary": "Results."},
        ticker="TEST",
        event_type="EARNINGS_RELEASE",
    )
    assert result == 0.5


def test_model_metadata_and_scale_are_preserved(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def fake_completion(**kwargs):
        message = SimpleNamespace(
            content=(
                '{"percentile": 73, "confidence": "high", '
                '"rules_applied": ["Q3-CAL-01", "GLB-GUID-01"]}'
            )
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(predict_module, "completion", fake_completion)
    result = predict_module._ask_llm_details(
        summary={"summary": "Raised guidance."},
        ticker="TEST",
        event_type="EARNINGS_RELEASE",
    )

    assert result.predicted_percentile == 0.73
    assert result.confidence == "high"
    assert result.rules_applied == ["Q3-CAL-01", "GLB-GUID-01"]


@pytest.mark.parametrize("model", ["gpt-5.4", "unknown/model", "gemini/"])
def test_invalid_model_configuration_raises(model: str) -> None:
    with pytest.raises(ValueError):
        predict_module._required_api_key(model)
