"""
Stage 1 POC Entry Point

Simple development entry point that runs the Stage 1 LangGraph workflow
for a single hardcoded case directory and saves a visualization of the
workflow graph.

Business logic should NOT be implemented here.
"""

from pathlib import Path

from src.orchestrator.graph_builder import build_graph, export_graph
from src.orchestrator.orchestrator import run

CASE_DIR = Path("cases/starch_nanocrystals")


def main() -> None:
    final_state = run(CASE_DIR)

    print("Saving workflow visualization...")
    try:
        output_path = export_graph(build_graph(), CASE_DIR / "outputs" / "workflow.png")
        print(f"Workflow visualization saved to {output_path}")
    except Exception as exc:
        print(f"Workflow visualization could not be saved: {exc}")

    print(f"review_package is None: {final_state['review_package'] is None}")
    print("Workflow completed successfully.")


if __name__ == "__main__":
    main()
