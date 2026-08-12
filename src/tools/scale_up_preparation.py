"""Deterministic Scale-Up Preparation (Milestone 2A).

Bridges Milestone 1's human-selected method and parameter review into
a validated `ScaleUpPreparation` -- the direct input to Milestone 2B's
scale-up calculation engine. This module performs no LLM reasoning at
all: `review_parameter_requirements` (Milestone 1) has already
determined, per required parameter, whether it is available (with
value/unit/source) or missing; this stage only

- re-validates the selected method's `method_id` against the
  authoritative knowledge base and retrieves its `assumptions_to_log`/
  `limitations` text (never invented, never re-derived);
- classifies each already-resolved parameter's provenance
  (measured/derived/assumed) from its `source` text;
- recognises the framework's own "(optional -- ...)" `required_inputs`
  annotation (already used by tier-3 linear extrapolation -- see
  `src.tools.linear_extrapolation`) as an explicit, pre-existing
  justification for a genuinely missing optional parameter, never an
  invented value; and
- computes the overall `READY`/`MISSING_PARAMETERS`/`NOT_READY` status.

The human's selected method is never replaced, reinterpreted, or
second-guessed here, and no alternative estimation method is proposed
or compared -- this stage's only questions are "is the selected
method's own definition genuine?" and "are its parameters available?".
No industrial quantity is calculated, no scale factor is applied, and
no missing value is estimated -- that is Milestone 2B.
"""

from src.models.parameter_review import MISSING_PARAMETERS, READY
from src.models.recommendation import EstimationMethodReference
from src.models.reviewed_recommendation import (
    ReviewedRecommendationEntry,
    ReviewedRecommendationPackage,
)
from src.models.scale_up_preparation import (
    ASSUMED,
    DERIVED,
    MEASURED,
    NO_PARAMETER_REVIEW,
    NO_SELECTED_METHOD,
    NOT_READY,
    CalculationInput,
    ScaleUpPreparation,
)

_LABORATORY_SOURCE_MARKERS = (
    "laboratory process inventory",
    "laboratory quantity",
    "technology overview",
)
_DERIVED_SOURCE_MARKERS = ("lab-derived parameters",)
_ASSUMED_SOURCE_MARKERS = ("assumption", "scaleup_decision_framework", "framework")


def _method_lookup(estimation_methods: list[dict]) -> dict[str, dict]:
    return {row["method_id"]: row for row in estimation_methods if row.get("method_id")}


def _classify_source_type(source: str | None) -> str:
    """Deterministically classify an already-resolved parameter's
    provenance from its `source` text (written by the Parameter
    Requirement Agent) -- never re-guessed from the value itself, and
    never a fresh LLM call.
    """
    normalized = (source or "").strip().lower()
    if any(marker in normalized for marker in _ASSUMED_SOURCE_MARKERS):
        return ASSUMED
    if any(marker in normalized for marker in _DERIVED_SOURCE_MARKERS):
        return DERIVED
    if any(marker in normalized for marker in _LABORATORY_SOURCE_MARKERS):
        return MEASURED
    # An unrecognised but populated source still names *some* real
    # evidence field the Parameter Requirement Agent found -- treat it
    # as directly reported rather than silently discarding its
    # provenance or guessing "assumed".
    return MEASURED


def _parse_required_input_tokens(required_inputs: str | None) -> list[dict]:
    """Parse the framework's ';'-separated `required_inputs` text into
    (name, optional) tokens, e.g. "industrial_output (optional --
    enables production_scale_factor)" -> {"name": "industrial_output",
    "optional": True}. This is the only place tier-3's existing
    "(optional -- ...)" annotation convention (see the linear
    extrapolation milestone) is read for this purpose -- never a new
    annotation convention invented here.
    """
    if not required_inputs:
        return []
    tokens = []
    for raw in required_inputs.split(";"):
        raw = raw.strip()
        if not raw:
            continue
        tokens.append(
            {
                "name": raw.split("(")[0].strip(),
                "optional": "(optional" in raw.lower(),
            }
        )
    return tokens


def _normalize_parameter_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _is_optional_per_framework(parameter_name: str, required_input_tokens: list[dict]) -> bool:
    normalized_target = _normalize_parameter_name(parameter_name)
    return any(
        token["optional"] and _normalize_parameter_name(token["name"]) == normalized_target
        for token in required_input_tokens
    )


