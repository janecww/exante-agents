"""Deterministic ranking of candidate rules for one flow.

The language model assesses every candidate rule of a flow's category
(operation match, conditions, and the status of every input under the
shared definition of "available", `src.skills.availability`). This
module turns those assessments into the recommendation, so the choice of
method and the rationale shown to the practitioner can never contradict
the assessments they come from:

- a rule is ELIGIBLE when its operations match the flow (generic rules
  always match) and its conditions hold (rules without conditions always
  hold);
- a rule is AVAILABLE when it is eligible and every input tagged LAB,
  CONSTANT, DEFAULT or LITERATURE is "available" (TARGET inputs never
  count). For Tier 3, the code's own linear-extrapolation result
  (`src.tools.linear_extrapolation`) decides whether the laboratory
  quantity can be extrapolated, not the model;
- RECOMMENDED = the available rule with the highest tier (ties: the rule
  listed first in the framework);
- ALTERNATIVE = among eligible rules of higher tier than the recommended
  one that are not available, the one with the fewest missing or
  ambiguous inputs (ties: the higher tier, then framework order); the
  others are listed with what each is missing;
- SAME- OR LOWER-TIER = the other eligible rules at or below the
  recommended tier, each "available" or with what it is missing;
- NOT APPLICABLE = rules whose operation does not match or whose
  conditions do not hold, with the model's reason. Every group is
  selectable.

Checks recorded on the entry (`checks`) instead of stopping the run,
because each has a conservative fallback:
- C3: the model's Tier 3 laboratory-quantity status disagrees with the
  code's linear-extrapolation result (the code wins);
- C4: a candidate or input the model did not assess (treated as not
  matching / missing), or one that is not in the framework (ignored);
- C5: an input marked available without a value or source (treated as
  missing).
C1 (the alternative is a higher tier than the recommendation) holds by
construction and is asserted.
"""

from src.models.recommendation import (
    CandidateAssessment,
    EstimationMethodReference,
    FlowAssessment,
    InputAssessment,
    RecommendationEntry,
)
from src.tools.evidence_trace import check_available_value
from src.skills.availability import (
    AVAILABLE,
    CONSTANT,
    DEFAULT,
    LAB,
    MISSING,
    STATUSES,
    TARGET,
    decides_availability,
)

LINEAR_EXTRAPOLATION_TIER = 3


def _reference(row: dict) -> EstimationMethodReference:
    return EstimationMethodReference(
        method_id=row["method_id"],
        method_name=row.get("method_name"),
        tier=row.get("tier"),
        tier_name=row.get("tier_name"),
    )


def normalise_inputs(
    method_id: str,
    input_records: list[dict],
    items: list[InputAssessment],
    checks: list[str],
    report_unassessed: bool = True,
    evidence: list[dict] | None = None,
) -> list[InputAssessment]:
    """One InputAssessment per framework input, in framework order, with the
    framework's tag. Used by both the recommendation ranking and Parameter
    Identification, so the two steps apply the same rules:

    - an input the model left out is 'missing' (C4); one it invented is
      dropped (C4); a status other than available/missing/ambiguous is
      'missing' (C4);
    - a DEFAULT input is always available with the framework's value;
    - an 'available' input without a value (or, except CONSTANT, without a
      source) is 'missing' (C5).
    """
    given = {item.name: item for item in items}
    known = [record["name"] for record in input_records]
    for extra in sorted(set(given) - set(known)):
        checks.append(f"C4: {method_id}: input {extra!r} is not in the framework and was ignored")

    result = []
    for record in input_records:
        item = given.get(record["name"])
        if item is None:
            item = InputAssessment(name=record["name"], status=MISSING)
            if report_unassessed:
                checks.append(f"C4: {method_id}: input {record['name']!r} was not assessed; treated as missing")
        item = item.model_copy()
        item.tag = record["tag"]
        status = (item.status or "").strip().lower()
        if status not in STATUSES:
            checks.append(f"C4: {method_id}: input {record['name']!r} had status {item.status!r}; treated as missing")
            status = MISSING
        if record["tag"] == DEFAULT:
            status, item.value = AVAILABLE, record["default"]
            item.source = item.source or "framework default"
        elif status == AVAILABLE and (
            item.value in (None, "") or (record["tag"] != CONSTANT and not item.source)
        ):
            checks.append(f"C5: {method_id}: input {record['name']!r} was marked available without a value and source; treated as missing")
            status = MISSING
        if status == AVAILABLE and evidence is not None:
            keep, message = check_available_value(
                record["name"], record["tag"], item.value, item.derivation, evidence, unit=item.unit
            )
            if message:
                checks.append(f"{message.split(':', 1)[0]}: {method_id}:{message.split(':', 1)[1]}")
            if not keep:
                status = MISSING
                item.note = "; ".join(filter(None, [item.note, message]))
        item.status = status
        result.append(item)
    return result


