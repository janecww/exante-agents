"""Prompt construction for the Estimation Recommendation Agent.

Assembles a single plain-text prompt from the confirmed inventory, the
technology context, the case's lab-derived parameters (if available),
the `source_priority` skill, and the authoritative estimation methods
knowledge base (`src/skills/scaleup_decision_framework.xlsx`). This
module performs no reasoning and makes no LLM calls, and it never
fabricates estimation methods: every candidate shown to the LLM -- and
every `method_id` the LLM may cite -- comes verbatim from that
workbook, never from general LLM knowledge.

Candidate methods are filtered by component entirely in Python before
the prompt is built (see `_candidate_methods_for_component` /
`_build_component_groups`): every confirmed inventory is grouped with
the other inventories sharing its component, and each group is paired
with only the estimation methods for that one component (e.g. an
"energy" group sees only `ENER-*` rows, never `CAT-*`/`SOLV-*`/
`REACT-*`/`HEAT-*`). The LLM therefore never searches across unrelated
components for any inventory -- it only evaluates the methods it has
already been given for that inventory's group. Grouping by component
(rather than repeating each candidate list once per inventory) also
keeps the prompt from scaling with inventory count: a technology with
several "energy" inventories (e.g. electricity used in five different
processes) shows the `ENER-*` candidates once, not once per inventory.
"""

import json

from src.models.confirmed_inventory import ConfirmedInventoryPackage
from src.models.recommendation import RecommendationPackage
from src.models.technology import Technology
from src.prompts.prompt_helpers import (
    dump,
    extract_process_context,
    format_technology_overview,
    section,
)
from src.prompts.schema_skeleton import build_json_skeleton

# Columns of scaleup_decision_framework.xlsx shown per candidate.
# "component" is omitted: every candidate list is already scoped to one
# component group, so restating it on every row would be pure
# repetition. Citation metadata (reference, provenance, url) is
# omitted too: it plays no role in applicability or representativeness.
_METHOD_TABLE_COLUMNS = [
    "i",
    "tier_name",
    "method_id",
    "method_name",
    "rule_or_equation",
    "required_inputs",
    "trigger_condition",
    "produces",
    "assumptions_to_log",
    "limitations",
]


def _normalize_component(component: str | None) -> str:
    """Loosely normalize a component label for matching purposes.

    The estimation methods knowledge base uses plural component labels
    for some categories ("reactants", "solvents") and singular for
    others ("catalyst", "heat", "energy"), while
    `ConfirmedInventoryEntry.component` always uses the singular
    category name. Stripping a trailing "s" makes both sides
    comparable without hardcoding every label pair.
    """
    normalized = (component or "").strip().lower()
    return normalized[:-1] if normalized.endswith("s") else normalized


def _candidate_methods_for_component(
    estimation_methods: list[dict], component: str | None
) -> list[dict]:
    """Every knowledge-base row matching one component, tier-ordered.

    This is the only filtering performed in code, and it is applied
    once per component group (see `_build_component_groups`) rather
    than once per whole confirmed inventory package -- a group's
    candidate list contains only methods for its own component.
    """
    normalized = _normalize_component(component)
    candidates = [
        {column: row.get(column) for column in _METHOD_TABLE_COLUMNS}
        for row in estimation_methods
        if _normalize_component(row.get("component")) == normalized
    ]
    return sorted(candidates, key=lambda row: row.get("i") or 0)


def _build_component_groups(
    confirmed_inventory: ConfirmedInventoryPackage, estimation_methods: list[dict]
) -> list[dict]:
    """Group confirmed inventories by component, each with its own
    pre-filtered candidate list shown exactly once per group.
    """
    inventories_by_component: dict[str | None, list[dict]] = {}
    component_order: list[str | None] = []

    for entry in confirmed_inventory.inventories:
        if entry.component not in inventories_by_component:
            inventories_by_component[entry.component] = []
            component_order.append(entry.component)
        inventories_by_component[entry.component].append(
            {
                "process_id": entry.process_id,
                "process_name": entry.process_name,
                "inventory_name": entry.inventory_name,
            }
        )

    return [
        {
            "component": component,
            "inventories": inventories_by_component[component],
            "candidate_methods": _candidate_methods_for_component(
                estimation_methods, component
            ),
        }
        for component in component_order
    ]


def _format_lab_derived_parameters(lab_derived_parameters: list[dict]) -> str:
    if not lab_derived_parameters:
        return "(no lab-derived parameters supplied for this case)"
    return dump(lab_derived_parameters)


