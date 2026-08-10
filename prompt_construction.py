"""Prompt construction utilities for the explaining markets project.

This module loads prompt templates, YAML playbooks, and ticker-to-industry
mappings, then assembles the final prompt text used for event analysis.
"""

from pathlib import Path
import re
import yaml
import pandas as pd

# Adjust the prompt version 
PROMPT_VERSION = "1.2.0"

# Paths to prompt file, rulebooks, industry map
ROOT = Path(__file__).resolve().parent
PROMPT_PATH = ROOT / "prompts" / "predict_v2.md"
GLOBAL_PATH = ROOT / "knowledge" / "playbooks" / "_global.yaml"
INDUSTRY_PATH = ROOT / "knowledge" / "playbooks" / "industry_playbooks.yaml"
MAPPINGS_PATH = ROOT / "knowledge" / "mappings" / "industry_map.csv"
DOSSIER_PATH = ROOT / "knowledge" / "dossier"
NO_CACHED_DOSSIER = "No cached dossier is available."
DOSSIER_RULE_ID = "GLB-MOD-01"

#####################################
# Util functions to help build prompt
#####################################
def load_yaml(path: Path) -> dict:
    """Load a YAML file from disk and return its contents as a dictionary."""
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def _load_map() -> pd.DataFrame:
    """Read the industry mapping CSV and return it indexed by ticker."""
    return pd.read_csv(MAPPINGS_PATH).set_index('ticker')

def get_industry(ticker: str) -> str | None:
    """Return the mapped industry for a ticker or None if it cannot be resolved."""
    try:    
        mappings = _load_map()
        return mappings.loc[ticker]['industry']
    except Exception as e:
        print(f"{ticker} not found in mappings.")
        return None

def format_industry_tag(industry: str) -> str:
    """Normalize an industry name into an underscore-delimited lowercase tag."""
    if industry is not None: 
        return industry.lower().replace(" ", "_").replace(",", "")
    else: 
        return None

def load_prompt_rules(
    industry: str,
    include_dossier_rule: bool = True,
) -> tuple[str, str] | tuple[str, None]:
    """
    Load global and industry-specific prompt rules.

    Args:
    industry: Normalized industry tag used to select the industry playbook.

    Returns:
    A tuple containing the core directive YAML and the industry rules YAML.
    """
    global_playbook = load_yaml(GLOBAL_PATH)
    industry_playbooks = load_yaml(INDUSTRY_PATH)

    # The `principles` block becomes {core_directive}.
    core_directive = yaml.safe_dump(
        global_playbook["principles"],
        sort_keys=False,
    )

    global_rules = global_playbook.get("rules", [])
    if not include_dossier_rule:
        global_rules = [
            rule for rule in global_rules
            if rule.get("id") != DOSSIER_RULE_ID
        ]

    # These global rules apply to every event, except dossier-only rules when
    # the ticker has no usable historical reaction observations.
    applicable_rules = {
        "global_rules": global_rules,

        # This must be included for every industry.
        "quarter_calibration": industry_playbooks.get(
            "quarter_calibration",
            [],
        ),
    }

    # Add only the matching industry block.
    if industry is not None:
        industry_block = industry_playbooks.get(industry)

        if industry_block:
            applicable_rules["industry"] = industry
            applicable_rules["industry_playbook"] = industry_block

        industry_rules = yaml.safe_dump(
            applicable_rules,
            sort_keys=False,
        )
    else:
        industry_rules = ""

    return core_directive, industry_rules

def get_dossier(ticker: str) -> dict | None:
    """Load a canonical ticker dossier, returning None when it is unavailable."""
    path = DOSSIER_PATH / f"{ticker.strip().upper()}.yaml"
    try:
        dossier = load_yaml(path)
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return None
    return dossier if isinstance(dossier, dict) else None

def is_valid_dossier(dossier: dict | None) -> bool:
    """A dossier is usable only when it contains at least one reaction."""
    if not isinstance(dossier, dict):
        return False
    observations = dossier.get("reaction_statistics", {}).get("observations")
    if isinstance(observations, bool):
        return False
    try:
        return float(observations) > 0
    except (TypeError, ValueError):
        return False

####################################
######### Build the prompt #########
####################################

def construct_prompt(
    summary_text: str, 
    ticker: str
) -> str:
    """
    Construct the final prompt text for a given ticker and event summary.

    Reads the prompt template, resolves the ticker's industry, loads relevant
    playbook rules, and substitutes all placeholders with generated content.

    Args:
    summary_text: The summarized event transcript content.
    ticker: The ticker symbol to resolve industry-specific rules.

    Returns:
    The rendered prompt text ready for model consumption.
    """

    # Read in prompt template and clean its
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt_template = re.sub(
        r"\A\s*<!--.*?-->\s*",
        "",
        prompt_template,
        count=1,
        flags=re.DOTALL,
    )

    industry = format_industry_tag(get_industry(ticker))
    dossier_data = get_dossier(ticker)
    has_valid_dossier = is_valid_dossier(dossier_data)
    core_directive, industry_rules = load_prompt_rules(
        industry,
        include_dossier_rule=has_valid_dossier,
    )
    dossier = (
        yaml.safe_dump(dossier_data, sort_keys=False)
        if has_valid_dossier
        else NO_CACHED_DOSSIER
    )

    user_prompt = (
        prompt_template
        # Summary of transcript
        .replace("{event_bullets}", summary_text)
        # Objective to complete
        .replace("{core_directive}", core_directive)
        # Industry specific trends to consider
        .replace("{industry_rules}", industry_rules)
        .replace("{dossier}", dossier)
    )

    return user_prompt