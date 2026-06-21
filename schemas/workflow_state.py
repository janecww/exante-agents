from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class WorkflowState:
    scope: Dict[str, Any] = field(default_factory=dict)
    assumptions: Dict[str, Any] = field(default_factory=dict)
    uncertainty: Dict[str, Any] = field(default_factory=dict)
    reviews: Dict[str, Any] = field(default_factory=dict)
    inventory: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "assumptions": self.assumptions,
            "uncertainty": self.uncertainty,
            "reviews": self.reviews,
            "inventory": self.inventory,
        }
