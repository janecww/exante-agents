"""LangGraph construction for the Stage 1 workflow.

Isolates graph construction (nodes, edges, compilation, visualization)
from the orchestrator, which is only responsible for invoking the
compiled graph. This keeps the future replacement of placeholder agents
with LLM-powered implementations independent of how the graph is wired.
"""

from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.process_evolution import process_evolution_agent
from src.agents.scientific_review import scientific_review_agent
from src.state.graph_state import GraphState


def build_graph() -> CompiledStateGraph:
    """Build and compile the Stage 1 workflow graph.

    Workflow: START -> Process Evolution Agent -> Scientific Review Agent -> END
    """
    graph = StateGraph(GraphState)
    graph.add_node("process_evolution", process_evolution_agent)
    graph.add_node("scientific_review", scientific_review_agent)

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
