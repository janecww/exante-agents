"""Excel export for the Milestone 2B standalone scale-up demo.

Makes Milestone 2A's `ScaleUpPreparation` (and, once computed,
Milestone 2B's `ScaleUpCalculationResult`) human-readable, exactly the
way every other Excel export in this project makes a Pydantic package
human-readable -- deterministic, no reasoning, and never inventing a
value on the way from object to spreadsheet cell.

Two independent worksheets in one standalone workbook (not the shared
`lci_development_workbook.xlsx` -- this is a Milestone 2B prototype,
not wired into the LangGraph-driven HITL workbook):

- "Scale-Up Parameters": one row per (inventory, parameter), covering
  every entry's `ScaleUpPreparation.calculation_inputs` (status
  "available") and `missing_parameters` (status "missing", every
  other column blank -- never a fabricated value). `Source Type`
  exposes each available parameter's provenance
  (`measured`/`derived`/`assumed`/`human_provided`) explicitly, so
  laboratory evidence, other existing evidence, and demo human input
  are never conflated.
- "Calculation Result": one row per inventory's
  `ScaleUpCalculationResult`, once `src.tools.scale_up_calculation`
  has run. "Result Value" and "Production Scale Factor" are written as
  real cross-sheet Excel formulas (e.g. `='Scale-Up Parameters'!I6`)
  referencing the exact input cells on "Scale-Up Parameters" whenever
  the calculation's own basis is traceable that way -- never only a
  plain computed number -- so a reviewer can click the result cell and
  see the formula bar. The formula always reproduces the same value
  `src.tools.scale_up_calculation` computed; it never introduces a
  different calculation.
"""

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.models.reviewed_recommendation import ReviewedRecommendationPackage
from src.models.scale_up_calculation import CALCULATED, ScaleUpCalculationResult
from src.tools.linear_extrapolation import DERIVED_FROM_OUTPUTS, UNCHANGED_SPECIFIC_CONSUMPTION

PARAMETER_SHEET_TITLE = "Scale-Up Parameters"
RESULT_SHEET_TITLE = "Calculation Result"

PARAMETER_HEADERS = [
    "Process ID",
    "Process Name",
    "Inventory",
    "Selected Method ID",
    "Selected Method",
    "Tier",
    "Parameter",
    "Status",
    "Value",
    "Unit",
    "Source",
    "Source Type",
]

RESULT_HEADERS = [
    "Process ID",
    "Process Name",
    "Inventory",
    "Selected Method ID",
    "Selected Method",
    "Calculation Status",
    "Result Value",
    "Result Unit",
    "Basis",
    "Production Scale Factor",
    "Calculation Rule",
    "Missing Parameters",
    "Calculation Notes",
]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

MAX_COLUMN_WIDTH = 60

AVAILABLE = "available"
MISSING = "missing"
NO_SELECTED_METHOD = "no_selected_method"

# The "Scale-Up Parameters" sheet's "Value" column, expressed as a
# letter so cross-sheet result formulas can reference it -- read from
# PARAMETER_HEADERS rather than hardcoded, so the two stay in sync if
# that sheet's column order ever changes.
_PARAMETER_VALUE_COLUMN_LETTER = get_column_letter(PARAMETER_HEADERS.index("Value") + 1)


def _autofit_columns(sheet: Worksheet, headers: list[str], last_row: int) -> None:
    for col_idx, header in enumerate(headers, start=1):
        longest = len(header)
        for row in sheet.iter_rows(min_col=col_idx, max_col=col_idx, min_row=2, max_row=last_row):
            for cell in row:
                if cell.value:
                    longest = max(longest, len(str(cell.value)))
        sheet.column_dimensions[get_column_letter(col_idx)].width = min(
            longest + 2, MAX_COLUMN_WIDTH
        )


def _finish_sheet(sheet: Worksheet, headers: list[str]) -> None:
    last_row = sheet.max_row
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"
    _autofit_columns(sheet, headers, last_row)


