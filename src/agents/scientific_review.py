"""Placeholder Scientific Review Agent for the Stage 1 LangGraph workflow.

The Scientific Review Agent evaluates proposed process and inventory
assumptions for completeness, plausibility, traceability, and scientific
justification.

Shared Stage 1 skills are injected by the orchestrator during
construction rather than loaded by the agent itself. The class implements
``__call__`` so that an instance can be registered directly as a
LangGraph node.

This milestone validates LangGraph state passing and dependency
injection only. The implementation below is intentionally a placeholder
for the future LLM-powered Scientific Review Agent.

============================================================================
Future Work
============================================================================

Future versions may additionally receive shared dependencies through the
same constructor-based dependency injection mechanism, including:

- LLM client
- Shared tools
- Prompt templates
- Literature retrieval interfaces

The callable interface should remain unchanged.
"""

from typing import Any

from src.state.graph_state import GraphState


class ScientificReviewAgent:
    """Placeholder Scientific Review Agent.

    Shared Stage 1 skills are provided by the orchestrator during
    construction. The current implementation validates workflow
    integration only and performs no scientific reasoning.
    """

    def __init__(self, skills: dict[str, Any]) -> None:
        """Initialise the placeholder agent.

        Parameters
        ----------
        skills
            Shared Stage 1 skills injected by the orchestrator.
        """
        self.skills = skills

    def __call__(self, state: GraphState) -> GraphState:
        """Execute the placeholder review step.

        The current implementation simply demonstrates LangGraph
        execution by returning the incoming GraphState unchanged.

        Parameters
        ----------
        state
            Shared workflow state.

        Returns
        -------
        GraphState
            The unchanged workflow state.
        """
        print("Running Scientific Review Agent...")

        # Temporary debug output for validating dependency injection.
        # Remove once prompt construction and LLM integration are implemented.
        if self.skills:
            print("Loaded shared skills:")
            for skill_name in self.skills.keys():
                print(f"- {skill_name}")
        else:
            print("Loaded shared skills: <none>")

        return state