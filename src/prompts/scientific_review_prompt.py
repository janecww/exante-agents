"""Prompt construction for the Scientific Review Agent.

Assembles a single plain-text prompt from the technology input, the
shared ReviewPackage, and the shared Stage 1 skills. This module
performs no reasoning and makes no LLM calls; it only prepares the
context a future LLM-powered agent will consume.
"""

import yaml

from src.models.review_package import ReviewPackage
from src.models.technology import Technology

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


def build_scientific_review_prompt(
    technology: Technology,
    review_package: ReviewPackage,
    skills: dict,
) -> str:
    """Build the Scientific Review Agent prompt for a review package.

    Args:
        technology: The full Technology model for the case.
        review_package: The shared ReviewPackage to be reviewed, containing
            the process and inventory assumptions proposed so far.
        skills: Dictionary of shared Stage 1 skills, keyed by skill name.

    Returns:
        A single plain-text prompt string (no chat/message formatting).
    """
    role = (
        "The Scientific Review Agent reviews proposed process and "
        "inventory assumptions for completeness, plausibility, "
        "traceability, and scientific justification."
    )

    task = (
        "Review the review package shown above.\n\n"
        "Use the supplied engineering knowledge where appropriate. Assess "
        "the completeness, plausibility, justification, traceability, and "
        "transparency of each assumption, and populate the review comments "
        "for each. Preserve the existing schema of the review package "
        "exactly: do not create any additional fields."
    )

    expected_output = (
        "Return the supplied ReviewPackage with review comments completed "
        "for each assumption while preserving the existing schema."
    )

    sections = [
        _section("ROLE", role),
        _section("AVAILABLE KNOWLEDGE", _format_available_knowledge(skills)),
        _section("TECHNOLOGY OVERVIEW", _format_technology_overview(technology)),
        _section("REVIEW PACKAGE", _dump(review_package.model_dump())),
        _section("TASK", task),
        _section("EXPECTED OUTPUT", expected_output),
    ]

    return "\n".join(sections)
