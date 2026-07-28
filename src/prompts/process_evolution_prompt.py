"""Prompt construction for the Process Evolution Agent.

Assembles a single plain-text prompt from the technology input, one
laboratory-scale process, the ProcessReviewEntry the agent is
responsible for completing, and the shared Stage 1 skills. This module
performs no reasoning and makes no LLM calls; it only prepares the
context a future LLM-powered agent will consume.
"""

import yaml

from src.models.review_package import ProcessReviewEntry
from src.models.technology import Process, Technology

SECTION_SEPARATOR = "=" * 70


def _dump(data: object) -> str:
    """Render a dict/model dump as readable YAML text."""
    return yaml.dump(data, sort_keys=False, allow_unicode=True).strip()


def _section(title: str, body: str) -> str:
    """Wrap a section title and body with a plain-text separator."""
    return f"{SECTION_SEPARATOR}\n{title}\n{SECTION_SEPARATOR}\n{body}\n"


def _format_available_knowledge(skills: dict) -> str:
    """Render the full contents of every supplied skill, not just names."""
    if not skills:
        return "(no shared skills supplied)"

    parts = []
    for skill_name, content in skills.items():
        title = skill_name.replace("_", " ").title()
        parts.append(f"{SECTION_SEPARATOR}\n{title}\n\n{_dump(content)}")
    parts.append(SECTION_SEPARATOR)
    return "\n\n".join(parts)


def _format_technology_overview(technology: Technology) -> str:
    """Render a concise summary of the technology."""
    return (
        f"Technology name: {technology.technology.name}\n"
        f"Functional unit: {technology.technology.functional_unit}\n"
        f"Target production scale: {technology.target_state.scale}\n"
        f"Number of laboratory processes: {len(technology.processes)}"
    )


def build_process_evolution_prompt(
    technology: Technology,
    process: Process,
    process_review_entry: ProcessReviewEntry,
    skills: dict,
) -> str:
    """Build the Process Evolution Agent prompt for one laboratory process.

    Args:
        technology: The full Technology model for the case.
        process: The single laboratory-scale Process to reason about.
        process_review_entry: The ProcessReviewEntry section of the shared
            ReviewPackage that the agent is responsible for completing.
            Initially this entry will mostly contain empty fields.
        skills: Dictionary of shared Stage 1 skills, keyed by skill name.

    Returns:
        A single plain-text prompt string (no chat/message formatting).
    """
    role = (
        "The Process Evolution Agent develops scientifically justified "
        "target-scale process and foreground inventory assumptions for "
        "one laboratory process."
    )

    task = (
        "Develop target-scale process and foreground inventory assumptions "
        "for the laboratory process shown above.\n\n"
        f"The target production scale is: {technology.target_state.scale}\n\n"
        "Use the supplied engineering knowledge where appropriate. Complete "
        "only the supplied review entry for this process. Preserve the "
        "existing schema of the review entry exactly: do not create any "
        "additional fields. Do not modify any other process."
    )

    expected_output = (
        "Return the supplied ProcessReviewEntry with all applicable fields "
        "completed while preserving the existing schema."
    )

    sections = [
        _section("ROLE", role),
        _section("AVAILABLE KNOWLEDGE", _format_available_knowledge(skills)),
        _section("TECHNOLOGY OVERVIEW", _format_technology_overview(technology)),
        _section("CURRENT LABORATORY PROCESS", _dump(process.model_dump())),
        _section(
            "CURRENT REVIEW ENTRY", _dump(process_review_entry.model_dump())
        ),
        _section("TASK", task),
        _section("EXPECTED OUTPUT", expected_output),
    ]

    return "\n".join(sections)
