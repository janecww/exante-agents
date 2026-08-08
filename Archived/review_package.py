"""Pydantic models mirroring src/schemas/review_package.yaml."""

from pydantic import BaseModel, Field


class TechnologySummary(BaseModel):
    """Condensed technology description carried in the review package."""

    name: str | None = None
    functional_unit: str | None = None
    target_scale: str | None = None


class Evidence(BaseModel):
    """A single supporting evidence citation."""

    source: str | None = None
    section: str | None = None
    justification: str | None = None


class ReasoningBasis(BaseModel):
    """How an assumption was derived.

    `primary`/`secondary` are expected to be one of: reported_literature,
    engineering_heuristic, technology_analogy, expert_rule, llm_reasoning,
    hybrid.
    """

    primary: str | None = None
    secondary: str | None = None
    explanation: str | None = None


class ReviewComments(BaseModel):
    """Scientific Review Agent feedback on an assumption."""

    overall_assessment: str | None = None
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ProcessAssumption(BaseModel):
    """Proposed industrial-scale process assumption for a lab process."""

    proposed_industrial_process: str | None = None
    description: str | None = None
    target_operating_conditions: str | None = None
    rationale: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    reasoning_basis: ReasoningBasis | None = None
    review_comments: ReviewComments | None = None


class InventoryFlowAssumption(BaseModel):
    """Proposed target-scale inventory assumption for a single flow."""

    name: str | None = None
    laboratory_value: float | None = None
    laboratory_unit: str | None = None
    proposed_estimation_method: str | None = None
    required_parameters: list[str] = Field(default_factory=list)
    rationale: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    reasoning_basis: ReasoningBasis | None = None
    review_comments: ReviewComments | None = None


class InventoryAssumptions(BaseModel):
    """Input and output inventory assumptions for a process."""

    inputs: list[InventoryFlowAssumption] = Field(default_factory=list)
    outputs: list[InventoryFlowAssumption] = Field(default_factory=list)


class ProcessReviewEntry(BaseModel):
    """A single process's assumptions and inventory assumptions for review."""

    process_id: str | None = None
    process_name: str | None = None
    process_assumption: ProcessAssumption | None = None
    inventory_assumptions: InventoryAssumptions | None = None


class ReviewPackage(BaseModel):
    """Top-level model corresponding to review_package.yaml."""

    technology: TechnologySummary
    processes: list[ProcessReviewEntry] = Field(default_factory=list)
