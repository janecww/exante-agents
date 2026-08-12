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
case's lab-derived parameters (both the process inventory quantities
and the lab-derived parameters come from the case's single,
unified `laboratory_case_workbook.xlsx`, loaded once by the
orchestrator), an LLM callable, and the case's output directory are
injected by the orchestrator during construction rather than resolved
by the agent itself. This agent consumes only `ConfirmedInventoryPackage`
(plus `Technology` for the process inventory's quantitative evidence)
from the graph state; it never reads Excel directly.

Current milestone:
    Agent -> build prompt -> invoke LLM -> persist raw response (always,
    before parsing is even attempted) -> parse JSON -> validate into
    RecommendationPackage -> verify every cited method_id actually
    exists in the knowledge base (and normalize its method_name/tier_name
    from the knowledge base) -> persist parsed package -> return the
    validated RecommendationPackage

    "Retrieve, never invent" is enforced deterministically, not left to
    prompt compliance alone: an LLM-cited method_id absent from the
    knowledge base is treated the same as any other schema-compliance
    failure and raised as-is, never silently repaired or retried. A
    null-like method_id (e.g. the string "null", or "") is normalized
    to a genuine `None` rather than rejected -- it is a non-compliant
    spelling of "no method applies", not a hallucinated citation.

    If the raw response is not valid JSON (e.g. truncated by the model's
    output limit -- see `config.invoke_llm`'s `finish_reason` check),
    the raw response has already been saved by that point; the
    `json.JSONDecodeError` raised is re-thrown with its message enriched
    with the saved response's path, length, and a truncation guess, with
    line/column/position still pointing at the real parse failure. No
    retry, repair, or fabrication is attempted -- this milestone is
    about making the failure inspectable, not automatically recovering
    from it.

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


def _response_appears_truncated(response: str) -> bool:
    """Best-effort guess at whether a raw response was cut off mid-output.

    The agent only has the raw string here, not the API's own
    `finish_reason` (that signal is checked, and printed, inside
    `config.invoke_llm` itself -- see its docstring). A complete JSON
    response practically always ends on a closing brace or bracket
    after trailing whitespace; anything else is a strong (though not
    certain) sign of truncation.
    """
    stripped = response.rstrip()
    return not stripped.endswith(("}", "]"))


def _method_lookup(estimation_methods: list[dict]) -> dict[str, dict]:
    """Map every known method_id to its authoritative method_name/tier_name.

    `tier_name` is deterministically propagated from this lookup (see
    `_normalize_reference`), never left to the LLM to infer -- a
    recommendation's tier is a property of the candidate row it cites,
    not a judgement call.
    """
    return {
        row["method_id"]: {
            "method_name": row.get("method_name"),
            "tier_name": row.get("tier_name"),
        }
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
    method_lookup: dict[str, dict],
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
    authoritative = method_lookup[reference.method_id]
    reference.method_name = authoritative["method_name"]
    reference.tier_name = authoritative["tier_name"]
    return reference


def _normalize_and_validate_method_references(
    package: RecommendationPackage, method_lookup: dict[str, dict]
) -> RecommendationPackage:
    """Verify every cited method_id is real, and normalize its name/tier.

    Raises `ValueError` listing every unrecognised method_id -- an LLM
    citing a method_id absent from the knowledge base is exactly the
    "inventing a method" failure this agent must never allow through.
    Null-like placeholders (see `_is_null_like`) are normalized to a
    genuine `None` rather than rejected. For every valid reference,
    `method_name` and `tier_name` are overwritten from the knowledge
    base, so neither the LLM's copy of the name nor an inferred tier
    can ever diverge from the authoritative row.
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
            Rows from the "Lab-Derived Parameters" worksheet of the
            case's unified `laboratory_case_workbook.xlsx`.
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
            The raw response is always persisted before parsing is even
            attempted, so it survives on disk regardless of what
            happens next. Raises `json.JSONDecodeError` (message
            enriched with the saved response's path, length, and
            truncation guess -- see `_response_appears_truncated` --
            while its `.lineno`/`.colno`/`.pos` still point at the
            original parse failure), a Pydantic `ValidationError`, or
            `ValueError` (unknown method_id) if the response does not
            comply; it is never repaired or retried.
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

        # Persisted before any parsing is attempted -- and therefore
        # still on disk exactly as received even if json.loads() below
        # fails -- using the project's existing raw-response artifact
        # convention (outputs/responses/), not a new storage mechanism.
        response_path = save_response(
            self.case_directory, "estimation_recommendation.txt", response
        )
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
                "Estimation recommendation LLM returned invalid JSON.\n"
                f"Raw response saved to: {response_path}\n"
                f"JSON error: {exc}"
            )
            print(diagnostic)
            append_log(
                self.case_directory,
                f"Response validation failed: invalid JSON ({exc})",
            )
            # Re-raised as a JSONDecodeError (not a different exception
            # type) so existing callers that catch json.JSONDecodeError
            # keep working; `doc`/`pos` are carried over unchanged so
            # `.lineno`/`.colno`/`.pos` still describe the real parse
            # failure. The response is never repaired, truncated, or
            # fabricated -- only the error message gains context.
            raise json.JSONDecodeError(
                "Estimation Recommendation Agent: the LLM returned "
                f"invalid/truncated JSON (response length: {response_length} "
                f"chars, appears truncated: {appears_truncated}). Raw "
                f"response saved to: {response_path}. Original error: "
                f"{exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc

        validated_package = RecommendationPackage.model_validate(parsed_response)
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
