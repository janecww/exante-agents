"""Pydantic models for the Inventory Classification Agent's output."""

from pydantic import BaseModel, Field

# `inventory_source` values. Defined once here so the prompt builder, the
# agent's post-validation enforcement, and the Excel exporter all agree
# on the exact, canonically-cased strings.
USER_INPUT_SOURCE = "User Input"
AGENT_SUGGESTION_SOURCE = "Agent Suggestion"

# Fixed human-review policy for every Agent Suggestion entry: introducing
# a new inventory always changes the foreground LCI, so this is a
# business rule -- not an LLM judgement call -- and is enforced
# deterministically by the agent regardless of what the LLM returns.
AGENT_SUGGESTION_HUMAN_REVIEW_REQUIRED = "Yes"
AGENT_SUGGESTION_REVIEW_REASON = (
    "New inventory suggested for industrial-scale modelling. Human "
    "confirmation is required before inclusion."
)


class InventoryClassificationEntry(BaseModel):
    """Suggested component classification for one foreground inventory.

    Covers both inventories that already exist in the case's laboratory
    input (`inventory_source` = "User Input") and additional inventories the
    agent conservatively suggests as commonly becoming explicit at
    industrial scale (`inventory_source` = "Agent Suggestion", e.g.
    steam, cooling water, compressed air). Agent suggestions are
    recommendations only; they are never automatically added to the
    foreground inventory -- the human reviewer decides via the "Include
    Inventory" column of the exported Excel workbook.

    `inventory_source` is expected to be one of: `USER_INPUT_SOURCE`,
    `AGENT_SUGGESTION_SOURCE`.
    `suggested_component` is expected to be one of: reactant, solvent,
    catalyst, energy, heat (see `src/skills/component_definition.yaml`).
    `human_review_required` is expected to be one of: "Yes", "No" --
    always "Yes" (with `review_reason` = `AGENT_SUGGESTION_REVIEW_REASON`)
    when `inventory_source` is `AGENT_SUGGESTION_SOURCE`.
    """

    process_id: str | None = None
    process_name: str | None = None
    inventory_name: str | None = None
    inventory_source: str | None = None
    suggested_component: str | None = None
    rationale: str | None = None
    human_review_required: str | None = None
    review_reason: str | None = None


class InventoryClassificationPackage(BaseModel):
    """Top-level model corresponding to inventory_classification.yaml."""

    inventories: list[InventoryClassificationEntry] = Field(default_factory=list)
