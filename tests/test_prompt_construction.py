from pathlib import Path

import yaml

import prompt_construction as prompts


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