def _apply_linear_extrapolation(
    row: dict, inputs: list[InputAssessment], linear_extrapolation: dict | None,
    laboratory_quantity: dict | None, checks: list[str],
) -> None:
    """Tier 3: the laboratory quantity's availability is decided by code."""
    applicable = bool(linear_extrapolation and linear_extrapolation.get("applicable"))
    for item in inputs:
        if item.tag != LAB:
            continue
        if applicable and item.status != AVAILABLE:
            checks.append(f"C3: {row['method_id']}: {item.name!r} set to available from the code's linear-extrapolation result (model said {item.status!r})")
            item.status = AVAILABLE
            item.value = laboratory_quantity.get("value") if laboratory_quantity else None
            item.unit = laboratory_quantity.get("unit") if laboratory_quantity else None
            item.source = item.source or "Laboratory Process Inventory: this flow's laboratory quantity"
        elif not applicable and item.status == AVAILABLE:
            checks.append(f"C3: {row['method_id']}: {item.name!r} set to missing: the code found no laboratory quantity to extrapolate (model said available)")
            item.status = MISSING


def _gaps(inputs: list[InputAssessment]) -> list[InputAssessment]:
    return [item for item in inputs if decides_availability(item.tag) and item.status != AVAILABLE]


def _describe_gaps(inputs: list[InputAssessment]) -> str:
    parts = []
    for item in _gaps(inputs):
        detail = f" ({item.note})" if item.note else ""
        parts.append(f"{item.name} {item.status}{detail}")
    return "; ".join(parts)


def _describe_available(inputs: list[InputAssessment]) -> str:
    parts = []
    for item in inputs:
        if item.tag == TARGET or item.status != AVAILABLE:
            continue
        unit = f" {item.unit}" if item.unit else ""
        how = item.derivation or item.source or item.tag
        parts.append(f"{item.name} = {item.value}{unit} [{item.tag}; {how}]")
    return "; ".join(parts)


def _condition_gap(item) -> str | None:
    """'conditions to confirm: ...' for a rule whose conditions the evidence cannot settle."""
    return f"conditions to confirm: {item[1].get('conditions')}" if item[5] else None


def _gap_count(item) -> int:
    return len(_gaps(item[2].inputs)) + (1 if item[5] else 0)


def _gap_names(item) -> str:
    names = [gap.name for gap in _gaps(item[2].inputs)]
    if item[5]:
        names.append("confirmation of its conditions")
    return ", ".join(names)


def _not_applicable_reason(record: CandidateAssessment) -> str:
    """Why the model ruled a rule out, in its own words where it gave them."""
    if not record.operation_match:
        return "operation does not match" + (f": {record.operation_note}" if record.operation_note else "")
    return "conditions not met" + (f": {record.conditions_note}" if record.conditions_note else "")


def _describe_item_gaps(item) -> str:
    return "; ".join(filter(None, [_describe_gaps(item[2].inputs), _condition_gap(item)]))


