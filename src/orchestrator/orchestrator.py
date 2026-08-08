"""Workflow orchestration for the Stage 1 pLCA-agents framework.

The orchestrator owns all workflow coordination: it loads project
inputs (technology, shared skills, the estimation methods knowledge
base, the case's lab-derived parameters), constructs the Inventory
Classification Agent and the Estimation Recommendation Agent (injecting
the shared LLM callable and each agent's own dependencies), drives
every workflow stage, coordinates LangGraph's native Human-in-the-Loop
interruption and resumption, and returns the resulting GraphState. It
also logs workflow milestones to the case's `outputs/logs/workflow.log`.

Workflow:
    Inventory Classification Agent
    -> Export LCI Development Workbook (Worksheet 1)
    -> INTERRUPT (human reviews and edits the workbook)
    -> RESUME
    -> Import reviewed workbook -> ConfirmedInventoryPackage
    -> Estimation Recommendation Agent
    -> Export Estimation Recommendations (Worksheet 2)
    -> END

`run()` starts a brand-new workflow and executes it up to the human
review interrupt. `resume()` continues a previously interrupted
workflow from that exact point, using LangGraph's checkpointer to
locate where execution paused, and runs it through to completion.
Inventory Classification and the workbook export never execute again on
resume: LangGraph only reruns the node containing the pending interrupt
(Human Review, which does nothing but interrupt), never a node that
already completed. Every node is represented as its own LangGraph node
so this holds regardless of workflow order -- the same interrupt ->
review -> resume pattern a future Scientific Review stage can reuse by
adding further nodes after `export_recommendations`.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt

from config import invoke_llm
from src.agents.estimation_recommendation import EstimationRecommendationAgent
from src.agents.inventory_classification import InventoryClassificationAgent
from src.models.technology import Technology
from src.orchestrator.graph_builder import build_graph
from src.state.graph_state import GraphState
from src.tools.excel_table_loader import load_excel_table
from src.tools.export_estimation_recommendations import (
    export_estimation_recommendations,
)
from src.tools.export_inventory_classification import export_inventory_classification
from src.tools.import_confirmed_inventory import import_confirmed_inventory_workbook
from src.tools.output_writer import append_log, save_parsed
from src.tools.skill_loader import load_skills
from src.tools.yaml_loader import load_yaml

SKILLS_DIR = Path("src/skills")
LCI_WORKBOOK_FILENAME = "lci_development_workbook.xlsx"
CHECKPOINT_DB_FILENAME = "checkpoints.sqlite"

# The authoritative estimation methods knowledge base. Lives alongside
# the YAML skills but is loaded separately (see `_load_estimation_methods`)
# since `load_skills()` is YAML-only.
ESTIMATION_METHODS_FILENAME = "scaleup_decision_framework.xlsx"

# Case-specific, optional: not every case supplies lab-derived
# parameters, so its absence is not an error (see
# `_load_lab_derived_parameters`).
LAB_DERIVED_PARAMETERS_FILENAME = "lab_derived_parameters.xlsx"

# Pydantic model classes stored directly in GraphState. Explicitly
# allow-listing them lets langgraph-checkpoint's serializer round-trip
# them across process boundaries (interrupt in one `python main.py
# start` process, resume in a later `python main.py resume` process)
# without emitting its "unregistered type" deprecation warning.
_CHECKPOINT_ALLOWED_MODULES = [
    ("src.models.technology", "Technology"),
    ("src.models.inventory_classification", "InventoryClassificationPackage"),
    ("src.models.confirmed_inventory", "ConfirmedInventoryPackage"),
    ("src.models.recommendation", "RecommendationPackage"),
]


@contextmanager
def _checkpointer_for(case_directory: Path):
    """Open the case's persistent LangGraph checkpoint database.

    A SQLite-backed checkpointer is used (rather than an in-memory one)
    specifically so a workflow interrupted in one process can be
    resumed from a separate, later process -- exactly what
    `python main.py start` / `python main.py resume` require.
    """
    db_path = case_directory / "outputs" / CHECKPOINT_DB_FILENAME
    db_path.parent.mkdir(parents=True, exist_ok=True)
    serde = JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_ALLOWED_MODULES)
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        yield SqliteSaver(connection, serde=serde)
    finally:
        connection.close()


def _thread_id_for(case_directory: Path) -> str:
    """A stable LangGraph thread_id identifying one case's workflow run."""
    return str(case_directory.resolve())


