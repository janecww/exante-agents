# pLCA-agents

Human-in-the-loop multi-agent framework for prospective Life Cycle Assessment (pLCA).

---

# Overview

This repository implements the **Stage 1 Proof of Concept (POC)** of a human-in-the-loop multi-agent framework for prospective Life Cycle Assessment (LCA).

Instead of directly generating a foreground Life Cycle Inventory (LCI), the framework assists LCA practitioners by developing scientifically justified process and foreground inventory assumptions that can be reviewed by experts before engineering calculations are performed.

The current implementation produces a structured review package for expert review.

For the detailed system architecture and design rationale, see **ARCHITECTURE.md**.

---

# Current Status

Implemented

- ✅ Technology input loading
- ✅ Process Evolution Agent
- ✅ Scientific Review Agent
- ✅ Structured review package generation (`review_package.yaml`)
- ✅ Manual Excel review package export (`review_package.xlsx`)

Planned

- Human review integration
- Human feedback interpretation
- Engineering calculations
- Foreground LCI generation
- Stage 2 workflow

---

# Repository Structure

```text
src/

    agents/
    orchestrator/
    prompts/
    skills/
    schemas/
    models/
    state/
    tools/

tests/

cases/

main.py
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

Execute

```bash
python main.py
```

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
parsed/review_package.yaml
```

---

## 3. Generate the Excel review package

The Excel export utility is currently **temporary** and is **not yet integrated into the LangGraph workflow**.

After Stage 1 completes successfully, manually execute

```bash
python src/tools/export_review_package.py
```

This converts

```text
parsed/review_package.yaml
```

into

```text
review_package.xlsx
```

for expert review.

Automatic export will be integrated into the orchestrator in a future milestone.

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

- Human review integration
- Human feedback interpretation
- Review Integration Agent
- Engineering calculations
- Material balance validation
- Energy balance validation
- Unit consistency validation
- Foreground LCI generation

---

# Documentation

- **ARCHITECTURE.md** — System architecture and design rationale
- **cases/** — Example case studies