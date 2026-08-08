"""Pydantic models mirroring src/schemas/recommendation.yaml.

`RecommendationPackage` is produced by the Estimation Recommendation
Agent from `ConfirmedInventoryPackage` and the authoritative estimation
methods knowledge base (`src/skills/scaleup_decision_framework.xlsx`).
The human remains responsible for selecting the final estimation
method -- this package is a recommendation only; the "Selected Method"
column of the exported workbook is where that final decision is made.
"""

from pydantic import BaseModel, Field


class EstimationMethodReference(BaseModel):
    """A reference to one row of the estimation methods knowledge base,
    identified by `method_id` for traceability. `method_name` is
    normalized from the knowledge base after LLM validation, so it can
    never diverge from the authoritative name for that `method_id`.
    """

    method_id: str | None = None
    method_name: str | None = None


class RecommendationEntry(BaseModel):
    """The recommendation for one confirmed foreground inventory.

    `recommended_method` is the most representative estimation method
    that can currently be applied using available information; `None`
    only if no candidate method in the knowledge base is applicable.
    `more_representative_method` is a higher-fidelity method that
    exists in the knowledge base but cannot yet be applied; `None` if
    none exists, in which case `additional_information_required` is
    the literal string "None".
    """

    process_id: str | None = None
    process_name: str | None = None
    inventory_name: str | None = None
    component: str | None = None
    recommended_method: EstimationMethodReference | None = None
    recommendation_rationale: str | None = None
    more_representative_method: EstimationMethodReference | None = None
    additional_information_required: str | None = None


class RecommendationPackage(BaseModel):
    """Top-level model corresponding to recommendation.yaml."""

    recommendations: list[RecommendationEntry] = Field(default_factory=list)
