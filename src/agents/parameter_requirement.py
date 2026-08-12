"""Parameter Requirement Agent for the Stage 1 pLCA-agents workflow.

Milestone 1: once a human has selected a final estimation method for an
inventory (see `ReviewedRecommendationEntry.human_selected_method` in
`src.models.reviewed_recommendation`, populated by
`src.tools.import_estimation_recommendations`), this agent determines
what information that specific method needs and whether the case's
existing evidence already supplies it.

This agent's responsibility is explicitly NOT method selection and NOT
the scale-up calculation itself:

- The human's selected method is never replaced, second-guessed, or
  proposed as a candidate for reconsideration -- see
  `src.prompts.parameter_requirement_prompt`'s ROLE text.
- No industrial quantity is calculated, no linear extrapolation or
  scaling factor is applied, and no missing value is estimated. Those
  belong to a later milestone (Milestone 2: Scale-up Calculation).

Current milestone:
    Human-selected method -> build prompt -> invoke LLM -> persist raw
    response (always, before parsing is even attempted) -> parse JSON
    -> validate into ParameterReview -> deterministically recompute
    missing_parameters/calculation_readiness from required_parameters
    (never trusted verbatim from the LLM's own summary) -> persist
    parsed review -> return the validated ParameterReview

    `review_parameter_requirements` (below) is the small orchestration
    helper that runs this agent once per inventory across a whole
    `ReviewedRecommendationPackage`, skipping every inventory with no
    human-selected method -- the agent itself is never invoked for
    those (Milestone 1, section 3).
"""

import json
from pathlib import Path
from typing import Callable

from src.models.parameter_review import AVAILABLE, MISSING_PARAMETERS, READY, ParameterReview
from src.models.reviewed_recommendation import (
    ReviewedRecommendationEntry,
    ReviewedRecommendationPackage,
)
from src.models.technology import Technology
from src.prompts.parameter_requirement_prompt import build_parameter_requirement_prompt
from src.tools.output_writer import append_log, save_parsed, save_prompt, save_response


def _response_appears_truncated(response: str) -> bool:
    """Best-effort guess at whether a raw response was cut off mid-output.

    Mirrors `src.agents.estimation_recommendation._response_appears_truncated`.
    """
    stripped = response.rstrip()
    return not stripped.endswith(("}", "]"))


def _normalize_calculation_readiness(review: ParameterReview) -> ParameterReview:
    """Deterministically recompute missing_parameters/calculation_readiness.

    Never trusted verbatim from the LLM's own summary of its own list --
    mirrors how `method_name`/`tier_name` are always re-derived from the
    knowledge base rather than trusted from an LLM's copy (see
    `src.agents.estimation_recommendation`). Any parameter whose status
    is not exactly `AVAILABLE` counts as missing, so an LLM writing a
    third, non-compliant status value can never accidentally read as
    ready.
    """
    missing = [
        parameter.parameter
        for parameter in review.required_parameters
        if parameter.status != AVAILABLE
    ]
    review.missing_parameters = missing
    review.calculation_readiness = MISSING_PARAMETERS if missing else READY
    return review


def _artifact_name(entry: ReviewedRecommendationEntry) -> str:
    """A filesystem-safe per-inventory artifact name (this agent runs
    once per inventory, unlike the single-shot Estimation Recommendation
    Agent, so its artifacts cannot share one fixed filename)."""
    process_id = (entry.process_id or "unknown").strip()
    inventory_name = (entry.inventory_name or "unknown").strip().lower().replace(" ", "_")
    return f"parameter_requirement_{process_id}_{inventory_name}"


