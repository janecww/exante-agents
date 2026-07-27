"""Workflow orchestration for the Stage 1 pLCA-agents framework.

The orchestrator coordinates execution of the compiled LangGraph
workflow: it loads a case's technology input, builds the initial
GraphState, runs the graph, and returns the final state. It contains no
engineering reasoning; that responsibility belongs to the individual
agents.
"""

from pathlib import Path

from src.models.technology import Technology
from src.orchestrator.graph_builder import build_graph
from src.state.graph_state import GraphState
from src.tools.yaml_loader import load_yaml


def run(case_directory: str | Path) -> GraphState:
    """Run the Stage 1 workflow for a single case directory.

    Loads `technology.yaml` from `case_directory`, builds the initial
    GraphState with `review_package=None`, executes the compiled
    LangGraph workflow, and returns the final state.
    """
    case_directory = Path(case_directory)

    print("Loading technology...")
    technology = Technology(**load_yaml(case_directory / "technology.yaml"))
    print(technology)

    initial_state: GraphState = {
        "technology": technology,
        "review_package": None,
    }

    print("Building LangGraph...")
    graph = build_graph()

    return graph.invoke(initial_state)
