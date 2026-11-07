"""Prompt construction for the Parameter Identification (Parameter Requirement) Agent.

One prompt per flow with a practitioner-selected method. The agent reports
every input of that method under the shared definition of "available"
(`src.skills.availability.AVAILABILITY_DEFINITION`) -- the identical text
the Estimation Recommendation step used -- with the same evidence
sections (`src.prompts.estimation_recommendation_prompt`), so the two
steps judge the same evidence by the same rules. The method is shown with
the agent-facing `rules` columns only.

The agent must not change the method, rank alternatives, or perform the
scale-up calculation.
"""

import json

from src.models.parameter_review import COMPUTED_FIELDS, COMPUTED_PARAMETER_FIELDS, ParameterReview
from src.models.reviewed_recommendation import ReviewedRecommendationEntry
from src.models.technology import Technology
from src.prompts.estimation_recommendation_prompt import (
    _build_laboratory_quantity_lookup,
    _build_process_inventory,
    _format_lab_derived_parameters,
    _normalize_name,
)
from src.prompts.prompt_helpers import dump, format_technology_overview, section
from src.prompts.schema_skeleton import build_json_skeleton
from src.skills.availability import AVAILABILITY_DEFINITION


def build_parameter_requirement_prompt(
    technology: Technology,
    lab_derived_parameters: list[dict],
    entry: ReviewedRecommendationEntry,
) -> str:
    """Build the prompt for one flow's selected method.

    Raises `ValueError` if `entry.human_selected_method` is `None`: the
    agent is never invoked for a flow without a selected method.
    """
    if entry.human_selected_method is None:
        raise ValueError(
            "Parameter Requirement Agent requires a human-selected method; "
            f"Process ID {entry.process_id!r} / Inventory "
            f"{entry.inventory_name!r} has none."
        )

    role = (
        "You identify, for ONE inventory flow and the scale-up method the practitioner selected for it, the value "
        "and source of every input the method needs, from the case evidence. The selection is final: never propose "
        "or evaluate another method, and do not perform the scale-up calculation. Apply the DEFINITION OF "
        "\"AVAILABLE\" below exactly; the Estimation Recommendation step used the same definition, and the two "
        "results are compared."
    )

    laboratory_quantity = _build_laboratory_quantity_lookup(technology).get(
        (entry.process_id, _normalize_name(entry.inventory_name))
    )
    flow = {
        "process_id": entry.process_id,
        "process_name": entry.process_name,
        "inventory_name": entry.inventory_name,
        "component": entry.component,
        "laboratory_quantity": laboratory_quantity,
    }

    task = (
        "Return one entry in `required_parameters` for EVERY input listed in the SELECTED METHOD's `inputs`, using "
        "exactly those names (in `parameter`), in the same order, and no other entries. For each: set `tag` to the "
        "tag shown in brackets, and `status`, `value`, `unit`, `source`, `derivation` and `note` following the "
        "DEFINITION OF \"AVAILABLE\". For [DEFAULT=...] inputs, status is \"available\" and value is the default. "
        "For [TARGET] inputs, status is \"missing\" unless the evidence states the value. Never write a value that "
        "is not in the evidence, a stated default, a standard physical constant, or the result of an allowed "
        "derivation.\n\n"
        "WHERE TO FIND: for every input whose status is \"missing\" or \"ambiguous\", set `where_to_find` to one "
        "short sentence telling the practitioner where this information could be obtained: the kind of source "
        "(e.g. an equipment datasheet or nameplate, the laboratory record of the experiment, the technology "
        "developer, a supplier, a pilot trial, published studies of the same unit operation, the planned "
        "industrial design). For an ambiguous input, say what must be clarified. Never give a value, an estimate "
        "or a range, and never name a specific publication, author or website. For an available input, set "
        "`where_to_find` to null."
    )

    skeleton = build_json_skeleton(ParameterReview)
    for field in COMPUTED_FIELDS:
        skeleton.pop(field, None)
    for field in COMPUTED_PARAMETER_FIELDS:
        skeleton["required_parameters"][0].pop(field, None)
    expected_output = (
        "Return ONLY valid JSON of exactly this structure (`required_parameters` holds one object per input). "
        "No markdown, no code fences, no extra fields.\n\n"
        f"{json.dumps(skeleton, indent=2)}"
    )

    sections = [
        section("ROLE", role),
        section("DEFINITION", AVAILABILITY_DEFINITION),
        section("SELECTED METHOD", dump(entry.human_selected_method.model_dump())),
        section("FLOW", dump(flow)),
        section("TECHNOLOGY OVERVIEW", format_technology_overview(technology)),
        section("LABORATORY PROCESS INVENTORY", dump(_build_process_inventory(technology))),
        section("LAB-DERIVED PARAMETERS", _format_lab_derived_parameters(lab_derived_parameters)),
        section("TASK", task),
        section("EXPECTED OUTPUT", expected_output),
    ]
    return "\n".join(sections)
