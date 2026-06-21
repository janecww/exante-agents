import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from agents import assumption_agent, inventory_agent, scope_agent, uncertainty_agent
from schemas.workflow_state import WorkflowState

CONFIDENCE_THRESHOLD = 0.6


class Orchestrator:
    def __init__(self, technology: str, scale: str):
        self.technology = technology
        self.scale = scale
        self.state = WorkflowState()
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = Path("outputs/logs")
        self.inventory_dir = Path("outputs/inventory")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.inventory_dir.mkdir(parents=True, exist_ok=True)
        self._setup_logging()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        log_file = self.log_dir / f"run_{self.run_id}.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )
        self.logger = logging.getLogger("orchestrator")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> WorkflowState:
        self.logger.info("=" * 60)
        self.logger.info("pLCA WORKFLOW STARTED")
        self.logger.info(f"Technology : {self.technology}")
        self.logger.info(f"Scale      : {self.scale}")
        self.logger.info(f"Run ID     : {self.run_id}")
        self.logger.info("=" * 60)

        self._run_scope()
        self._run_assumptions()
        self._run_uncertainty()

        flagged = self._get_flagged_assumptions()
        if flagged:
            self.logger.info(
                f"{len(flagged)} assumption(s) flagged — confidence < {CONFIDENCE_THRESHOLD} "
                f"or expert review required. Pausing for human review."
            )
            self._human_review(flagged)
        else:
            self.logger.info(
                "All assumptions meet the confidence threshold. "
                "No human review required."
            )

        self._run_inventory()
        self._save_outputs()

        self.logger.info("=" * 60)
        self.logger.info("WORKFLOW COMPLETE")
        self.logger.info(f"Outputs saved to: outputs/")
        self.logger.info("=" * 60)
        return self.state

    # ------------------------------------------------------------------
    # Agent steps
    # ------------------------------------------------------------------

    def _run_scope(self) -> None:
        self.logger.info("--- Scope Agent ---")
        self.state.scope = scope_agent.run(self.technology, self.scale)
        n_params = len(self.state.scope.get("key_parameters", []))
        self.logger.info(f"Scope defined. {n_params} key parameters identified.")

    def _run_assumptions(self) -> None:
        self.logger.info("--- Assumption Agent ---")
        self.state.assumptions = assumption_agent.run(self.state.scope)
        n = len(self.state.assumptions.get("assumptions", []))
        self.logger.info(f"Generated {n} assumptions.")

    def _run_uncertainty(self) -> None:
        self.logger.info("--- Uncertainty Agent ---")
        self.state.uncertainty = uncertainty_agent.run(self.state.assumptions)
        items = self.state.uncertainty.get("assumptions", [])
        low = [i for i in items if i.get("confidence", 1.0) < CONFIDENCE_THRESHOLD]
        self.logger.info(
            f"Evaluated {len(items)} assumptions. "
            f"{len(low)} below confidence threshold ({CONFIDENCE_THRESHOLD})."
        )

    def _run_inventory(self) -> None:
        self.logger.info("--- Inventory Agent ---")
        register = self._build_assumption_register()
        self.state.inventory = inventory_agent.run(self.state.scope, register)
        n = len(self.state.inventory.get("inventory", []))
        self.logger.info(f"Inventory compiled: {n} entries.")

    # ------------------------------------------------------------------
    # Human-in-the-loop
    # ------------------------------------------------------------------

    def _get_flagged_assumptions(self) -> List[Dict[str, Any]]:
        return [
            item
            for item in self.state.uncertainty.get("assumptions", [])
            if item.get("confidence", 1.0) < CONFIDENCE_THRESHOLD
            or item.get("expert_review_required", False)
        ]

    def _assumption_detail_lookup(self) -> Dict[str, Dict]:
        return {
            a["parameter"]: a
            for a in self.state.assumptions.get("assumptions", [])
        }

    def _human_review(self, flagged: List[Dict[str, Any]]) -> None:
        self.logger.info("--- Human Review ---")
        lookup = self._assumption_detail_lookup()
        reviews: Dict[str, Any] = {}

        print()
        print("=" * 60)
        print("  HUMAN REVIEW REQUIRED")
        print(f"  {len(flagged)} assumption(s) need your input before the")
        print("  workflow can proceed to the Inventory Agent.")
        print("=" * 60)

        for idx, item in enumerate(flagged, start=1):
            param = item["parameter"]
            detail = lookup.get(param, {})

            print(f"\n[{idx}/{len(flagged)}] {param}")
            print(f"  Proposed value : {detail.get('value', 'N/A')} {detail.get('unit', '')}")
            print(f"  Confidence     : {item.get('confidence', 'N/A'):.2f}")
            print(f"  Justification  : {item.get('justification', 'N/A')}")
            print(f"  Rationale      : {detail.get('rationale', 'N/A')}")
            print(f"  Analogy used   : {detail.get('analogy', 'N/A')}")
            print(f"  Evidence       : {detail.get('evidence', 'N/A')}")
            print()

            choice = self._prompt_choice(
                "  Decision — [A]pprove  [R]evise  [X] Reject : ",
                valid={"A", "R", "X"},
            )

            if choice == "A":
                decision: Dict[str, Any] = {
                    "action": "approved",
                    "original_value": detail.get("value"),
                    "final_value": detail.get("value"),
                    "unit": detail.get("unit", ""),
                    "expert_note": "",
                }
            elif choice == "R":
                new_val = input(
                    f"  Revised value for '{param}' "
                    f"[current: {detail.get('value', 'N/A')} {detail.get('unit', '')}]: "
                ).strip()
                note = input("  Expert note (optional): ").strip()
                decision = {
                    "action": "revised",
                    "original_value": detail.get("value"),
                    "final_value": new_val,
                    "unit": detail.get("unit", ""),
                    "expert_note": note,
                }
            else:  # X
                note = input("  Reason for rejection (optional): ").strip()
                decision = {
                    "action": "rejected",
                    "original_value": detail.get("value"),
                    "final_value": None,
                    "unit": detail.get("unit", ""),
                    "expert_note": note,
                }

            reviews[param] = decision
            self.logger.info(f"Human decision for '{param}': {decision['action']}")

        self.state.reviews = reviews

        print()
        print("=" * 60)
        print("  Review complete. Proceeding to Inventory Agent.")
        print("=" * 60)
        print()

    @staticmethod
    def _prompt_choice(prompt: str, valid: set) -> str:
        while True:
            choice = input(prompt).strip().upper()
            if choice in valid:
                return choice
            print(f"  Invalid input. Please enter one of: {', '.join(sorted(valid))}")

    # ------------------------------------------------------------------
    # Assumption register (merged view of all agent outputs + reviews)
    # ------------------------------------------------------------------

    def _build_assumption_register(self) -> List[Dict[str, Any]]:
        lookup_assumption: Dict[str, Dict] = {
            a["parameter"]: a
            for a in self.state.assumptions.get("assumptions", [])
        }
        lookup_uncertainty: Dict[str, Dict] = {
            u["parameter"]: u
            for u in self.state.uncertainty.get("assumptions", [])
        }
        reviews = self.state.reviews

        register: List[Dict[str, Any]] = []
        for param, assumption in lookup_assumption.items():
            uncertainty = lookup_uncertainty.get(param, {})
            review = reviews.get(param)

            if review and review["action"] == "rejected":
                self.logger.info(f"Assumption '{param}' rejected by expert — excluded from inventory.")
                continue

            final_value = (
                review["final_value"]
                if review and review["action"] == "revised"
                else assumption.get("value")
            )

            register.append({
                "parameter": param,
                "value": final_value,
                "unit": assumption.get("unit", ""),
                "evidence": assumption.get("evidence", ""),
                "analogy": assumption.get("analogy", ""),
                "confidence": uncertainty.get("confidence", 0.5),
                "expert_review_required": uncertainty.get("expert_review_required", False),
                "expert_decision": review["action"] if review else "",
            })

        return register

    # ------------------------------------------------------------------
    # Output persistence
    # ------------------------------------------------------------------

    def _save_outputs(self) -> None:
        self.logger.info("--- Saving Outputs ---")

        # Full workflow state
        state_path = self.log_dir / f"workflow_state_{self.run_id}.json"
        state_path.write_text(
            json.dumps(self.state.to_dict(), indent=2), encoding="utf-8"
        )
        self.logger.info(f"Workflow state  → {state_path}")

        # Assumption register (JSON)
        register = self._build_assumption_register()
        reg_json = self.inventory_dir / f"assumption_register_{self.run_id}.json"
        reg_json.write_text(json.dumps(register, indent=2), encoding="utf-8")
        self.logger.info(f"Assumption register (JSON) → {reg_json}")

        # Assumption register (CSV)
        reg_csv = self.inventory_dir / f"assumption_register_{self.run_id}.csv"
        if register:
            _write_csv(reg_csv, register, fieldnames=list(register[0].keys()))
            self.logger.info(f"Assumption register (CSV)  → {reg_csv}")

        # Final inventory (CSV)
        inventory_items = self.state.inventory.get("inventory", [])
        inv_csv = self.inventory_dir / f"inventory_{self.run_id}.csv"
        if inventory_items:
            _write_csv(
                inv_csv,
                inventory_items,
                fieldnames=["parameter", "value", "unit", "confidence", "expert_reviewed"],
            )
            self.logger.info(f"Final inventory (CSV)      → {inv_csv}")


def _write_csv(path: Path, rows: List[Dict], fieldnames: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
