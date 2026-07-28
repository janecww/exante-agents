"""
Stage 1 POC Entry Point

Simple development entry point that runs the Stage 1 LangGraph workflow
for a single hardcoded case directory and saves a visualization of the
workflow graph.

Business logic should NOT be implemented here.
"""

import sys
from pathlib import Path

# Ensure prompts containing non-ASCII characters (e.g. equations in the
# skill files) print correctly regardless of the terminal's codepage.
sys.stdout.reconfigure(encoding="utf-8")

from src.orchestrator.graph_builder import build_graph, export_graph
from src.orchestrator.orchestrator import run

CASE_DIR = Path("cases/starch_nanocrystals")


def main() -> None:
    final_state = run(CASE_DIR)

    print("Saving workflow visualization...")
    try:
        # Only the topology is drawn, so plain pass-through stages are
        # sufficient here; the real stages are built inside run().
        visualization_graph = build_graph(lambda state: state, lambda state: state)
        output_path = export_graph(visualization_graph, CASE_DIR / "outputs" / "workflow.png")
        print(f"Workflow visualization saved to {output_path}")
    except Exception as exc:
        print(f"Workflow visualization could not be saved: {exc}")

    review_package = final_state["review_package"]
    print(f"Review package contains {len(review_package.processes)} process entries.")
    print("Workflow completed successfully.")


if __name__ == "__main__":
    main()
