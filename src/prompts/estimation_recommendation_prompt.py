"""Prompt construction for the Estimation Recommendation Agent.

Assembles a single plain-text prompt from the confirmed inventory, the
case's unified Laboratory Case Workbook (`laboratory_case_workbook.xlsx`,
loaded by the orchestrator into a `Technology` model plus a list of
lab-derived-parameter rows -- see
`src.tools.laboratory_case_workbook`), the `source_priority` skill, and
the authoritative estimation methods knowledge base
(`src/skills/scaleup_decision_framework.xlsx`). This module performs no
reasoning and makes no LLM calls, and it never fabricates estimation
methods: every candidate shown to the LLM -- and every `method_id` the
LLM may cite -- comes verbatim from that workbook, never from general
LLM knowledge.

Decision flow (per confirmed inventory)
----------------------------------------

The agent's decision process is explicit and traceable, and as much of
it as possible is performed deterministically in Python rather than
left to the LLM to reconstruct from free text:

    confirmed inventory
        -> component classification (already on the inventory)
        -> candidate methods for that component, retrieved from the
           knowledge base (`_candidate_methods_for_component`) --
           component routing is a Python filter, not an LLM search
        -> for tier-3 (linear extrapolation) candidates specifically,
           the applicable basis is pre-computed deterministically via
           `src.tools.linear_extrapolation.apply_linear_extrapolation`
           (`_attach_linear_extrapolation`) -- the LLM is told this
           result directly rather than asked to invent its own scale
           factor
        -> the LLM checks the remaining candidates' applicability
           against the laboratory/lab-derived evidence shown, ranks
           only the applicable ones by tier, and recommends the
           highest-tier applicable one
        -> at most one higher-tier, currently-unavailable candidate is
           optionally reported as worth exploring, with only its
           genuinely missing information

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

Every confirmed inventory's own laboratory quantity (value + unit, read
directly from the Laboratory Case Workbook's process inventory) is
attached to it inside its component group -- this is the fix for the
agent previously claiming laboratory evidence was missing when it had,
in fact, simply never been shown the quantity anywhere in the prompt.
A full LABORATORY PROCESS INVENTORY section (every process's inputs
and outputs, with quantities) is shown separately for evidence a
required_input might need beyond the inventory being evaluated (e.g. a
method's `lab_output_mass` requirement, which is a product output, not
an input).
"""

import json

from src.models.confirmed_inventory import ConfirmedInventoryPackage
from src.models.recommendation import RecommendationPackage
from src.models.technology import Technology
from src.prompts.prompt_helpers import dump, format_technology_overview, section
from src.prompts.schema_skeleton import build_json_skeleton
from src.tools.linear_extrapolation import UNAVAILABLE, apply_linear_extrapolation

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

_LINEAR_EXTRAPOLATION_TIER = 3


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


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _build_laboratory_quantity_lookup(technology: Technology) -> dict[tuple, dict]:
    """Map (process_id, normalized inventory name) -> its lab quantity.

    Built from the process inventory's *input* flows only -- confirmed
    inventories are always foreground inputs (or agent-suggested new
    inventories, which legitimately have no lab quantity yet). This is
    the deterministic lookup that guarantees a confirmed inventory's
    own laboratory value is always attached to it (see
    `_build_component_groups`), rather than requiring the LLM to find
    it itself across a separate section.
    """
    lookup = {}
    for process in technology.processes:
        for flow in process.inputs:
            lookup[(process.id, _normalize_name(flow.name))] = {
                "value": flow.value,
                "unit": flow.unit,
            }
    return lookup