def _parameter_rows(package: ReviewedRecommendationPackage) -> list[list]:
    rows = []
    for entry in package.recommendations:
        preparation = entry.scale_up_preparation
        if preparation is None:
            continue  # structurally shouldn't happen once Milestone 2A has run

        method_id = preparation.selected_method.method_id if preparation.selected_method else ""
        method_name = preparation.selected_method.method_name if preparation.selected_method else ""
        tier_name = preparation.selected_method.tier_name if preparation.selected_method else ""

        if preparation.selected_method is None:
            # Rejected / no selection at all -- still one row, so every
            # inventory is accounted for, never silently omitted.
            rows.append(
                [
                    entry.process_id or "",
                    entry.process_name or "",
                    entry.inventory_name or "",
                    "",
                    "",
                    "",
                    "",
                    NO_SELECTED_METHOD,
                    "",
                    "",
                    preparation.reason or "",
                    "",
                ]
            )
            continue

        for calculation_input in preparation.calculation_inputs:
            rows.append(
                [
                    entry.process_id or "",
                    entry.process_name or "",
                    entry.inventory_name or "",
                    method_id,
                    method_name,
                    tier_name,
                    calculation_input.parameter,
                    AVAILABLE,
                    calculation_input.value,
                    calculation_input.unit,
                    calculation_input.source or "",
                    calculation_input.source_type or "",
                ]
            )

        for parameter in preparation.missing_parameters:
            rows.append(
                [
                    entry.process_id or "",
                    entry.process_name or "",
                    entry.inventory_name or "",
                    method_id,
                    method_name,
                    tier_name,
                    parameter,
                    MISSING,
                    None,
                    None,
                    None,
                    None,
                ]
            )
    return rows


def export_scale_up_parameter_review(
    package: ReviewedRecommendationPackage, workbook_path: str | Path
) -> int:
    """Export the "Scale-Up Parameters" worksheet for every inventory.

    Creates `workbook_path` if it doesn't exist; replaces the worksheet
    (rather than duplicating it) if the workbook already exists and
    has one. Never modifies any other worksheet in the same workbook
    (e.g. one already written by `export_scale_up_calculation_results`).

    Returns the number of parameter rows written.
    """
    workbook_path = Path(workbook_path)
    workbook = load_workbook(workbook_path) if workbook_path.exists() else Workbook()
    if "Sheet" in workbook.sheetnames and len(workbook.sheetnames) == 1:
        del workbook["Sheet"]  # the default empty sheet from Workbook()

    if PARAMETER_SHEET_TITLE in workbook.sheetnames:
        del workbook[PARAMETER_SHEET_TITLE]
    sheet = workbook.create_sheet(title=PARAMETER_SHEET_TITLE)

    sheet.append(PARAMETER_HEADERS)
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    rows = _parameter_rows(package)
    for row in rows:
        sheet.append(row)

    _finish_sheet(sheet, PARAMETER_HEADERS)
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(workbook_path)

    return len(rows)


def _parameter_cell_lookup(package: ReviewedRecommendationPackage) -> dict[tuple, int]:
    """Map (process_id, inventory_name, parameter) -> the 1-indexed row
    that parameter occupies on the "Scale-Up Parameters" worksheet.

    Recomputes `_parameter_rows` (the exact same, deterministic
    ordering `export_scale_up_parameter_review` writes) rather than
    threading a lookup through both export functions' public
    signatures -- cheap, and guarantees the two never drift apart.
    """
    return {
        (row[0], row[2], row[6]): row_number
        for row_number, row in enumerate(_parameter_rows(package), start=2)
    }


def _parameter_cell_ref(row_number: int) -> str:
    return f"'{PARAMETER_SHEET_TITLE}'!{_PARAMETER_VALUE_COLUMN_LETTER}{row_number}"


def _result_value_formula_and_note(
    result: ScaleUpCalculationResult, cell_lookup: dict[tuple, int], key: tuple
) -> tuple[str | float | None, str]:
    """The "Result Value" cell's content and a human-readable note.

    Returns an Excel formula string (starting with "=") whenever the
    result is traceable back to specific "Scale-Up Parameters" cells;
    otherwise falls back to the plain computed number, so the displayed
    result is never blank or wrong even if a cell can't be located.
    Never changes *what* was calculated -- only how it is expressed.
    """
    plain_value = result.result.value if result.result else None
    if result.calculation_status != CALCULATED or not result.primary_parameter:
        return plain_value, ""

    primary_row = cell_lookup.get((*key, result.primary_parameter))
    if primary_row is None:
        return plain_value, ""
    primary_ref = _parameter_cell_ref(primary_row)

    if result.basis in (DERIVED_FROM_OUTPUTS, UNCHANGED_SPECIFIC_CONSUMPTION) and (
        result.laboratory_output_parameter
    ):
        laboratory_output_row = cell_lookup.get((*key, result.laboratory_output_parameter))
        if laboratory_output_row is None:
            return plain_value, ""
        laboratory_output_ref = _parameter_cell_ref(laboratory_output_row)
        formula = f"={primary_ref}/{laboratory_output_ref}"
        note = (
            f"Result = {result.primary_parameter} ÷ {result.laboratory_output_parameter} "
            f"(basis: {result.basis})"
        )
        return formula, note

    # unchanged_specific_consumption with no known laboratory_output,
    # or already_normalized_to_FU: the per-functional-unit value is the
    # laboratory value carried forward unchanged (see
    # src.tools.linear_extrapolation) -- a direct reference, not a
    # computed ratio, but still a real formula, not a hardcoded number.
    formula = f"={primary_ref}"
    note = f"Result = {result.primary_parameter} (basis: {result.basis})"
    return formula, note


