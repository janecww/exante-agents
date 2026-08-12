"""Excel export of RecommendationPackage into Worksheet 2 ("Estimation
Recommendations") of the existing, shared LCI Development Workbook.

Transforms the validated `RecommendationPackage` produced by the
Estimation Recommendation Agent into a reviewer-friendly worksheet
appended to the same `lci_development_workbook.xlsx` that Worksheet 1
("Inventory Classification") already lives in. This is a deterministic
formatting step -- it performs no reasoning, does not re-derive any
recommendation, and does not re-rank or re-check applicability; it
only presents the values the agent already produced, one row per
confirmed inventory, in the same order the recommendation workflow
produced them. Worksheet 1 (and any other existing worksheet) is left
completely unchanged.

Method IDs are exposed directly ("Recommended Method ID" / "More
Representative Method ID") rather than folded into a name-only
display, so a reviewer can trace any recommendation straight back to
its row in `src/skills/scaleup_decision_framework.xlsx` without
cross-referencing anything else. "Recommended Method" and "More
Representative Method" (with their IDs and the rationale/additional-
information fields) are always the agent's own output -- never a human
decision.

"Human Selected Method ID" is the single field representing the human's
final decision, distinct from every agent-produced column above it.
Unlike the rest of the sheet, it is never derived from the
recommendation package: it starts blank for an inventory the human has
not yet reviewed, and -- because re-running this stage replaces the
worksheet rather than appending to it (e.g. after a case's inventory or
lab evidence changes and recommendations are regenerated) -- any value
a human already entered for a still-present inventory (matched by
Process ID + Inventory) is read back from the existing worksheet and
carried forward, never cleared or overwritten by the agent.
"""

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.models.recommendation import (
    EstimationMethodReference,
    RecommendationEntry,
    RecommendationPackage,
)

SHEET_TITLE = "Estimation Recommendations"

HEADERS = [
    "Process ID",
    "Process Name",
    "Inventory",
    "Component",
    "Recommended Method ID",
    "Recommended Method",
    "Recommendation Rationale",
    "More Representative Method ID",
    "More Representative Method",
    "Additional Information Required",
    "Human Selected Method ID",
]

_PROCESS_ID_COLUMN = HEADERS.index("Process ID")
_INVENTORY_COLUMN = HEADERS.index("Inventory")
_HUMAN_SELECTED_METHOD_ID_COLUMN = HEADERS.index("Human Selected Method ID")

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

MAX_COLUMN_WIDTH = 60


def _method_id(reference: EstimationMethodReference | None) -> str:
    if reference is None:
        return ""
    return reference.method_id or ""


def _method_name(reference: EstimationMethodReference | None) -> str:
    """The plain display name for a method reference, or "" if none."""
    if reference is None:
        return ""
    return reference.method_name or ""


def _read_preserved_human_selections(workbook: Workbook) -> dict[tuple, str]:
    """Read (Process ID, Inventory) -> Human Selected Method ID from a
    previously exported "Estimation Recommendations" worksheet, if any.

    Returns an empty mapping when the worksheet doesn't exist yet, or
    when its header row doesn't match the current `HEADERS` exactly --
    an older-schema sheet (e.g. one written before this column existed)
    has nothing safely preservable, so preservation is skipped rather
    than risk reading a human's entry out of the wrong column.
    """
    if SHEET_TITLE not in workbook.sheetnames:
        return {}
    sheet = workbook[SHEET_TITLE]
    header_row = [cell.value for cell in sheet[1]]
    if header_row != HEADERS:
        return {}

    preserved = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        selected = row[_HUMAN_SELECTED_METHOD_ID_COLUMN]
        if selected:
            key = (row[_PROCESS_ID_COLUMN], row[_INVENTORY_COLUMN])
            preserved[key] = selected
    return preserved


def _entry_row(entry: RecommendationEntry, human_selected_method_id: str) -> list:
    """Build one worksheet row from a RecommendationEntry.

    `human_selected_method_id` is supplied by the caller (blank for a
    newly generated output, or the preserved value read back from a
    prior export) -- this function never invents or defaults it.
    """
    return [
        entry.process_id or "",
        entry.process_name or "",
        entry.inventory_name or "",
        entry.component or "",
        _method_id(entry.recommended_method),
        _method_name(entry.recommended_method),
        entry.recommendation_rationale or "",
        _method_id(entry.more_representative_method),
        _method_name(entry.more_representative_method),
        entry.additional_information_required or "",
        human_selected_method_id or "",
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


def export_estimation_recommendations(
    package: RecommendationPackage, workbook_path: str | Path
) -> int:
    """Append the "Estimation Recommendations" worksheet to `workbook_path`.

    Opens the existing LCI Development Workbook, adds (or replaces, if
    this stage is re-run) Worksheet 2, and saves back to the same path.
    Worksheet 1 and any other existing worksheet are left untouched.

    Before replacing the worksheet, any existing "Human Selected Method
    ID" values are read back (keyed by Process ID + Inventory) and
    carried forward onto the matching rows of the regenerated sheet --
    the agent never populates or clears this column itself.

    Returns the number of recommendations exported.
    """
    workbook_path = Path(workbook_path)
    workbook = load_workbook(workbook_path)

    preserved_selections = _read_preserved_human_selections(workbook)

    if SHEET_TITLE in workbook.sheetnames:
        # Re-running this stage replaces the worksheet rather than
        # duplicating or appending to it.
        del workbook[SHEET_TITLE]
    sheet = workbook.create_sheet(title=SHEET_TITLE)

    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    for entry in package.recommendations:
        key = (entry.process_id or "", entry.inventory_name or "")
        human_selected_method_id = preserved_selections.get(key, "")
        sheet.append(_entry_row(entry, human_selected_method_id))

    last_row = sheet.max_row

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{last_row}"
    _autofit_columns(sheet, last_row)

    workbook.save(workbook_path)

    return len(package.recommendations)
