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

from src.models.parameter_review import (
    AVAILABLE,
    MISSING_PARAMETERS,
    READY,
    ParameterReview,
    RequiredParameter,
)
from src.models.recommendation import InputAssessment, RecommendationPackage
from src.models.reviewed_recommendation import (
    HumanSelectedMethod,
    ReviewedRecommendationEntry,
    ReviewedRecommendationPackage,
)
from src.models.technology import Technology
from src.prompts.parameter_requirement_prompt import build_parameter_requirement_prompt
from src.skills.availability import TARGET, decides_availability, parse_inputs
from src.tools.evidence_trace import build_evidence_index
from src.tools.method_ranking import normalise_inputs
from src.tools.output_writer import append_log, save_parsed, save_prompt, save_response


def _response_appears_truncated(response: str) -> bool:
    """Best-effort guess at whether a raw response was cut off mid-output.

    Mirrors `src.agents.estimation_recommendation._response_appears_truncated`.
    """
    stripped = response.rstrip()
    return not stripped.endswith(("}", "]"))


def _normalize_review(
    review: ParameterReview, method: HumanSelectedMethod, evidence: list[dict] | None = None
) -> ParameterReview:
    """Apply the framework to the model's answer, then compute the summary.

    The inputs are normalised exactly as in the recommendation ranking
    (`src.tools.method_ranking.normalise_inputs`): one entry per framework
    input in framework order, the framework's tag, DEFAULT values filled
    in, and an "available" input without a value treated as missing (C5).
    Findings go to `consistency_flags`. `missing_parameters` (non-TARGET
    inputs not available), `target_inputs` and `calculation_readiness` are
    computed here, never taken from the model.
    """
    flags: list[str] = []
    items = [
        InputAssessment(
            name=item.parameter, tag=item.tag, status=item.status, value=item.value, unit=item.unit,
            source=item.source, derivation=item.derivation, note=item.note,
        )
        for item in review.required_parameters
    ]
    normalised = normalise_inputs(method.method_id, parse_inputs(method.inputs), items, flags, evidence=evidence)
    review.required_parameters = [
        RequiredParameter(
            parameter=item.name, tag=item.tag, status=item.status, value=item.value, unit=item.unit,
            source=item.source, derivation=item.derivation, note=item.note,
        )
        for item in normalised
    ]
    review.missing_parameters = [
        item.parameter for item in review.required_parameters
        if decides_availability(item.tag) and item.status != AVAILABLE
    ]
    review.target_inputs = [item.parameter for item in review.required_parameters if item.tag == TARGET]
    review.calculation_readiness = MISSING_PARAMETERS if review.missing_parameters else READY
    review.consistency_flags = flags
    return review


def compare_with_recommendation(
    review: ParameterReview, entry: ReviewedRecommendationEntry, recommendation_package: RecommendationPackage | None
) -> list[str]:
    """Check C2: every input of the selected method must have the same status
    here as in the Estimation Recommendation step's assessment."""
    if recommendation_package is None or entry.human_selected_method is None:
        return []
    method_id = entry.human_selected_method.method_id
    key = ((entry.process_id or "").strip().lower(), (entry.inventory_name or "").strip().lower())
    for recommendation in recommendation_package.recommendations:
        if ((recommendation.process_id or "").strip().lower(), (recommendation.inventory_name or "").strip().lower()) != key:
            continue
        for candidate in recommendation.candidate_assessments:
            if candidate.method_id != method_id:
                continue
            before = {item.name: item.status for item in candidate.inputs}
            return [
                f"C2: {item.parameter} is {item.status!r} here but was {before[item.parameter]!r} in the recommendation step"
                for item in review.required_parameters
                if item.parameter in before and before[item.parameter] != item.status
            ]
    return [f"C2: no recommendation-step assessment found for {method_id}; not compared"]


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

        validated_review = _normalize_review(
            validated_review,
            entry.human_selected_method,
            evidence=build_evidence_index(technology, lab_derived_parameters),
        )
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
    recommendation_package: RecommendationPackage | None = None,
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
        review = agent(technology, lab_derived_parameters, entry)
        review.consistency_flags += compare_with_recommendation(review, entry, recommendation_package)
        save_parsed(agent.case_directory, f"{_artifact_name(entry)}.yaml", review.model_dump())
        for flag in review.consistency_flags:
            append_log(agent.case_directory, f"  {entry.process_id} / {entry.inventory_name}: {flag}")
        entry.parameter_review = review
    return package
