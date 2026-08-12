# pLCA-agents

Human-in-the-loop multi-agent framework for prospective Life Cycle Assessment (pLCA).

---

# Overview

This repository implements the **Stage 1 Proof of Concept (POC)** of a human-in-the-loop multi-agent framework for prospective Life Cycle Assessment (LCA).

Instead of directly generating a foreground Life Cycle Inventory (LCI), Stage 1 assists LCA practitioners in preparing the foreground inventory for estimation: classifying laboratory-scale inventories into component categories, recommending an estimation method for every confirmed inventory, letting a human select the final method per inventory, and then checking what information that selected method needs before any scale-up calculation is attempted.

For the detailed system architecture and design rationale, see **Architecture.md**.

---

# Current Status

## Stage 1 workflow (implemented)

```text
Laboratory Case Workbook
        ↓
Inventory / Component Classification
        ↓
Estimation Recommendation
        ↓
Human Method Selection (recommended / alternative / neither)
        ↓
Parameter Requirement Review
        ↓
END
```

- ✅ Laboratory Case Workbook input (technology + lab-derived parameters, with provenance)
- ✅ Inventory Classification Agent
- ✅ LCI Development Workbook (Worksheet 1) export/import, native LangGraph Human-in-the-Loop interrupt/resume
- ✅ Estimation Recommendation Agent (retrieves from `scaleup_decision_framework.xlsx`, never invents a method)
- ✅ LCI Development Workbook (Worksheet 2) export/import, including human method selection (recommended / alternative / neither)
- ✅ Parameter Requirement Agent (required / available / missing parameters, calculation readiness)

Stage 1 terminates after the Parameter Requirement Agent has run.

## Stage 2 (standalone prototype, not wired into the workflow)

A standalone scale-up calculation demo (`run_scale_up_demo.py`) exists to validate the Stage 2 design before it is integrated into the LangGraph workflow. It is **not** part of `main.py`/the active graph — see Architecture.md's "Scale-Up Preparation" and "Milestone 2B" sections.

## Planned

- Wiring a real scale-up calculation stage into the active workflow
- Scientific Review Agent
- Engineering calculations, material/energy balance validation, unit consistency validation
- Foreground LCI generation

---

# Repository Structure

```text
src/

    agents/          # Reasoning agents (Inventory Classification, Estimation Recommendation, Parameter Requirement)
    orchestrator/     # LangGraph workflow topology and orchestration
    prompts/          # Prompt construction for each agent
    skills/           # Shared, non-code knowledge (component_definition.yaml, source_priority.yaml, scaleup_decision_framework.xlsx)
    models/           # Pydantic models
    state/            # Shared LangGraph state
    tools/            # Deterministic export/import/loader utilities

tests/

cases/

main.py                  # Stage 1 entry point (start / resume)
run_scale_up_demo.py      # Standalone Stage 2 prototype entry point (not wired into main.py)
```

---

# Getting Started

## 1. Prepare a case

Each execution is organised as a case under the `cases/` directory.

Example

```text
cases/

    starch_nanocrystals/

        laboratory_case_workbook.xlsx   # Required

        references/              # Optional supporting documents

            paper_1.pdf
            supplementary.pdf

        outputs/                 # Generated automatically

            inputs/
            prompts/
            responses/
            parsed/
            logs/
```

### Required input

Every case must contain

```text
laboratory_case_workbook.xlsx
```

This single workbook (see `src/tools/laboratory_case_workbook.py`) combines what used to be two separate files (`technology.yaml` and `references/lab_derived_parameters.xlsx`) into three worksheets: Technology Overview, Process Inventory, and Lab-Derived Parameters. It defines:

- technology information
- laboratory workflow
- laboratory inventory
- target production scale
- functional unit

### Optional input

Supporting documents may be placed under

```text
references/
```

Examples include

- Peer-reviewed journal articles
- Technical reports
- Patents
- Experimental reports
- Supplementary information

If provided, these documents are treated as the highest-priority evidence source during assumption development.

---

## 2. Run Stage 1

The pipeline pauses **twice** for human review, so a full run needs `start` followed by `resume` twice:

```bash
python main.py start
# review/edit Worksheet 1 ("Inventory Classification") in the LCI Development Workbook, then:
python main.py resume
# review Worksheet 2 ("Estimation Recommendations"): enter each inventory's
# "Human Selected Method ID" (recommended, alternative, or leave blank), then:
python main.py resume
```

`resume` reports whichever interrupt is currently pending, so re-running `python main.py resume` after each round of edits is all that's needed.

Execution artifacts are automatically generated under

```text
cases/<case_name>/outputs/

    inputs/
    prompts/
    responses/
    parsed/
    logs/
```

The final structured output is

```text
parsed/reviewed_recommendation.yaml
```

containing, per confirmed inventory, the agent's recommendation, the human's selected method, and the parameter requirement review.

---

## 3. Standalone Stage 2 prototype (optional)

A standalone demo lets you inspect and iterate on the scale-up calculation design without touching the LangGraph workflow:

```bash
python run_scale_up_demo.py
```

It loads a case's `reviewed_recommendation.yaml` (from step 2 above) if one exists, otherwise builds a small synthetic example, and produces `scale_up_demo.xlsx` showing the calculation parameters and results. See Architecture.md's "Milestone 2B — Standalone Scale-Up Calculation Demo" section for details.

---

# Design Principles

The framework follows five core principles:

- Human-in-the-loop decision making
- Structured reasoning
- Schema validation
- Modular architecture
- Extensibility

---

# Future Development

Stage 2 will extend the framework with:

- Wiring a real scale-up calculation stage into the active LangGraph workflow
- Scientific Review Agent
- Engineering calculations
- Material balance validation
- Energy balance validation
- Unit consistency validation
- Foreground LCI generation

---

# Documentation

- **Architecture.md** — System architecture and design rationale
- **cases/** — Example case studies
