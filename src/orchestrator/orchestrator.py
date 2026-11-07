"""Workflow orchestration for the Stage 1 pLCA-agents framework.

The orchestrator owns all workflow coordination: it loads project
inputs -- the case's unified Laboratory Case Workbook (technology +
lab-derived parameters, see `src.tools.laboratory_case_workbook`),
shared skills, and the estimation methods knowledge base -- constructs
the Inventory Classification Agent, the Estimation Recommendation
Agent, and the Parameter Requirement Agent (injecting the shared LLM
callable and each agent's own dependencies), drives every workflow
stage, coordinates LangGraph's native Human-in-the-Loop interruption
and resumption, and returns the resulting GraphState. It also logs
workflow milestones to the case's `outputs/logs/workflow.log`.

The case's laboratory input is a single canonical source: every agent
that needs process quantities or lab-derived parameters gets them from
the same `laboratory_case_workbook.xlsx`, loaded exactly once per
`run()`/`resume()` call -- there is no separate `technology.yaml` or
standalone `lab_derived_parameters.xlsx` read anywhere in this
pipeline, so there is no risk of one agent seeing stale or
inconsistent laboratory evidence relative to another.

Workflow:
    Inventory Classification Agent
    -> Export LCI Development Workbook (Worksheet 1)
    -> INTERRUPT (human reviews and edits the workbook)
    -> RESUME
    -> Import reviewed workbook -> ConfirmedInventoryPackage
    -> Estimation Recommendation Agent
    -> Export Estimation Recommendations (Worksheet 2)
    -> INTERRUPT (human selects, per inventory, the recommended method,
       the more representative method, or neither -- Milestone 1)
    -> RESUME
    -> Import human method selection -> ReviewedRecommendationPackage
    -> Parameter Requirement Agent (Milestone 1; skipped for any
       inventory with no selected method)
    -> Export Parameter Review (Worksheet 3, appended to the same
       workbook, alongside the existing reviewed_recommendation.yaml)
    -> END

Stage 1 ends at the Parameter Requirement Agent. The scale-up
calculation prototype (`src.tools.scale_up_preparation`, and the
standalone Milestone 2B demo under `src.tools.scale_up_*` /
`run_scale_up_demo.py`) is deliberately not wired into this graph --
it remains available as future, standalone Stage 2 work, but is never
constructed or invoked by `run()`/`resume()`.

`run()` starts a brand-new workflow and executes it up to the first
human review interrupt. `resume()` continues a previously interrupted
workflow from whichever interrupt is currently pending, using
LangGraph's checkpointer to locate where execution paused, and runs it
until either the *next* interrupt or the end of the workflow -- since
this pipeline now pauses twice (once for Worksheet 1 review, once for
Worksheet 2 method selection), `resume()` must be called twice in a
full run: once after editing Worksheet 1, once after editing Worksheet
2's "Human Selected Method ID" column. Every already-completed node
never reruns: LangGraph only reruns the node containing whichever
interrupt is currently pending, never a node that already completed.
Every stage is represented as its own LangGraph node so this holds
regardless of workflow order -- the same interrupt -> review -> resume
pattern a future stage can reuse by adding further nodes after
`parameter_requirement_review`.
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
from src.agents.parameter_requirement import (
    ParameterRequirementAgent,
    review_parameter_requirements,
)
from src.models.technology import Technology
from src.orchestrator.graph_builder import build_graph
from src.state.graph_state import GraphState
from src.tools.estimation_methods_knowledge_base import (
    load_estimation_methods_knowledge_base,
)
from src.tools.export_estimation_recommendations import (
    export_estimation_recommendations,
)
from src.tools.export_inventory_classification import export_inventory_classification
from src.tools.export_parameter_review import export_parameter_review
from src.tools.import_confirmed_inventory import import_confirmed_inventory_workbook
from src.tools.import_estimation_recommendations import (
    import_estimation_recommendations_workbook,
)
from src.tools.laboratory_case_workbook import import_laboratory_case_workbook
from src.tools.output_writer import append_log, save_parsed
from src.tools.skill_loader import load_skills

SKILLS_DIR = Path("src/skills")
LCI_WORKBOOK_FILENAME = "lci_development_workbook.xlsx"
CHECKPOINT_DB_FILENAME = "checkpoints.sqlite"

# The case's single canonical laboratory input: process inventory
# (technology) plus lab-derived parameters, combined into one workbook.
# Replaces the former technology.yaml + references/lab_derived_parameters.xlsx
# split -- see `src.tools.laboratory_case_workbook`.
LABORATORY_CASE_WORKBOOK_FILENAME = "laboratory_case_workbook.xlsx"

# The authoritative estimation methods knowledge base. Lives alongside
# the YAML skills but is loaded separately (see `_load_estimation_methods`)
# since `load_skills()` is YAML-only. Its method rows live on the
# `rules` worksheet -- see `src.tools.estimation_methods_knowledge_base`.
ESTIMATION_METHODS_FILENAME = "scaleup_decision_framework.xlsx"

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
    ("src.models.reviewed_recommendation", "ReviewedRecommendationPackage"),
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
    return load_estimation_methods_knowledge_base(SKILLS_DIR / ESTIMATION_METHODS_FILENAME)


def _load_laboratory_case(case_directory: Path) -> tuple[Technology, list[dict]]:
    """Load the case's canonical laboratory input.

    Reads the single unified `laboratory_case_workbook.xlsx`, returning
    the `Technology` model (process inventory) and the lab-derived
    parameter rows together -- both types of laboratory evidence come
    from this one file, so every agent that consumes either is
    guaranteed to see the same laboratory input.
    """
    path = case_directory / LABORATORY_CASE_WORKBOOK_FILENAME
    return import_laboratory_case_workbook(path)


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


def _run_human_method_selection_stage(
    state: GraphState, case_directory: Path
) -> GraphState:
    """LangGraph node: pause the workflow for human method selection.

    This node does nothing but interrupt -- mirrors
    `_run_human_review_stage`. The human edits Worksheet 2's "Human
    Selected Method ID" column (reusing the existing Excel HITL
    mechanism; see `src.tools.export_estimation_recommendations`),
    choosing, per inventory, the recommended method, the more
    representative method, or neither.
    """
    interrupt(
        {
            "message": (
                "Review Worksheet 2 (\"Estimation Recommendations\") and, "
                "for each inventory, enter its 'Human Selected Method ID' "
                "-- the Recommended Method ID, the More Representative "
                "Method ID, or leave it blank to select neither -- then "
                "resume the workflow."
            ),
            "lci_workbook_path": state["lci_workbook_path"],
        }
    )
    append_log(case_directory, "Workflow resumed after human method selection")

    return {}


def _run_import_human_selection_stage(
    state: GraphState, case_directory: Path, estimation_methods: list[dict]
) -> GraphState:
    """LangGraph node: import the human's method selection exactly once."""
    reviewed_recommendation = import_estimation_recommendations_workbook(
        state["lci_workbook_path"], estimation_methods
    )
    append_log(case_directory, "Human method selection imported from workbook")

    return {"reviewed_recommendation": reviewed_recommendation}


