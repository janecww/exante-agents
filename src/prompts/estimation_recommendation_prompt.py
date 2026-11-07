"""Prompt construction for the Estimation Recommendation step (one flow per call).

For each confirmed flow, the language model is shown the flow, the case
evidence (with each value's Provenance), the candidate rules of the flow's
category, and the shared definition of "available"
(`src.skills.availability.AVAILABILITY_DEFINITION`, identical in the
Parameter Identification prompt). It returns a `FlowAssessment`: for every
candidate, whether the rule's operations and conditions apply, and the
status of every input. It does NOT rank or recommend: the code does that
from the assessment (`src.tools.method_ranking.rank_candidates`), so the
recommendation and its rationale can never contradict the assessment.

Done in code before the prompt is built:
- Filter 1, component routing: only the rules of the flow's category are
  candidates (`candidate_rows_for_component`).
- Tier 3: whether the flow's laboratory quantity can be linearly
  extrapolated (`src.tools.linear_extrapolation`), shown to the model and
  enforced again by the ranking.

Only the agent-facing `rules` columns are shown; the `documentation` sheet
is never part of a prompt. The `source_priority` skill is not used here:
it ranks literature and the model's own knowledge as fallback evidence,
which the definition of "available" excludes.
"""

import json

from src.models.confirmed_inventory import ConfirmedInventoryEntry, ConfirmedInventoryPackage
from src.models.recommendation import FlowAssessment
from src.models.technology import Technology
from src.prompts.prompt_helpers import dump, format_technology_overview, section
from src.prompts.schema_skeleton import build_json_skeleton
from src.skills.availability import AVAILABILITY_DEFINITION
from src.tools.linear_extrapolation import UNAVAILABLE, apply_linear_extrapolation

# The rule columns shown to the model, per candidate. `component` is
# omitted (all candidates share the flow's category); `produces` is
# omitted (the same for every rule of a category).
PROMPT_RULE_COLUMNS = [
    "tier",
    "method_id",
    "method_name",
    "scope",
    "operations",
    "conditions",
    "rule_or_equation",
    "inputs",
    "depends_on",
]

_LINEAR_EXTRAPOLATION_TIER = 3


def _normalize_component(component: str | None) -> str:
    """Match "Solvents"/"solvent", "Reactants"/"reactant", etc."""
    normalized = (component or "").strip().lower()
    return normalized[:-1] if normalized.endswith("s") else normalized


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def candidate_rows_for_component(estimation_methods: list[dict], component: str | None) -> list[dict]:
    """Every framework row of one category, in framework order (Filter 1)."""
    normalized = _normalize_component(component)
    return [row for row in estimation_methods if _normalize_component(row.get("component")) == normalized]


def _build_laboratory_quantity_lookup(technology: Technology) -> dict[tuple, dict]:
    """(process_id, normalized inventory name) -> its laboratory quantity."""
    lookup = {}
    for process in technology.processes:
        for flow in process.inputs:
            lookup[(process.id, _normalize_name(flow.name))] = {
                "value": flow.value,
                "unit": flow.unit,
                "provenance": flow.provenance,
            }
    return lookup


def _linear_extrapolation(
    laboratory_quantity: dict | None,
    candidate_rows: list[dict],
    laboratory_output: float | None,
    industrial_output: float | None,
    functional_unit_defined: bool,
) -> dict | None:
    """The code's Tier 3 result for one flow, or None when the category has
    no Tier 3 rule or the flow has no laboratory quantity."""
    if not any(row.get("tier") == _LINEAR_EXTRAPOLATION_TIER for row in candidate_rows):
        return None
    if laboratory_quantity is None or laboratory_quantity.get("value") is None:
        return None
    result = apply_linear_extrapolation(
        laboratory_quantity["value"],
        laboratory_output=laboratory_output,
        industrial_output=industrial_output,
        functional_unit_defined=functional_unit_defined,
    )
    return {
        "applicable": result.basis != UNAVAILABLE,
        "basis": result.basis,
        "explanation": result.explanation,
        "missing_information": result.missing_information,
    }


def prepare_flow_contexts(
    technology: Technology,
    confirmed_inventory: ConfirmedInventoryPackage,
    estimation_methods: list[dict],
) -> list[dict]:
    """Per confirmed flow: the flow, its candidate rows, its laboratory
    quantity and the code's Tier 3 result -- everything the prompt and the
    ranking need, computed once."""
    lookup = _build_laboratory_quantity_lookup(technology)
    functional_unit_defined = bool((technology.technology.functional_unit or "").strip())
    processes = {process.id: process for process in technology.processes}
    contexts = []
    for entry in confirmed_inventory.inventories:
        candidate_rows = candidate_rows_for_component(estimation_methods, entry.component)
        laboratory_quantity = lookup.get((entry.process_id, _normalize_name(entry.inventory_name)))
        process = processes.get(entry.process_id)
        contexts.append(
            {
                "flow": {
                    "process_id": entry.process_id,
                    "process_name": entry.process_name,
                    "process_type": process.process_type if process else None,
                    "process_note": process.note if process else None,
                    "inventory_name": entry.inventory_name,
                    "component": entry.component,
                },
                "entry": entry,
                "candidate_rows": candidate_rows,
                "laboratory_quantity": laboratory_quantity,
                "linear_extrapolation": _linear_extrapolation(
                    laboratory_quantity,
                    candidate_rows,
                    technology.current_state.throughput,
                    technology.target_state.throughput,
                    functional_unit_defined,
                ),
            }
        )
    return contexts