def _attach_linear_extrapolation(
    laboratory_quantity: dict | None,
    candidate_methods: list[dict],
    laboratory_output: float | None,
    industrial_output: float | None,
    functional_unit_defined: bool = False,
) -> dict | None:
    """Deterministically pre-compute tier-3 applicability for one inventory.

    Returns `None` when this inventory's component group has no tier-3
    (linear extrapolation) candidate at all, or when the inventory has
    no laboratory quantity to extrapolate from -- in either case there
    is nothing for `apply_linear_extrapolation` to compute, and the LLM
    is given nothing to (mis)interpret as an invitation to invent one.

    Otherwise, calls `src.tools.linear_extrapolation.apply_linear_extrapolation`
    -- the single source of truth for what a scale factor is and where
    it comes from -- and returns its result as a plain dict the LLM is
    told to use directly for tier-3 applicability, rather than
    reasoning about output/scale-factor availability itself.
    `laboratory_output`/`industrial_output` being unknown never makes
    this `applicable: False` by itself -- Tier 3 falls back to the
    `unchanged_specific_consumption` basis instead, provided
    `functional_unit_defined` is True; see `apply_linear_extrapolation`.
    """
    has_linear_extrapolation_candidate = any(
        row.get("i") == _LINEAR_EXTRAPOLATION_TIER for row in candidate_methods
    )
    if not has_linear_extrapolation_candidate or laboratory_quantity is None:
        return None
    if laboratory_quantity.get("value") is None:
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
        "production_scale_factor": result.production_scale_factor,
        "industrial_input_per_functional_unit": result.industrial_input_per_functional_unit,
        "explanation": result.explanation,
        "missing_information": result.missing_information,
    }