def _run_parameter_requirement_review_stage(
    state: GraphState,
    agent: ParameterRequirementAgent,
    lab_derived_parameters: list[dict],
    case_directory: Path,
) -> GraphState:
    """LangGraph node: review parameter readiness for every inventory
    with a human-selected method (Milestone 1). Skipped entirely for
    any inventory where the human selected neither proposed method --
    see `review_parameter_requirements`. This is Stage 1's final node:
    its result is persisted as `reviewed_recommendation.yaml` (the
    machine-readable record) and as the "Parameter Review" worksheet
    appended to the same shared `lci_development_workbook.xlsx` (the
    human-readable one) -- both derived from the same structured
    result, neither replacing the other.
    """
    reviewed_recommendation = review_parameter_requirements(
        state["technology"],
        lab_derived_parameters,
        state["reviewed_recommendation"],
        agent,
        recommendation_package=state.get("recommendation_package"),
    )
    append_log(case_directory, "Parameter requirement review completed")

    save_parsed(
        case_directory,
        "reviewed_recommendation.yaml",
        reviewed_recommendation.model_dump(),
    )
    append_log(case_directory, "Parsed reviewed recommendation saved")

    export_parameter_review(reviewed_recommendation, state["lci_workbook_path"])
    append_log(case_directory, "Parameter review exported to workbook")

    return {"reviewed_recommendation": reviewed_recommendation}


