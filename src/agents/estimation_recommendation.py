"""Estimation Recommendation Agent for the Stage 1 pLCA-agents workflow.

The Estimation Recommendation Agent recommends, for every confirmed
foreground inventory, the most appropriate estimation method that can
currently be applied -- retrieved from the authoritative estimation
methods knowledge base (`src/skills/scaleup_decision_framework.xlsx`),
never invented -- and identifies a more representative method plus
what additional information it would need, where one exists. The human
remains responsible for selecting the final estimation method (the
"Selected Method" column of the exported workbook).

Shared Stage 1 skills, the estimation methods knowledge base, the
case's lab-derived parameters, an LLM callable, and the case's output
directory are injected by the orchestrator during construction rather
than resolved by the agent itself. This agent consumes only
`ConfirmedInventoryPackage` (plus `Technology` for process context)
from the graph state; it never reads Excel directly.

Current milestone:
    Agent -> build prompt -> invoke LLM -> persist raw response -> parse
    JSON -> validate into RecommendationPackage -> verify every cited
    method_id actually exists in the knowledge base (and normalize its
    method_name from the knowledge base) -> persist parsed package ->
    return the validated RecommendationPackage

    "Retrieve, never invent" is enforced deterministically, not left to
    prompt compliance alone: an LLM-cited method_id absent from the
    knowledge base is treated the same as any other schema-compliance
    failure and raised as-is, never silently repaired or retried. A
    null-like method_id (e.g. the string "null", or "") is normalized
    to a genuine `None` rather than rejected -- it is a non-compliant
    spelling of "no method applies", not a hallucinated citation.

Future milestone:
    Human selection of the final method (Scientific Review of the
    recommendation itself is out of scope here).
"""

import json
from pathlib import Path
from typing import Any, Callable

from src.models.confirmed_inventory import ConfirmedInventoryPackage
from src.models.recommendation import EstimationMethodReference, RecommendationPackage
from src.models.technology import Technology
from src.prompts.estimation_recommendation_prompt import (
    build_estimation_recommendation_prompt,
)
from src.tools.output_writer import (
    append_log,
    save_input,
    save_parsed,
    save_prompt,
    save_response,
)


_NULL_LIKE_METHOD_IDS = {"", "null", "none", "n/a", "na"}


def _method_lookup(estimation_methods: list[dict]) -> dict[str, str | None]:
    """Map every known method_id to its authoritative method_name."""
    return {
        row["method_id"]: row.get("method_name")
        for row in estimation_methods
        if row.get("method_id")
    }


def _is_null_like(method_id: str | None) -> bool:
    """Whether a method_id is a null-like placeholder, not a real citation.

    Despite explicit prompt instructions to use the JSON literal `null`
    when no method applies, an LLM will sometimes instead emit the
    string `"null"`, an empty string, or similar -- inside an otherwise
    well-formed method object. These are not hallucinated method IDs;
    they are non-compliant spellings of "no method", and must be
    treated exactly like a genuine null rather than failing validation.
    """
    return method_id is None or method_id.strip().lower() in _NULL_LIKE_METHOD_IDS


def _normalize_reference(
    reference: EstimationMethodReference | None,
    method_lookup: dict[str, str | None],
    unknown_ids: set[str],
) -> EstimationMethodReference | None:
    """Normalize one method reference; record its method_id if unknown.

    Returns `None` if `reference` is absent or its `method_id` is
    null-like (see `_is_null_like`) -- both are treated as "no method".
    A `method_id` that is present, not null-like, and not found in the
    knowledge base is a genuine hallucination: it is recorded in
    `unknown_ids` and the reference is returned unchanged so the caller
    can raise with the full list of offending IDs.
    """
    if reference is None or _is_null_like(reference.method_id):
        return None
    if reference.method_id not in method_lookup:
        unknown_ids.add(reference.method_id)
        return reference
    reference.method_name = method_lookup[reference.method_id]
    return reference


