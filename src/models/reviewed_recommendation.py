"""Pydantic models for the human-reviewed Estimation Recommendation output.

Mirrors the existing `InventoryClassificationPackage` ->
`ConfirmedInventoryPackage` split (see `src.models.confirmed_inventory`):
the agent's own output (`RecommendationPackage`, in
`src.models.recommendation`) is never modified in place, in either its
schema or its contents. Once a human has reviewed Worksheet 2 and
selected a final method (or rejected both proposed options),
`src.tools.import_estimation_recommendations` reads that decision back
into `ReviewedRecommendationPackage` -- a strictly additive structure
that keeps every agent-produced field (`recommended_method`,
`recommendation_rationale`, `more_representative_method`,
`additional_information_required`) exactly as the agent produced it,
alongside the human's own decision and (once selected) the parameter
readiness review for that decision.

Deliberately a separate model, not new fields added onto
`RecommendationEntry` / `RecommendationPackage`: those two classes are
walked directly by `src.prompts.schema_skeleton.build_json_skeleton` to
build the JSON structure shown to the LLM, so any field added to them
would be sent to the LLM as something to populate -- exactly what must
never happen with a human decision. `EstimationMethodReference` (also
LLM-facing) is reused unchanged for `recommended_method` /
`more_representative_method` here; `HumanSelectedMethod` is a distinct,
richer model (never referenced by the LLM-facing schema) that carries
the full method definition retrieved from the knowledge base.

Milestone 1 (human method selection): the human has exactly three
meaningful decisions per inventory -- accept the recommended method,
accept the more representative ("alternative") method, or select
neither -- recorded as `selection_source`
(`SELECTION_RECOMMENDED`/`SELECTION_ALTERNATIVE`/`SELECTION_NONE`). Any
other method_id is not a presented option and is rejected by
`src.tools.import_estimation_recommendations` rather than accepted as a
free-form substitution. Once a method is selected,
`src.agents.parameter_requirement.review_parameter_requirements`
populates `parameter_review`; it is `None` whenever
`selection_source == SELECTION_NONE` -- the parameter agent is never
invoked for an inventory with no selected method.
"""

from pydantic import BaseModel, Field

from src.models.parameter_review import ParameterReview
from src.models.recommendation import EstimationMethodReference
from src.models.scale_up_preparation import ScaleUpPreparation

PENDING = "pending"
SELECTED = "selected"

SELECTION_RECOMMENDED = "recommended"
SELECTION_ALTERNATIVE = "alternative"
SELECTION_NONE = "none"


class HumanSelectedMethod(BaseModel):
    """The human's validated final method selection.

    Retrieved in full from `src/skills/scaleup_decision_framework.xlsx`
    once `import_estimation_recommendations_workbook` confirms
    `method_id` is a real method belonging to the inventory's own
    component group -- never invented, and never authored by the LLM.
    """

    method_id: str
    method_name: str | None = None
    tier_name: str | None = None
    component: str | None = None
    rule_or_equation: str | None = None
    required_inputs: str | None = None
    trigger_condition: str | None = None
    produces: str | None = None
    assumptions_to_log: str | None = None
    limitations: str | None = None
    reference: str | None = None
    provenance: str | None = None
    url: str | None = None


class ReviewedRecommendationEntry(BaseModel):
    """One inventory's recommendation, plus the human's own decision.

    `recommended_method`, `recommendation_rationale`,
    `more_representative_method`, and `additional_information_required`
    are carried over unchanged from the agent's own
    `RecommendationEntry` -- this model only adds the human's decision,
    it never replaces or reinterprets the agent's output.

    `human_selected_method` is `None` whenever the workbook's "Human
    Selected Method ID" cell was blank -- it is never defaulted to
    `recommended_method`. `human_selection_status` makes that
    distinction explicit for downstream code: `"pending"` (no selection
    yet) or `"selected"` (a validated selection exists). `selection_source`
    additionally records *which* of the two proposed methods was chosen
    (`SELECTION_RECOMMENDED`/`SELECTION_ALTERNATIVE`), or
    `SELECTION_NONE` when nothing was selected. An invalid selection --
    a method_id that is neither the recommended nor the alternative
    method for this inventory -- is never represented as a package
    state at all: it raises `ValueError` in
    `import_estimation_recommendations_workbook` instead, since it is
    not one of the human's three meaningful decisions.

    `parameter_review` is populated only once a method has been
    selected (`selection_source` is `SELECTION_RECOMMENDED` or
    `SELECTION_ALTERNATIVE`); it stays `None` for `SELECTION_NONE` --
    the Parameter Requirement Agent is never invoked for an inventory
    with no selected method.

    `scale_up_preparation` (Milestone 2A) is populated by
    `src.tools.scale_up_preparation.prepare_scale_up_inputs` for
    *every* entry, including a rejected one -- unlike `parameter_review`,
    it is never `None`: a rejected inventory still gets a
    `ScaleUpPreparation` recording `calculation_status = NOT_READY`, so
    downstream code can always inspect one consistent structure rather
    than checking for `None` first.
    """

    process_id: str | None = None
    process_name: str | None = None
    inventory_name: str | None = None
    component: str | None = None
    recommended_method: EstimationMethodReference | None = None
    recommendation_rationale: str | None = None
    more_representative_method: EstimationMethodReference | None = None
    additional_information_required: str | None = None
    human_selected_method: HumanSelectedMethod | None = None
    human_selection_status: str | None = None
    selection_source: str | None = None
    parameter_review: ParameterReview | None = None
    scale_up_preparation: ScaleUpPreparation | None = None


class ReviewedRecommendationPackage(BaseModel):
    """Top-level model produced by `import_estimation_recommendations_workbook`."""

    recommendations: list[ReviewedRecommendationEntry] = Field(default_factory=list)
