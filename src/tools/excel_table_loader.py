"""Generic deterministic loader for tabular Excel reference/skill files.

Reads one worksheet of an `.xlsx` file into a list of plain dicts, one
per data row, keyed by the header row. This performs no reasoning, no
filtering, and no unit conversion -- callers interpret the rows.
Used to load Excel-based knowledge sources that aren't a good fit for
the YAML-only `skill_loader` (e.g. `scaleup_decision_framework.xlsx`,
`lab_derived_parameters.xlsx`), keeping this parsing logic in one place
rather than duplicated per caller.
"""

from pathlib import Path

from openpyxl import load_workbook


def load_excel_table(path: str | Path, sheet_name: str | None = None) -> list[dict]:
    """Load one worksheet of an .xlsx file as a list of row dicts.

    The first *fully populated* row encountered (every column filled)
    is treated as the column headers, so a leading title row (typically
    just one cell filled in an otherwise wide sheet) and any blank row
    above the real header are both skipped automatically; every
    following non-blank row becomes one dict keyed by those headers.
    `sheet_name` selects a specific worksheet; defaults to the
    workbook's active worksheet.

    Raises `FileNotFoundError` if `path` does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Excel table not found: {path}")

    workbook = load_workbook(path, data_only=True)
    sheet = workbook[sheet_name] if sheet_name else workbook.active

    rows = sheet.iter_rows(values_only=True)

    header = None
    for row in rows:
        if row and all(value is not None for value in row):
            header = [str(value).strip() for value in row]
            break
    if header is None:
        return []

    records = []
    for row in rows:
        if all(value is None for value in row):
            continue
        records.append(dict(zip(header, row)))
    return records
