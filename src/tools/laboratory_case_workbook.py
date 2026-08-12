"""Load/save the unified Laboratory Case Workbook -- the canonical
laboratory input for the Stage 1 workflow.

Previously the laboratory case was split across two files: `technology.yaml`
(process inventory: process IDs, names, inputs, outputs, quantities,
units) and `references/lab_derived_parameters.xlsx` (parameters
extracted or calculated from laboratory data). This module replaces
that split with one workbook, `laboratory_case_workbook.xlsx`,
containing three worksheets:

    Technology Overview     -- key/value technology-level metadata
    Process Inventory       -- one row per process, per input, per output
    Lab-Derived Parameters  -- one row per lab-derived parameter

Every row in the two data worksheets carries a "Provenance" column
(Reported / Calculated / Assumed) so it always stays clear whether a
value was measured in the lab, derived from lab data, or assumed --
this is deterministic bookkeeping, never inferred by an LLM.

`export_laboratory_case_workbook()` builds the workbook (used once to
migrate a case from the old `technology.yaml` +
`lab_derived_parameters.xlsx` split, and available for any case that
wants to regenerate it). `import_laboratory_case_workbook()` is what
the orchestrator actually calls at runtime: it returns a `Technology`
model (from Process Inventory + Technology Overview) and a list of
lab-derived-parameter row dicts (from Lab-Derived Parameters, in the
same shape `src.tools.excel_table_loader.load_excel_table` already
produced for the old standalone file, plus "Provenance"), so no
downstream consumer -- agents, prompts -- needs to change how it
consumes either.
"""

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.models.technology import (
    CurrentState,
    InventoryFlow,
    Process,
    TargetState,
    Technology,
    TechnologyInfo,
)

TECHNOLOGY_OVERVIEW_SHEET = "Technology Overview"
PROCESS_INVENTORY_SHEET = "Process Inventory"
LAB_DERIVED_PARAMETERS_SHEET = "Lab-Derived Parameters"

PROCESS_INVENTORY_HEADERS = [
    "Process ID",
    "Process Name",
    "Process Type",
    "Depends On",
    "Note",
    "Record Type",
    "Inventory Name",
    "Value",
    "Unit",
    "Provenance",
]

LAB_DERIVED_PARAMETERS_HEADERS = [
    "Process Stage",
    "Parameter",
    "Value (as printed)",
    "Value (numeric)",
    "Unit",
    "Description",
    "Data Source",
    "Provenance",
]

# The exact keys `src.tools.excel_table_loader.load_excel_table` produced
# for the original standalone lab_derived_parameters.xlsx -- preserved
# so the Estimation Recommendation Agent's prompt builder needs no
# changes to keep reading these rows.
_LEGACY_LAB_PARAMETER_KEYS = [
    "Process stage",
    "Parameter",
    "Value (as printed)",
    "Value (numeric)",
    "Unit",
    "Description",
    "Data source",
]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
MAX_COLUMN_WIDTH = 60

REPORTED = "Reported"
CALCULATED = "Calculated"
ASSUMED = "Assumed"


def _classify_data_source_provenance(data_source: str | None) -> str:
    """Normalize a free-text "Data source" note into Reported/Calculated/Assumed.

    `lab_derived_parameters.xlsx` already writes this distinction in
    prose (e.g. "Laboratory experiment", "Calculated from laboratory
    data", "Assumed room temperature"); this only standardizes it into
    one of the three provenance categories, it never invents a
    classification the source text doesn't already state.
    """
    text = (data_source or "").strip().lower()
    if "assum" in text:
        return ASSUMED
    if "calculat" in text:
        return CALCULATED
    return REPORTED


def _style_header_row(sheet: Worksheet) -> None:
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL


def _autofit_columns(sheet: Worksheet, headers: list[str], last_row: int) -> None:
    for col_idx, header in enumerate(headers, start=1):
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


def _write_technology_overview_sheet(workbook: Workbook, technology: Technology) -> None:
    sheet = workbook.create_sheet(title=TECHNOLOGY_OVERVIEW_SHEET)
    sheet.append(["Field", "Value"])
    _style_header_row(sheet)

    rows = [
        ("name", technology.technology.name),
        ("type", technology.technology.type),
        ("functional_unit", technology.technology.functional_unit),
        ("description", technology.technology.description),
        ("current_state.trl", technology.current_state.trl),
        ("current_state.scale", technology.current_state.scale),
        ("current_state.throughput", technology.current_state.throughput),
        ("target_state.trl", technology.target_state.trl),
        ("target_state.scale", technology.target_state.scale),
        ("target_state.throughput", technology.target_state.throughput),
    ]
    for field, value in rows:
        sheet.append([field, value])

    _autofit_columns(sheet, ["Field", "Value"], sheet.max_row)


