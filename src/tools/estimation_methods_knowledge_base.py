"""Loader for the authoritative estimation methods knowledge base
(`src/skills/scaleup_decision_framework.xlsx`), the "new" (2026-08)
`rules`/`how_to_use` workbook format that replaced the original
single-sheet `scaleup_decision_framework` worksheet.

This is a thin wrapper around the generic, deterministic
`src.tools.excel_table_loader.load_excel_table` -- it performs no
reasoning and never invents a method -- but it owns two pieces of
domain knowledge specific to this one workbook that would otherwise
have to be duplicated at every call site:

1. The method rows live on the `rules` worksheet, not the workbook's
   first/active sheet (that is `how_to_use`, human-readable
   documentation of how this code uses the `rules` sheet and which
   framework logic is not implemented -- not a data table, and never
   read by any agent). Every caller must therefore select the `rules`
   sheet explicitly.

2. `tier_name` compatibility: the current workbook format numbers each
   method's tier (1-6) rather than naming it, but every consumer of
   this knowledge base written before this format change --
   `EstimationMethodReference.tier_name` /
   `HumanSelectedMethod.tier_name` (LLM-facing and human-selection
   schemas), the "Tier" column of the "Parameter Review" worksheet, and
   the still-present (not wired into the Stage 1 graph)
   `src/tools/scale_up_calculation.py` Milestone 2B prototype -- expects
   a descriptive `tier_name` string on every row, e.g. "linear
   extrapolation". Rather than guess a naming, `TIER_NAME_BY_NUMBER`
   below was derived by cross-referencing every one of the 36
   method_ids shared between the retired single-sheet workbook (which
   had both a numeric position and a `tier_name` string per row) and
   this format: every method_id's numeric tier and its old `tier_name`
   matched up 1:1 and with no exceptions (verified programmatically,
   not assumed), so this mapping is a verified equivalence, not a
   guess. `load_estimation_methods_knowledge_base` uses it to add a
   `tier_name` key to every row so every existing consumer keeps
   working unchanged; new Stage 1 code should prefer the row's own,
   authoritative `tier` (int) field directly instead.
"""

from pathlib import Path

from src.tools.excel_table_loader import load_excel_table

RULES_SHEET_NAME = "rules"

# Verified 1:1 against the retired workbook's tier_name/method_id
# pairs -- see this module's docstring. Do not extend or reinterpret
# without re-verifying against the framework's own tier cascade
# (`how_to_use`, section 1, lists the same names).
TIER_NAME_BY_NUMBER = {
    1: "omission / cut-off",
    2: "proxy substitution",
    3: "linear extrapolation",
    4: "heuristic default factor",
    5: "empirical scaling law",
    6: "engineering equation",
}


def load_estimation_methods_knowledge_base(path: str | Path) -> list[dict]:
    """Load every row of the `rules` worksheet, with `tier_name` added.

    Args:
        path: Path to the estimation methods knowledge base workbook
            (`src/skills/scaleup_decision_framework.xlsx`).

    Returns:
        One dict per method row, keyed by every column the `rules`
        worksheet defines (`component`, `tier`, `method_id`,
        `method_name`, `operation_scope`, `applies_when`,
        `rule_or_equation`, `required_inputs`, `input_sourcing`,
        `sequence_with`, `produces`, `bias_direction`,
        `assumptions_to_log`, `escalate_if`, `confidence`, `reference`,
        `reference_note`, `url`, `limitations`, `scope_gap_flag`), plus
        a derived `tier_name` (see module docstring). Raises
        `FileNotFoundError` if `path` does not exist (propagated from
        `load_excel_table`).
    """
    rows = load_excel_table(path, sheet_name=RULES_SHEET_NAME)
    for row in rows:
        row["tier_name"] = TIER_NAME_BY_NUMBER.get(row.get("tier"))
    return rows
