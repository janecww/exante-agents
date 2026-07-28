"""Temporary manual debugging exporter for an already-generated ReviewPackage.

Reads the parsed ReviewPackage YAML produced by a prior workflow run and
writes it into a single, human-readable Excel worksheet using openpyxl,
purely for manual inspection.

This is NOT the production Excel exporter (that will be implemented
separately) and does not touch the orchestrator, agents, prompts,
schemas, GraphState, YAML generation, or the existing exporter. It is
meant to be run manually, on demand:

    python src/tools/export_review_package_manual.py
"""

from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = (
    ROOT / "cases" / "starch_nanocrystals" / "outputs" / "parsed" / "review_package.yaml"
)
EXCEL_PATH = ROOT / "cases" / "starch_nanocrystals" / "outputs" / "review_package_manual.xlsx"

HEADERS = [
    "Process ID",
    "Process Name",
    "Record Type",
    "Flow Name",
    "Laboratory Value",
    "Laboratory Unit",
    "Proposed Industrial Process / Estimation Method",
    "Required Parameters",
    "Rationale",
    "Evidence",
    "Primary Reasoning",
    "Secondary Reasoning",
    "Review Assessment",
    "Strengths",
    "Concerns",
    "Recommendations",
    "Expert Revision",
    "Expert Comments",
]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
PROCESS_FILL = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
PROCESS_FONT = Font(bold=True)
WRAP_ALIGNMENT = Alignment(wrap_text=True, vertical="top")

MAX_COLUMN_WIDTH = 60


def _join_evidence(evidence: list[dict] | None) -> str:
    """Concatenate a list of Evidence dicts into one readable string."""
    if not evidence:
        return ""
    lines = []
    for item in evidence:
        source = item.get("source") or ""
        section = item.get("section") or ""
        justification = item.get("justification") or ""
        lines.append(f"{source} ({section}): {justification}")
    return "\n".join(lines)


def _join_list(values: list[str] | None) -> str:
    """Join a list of strings into multiline, bulleted text."""
    if not values:
        return ""
    return "\n".join(f"- {value}" for value in values)


def _process_row(entry: dict) -> list:
    """Build one PROCESS row from a ProcessReviewEntry dict."""
    process_id = entry.get("process_id") or ""
    process_name = entry.get("process_name") or ""
    assumption = entry.get("process_assumption") or {}
    reasoning_basis = assumption.get("reasoning_basis") or {}
    review_comments = assumption.get("review_comments") or {}

    rationale_parts = []
    if assumption.get("description"):
        rationale_parts.append(f"Description: {assumption['description']}")
    if assumption.get("target_operating_conditions"):
        rationale_parts.append(
            f"Target Operating Conditions: {assumption['target_operating_conditions']}"
        )
    if assumption.get("rationale"):
        rationale_parts.append(f"Rationale: {assumption['rationale']}")

    return [
        process_id,
        process_name,
        "PROCESS",
        "",
        "",
        "",
        assumption.get("proposed_industrial_process") or "",
        "",
        "\n\n".join(rationale_parts),
        _join_evidence(assumption.get("evidence")),
        reasoning_basis.get("primary") or "",
        reasoning_basis.get("secondary") or "",
        review_comments.get("overall_assessment") or "",
        _join_list(review_comments.get("strengths")),
        _join_list(review_comments.get("concerns")),
        _join_list(review_comments.get("recommendations")),
        "",
        "",
    ]


def _flow_row(process_id: str, process_name: str, record_type: str, flow: dict) -> list:
    """Build one INPUT or OUTPUT row from an InventoryFlowAssumption dict."""
    reasoning_basis = flow.get("reasoning_basis") or {}
    review_comments = flow.get("review_comments") or {}
    laboratory_value = flow.get("laboratory_value")

    return [
        process_id,
        process_name,
        record_type,
        flow.get("name") or "",
        laboratory_value if laboratory_value is not None else "",
        flow.get("laboratory_unit") or "",
        flow.get("proposed_estimation_method") or "",
        _join_list(flow.get("required_parameters")),
        flow.get("rationale") or "",
        _join_evidence(flow.get("evidence")),
        reasoning_basis.get("primary") or "",
        reasoning_basis.get("secondary") or "",
        review_comments.get("overall_assessment") or "",
        _join_list(review_comments.get("strengths")),
        _join_list(review_comments.get("concerns")),
        _join_list(review_comments.get("recommendations")),
        "",
        "",
    ]


def _autofit_columns(sheet: Worksheet, last_row: int) -> None:
    """Size each column to its longest line, capped at MAX_COLUMN_WIDTH."""
    for col_idx, header in enumerate(HEADERS, start=1):
        longest = len(header)
        for row in sheet.iter_rows(min_col=col_idx, max_col=col_idx, min_row=2, max_row=last_row):
            for cell in row:
                if cell.value:
                    longest = max(longest, max(len(line) for line in str(cell.value).split("\n")))
        sheet.column_dimensions[get_column_letter(col_idx)].width = min(
            longest + 2, MAX_COLUMN_WIDTH
        )


def export_review_package(yaml_path: Path, excel_path: Path) -> int:
    """Export the ReviewPackage YAML at yaml_path into a workbook at excel_path.

    Writes one integrated "Review Package" worksheet: for every process, a
    bolded/shaded PROCESS row followed immediately by its INPUT rows then
    its OUTPUT rows, then one blank row before the next process.

    Returns the number of processes exported.
    """
    with yaml_path.open("r", encoding="utf-8") as f:
        review_package = yaml.safe_load(f)

    processes = review_package.get("processes") or []

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Review Package"

    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = WRAP_ALIGNMENT

    current_row = 1
    for entry in processes:
        process_id = entry.get("process_id") or ""
        process_name = entry.get("process_name") or ""

        sheet.append(_process_row(entry))
        current_row += 1
        process_row_index = current_row
        for cell in sheet[process_row_index]:
            cell.font = PROCESS_FONT
            cell.fill = PROCESS_FILL
            cell.alignment = WRAP_ALIGNMENT

        inventory = entry.get("inventory_assumptions") or {}

        for flow in inventory.get("inputs") or []:
            sheet.append(_flow_row(process_id, process_name, "INPUT", flow))
            current_row += 1
            for cell in sheet[current_row]:
                cell.alignment = WRAP_ALIGNMENT

        for flow in inventory.get("outputs") or []:
            sheet.append(_flow_row(process_id, process_name, "OUTPUT", flow))
            current_row += 1
            for cell in sheet[current_row]:
                cell.alignment = WRAP_ALIGNMENT

        sheet.append([])
        current_row += 1

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{current_row}"
    _autofit_columns(sheet, current_row)

    excel_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(excel_path)

    return len(processes)


def main() -> None:
    print(f"YAML input path: {YAML_PATH}")
    print(f"Excel output path: {EXCEL_PATH}")

    count = export_review_package(YAML_PATH, EXCEL_PATH)

    print(f"Number of processes exported: {count}")


if __name__ == "__main__":
    main()
