from pathlib import Path
from types import SimpleNamespace

import yaml

import prompt_construction as prompts


def test_classifier_industries_match_playbook_keys():
    playbooks = prompts.load_yaml(prompts.INDUSTRY_PATH)
    expected = {
        key for key, value in playbooks.items()
        if key not in {"meta", "quarter_calibration", "sources"}
        and isinstance(value, dict)
    }

    assert {
        prompts.format_industry_tag(industry)
        for industry in prompts.INDUSTRIES
    } == expected


def test_classify_industry_accepts_exact_supported_label(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(
                    content='{"industry": "Healthcare Services"}'
                )
            )]
        )

    monkeypatch.setattr(prompts, "completion", fake_completion)

    industry = prompts._classify_industry(
        ticker="TEST",
        summary_text="The company operates hospitals and clinics.",
    )

    assert industry == "Healthcare Services"
    assert calls[0]["model"] == prompts.CLASSIFIER_MODEL
    assert calls[0]["num_retries"] == 0


def test_classify_industry_rejects_unsupported_label(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        prompts,
        "completion",
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"industry": "Other"}')
            )]
        ),
    )

    assert prompts._classify_industry(
        ticker="TEST",
        summary_text="Ambiguous company.",
    ) is None


def test_classify_industry_skips_call_without_provider_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        prompts,
        "completion",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("called")),
    )

    assert prompts._classify_industry(
        ticker="TEST",
        summary_text="Summary",
    ) is None


def test_construct_prompt_does_not_classify_mapped_ticker(monkeypatch):
    monkeypatch.setattr(
        prompts,
        "_classify_industry",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("called")),
    )

    rendered = prompts.construct_prompt("Summary", "INTT")

    assert "industry: semiconductors" in rendered


def test_load_prompt_rules_returns_named_serialized_sections():
    rules = prompts.load_prompt_rules("retail")

    assert isinstance(rules, prompts.PromptRules)
    assert all(isinstance(value, str) for value in (
        rules.core_directive,
        rules.precedence,
        rules.anti_patterns,
        rules.global_rules,
        rules.industry_rules,
    ))
    assert "P1" in rules.core_directive
    assert "GLB-NEUTRAL-01" in rules.global_rules
    assert "quarter_calibration" in rules.industry_rules
    assert "industry: retail" in rules.industry_rules


def test_global_and_calibration_rules_survive_missing_industry():
    rules = prompts.load_prompt_rules(None)

    assert "GLB-NEUTRAL-01" in rules.global_rules
    assert "quarter_calibration" in rules.industry_rules
    assert "industry:" not in rules.industry_rules


def test_dossier_rule_can_be_excluded_independently():
    rules = prompts.load_prompt_rules("retail", include_dossier_rule=False)

    assert prompts.DOSSIER_RULE_ID not in rules.global_rules
    assert "quarter_calibration" in rules.industry_rules


def test_global_rule_prompt_metadata_is_filtered_without_mutating_source():
    source_rules = prompts.load_yaml(prompts.GLOBAL_PATH)["rules"]
    rendered_rules = yaml.safe_load(prompts._load_global_rules())

    assert any("source" in rule for rule in source_rules)
    assert any("evidence" in rule for rule in source_rules)
    assert all("source" not in rule for rule in rendered_rules)
    assert all("evidence" not in rule for rule in rendered_rules)
    assert [rule["id"] for rule in rendered_rules] == [
        rule["id"] for rule in source_rules
    ]


def test_is_valid_dossier_requires_positive_observations():
    assert not prompts.is_valid_dossier(None)
    assert not prompts.is_valid_dossier({})
    assert not prompts.is_valid_dossier(
        {"reaction_statistics": {"observations": 0}}
    )
    assert prompts.is_valid_dossier(
        {"reaction_statistics": {"observations": 1}}
    )
    assert prompts.is_valid_dossier(
        "reaction_statistics:\n  observations: 1\n"
    )


def test_get_dossier_returns_the_complete_file_text(tmp_path: Path, monkeypatch):
    dossier_dir = tmp_path / "dossier"
    dossier_dir.mkdir()
    expected = "ticker: TEST\nreaction_statistics:\n  observations: 2\n"
    (dossier_dir / "TEST.yaml").write_text(expected, encoding="utf-8")
    monkeypatch.setattr(prompts, "DOSSIER_PATH", dossier_dir)

    dossier = prompts.get_dossier("test")

    assert isinstance(dossier, str)
    assert dossier == expected


def test_invalid_dossier_uses_fallback_and_omits_dossier_rule(
    tmp_path: Path,
    monkeypatch,
):
    dossier_dir = tmp_path / "dossier"
    dossier_dir.mkdir()
    (dossier_dir / "HOLX.yaml").write_text(
        yaml.safe_dump(
            {
                "ticker": "HOLX",
                "prior_reactions": [],
                "reaction_statistics": {"observations": 0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts, "DOSSIER_PATH", dossier_dir)

    rendered = prompts.construct_prompt("Sample earnings summary", "HOLX")

    assert prompts.NO_CACHED_DOSSIER in rendered
    assert prompts.DOSSIER_RULE_ID not in rendered


def test_valid_dossier_is_serialized_and_keeps_dossier_rule(
    tmp_path: Path,
    monkeypatch,
):
    dossier_dir = tmp_path / "dossier"
    dossier_dir.mkdir()
    (dossier_dir / "HOLX.yaml").write_text(
        yaml.safe_dump(
            {
                "ticker": "HOLX",
                "prior_reactions": [{"abnormal_return_pct": 2.5}],
                "reaction_statistics": {"observations": 1},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(prompts, "DOSSIER_PATH", dossier_dir)

    rendered = prompts.construct_prompt("Sample earnings summary", "HOLX")

    assert "ticker: HOLX" in rendered
    assert "observations: 1" in rendered
    assert prompts.NO_CACHED_DOSSIER not in rendered
    assert prompts.DOSSIER_RULE_ID in rendered
