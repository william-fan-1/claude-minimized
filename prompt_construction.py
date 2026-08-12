"""Prompt construction utilities for the explaining markets project.

This module loads prompt templates, YAML playbooks, and ticker-to-industry
mappings, then assembles the final prompt text used for event analysis.
"""

from pathlib import Path
from dataclasses import dataclass
import os
import re
import yaml
import pandas as pd
from litellm import completion
from pydantic import BaseModel

# Adjust the prompt version 
PROMPT_VERSION = "2.0.0"

# Paths to prompt file, rulebooks, industry map
ROOT = Path(__file__).resolve().parent
PROMPT_PATH = ROOT / "prompts" / "predict_v2.md"
GLOBAL_PATH = ROOT / "knowledge" / "playbooks" / "_global.yaml"
INDUSTRY_PATH = ROOT / "knowledge" / "playbooks" / "industry_playbooks.yaml"
MAPPINGS_PATH = ROOT / "knowledge" / "mappings" / "industry_map.csv"
DOSSIER_PATH = ROOT / "knowledge" / "dossier"
NO_CACHED_DOSSIER = "No cached dossier is available."
DOSSIER_RULE_ID = "GLB-MOD-01"
CLASSIFIER_MODEL = "gemini/gemini-2.5-flash-lite"
CLASSIFIER_TIMEOUT_SECONDS = 30.0

INDUSTRIES = (
    "Commercial Products",
    "Commercial Services",
    "Commercial Transportation",
    "Other Business Products and Services",
    "Apparel and Accessories",
    "Consumer Durables",
    "Consumer Non-Durables",
    "Media",
    "Restaurants, Hotels and Leisure",
    "Retail",
    "Services (Non-Financial)",
    "Transportation",
    "Other Consumer Products and Services",
    "Energy Equipment",
    "Exploration, Production and Refining",
    "Energy Services",
    "Utilities",
    "Other Energy",
    "Capital Markets/Institutions",
    "Commercial Banks",
    "Insurance",
    "Other Financial Services",
    "Healthcare Devices and Supplies",
    "Healthcare Services",
    "Healthcare Technology Systems",
    "Pharmaceuticals and Biotechnology",
    "Other Healthcare",
    "Communications and Networking",
    "Computer Hardware",
    "Semiconductors",
    "IT Services",
    "Software",
    "Other Information Technology",
    "Agriculture",
    "Chemicals and Gases",
    "Construction (Non-Wood)",
    "Containers and Packaging",
    "Forestry",
    "Metals, Minerals and Mining",
    "Textiles",
    "Other Materials",
)


class IndustryTag(BaseModel):
    industry: str

@dataclass(frozen=True)
class PromptRules:
    """Serialized rule sections inserted into the prompt template."""

    core_directive: str
    precedence: str
    anti_patterns: str
    global_rules: str
    industry_rules: str

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

def format_industry_tag(industry: str | None) -> str | None:
    """Normalize an industry name into an underscore-delimited lowercase tag."""
    if industry is None:
        return None
    return re.sub(r"[^a-z0-9]+", "_", industry.lower()).strip("_")

