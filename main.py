"""
Stage 1 POC Entry Point

Simple development entry point that runs the Stage 1 LangGraph workflow
for a single hardcoded case directory, saves a visualization of the
workflow graph, and provides separate `start`/`resume` entry points for
the Human-in-the-Loop interrupt around the LCI Development Workbook.

Usage:
    python main.py start   # run a new workflow, up to the review interrupt
    python main.py resume  # resume a previously interrupted workflow

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
        # sufficient here; the real stages are built inside run().
        visualization_graph = build_graph(
            _identity, _identity, _identity, _identity, _identity, _identity
        )
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