class ParameterRequirementAgent:
    """Parameter Requirement Agent: reviews one inventory's human-selected
    method for information readiness.

    An LLM callable and the case's output directory are provided by the
    orchestrator during construction, matching every other agent in
    this codebase.
    """

    def __init__(
        self,
        llm: Callable[[str], str] | None,
        case_directory: str | Path,
    ) -> None:
        """Initialise the agent.

        Parameters
        ----------
        llm
            A `prompt -> str` callable injected by the orchestrator.
        case_directory
            The case directory whose `outputs/` tree execution
            artifacts are persisted under.
        """
        self.llm = llm
        self.case_directory = Path(case_directory)

    def __call__(
        self,
        technology: Technology,
        lab_derived_parameters: list[dict],
        entry: ReviewedRecommendationEntry,
    ) -> ParameterReview:
        """Build the prompt, invoke the LLM, and return a validated review.

        Parameters
        ----------
        technology
            The full Technology model for the case (process context and
            quantitative laboratory evidence).
        lab_derived_parameters
            Rows from the case's Laboratory Case Workbook "Lab-Derived
            Parameters" worksheet.
        entry
            The reviewed recommendation entry for one inventory, with
            `human_selected_method` populated.

        Returns
        -------
        ParameterReview
            The LLM's response, parsed as JSON and validated, with
            `missing_parameters`/`calculation_readiness` always
            recomputed deterministically from `required_parameters`.

        Raises
        ------
        ValueError
            If `entry.human_selected_method` is `None` -- this agent
            must never be invoked for an inventory with no selected
            method.
        json.JSONDecodeError
            If the LLM's response is not valid JSON (message enriched
            with the saved response's path, length, and truncation
            guess, mirroring `EstimationRecommendationAgent`).
        """
        if entry.human_selected_method is None:
            raise ValueError(
                "Parameter Requirement Agent requires a human-selected "
                f"method; Process ID {entry.process_id!r} / Inventory "
                f"{entry.inventory_name!r} has none."
            )

        print(
            "Running Parameter Requirement Agent for "
            f"{entry.process_id} / {entry.inventory_name}..."
        )

        artifact_name = f"{_artifact_name(entry)}.txt"

        prompt = build_parameter_requirement_prompt(
            technology, lab_derived_parameters, entry
        )
        save_prompt(self.case_directory, artifact_name, prompt)
        append_log(
            self.case_directory,
            f"Parameter Requirement: {entry.process_id} / {entry.inventory_name}",
        )
        append_log(self.case_directory, "Prompt generated")

        response = self.llm(prompt)
        append_log(self.case_directory, "LLM invoked")

        response_path = save_response(self.case_directory, artifact_name, response)
        append_log(self.case_directory, "Response saved")

        response_length = len(response)
        appears_truncated = _response_appears_truncated(response)
        append_log(
            self.case_directory,
            f"Raw response length: {response_length} chars; "
            f"appears truncated: {appears_truncated}",
        )

        try:
            parsed_response = json.loads(response)
        except json.JSONDecodeError as exc:
            diagnostic = (
                "Parameter requirement LLM returned invalid JSON.\n"
                f"Raw response saved to: {response_path}\n"
                f"JSON error: {exc}"
            )
            print(diagnostic)
            append_log(
                self.case_directory,
                f"Response validation failed: invalid JSON ({exc})",
            )
            raise json.JSONDecodeError(
                "Parameter Requirement Agent: the LLM returned "
                f"invalid/truncated JSON (response length: {response_length} "
                f"chars, appears truncated: {appears_truncated}). Raw "
                f"response saved to: {response_path}. Original error: "
                f"{exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc

        validated_review = ParameterReview.model_validate(parsed_response)
        append_log(self.case_directory, "Response validated")

        validated_review = _normalize_calculation_readiness(validated_review)
        append_log(
            self.case_directory,
            f"Calculation readiness: {validated_review.calculation_readiness}",
        )

        save_parsed(
            self.case_directory,
            f"{_artifact_name(entry)}.yaml",
            validated_review.model_dump(),
        )
        append_log(self.case_directory, "Parsed parameter review saved")

        return validated_review


def review_parameter_requirements(
    technology: Technology,
    lab_derived_parameters: list[dict],
    package: ReviewedRecommendationPackage,
    agent: ParameterRequirementAgent,
) -> ReviewedRecommendationPackage:
    """Run the Parameter Requirement Agent for every selected inventory.

    For every entry in `package.recommendations`: if
    `human_selected_method` is `None` (the human rejected both proposed
    methods, or has not yet decided -- see `selection_source` on
    `ReviewedRecommendationEntry`), `parameter_review` is set to `None`
    and the agent is never invoked for that inventory, per Milestone 1
    section 3. Otherwise the agent is called and its result is attached
    to `entry.parameter_review`.

    Mutates and returns `package` in place, matching the plain,
    deterministic iteration style already used elsewhere in this
    codebase for reviewing/attaching outputs onto a package's entries.
    """
    for entry in package.recommendations:
        if entry.human_selected_method is None:
            entry.parameter_review = None
            continue
        entry.parameter_review = agent(technology, lab_derived_parameters, entry)
    return package