def _classify_industry(*, ticker: str, summary_text: str) -> str | None:
    """Classify an unmapped ticker into one supported industry; never fatal."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None

    prompt = (
        "Classify the company into exactly one industry from the allowed list. "
        "Use the ticker and earnings summary only as classification evidence.\n\n"
        f"Ticker: {ticker}\n"
        f"Earnings summary:\n{summary_text[:2500]}\n\n"
        f"Allowed industries (choose exactly one): {', '.join(INDUSTRIES)}\n\n"
        'Respond with JSON only: {"industry": "<exact allowed industry>"}'
    )

    try:
        response = completion(
            model=CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=CLASSIFIER_TIMEOUT_SECONDS,
            num_retries=0,
        )
        tag = IndustryTag.model_validate_json(
            response.choices[0].message.content
        )
        if tag.industry not in INDUSTRIES:
            print(
                f"[WARN] unsupported industry classification for {ticker}: "
                f"{tag.industry!r}"
            )
            return None
        return tag.industry
    except Exception as exc:
        print(
            f"[WARN] industry classification failed for {ticker}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None

####################################
########## Retrieve rules ##########
####################################

def _load_industry_rules(industry: str | None) -> str:
    industry_playbooks = load_yaml(INDUSTRY_PATH)

    # Include quarterly calibration rules
    applicable_rules = {
        # This must be included for every industry.
        "quarter_calibration": industry_playbooks.get(
            "quarter_calibration",
            [],
        ),
    }

    if industry is not None:
        industry_block = industry_playbooks.get(industry)
        if industry_block:
            applicable_rules["industry"] = industry
            applicable_rules["industry_playbook"] = industry_block

    return yaml.safe_dump(applicable_rules, sort_keys=False)

def _filter_rule_metadata(rules: list[dict]) -> list[dict]:
    """Copy rules while removing prompt-irrelevant provenance metadata."""
    excluded_fields = {"source", "evidence"}
    return [
        {
            key: value
            for key, value in rule.items()
            if key not in excluded_fields
        }
        for rule in rules
    ]

def _load_block_from_global(
    key: str,
    *,
    include_dossier_rule: bool = True,
) -> str:
    global_playbook = load_yaml(GLOBAL_PATH)
    block = global_playbook.get(key, [])

    if key == "rules" and not include_dossier_rule:
        block = [
            rule
            for rule in block
            if rule.get("id") != DOSSIER_RULE_ID
        ]

    block = _filter_rule_metadata(block)

    return yaml.safe_dump(block, sort_keys=False)

def _load_core_directive(include_dossier_rule: bool = True) -> str:
    return _load_block_from_global(
        "principles",
        include_dossier_rule=include_dossier_rule,
    )

def _load_precedence_rules(include_dossier_rule: bool = True) -> str:
    return _load_block_from_global(
        "precedence",
        include_dossier_rule=include_dossier_rule,
    )

def _load_anti_patterns(include_dossier_rule: bool = True) -> str:
    return _load_block_from_global(
        "anti_patterns",
        include_dossier_rule=include_dossier_rule,
    )

def _load_global_rules(
    include_dossier_rule: bool = True
) -> str:
    return _load_block_from_global(
        "rules",
        include_dossier_rule=include_dossier_rule,
    )

def load_prompt_rules(
    industry: str | None,
    include_dossier_rule: bool = True,
) -> PromptRules:
    """
    Load each independently owned prompt-rule section.

    Args:
    industry: Normalized industry tag used to select the industry playbook.

    Returns:
    A named collection of serialized sections ready for prompt substitution.
    """
    return PromptRules(
        core_directive=_load_core_directive(
            include_dossier_rule=include_dossier_rule,
        ),
        precedence=_load_precedence_rules(
            include_dossier_rule=include_dossier_rule,
        ),
        anti_patterns=_load_anti_patterns(
            include_dossier_rule=include_dossier_rule,
        ),
        global_rules=_load_global_rules(
            include_dossier_rule=include_dossier_rule,
        ),
        industry_rules=_load_industry_rules(industry),
    )

#####################################
###### Check for valid dossier ######
#####################################

def get_dossier(ticker: str) -> str | None:
    """Return the complete canonical ticker dossier file as text."""
    path = DOSSIER_PATH / f"{ticker.strip().upper()}.yaml"
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None

def parse_dossier(dossier: str | dict | None) -> dict | None:
    """Parse dossier text for internal checks without changing prompt contents."""
    if isinstance(dossier, dict):
        return dossier
    if not isinstance(dossier, str):
        return None
    try:
        parsed = yaml.safe_load(dossier)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None

def is_valid_dossier(dossier: str | dict | None) -> bool:
    """A dossier is usable only when it contains at least one reaction."""
    dossier_data = parse_dossier(dossier)
    if dossier_data is None:
        return False
    observations = dossier_data.get("reaction_statistics", {}).get("observations")
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

    industry_name = get_industry(ticker)
    if industry_name is None:
        industry_name = _classify_industry(
            ticker=ticker,
            summary_text=summary_text,
        )
    industry = format_industry_tag(industry_name)
    dossier_text = get_dossier(ticker)
    has_valid_dossier = is_valid_dossier(dossier_text)
    rules = load_prompt_rules(
        industry,
        include_dossier_rule=has_valid_dossier,
    )
    dossier = dossier_text if has_valid_dossier else NO_CACHED_DOSSIER

    user_prompt = (
        prompt_template
        # Summary of transcript
        .replace("{summary_text}", summary_text)
        # Objective to complete
        .replace("{core_directive}", rules.core_directive)
        # Industry specific trends to consider
        .replace("{industry_rules}", rules.industry_rules)
        # Previous earnings results
        .replace("{dossier}", dossier)
        # Rules on how to handle conflicting rules
        .replace("{precedence}", rules.precedence)
        # When not to fire
        .replace("{anti_patterns}", rules.anti_patterns)
        # Global rules
        .replace("{global_rules}", rules.global_rules)
    )

    return user_prompt
