import json
import re
from pathlib import Path

from config import client, MODEL

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "scope_prompt.md"

_REQUIRED_KEYS = {
    "functional_unit", "system_boundary", "lifecycle_stages",
    "foreground_processes", "background_processes", "key_parameters",
}


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"No JSON object found in Scope Agent response:\n{text[:500]}")
    return json.loads(match.group())


def run(technology: str, scale: str) -> dict:
    system_prompt = _load_system_prompt()
    user_message = (
        f"Define the prospective LCA scope for the following technology:\n"
        f"- Technology: {technology}\n"
        f"- Production Scale: {scale}\n\n"
        f"Return a JSON object with exactly these keys: "
        f"functional_unit, system_boundary, lifecycle_stages (array), "
        f"foreground_processes (array), background_processes (array), key_parameters (array)."
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

    missing = _REQUIRED_KEYS - result.keys()
    if missing:
        raise ValueError(f"Scope Agent response missing keys: {missing}")

    return result
