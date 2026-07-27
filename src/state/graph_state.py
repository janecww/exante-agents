"""Shared LangGraph state for the Stage 1 pLCA-agents workflow.

`GraphState` is the shared state object passed throughout the LangGraph
workflow as the Process Evolution Agent and Scientific Review Agent execute. It does not
define new data structures; it only references the existing `Technology`
and `ReviewPackage` Pydantic models so that the graph, the agents, and the
orchestrator all share one canonical representation of the workflow data.

- `technology` is the user-provided description of the laboratory-scale
  technology. It is treated as immutable input: it is loaded once from
  `technology.yaml` and read by agents, never modified during the workflow.
- `review_package` is an evolving working document that is progressively populated
  and refined as the workflow runs: created by the Process Evolution Agent,
  then annotated by the Scientific Review Agent, until it is ready for
  human review. It is `None` until the first draft has been produced.

Developer note: this proof-of-concept intentionally omits workflow
metadata (e.g. iteration count, current agent, retry count, convergence
status). 

Future work: A future version of the framework may introduce a dedicated
`WorkflowState` model to track workflow execution metadata (e.g.
iteration count, convergence status, retry information, or checkpoint
state). This can be added without changing the existing Technology or
ReviewPackage models.
"""

from typing import TypedDict

from src.models.review_package import ReviewPackage
from src.models.technology import Technology


class GraphState(TypedDict):
    """Shared state passed between LangGraph nodes in the Stage 1 workflow."""

    technology: Technology
    review_package: ReviewPackage | None
