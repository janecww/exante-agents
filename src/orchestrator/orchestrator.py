"""Workflow orchestration for the Stage 1 pLCA-agents framework.

The orchestrator owns all workflow coordination: it loads project inputs
(technology, shared skills), instantiates the shared ReviewPackage with
one empty entry per laboratory process, constructs the agents, drives
the Process Evolution Stage (looping over every laboratory process and
invoking the Process Evolution Agent once per process), drives the
Scientific Review Stage (invoking the Scientific Review Agent once on
the completed ReviewPackage), builds and executes the LangGraph
workflow, and returns the final GraphState.

The agents themselves never coordinate workflow: the Process Evolution
Agent reasons about exactly one laboratory process per call and knows
nothing about the other processes or the overall ReviewPackage; the
Scientific Review Agent reviews the completed ReviewPackage exactly once
and knows nothing about how it was produced. Both stages are LangGraph
nodes that own that coordination on the agents' behalf.
"""

from pathlib import Path

from src.agents.process_evolution import ProcessEvolutionAgent
from src.agents.scientific_review import ScientificReviewAgent
from src.models.review_package import ProcessReviewEntry, ReviewPackage
from src.models.technology import Technology
from src.orchestrator.graph_builder import build_graph
from src.state.graph_state import GraphState
from src.tools.skill_loader import load_skills
from src.tools.yaml_loader import load_yaml

SKILLS_DIR = Path("src/skills")


def _build_initial_review_package(technology: Technology) -> ReviewPackage:
    """Instantiate a ReviewPackage with one empty entry per lab process.

    Each entry contains only `process_id`/`process_name`; every other
    field remains empty until the Process Evolution Agent completes it.
    """
    return ReviewPackage(
        technology={
            "name": technology.technology.name,
            "functional_unit": technology.technology.functional_unit,
            "target_scale": technology.target_state.scale,
        },
        processes=[
            ProcessReviewEntry(process_id=process.id, process_name=process.name)
            for process in technology.processes
        ],
    )


def _run_process_evolution_stage(
    state: GraphState, agent: ProcessEvolutionAgent
) -> GraphState:
    """LangGraph node: complete one ProcessReviewEntry per lab process.

    Loops over every laboratory process in `technology`, invoking the
    Process Evolution Agent once per process, and replaces the
    corresponding entry inside the ReviewPackage with the entry the
    agent returns. The agent itself has no knowledge of this loop.
    """
    technology = state["technology"]
    review_package = state["review_package"]

    entry_index_by_process_id = {
        entry.process_id: index
        for index, entry in enumerate(review_package.processes)
    }

    for process in technology.processes:
        index = entry_index_by_process_id[process.id]
        review_package.processes[index] = agent(
            technology, process, review_package.processes[index]
        )

    return {"technology": technology, "review_package": review_package}


def _run_scientific_review_stage(
    state: GraphState, agent: ScientificReviewAgent
) -> GraphState:
    """LangGraph node: review the completed ReviewPackage exactly once."""
    technology = state["technology"]
    review_package = agent(technology, state["review_package"])

    return {"technology": technology, "review_package": review_package}


def run(case_directory: str | Path) -> GraphState:
    """Run the Stage 1 workflow for a single case directory.

    Loads `technology.yaml` from `case_directory` and the shared skills
    from `SKILLS_DIR`, instantiates the initial ReviewPackage, constructs
    the agents with the loaded skills injected, builds and executes the
    compiled LangGraph workflow, and returns the final GraphState.
    """
    case_directory = Path(case_directory)

    print("Loading technology...")
    technology = Technology(**load_yaml(case_directory / "technology.yaml"))

    print("Loading shared skills...")
    skills = load_skills(SKILLS_DIR)

    print("Instantiating review package...")
    review_package = _build_initial_review_package(technology)

    initial_state: GraphState = {
        "technology": technology,
        "review_package": review_package,
    }

    # TODO: inject a real LLM client once agents invoke the LLM.
    process_agent = ProcessEvolutionAgent(None, skills)
    review_agent = ScientificReviewAgent(None, skills)

    def process_evolution_stage(state: GraphState) -> GraphState:
        return _run_process_evolution_stage(state, process_agent)

    def scientific_review_stage(state: GraphState) -> GraphState:
        return _run_scientific_review_stage(state, review_agent)

    print("Building LangGraph...")
    graph = build_graph(process_evolution_stage, scientific_review_stage)

    return graph.invoke(initial_state)
