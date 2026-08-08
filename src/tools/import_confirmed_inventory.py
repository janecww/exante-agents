"""Deterministic import of the human-reviewed LCI Development Workbook.

Reads Worksheet 1 ("Inventory Classification") of the reviewed
`lci_development_workbook.xlsx`, validates its structure and required
columns, and converts every row the human marked "Include Inventory" =
"Yes" into a `ConfirmedInventoryPackage` -- the authoritative inventory
package for downstream agents. This tool performs no LLM reasoning and
no inference: it faithfully mirrors what the reviewer wrote in the
workbook, using each row's "Final Component" as the confirmed
component. Downstream agents must never read or parse Excel directly;
they consume `ConfirmedInventoryPackage` instead.
"""

from pathlib import Path

from openpyxl import load_workbook

from src.models.confirmed_inventory import (
    ConfirmedInventoryEntry,
    ConfirmedInventoryPackage,
)
from src.tools.export_inventory_classification import HEADERS, SHEET_TITLE

REQUIRED_COLUMNS = HEADERS

INCLUDE_INVENTORY_YES = "yes"


def _read_header_row(sheet) -> list:
    return [cell.value for cell in sheet[1]]


def import_confirmed_inventory_workbook(
    workbook_path: str | Path,
) -> ConfirmedInventoryPackage:
    """Import the reviewed LCI Development Workbook into a package.

    Raises `FileNotFoundError` if the workbook does not exist, or
    `ValueError` if the expected "Inventory Classification" worksheet
    or its required columns are missing. Only rows where "Include
    Inventory" is exactly "Yes" (case-insensitive) are included in the
    returned package.
    """
    workbook_path = Path(workbook_path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"LCI Development Workbook not found: {workbook_path}")

    workbook = load_workbook(workbook_path, data_only=True)

    if SHEET_TITLE not in workbook.sheetnames:
        raise ValueError(
            f'Worksheet "{SHEET_TITLE}" not found in {workbook_path}. '
            f"Found worksheets: {workbook.sheetnames}"
        )
    sheet = workbook[SHEET_TITLE]

    header_row = _read_header_row(sheet)
    if header_row != REQUIRED_COLUMNS:
        raise ValueError(
            f'Unexpected columns in the "{SHEET_TITLE}" worksheet of '
            f"{workbook_path}.\nExpected: {REQUIRED_COLUMNS}\nFound: {header_row}"
        )

    column_index = {name: index for index, name in enumerate(REQUIRED_COLUMNS)}

    entries = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row is None or all(value is None for value in row):
            continue  # skip fully blank rows (e.g. trailing rows)

        include_inventory = row[column_index["Include Inventory"]]
        if not isinstance(include_inventory, str):
            continue
        if include_inventory.strip().lower() != INCLUDE_INVENTORY_YES:
            continue

        entries.append(
            ConfirmedInventoryEntry(
                process_id=row[column_index["Process ID"]],
                process_name=row[column_index["Process Name"]],
                inventory_name=row[column_index["Inventory"]],
                inventory_source=row[column_index["Inventory Source"]],
                component=row[column_index["Final Component"]],
            )
        )

    return ConfirmedInventoryPackage(inventories=entries)
