"""Deterministic import of the human's method selection from Worksheet 2
("Estimation Recommendations") of the reviewed LCI Development Workbook.

Reads Worksheet 2 back exactly as `export_estimation_recommendations`
wrote it, validates its structure and required columns (reusing that
module's own `HEADERS`/`SHEET_TITLE` rather than re-declaring them), and
converts every row into a `ReviewedRecommendationEntry`: the agent's own
`recommended_method`, `recommendation_rationale`,
`more_representative_method`, and `additional_information_required` are
carried over unchanged, and the "Human Selected Method ID" column is
read, validated, and resolved into a full `HumanSelectedMethod`
definition plus a `selection_source`.

Milestone 1: the human has exactly three meaningful decisions per
inventory -- accept the recommended method, accept the more
representative ("alternative") method, or select neither. This tool
enforces that constraint directly: a populated "Human Selected Method
ID" must equal this row's own `Recommended Method ID` or `More
Representative Method ID` exactly. Any other value -- even a real,
otherwise-valid method_id from the knowledge base -- is not a presented
option and raises `ValueError`; free-form substitution of a third
method is not part of this decision. If the recommended or alternative
method does not exist for a row (its ID column is blank), that option
simply cannot be matched, so it is never selectable.

This tool performs no LLM reasoning and no inference:

- A blank "Human Selected Method ID" becomes `human_selected_method =
  None`, `human_selection_status = "pending"`, and `selection_source =
  "none"` -- it is never defaulted to the agent's recommendation.
- A populated selection is validated as described above; a failure
  raises `ValueError` identifying the offending Process ID, Inventory,
  and method ID, rather than being silently corrected, ignored, or
  replaced with the recommendation.
- Every retrieved field of a valid selection (the agent-facing `rules`
  columns: method_name, tier, component, scope, operations, conditions,
  rule_or_equation, inputs, depends_on, produces; plus the derived
  tier_name) is copied verbatim from the knowledge base -- never
  duplicated or re-derived in Python (only `tier_name` is derived, by
  `src.tools.estimation_methods_knowledge_base`, not by this module).
  Once selected, the human's decision is
  authoritative: nothing downstream (including the Parameter
  Requirement Agent -- see `src.agents.parameter_requirement`) may
  replace it or propose a different method.

Rows are matched to their own data by their own cells (Process ID +
Inventory), never by worksheet row number: each row is self-contained,
so re-ordering rows in the worksheet has no effect on which data is
associated with which inventory.
"""

import re
from pathlib import Path

from openpyxl import load_workbook

from src.models.recommendation import EstimationMethodReference
from src.models.reviewed_recommendation import (
    PENDING,
    SELECTED,
    SELECTION_ALTERNATIVE,
    SELECTION_LOWER_TIER,
    SELECTION_NOT_APPLICABLE,
    SELECTION_OTHER_HIGHER_TIER,
    SELECTION_NONE,
    SELECTION_RECOMMENDED,
    HumanSelectedMethod,
    ReviewedRecommendationEntry,
    ReviewedRecommendationPackage,
)
from src.tools.export_estimation_recommendations import HEADERS, SHEET_TITLE

# Fields retrieved verbatim from the knowledge base for a validated
# human selection -- see `HumanSelectedMethod`. `tier_name` is the one
# exception: it is not a `rules` worksheet column, but a derived
# compatibility field already added by
# `src.tools.estimation_methods_knowledge_base.load_estimation_methods_knowledge_base`,
# so it is retrieved here exactly like every genuine column.
_METHOD_DEFINITION_COLUMNS = list(HumanSelectedMethod.model_fields)


def _method_lookup(estimation_methods: list[dict]) -> dict[str, dict]:
    return {row["method_id"]: row for row in estimation_methods if row.get("method_id")}


def _read_header_row(sheet) -> list:
    return [cell.value for cell in sheet[1]]


def _method_reference(
    method_id: object, method_name: object, method_lookup: dict[str, dict]
) -> EstimationMethodReference | None:
    """Rebuild an agent-produced method reference from its worksheet cells.

    Worksheet 2 does not store tier_name (see Prompt 3), so it is
    looked up here from the same authoritative knowledge base the
    agent itself validated `method_id` against -- never re-derived or
    guessed. This does not re-validate `method_id`: that already
    happened when the agent produced it (see
    `src.agents.estimation_recommendation._normalize_and_validate_method_references`);
    this import tool's own validation is reserved for the human's
    selection.
    """
    if not method_id:
        return None
    framework_row = method_lookup.get(method_id)
    return EstimationMethodReference(
        method_id=method_id,
        method_name=method_name or None,
        tier_name=framework_row.get("tier_name") if framework_row else None,
    )


