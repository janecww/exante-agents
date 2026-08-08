"""Excel export of RecommendationPackage into Worksheet 2 ("Estimation
Recommendations") of the existing, shared LCI Development Workbook.

Transforms the validated `RecommendationPackage` produced by the
Estimation Recommendation Agent into a reviewer-friendly worksheet
appended to the same `lci_development_workbook.xlsx` that Worksheet 1
("Inventory Classification") already lives in. This is a deterministic
formatting step -- it performs no reasoning and does not re-derive any
recommendation; it only presents the values the agent already
produced. Worksheet 1 (and any other existing worksheet) is left
completely unchanged.

`method_id` is retained on `RecommendationPackage` for traceability but
is deliberately not displayed here, per design: only `method_name` is
shown, and "Selected Method" is pre-populated from the recommendation
so a reviewer who agrees can accept the workbook unchanged, or
overwrite it with their own choice. The workbook remains editable for
future Human-in-the-Loop stages.
"""

from pathlib import Path

from openpyxl import load_workbook
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
    "Final Component",
    "Recommended Method",
    "Recommendation Rationale",
    "More Representative Method",
    "Additional Information Required",
    "Selected Method",
]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

MAX_COLUMN_WIDTH = 60


def _method_name(reference: EstimationMethodReference | None) -> str:
    """The display name for a method reference, or "" if there is none."""
    if reference is None:
        return ""
    return reference.method_name or ""


def _entry_row(entry: RecommendationEntry) -> list:
    """Build one worksheet row from a RecommendationEntry.

    "Selected Method" is pre-populated with the recommended method's
    name so a reviewer who agrees can accept the workbook unchanged;
    disagreements are corrected by overwriting this column. Method IDs
    are never written to any cell -- only method names are displayed.
    """
    recommended_name = _method_name(entry.recommended_method)
    return [
        entry.process_id or "",
        entry.process_name or "",
        entry.inventory_name or "",
        entry.component or "",
        recommended_name,
        entry.recommendation_rationale or "",
        _method_name(entry.more_representative_method),
        entry.additional_information_required or "",
        recommended_name,
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

    Returns the number of recommendations exported.
    """
    workbook_path = Path(workbook_path)
    workbook = load_workbook(workbook_path)

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
        sheet.append(_entry_row(entry))

    last_row = sheet.max_row

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{last_row}"
    _autofit_columns(sheet, last_row)

    workbook.save(workbook_path)

    return len(package.recommendations)