def _build_case_graph(
    case_directory: Path,
    classification_agent: InventoryClassificationAgent,
    recommendation_agent: EstimationRecommendationAgent,
    parameter_requirement_agent: ParameterRequirementAgent,
    lab_derived_parameters: list[dict],
    estimation_methods: list[dict],
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

    def human_method_selection_stage(state: GraphState) -> GraphState:
        return _run_human_method_selection_stage(state, case_directory)

    def import_human_selection_stage(state: GraphState) -> GraphState:
        return _run_import_human_selection_stage(state, case_directory, estimation_methods)

    def parameter_requirement_review_stage(state: GraphState) -> GraphState:
        return _run_parameter_requirement_review_stage(
            state, parameter_requirement_agent, lab_derived_parameters, case_directory
        )

    return build_graph(
        inventory_classification_stage,
        export_workbook_stage,
        human_review_stage,
        import_confirmed_inventory_stage,
        estimation_recommendation_stage,
        export_recommendations_stage,
        human_method_selection_stage,
        import_human_selection_stage,
        parameter_requirement_review_stage,
        checkpointer=checkpointer,
    )


def _build_agents(
    case_directory: Path, lab_derived_parameters: list[dict]
) -> tuple[
    InventoryClassificationAgent,
    EstimationRecommendationAgent,
    ParameterRequirementAgent,
    list[dict],
]:
    """Construct every agent with its dependencies injected.

    Called identically by `run()` and `resume()` so the graph topology
    -- required to match across both -- is wired the same way in both
    processes. Constructing an agent in `run()` is cheap (no LLM call
    happens at construction time) even though some will only actually
    be invoked after a later `resume()`. `lab_derived_parameters` is
    passed in rather than reloaded here so every agent is guaranteed to
    see laboratory evidence read from the same
    `laboratory_case_workbook.xlsx` load (see `_load_laboratory_case`).
    `estimation_methods` is also returned so the caller can wire the
    (non-agent, deterministic) import-human-selection stage closure
    without loading the knowledge base a second time.
    """
    skills = load_skills(SKILLS_DIR)
    estimation_methods = _load_estimation_methods()

    classification_agent = InventoryClassificationAgent(
        invoke_llm, skills, case_directory
    )
    recommendation_agent = EstimationRecommendationAgent(
        invoke_llm, skills, estimation_methods, lab_derived_parameters, case_directory
    )
    parameter_requirement_agent = ParameterRequirementAgent(invoke_llm, case_directory)
    return (
        classification_agent,
        recommendation_agent,
        parameter_requirement_agent,
        estimation_methods,
    )


def run(case_directory: str | Path) -> GraphState:
    """Start a new Stage 1 workflow run for a case directory.

    Loads the case's unified `laboratory_case_workbook.xlsx` and every
    agent's shared dependencies, constructs every agent, and executes
    the workflow up to the first human review interrupt. The returned
    dict contains an `"__interrupt__"` key when paused (the normal
    outcome of `run()`); use `resume()` afterward to continue -- twice,
    for a full run, since this pipeline pauses twice (see module
    docstring).
    """
    case_directory = Path(case_directory)
    append_log(case_directory, "Workflow started")

    print("Loading laboratory case workbook...")
    technology, lab_derived_parameters = _load_laboratory_case(case_directory)

    print("Loading shared skills and knowledge bases...")
    (
        classification_agent,
        recommendation_agent,
        parameter_requirement_agent,
        estimation_methods,
    ) = _build_agents(case_directory, lab_derived_parameters)

    initial_state: GraphState = {
        "technology": technology,
        "inventory_classification": None,
        "confirmed_inventory": None,
        "lci_workbook_path": None,
        "recommendation_package": None,
        "reviewed_recommendation": None,
    }

    config = {"configurable": {"thread_id": _thread_id_for(case_directory)}}

    print("Building LangGraph...")
    with _checkpointer_for(case_directory) as checkpointer:
        graph = _build_case_graph(
            case_directory,
            classification_agent,
            recommendation_agent,
            parameter_requirement_agent,
            lab_derived_parameters,
            estimation_methods,
            checkpointer,
        )
        final_state = graph.invoke(initial_state, config=config)

    if "__interrupt__" in final_state:
        append_log(case_directory, "Workflow interrupted for human review")

    return final_state


def resume(case_directory: str | Path) -> GraphState:
    """Resume a previously interrupted Stage 1 workflow run.

    Loads the persisted LangGraph checkpoint for `case_directory` and
    continues execution from whichever interrupt is currently pending.
    This pipeline pauses twice, so a full run calls `resume()` twice:

    - First call: imports the reviewed Worksheet 1 workbook, constructs
      `ConfirmedInventoryPackage`, runs the Estimation Recommendation
      Agent, appends Worksheet 2 to the shared workbook, and then
      pauses again at the human method selection interrupt -- the
      returned state contains `"__interrupt__"` once more.
    - Second call (after the human has edited Worksheet 2's "Human
      Selected Method ID" column): imports the human's selection,
      constructs `ReviewedRecommendationPackage`, runs the Parameter
      Requirement Agent for every selected inventory, and completes
      the workflow -- Stage 1 ends here.

    Earlier, already-completed nodes never rerun regardless of which
    interrupt is pending -- only the node containing that interrupt
    (rerun from its top) and the nodes after it execute.

    Raises `RuntimeError` if no interrupted workflow checkpoint is
    found for this case directory.
    """
    case_directory = Path(case_directory)

    # Reconstructed only to wire the graph identically to `run()`;
    # already-completed stages will not be invoked again. `technology`
    # itself is restored from the checkpoint, not reloaded here --
    # only `lab_derived_parameters` is needed, for the agents that
    # consume it.
    _, lab_derived_parameters = _load_laboratory_case(case_directory)
    (
        classification_agent,
        recommendation_agent,
        parameter_requirement_agent,
        estimation_methods,
    ) = _build_agents(case_directory, lab_derived_parameters)
    config = {"configurable": {"thread_id": _thread_id_for(case_directory)}}

    with _checkpointer_for(case_directory) as checkpointer:
        graph = _build_case_graph(
            case_directory,
            classification_agent,
            recommendation_agent,
            parameter_requirement_agent,
            lab_derived_parameters,
            estimation_methods,
            checkpointer,
        )

        snapshot = graph.get_state(config)
        if not snapshot.next:
            raise RuntimeError(
                f"No interrupted workflow found for {case_directory}. "
                "Run `python main.py start` first."
            )

        final_state = graph.invoke(Command(resume="reviewed"), config=config)

    if "__interrupt__" in final_state:
        append_log(case_directory, "Workflow interrupted for human method selection")
    else:
        append_log(case_directory, "Workflow completed")

    return final_state
