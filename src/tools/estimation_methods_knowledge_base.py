"""Loader for the estimation methods knowledge base
(`src/skills/scaleup_decision_framework.xlsx`, framework v2).

The workbook has three sheets (see its `how_to_use` sheet):

- `rules`: the only sheet any agent sees. One row per method: component,
  tier, method_id, method_name, scope, operations, conditions,
  rule_or_equation, inputs, depends_on, produces.
- `documentation`: literature basis and caveats per rule, for people
  only. Loaded separately by `load_framework_documentation`, never
  passed to a prompt.
- `how_to_use`: human-readable explanation, never read by code.

This module performs no reasoning. On top of the raw rows it adds:

1. `input_records`: the rule's `inputs` parsed into ``{name, tag,
   default}`` records by `src.skills.availability.parse_inputs`. A
   malformed `inputs` cell raises `ValueError` at load time.
2. `required_inputs`: the input names joined by "; " -- a derived
   compatibility field for the stand-alone scale-up prototype
   (`src.tools.scale_up_preparation` / `scale_up_calculation`), which is
   not part of the workflow.
3. `tier_name`: a descriptive label for the numeric tier
   (`TIER_NAME_BY_NUMBER`), used in output schemas and worksheets.
"""

from functools import lru_cache
from pathlib import Path

from src.skills.availability import parse_inputs
from src.tools.excel_table_loader import load_excel_table

RULES_SHEET_NAME = "rules"
DOCUMENTATION_SHEET_NAME = "documentation"

# The agent-facing columns of the `rules` sheet, in sheet order.
RULE_COLUMNS = [
    "component",
    "tier",
    "method_id",
    "method_name",
    "scope",
    "operations",
    "conditions",
    "rule_or_equation",
    "inputs",
    "depends_on",
    "produces",
]

TIER_NAME_BY_NUMBER = {
    1: "omission / cut-off",
    2: "proxy substitution",
    3: "linear extrapolation",
    4: "heuristic default factor",
    5: "empirical scaling law",
    6: "engineering equation",
}


def load_estimation_methods_knowledge_base(path: str | Path) -> list[dict]:
    """Load every row of the `rules` sheet, with derived fields added.

    Raises `FileNotFoundError` if `path` does not exist, and
    `ValueError` if the sheet's columns differ from `RULE_COLUMNS` or a
    rule's `inputs` cell is malformed.
    """
    rows = load_excel_table(path, sheet_name=RULES_SHEET_NAME)
    if rows and list(rows[0].keys()) != RULE_COLUMNS:
        raise ValueError(
            f"Unexpected columns in the '{RULES_SHEET_NAME}' sheet of {path}.\n"
            f"Expected: {RULE_COLUMNS}\nFound: {list(rows[0].keys())}"
        )
    for row in rows:
        try:
            row["input_records"] = parse_inputs(row.get("inputs"))
        except ValueError as exc:
            raise ValueError(f"{row.get('method_id')}: {exc}") from exc
        row["required_inputs"] = "; ".join(record["name"] for record in row["input_records"])
        row["tier_name"] = TIER_NAME_BY_NUMBER.get(row.get("tier"))
    return rows


def load_framework_documentation(path: str | Path) -> dict[str, dict]:
    """The `documentation` sheet, keyed by method_id (people-facing only)."""
    rows = load_excel_table(path, sheet_name=DOCUMENTATION_SHEET_NAME)
    return {row["method_id"]: row for row in rows if row.get("method_id")}


DEFAULT_FRAMEWORK_PATH = Path(__file__).resolve().parents[1] / "skills" / "scaleup_decision_framework.xlsx"


@lru_cache(maxsize=1)
def framework_documentation() -> dict[str, dict]:
    """The documentation sheet of the project's framework, loaded once.

    Used only by the stand-alone scale-up prototype; never passed to a
    prompt."""
    return load_framework_documentation(DEFAULT_FRAMEWORK_PATH)

