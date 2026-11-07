"""Pydantic models for the Estimation Recommendation step.

Two layers, so that a model never writes a decision the code makes:

- `FlowAssessment` (with `CandidateAssessment` and `InputAssessment`) is
  what the language model returns for ONE flow: for every candidate
  rule of the flow's category, whether the rule's operations and
  conditions apply, and the status of every input under the shared
  definition of "available" (`src.skills.availability`). It is walked by
  `src.prompts.schema_skeleton.build_json_skeleton` to show the model the
  JSON to return.
- `RecommendationEntry` / `RecommendationPackage` are built by code
  (`src.agents.estimation_recommendation.rank_candidates`) from those
  assessments: the recommended method (highest-tier available rule), the
  alternative (a higher-tier rule that would become available with more
  inputs) and the rationale. They are never shown to the model as
  something to fill in.

The practitioner's decision lives in a separate model,
`src.models.reviewed_recommendation`.
"""

from pydantic import BaseModel, Field


class InputAssessment(BaseModel):
    """One input of one candidate rule, assessed against the case evidence.

    `tag` is always overwritten from the framework after validation (the
    model's copy is never trusted). `status` is one of "available",
    "missing", "ambiguous". `derivation` records the calculation for a
    derived value; `note` names candidate values for an ambiguous input or
    a related value that could not be used.
    """

    name: str
    tag: str | None = None
    status: str = "missing"
    value: str | float | None = None
    unit: str | None = None
    source: str | None = None
    derivation: str | None = None
    note: str | None = None


class CandidateAssessment(BaseModel):
    """One candidate rule, assessed for one flow."""

    method_id: str
    operation_match: bool = False
    operation_note: str | None = None
    conditions_met: bool | None = None
    conditions_note: str | None = None
    inputs: list[InputAssessment] = Field(default_factory=list)


class FlowAssessment(BaseModel):
    """The language model's answer for one flow: every candidate assessed."""

    candidates: list[CandidateAssessment] = Field(default_factory=list)


class EstimationMethodReference(BaseModel):
    """A reference to one rule of the framework. `method_name`, `tier` and
    `tier_name` always come from the framework, never from a model."""

    method_id: str | None = None
    method_name: str | None = None
    tier: int | None = None
    tier_name: str | None = None


class RecommendationEntry(BaseModel):
    """The recommendation for one confirmed flow, computed by code.

    `recommended_method`: the highest-tier available rule (`None` if no
    rule is available). `more_representative_method`: a higher-tier rule
    that would become available if the missing inputs listed in
    `additional_information_required` were supplied (`None` if there is
    none; the field is then the literal "None").
    `other_higher_tier_methods`: the remaining higher-tier rules, each with
    what it is missing. `candidate_assessments`: the model's per-candidate
    assessment the ranking was computed from, with tags filled in from the
    framework. `checks`: findings of the deterministic checks.
    """

    process_id: str | None = None
    process_name: str | None = None
    inventory_name: str | None = None
    component: str | None = None
    recommended_method: EstimationMethodReference | None = None
    recommendation_rationale: str | None = None
    more_representative_method: EstimationMethodReference | None = None
    additional_information_required: str | None = None
    other_higher_tier_methods: str | None = None
    candidate_assessments: list[CandidateAssessment] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class RecommendationPackage(BaseModel):
    """Top-level model corresponding to recommendation.yaml."""

    recommendations: list[RecommendationEntry] = Field(default_factory=list)