def build_estimation_recommendation_prompt(
    technology: Technology,
    confirmed_inventory: ConfirmedInventoryPackage,
    estimation_methods: list[dict],
    lab_derived_parameters: list[dict],
    skills: dict,
) -> str:
    """Build the Estimation Recommendation Agent prompt.

    Args:
        technology: The full Technology model for the case (used only
            for process context: type, note, existing inputs).
        confirmed_inventory: The human-confirmed inventory to recommend
            estimation methods for.
        estimation_methods: Every row of
            `src/skills/scaleup_decision_framework.xlsx`, as loaded by
            `src.tools.excel_table_loader.load_excel_table`. The
            authoritative estimation-method knowledge base.
        lab_derived_parameters: Rows of the case's
            `references/lab_derived_parameters.xlsx`, if available for
            this case, else an empty list.
        skills: Dictionary of shared Stage 1 skills, keyed by skill
            name. Only `source_priority` is used.

    Returns:
        A single plain-text prompt string (no chat/message formatting).
    """
    role = (
        "The Estimation Recommendation Agent recommends, for every "
        "confirmed foreground inventory, the most appropriate "
        "estimation method that can currently be applied, explains why, "
        "and -- where a more representative method exists but cannot "
        "yet be applied -- reports what additional information it "
        "would require. The human remains responsible for selecting "
        "the final estimation method."
    )

    component_groups = _build_component_groups(confirmed_inventory, estimation_methods)

    task = (
        "COMPONENT GROUPS AND CANDIDATE METHODS above groups every "
        "confirmed inventory by component. Each group's "
        "candidate_methods list has already been filtered in Python to "
        "only the estimation methods for that one component -- do not "
        "consider any other group's methods for an inventory, and do "
        "not search for candidates anywhere else. Every inventory "
        "listed in a group's inventories list shares that group's "
        "candidate_methods.\n\n"
        "For every inventory, in every group:\n\n"
        "1. EVALUATE APPLICABILITY: for each of its group's candidates, "
        "compare required_inputs and trigger_condition against the "
        "information actually available from TECHNOLOGY OVERVIEW, "
        "LABORATORY PROCESS CONTEXT, LAB-DERIVED PARAMETERS, and SOURCE "
        "PRIORITY. A method is only applicable if the information it "
        "requires is genuinely available now.\n\n"
        "2. RECOMMEND: each candidate's \"i\" is its tier (1 = omission "
        "/ cut-off, the least representative, through 6 = engineering "
        "equation, the most representative). Among the applicable "
        "candidates, set recommended_method to the highest-tier one -- "
        "copying method_id and method_name verbatim -- and explain the "
        "choice concisely in recommendation_rationale. If none of this "
        "inventory's candidates are applicable, set recommended_method "
        "to null and explain why in recommendation_rationale.\n\n"
        "3. MORE REPRESENTATIVE METHOD: if a higher-tier candidate in "
        "the same group is not currently applicable, set "
        "more_representative_method to it (copied the same way) and "
        "list in additional_information_required only the specific "
        "information genuinely missing (for example: equipment power "
        "rating, operating time, reactor dimensions, reactor material, "
        "insulation information, heat transfer coefficient, material "
        "properties, equipment specifications, process simulation "
        "results). Otherwise set more_representative_method to null and "
        "additional_information_required to the literal string "
        '"None".\n\n'
        "Populate the JSON structure shown in EXPECTED OUTPUT below "
        "with exactly one entry per inventory across all groups, in "
        "the same order as they appear above."
    )

    skeleton = build_json_skeleton(RecommendationPackage)
    # recommended_method / more_representative_method are Optional
    # nested objects, so the generic skeleton generator always expands
    # them into a populated example -- but "no method applies" (a
    # common, important case) must be represented as the JSON literal
    # null, never as an object with empty or "null"-string fields. This
    # is the exact template to copy, so it shows null directly; the
    # populated shape is shown separately below, clearly as an
    # illustration rather than something to copy verbatim.
    skeleton["recommendations"][0]["recommended_method"] = None
    skeleton["recommendations"][0]["more_representative_method"] = None

    expected_output = (
        "Below is the exact JSON structure expected. Copy this structure "
        "exactly. Populate values only.\n\n"
        "recommended_method and more_representative_method are shown as "
        "null here because that is the exact value to use whenever no "
        "such method exists for an inventory -- not the string \"null\", "
        "not an empty string, and not an object containing null or "
        'empty fields. When a method does exist, replace null with an '
        "object of exactly this shape, with method_id and method_name "
        "copied verbatim from one of that inventory's candidates:\n"
        '{"method_id": "<copied from a candidate>", '
        '"method_name": "<copied from a candidate>"}\n\n'
        "Do not:\n"
        "- rename fields\n"
        "- remove fields\n"
        "- add fields\n"
        "- replace a populated method object with a bare string\n"
        "- replace lists with dictionaries\n\n"
        "Return ONLY valid JSON. Do not include markdown, explanations, or "
        "code fences.\n\n"
        f"{json.dumps(skeleton, indent=2)}"
    )

    sections = [
        section("ROLE", role),
        section(
            "AVAILABLE KNOWLEDGE",
            f"Source Priority\n\n{dump(skills.get('source_priority') or {})}",
        ),
        section("TECHNOLOGY OVERVIEW", format_technology_overview(technology)),
        section(
            "LABORATORY PROCESS CONTEXT", dump(extract_process_context(technology))
        ),
        section("COMPONENT GROUPS AND CANDIDATE METHODS", dump(component_groups)),
        section(
            "LAB-DERIVED PARAMETERS",
            _format_lab_derived_parameters(lab_derived_parameters),
        ),
        section("TASK", task),
        section("EXPECTED OUTPUT", expected_output),
    ]

    return "\n".join(sections)
