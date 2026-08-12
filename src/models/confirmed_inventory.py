"""Pydantic models for the human-reviewed, confirmed inventory.

`ConfirmedInventoryPackage` is the authoritative inventory package for
downstream agents (e.g. a future Estimation Recommendation Agent). It
is constructed purely from the human-reviewed LCI Development Workbook
by `src.tools.import_confirmed_inventory` -- no LLM reasoning, no
inference: only rows where "Include Inventory" = "Yes" are included,
using each row's reviewer-selected "Final Component". Downstream agents
should consume this model and must never read or parse Excel directly.
"""

from pydantic import BaseModel, Field


class ConfirmedInventoryEntry(BaseModel):
    """One inventory confirmed by the human reviewer, ready for estimation.

    `component` is the reviewer's "Final Component" selection from the
    workbook, which may differ from the Inventory Classification
    Agent's original suggestion. `inventory_source` is carried over
    unchanged for traceability (see
    `src.models.inventory_classification.InventoryClassificationEntry`).
    """

    process_id: str | None = None
    process_name: str | None = None
    inventory_name: str | None = None
    inventory_source: str | None = None
    component: str | None = None


class ConfirmedInventoryPackage(BaseModel):
    """Top-level model corresponding to confirmed_inventory.yaml."""

    inventories: list[ConfirmedInventoryEntry] = Field(default_factory=list)