_LISTED_METHOD = re.compile(r"([A-Z]+-T\d+[a-z]?) \(Tier \d\)")


def listed_other_higher_tier_methods(cell: object) -> list[str]:
    """Method IDs listed in a row's "Other Higher-Tier Methods" cell, as
    written by `src.tools.method_ranking` ("ENER-T5 (Tier 5): ...; ...").
    The "Same- or Lower-Tier Methods" and "Not Applicable (agent's reason)"
    cells use the same format."""
    return _LISTED_METHOD.findall(str(cell or ""))


listed_methods = listed_other_higher_tier_methods

_LISTED_ENTRY = re.compile(r"([A-Z]+-T\d+[a-z]?) \(Tier \d\): (.*?)(?=; [A-Z]+-T\d+[a-z]? \(Tier \d\)|$)", re.S)


def listed_method_details(cell: object) -> dict[str, str]:
    """{method_id: text after its "(Tier n): "} for a listing cell, e.g. the
    agent's reason in the "Not Applicable (agent's reason)" column."""
    return {match.group(1): match.group(2).strip() for match in _LISTED_ENTRY.finditer(str(cell or ""))}


def _resolve_human_selection(
    method_id: object,
    process_id: object,
    inventory_name: object,
    recommended_method_id: object,
    more_representative_method_id: object,
    method_lookup: dict[str, dict],
    other_higher_tier_method_ids: list[str] | None = None,
    lower_tier_method_ids: list[str] | None = None,
    not_applicable_method_ids: list[str] | None = None,
) -> tuple[HumanSelectedMethod | None, str, str]:
    """Validate and resolve one row's "Human Selected Method ID" cell.

    The human may select any rule shown for this inventory: the
    recommended method, the alternative (more-representative) method, or
    a method listed under Other Higher-Tier Methods, Same- or Lower-Tier
    Methods, or Not Applicable -- or select none. Returns `(None,
    PENDING, SELECTION_NONE)` for a blank cell -- this also covers "the
    human has not decided yet", since this milestone's model has no
    separate pending-vs-rejected distinction. For a populated cell that
    is not shown for this row -- including a real, otherwise-valid
    method_id of another category -- raises `ValueError`: it is never
    silently accepted as a free-form substitution. Otherwise
    returns the full `HumanSelectedMethod` definition, `SELECTED`, and
    the matching `selection_source`.
    """
    if not method_id:
        return None, PENDING, SELECTION_NONE

    method_id = str(method_id).strip()
    if method_id == recommended_method_id:
        selection_source = SELECTION_RECOMMENDED
    elif method_id == more_representative_method_id:
        selection_source = SELECTION_ALTERNATIVE
    elif method_id in (other_higher_tier_method_ids or []):
        selection_source = SELECTION_OTHER_HIGHER_TIER
    elif method_id in (lower_tier_method_ids or []):
        selection_source = SELECTION_LOWER_TIER
    elif method_id in (not_applicable_method_ids or []):
        selection_source = SELECTION_NOT_APPLICABLE
    else:
        raise ValueError(
            f"Invalid Human Selected Method ID {method_id!r} for Process ID "
            f"{process_id!r} / Inventory {inventory_name!r}: the human may "
            "only select a method shown for this inventory -- the recommended "
            f"method ({recommended_method_id!r}), the more representative "
            f"method ({more_representative_method_id!r}), or one listed under "
            f"Other Higher-Tier Methods ({other_higher_tier_method_ids or []}), "
            f"Same- or Lower-Tier Methods ({lower_tier_method_ids or []}) or "
            f"Not Applicable ({not_applicable_method_ids or []}); "
            "leave the cell blank to select none."
        )

    framework_row = method_lookup.get(method_id)
    if framework_row is None:
        # Defensive only: recommended_method_id / more_representative_method_id
        # were already validated against the knowledge base by the
        # Estimation Recommendation Agent before export, so this should
        # never actually happen.
        raise ValueError(
            f"Human Selected Method ID {method_id!r} for Process ID "
            f"{process_id!r} / Inventory {inventory_name!r} is not found in "
            "the estimation methods knowledge base "
            "(src/skills/scaleup_decision_framework.xlsx)."
        )

    human_selected_method = HumanSelectedMethod(
        **{column: framework_row.get(column) for column in _METHOD_DEFINITION_COLUMNS}
    )
    return human_selected_method, SELECTED, selection_source


