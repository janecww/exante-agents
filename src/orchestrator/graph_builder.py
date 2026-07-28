"""LangGraph topology construction for the Stage 1 workflow.

This module owns only the workflow topology: registering nodes, wiring
edges, and compiling the graph. Each node represents one workflow stage
(a `GraphState -> GraphState` callable) supplied by the orchestrator; this
module has no knowledge of what a stage does internally (e.g. that the
Process Evolution Stage loops over every laboratory process, or where
agent dependencies such as shared skills come from).
"""

from pathlib import Path
from typing import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.state.graph_state import GraphState

StageCallable = Callable[[GraphState], GraphState]


def build_graph(
    process_evolution_stage: StageCallable,
    scientific_review_stage: StageCallable,
) -> CompiledStateGraph:
    """Build and compile the Stage 1 workflow graph.

    Workflow: START -> Process Evolution Stage -> Scientific Review Stage -> END

    `process_evolution_stage` and `scientific_review_stage` are fully
    constructed `GraphState -> GraphState` callables, registered directly
    as LangGraph nodes.
    """
    graph = StateGraph(GraphState)
    graph.add_node("process_evolution", process_evolution_stage)
    graph.add_node("scientific_review", scientific_review_stage)

    graph.add_edge(START, "process_evolution")
    graph.add_edge("process_evolution", "scientific_review")
    graph.add_edge("scientific_review", END)

    return graph.compile()


def export_graph(graph: CompiledStateGraph, output_path: str | Path) -> Path:
    """Export a visualization of a compiled graph to output_path.

    Attempts a PNG export first. If PNG export is unavailable (e.g.
    missing optional dependencies or no network access), falls back to
    writing a Mermaid diagram (`.mmd`) instead. Visualization is best
    effort and must never interrupt workflow execution, so failures are
    caught and reported rather than raised.

    Returns the path that was actually written.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph_repr = graph.get_graph()

    png_path = output_path.with_suffix(".png")
    try:
        graph_repr.draw_mermaid_png(output_file_path=str(png_path))
        return png_path
    except Exception as exc:
        print(f"PNG export unavailable ({exc}); falling back to Mermaid diagram.")

    mmd_path = output_path.with_suffix(".mmd")
    mmd_path.write_text(graph_repr.draw_mermaid(), encoding="utf-8")
    return mmd_path
