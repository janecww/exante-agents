import json
import re
from pathlib import Path

from config import client, MODEL

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "assumption_prompt.md"

_REQUIRED_ITEM_KEYS = {"parameter", "value", "unit", "rationale", "analogy", "evidence"}


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"No JSON object found in Assumption Agent response:\n{text[:500]}")
    return json.loads(match.group())


def run(scope: dict) -> dict:
    system_prompt = _load_system_prompt()
    user_message = (
        f"Generate prospective inventory assumptions for the following LCA scope:\n\n"
        f"{json.dumps(scope, indent=2)}\n\n"
        f"Return a JSON object with a single key 'assumptions' containing an array. "
        f"Each item must have: parameter, value, unit, rationale, analogy, evidence."
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
    )

    content = response.choices[0].message.content.strip()
    result = _extract_json(content)

    if "assumptions" not in result:
        raise ValueError("Assumption Agent response missing 'assumptions' key.")

    for item in result["assumptions"]:
        missing = _REQUIRED_ITEM_KEYS - item.keys()
        if missing:
            item.update({k: "" for k in missing})

    return result