def _build_component_groups(
    confirmed_inventory: ConfirmedInventoryPackage,
    estimation_methods: list[dict],
    laboratory_quantity_lookup: dict[tuple, dict],
    laboratory_output: float | None = None,
    industrial_output: float | None = None,
    functional_unit_defined: bool = False,
) -> list[dict]:
    """Group confirmed inventories by component, each with its own
    pre-filtered candidate list shown exactly once per group.

    Every inventory entry also carries its own `laboratory_quantity` --
    looked up deterministically, never left for the LLM to search for
    -- which is `None` only when the workbook genuinely has no
    quantity for it (e.g. a newly agent-suggested inventory that was
    never measured in the lab) -- and, when the group has a tier-3
    candidate, its own `linear_extrapolation` result (see
    `_attach_linear_extrapolation`).
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
                "laboratory_quantity": laboratory_quantity_lookup.get(
                    (entry.process_id, _normalize_name(entry.inventory_name))
                ),
            }
        )

    groups = []
    for component in component_order:
        candidate_methods = _candidate_methods_for_component(estimation_methods, component)
        inventories = inventories_by_component[component]
        for inventory in inventories:
            inventory["linear_extrapolation"] = _attach_linear_extrapolation(
                inventory["laboratory_quantity"],
                candidate_methods,
                laboratory_output,
                industrial_output,
                functional_unit_defined,
            )
        groups.append(
            {
                "component": component,
                "inventories": inventories,
                "candidate_methods": candidate_methods,
            }
        )
    return groups


def _build_process_inventory(technology: Technology) -> list[dict]:
    """The full laboratory process inventory: every process's inputs
    and outputs, with their reported quantities and units.

    This is the "LABORATORY PROCESS INVENTORY" evidence section --
    broader than the per-group `laboratory_quantity` (which only covers
    each group's own confirmed inventories): it also exposes process
    outputs, since a candidate method's required_inputs may reference a
    product output (e.g. `lab_output_mass`) rather than an input.
    """
    return [
        {
            "process_id": process.id,
            "process_name": process.name,
            "process_type": process.process_type,
            "note": process.note,
            "depends_on": process.depends_on,
            "inputs": [
                {"name": flow.name, "value": flow.value, "unit": flow.unit}
                for flow in process.inputs
            ],
            "outputs": [
                {"name": flow.name, "value": flow.value, "unit": flow.unit}
                for flow in process.outputs
            ],
        }
        for process in technology.processes
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
        technology: The full Technology model for the case, read from
            the Laboratory Case Workbook's Technology Overview and
            Process Inventory worksheets. Supplies both process context
            and the quantitative laboratory evidence (input/output
            values and units) this agent must check before ever
            reporting information as unavailable, plus
            `current_state.throughput` / `target_state.throughput`
            (laboratory/industrial production output) used to
            pre-compute tier-3 linear-extrapolation applicability.
        confirmed_inventory: The human-confirmed inventory to recommend
            estimation methods for.
        estimation_methods: Every row of
            `src/skills/scaleup_decision_framework.xlsx`, as loaded by
            `src.tools.excel_table_loader.load_excel_table`. The
            authoritative estimation-method knowledge base -- the
            framework's built-in engineering knowledge.
        lab_derived_parameters: Rows from the Laboratory Case
            Workbook's "Lab-Derived Parameters" worksheet.
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
        "the final estimation method. The agent answers 'given what we "
        "know about this specific inventory, which method from this "
        "component's predefined method set can we actually apply now, "
        "and what is the best more-representative method we could "
        "explore with additional information?' -- not 'what estimation "
        "method seems best in general?'"
    )

    laboratory_quantity_lookup = _build_laboratory_quantity_lookup(technology)
    functional_unit_defined = bool((technology.technology.functional_unit or "").strip())
    component_groups = _build_component_groups(
        confirmed_inventory,
        estimation_methods,
        laboratory_quantity_lookup,
        laboratory_output=technology.current_state.throughput,
        industrial_output=technology.target_state.throughput,
        functional_unit_defined=functional_unit_defined,
    )
    process_inventory = _build_process_inventory(technology)

    task = (
        "DECISION FLOW: for every inventory, in every group below, follow "
        "this exact sequence -- do not start by searching across all "
        "estimation methods; start from the inventory and its "
        "component.\n\n"
        "EVIDENCE PRIORITY: use, in this order -- (1) the user's own "
        "laboratory evidence (LABORATORY PROCESS INVENTORY and "
        "LAB-DERIVED PARAMETERS below), (2) the framework's built-in "
        "engineering knowledge (the candidate_methods shown in each "
        "group below, and SOURCE PRIORITY), (3) other evidence per "
        "SOURCE PRIORITY's hierarchy, and only last, (4) general "
        "internal knowledge, when nothing stronger applies. Never make "
        "a recommendation from general knowledge alone when the "
        "workbook or the knowledge base already answers the "
        "question -- and always say which of these you relied on in "
        "recommendation_rationale.\n\n"
        "CHECKING AVAILABILITY: before treating any required_inputs "
        "item as unavailable, check BOTH LABORATORY PROCESS INVENTORY "
        "(every process's inputs and outputs, with quantities) and "
        "LAB-DERIVED PARAMETERS (extracted or calculated parameters) -- "
        "an inventory's own laboratory_quantity, attached to it in "
        "COMPONENT GROUPS AND CANDIDATE METHODS below, is also drawn "
        "directly from LABORATORY PROCESS INVENTORY. Only report "
        "information as missing when it is genuinely absent from both; "
        "never invent a value, and never claim something is missing "
        "when it is present under a slightly different label -- check "
        "the process's full input and output list before concluding "
        "otherwise.\n\n"
        "COMPONENT ROUTING: COMPONENT GROUPS AND CANDIDATE METHODS below "
        "groups every confirmed inventory by component -- this grouping "
        "is the routing step and has already been done in Python. Each "
        "group's candidate_methods list has already been filtered to "
        "only the estimation methods for that one component -- do not "
        "consider any other group's methods for an inventory, and do "
        "not search for candidates anywhere else. Every inventory "
        "listed in a group's inventories list shares that group's "
        "candidate_methods.\n\n"
        "LINEAR EXTRAPOLATION (tier 3): where an inventory's entry "
        "includes a linear_extrapolation object, that result has "
        "already been computed deterministically (see "
        "src/tools/linear_extrapolation.py) -- use its \"applicable\" "
        "flag, \"basis\", and \"explanation\" directly for that "
        "inventory's tier-3 candidate rather than judging its "
        "applicability yourself or inventing your own scale-factor "
        "reasoning. There are three possible bases, and a missing "
        "laboratory/industrial production output never makes tier 3 "
        "inapplicable by itself:\n"
        "  - derived_from_outputs: a production_scale_factor was "
        "derived from known laboratory and industrial outputs.\n"
        "  - unchanged_specific_consumption: a production_scale_factor "
        "could NOT be derived (one or both outputs are unknown), but "
        "tier 3 remains applicable -- laboratory-specific consumption "
        "per functional unit is assumed unchanged at industrial scale. "
        "Never describe this basis as \"scale factor = 1\"; it is an "
        "explicit assumption, not a derived physical ratio.\n"
        "  - already_normalized_to_FU: the inventory is already "
        "expressed per functional unit; no output-based scaling is "
        "needed at all.\n"
        "\"applicable\" is only False when basis is \"unavailable\" -- "
        "a genuinely rare case, distinct from the two bullets above. "
        "When \"applicable\" is true, treat this inventory's tier-3 "
        "candidate as applicable and never write a rationale that "
        "contradicts it: if you recommend a tier-3 method, never also "
        "say linear extrapolation \"is not applicable\" or that it "
        "fails due to a missing production output -- instead say, if "
        "relevant, that \"a derived production scale factor could not "
        "be calculated, so tier 3 remains applicable under the "
        "unchanged-specific-consumption assumption\" (the explanation "
        "field already phrases it exactly this way; you may reuse it). "
        "A missing linear_extrapolation object (null) means this "
        "inventory has no tier-3 candidate or no laboratory quantity to "
        "extrapolate from -- not that tier 3 was judged inapplicable.\n\n"
        "For every inventory, in every group:\n\n"
        "1. EVALUATE APPLICABILITY: for each of its group's candidates, "
        "compare required_inputs and trigger_condition against the "
        "information actually available from the inventory's own "
        "laboratory_quantity (and linear_extrapolation, for tier 3), "
        "LABORATORY PROCESS INVENTORY, LAB-DERIVED PARAMETERS, "
        "TECHNOLOGY OVERVIEW, and SOURCE PRIORITY. A method is only "
        "applicable if the information it requires is genuinely "
        "available now. Do not treat tier 1 (omission/cut-off) as "
        "applicable by default merely because it is the lowest tier -- "
        "it is applicable only when its own trigger_condition is "
        "genuinely satisfied, exactly like every other tier.\n\n"
        "2. RECOMMEND: each candidate's \"i\" is its tier (1 = omission "
        "/ cut-off, the least representative, through 6 = engineering "
        "equation, the most representative). Rank ONLY the candidates "
        "you judged applicable in step 1 by tier, and set "
        "recommended_method to the highest-tier one among them -- never "
        "a candidate you judged inapplicable, regardless of its tier -- "
        "copying method_id, method_name, and tier_name verbatim. Explain "
        "the choice in recommendation_rationale: state why it is "
        "applicable (which evidence made it so) and, briefly, why no "
        "higher-tier candidate is currently applicable. Do not merely "
        "restate the method's name as the rationale. If none of this "
        "inventory's candidates are applicable, set recommended_method "
        "to null and explain why -- including exactly what evidence is "
        "missing -- in recommendation_rationale. Do not include a "
        "numerical confidence score anywhere in the output.\n\n"
        "3. OPTIONAL MORE REPRESENTATIVE METHOD: identify AT MOST ONE "
        "higher-tier candidate in the same group that is not currently "
        "applicable but could realistically become applicable with "
        "additional information -- the single most relevant one, not "
        "every unavailable higher-tier candidate. Set "
        "more_representative_method to it (copied the same way, "
        "including tier_name) and list in "
        "additional_information_required only the specific information "
        "genuinely missing -- checked against LABORATORY PROCESS "
        "INVENTORY and LAB-DERIVED PARAMETERS first -- for example: "
        "equipment power rating, operating time, reactor dimensions, "
        "reactor material, insulation information, heat transfer "
        "coefficient, material properties, equipment specifications, "
        "process simulation results. Do not populate this field merely "
        "because a higher tier exists in the group; if no such method "
        "is realistically worth exploring, set more_representative_method "
        "to null and additional_information_required to the literal "
        'string "None".\n\n'
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
        "object of exactly this shape, with method_id, method_name, and "
        "tier_name all copied verbatim from one of that inventory's "
        "candidates (tier_name will also be independently verified "
        "against the knowledge base afterward, so copy it accurately "
        "rather than leaving it blank), never a bare method-name "
        "string, and never a newly invented method_id:\n"
        '{"method_id": "<copied from a candidate>", '
        '"method_name": "<copied from a candidate>", '
        '"tier_name": "<copied from a candidate>"}\n\n'
        "Do not:\n"
        "- rename fields\n"
        "- remove fields\n"
        "- add fields (including a confidence score)\n"
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
        section("LABORATORY PROCESS INVENTORY", dump(process_inventory)),
        section("COMPONENT GROUPS AND CANDIDATE METHODS", dump(component_groups)),
        section(
            "LAB-DERIVED PARAMETERS",
            _format_lab_derived_parameters(lab_derived_parameters),
        ),
        section("TASK", task),
        section("EXPECTED OUTPUT", expected_output),
    ]

    return "\n".join(sections)
