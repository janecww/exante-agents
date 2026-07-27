# pLCA-agents

AI-assisted prospective Life Cycle Assessment (pLCA) with human-in-the-loop expert review.

## Demo case study

Brown seaweed-based bioplastic at 4,000 tonnes/year production capacity.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your OPENROUTER_API_KEY
```

## Run

```bash
python main.py
```

## Workflow

```
Scope Agent → Assumption Agent → Uncertainty Agent → [Human Review] → Inventory Agent
```

| Step | What happens |
|---|---|
| **Scope Agent** | Defines functional unit, system boundary, foreground/background processes, and key parameters |
| **Assumption Agent** | Generates quantitative assumptions with values, units, analogies, and evidence |
| **Uncertainty Agent** | Evaluates confidence (0–1) for each assumption; flags those needing expert review |
| **Human Review** | Pauses workflow for any assumption with confidence < 0.6 or `expert_review_required = true` |
| **Inventory Agent** | Compiles final prospective inventory table from approved assumptions |

## Human review

For each flagged assumption the terminal shows:

- Proposed value and unit
- Confidence score and justification
- Rationale and analogy used
- Supporting evidence

You choose: **[A]pprove**, **[R]evise** (enter new value), or **[X] Reject**.  
Rejected assumptions are excluded from the inventory. The workflow does not proceed until all flagged assumptions are resolved.

## Outputs

All outputs are timestamped with the run ID (`YYYYMMDD_HHMMSS`).

| File | Description |
|---|---|
| `outputs/logs/run_<id>.log` | Full execution log |
| `outputs/logs/workflow_state_<id>.json` | Complete workflow state (all agent outputs + decisions) |
| `outputs/inventory/assumption_register_<id>.json` | Assumption register with traceability (JSON) |
| `outputs/inventory/assumption_register_<id>.csv` | Assumption register (CSV) |
| `outputs/inventory/inventory_<id>.csv` | Final prospective inventory table (CSV) |

## Assumption register fields

| Field | Description |
|---|---|
| `parameter` | Name of the inventory parameter |
| `value` | Final approved value (revised if expert changed it) |
| `unit` | Unit of measurement |
| `evidence` | Supporting literature or data source |
| `analogy` | Analogous technology used as proxy |
| `confidence` | Confidence score 0.0–1.0 |
| `expert_review_required` | Whether expert review was triggered |
| `expert_decision` | `approved`, `revised`, `rejected`, or blank |

## Configuration

Edit `main.py` to change the technology description or production scale.  
The confidence threshold (default 0.6) is set in `harness/orchestrator.py`.


## Notes
Run "python -m venv venv"
Run ".\venv\Scripts\Activate.ps1"