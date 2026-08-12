"""Standalone human-input application for Milestone 2B's scale-up demo.

`apply_human_parameter_inputs` lets a human fill in the parameters
Milestone 2A's `ScaleUpPreparation.missing_parameters` reported as
genuinely absent -- for this standalone prototype only, since the real
LangGraph workflow has no such step yet (see Architecture.md). Every
supplied value is recorded with `source = "Human-provided (demo)"` and
`source_type = HUMAN_PROVIDED`; nothing here pretends a demo value came
from the laboratory workbook, and nothing invents a value the human
didn't supply.

Reuses `CalculationInput`/`ScaleUpPreparation` from Milestone 2A
unchanged (`src.models.scale_up_preparation`) rather than introducing a
parallel "finalized inputs" model -- once human inputs are merged in,
the resulting `ScaleUpPreparation` *is* the completed calculation-input
structure Milestone 2B's calculator consumes.
"""

from src.models.parameter_review import MISSING_PARAMETERS, READY
from src.models.scale_up_calculation import HUMAN_PROVIDED
from src.models.scale_up_preparation import CalculationInput, ScaleUpPreparation

HUMAN_PROVIDED_SOURCE = "Human-provided (demo)"


def apply_human_parameter_inputs(
    preparation: ScaleUpPreparation, human_inputs: dict[str, dict]
) -> ScaleUpPreparation:
    """Merge explicit human-provided values into a `ScaleUpPreparation`.

    Args:
        preparation: A `ScaleUpPreparation` produced by Milestone 2A
            (`src.tools.scale_up_preparation.prepare_scale_up_inputs`).
            Never mutated -- a new object is returned, so the original
            Milestone 2A evidence stays inspectable and unchanged.
        human_inputs: Maps a missing parameter's name to `{"value":
            ..., "unit": ...}`. `unit` may be omitted or `None`.

    Returns:
        A new `ScaleUpPreparation` with every supplied parameter moved
        from `missing_parameters` into `calculation_inputs` (value,
        unit, `source = "Human-provided (demo)"`,
        `source_type = HUMAN_PROVIDED`), `calculation_status`
        recomputed from whatever remains missing, and every other
        field (`selected_method`, `selection_source`, every
        already-available `calculation_input`, `assumptions`,
        `limitations`, `reason`) carried over unchanged.

    Raises:
        ValueError: if a key in `human_inputs` is not currently in
            `preparation.missing_parameters` -- including a parameter
            that is already available (never silently overwritten) or
            one that was never a required parameter at all. Naming the
            preparation's own `missing_parameters` in the error avoids
            a human having to guess what's actually still needed.
    """
    missing = set(preparation.missing_parameters)
    unknown = sorted(set(human_inputs) - missing)
    if unknown:
        raise ValueError(
            f"Cannot apply human input for {unknown!r}: not a currently "
            f"missing parameter for this inventory. Missing parameters "
            f"are: {sorted(missing)!r}. Existing laboratory/derived "
            "evidence is never overwritten by a demo input."
        )

    new_calculation_inputs = list(preparation.calculation_inputs)
    remaining_missing = []
    for parameter in preparation.missing_parameters:
        if parameter in human_inputs:
            supplied = human_inputs[parameter]
            new_calculation_inputs.append(
                CalculationInput(
                    parameter=parameter,
                    value=supplied.get("value"),
                    unit=supplied.get("unit"),
                    source=HUMAN_PROVIDED_SOURCE,
                    source_type=HUMAN_PROVIDED,
                )
            )
        else:
            # Not supplied -- stays missing. Never fabricated to make
            # the calculation runnable.
            remaining_missing.append(parameter)

    return ScaleUpPreparation(
        selected_method=preparation.selected_method,
        selection_source=preparation.selection_source,
        calculation_status=MISSING_PARAMETERS if remaining_missing else READY,
        reason=None if not remaining_missing else preparation.reason,
        calculation_inputs=new_calculation_inputs,
        missing_parameters=remaining_missing,
        assumptions=list(preparation.assumptions),
        limitations=list(preparation.limitations),
    )
