"""Placeholder Scientific Review Agent node for the Stage 1 LangGraph workflow.

This milestone validates LangGraph state passing only. The real agent
will review process and inventory assumptions for completeness,
plausibility, and traceability; that reasoning is out of scope here.
"""

from src.state.graph_state import GraphState


def scientific_review_agent(state: GraphState) -> GraphState:
    """Placeholder standing in for the future Scientific Review Agent.

    Prints an execution message and returns the state unchanged, without
    creating or modifying the review package.
    """
    print("Running Scientific Review Agent...")
    return state