def _build_process_inventory(technology: Technology) -> list[dict]:
    """Every process's inputs and outputs, with value, unit and Provenance."""
    return [
        {
            "process_id": process.id,
            "process_name": process.name,
            "process_type": process.process_type,
            "note": process.note,
            "depends_on": process.depends_on,
            "inputs": [
                {"name": flow.name, "value": flow.value, "unit": flow.unit, "provenance": flow.provenance}
                for flow in process.inputs
            ],
            "outputs": [
                {"name": flow.name, "value": flow.value, "unit": flow.unit, "provenance": flow.provenance}
                for flow in process.outputs
            ],
        }
        for process in technology.processes
    ]


def _format_lab_derived_parameters(lab_derived_parameters: list[dict]) -> str:
    if not lab_derived_parameters:
        return "(no lab-derived parameters supplied for this case)"
    return dump(lab_derived_parameters)


def format_rules_for_prompt(rows: list[dict]) -> str:
    return dump([{column: row.get(column) for column in PROMPT_RULE_COLUMNS} for row in rows])


def build_flow_assessment_prompt(
    technology: Technology,
    context: dict,
    lab_derived_parameters: list[dict],
) -> str:
    """The prompt for one flow (see module docstring)."""
    flow = dict(context["flow"])
    flow["laboratory_quantity"] = context["laboratory_quantity"]
    flow["linear_extrapolation (computed by code)"] = context["linear_extrapolation"]

    role = (
        "You assess, for ONE inventory flow of an ex-ante LCA case, which scale-up rules of the flow's category "
        "can be applied with the case's evidence. You do not choose or rank a method: the code ranks the rules "
        "from your assessment. Apply the DEFINITION OF \"AVAILABLE\" below exactly; it is the same definition the "
        "Parameter Identification agent uses later, and the two results are compared."
    )

    task = (
        "Assess EVERY rule listed in CANDIDATE RULES, in the order listed, and return one entry per rule in "
        "`candidates` (method_id copied exactly).\n\n"
        "1. operation_match: for a rule with scope \"generic\", true. For a rule with scope \"named\", true only if "
        "the flow's process step (FLOW: process_name, process_type, process_note) is one of the rule's "
        "`operations` (an equivalent wording counts, e.g. \"stirring\" for \"agitation\"); otherwise false. Give "
        "a short reason in operation_note.\n"
        "2. conditions_met: null if the rule has no `conditions`. Otherwise true or false, judged from the case "
        "evidence and the flow's process step; give a short reason in conditions_note.\n"
        "3. inputs: if operation_match is false, return an empty list. Otherwise one entry for EVERY input in the "
        "rule's `inputs`, using exactly the input names given there, in the same order. Set `tag` to the tag "
        "shown in brackets. Set `status`, `value`, `unit`, `source`, `derivation` and `note` following the "
        "DEFINITION OF \"AVAILABLE\". For [DEFAULT=...] inputs, status is \"available\" and value is the default. "
        "For [TARGET] inputs, status is \"missing\" unless the evidence states the value.\n\n"
        "Tier 3 rules: whether this flow's laboratory quantity can be extrapolated was computed by code and is "
        "shown in FLOW as linear_extrapolation. Report the rule's laboratory-quantity input from that result.\n\n"
        "Do not add rules, inputs or fields. Do not recommend or rank. Never write a value that is not in the "
        "evidence, a stated default, a standard physical constant, or the result of an allowed derivation."
    )

    skeleton = build_json_skeleton(FlowAssessment)
    expected_output = (
        "Return ONLY valid JSON of exactly this structure (one object in `candidates` per candidate rule; "
        "`inputs` may hold several objects). No markdown, no code fences, no extra fields.\n\n"
        f"{json.dumps(skeleton, indent=2)}"
    )

    sections = [
        section("ROLE", role),
        section("DEFINITION", AVAILABILITY_DEFINITION),
        section("FLOW", dump(flow)),
        section("CANDIDATE RULES", format_rules_for_prompt(context["candidate_rows"])),
        section("TECHNOLOGY OVERVIEW", format_technology_overview(technology)),
        section("LABORATORY PROCESS INVENTORY", dump(_build_process_inventory(technology))),
        section("LAB-DERIVED PARAMETERS", _format_lab_derived_parameters(lab_derived_parameters)),
        section("TASK", task),
        section("EXPECTED OUTPUT", expected_output),
    ]
    return "\n".join(sections)
