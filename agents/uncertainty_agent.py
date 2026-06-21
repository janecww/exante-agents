import json
import re
from pathlib import Path

from config import client, MODEL

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "uncertainty_prompt.md"

_REQUIRED_ITEM_KEYS = {"parameter", "confidence", "justification", "expert_review_required"}


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"No JSON object found in Uncertainty Agent response:\n{text[:500]}")
    return json.loads(match.group())


def run(assumptions: dict) -> dict:
    system_prompt = _load_system_prompt()
    user_message = (
        f"Evaluate the confidence of each assumption below and flag those requiring expert review:\n\n"
        f"{json.dumps(assumptions, indent=2)}\n\n"
        f"Return a JSON object with a single key 'assumptions' containing an array. "
        f"Each item must have: parameter (string, matching the input), "
        f"confidence (float 0.0–1.0), justification (string), "
        f"expert_review_required (boolean)."
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

    if "assumptions" not in result:
        raise ValueError("Uncertainty Agent response missing 'assumptions' key.")

    for item in result["assumptions"]:
        missing = _REQUIRED_ITEM_KEYS - item.keys()
        if missing:
            item.update({k: "" for k in missing})
        # Clamp confidence to [0.0, 1.0]
        item["confidence"] = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
        # Normalise expert_review_required to bool
        erq = item.get("expert_review_required", False)
        item["expert_review_required"] = bool(erq) if not isinstance(erq, str) else erq.lower() == "true"

    return result
