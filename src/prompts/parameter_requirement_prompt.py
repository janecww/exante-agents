"""Prompt construction for the Parameter Requirement Agent.

Assembles a single plain-text prompt for one inventory's human-selected
estimation method (`ReviewedRecommendationEntry.human_selected_method`,
see `src.models.reviewed_recommendation`). This module performs no
reasoning and makes no LLM calls.

Reuses the case's laboratory evidence exactly as
`src.prompts.estimation_recommendation_prompt` already represents it
(`_build_laboratory_quantity_lookup`, `_build_process_inventory`,
`_format_lab_derived_parameters`, `_normalize_name`) rather than
re-deriving a second representation of the same workbook data -- this
agent needs the identical evidence sections, just for one already-
selected method instead of a component's whole candidate list.

Milestone 1 scope: this agent's only task is to determine what
information the human's already-selected method needs and whether the
case's existing evidence already supplies it. It must never be asked
to reconsider, replace, or evaluate alternatives to that selection, and
it must never perform the scale-up calculation itself -- both are
explicitly out of scope here and left to a later milestone.
"""

import json

from src.models.parameter_review import ParameterReview
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


def build_parameter_requirement_prompt(
    technology: Technology,
    lab_derived_parameters: list[dict],
    entry: ReviewedRecommendationEntry,
) -> str:
    """Build the Parameter Requirement Agent prompt for one selected method.

    Args:
        technology: The full Technology model for the case, supplying
            both process context and the quantitative laboratory
            evidence this agent must check before ever reporting a
            parameter as missing.
        lab_derived_parameters: Rows from the Laboratory Case
            Workbook's "Lab-Derived Parameters" worksheet.
        entry: The reviewed recommendation entry for one inventory,
            with `human_selected_method` populated -- the full method
            definition retrieved from the knowledge base by
            `src.tools.import_estimation_recommendations`.

    Returns:
        A single plain-text prompt string (no chat/message formatting).

    Raises:
        ValueError: if `entry.human_selected_method` is `None`. This
            agent must never be invoked for an inventory the human has
            not selected a method for (Milestone 1, section 3: "do not
            invoke the parameter-requirement agent for that inventory").
    """
    if entry.human_selected_method is None:
        raise ValueError(
            "Parameter Requirement Agent requires a human-selected method; "
            f"Process ID {entry.process_id!r} / Inventory "
            f"{entry.inventory_name!r} has none."
        )

    role = (
        "The Parameter Requirement Agent determines, for one inventory's "
        "already human-selected estimation method, what information that "
        "method needs and whether the case's existing evidence already "
        "supplies it. The human's selection is final and authoritative: "
        "never propose a different method, never suggest the human "
        "reconsider, and never evaluate whether some other candidate "
        "would be better. This agent also does not perform the scale-up "
        "calculation itself -- it only determines whether enough "
        "information exists to attempt it later."
    )

    laboratory_quantity_lookup = _build_laboratory_quantity_lookup(technology)
    laboratory_quantity = laboratory_quantity_lookup.get(
        (entry.process_id, _normalize_name(entry.inventory_name))
    )
    process_inventory = _build_process_inventory(technology)

    inventory_context = {
        "process_id": entry.process_id,
        "process_name": entry.process_name,
        "inventory_name": entry.inventory_name,
        "component": entry.component,
        "laboratory_quantity": laboratory_quantity,
    }

    task = (
        "SELECTED METHOD below is the human's final decision for this "
        "inventory -- treat it as given, not as something to evaluate or "
        "second-guess.\n\n"
        "1. REQUIRED PARAMETERS: derive the parameters actually needed to "
        "apply this method and, later, perform its scale-up calculation, "
        "from -- in order of relevance -- (1) its required_inputs (the "
        "primary source), (2) rule_or_equation, (3) applies_when, "
        "(4) produces, (5) assumptions_to_log, (6) escalate_if, and "
        "(7) limitations, wherever any of these name a specific input or "
        "condition. Do not invent parameters unrelated to this method's "
        "own definition -- required_inputs is authoritative for *which* "
        "parameters are needed; the other fields only help you understand "
        "them, they never add new ones.\n\n"
        "2. CHECK AVAILABILITY: for every required parameter, check -- in "
        "this order -- (a) this inventory's own laboratory_quantity "
        "(shown in INVENTORY below), (b) LABORATORY PROCESS INVENTORY "
        "(every process's inputs and outputs, with quantities), "
        "(c) LAB-DERIVED PARAMETERS, and (d) TECHNOLOGY OVERVIEW. "
        "Parameter names may differ between the method's definition and "
        "the workbook -- use reasonable semantic matching: for example, "
        "do not declare \"reactor output mass\" missing merely because "
        "the workbook calls it \"product mass\". If the evidence contains "
        "a parameter under a different but clearly equivalent name, "
        "treat it as available and record the actual field/name you "
        "matched it to in source. Never claim a parameter is missing "
        "without having checked all four of these first, and never "
        "invent, estimate, or approximate a numeric value for a "
        "parameter you cannot actually find.\n\n"
        "3. RECORD EACH PARAMETER: for every required parameter, set "
        "status to \"available\" or \"missing\". When available, set "
        "value and unit to what you found (copied, never invented) and "
        "source to where you found it (e.g. \"Laboratory Process "
        "Inventory: P01 water input\" or \"Lab-Derived Parameters: "
        "m_mix\"). When missing, set value, unit, and source to null -- "
        "never a placeholder or an estimate. If, while missing, you find "
        "a semantically related value that cannot be used as-is (most "
        "commonly a unit mismatch, e.g. a quantity reported in litres "
        "when this parameter needs kg, with no density value available "
        "to convert it), still set value/unit/source to null -- do not "
        "invent a converted number -- but set note to name what you "
        "found and why it could not be used (e.g. \"Laboratory Process "
        "Inventory: P02 water input = 15.61 L; converting to kg requires "
        "a density value, which is not available in this case's "
        "evidence\"). Leave note null whenever nothing related was found "
        "at all, or whenever status is \"available\".\n\n"
        "Do not calculate the industrial quantity, perform linear "
        "extrapolation, apply a scaling factor, estimate any missing "
        "value, select a different method, or override the human's "
        "selection -- all of that belongs to a later stage. Do not "
        "include a numerical confidence score anywhere in the output. "
        "missing_parameters and calculation_readiness will be "
        "recomputed deterministically from required_parameters after "
        "you respond, so focus on getting each parameter's own status "
        "right rather than these two summary fields.\n\n"
        "Populate the JSON structure shown in EXPECTED OUTPUT below."
    )

    skeleton = build_json_skeleton(ParameterReview)

    expected_output = (
        "Below is the exact JSON structure expected. Copy this structure "
        "exactly. Populate values only.\n\n"
        "Do not:\n"
        "- rename fields\n"
        "- remove fields\n"
        "- add fields (including a confidence score)\n"
        "- replace lists with dictionaries\n\n"
        "Return ONLY valid JSON. Do not include markdown, explanations, or "
        "code fences.\n\n"
        f"{json.dumps(skeleton, indent=2)}"
    )

    sections = [
        section("ROLE", role),
        section("SELECTED METHOD", dump(entry.human_selected_method.model_dump())),
        section("INVENTORY", dump(inventory_context)),
        section("TECHNOLOGY OVERVIEW", format_technology_overview(technology)),
        section("LABORATORY PROCESS INVENTORY", dump(process_inventory)),
        section(
            "LAB-DERIVED PARAMETERS",
            _format_lab_derived_parameters(lab_derived_parameters),
        ),
        section("TASK", task),
        section("EXPECTED OUTPUT", expected_output),
    ]

    return "\n".join(sections)
