"""Scientific Review Agent for the Stage 1 pLCA-agents workflow.

The Scientific Review Agent evaluates proposed process and inventory
assumptions for completeness, plausibility, traceability, and scientific
justification. Shared Stage 1 skills, an LLM callable, and the case's
output directory are injected by the orchestrator during construction
rather than resolved by the agent itself.

The agent reviews the completed ReviewPackage exactly once per call. It
has no knowledge of how the ReviewPackage was produced — the
orchestrator's Process Evolution Stage owns that iteration, not this
agent.

Current milestone:
    Agent -> build prompt -> invoke LLM -> persist raw response -> parse
    JSON -> validate into ReviewPackage -> persist parsed package ->
    return the validated ReviewPackage

    The LLM is instructed (via the prompt) to return only JSON matching
    the existing ReviewPackage schema. That JSON is parsed with
    `json.loads()` and validated with `ReviewPackage.model_validate()` —
    no manual field mapping. If parsing or validation fails, the
    exception is raised as-is (after the raw response has already been
    saved for debugging); the response is never repaired or retried.

Future milestone:
    Confidence estimation, retries, and human review of low-confidence
    review comments.
"""

import json
from pathlib import Path
from typing import Any, Callable

from src.models.review_package import ReviewPackage
from src.models.technology import Technology
from src.prompts.scientific_review_prompt import build_scientific_review_prompt
from src.tools.output_writer import (
    append_log,
    save_input,
    save_parsed,
    save_prompt,
    save_response,
)


class ScientificReviewAgent:
    """Scientific Review Agent: reviews the completed ReviewPackage once.

    Shared Stage 1 skills, an LLM callable, and the case's output
    directory are provided by the orchestrator during construction. The
    current implementation builds the prompt, invokes the LLM, persists
    the input/prompt/response/parsed artifacts, and validates the raw
    JSON response into a `ReviewPackage` using Pydantic.
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
        self, technology: Technology, review_package: ReviewPackage
    ) -> ReviewPackage:
        """Build the review prompt, invoke the LLM, and return a validated package.

        Parameters
        ----------
        technology
            The full Technology model for the case.
        review_package
            The completed ReviewPackage to review.

        Returns
        -------
        ReviewPackage
            The LLM's response, parsed as JSON and validated into a
            `ReviewPackage`. Raises `json.JSONDecodeError` or a Pydantic
            `ValidationError` if the response is not valid JSON matching
            the expected schema; the response is never repaired or
            retried.
        """
        print("Running Scientific Review Agent...")

        save_input(
            self.case_directory,
            "scientific_review_package.yaml",
            review_package.model_dump(),
        )

        prompt = build_scientific_review_prompt(
            technology, review_package, self.skills
        )
        save_prompt(self.case_directory, "scientific_review.txt", prompt)
        append_log(self.case_directory, "Scientific Review")
        append_log(self.case_directory, "Prompt generated")

        response = self.llm(prompt)
        append_log(self.case_directory, "LLM invoked")

        save_response(self.case_directory, "scientific_review.txt", response)
        append_log(self.case_directory, "Response saved")

        validated_review_package = ReviewPackage.model_validate(json.loads(response))
        append_log(self.case_directory, "Response validated")

        save_parsed(
            self.case_directory,
            "review_package.yaml",
            validated_review_package.model_dump(),
        )
        append_log(self.case_directory, "Parsed review package saved")

        return validated_review_package
