"""Scientific Review Agent node for the Stage 1 LangGraph workflow.

The Scientific Review Agent evaluates proposed process and inventory
assumptions for completeness, plausibility, traceability, and scientific
justification. Shared Stage 1 skills and an LLM client are injected by
the orchestrator during construction rather than loaded by the agent
itself. The class implements ``__call__`` so an instance can be
registered directly as a LangGraph node.

Current milestone:
    Agent -> build prompt -> print prompt -> return unchanged state

    The agent extracts `technology` and `review_package` from GraphState,
    builds a prompt via `build_scientific_review_prompt`, prints it, and
    returns the incoming GraphState unchanged. The LLM is injected but is
    not invoked yet.

Future milestone:
    Agent -> build prompt -> invoke LLM -> update ReviewPackage -> return
    updated state

    1. The orchestrator will be refactored to iterate over each
       laboratory process's ProcessReviewEntry instead of the empty
       placeholder ReviewPackage used here.
    2. Prompt printing will be replaced with an actual LLM invocation.
    3. The LLM's structured output will be used to populate the
       review_comments in the ReviewPackage carried in GraphState.
"""

from typing import Any

from src.models.review_package import ReviewPackage
from src.prompts.scientific_review_prompt import build_scientific_review_prompt
from src.state.graph_state import GraphState


class ScientificReviewAgent:
    """Scientific Review Agent: builds and prints its LLM prompt.

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
        """Build and print the Scientific Review prompt for the package.

        Parameters
        ----------
        state
            Shared workflow state.

        Returns
        -------
        GraphState
            The unchanged workflow state.
        """
        print("Running Scientific Review Agent...")

        technology = state["technology"]

        # TODO: the orchestrator will be refactored to construct the
        # ReviewPackage as the Process Evolution Agent completes each
        # ProcessReviewEntry. Until then, GraphState's review_package is
        # still None, so build an empty placeholder here.
        review_package = state["review_package"] or ReviewPackage(
            technology={
                "name": technology.technology.name,
                "functional_unit": technology.technology.functional_unit,
                "target_scale": technology.target_state.scale,
            }
        )

        prompt = build_scientific_review_prompt(
            technology, review_package, self.skills
        )
        print(prompt)

        # TODO:
        # response = self.llm.invoke(prompt)
        # Parse `response` and use it to populate review_comments in the
        # ReviewPackage, then update `state["review_package"]` accordingly.

        return state
