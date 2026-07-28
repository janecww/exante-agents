"""Workflow orchestration for the Stage 1 pLCA-agents framework.

The orchestrator owns dependency construction for the workflow: it loads
project inputs (technology) and shared resources (skills), constructs
the agent instances, builds the graph from those instances, and executes
the workflow, returning the final state. It contains no engineering
reasoning; that responsibility belongs to the individual agents.
"""

from pathlib import Path

from src.agents.process_evolution import ProcessEvolutionAgent
from src.agents.scientific_review import ScientificReviewAgent
from src.models.technology import Technology
from src.orchestrator.graph_builder import build_graph
from src.state.graph_state import GraphState
from src.tools.skill_loader import load_skills
from src.tools.yaml_loader import load_yaml

SKILLS_DIR = Path("src/skills")


def run(case_directory: str | Path) -> GraphState:
    """Run the Stage 1 workflow for a single case directory.

    Loads `technology.yaml` from `case_directory` and the shared skills
    from `SKILLS_DIR`, builds the initial GraphState with
    `review_package=None`, constructs the placeholder agents with the
    loaded skills injected, builds and executes the compiled LangGraph
    workflow, and returns the final state.
    """
    case_directory = Path(case_directory)

    print("Loading technology...")
    technology = Technology(**load_yaml(case_directory / "technology.yaml"))

    print("Loading shared skills...")
    skills = load_skills(SKILLS_DIR)

    initial_state: GraphState = {
        "technology": technology,
        "review_package": None,
    }

    # TODO: inject a real LLM client once agents invoke the LLM.
    process_agent = ProcessEvolutionAgent(None, skills)
    review_agent = ScientificReviewAgent(None, skills)

    print("Building LangGraph...")
    graph = build_graph(process_agent, review_agent)

    return graph.invoke(initial_state)