def _process_row(process: Process, record_type: str, flow=None) -> list:
    return [
        process.id or "",
        process.name or "",
        process.process_type or "",
        "; ".join(process.depends_on),
        process.note or "",
        record_type,
        flow.name if flow else "",
        flow.value if (flow and flow.value is not None) else "",
        flow.unit if flow else "",
        REPORTED,
    ]


def _write_process_inventory_sheet(workbook: Workbook, technology: Technology) -> None:
    sheet = workbook.create_sheet(title=PROCESS_INVENTORY_SHEET)
    sheet.append(PROCESS_INVENTORY_HEADERS)
    _style_header_row(sheet)

    for process in technology.processes:
        sheet.append(_process_row(process, "Process"))
        for flow in process.inputs:
            sheet.append(_process_row(process, "Input", flow))
        for flow in process.outputs:
            sheet.append(_process_row(process, "Output", flow))

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = (
        f"A1:{get_column_letter(len(PROCESS_INVENTORY_HEADERS))}{sheet.max_row}"
    )
    _autofit_columns(sheet, PROCESS_INVENTORY_HEADERS, sheet.max_row)


def _write_lab_derived_parameters_sheet(
    workbook: Workbook, lab_derived_parameters: list[dict]
) -> None:
    sheet = workbook.create_sheet(title=LAB_DERIVED_PARAMETERS_SHEET)
    sheet.append(LAB_DERIVED_PARAMETERS_HEADERS)
    _style_header_row(sheet)

    for row in lab_derived_parameters:
        data_source = row.get("Data source")
        sheet.append(
            [
                row.get("Process stage") or "",
                row.get("Parameter") or "",
                row.get("Value (as printed)") or "",
                row.get("Value (numeric)") if row.get("Value (numeric)") is not None else "",
                row.get("Unit") or "",
                row.get("Description") or "",
                data_source or "",
                _classify_data_source_provenance(data_source),
            ]
        )

    sheet.freeze_panes = "A2"
    if sheet.max_row > 1:
        sheet.auto_filter.ref = (
            f"A1:{get_column_letter(len(LAB_DERIVED_PARAMETERS_HEADERS))}{sheet.max_row}"
        )
    _autofit_columns(sheet, LAB_DERIVED_PARAMETERS_HEADERS, sheet.max_row)


def export_laboratory_case_workbook(
    technology: Technology,
    lab_derived_parameters: list[dict],
    path: str | Path,
) -> None:
    """Write the unified Laboratory Case Workbook to `path`.

    Combines `technology` (Technology Overview + Process Inventory
    worksheets) and `lab_derived_parameters` (Lab-Derived Parameters
    worksheet, in the row shape `excel_table_loader.load_excel_table`
    produces for the original standalone file) into one workbook, with
    no loss of information from either source.
    """
    path = Path(path)
    workbook = Workbook()
    workbook.remove(workbook.active)  # replace the default blank sheet

    _write_technology_overview_sheet(workbook, technology)
    _write_process_inventory_sheet(workbook, technology)
    _write_lab_derived_parameters_sheet(workbook, lab_derived_parameters)

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _read_technology_overview(workbook) -> tuple[TechnologyInfo, CurrentState, TargetState]:
    if TECHNOLOGY_OVERVIEW_SHEET not in workbook.sheetnames:
        raise ValueError(
            f'Worksheet "{TECHNOLOGY_OVERVIEW_SHEET}" not found in the '
            "laboratory case workbook."
        )
    sheet = workbook[TECHNOLOGY_OVERVIEW_SHEET]
    values = {
        row[0]: row[1]
        for row in sheet.iter_rows(min_row=2, values_only=True)
        if row and row[0] is not None
    }

    technology_info = TechnologyInfo(
        name=values.get("name"),
        type=values.get("type"),
        functional_unit=values.get("functional_unit"),
        description=values.get("description"),
    )
    current_state = CurrentState(
        trl=values.get("current_state.trl"),
        scale=values.get("current_state.scale"),
        throughput=values.get("current_state.throughput"),
    )
    target_state = TargetState(
        trl=values.get("target_state.trl"),
        scale=values.get("target_state.scale"),
        throughput=values.get("target_state.throughput"),
    )
    return technology_info, current_state, target_state


