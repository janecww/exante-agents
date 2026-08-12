"""Pydantic models for the Parameter Requirement Agent's output.

Once a human has selected a final method for an inventory (see
`ReviewedRecommendationEntry.human_selected_method` in
`src.models.reviewed_recommendation`), the Parameter Requirement Agent
(`src.agents.parameter_requirement`) determines what information that
specific method needs and whether the case's existing evidence already
supplies it. It does not select or change the method -- the human's
selection is authoritative -- and it does not perform the eventual
scale-up calculation; that is a later milestone.
"""

from pydantic import BaseModel, Field

READY = "READY"
MISSING_PARAMETERS = "MISSING_PARAMETERS"

AVAILABLE = "available"
MISSING = "missing"


class RequiredParameter(BaseModel):
    """One parameter the selected method needs, and whether it is available.

    `value`/`unit`/`source` are populated only when `status` is
    `AVAILABLE` -- copied from real case evidence, never invented or
    estimated. When `status` is `MISSING`, they are `None`: this agent
    never fabricates a placeholder value for something it could not
    find. `source` names where an available value came from (e.g.
    "Laboratory Process Inventory: P01 water input", or "Lab-Derived
    Parameters: m_mix"), so it stays traceable to real case evidence
    rather than an unexplained number.
    """

    parameter: str
    status: str = AVAILABLE
    value: str | float | None = None
    unit: str | None = None
    source: str | None = None


class ParameterReview(BaseModel):
    """The full parameter-readiness review for one inventory's selected method.

    `missing_parameters` and `calculation_readiness` are always
    deterministically recomputed from `required_parameters` by
    `src.agents.parameter_requirement._normalize_calculation_readiness`
    after the LLM responds -- never trusted verbatim from the LLM's own
    summary of its own list, mirroring how `tier_name` is always
    re-derived from the knowledge base rather than trusted from an
    LLM's copy (see `src.agents.estimation_recommendation`).
    """

    required_parameters: list[RequiredParameter] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    calculation_readiness: str = MISSING_PARAMETERS
