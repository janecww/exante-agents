"""Deterministic utilities for persisting Stage 1 execution artifacts.

Agents call these helpers to record what they were given and what the
LLM returned; the helpers contain no reasoning of their own, only file
I/O. Everything is written under the case directory's existing
`outputs/` structure:

    cases/<case>/outputs/
        inputs/     # the object supplied to an agent, as YAML
        prompts/    # the exact prompt text sent to the LLM
        responses/  # the exact raw text the LLM returned
        parsed/     # the validated Pydantic model dump, as YAML
        logs/       # a single append-only workflow.log
"""

from pathlib import Path

from src.tools.yaml_loader import save_yaml


def _outputs_dir(case_directory: str | Path) -> Path:
    return Path(case_directory) / "outputs"


def save_input(case_directory: str | Path, filename: str, data: dict) -> Path:
    """Persist the object supplied to an agent as YAML under outputs/inputs/."""
    path = _outputs_dir(case_directory) / "inputs" / filename
    save_yaml(data, path)
    return path


def save_prompt(case_directory: str | Path, filename: str, prompt: str) -> Path:
    """Persist a generated prompt as plain text under outputs/prompts/."""
    path = _outputs_dir(case_directory) / "prompts" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")
    return path


def save_response(case_directory: str | Path, filename: str, response: str) -> Path:
    """Persist a raw LLM response, unmodified, under outputs/responses/."""
    path = _outputs_dir(case_directory) / "responses" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response, encoding="utf-8")
    return path


def save_parsed(case_directory: str | Path, filename: str, data: dict) -> Path:
    """Persist a validated Pydantic model dump as YAML under outputs/parsed/."""
    path = _outputs_dir(case_directory) / "parsed" / filename
    save_yaml(data, path)
    return path


def append_log(case_directory: str | Path, message: str) -> Path:
    """Append a single text execution message to outputs/logs/workflow.log."""
    path = _outputs_dir(case_directory) / "logs" / "workflow.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{message}\n")
    return path