def prepare_scale_up_inputs(
    entry: ReviewedRecommendationEntry, estimation_methods: list[dict]
) -> ScaleUpPreparation:
    """Build the validated calculation-input package for one inventory.

    Always returns a `ScaleUpPreparation` -- never `None` -- even when
    the human rejected both proposed methods (`calculation_status =
    NOT_READY`, `reason = NO_SELECTED_METHOD`), so downstream code
    always has one consistent structure to inspect.

    Raises `ValueError` if a method was selected but its `method_id`
    cannot be found in `estimation_methods`: the knowledge base is the
    sole authority for the selected method's definition. Milestone 1
    already validated this once at import time; this is a defensive
    re-check, not a new source of truth, and it never falls back to
    inventing a method definition.
    """
    if entry.human_selected_method is None:
        return ScaleUpPreparation(
            selected_method=None,
            selection_source=entry.selection_source,
            calculation_status=NOT_READY,
            reason=NO_SELECTED_METHOD,
        )

    method_lookup = _method_lookup(estimation_methods)
    method_row = method_lookup.get(entry.human_selected_method.method_id)
    if method_row is None:
        raise ValueError(
            "Scale-Up Preparation: selected method_id "
            f"{entry.human_selected_method.method_id!r} for Process ID "
            f"{entry.process_id!r} / Inventory {entry.inventory_name!r} is "
            "not found in the estimation methods knowledge base "
            "(src/skills/scaleup_decision_framework.xlsx)."
        )

    selected_method = EstimationMethodReference(
        method_id=method_row["method_id"],
        method_name=method_row.get("method_name"),
        tier_name=method_row.get("tier_name"),
    )

    if entry.parameter_review is None:
        return ScaleUpPreparation(
            selected_method=selected_method,
            selection_source=entry.selection_source,
            calculation_status=NOT_READY,
            reason=NO_PARAMETER_REVIEW,
        )

    required_input_tokens = _parse_required_input_tokens(method_row.get("required_inputs"))

    calculation_inputs = []
    missing_parameters = []
    for required_parameter in entry.parameter_review.required_parameters:
        if required_parameter.status == "available":
            calculation_inputs.append(
                CalculationInput(
                    parameter=required_parameter.parameter,
                    value=required_parameter.value,
                    unit=required_parameter.unit,
                    source=required_parameter.source,
                    source_type=_classify_source_type(required_parameter.source),
                )
            )
        elif _is_optional_per_framework(required_parameter.parameter, required_input_tokens):
            # The framework's own required_inputs annotation already
            # explains why this specific parameter can be absent (e.g.
            # tier 3's optional industrial_output/laboratory_output) --
            # not a fabricated value, an explicit, pre-existing
            # framework justification (see section 9's "explicitly
            # justified by the method/framework").
            calculation_inputs.append(
                CalculationInput(
                    parameter=required_parameter.parameter,
                    value=None,
                    unit=None,
                    source="scaleup_decision_framework.xlsx: required_inputs (optional)",
                    source_type=ASSUMED,
                )
            )
        else:
            missing_parameters.append(required_parameter.parameter)

    calculation_status = MISSING_PARAMETERS if missing_parameters else READY

    assumptions_to_log = method_row.get("assumptions_to_log")
    limitations = method_row.get("limitations")

    return ScaleUpPreparation(
        selected_method=selected_method,
        selection_source=entry.selection_source,
        calculation_status=calculation_status,
        reason=None,
        calculation_inputs=calculation_inputs,
        missing_parameters=missing_parameters,
        assumptions=[assumptions_to_log] if assumptions_to_log else [],
        limitations=[limitations] if limitations else [],
    )


def prepare_scale_up_inputs_for_package(
    package: ReviewedRecommendationPackage, estimation_methods: list[dict]
) -> ReviewedRecommendationPackage:
    """Run scale-up preparation for every inventory in the package.

    Unlike `review_parameter_requirements` (Milestone 1), this runs for
    *every* entry unconditionally -- including rejected ones, which
    always resolve to `NOT_READY` rather than being skipped -- since a
    `ScaleUpPreparation` must always exist for downstream code to
    inspect. Mutates and returns `package` in place.
    """
    for entry in package.recommendations:
        entry.scale_up_preparation = prepare_scale_up_inputs(entry, estimation_methods)
    return package