def rank_candidates(
    flow: dict,
    candidate_rows: list[dict],
    assessment: FlowAssessment,
    linear_extrapolation: dict | None = None,
    laboratory_quantity: dict | None = None,
    evidence: list[dict] | None = None,
) -> RecommendationEntry:
    """Build the RecommendationEntry for one flow from the model's assessment.

    `flow` carries process_id, process_name, inventory_name, component.
    `candidate_rows` are the framework rows of the flow's category, in
    framework order (as loaded by
    `src.tools.estimation_methods_knowledge_base`).
    """
    checks: list[str] = []
    by_id: dict[str, CandidateAssessment] = {}
    for item in assessment.candidates:
        if item.method_id in by_id:
            checks.append(f"C4: {item.method_id} was assessed twice; the first assessment is used")
            continue
        by_id[item.method_id] = item
    known_ids = {row["method_id"] for row in candidate_rows}
    for unknown in sorted(set(by_id) - known_ids):
        checks.append(f"C4: {unknown} is not a candidate for this flow and was ignored")

    assessed_rows = []  # (order, row, CandidateAssessment-with-normalised-inputs, eligible, available)
    for order, row in enumerate(candidate_rows):
        given = by_id.get(row["method_id"])
        if given is None:
            checks.append(f"C4: {row['method_id']} was not assessed; treated as not applicable")
        generic = (row.get("scope") or "").strip().lower() == "generic"
        operation_match = True if generic else bool(given and given.operation_match)
        has_conditions = bool((row.get("conditions") or "").strip())
        # Conditions: true = hold; false = the evidence shows they do not hold;
        # null = the evidence cannot tell. An unconfirmed rule may be offered as
        # the alternative or listed, never recommended.
        unconfirmed = has_conditions and given is not None and given.conditions_met is None
        conditions_met = True if not has_conditions else bool(given and given.conditions_met)
        inputs = (
            normalise_inputs(
                row["method_id"], row["input_records"], given.inputs if given else [], checks,
                report_unassessed=given is not None, evidence=evidence,
            )
            if operation_match
            else []
        )
        if operation_match and row.get("tier") == LINEAR_EXTRAPOLATION_TIER:
            _apply_linear_extrapolation(row, inputs, linear_extrapolation, laboratory_quantity, checks)
        eligible = operation_match and (conditions_met or unconfirmed)
        available = eligible and not unconfirmed and not _gaps(inputs)
        record = CandidateAssessment(
            method_id=row["method_id"],
            operation_match=operation_match,
            operation_note=(given.operation_note if given else None),
            conditions_met=(None if (unconfirmed or not has_conditions) else conditions_met),
            conditions_note=(given.conditions_note if given else None),
            inputs=inputs,
        )
        assessed_rows.append((order, row, record, eligible, available, unconfirmed))

    available_rows = [item for item in assessed_rows if item[4]]
    recommended = max(available_rows, key=lambda item: (item[1].get("tier") or 0, -item[0]), default=None)
    floor = recommended[1].get("tier") if recommended else 0
    higher = [item for item in assessed_rows if item[3] and not item[4] and (item[1].get("tier") or 0) > floor]
    alternative = min(higher, key=lambda item: (_gap_count(item), -(item[1].get("tier") or 0), item[0]), default=None)
    others = sorted((item for item in higher if item is not alternative), key=lambda item: (-(item[1].get("tier") or 0), item[0]))
    by_tier = lambda item: (-(item[1].get("tier") or 0), item[0])  # noqa: E731
    # Shown so the practitioner can select any rule of the category:
    # eligible rules at or below the recommended tier, and rules the model
    # judged not applicable.
    lower = sorted(
        (item for item in assessed_rows if item[3] and item is not recommended and (item[1].get("tier") or 0) <= floor),
        key=by_tier,
    )
    not_applicable = sorted((item for item in assessed_rows if not item[3]), key=by_tier)
    if recommended and alternative:
        assert (alternative[1].get("tier") or 0) > (recommended[1].get("tier") or 0), "C1 violated"

    # Rationale, built only from the assessments above.
    sentences = []
    if recommended:
        row, record = recommended[1], recommended[2]
        sentences.append(f"Recommended {row['method_id']} (Tier {row.get('tier')}): every required input is available: {_describe_available(record.inputs) or 'no inputs required'}.")
        targets = [item.name for item in record.inputs if item.tag == TARGET]
        if targets:
            sentences.append(f"To be supplied for the scale-up calculation: {', '.join(targets)}.")
    else:
        sentences.append("No rule is available: every eligible rule lacks at least one required input.")
    not_available = [item for item in assessed_rows if item[3] and not item[4] and item is not recommended]
    if not_available:
        sentences.append("Not available: " + "; ".join(f"{item[1]['method_id']} (Tier {item[1].get('tier')}, lacks {_gap_names(item)})" for item in sorted(not_available, key=lambda item: (-(item[1].get('tier') or 0), item[0]))) + ".")
    not_eligible = [item for item in assessed_rows if not item[3]]
    if not_eligible:
        reasons = []
        for _, row, record, _, _, _ in not_eligible:
            if not record.operation_match:
                reasons.append(f"{row['method_id']} (operation does not match{': ' + record.operation_note if record.operation_note else ''})")
            else:
                reasons.append(f"{row['method_id']} (conditions not met{': ' + record.conditions_note if record.conditions_note else ''})")
        sentences.append("Not applicable: " + "; ".join(reasons) + ".")

    return RecommendationEntry(
        process_id=flow.get("process_id"),
        process_name=flow.get("process_name"),
        inventory_name=flow.get("inventory_name"),
        component=flow.get("component"),
        recommended_method=_reference(recommended[1]) if recommended else None,
        recommendation_rationale=" ".join(sentences),
        more_representative_method=_reference(alternative[1]) if alternative else None,
        additional_information_required=(_describe_item_gaps(alternative) if alternative else "None"),
        other_higher_tier_methods=("; ".join(f"{item[1]['method_id']} (Tier {item[1].get('tier')}): {_describe_item_gaps(item)}" for item in others) or None),
        lower_tier_methods=("; ".join(
            f"{item[1]['method_id']} (Tier {item[1].get('tier')}): {'available' if item[4] else _describe_item_gaps(item)}"
            for item in lower) or None),
        not_applicable_methods=("; ".join(
            f"{item[1]['method_id']} (Tier {item[1].get('tier')}): {_not_applicable_reason(item[2])}"
            for item in not_applicable) or None),
        candidate_assessments=[item[2] for item in assessed_rows],
        checks=checks,
    )
