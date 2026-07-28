"""Process Evolution Agent for the Stage 1 pLCA-agents workflow.

The Process Evolution Agent develops prospective industrial process and
foreground inventory assumptions from laboratory-scale technologies.
Shared Stage 1 skills and an LLM client are injected by the orchestrator
during construction rather than loaded by the agent itself.

The agent reasons about exactly one laboratory process per call. It has
no knowledge of the overall workflow, the other laboratory processes, or
how its result is assembled into the shared ReviewPackage — the
orchestrator's Process Evolution Stage owns that iteration and never the
agent itself.

Current milestone:
    Orchestrator's Process Evolution Stage loops over every laboratory
    process, calling this agent once per process:
        Agent -> build prompt -> print prompt -> return the
        ProcessReviewEntry unchanged

    The LLM is injected but is not invoked yet.

Future milestone:
    Agent -> build prompt -> invoke LLM -> parse response -> return an
    updated ProcessReviewEntry.
"""

from typing import Any

from src.models.review_package import ProcessReviewEntry
from src.models.technology import Process, Technology
from src.prompts.process_evolution_prompt import build_process_evolution_prompt


class ProcessEvolutionAgent:
    """Process Evolution Agent: reasons about exactly one process.

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
        self,
        technology: Technology,
        process: Process,
        process_review_entry: ProcessReviewEntry,
    ) -> ProcessReviewEntry:
        """Build and print the prompt for one laboratory process.

        Parameters
        ----------
        technology
            The full Technology model for the case.
        process
            The single laboratory-scale process to reason about.
        process_review_entry
            The ProcessReviewEntry section of the shared ReviewPackage
            that this agent is responsible for completing.

        Returns
        -------
        ProcessReviewEntry
            The entry for this process (currently unchanged, since no
            LLM is invoked yet).
        """
        print(f"Running Process Evolution Agent for process '{process.id}'...")

        prompt = build_process_evolution_prompt(
            technology, process, process_review_entry, self.skills
        )
        print(prompt)

        # TODO:
        # response = self.llm.invoke(prompt)
        # Parse `response` and use it to populate and return an updated
        # ProcessReviewEntry.

        return process_review_entry
