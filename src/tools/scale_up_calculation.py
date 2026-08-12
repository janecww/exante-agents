"""Standalone deterministic scale-up calculation for Milestone 2B.

`calculate_scale_up` is plain Python -- no LLM, no agent, no new
reasoning. It consumes the human-selected method and a *completed*
`ScaleUpPreparation` (Milestone 2A, optionally topped up by
`src.tools.scale_up_human_input.apply_human_parameter_inputs`) and
either performs the calculation or reports precisely why it could not,
using one of exactly four `calculation_status` values -- never a
numerical guess.

Currently implemented: tier-3 ("linear extrapolation") methods only
(`REACT-T3`/`SOLV-T3`/`CAT-T3`/`HEAT-T3`/`ENER-T3`), by reusing
`src.tools.linear_extrapolation.apply_linear_extrapolation` -- the
existing, already-tested calculation, never reimplemented here. Every
other method returns `CALCULATION_NOT_IMPLEMENTED` rather than
guessing at an equation this module has not been taught. Extending
coverage to more tiers is future work, deliberately out of scope for
this milestone (see Architecture.md).
"""

from src.models.parameter_review import MISSING_PARAMETERS, READY
from src.models.scale_up_calculation import (
    CALCULATED,
    CALCULATION_NOT_IMPLEMENTED,
    CalculatedValue,
    ScaleUpCalculationResult,
)
from src.models.scale_up_preparation import NOT_READY, CalculationInput, ScaleUpPreparation
from src.tools.linear_extrapolation import apply_linear_extrapolation

_LINEAR_EXTRAPOLATION_TIER_NAME = "linear extrapolation"

# Tokens every tier-3 method's `required_inputs` shares (see
# `src.tools.scale_up_preparation._parse_required_input_tokens`) --
# whichever token remains after excluding these is that method's own
# primary laboratory-quantity parameter (e.g. `lab_solvent_mass` for
# SOLV-T3, `lab_measured_electricity` for ENER-T3).
_UNIVERSAL_LINEAR_EXTRAPOLATION_PARAMETERS = {
    "laboratory_output",
    "industrial_output",
    "functional_unit",
}


def _method_lookup(estimation_methods: list[dict]) -> dict[str, dict]:
    return {row["method_id"]: row for row in estimation_methods if row.get("method_id")}


def _normalize_parameter_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _primary_linear_extrapolation_parameter(required_inputs: str | None) -> str | None:
    """The one required_inputs token that isn't laboratory_output,
    industrial_output, or functional_unit -- this method's own
    laboratory-quantity parameter name, read verbatim from the
    knowledge base, never guessed.
    """
    if not required_inputs:
        return None
    for raw in required_inputs.split(";"):
        name = raw.strip().split("(")[0].strip()
        if _normalize_parameter_name(name) not in _UNIVERSAL_LINEAR_EXTRAPOLATION_PARAMETERS:
            return name
    return None


def _numeric_value(calculation_input: CalculationInput | None) -> float | None:
    """The float value of a resolved calculation input, or `None` if
    absent, unresolved, or genuinely not numeric -- never guessed or
    coerced from an unrelated field.
    """
    if calculation_input is None or calculation_input.value is None:
        return None
    try:
        return float(calculation_input.value)
    except (TypeError, ValueError):
        return None


