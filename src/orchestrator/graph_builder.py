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
    human_method_selection_stage: StageCallable,
    import_human_selection_stage: StageCallable,
    parameter_requirement_review_stage: StageCallable,
    scale_up_preparation_stage: StageCallable,
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
        -> Human Method Selection Stage (interrupts here -- Milestone 1)
        -> Import Human Selection Stage
        -> Parameter Requirement Review Stage (Milestone 1)
        -> Scale-Up Preparation Stage (Milestone 2A)
        -> END

    Every stage is a fully constructed `GraphState -> GraphState`
    callable, registered directly as a LangGraph node. Human Review and
    Human Method Selection are deliberately their own nodes containing
    nothing but the interrupt: LangGraph reruns an interrupted node
    from the top on resume, so keeping the preceding export node
    separate and already-completed guarantees the workbook is written
    exactly once and is never overwritten (destroying the human's
    edits) when the workflow resumes. Reasoning/export node pairs are
    split the same way throughout (Inventory Classification / Export
    Workbook, Estimation Recommendation / Export Recommendations) so a
    future Scientific Review stage can insert a further interrupt the
    same way without restructuring any existing node.

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
    graph.add_node("human_method_selection", human_method_selection_stage)
    graph.add_node("import_human_selection", import_human_selection_stage)
    graph.add_node("parameter_requirement_review", parameter_requirement_review_stage)
    graph.add_node("scale_up_preparation", scale_up_preparation_stage)

    graph.add_edge(START, "inventory_classification")
    graph.add_edge("inventory_classification", "export_workbook")
    graph.add_edge("export_workbook", "human_review")
    graph.add_edge("human_review", "import_confirmed_inventory")
    graph.add_edge("import_confirmed_inventory", "estimation_recommendation")
    graph.add_edge("estimation_recommendation", "export_recommendations")
    graph.add_edge("export_recommendations", "human_method_selection")
    graph.add_edge("human_method_selection", "import_human_selection")
    graph.add_edge("import_human_selection", "parameter_requirement_review")
    graph.add_edge("parameter_requirement_review", "scale_up_preparation")
    graph.add_edge("scale_up_preparation", END)

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
