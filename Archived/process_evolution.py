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
    Agent -> build prompt -> invoke LLM -> persist raw response -> parse
    JSON -> validate into ProcessReviewEntry -> persist parsed entry ->
    return the validated ProcessReviewEntry

    The LLM is instructed (via the prompt) to return only JSON matching
    the existing ProcessReviewEntry schema. That JSON is parsed with
    `json.loads()` and validated with `ProcessReviewEntry.model_validate()`
    — no manual field mapping. If parsing or validation fails, the
    exception is raised as-is (after the raw response has already been
    saved for debugging); the response is never repaired or retried.

Future milestone:
    Confidence estimation, retries, and human review of low-confidence
    assumptions.
"""

import json
import re
from pathlib import Path
from typing import Any, Callable

from src.models.review_package import ProcessReviewEntry
from src.models.technology import Process, Technology
from src.prompts.process_evolution_prompt import build_process_evolution_prompt
from src.tools.output_writer import (
    append_log,
    save_input,
    save_parsed,
    save_prompt,
    save_response,
)


def _slugify(text: str | None) -> str:
    """Turn free text into a filesystem-safe lowercase slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text or "").strip("_").lower()
    return slug or "process"


class ProcessEvolutionAgent:
    """Process Evolution Agent: reasons about exactly one process.

    Shared Stage 1 skills, an LLM callable, and the case's output
    directory are provided by the orchestrator during construction. The
    current implementation builds the prompt, invokes the LLM, persists
    the input/prompt/response/parsed artifacts, and validates the raw
    JSON response into a `ProcessReviewEntry` using Pydantic.
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
        """Build the prompt, invoke the LLM, and return a validated entry.

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
            The LLM's response, parsed as JSON and validated into a
            `ProcessReviewEntry`. Raises `json.JSONDecodeError` or a
            Pydantic `ValidationError` if the response is not valid JSON
            matching the expected schema; the response is never repaired
            or retried.
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

        validated_entry = ProcessReviewEntry.model_validate(json.loads(response))
        append_log(self.case_directory, "Response validated")

        save_parsed(self.case_directory, f"{stem}.yaml", validated_entry.model_dump())
        append_log(self.case_directory, "Parsed entry saved")

        return validated_entry
