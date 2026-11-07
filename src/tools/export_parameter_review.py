"""Excel export of the Parameter Requirement Agent's output into
Worksheet 3 ("Parameter Review") of the existing, shared LCI
Development Workbook.

Transforms the `ReviewedRecommendationPackage` already produced by
Milestone 1 (`src.tools.import_estimation_recommendations` +
`src.agents.parameter_requirement.review_parameter_requirements`) into
a reviewer-friendly worksheet appended to the same
`lci_development_workbook.xlsx` that Worksheets 1 ("Inventory
Classification") and 2 ("Estimation Recommendations") already live in.
This is a deterministic formatting step -- it performs no reasoning,
never re-derives parameter availability, and never re-implements the
Parameter Requirement Agent's own checks; it only presents the
`ParameterReview`/`RequiredParameter` values the agent already
produced. Every other existing worksheet is left completely unchanged.

One row per required parameter, per inventory with a selected method
(`entry.human_selected_method` not `None`) -- `Selected Method ID`,
`Selected Method`, and `Tier` come directly from that
`HumanSelectedMethod` object, never derived from the method name or
abbreviated. For an inventory where the human selected neither
proposed method (`human_selected_method is None`), no parameter rows
are fabricated: a single row shows the inventory's identity with every
method/parameter column genuinely blank (`None`, not the literal text
"null"/"N/A"/"None").

"Source Type" is not a field on `RequiredParameter` -- it is derived
here, deterministically and only for readability, from the `source`
text the agent already recorded (e.g. "Lab-Derived Parameters: t" ->
"lab-derived"), by matching against the same four evidence sections
`src.prompts.parameter_requirement_prompt` instructs the agent to
check and cite. It never overrides, infers, or second-guesses
`status`/`value`/`source` themselves, and it is left blank (`None`)
whenever the source text doesn't match a known evidence section --
never a guessed category.

"Note" is `RequiredParameter.note` shown verbatim -- populated by the
agent only for a `MISSING` parameter where a semantically related value
exists but could not be used as-is (most commonly a unit mismatch,
e.g. a value reported in litres when kg is needed, with no density
available to convert it). This surfaces "a conversion is needed" to
the reviewer directly in the exported workbook, rather than that
context being lost once the parameter is marked missing.
"""

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.models.reviewed_recommendation import (
    HumanSelectedMethod,
    ReviewedRecommendationEntry,
    ReviewedRecommendationPackage,
)

SHEET_TITLE = "Parameter Review"

HEADERS = [
    "Process ID",
    "Process Name",
    "Inventory",
    "Selected Method ID",
    "Selected Method",
    "Tier",
    "Parameter",
    "Tag",
    "Status",
    "Value",
    "Unit",
    "Source",
    "Source Type",
    "Derivation",
    "Note",
    "Consistency Check",
]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

MAX_COLUMN_WIDTH = 60

# Matched (case-insensitively, as a substring) against a
# RequiredParameter's own `source` text -- the exact evidence-section
# names src.prompts.parameter_requirement_prompt instructs the agent to
# check and cite in that field. Order matters only in that the first
# match wins; none of these patterns overlap in practice.
_SOURCE_TYPE_PATTERNS = [
    ("lab-derived parameters", "lab-derived"),
    ("laboratory process inventory", "laboratory inventory"),
    ("laboratory_quantity", "laboratory inventory"),
    ("technology overview", "technology overview"),
    ("scaleup_decision_framework", "framework"),
    ("framework", "framework"),
]


def _source_type(source: str | None) -> str | None:
    """A short, human-readable evidence-category label for `source`.

    Purely presentational: derived from text the agent already wrote,
    never independently determined and never allowed to influence
    `status`/`value`. Returns `None` (a genuinely blank cell) when
    `source` is empty or doesn't match a known evidence section --
    never a fabricated or guessed category.
    """
    if not source:
        return None
    normalized = source.strip().lower()
    for pattern, label in _SOURCE_TYPE_PATTERNS:
        if pattern in normalized:
            return label
    return None


def _method_row_prefix(
    entry: ReviewedRecommendationEntry, method: HumanSelectedMethod | None
) -> list:
    return [
        entry.process_id or "",
        entry.process_name or "",
        entry.inventory_name or "",
        method.method_id if method else None,
        method.method_name if method else None,
        method.tier_name if method else None,
    ]


def _rows_for_entry(entry: ReviewedRecommendationEntry) -> list[list]:
    """One row per required parameter for this inventory, or a single
    identity-only row when there is nothing to show a parameter for.

    Never fabricates a parameter requirement: an inventory with no
    selected method (`human_selected_method is None`, per Milestone 1
    section 3 -- the human rejected both proposed methods) gets exactly
    one row with every method/parameter column blank. An inventory with
    a selected method but no parameter review yet, or with a parameter
    review that lists no required parameters, similarly gets one row
    with the method columns filled in and the parameter columns blank
    -- never a fabricated parameter, and never an inventory silently
    omitted from the sheet.
    """
    method = entry.human_selected_method
    required_parameters = (
        entry.parameter_review.required_parameters
        if entry.parameter_review is not None
        else []
    )

    if not required_parameters:
        return [_method_row_prefix(entry, method) + [None] * 10]

    flags = entry.parameter_review.consistency_flags if entry.parameter_review is not None else []
    names = [item.parameter for item in required_parameters]
    # A flag goes on the row of the input it names; a flag naming no input
    # goes on the flow's first row.
    general = [flag for flag in flags if not any(f"{name}" in flag for name in names)]

    rows = []
    for index, required_parameter in enumerate(required_parameters):
        own = [flag for flag in flags if required_parameter.parameter in flag]
        rows.append(
            _method_row_prefix(entry, method)
            + [
                required_parameter.parameter,
                required_parameter.tag,
                required_parameter.status,
                required_parameter.value,
                required_parameter.unit,
                required_parameter.source,
                _source_type(required_parameter.source),
                required_parameter.derivation,
                required_parameter.note,
                "\n".join(own + (general if index == 0 else [])) or None,
            ]
        )
    return rows


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


def export_parameter_review(
    package: ReviewedRecommendationPackage, workbook_path: str | Path
) -> int:
    """Append the "Parameter Review" worksheet to `workbook_path`.

    Opens the existing LCI Development Workbook, adds (or replaces, if
    this stage is re-run) the "Parameter Review" worksheet, and saves
    back to the same path. Every other existing worksheet (Worksheet 1
    "Inventory Classification", Worksheet 2 "Estimation
    Recommendations", and any other) is left untouched.

    Returns the number of rows written (one per required parameter,
    per inventory with a selected method; one identity-only row for an
    inventory with no selected method or no parameters to show).
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

    row_count = 0
    for entry in package.recommendations:
        for row in _rows_for_entry(entry):
            sheet.append(row)
            row_count += 1

    last_row = sheet.max_row

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{last_row}"
    _autofit_columns(sheet, last_row)

    workbook.save(workbook_path)

    return row_count
