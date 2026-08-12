"""
Stage 1 POC Entry Point

Simple development entry point that runs the Stage 1 LangGraph workflow
for a single hardcoded case directory, saves a visualization of the
workflow graph, and provides separate `start`/`resume` entry points for
the Human-in-the-Loop interrupts around the LCI Development Workbook.

Usage:
    python main.py start   # run a new workflow, up to the Worksheet 1 review interrupt
    python main.py resume  # resume a previously interrupted workflow

The pipeline now pauses twice (Milestone 2A: human method selection was
added after the estimation recommendation stage), so a full run calls
`resume` twice: once after editing Worksheet 1 ("Inventory
Classification"), once after entering each inventory's "Human Selected
Method ID" on Worksheet 2 ("Estimation Recommendations"). `resume`
always reports whichever interrupt is currently pending -- see
`_report` -- so simply re-running `python main.py resume` after each
round of edits is all that's needed either way.

`start` is the default if no command is given.

Business logic should NOT be implemented here.
"""

import sys
from pathlib import Path

# Ensure prompts containing non-ASCII characters (e.g. equations in the
# skill files) print correctly regardless of the terminal's codepage.
sys.stdout.reconfigure(encoding="utf-8")

from src.orchestrator.graph_builder import build_graph, export_graph
from src.orchestrator.orchestrator import resume as resume_workflow
from src.orchestrator.orchestrator import run

CASE_DIR = Path("cases/starch_nanocrystals")


def _identity(state):
    return state


def _save_visualization() -> None:
    print("Saving workflow visualization...")
    try:
        # Only the topology is drawn, so plain pass-through stages are
        # sufficient here; the real stages are built inside run(). The
        # pipeline now has 10 stages (Milestone 2A added human method
        # selection, its import, parameter requirement review, and
        # scale-up preparation after export_recommendations).
        visualization_graph = build_graph(*([_identity] * 10))
        output_path = export_graph(visualization_graph, CASE_DIR / "outputs" / "workflow.png")
        print(f"Workflow visualization saved to {output_path}")
    except Exception as exc:
        print(f"Workflow visualization could not be saved: {exc}")


def _report(final_state) -> None:
    if "__interrupt__" in final_state:
        interrupt_info = final_state["__interrupt__"][0].value
        print(interrupt_info["message"])
        print(f"Workbook: {interrupt_info['lci_workbook_path']}")
        print("Once you have saved your edits, run: python main.py resume")
        return

    confirmed_inventory = final_state["confirmed_inventory"]
    print(
        f"Confirmed inventory contains {len(confirmed_inventory.inventories)} entries."
    )
    recommendation_package = final_state["recommendation_package"]
    print(
        f"Estimation recommendations generated for {len(recommendation_package.recommendations)} entries."
    )

    reviewed_recommendation = final_state["reviewed_recommendation"]
    if reviewed_recommendation is not None:
        entries = reviewed_recommendation.recommendations
        ready = sum(
            1
            for entry in entries
            if entry.scale_up_preparation and entry.scale_up_preparation.calculation_status == "READY"
        )
        missing = sum(
            1
            for entry in entries
            if entry.scale_up_preparation
            and entry.scale_up_preparation.calculation_status == "MISSING_PARAMETERS"
        )
        not_ready = sum(
            1
            for entry in entries
            if entry.scale_up_preparation and entry.scale_up_preparation.calculation_status == "NOT_READY"
        )
        print(
            f"Scale-up preparation: {ready} ready, {missing} missing parameters, "
            f"{not_ready} not ready (no method selected)."
        )

    print("Workflow completed successfully.")


def start() -> None:
    final_state = run(CASE_DIR)
    _save_visualization()
    _report(final_state)


def resume() -> None:
    final_state = resume_workflow(CASE_DIR)
    _report(final_state)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "start"

    if command == "start":
        start()
    elif command == "resume":
        resume()
    else:
        print(f"Unknown command: {command!r}. Use 'start' or 'resume'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
