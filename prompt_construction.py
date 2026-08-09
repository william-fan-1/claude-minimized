from pathlib import Path
import re
import yaml

# Adjust the prompt version 
PROMPT_VERSION = "1.1.0"

# Paths to prompt file, rulebooks, industry map
ROOT = Path(__file__).resolve().parent
PROMPT_PATH = ROOT / "prompts" / "predict_v1.md"
GLOBAL_PATH = ROOT / "knowledge" / "playbooks" / "_global.yaml"
INDUSTRY_PATH = ROOT / "knowledge" / "playbooks" / "industry_playbooks.yaml"
MAPPINGS_PATH = ROOT / "knowledge" / "mappings" / "industry_map.csv"

#####################################
# Util functions to help build prompt
#####################################
def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def _rule_applies(rule: dict, profiles: list[str]) -> bool:
    """Keep a rule if its scope matches the company's profile tags."""
    required = (rule.get("scope") or {}).get("profile")
    if not required:
        return True            # unscoped / applies\_to: all
    if not profiles:
        return True            # no classification -> keep everything, fail safe
    return any(p == required or p in required or required in p for p in profiles)

def load_prompt_rules(industry: str) -> tuple[str, str]:
    global_playbook = load_yaml(GLOBAL_PATH)
    industry_playbooks = load_yaml(INDUSTRY_PATH)

    # The `principles` block becomes {core_directive}.
    core_directive = yaml.safe_dump(
        global_playbook["principles"],
        sort_keys=False,
    )

    # These global rules apply to every event.
    applicable_rules = {
        "global_rules": global_playbook.get("rules", []),

        # This must be included for every industry.
        "quarter_calibration": industry_playbooks.get(
            "quarter_calibration",
            [],
        ),
    }

    # Add only the matching industry block.
    industry_block = industry_playbooks.get(industry)

    if industry_block:
        applicable_rules["industry"] = industry
        applicable_rules["industry_playbook"] = industry_block

    industry_rules = yaml.safe_dump(
        applicable_rules,
        sort_keys=False,
    )

    return core_directive, industry_rules

def _load_map():
    pass

def get_industry(ticker):
    pass

def format_industry_tag(industry):
    pass

####################################
######### Build the prompt #########
####################################

def construct_prompt(summary_text, ticker):

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
    core_directive, industry_rules = load_prompt_rules(industry)

    # TODO: Implement dossier in next pass
    dossier = "No cached dossier is available."

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