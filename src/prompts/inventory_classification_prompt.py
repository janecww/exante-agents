"""Prompt construction for the Inventory Classification Agent.

Assembles a single plain-text prompt from the technology input and the
`component_definition` skill. Per the Inventory Classification Agent's
design, this is intentionally the *only* knowledge source used during
classification -- any other shared skills present in the injected
skills dictionary (e.g. `source_priority`) are ignored here. This
module performs no reasoning and makes no LLM calls; it only prepares
the context a future LLM-powered agent will consume.

The agent performs two tasks from this one prompt: classifying every
existing foreground input inventory (unchanged from the original
design), and conservatively suggesting additional inventories that
commonly become explicit at industrial scale (e.g. steam, cooling
water, compressed air). Both tasks share one output schema,
distinguished by `inventory_source` ("User Input" vs.
"Agent Suggestion"); suggestions are recommendations only and are never
treated as confirmed foreground inventories. Agent-suggested entries
are always instructed to require human review -- the agent
(`src/agents/inventory_classification.py`) additionally enforces this
deterministically after validation, so it holds even if the LLM does
not comply with this instruction.
"""

import json

from src.models.inventory_classification import (
    AGENT_SUGGESTION_REVIEW_REASON,
    InventoryClassificationPackage,
)
from src.models.technology import Technology
from src.prompts.prompt_helpers import (
    dump,
    extract_process_context,
    format_technology_overview,
    section,
)
from src.prompts.schema_skeleton import build_json_skeleton


def _format_available_knowledge(skills: dict) -> str:
    """Render the `component_definition` skill only.

    Inventory classification uses a single knowledge source by design;
    any other shared skill supplied in `skills` is deliberately not
    shown to the LLM here.
    """
    component_definition = skills.get("component_definition")
    if not component_definition:
        return "(component_definition skill not supplied)"

    return f"Component Definition\n\n{dump(component_definition)}"


def _extract_foreground_inputs(technology: Technology) -> list[dict]:
    """Flatten every process's input inventories into one list.

    Only input flows are extracted. Process outputs (products,
    wastewater, biowaste, emissions) are process results, not foreground
    inventories to classify, and must never appear here.
    """
    return [
        {
            "process_id": process.id,
            "process_name": process.name,
            "inventory_name": flow.name,
            "value": flow.value,
            "unit": flow.unit,
        }
        for process in technology.processes
        for flow in process.inputs
    ]


def build_inventory_classification_prompt(technology: Technology, skills: dict) -> str:
    """Build the Inventory Classification Agent prompt for one technology.

    Args:
        technology: The full Technology model for the case.
        skills: Dictionary of shared Stage 1 skills, keyed by skill name.
            Only the `component_definition` skill is used.

    Returns:
        A single plain-text prompt string (no chat/message formatting).
    """
    role = (
        "The Inventory Classification Agent classifies each foreground "
        "input inventory of a laboratory-scale technology into a "
        "predefined component category, and conservatively suggests "
        "additional inventories that commonly become explicit during "
        "industrial-scale implementation, in preparation for estimation "
        "method retrieval. Suggested additional inventories are "
        "recommendations only and are never automatically added to the "
        "foreground inventory."
    )

    foreground_inputs = _extract_foreground_inputs(technology)
    process_context = extract_process_context(technology)

    task = (
        "Perform two tasks for this technology.\n\n"
        "TASK 1 - CLASSIFY EXISTING INVENTORIES\n"
        "Classify every foreground input inventory shown in FOREGROUND "
        "INPUT INVENTORIES above into exactly one component category, "
        "using only the component definitions above. Consider both the "
        "inventory name and its process context. Provide a concise "
        "rationale (1-2 sentences) for the chosen category, and set "
        "inventory_source to \"User Input\". Set human_review_required "
        "to \"Yes\" only when the inventory could reasonably belong to "
        "multiple component categories, its name is ambiguous, or the "
        "process context does not provide sufficient information to "
        "confidently determine its role; otherwise set it to \"No\". "
        "When human_review_required is \"Yes\", explain why in "
        "review_reason; otherwise leave review_reason empty.\n\n"
        "TASK 2 - SUGGEST POTENTIAL ADDITIONAL INVENTORIES\n"
        "For each process shown in LABORATORY PROCESS CONTEXT above, "
        "consider whether additional inventories commonly become "
        "explicit during industrial-scale implementation (for example: "
        "heat, steam, cooling water, compressed air), based on the "
        "process type, process context, its existing inventories, and "
        "general engineering knowledge. Be conservative: only suggest "
        "an additional inventory when there is reasonable engineering "
        "justification, and never suggest one that is already listed "
        "as an existing input for that process. Do not estimate a "
        "quantity for a suggested inventory and do not treat it as "
        "part of the confirmed foreground inventory -- it is a "
        "recommendation for the human reviewer to accept or reject. "
        "For each suggestion, classify it into a component category "
        "using the same component definitions and provide a concise "
        "rationale, then set inventory_source to \"Agent Suggestion\". "
        "Introducing a new inventory always changes the foreground LCI, "
        "so -- unlike TASK 1 -- human review is never optional here: "
        "always set human_review_required to \"Yes\" and review_reason "
        f'to exactly: "{AGENT_SUGGESTION_REVIEW_REASON}"\n\n'
        "Populate the JSON structure shown in EXPECTED OUTPUT below "
        "with one entry per inventory: first one entry for every "
        "inventory listed in FOREGROUND INPUT INVENTORIES (in the same "
        "order, from TASK 1), followed by one entry for every "
        "additional inventory you suggest (from TASK 2). Do not "
        "classify process outputs; they are out of scope for both "
        "tasks."
    )

    skeleton = build_json_skeleton(InventoryClassificationPackage)
    expected_output = (
        "Below is the exact JSON structure expected. Copy this structure "
        "exactly. Populate values only.\n\n"
        "Do not:\n"
        "- rename fields\n"
        "- remove fields\n"
        "- add fields\n"
        "- replace nested objects with strings\n"
        "- replace lists with dictionaries\n\n"
        "Return ONLY valid JSON. Do not include markdown, explanations, or "
        "code fences.\n\n"
        f"{json.dumps(skeleton, indent=2)}"
    )

    sections = [
        section("ROLE", role),
        section("AVAILABLE KNOWLEDGE", _format_available_knowledge(skills)),
        section("TECHNOLOGY OVERVIEW", format_technology_overview(technology)),
        section("FOREGROUND INPUT INVENTORIES", dump(foreground_inputs)),
        section("LABORATORY PROCESS CONTEXT", dump(process_context)),
        section("TASK", task),
        section("EXPECTED OUTPUT", expected_output),
    ]

    return "\n".join(sections)
