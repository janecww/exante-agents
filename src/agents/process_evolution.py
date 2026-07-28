"""Process Evolution Agent for the Stage 1 pLCA-agents workflow.

The Process Evolution Agent develops prospective industrial process and
foreground inventory assumptions from laboratory-scale technologies.
Shared Stage 1 skills, an LLM callable, and the case's output directory
are injected by the orchestrator during construction rather than
resolved by the agent itself.

The agent reasons about exactly one laboratory process per call. It has
no knowledge of the overall workflow, the other laboratory processes, or
how its result is assembled into the shared ReviewPackage — the
orchestrator's Process Evolution Stage owns that iteration and never the
agent itself.

Current milestone:
    Orchestrator's Process Evolution Stage loops over every laboratory
    process, calling this agent once per process:
        Agent -> build prompt -> invoke LLM -> persist input/prompt/
        response -> return the ProcessReviewEntry unchanged

    The raw LLM response is persisted but never parsed, and the
    ProcessReviewEntry is not updated yet.

Future milestone:
    Agent -> build prompt -> invoke LLM -> parse response -> return an
    updated ProcessReviewEntry.
"""

import re
from pathlib import Path
from typing import Any, Callable

from src.models.review_package import ProcessReviewEntry
from src.models.technology import Process, Technology
from src.prompts.process_evolution_prompt import build_process_evolution_prompt
from src.tools.output_writer import append_log, save_input, save_prompt, save_response


def _slugify(text: str | None) -> str:
    """Turn free text into a filesystem-safe lowercase slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text or "").strip("_").lower()
    return slug or "process"


class ProcessEvolutionAgent:
    """Process Evolution Agent: reasons about exactly one process.

    Shared Stage 1 skills, an LLM callable, and the case's output
    directory are provided by the orchestrator during construction. The
    current implementation builds the prompt, invokes the LLM, and
    persists the input/prompt/response as execution artifacts, but
    performs no parsing or reasoning over the response.
    """

    def __init__(
        self,
        llm: Callable[[str], str] | None,
        skills: dict[str, Any],
        case_directory: str | Path,
    ) -> None:
        """Initialise the agent.

        Parameters
        ----------
        llm
            A `prompt -> str` callable injected by the orchestrator.
        skills
            Shared Stage 1 skills injected by the orchestrator.
        case_directory
            The case directory whose `outputs/` tree execution artifacts
            are persisted under.
        """
        self.llm = llm
        self.skills = skills
        self.case_directory = Path(case_directory)

    def __call__(
        self,
        technology: Technology,
        process: Process,
        process_review_entry: ProcessReviewEntry,
    ) -> ProcessReviewEntry:
        """Build the prompt, invoke the LLM, and persist the artifacts.

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
            The entry for this process, unchanged (the response is not
            parsed yet).
        """
        print(f"Running Process Evolution Agent for process '{process.id}'...")

        stem = f"{process.id}_{_slugify(process.name)}"

        save_input(self.case_directory, f"{stem}.yaml", process.model_dump())

        prompt = build_process_evolution_prompt(
            technology, process, process_review_entry, self.skills
        )
        save_prompt(self.case_directory, f"{stem}.txt", prompt)
        append_log(self.case_directory, f"Process Evolution: {process.name}")
        append_log(self.case_directory, "Prompt generated")

        response = self.llm(prompt)
        append_log(self.case_directory, "LLM invoked")

        save_response(self.case_directory, f"{stem}.txt", response)
        append_log(self.case_directory, "Response saved")

        # TODO:
        # Parse `response` and use it to populate and return an updated
        # ProcessReviewEntry.

        return process_review_entry
