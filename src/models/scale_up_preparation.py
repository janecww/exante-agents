"""Pydantic models for Milestone 2A: Scale-Up Preparation.

Bridges the human-selected method (Milestone 1,
`src.models.reviewed_recommendation.ReviewedRecommendationEntry.human_selected_method`)
and its parameter readiness review (`src.models.parameter_review`) into
a validated, calculation-ready input package -- the direct input to
Milestone 2B's scale-up calculation engine. This module performs no
reasoning of its own; see `src.tools.scale_up_preparation` for the
deterministic resolution logic that builds a `ScaleUpPreparation`.
"""

from pydantic import BaseModel, Field

from src.models.recommendation import EstimationMethodReference

NOT_READY = "NOT_READY"

MEASURED = "measured"
DERIVED = "derived"
ASSUMED = "assumed"

NO_SELECTED_METHOD = "NO_SELECTED_METHOD"
NO_PARAMETER_REVIEW = "NO_PARAMETER_REVIEW"


class CalculationInput(BaseModel):
    """One parameter resolved and ready for the scale-up calculation.

    `source_type` records its provenance -- `MEASURED` (directly
    reported in the Laboratory Process Inventory, the inventory's own
    laboratory quantity, or Technology Overview), `DERIVED` (already
    calculated by the Lab-Derived Parameters stage), or `ASSUMED` (the
    selected method's own knowledge-base definition explicitly
    justifies proceeding without external evidence for this specific
    parameter -- e.g. a tier-3 method's "(optional -- ...)"
    `required_inputs` annotation -- never an arbitrary or invented
    substitute). `value`/`unit` are populated only for genuinely
    resolved parameters; an `ASSUMED` parameter with no framework
    constant to copy may have `value = None` while still being
    calculation-ready, because the method itself explains why no value
    is needed.
    """

    parameter: str
    value: str | float | None = None
    unit: str | None = None
    source: str | None = None
    source_type: str | None = None


class ScaleUpPreparation(BaseModel):
    """The validated calculation-input package for one inventory.

    `selected_method` and `selection_source` are carried over verbatim
    from the human's Milestone 1 decision (see
    `ReviewedRecommendationEntry`) -- this stage never replaces or
    reinterprets them, and never proposes a different method.

    `calculation_status` is exactly one of `READY`
    (`src.models.parameter_review.READY`), `MISSING_PARAMETERS`
    (`src.models.parameter_review.MISSING_PARAMETERS`), or `NOT_READY`
    -- always computed deterministically
    (`src.tools.scale_up_preparation.prepare_scale_up_inputs`), never
    an LLM confidence score. `reason` is populated only for
    `NOT_READY` (`NO_SELECTED_METHOD` or `NO_PARAMETER_REVIEW`).
    """

    selected_method: EstimationMethodReference | None = None
    selection_source: str | None = None
    calculation_status: str = NOT_READY
    reason: str | None = None
    calculation_inputs: list[CalculationInput] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
