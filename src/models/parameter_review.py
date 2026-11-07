"""Pydantic models for the Parameter Identification (Parameter Requirement) Agent.

Once the practitioner has selected a method for a flow, the agent reports,
for every input of that method, its status under the shared definition of
"available" (`src.skills.availability`) -- the same definition the
Estimation Recommendation step used -- with value, unit, source and, for
a derived value, the derivation. It does not select or change the method
and does not perform the scale-up calculation.

The language model fills `required_parameters` only. Everything else is
computed by code (`src.agents.parameter_requirement`): the framework tag of
each input, `missing_parameters`, `target_inputs`, `calculation_readiness`
and `consistency_flags` (checks C2 and C5).
"""

from pydantic import BaseModel, Field

READY = "READY"
MISSING_PARAMETERS = "MISSING_PARAMETERS"

AVAILABLE = "available"
MISSING = "missing"
AMBIGUOUS = "ambiguous"

# Fields of ParameterReview that code computes; removed from the JSON
# skeleton shown to the model.
COMPUTED_FIELDS = ("missing_parameters", "target_inputs", "calculation_readiness", "consistency_flags")


class RequiredParameter(BaseModel):
    """One input of the selected method and its status.

    `status` is "available", "missing" or "ambiguous". `value`, `unit` and
    `source` are given only for an available input, copied from the case
    evidence (or the framework default / a stated physical constant);
    `derivation` records the calculation when the value was derived by an
    allowed derivation; `note` names the candidate values of an ambiguous
    input, or a related value that could not be used. `tag` is always
    overwritten from the framework.
    """

    parameter: str
    tag: str | None = None
    status: str = MISSING
    value: str | float | None = None
    unit: str | None = None
    source: str | None = None
    derivation: str | None = None
    note: str | None = None
    # Only for a missing or ambiguous input: where the practitioner could
    # obtain it (a kind of source, never a value or a citation). Numbers
    # are removed by code.
    where_to_find: str | None = None
    # Filled by code, not the model: the selected rule's own reference from
    # the framework's documentation sheet, for a missing LITERATURE input.
    framework_reference: str | None = None


# Fields of RequiredParameter that code fills; removed from the skeleton.
COMPUTED_PARAMETER_FIELDS = ("framework_reference",)


class ParameterReview(BaseModel):
    """The parameter review for one flow's selected method.

    `calculation_readiness` is READY when every input tagged LAB,
    CONSTANT, DEFAULT or LITERATURE is available; the TARGET inputs listed
    in `target_inputs` are then still to be supplied by the practitioner
    for the scale-up calculation. `missing_parameters` lists the non-TARGET
    inputs that are missing or ambiguous.
    """

    required_parameters: list[RequiredParameter] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    target_inputs: list[str] = Field(default_factory=list)
    calculation_readiness: str = MISSING_PARAMETERS
    consistency_flags: list[str] = Field(default_factory=list)
