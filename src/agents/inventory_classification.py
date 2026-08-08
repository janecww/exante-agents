"""Inventory Classification Agent for the Stage 1 pLCA-agents workflow.

The Inventory Classification Agent extracts every foreground input
inventory from a laboratory-scale technology and classifies each one
into a predefined component category (reactant, solvent, catalyst,
energy, heat), using only the `component_definition` skill. Shared
Stage 1 skills, an LLM callable, and the case's output directory are
injected by the orchestrator during construction rather than resolved
by the agent itself.

This agent prepares inputs for downstream estimation method retrieval;
it does not itself perform scientific judgement about estimation
methods, and its suggested classifications are always subject to human
verification before the workflow continues.

The agent also conservatively suggests additional inventories that
commonly become explicit at industrial scale but are absent from the
laboratory LCI (e.g. steam, cooling water, compressed air). Introducing
a new inventory always changes the foreground LCI, so -- unlike the
component classification itself, which is genuine LLM judgement --
whether an agent-suggested inventory requires human review is a fixed
business rule, not something left to the LLM's discretion: it is
enforced deterministically after validation (see
`_enforce_agent_suggestion_review_policy`), so it holds regardless of
what the raw LLM response contains.

Current milestone:
    Agent -> build prompt -> invoke LLM -> persist raw response -> parse
    JSON -> validate into InventoryClassificationPackage -> enforce the
    fixed human-review policy for agent-suggested inventories -> persist
    parsed package -> return the validated InventoryClassificationPackage

    The LLM is instructed (via the prompt) to return only JSON matching
    the existing InventoryClassificationPackage schema. That JSON is
    parsed with `json.loads()` and validated with
    `InventoryClassificationPackage.model_validate()` -- no manual field
    mapping. If parsing or validation fails, the exception is raised
    as-is (after the raw response has already been saved for debugging);
    the response is never repaired or retried.

Future milestone:
    Human verification of the suggested classifications, followed by
    the Estimation Recommendation Agent.
"""

import json
from pathlib import Path
from typing import Any, Callable

from src.models.inventory_classification import (
    AGENT_SUGGESTION_HUMAN_REVIEW_REQUIRED,
    AGENT_SUGGESTION_REVIEW_REASON,
    AGENT_SUGGESTION_SOURCE,
    InventoryClassificationPackage,
)
from src.models.technology import Technology
from src.prompts.inventory_classification_prompt import (
    build_inventory_classification_prompt,
)
from src.tools.output_writer import (
    append_log,
    save_input,
    save_parsed,
    save_prompt,
    save_response,
)


def _enforce_agent_suggestion_review_policy(
    package: InventoryClassificationPackage,
) -> InventoryClassificationPackage:
    """Force the fixed human-review policy for every agent-suggested entry.

    Every entry whose `inventory_source` is `AGENT_SUGGESTION_SOURCE`
    (matched case-insensitively, since the LLM's exact casing cannot be
    relied on) has `human_review_required` and `review_reason`
    overwritten to the fixed policy values -- and `inventory_source`
    itself normalized to its canonical casing -- regardless of what the
    LLM returned. "User Input" entries are left untouched: their
    human-review determination remains genuine LLM judgement.
    """
    for entry in package.inventories:
        if (entry.inventory_source or "").strip().lower() == (
            AGENT_SUGGESTION_SOURCE.lower()
        ):
            entry.inventory_source = AGENT_SUGGESTION_SOURCE
            entry.human_review_required = AGENT_SUGGESTION_HUMAN_REVIEW_REQUIRED
            entry.review_reason = AGENT_SUGGESTION_REVIEW_REASON
    return package


class InventoryClassificationAgent:
    """Inventory Classification Agent: classifies every foreground input.

    Shared Stage 1 skills, an LLM callable, and the case's output
    directory are provided by the orchestrator during construction. The
    current implementation builds the prompt, invokes the LLM, persists
    the input/prompt/response/parsed artifacts, and validates the raw
    JSON response into an `InventoryClassificationPackage` using
    Pydantic.
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
            Shared Stage 1 skills injected by the orchestrator. Only the
            `component_definition` skill is used during classification.
        case_directory
            The case directory whose `outputs/` tree execution artifacts
            are persisted under.
        """
        self.llm = llm
        self.skills = skills
        self.case_directory = Path(case_directory)

    def __call__(self, technology: Technology) -> InventoryClassificationPackage:
        """Build the prompt, invoke the LLM, and return a validated package.

        Parameters
        ----------
        technology
            The full Technology model for the case.

        Returns
        -------
        InventoryClassificationPackage
            The LLM's response, parsed as JSON and validated into an
            `InventoryClassificationPackage`. Raises
            `json.JSONDecodeError` or a Pydantic `ValidationError` if the
            response is not valid JSON matching the expected schema; the
            response is never repaired or retried.
        """
        print("Running Inventory Classification Agent...")

        save_input(self.case_directory, "technology.yaml", technology.model_dump())

        prompt = build_inventory_classification_prompt(technology, self.skills)
        save_prompt(self.case_directory, "inventory_classification.txt", prompt)
        append_log(self.case_directory, "Inventory Classification")
        append_log(self.case_directory, "Prompt generated")

        response = self.llm(prompt)
        append_log(self.case_directory, "LLM invoked")

        save_response(self.case_directory, "inventory_classification.txt", response)
        append_log(self.case_directory, "Response saved")

        validated_package = InventoryClassificationPackage.model_validate(
            json.loads(response)
        )
        append_log(self.case_directory, "Response validated")

        validated_package = _enforce_agent_suggestion_review_policy(validated_package)
        append_log(
            self.case_directory, "Agent-suggested inventories require human review"
        )

        save_parsed(
            self.case_directory,
            "inventory_classification.yaml",
            validated_package.model_dump(),
        )
        append_log(self.case_directory, "Parsed inventory classification saved")

        return validated_package
