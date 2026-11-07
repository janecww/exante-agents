"""Estimation Recommendation Agent for the Stage 1 pLCA-agents workflow.

For every confirmed flow, one language-model call assesses every
candidate rule of the flow's category against the case evidence, using
the shared definition of "available" (`src.skills.availability`). The
code then ranks the rules and writes the rationale from that assessment
(`src.tools.method_ranking.rank_candidates`): the recommended method is
the highest-tier available rule, and the alternative is a higher-tier
rule that would become available with more inputs. The practitioner
selects the final method afterwards (Worksheet 2).

Per flow:
    build prompt -> invoke LLM -> persist raw response (always, before
    parsing) -> parse JSON -> validate into FlowAssessment -> rank in code
    (framework tags, Tier 3 from linear extrapolation, checks C1/C3/C4/C5)
Then: persist recommendation.yaml -> return the RecommendationPackage.

A response that is not valid JSON, or does not match the schema, stops
the workflow with the raw response kept on disk; it is never repaired or
retried. Smaller problems in an otherwise valid answer (an input left
out, a status that is not one of the three allowed values, an
"available" input without a value) are handled conservatively by the
ranking and recorded in the entry's `checks`.
"""

import json
from pathlib import Path
from typing import Any, Callable

from src.models.confirmed_inventory import ConfirmedInventoryPackage
from src.models.recommendation import FlowAssessment, RecommendationPackage
from src.models.technology import Technology
from src.prompts.estimation_recommendation_prompt import (
    build_flow_assessment_prompt,
    prepare_flow_contexts,
)
from src.tools.evidence_trace import build_evidence_index
from src.tools.method_ranking import rank_candidates
from src.tools.output_writer import append_log, save_input, save_parsed, save_prompt, save_response


def _response_appears_truncated(response: str) -> bool:
    """Best-effort guess at whether a raw response was cut off mid-output."""
    return not response.rstrip().endswith(("}", "]"))


def _artifact_name(flow: dict) -> str:
    process_id = (flow.get("process_id") or "unknown").strip()
    inventory_name = (flow.get("inventory_name") or "unknown").strip().lower().replace(" ", "_")
    return f"estimation_recommendation_{process_id}_{inventory_name}"


class EstimationRecommendationAgent:
    """Recommends an estimation method for every confirmed flow (see module docstring)."""

    def __init__(
        self,
        llm: Callable[[str], str] | None,
        skills: dict[str, Any],
        estimation_methods: list[dict],
        lab_derived_parameters: list[dict],
        case_directory: str | Path,
    ) -> None:
        """`skills` is accepted for a uniform agent interface; this agent
        uses none of them (see `src.prompts.estimation_recommendation_prompt`)."""
        self.llm = llm
        self.skills = skills
        self.estimation_methods = estimation_methods
        self.lab_derived_parameters = lab_derived_parameters
        self.case_directory = Path(case_directory)

    def _assess(self, technology: Technology, context: dict) -> FlowAssessment:
        flow = context["flow"]
        artifact = f"{_artifact_name(flow)}.txt"
        prompt = build_flow_assessment_prompt(technology, context, self.lab_derived_parameters)
        save_prompt(self.case_directory, artifact, prompt)
        append_log(self.case_directory, f"Estimation Recommendation: {flow['process_id']} / {flow['inventory_name']}")

        response = self.llm(prompt)
        response_path = save_response(self.case_directory, artifact, response)
        appears_truncated = _response_appears_truncated(response)
        append_log(
            self.case_directory,
            f"Response saved ({len(response)} chars; appears truncated: {appears_truncated})",
        )
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as exc:
            append_log(self.case_directory, f"Response validation failed: invalid JSON ({exc})")
            raise json.JSONDecodeError(
                f"Estimation Recommendation Agent ({flow['process_id']} / {flow['inventory_name']}): the LLM "
                f"returned invalid/truncated JSON (response length: {len(response)} chars, appears truncated: "
                f"{appears_truncated}). Raw response saved to: {response_path}. Original error: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc
        assessment = FlowAssessment.model_validate(parsed)
        append_log(self.case_directory, "Response validated")
        return assessment

    def __call__(
        self, technology: Technology, confirmed_inventory: ConfirmedInventoryPackage
    ) -> RecommendationPackage:
        print("Running Estimation Recommendation Agent...")
        save_input(self.case_directory, "confirmed_inventory.yaml", confirmed_inventory.model_dump())

        evidence = build_evidence_index(technology, self.lab_derived_parameters)
        entries = []
        for context in prepare_flow_contexts(technology, confirmed_inventory, self.estimation_methods):
            flow = context["flow"]
            print(f"  assessing {flow['process_id']} / {flow['inventory_name']}...")
            assessment = self._assess(technology, context)
            entry = rank_candidates(
                flow,
                context["candidate_rows"],
                assessment,
                linear_extrapolation=context["linear_extrapolation"],
                laboratory_quantity=context["laboratory_quantity"],
                evidence=evidence,
            )
            recommended = entry.recommended_method.method_id if entry.recommended_method else None
            alternative = entry.more_representative_method.method_id if entry.more_representative_method else None
            append_log(
                self.case_directory,
                f"Ranked: recommended={recommended}, alternative={alternative}, checks={len(entry.checks)}",
            )
            for check in entry.checks:
                append_log(self.case_directory, f"  {check}")
            entries.append(entry)

        package = RecommendationPackage(recommendations=entries)
        save_parsed(self.case_directory, "recommendation.yaml", package.model_dump())
        append_log(self.case_directory, "Parsed recommendation package saved")
        return package