def _load_estimation_methods() -> list[dict]:
    """Load the authoritative estimation methods knowledge base."""
    return load_excel_table(SKILLS_DIR / ESTIMATION_METHODS_FILENAME)


def _load_lab_derived_parameters(case_directory: Path) -> list[dict]:
    """Load the case's lab-derived parameters, if the case supplies any."""
    path = case_directory / "references" / LAB_DERIVED_PARAMETERS_FILENAME
    if not path.exists():
        return []
    return load_excel_table(path)


def _run_inventory_classification_stage(
    state: GraphState, agent: InventoryClassificationAgent
) -> GraphState:
    """LangGraph node: classify every foreground input inventory once."""
    technology = state["technology"]
    inventory_classification = agent(technology)

    return {
        "technology": technology,
        "inventory_classification": inventory_classification,
    }


def _run_export_workbook_stage(state: GraphState, case_directory: Path) -> GraphState:
    """LangGraph node: export Worksheet 1 into the shared LCI Development
    Workbook. Runs to completion exactly once -- it never reruns on
    resume, so the human's edits are never overwritten.
    """
    workbook_path = case_directory / "outputs" / "parsed" / LCI_WORKBOOK_FILENAME
    export_inventory_classification(state["inventory_classification"], workbook_path)
    append_log(case_directory, "LCI Development Workbook exported")

    return {"lci_workbook_path": str(workbook_path)}


def _run_human_review_stage(state: GraphState, case_directory: Path) -> GraphState:
    """LangGraph node: pause the workflow for human review of the workbook.

    This node does nothing but interrupt. LangGraph reruns a node's
    function from the top when the workflow resumes from an interrupt
    raised inside it, so any side effect placed before `interrupt()`
    here would repeat every time this node reruns; the log entry below
    is placed after it instead, so it only ever runs once, when the
    workflow actually resumes.
    """
    interrupt(
        {
            "message": (
                "Review and edit the LCI Development Workbook, then "
                "resume the workflow."
            ),
            "lci_workbook_path": state["lci_workbook_path"],
        }
    )
    append_log(case_directory, "Workflow resumed after human review")

    return {}


def _run_import_confirmed_inventory_stage(
    state: GraphState, case_directory: Path
) -> GraphState:
    """LangGraph node: import the reviewed workbook exactly once."""
    confirmed_inventory = import_confirmed_inventory_workbook(
        state["lci_workbook_path"]
    )
    append_log(case_directory, "Confirmed inventory imported from workbook")

    save_parsed(
        case_directory, "confirmed_inventory.yaml", confirmed_inventory.model_dump()
    )
    append_log(case_directory, "Parsed confirmed inventory saved")

    return {"confirmed_inventory": confirmed_inventory}


def _run_estimation_recommendation_stage(
    state: GraphState, agent: EstimationRecommendationAgent
) -> GraphState:
    """LangGraph node: recommend an estimation method for every confirmed
    inventory. Consumes only `technology` (process context) and
    `confirmed_inventory` from state -- never Excel directly.
    """
    recommendation_package = agent(state["technology"], state["confirmed_inventory"])

    return {"recommendation_package": recommendation_package}


def _run_export_recommendations_stage(
    state: GraphState, case_directory: Path
) -> GraphState:
    """LangGraph node: append Worksheet 2 to the shared workbook.

    Worksheet 1 ("Inventory Classification") is left untouched.
    """
    export_estimation_recommendations(
        state["recommendation_package"], state["lci_workbook_path"]
    )
    append_log(case_directory, "Estimation recommendations exported to workbook")

    return {}


def _build_case_graph(
    case_directory: Path,
    classification_agent: InventoryClassificationAgent,
    recommendation_agent: EstimationRecommendationAgent,
    checkpointer,
):
    """Wire every stage (with its dependencies closed over) into one graph."""

    def inventory_classification_stage(state: GraphState) -> GraphState:
        return _run_inventory_classification_stage(state, classification_agent)

    def export_workbook_stage(state: GraphState) -> GraphState:
        return _run_export_workbook_stage(state, case_directory)

    def human_review_stage(state: GraphState) -> GraphState:
        return _run_human_review_stage(state, case_directory)

    def import_confirmed_inventory_stage(state: GraphState) -> GraphState:
        return _run_import_confirmed_inventory_stage(state, case_directory)

    def estimation_recommendation_stage(state: GraphState) -> GraphState:
        return _run_estimation_recommendation_stage(state, recommendation_agent)

    def export_recommendations_stage(state: GraphState) -> GraphState:
        return _run_export_recommendations_stage(state, case_directory)

    return build_graph(
        inventory_classification_stage,
        export_workbook_stage,
        human_review_stage,
        import_confirmed_inventory_stage,
        estimation_recommendation_stage,
        export_recommendations_stage,
        checkpointer=checkpointer,
    )


