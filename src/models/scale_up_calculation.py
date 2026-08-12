"""Pydantic models for Milestone 2B's standalone scale-up calculation demo.

This module is deliberately separate from `src.models.scale_up_preparation`
(Milestone 2A) rather than extending it: `CalculationInput` is reused
unchanged here (its `source_type` is a free string, so a fourth
provenance value -- `HUMAN_PROVIDED`, see below -- needs no schema
change), and `ScaleUpPreparation` itself doubles as the "completed
calculation-input structure" once `src.tools.scale_up_human_input`
merges in demo values -- there is no separate "finalized inputs" model.
This file only adds what Milestone 2A's models have no reason to
know about: the numerical result of actually running a calculation.
"""

from pydantic import BaseModel, Field

from src.models.recommendation import EstimationMethodReference

# A fourth provenance value alongside Milestone 2A's `MEASURED` /
# `DERIVED` / `ASSUMED` (`src.models.scale_up_preparation`): a value
# supplied by a human for this standalone demo, never pretended to be
# laboratory evidence.
HUMAN_PROVIDED = "human_provided"

CALCULATED = "CALCULATED"
CALCULATION_NOT_IMPLEMENTED = "CALCULATION_NOT_IMPLEMENTED"


class CalculatedValue(BaseModel):
    """The numerical result of a scale-up calculation."""

    value: float | None = None
    unit: str | None = None


class ScaleUpCalculationResult(BaseModel):
    """The outcome of `src.tools.scale_up_calculation.calculate_scale_up`.

    `calculation_status` is exactly one of `CALCULATED`,
    `MISSING_PARAMETERS` (`src.models.parameter_review.MISSING_PARAMETERS`),
    `NOT_READY` (`src.models.scale_up_preparation.NOT_READY`), or
    `CALCULATION_NOT_IMPLEMENTED` -- always computed deterministically,
    and `result` is populated only for `CALCULATED`. `selected_method`
    is carried over verbatim from the `ScaleUpPreparation` that was
    calculated from; this module never replaces or reinterprets it.

    `primary_parameter`/`laboratory_output_parameter`/
    `industrial_output_parameter` name which of the calculation's own
    input parameters were actually used numerically (populated only
    for `CALCULATED`; the latter two are `None` whenever that value
    wasn't available and so played no part in the result). They exist
    solely so `src.tools.export_scale_up_parameter_review` can write
    the result as a real Excel formula referencing those parameters'
    own cells on the "Scale-Up Parameters" sheet, rather than only a
    plain computed number -- the calculation itself is unchanged.
    """

    calculation_status: str
    result: CalculatedValue | None = None
    missing_parameters: list[str] = Field(default_factory=list)
    reason: str | None = None
    calculation_rule: str | None = None
    basis: str | None = None
    production_scale_factor: float | None = None
    selected_method: EstimationMethodReference | None = None
    primary_parameter: str | None = None
    laboratory_output_parameter: str | None = None
    industrial_output_parameter: str | None = None
