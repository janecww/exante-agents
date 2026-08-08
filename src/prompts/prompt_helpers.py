"""Shared plain-text prompt-formatting helpers used by every prompt builder.

Centralised here so each prompt-builder module (one per agent) only
contains what is unique to that agent's prompt. The section-wrapping
convention and generic technology/process formatting are identical
across agents and must not be allowed to drift out of sync between
copies.
"""

import yaml

from src.models.technology import Technology

SECTION_SEPARATOR = "=" * 70


def dump(data: object) -> str:
    """Render a dict/model dump as readable YAML text."""
    return yaml.dump(data, sort_keys=False, allow_unicode=True).strip()


def section(title: str, body: str) -> str:
    """Wrap a section title and body with a plain-text separator."""
    return f"{SECTION_SEPARATOR}\n{title}\n{SECTION_SEPARATOR}\n{body}\n"


def format_technology_overview(technology: Technology) -> str:
    """Render a concise summary of the technology."""
    return (
        f"Technology name: {technology.technology.name}\n"
        f"Functional unit: {technology.technology.functional_unit}\n"
        f"Target production scale: {technology.target_state.scale}\n"
        f"Number of laboratory processes: {len(technology.processes)}"
    )


def extract_process_context(technology: Technology) -> list[dict]:
    """Summarise each process: type, note, and existing input names.

    Process outputs are deliberately excluded -- they are out of scope
    for both inventory classification and estimation recommendation.
    """
    return [
        {
            "process_id": process.id,
            "process_name": process.name,
            "process_type": process.process_type,
            "note": process.note,
            "existing_inputs": [flow.name for flow in process.inputs],
        }
        for process in technology.processes
    ]