def calculate_scale_up(
    preparation: ScaleUpPreparation, estimation_methods: list[dict]
) -> ScaleUpCalculationResult:
    """Run the deterministic scale-up calculation for one inventory.

    Args:
        preparation: A `ScaleUpPreparation` (Milestone 2A), typically
            after `apply_human_parameter_inputs` has topped up any
            demo-supplied values. Never mutated, and its
            `selected_method` is never replaced or reconsidered here.
        estimation_methods: Every row of
            `src/skills/scaleup_decision_framework.xlsx`, as loaded by
            `src.tools.excel_table_loader.load_excel_table` -- the
            sole source of the selected method's `rule_or_equation`
            and `required_inputs`.

    Returns:
        A `ScaleUpCalculationResult` with `calculation_status` one of:

        - `NOT_READY`: no method was selected (carries `reason` over
          from `preparation`).
        - `MISSING_PARAMETERS`: a method is selected but a required
          parameter is still missing (never calculated).
        - `CALCULATION_NOT_IMPLEMENTED`: all parameters are available,
          but this module has no equation for the selected method's
          tier yet.
        - `CALCULATED`: the calculation ran; `result` is populated.

        Stops and reports rather than calculating whenever required
        information is unavailable; never asks an LLM to do arithmetic,
        and never silently resolves a unit conversion.
    """
    if preparation.calculation_status == NOT_READY:
        return ScaleUpCalculationResult(
            calculation_status=NOT_READY,
            reason=preparation.reason,
            selected_method=preparation.selected_method,
        )

    if preparation.calculation_status == MISSING_PARAMETERS:
        return ScaleUpCalculationResult(
            calculation_status=MISSING_PARAMETERS,
            missing_parameters=list(preparation.missing_parameters),
            selected_method=preparation.selected_method,
        )

    # calculation_status == READY from here on.
    selected_method = preparation.selected_method
    method_row = _method_lookup(estimation_methods).get(selected_method.method_id)
    if method_row is None:
        # Defensive only: Milestone 2A already validated method_id
        # against this same knowledge base. Never invents a method.
        raise ValueError(
            f"calculate_scale_up: selected method_id {selected_method.method_id!r} "
            "is not found in the estimation methods knowledge base "
            "(src/skills/scaleup_decision_framework.xlsx)."
        )

    if method_row.get("tier_name") != _LINEAR_EXTRAPOLATION_TIER_NAME:
        return ScaleUpCalculationResult(
            calculation_status=CALCULATION_NOT_IMPLEMENTED,
            selected_method=selected_method,
            calculation_rule=method_row.get("rule_or_equation"),
        )

    inputs_by_parameter = {ci.parameter: ci for ci in preparation.calculation_inputs}

    primary_parameter = _primary_linear_extrapolation_parameter(method_row.get("required_inputs"))
    primary_input = inputs_by_parameter.get(primary_parameter)
    primary_value = _numeric_value(primary_input)
    if primary_input is None or primary_value is None:
        # READY should guarantee this is resolved; if it somehow isn't
        # (e.g. a non-numeric value slipped through), report it as
        # missing rather than calculating with a wrong number.
        return ScaleUpCalculationResult(
            calculation_status=MISSING_PARAMETERS,
            missing_parameters=[primary_parameter or "(unknown primary parameter)"],
            selected_method=selected_method,
        )

    laboratory_output = _numeric_value(inputs_by_parameter.get("laboratory_output"))
    industrial_output = _numeric_value(inputs_by_parameter.get("industrial_output"))
    functional_unit_defined = "functional_unit" in inputs_by_parameter

    extrapolation = apply_linear_extrapolation(
        primary_value,
        laboratory_output=laboratory_output,
        industrial_output=industrial_output,
        functional_unit_defined=functional_unit_defined,
    )

    return ScaleUpCalculationResult(
        calculation_status=CALCULATED,
        result=CalculatedValue(
            value=extrapolation.industrial_input_per_functional_unit,
            unit=primary_input.unit,
        ),
        calculation_rule=method_row.get("rule_or_equation"),
        basis=extrapolation.basis,
        production_scale_factor=extrapolation.production_scale_factor,
        selected_method=selected_method,
        primary_parameter=primary_parameter,
        # Only recorded when actually numeric and therefore actually
        # used by apply_linear_extrapolation above -- never claims a
        # parameter was used just because it happens to be present.
        laboratory_output_parameter="laboratory_output" if laboratory_output is not None else None,
        industrial_output_parameter="industrial_output" if industrial_output is not None else None,
    )