def _read_process_inventory(workbook) -> list[Process]:
    if PROCESS_INVENTORY_SHEET not in workbook.sheetnames:
        raise ValueError(
            f'Worksheet "{PROCESS_INVENTORY_SHEET}" not found in the '
            "laboratory case workbook."
        )
    sheet = workbook[PROCESS_INVENTORY_SHEET]

    header_row = [cell.value for cell in sheet[1]]
    if header_row != PROCESS_INVENTORY_HEADERS:
        raise ValueError(
            f'Unexpected columns in the "{PROCESS_INVENTORY_SHEET}" worksheet.\n'
            f"Expected: {PROCESS_INVENTORY_HEADERS}\nFound: {header_row}"
        )
    column_index = {name: index for index, name in enumerate(PROCESS_INVENTORY_HEADERS)}

    processes: dict[str, Process] = {}
    order: list[str] = []

    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row is None or all(value is None for value in row):
            continue

        process_id = row[column_index["Process ID"]] or ""
        record_type = row[column_index["Record Type"]]

        if process_id not in processes:
            depends_on_raw = row[column_index["Depends On"]] or ""
            processes[process_id] = Process(
                id=process_id or None,
                name=row[column_index["Process Name"]] or None,
                process_type=row[column_index["Process Type"]] or None,
                depends_on=[dep.strip() for dep in depends_on_raw.split(";") if dep.strip()],
                note=row[column_index["Note"]] or None,
            )
            order.append(process_id)

        if record_type in ("Input", "Output"):
            value = row[column_index["Value"]]
            flow = InventoryFlow(
                name=row[column_index["Inventory Name"]] or None,
                value=value if value != "" else None,
                unit=row[column_index["Unit"]] or None,
            )
            if record_type == "Input":
                processes[process_id].inputs.append(flow)
            else:
                processes[process_id].outputs.append(flow)

    return [processes[process_id] for process_id in order]


def _read_lab_derived_parameters(workbook) -> list[dict]:
    if LAB_DERIVED_PARAMETERS_SHEET not in workbook.sheetnames:
        raise ValueError(
            f'Worksheet "{LAB_DERIVED_PARAMETERS_SHEET}" not found in the '
            "laboratory case workbook."
        )
    sheet = workbook[LAB_DERIVED_PARAMETERS_SHEET]

    header_row = [cell.value for cell in sheet[1]]
    if header_row != LAB_DERIVED_PARAMETERS_HEADERS:
        raise ValueError(
            f'Unexpected columns in the "{LAB_DERIVED_PARAMETERS_SHEET}" worksheet.\n'
            f"Expected: {LAB_DERIVED_PARAMETERS_HEADERS}\nFound: {header_row}"
        )

    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row is None or all(value is None for value in row):
            continue
        record = dict(zip(LAB_DERIVED_PARAMETERS_HEADERS, row))
        # Re-key to the legacy column names so existing consumers (the
        # Estimation Recommendation prompt builder) need no changes,
        # then carry "Provenance" forward as an addition.
        legacy_shaped = {
            legacy_key: record[header]
            for legacy_key, header in zip(
                _LEGACY_LAB_PARAMETER_KEYS, LAB_DERIVED_PARAMETERS_HEADERS
            )
        }
        legacy_shaped["Provenance"] = record["Provenance"]
        rows.append(legacy_shaped)

    return rows


def import_laboratory_case_workbook(path: str | Path) -> tuple[Technology, list[dict]]:
    """Read the unified Laboratory Case Workbook at `path`.

    Returns `(technology, lab_derived_parameters)`: a `Technology`
    model reconstructed from the Technology Overview and Process
    Inventory worksheets, and the Lab-Derived Parameters worksheet as a
    list of row dicts (same shape as the original standalone
    `lab_derived_parameters.xlsx`, plus "Provenance").

    Raises `FileNotFoundError` if the workbook does not exist, or
    `ValueError` if an expected worksheet or its columns are missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Laboratory case workbook not found: {path}")

    workbook = load_workbook(path, data_only=True)

    technology_info, current_state, target_state = _read_technology_overview(workbook)
    processes = _read_process_inventory(workbook)
    lab_derived_parameters = _read_lab_derived_parameters(workbook)

    technology = Technology(
        technology=technology_info,
        current_state=current_state,
        target_state=target_state,
        processes=processes,
    )
    return technology, lab_derived_parameters
