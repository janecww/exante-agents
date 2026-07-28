"""Process Evolution Agent node for the Stage 1 LangGraph workflow.

The Process Evolution Agent develops prospective industrial process and
foreground inventory assumptions from laboratory-scale technologies.
Shared Stage 1 skills and an LLM client are injected by the orchestrator
during construction rather than loaded by the agent itself. The class
implements ``__call__`` so an instance can be registered directly as a
LangGraph node.

Current milestone:
    Agent -> build prompt -> print prompt -> return unchanged state

    The agent extracts `technology` from GraphState, builds a prompt via
    `build_process_evolution_prompt`, prints it, and returns the incoming
    GraphState unchanged. The LLM is injected but is not invoked yet.

Future milestone:
    Agent -> build prompt -> invoke LLM -> update ReviewPackage -> return
    updated state

    1. The orchestrator will be refactored to iterate over each
       laboratory process and pass the corresponding ProcessReviewEntry
       to this agent, instead of the placeholder used here.
    2. Prompt printing will be replaced with an actual LLM invocation.
    3. The LLM's structured output will be used to populate the
       ReviewPackage carried in GraphState.
"""

from typing import Any

from src.models.review_package import ProcessReviewEntry
from src.models.technology import Process
from src.prompts.process_evolution_prompt import build_process_evolution_prompt
from src.state.graph_state import GraphState


class ProcessEvolutionAgent:
    """Process Evolution Agent: builds and prints its LLM prompt.

    Shared Stage 1 skills and an LLM client are provided by the
    orchestrator during construction. The current implementation builds
    and prints the prompt for review but performs no reasoning and makes
    no LLM calls.
    """

    def __init__(self, llm: Any, skills: dict[str, Any]) -> None:
        """Initialise the agent.

        Parameters
        ----------
        llm
            LLM client injected by the orchestrator. Not yet used.
        skills
            Shared Stage 1 skills injected by the orchestrator.
        """
        self.llm = llm
        self.skills = skills

    def __call__(self, state: GraphState) -> GraphState:
        """Build and print the Process Evolution prompt for one process.

        Parameters
        ----------
        state
            Shared workflow state.

        Returns
        -------
        GraphState
            The unchanged workflow state.
        """
        print("Running Process Evolution Agent...")

        technology = state["technology"]

        # TODO: the orchestrator will be refactored to iterate over each
        # laboratory process and pass the corresponding process and
        # ProcessReviewEntry to this agent. Until then, use the first
        # laboratory process (if any) as a placeholder.
        process = technology.processes[0] if technology.processes else Process()
        process_review_entry = ProcessReviewEntry(
            process_id=process.id, process_name=process.name
        )

        prompt = build_process_evolution_prompt(
            technology, process, process_review_entry, self.skills
        )
        print(prompt)

        # TODO:
        # response = self.llm.invoke(prompt)
        # Parse `response` and use it to populate the ProcessReviewEntry,
        # then update `state["review_package"]` accordingly.

        return state