def _build_agents(
    case_directory: Path,
) -> tuple[InventoryClassificationAgent, EstimationRecommendationAgent]:
    """Construct both agents with their dependencies injected.

    Called identically by `run()` and `resume()` so the graph topology
    -- required to match across both -- is wired the same way in both
    processes. Constructing `EstimationRecommendationAgent` in `run()`
    is cheap (no LLM call happens at construction time) even though it
    will only actually be invoked after `resume()`.
    """
    skills = load_skills(SKILLS_DIR)
    estimation_methods = _load_estimation_methods()
    lab_derived_parameters = _load_lab_derived_parameters(case_directory)

    classification_agent = InventoryClassificationAgent(
        invoke_llm, skills, case_directory
    )
    recommendation_agent = EstimationRecommendationAgent(
        invoke_llm, skills, estimation_methods, lab_derived_parameters, case_directory
    )
    return classification_agent, recommendation_agent


def run(case_directory: str | Path) -> GraphState:
    """Start a new Stage 1 workflow run for a case directory.

    Loads `technology.yaml` from `case_directory` and every agent's
    shared dependencies, constructs both agents, and executes the
    workflow up to the human review interrupt. The returned dict
    contains an `"__interrupt__"` key when paused (the normal outcome
    of `run()`); use `resume()` afterward to continue.
    """
    case_directory = Path(case_directory)
    append_log(case_directory, "Workflow started")

    print("Loading technology...")
    technology = Technology(**load_yaml(case_directory / "technology.yaml"))

    print("Loading shared skills and knowledge bases...")
    classification_agent, recommendation_agent = _build_agents(case_directory)

    initial_state: GraphState = {
        "technology": technology,
        "inventory_classification": None,
        "confirmed_inventory": None,
        "lci_workbook_path": None,
        "recommendation_package": None,
    }

    config = {"configurable": {"thread_id": _thread_id_for(case_directory)}}

    print("Building LangGraph...")
    with _checkpointer_for(case_directory) as checkpointer:
        graph = _build_case_graph(
            case_directory, classification_agent, recommendation_agent, checkpointer
        )
        final_state = graph.invoke(initial_state, config=config)

    if "__interrupt__" in final_state:
        append_log(case_directory, "Workflow interrupted for human review")

    return final_state


def resume(case_directory: str | Path) -> GraphState:
    """Resume a previously interrupted Stage 1 workflow run.

    Loads the persisted LangGraph checkpoint for `case_directory` and
    continues execution from the interruption point: imports the
    reviewed workbook, constructs the `ConfirmedInventoryPackage`, runs
    the Estimation Recommendation Agent, appends its worksheet to the
    shared workbook, and completes the workflow. Inventory
    Classification and the workbook export do not run again -- only the
    interrupted Human Review node (which does nothing but resume) and
    the nodes after it execute.

    Raises `RuntimeError` if no interrupted workflow checkpoint is
    found for this case directory.
    """
    case_directory = Path(case_directory)

    # Reconstructed only to wire the graph identically to `run()`; since
    # Inventory Classification already completed, it will not be
    # invoked again.
    classification_agent, recommendation_agent = _build_agents(case_directory)
    config = {"configurable": {"thread_id": _thread_id_for(case_directory)}}

    with _checkpointer_for(case_directory) as checkpointer:
        graph = _build_case_graph(
            case_directory, classification_agent, recommendation_agent, checkpointer
        )

        snapshot = graph.get_state(config)
        if not snapshot.next:
            raise RuntimeError(
                f"No interrupted workflow found for {case_directory}. "
                "Run `python main.py start` first."
            )

        final_state = graph.invoke(Command(resume="reviewed"), config=config)

    append_log(case_directory, "Workflow completed")

    return final_state