def _production_scale_factor_formula(
    result: ScaleUpCalculationResult, cell_lookup: dict[tuple, int], key: tuple
) -> str | float | None:
    """The "Production Scale Factor" cell's content, as a formula when
    both outputs were actually used (see `DERIVED_FROM_OUTPUTS`), else
    the plain (`None`) value -- a scale factor is genuinely undefined
    for every other basis, never a placeholder."""
    if (
        result.calculation_status != CALCULATED
        or result.basis != DERIVED_FROM_OUTPUTS
        or not result.laboratory_output_parameter
        or not result.industrial_output_parameter
    ):
        return result.production_scale_factor

    laboratory_output_row = cell_lookup.get((*key, result.laboratory_output_parameter))
    industrial_output_row = cell_lookup.get((*key, result.industrial_output_parameter))
    if laboratory_output_row is None or industrial_output_row is None:
        return result.production_scale_factor

    return f"={_parameter_cell_ref(industrial_output_row)}/{_parameter_cell_ref(laboratory_output_row)}"


def _result_row(
    key: tuple, entry, result: ScaleUpCalculationResult, cell_lookup: dict[tuple, int]
) -> list:
    process_id, inventory_name = key
    method_id = result.selected_method.method_id if result.selected_method else ""
    method_name = result.selected_method.method_name if result.selected_method else ""
    result_value, note = _result_value_formula_and_note(result, cell_lookup, key)
    return [
        process_id or "",
        (entry.process_name if entry else "") or "",
        inventory_name or "",
        method_id,
        method_name,
        result.calculation_status,
        result_value,
        result.result.unit if result.result else None,
        result.basis or "",
        _production_scale_factor_formula(result, cell_lookup, key),
        result.calculation_rule or "",
        "; ".join(result.missing_parameters) if result.missing_parameters else "",
        note,
    ]


def export_scale_up_calculation_results(
    package: ReviewedRecommendationPackage,
    results: dict[tuple, ScaleUpCalculationResult],
    workbook_path: str | Path,
) -> int:
    """Export the "Calculation Result" worksheet, one row per inventory.

    `results` maps `(process_id, inventory_name)` -> the
    `ScaleUpCalculationResult` computed for that inventory by
    `src.tools.scale_up_calculation.calculate_scale_up`. Creates
    `workbook_path` if it doesn't exist; replaces the worksheet if the
    workbook already has one, and never touches any other worksheet
    (e.g. "Scale-Up Parameters").

    "Result Value" and "Production Scale Factor" are written as
    cross-sheet Excel formulas referencing "Scale-Up Parameters"'s own
    "Value" column (e.g. `='Scale-Up Parameters'!I6`) whenever the
    result is traceable that way, falling back to the plain computed
    number otherwise -- either way the displayed value is identical to
    what `calculate_scale_up` returned; only its expression as a
    formula vs. a constant differs. `package` must be the same package
    `export_scale_up_parameter_review` was (or will be) called with, so
    the referenced row numbers line up with what that sheet actually
    contains -- `run_scale_up_demo` guarantees this by construction.

    Returns the number of result rows written.
    """
    workbook_path = Path(workbook_path)
    workbook = load_workbook(workbook_path) if workbook_path.exists() else Workbook()
    if "Sheet" in workbook.sheetnames and len(workbook.sheetnames) == 1:
        del workbook["Sheet"]

    if RESULT_SHEET_TITLE in workbook.sheetnames:
        del workbook[RESULT_SHEET_TITLE]
    sheet = workbook.create_sheet(title=RESULT_SHEET_TITLE)

    sheet.append(RESULT_HEADERS)
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    entries_by_key = {
        (entry.process_id, entry.inventory_name): entry for entry in package.recommendations
    }
    cell_lookup = _parameter_cell_lookup(package)

    row_count = 0
    for key, result in results.items():
        sheet.append(_result_row(key, entries_by_key.get(key), result, cell_lookup))
        row_count += 1

    _finish_sheet(sheet, RESULT_HEADERS)
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(workbook_path)

    return row_count