def import_estimation_recommendations_workbook(
    workbook_path: str | Path, estimation_methods: list[dict]
) -> ReviewedRecommendationPackage:
    """Import Worksheet 2's human method selections into a structured package.

    Parameters
    ----------
    workbook_path
        The shared `lci_development_workbook.xlsx`, after Worksheet 2
        has been exported (and optionally reviewed by a human).
    estimation_methods
        Every row of `src/skills/scaleup_decision_framework.xlsx`, as
        loaded by `src.tools.excel_table_loader.load_excel_table` --
        the sole source of truth a human selection is validated
        against.

    Raises `FileNotFoundError` if the workbook does not exist, or
    `ValueError` if the "Estimation Recommendations" worksheet or its
    expected columns are missing, or if any row's "Human Selected
    Method ID" is populated but invalid (unknown method_id, or one
    belonging to a different component group than the inventory).
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
    if header_row != HEADERS:
        raise ValueError(
            f'Unexpected columns in the "{SHEET_TITLE}" worksheet of '
            f"{workbook_path}.\nExpected: {HEADERS}\nFound: {header_row}"
        )

    column_index = {name: index for index, name in enumerate(HEADERS)}
    method_lookup = _method_lookup(estimation_methods)

    entries = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row is None or all(value is None for value in row):
            continue  # skip fully blank rows (e.g. trailing rows)

        process_id = row[column_index["Process ID"]]
        inventory_name = row[column_index["Inventory"]]
        component = row[column_index["Component"]]
        recommended_method_id = row[column_index["Recommended Method ID"]]
        more_representative_method_id = row[column_index["More Representative Method ID"]]

        human_selected_method, human_selection_status, selection_source = (
            _resolve_human_selection(
                row[column_index["Human Selected Method ID"]],
                process_id,
                inventory_name,
                recommended_method_id,
                more_representative_method_id,
                method_lookup,
                listed_methods(row[column_index["Other Higher-Tier Methods (missing inputs)"]]),
                listed_methods(row[column_index["Same- or Lower-Tier Methods"]]),
                listed_methods(row[column_index["Not Applicable (agent's reason)"]]),
            )
        )

        entries.append(
            ReviewedRecommendationEntry(
                process_id=process_id,
                process_name=row[column_index["Process Name"]],
                inventory_name=inventory_name,
                component=component,
                recommended_method=_method_reference(
                    recommended_method_id,
                    row[column_index["Recommended Method"]],
                    method_lookup,
                ),
                recommendation_rationale=row[column_index["Recommendation Rationale"]],
                more_representative_method=_method_reference(
                    more_representative_method_id,
                    row[column_index["More Representative Method"]],
                    method_lookup,
                ),
                additional_information_required=row[
                    column_index["Additional Information Required"]
                ],
                other_higher_tier_methods=row[
                    column_index["Other Higher-Tier Methods (missing inputs)"]
                ],
                lower_tier_methods=row[column_index["Same- or Lower-Tier Methods"]],
                not_applicable_methods=row[column_index["Not Applicable (agent's reason)"]],
                human_selected_method=human_selected_method,
                human_selection_status=human_selection_status,
                selection_source=selection_source,
            )
        )

    return ReviewedRecommendationPackage(recommendations=entries)


def resolve_final_method(
    entry: ReviewedRecommendationEntry,
) -> HumanSelectedMethod | None:
    """The downstream-usable final method for one inventory.

    Explicit precedence: the human's selection is used whenever
    present; the agent's recommendation is never silently treated as
    human-approved. Returns `None` -- never a fallback to
    `entry.recommended_method` -- when no human selection has been made
    yet, so downstream code cannot mistake "not yet decided" for "no
    method needed". No existing downstream workflow stage currently
    calls this (Stage 1 terminates after Worksheet 2 is exported -- see
    Architecture.md); it is provided ready for a future stage to use.
    """
    return entry.human_selected_method
