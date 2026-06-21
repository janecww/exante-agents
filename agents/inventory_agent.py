import json
import re
from pathlib import Path
from typing import List

from config import client, MODEL

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "inventory_prompt.md"

_REQUIRED_ITEM_KEYS = {"parameter", "value", "unit", "confidence", "expert_reviewed"}


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"No JSON object found in Inventory Agent response:\n{text[:500]}")
    return json.loads(match.group())


def run(scope: dict, assumption_register: List[dict]) -> dict:
    system_prompt = _load_system_prompt()
    user_message = (
        f"Compile the final prospective LCA inventory.\n\n"
        f"LCA Scope:\n{json.dumps(scope, indent=2)}\n\n"
        f"Reviewed Assumption Register:\n{json.dumps(assumption_register, indent=2)}\n\n"
        f"Return a JSON object with a single key 'inventory' containing an array. "
        f"Each item must have: parameter (string), value (number), unit (string), "
        f"confidence (float 0.0–1.0), expert_reviewed (boolean)."
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content.strip()
    result = _extract_json(content)

    if "inventory" not in result:
        raise ValueError("Inventory Agent response missing 'inventory' key.")

    for item in result["inventory"]:
        missing = _REQUIRED_ITEM_KEYS - item.keys()
        if missing:
            item.update({k: "" for k in missing})
        item["confidence"] = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
        er = item.get("expert_reviewed", False)
        item["expert_reviewed"] = bool(er) if not isinstance(er, str) else er.lower() == "true"

    return result
