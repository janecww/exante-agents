"""Deterministic loader for the Stage 1 shared skill YAML files.

Wraps the generic `load_yaml()` utility to load all Stage 1 skills from a
directory into a single plain Python dictionary. This loader performs no
reasoning and no schema validation; it is intended to be invoked by the
orchestrator, which injects the resulting dictionary into agents.
"""

from pathlib import Path

from src.tools.yaml_loader import load_yaml

SKILL_FILES = (
    "component_definition",
    "source_priority",
    "review_specification",
)


def load_skills(skill_directory: Path) -> dict:
    """Load all Stage 1 skill YAML files from skill_directory.

    Returns a dict keyed by skill name (filename without `.yaml`), with
    each value being the parsed contents of that skill's YAML file. If a
    required skill file is missing or malformed, the exception raised by
    `load_yaml()` propagates unchanged.
    """
    skill_directory = Path(skill_directory)
    return {
        skill_name: load_yaml(skill_directory / f"{skill_name}.yaml")
        for skill_name in SKILL_FILES
    }


# ============================================================================
# Future Work
# ============================================================================
#
# Stage 1 intentionally returns a plain Python dictionary to keep the
# architecture lightweight.
#
# Future versions may replace this with a dedicated Pydantic Skills model to:
#
# - provide stronger typing
# - improve IDE autocomplete
# - validate skill schemas
# - support versioning
# - simplify dependency injection
#
# The public API of this loader should remain stable regardless of the
# underlying implementation.
# ============================================================================
