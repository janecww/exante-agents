"""Excel export of the InventoryClassificationPackage into Worksheet 1
("Inventory Classification") of the shared LCI Development Workbook.

Transforms the validated `InventoryClassificationPackage` produced by
the Inventory Classification Agent into a single, reviewer-friendly
Excel worksheet. This is a deterministic formatting step -- it performs
no reasoning and does not re-derive any classification; it only
presents the values the agent already produced. It contains no
inventory classification logic of its own, and never re-parses the
agent's YAML output: the orchestrator passes it the same in-memory
`InventoryClassificationPackage` the agent returned.

`outputs/parsed/inventory_classification.yaml` remains the internal,
machine-readable artifact used by downstream agents.
`outputs/parsed/lci_development_workbook.xlsx` is the primary interface
for human review, covering both inventories that already exist in the
case's laboratory input ("Inventory Source" = "User Input") and additional
inventories the agent conservatively suggests ("Inventory Source" =
"Agent Suggestion"). Every row pre-populates "Final Component" with the
agent's suggestion (editable, restricted to the five predefined
categories) and "Include Inventory" by provenance -- "Yes" for existing
inventories, "No" for agent suggestions, since a suggestion only
becomes part of the confirmed foreground inventory once a human
promotes it. The workbook is the single Human-in-the-Loop artifact
shared across all workflow stages: after human review, the orchestrator
interrupts the workflow, then `src.tools.import_confirmed_inventory`
reads this same worksheet back into a `ConfirmedInventoryPackage` --
only inventories where "Include Inventory" = "Yes" are carried forward,
using the "Final Component" selected by the user. Future workflow
stages (e.g. a Recommendation Agent) may add further worksheets to this
same workbook; this module remains responsible only for Worksheet 1.
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from src.models.inventory_classification import (
    AGENT_SUGGESTION_SOURCE,
    InventoryClassificationEntry,
    InventoryClassificationPackage,
)

SHEET_TITLE = "Inventory Classification"

HEADERS = [
    "Process ID",
    "Process Name",
    "Inventory",
    "Inventory Source",
    "Suggested Component",
    "Human Review Recommended",
    "Review Reason",
    "Final Component",
    "Include Inventory",
]

FINAL_COMPONENT_COLUMN = HEADERS.index("Final Component") + 1
INCLUDE_INVENTORY_COLUMN = HEADERS.index("Include Inventory") + 1

COMPONENT_CATEGORIES = ["reactant", "solvent", "catalyst", "energy", "heat"]
INCLUDE_INVENTORY_VALUES = ["Yes", "No"]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
REVIEW_RECOMMENDED_FILL = PatternFill(
    start_color="FFF9C4", end_color="FFF9C4", fill_type="solid"
)

MAX_COLUMN_WIDTH = 60


def _default_include_inventory(entry: InventoryClassificationEntry) -> str:
    """Default "Include Inventory" pre-population, by provenance.

    Existing inventories from the case's laboratory input ("User Input")
    default to "Yes"; inventories the agent suggests ("Agent Suggestion")
    default to "No", since only the human reviewer may promote a
    suggestion into the confirmed foreground inventory. The reviewer may
    still change this value for any row.
    """
    source = (entry.inventory_source or "").strip().lower()
    return "No" if source == AGENT_SUGGESTION_SOURCE.lower() else "Yes"


def _entry_row(entry: InventoryClassificationEntry) -> list:
    """Build one worksheet row from an InventoryClassificationEntry.

    "Final Component" is pre-populated with "Suggested Component" so a
    reviewer who agrees with every suggestion can accept the workbook
    unchanged; disagreements are corrected by overwriting this column.
    """
    return [
        entry.process_id or "",
        entry.process_name or "",
        entry.inventory_name or "",
        entry.inventory_source or "",
        entry.suggested_component or "",
        entry.human_review_required or "",
        entry.review_reason or "",
        entry.suggested_component or "",
        _default_include_inventory(entry),
    ]


def _autofit_columns(sheet: Worksheet, last_row: int) -> None:
    """Size each column to its longest value, capped at MAX_COLUMN_WIDTH."""
    for col_idx, header in enumerate(HEADERS, start=1):
        longest = len(header)
        for row in sheet.iter_rows(
            min_col=col_idx, max_col=col_idx, min_row=2, max_row=last_row
        ):
            for cell in row:
                if cell.value:
                    longest = max(longest, len(str(cell.value)))
        sheet.column_dimensions[get_column_letter(col_idx)].width = min(
            longest + 2, MAX_COLUMN_WIDTH
        )


def _add_list_validation(
    sheet: Worksheet, column: int, values: list[str], last_row: int
) -> None:
    """Restrict a column to a drop-down list of `values` for every data row."""
    column_letter = get_column_letter(column)
    validation = DataValidation(
        type="list", formula1=f'"{",".join(values)}"', allow_blank=True
    )
    validation.errorTitle = "Invalid value"
    validation.error = "Select one of: " + ", ".join(values)
    validation.showErrorMessage = True
    sheet.add_data_validation(validation)
    validation.add(f"{column_letter}2:{column_letter}{last_row}")


def export_inventory_classification(
    package: InventoryClassificationPackage, excel_path: str | Path
) -> int:
    """Export an InventoryClassificationPackage to a reviewer-facing workbook.

    Writes one "Inventory Classification" worksheet, one row per
    inventory (existing and agent-suggested alike), with "Final
    Component" restricted to the five predefined component categories
    and "Include Inventory" restricted to "Yes"/"No", both via drop-down
    data validation. Rows the agent flagged for human review ("Human
    Review Recommended" = "Yes") are highlighted light yellow as an
    advisory cue only -- the reviewer retains final authority and may
    edit any row (including agent-suggested inventories) regardless of
    the highlight.

    Returns the number of inventories exported.
    """
    excel_path = Path(excel_path)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE

    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    for entry in package.inventories:
        sheet.append(_entry_row(entry))
        if (entry.human_review_required or "").strip().lower() == "yes":
            for cell in sheet[sheet.max_row]:
                cell.fill = REVIEW_RECOMMENDED_FILL

    last_row = sheet.max_row

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{last_row}"
    _autofit_columns(sheet, last_row)

    if last_row > 1:
        _add_list_validation(
            sheet, FINAL_COMPONENT_COLUMN, COMPONENT_CATEGORIES, last_row
        )
        _add_list_validation(
            sheet, INCLUDE_INVENTORY_COLUMN, INCLUDE_INVENTORY_VALUES, last_row
        )

    excel_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(excel_path)

    return len(package.inventories)
