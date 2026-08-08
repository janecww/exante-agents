"""LangGraph topology construction for the Stage 1 workflow.

This module owns only the workflow topology: registering nodes, wiring
edges, and compiling the graph (optionally with a checkpointer for
Human-in-the-Loop interruption). Each node represents one workflow
stage (a `GraphState -> GraphState` callable) supplied by the
orchestrator; this module has no knowledge of what a stage does
internally (e.g. that the Human Review Stage calls LangGraph's
`interrupt()`, or where agent dependencies such as shared skills come
from).
"""

from pathlib import Path
from typing import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.state.graph_state import GraphState

StageCallable = Callable[[GraphState], GraphState]


def build_graph(
    inventory_classification_stage: StageCallable,
    export_workbook_stage: StageCallable,
    human_review_stage: StageCallable,
    import_confirmed_inventory_stage: StageCallable,
    estimation_recommendation_stage: StageCallable,
    export_recommendations_stage: StageCallable,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build and compile the Stage 1 workflow graph.

    Workflow:
        START
        -> Inventory Classification Stage
        -> Export Workbook Stage (Worksheet 1)
        -> Human Review Stage (interrupts here)
        -> Import Confirmed Inventory Stage
        -> Estimation Recommendation Stage
        -> Export Recommendations Stage (Worksheet 2)
        -> END

    Every stage is a fully constructed `GraphState -> GraphState`
    callable, registered directly as a LangGraph node. Human Review is
    deliberately its own node containing nothing but the interrupt:
    LangGraph reruns an interrupted node from the top on resume, so
    keeping Export Workbook as a separate, already-completed node
    guarantees the workbook is written exactly once and is never
    overwritten (destroying the human's edits) when the workflow
    resumes. Estimation Recommendation and Export Recommendations
    follow the same reasoning/export split as Inventory Classification
    and Export Workbook -- ready for a future Human Review interrupt to
    be inserted after Export Recommendations without restructuring
    either node.

    `checkpointer` persists graph state so the workflow can be
    interrupted in one process and resumed from a separate one later
    (see `src.orchestrator.orchestrator`). Passing `None` (the default)
    compiles an uncheckpointed graph, which is sufficient for
    topology-only uses such as visualization export.
    """
    graph = StateGraph(GraphState)
    graph.add_node("inventory_classification", inventory_classification_stage)
    graph.add_node("export_workbook", export_workbook_stage)
    graph.add_node("human_review", human_review_stage)
    graph.add_node("import_confirmed_inventory", import_confirmed_inventory_stage)
    graph.add_node("estimation_recommendation", estimation_recommendation_stage)
    graph.add_node("export_recommendations", export_recommendations_stage)

    graph.add_edge(START, "inventory_classification")
    graph.add_edge("inventory_classification", "export_workbook")
    graph.add_edge("export_workbook", "human_review")
    graph.add_edge("human_review", "import_confirmed_inventory")
    graph.add_edge("import_confirmed_inventory", "estimation_recommendation")
    graph.add_edge("estimation_recommendation", "export_recommendations")
    graph.add_edge("export_recommendations", END)

    return graph.compile(checkpointer=checkpointer)


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