def _normalize_and_validate_method_references(
    package: RecommendationPackage, method_lookup: dict[str, str | None]
) -> RecommendationPackage:
    """Verify every cited method_id is real, and normalize its name.

    Raises `ValueError` listing every unrecognised method_id -- an LLM
    citing a method_id absent from the knowledge base is exactly the
    "inventing a method" failure this agent must never allow through.
    Null-like placeholders (see `_is_null_like`) are normalized to a
    genuine `None` rather than rejected. For every valid reference,
    `method_name` is overwritten from the knowledge base, so a typo in
    the LLM's copy of the name can never diverge from the authoritative
    one.
    """
    unknown_ids: set[str] = set()

    for entry in package.recommendations:
        entry.recommended_method = _normalize_reference(
            entry.recommended_method, method_lookup, unknown_ids
        )
        entry.more_representative_method = _normalize_reference(
            entry.more_representative_method, method_lookup, unknown_ids
        )

    if unknown_ids:
        raise ValueError(
            "Estimation Recommendation Agent cited method_id(s) not found "
            f"in the estimation methods knowledge base: {sorted(unknown_ids)}"
        )

    return package


class EstimationRecommendationAgent:
    """Estimation Recommendation Agent: recommends an estimation method
    for every confirmed foreground inventory.

    Shared Stage 1 skills, the estimation methods knowledge base, the
    case's lab-derived parameters, an LLM callable, and the case's
    output directory are provided by the orchestrator during
    construction. The current implementation builds the prompt, invokes
    the LLM, persists the input/prompt/response/parsed artifacts, and
    validates the raw JSON response into a `RecommendationPackage`
    using Pydantic, then checks every cited method_id against the
    knowledge base.
    """

    def __init__(
        self,
        llm: Callable[[str], str] | None,
        skills: dict[str, Any],
        estimation_methods: list[dict],
        lab_derived_parameters: list[dict],
        case_directory: str | Path,
    ) -> None:
        """Initialise the agent.

        Parameters
        ----------
        llm
            A `prompt -> str` callable injected by the orchestrator.
        skills
            Shared Stage 1 skills injected by the orchestrator. Only
            `source_priority` is used.
        estimation_methods
            Every row of the estimation methods knowledge base
            (`src/skills/scaleup_decision_framework.xlsx`), as a list
            of dicts. The authoritative source of every method_id this
            agent may cite.
        lab_derived_parameters
            Rows of the case's `references/lab_derived_parameters.xlsx`,
            if available for this case, else an empty list.
        case_directory
            The case directory whose `outputs/` tree execution
            artifacts are persisted under.
        """
        self.llm = llm
        self.skills = skills
        self.estimation_methods = estimation_methods
        self.lab_derived_parameters = lab_derived_parameters
        self.case_directory = Path(case_directory)

    def __call__(
        self, technology: Technology, confirmed_inventory: ConfirmedInventoryPackage
    ) -> RecommendationPackage:
        """Build the prompt, invoke the LLM, and return a validated package.

        Parameters
        ----------
        technology
            The full Technology model for the case (process context only).
        confirmed_inventory
            The human-confirmed inventory to recommend estimation
            methods for.

        Returns
        -------
        RecommendationPackage
            The LLM's response, parsed as JSON, validated into a
            `RecommendationPackage`, and checked so every cited
            method_id exists in the estimation methods knowledge base.
            Raises `json.JSONDecodeError`, a Pydantic `ValidationError`,
            or `ValueError` (unknown method_id) if the response does
            not comply; it is never repaired or retried.
        """
        print("Running Estimation Recommendation Agent...")

        save_input(
            self.case_directory,
            "confirmed_inventory.yaml",
            confirmed_inventory.model_dump(),
        )

        prompt = build_estimation_recommendation_prompt(
            technology,
            confirmed_inventory,
            self.estimation_methods,
            self.lab_derived_parameters,
            self.skills,
        )
        save_prompt(self.case_directory, "estimation_recommendation.txt", prompt)
        append_log(self.case_directory, "Estimation Recommendation")
        append_log(self.case_directory, "Prompt generated")

        response = self.llm(prompt)
        append_log(self.case_directory, "LLM invoked")

        save_response(self.case_directory, "estimation_recommendation.txt", response)
        append_log(self.case_directory, "Response saved")

        validated_package = RecommendationPackage.model_validate(json.loads(response))
        append_log(self.case_directory, "Response validated")

        validated_package = _normalize_and_validate_method_references(
            validated_package, _method_lookup(self.estimation_methods)
        )
        append_log(
            self.case_directory, "Method references verified against knowledge base"
        )

        save_parsed(
            self.case_directory,
            "recommendation.yaml",
            validated_package.model_dump(),
        )
        append_log(self.case_directory, "Parsed recommendation package saved")

        return validated_package
