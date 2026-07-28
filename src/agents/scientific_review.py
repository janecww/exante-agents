"""Scientific Review Agent for the Stage 1 pLCA-agents workflow.

The Scientific Review Agent evaluates proposed process and inventory
assumptions for completeness, plausibility, traceability, and scientific
justification. Shared Stage 1 skills and an LLM client are injected by
the orchestrator during construction rather than loaded by the agent
itself.

The agent reviews the completed ReviewPackage exactly once per call. It
has no knowledge of how the ReviewPackage was produced — the
orchestrator's Process Evolution Stage owns that iteration, not this
agent.

Current milestone:
    Orchestrator's Scientific Review Stage calls this agent once, after
    every laboratory process has been processed:
        Agent -> build prompt -> print prompt -> return the ReviewPackage
        unchanged

    The LLM is injected but is not invoked yet.

Future milestone:
    Agent -> build prompt -> invoke LLM -> parse response -> return an
    updated ReviewPackage with review_comments populated.
"""

from typing import Any

from src.models.review_package import ReviewPackage
from src.models.technology import Technology
from src.prompts.scientific_review_prompt import build_scientific_review_prompt


class ScientificReviewAgent:
    """Scientific Review Agent: reviews the completed ReviewPackage once.

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

    def __call__(
        self, technology: Technology, review_package: ReviewPackage
    ) -> ReviewPackage:
        """Build and print the review prompt for the completed package.

        Parameters
        ----------
        technology
            The full Technology model for the case.
        review_package
            The completed ReviewPackage to review.

        Returns
        -------
        ReviewPackage
            The review package (currently unchanged, since no LLM is
            invoked yet).
        """
        print("Running Scientific Review Agent...")

        prompt = build_scientific_review_prompt(
            technology, review_package, self.skills
        )
        print(prompt)

        # TODO:
        # response = self.llm.invoke(prompt)
        # Parse `response` and use it to populate review_comments, then
        # return an updated ReviewPackage.

        return review_package
