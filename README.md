# pLCA-agents

A human-in-the-loop, multi-agent framework that helps LCA practitioners prepare the foreground inventory of an **ex-ante (prospective) LCA** of an emerging bio-based product. For each laboratory inventory flow, it recommends a scale-up estimation method and lists the parameters still needed to apply it.

This repository holds the code, prompts, knowledge base and case outputs for the paper *Ex-Ante LCA of Emerging Bio-Based Products: A Human-AI Collaborative Framework for Scale-Up Decision Support* (Procedia CIRP, manuscript PROCIR-D-26-00293).

**Scope.** The workflow ends with a list of the parameters each selected method needs. The scale-up calculations themselves are outside the current scope (see [Limitations](#limitations)).

For the full design, see [Architecture.md](Architecture.md).

---

## Workflow

The orchestrator runs a **fixed sequence** of nine steps. Three steps call an agent (a language model); two are **review checkpoints** where the workflow pauses until the practitioner has edited an Excel workbook. All hand-offs pass through the orchestrator; the agents never talk to each other.

```text
Laboratory Case Workbook (practitioner's input)
      │
      ▼
[Agent] Inventory Classification ──► Worksheet 1 "Inventory Classification"
      │
      ▼
◆ Review checkpoint 1: practitioner confirms/changes each category and
  includes/excludes each flow (including flows the agent proposed)
      │
      ▼
[Agent] Estimation Recommendation ──► Worksheet 2 "Estimation Recommendations"
      │
      ▼
◆ Review checkpoint 2: practitioner selects, per flow, the recommended
  method, the more representative method, or neither
      │
      ▼
[Agent] Parameter Identification ──► Worksheet 3 "Parameter Review"
      │
      ▼
     END  (parameter list per flow; no scale-up calculation)
```

The workflow cannot yet go back to an earlier checkpoint. If the practitioner finds a classification error at checkpoint 2, they must restart from step 1.

---

## What is decided by code, and what by the language model

| Decided by deterministic code | Decided by the language model |
|---|---|
| Routing each flow to the rules of its category (the model never sees other categories' rules) | Classifying each laboratory flow into one of five categories, from the process description |
| Whether Tier 3 linear extrapolation is possible from the laboratory quantity ([`linear_extrapolation.py`](src/tools/linear_extrapolation.py)); the result is passed to the model | Proposing additional flows that usually appear at industrial scale (e.g. heat) |
| Every agent output must match a fixed JSON schema (Pydantic) | Deciding which candidate rules match the flow's unit operation |
| Every cited method must exist in the knowledge base; its name and tier are taken from the knowledge base, not from the model | Deciding whether each rule's required inputs are available in the case evidence, including parameters recorded under different names |
| Every confirmed flow must receive a recommendation | Ranking: recommending the highest-tier available rule, plus at most one more representative rule |
| Every agent-proposed flow is flagged for practitioner review | Writing the rationale |
| The practitioner's selection must be one of the two presented methods | Identifying, for the selected method, which parameters are available and where they come from |
| Calculation readiness is recomputed from each parameter's status | |

If a check fails, the workflow **stops** and keeps the model's raw response in `outputs/responses/`. Nothing is repaired or retried automatically.

The code does **not** check that a recommended method's required inputs are actually present. That judgement is the model's, and the practitioner (checkpoint 2) and the Parameter Identification step act as the safeguards.

---

## Knowledge base

| File | What it holds | Used by |
|---|---|---|
| [`src/skills/scaleup_decision_framework.xlsx`](src/skills/scaleup_decision_framework.xlsx), worksheet `rules` | 37 scale-up rules, one row per method | Estimation Recommendation, Parameter Identification |
| [`src/skills/component_definition.yaml`](src/skills/component_definition.yaml) | Definitions of the five categories | Inventory Classification |
| [`src/skills/source_priority.yaml`](src/skills/source_priority.yaml) | Evidence hierarchy (project data first, model knowledge last) | Estimation Recommendation |

**Categories:** reactant, solvent, catalyst, energy (electricity only) and heat (thermal energy for heating or cooling).

**Tiers** (1 = least representative, 6 = most):

| Tier | Name in the knowledge base | Example (electricity) |
|---|---|---|
| 1 | omission / cut-off | ENER-T1 omission of minor electricity |
| 2 | proxy substitution | ENER-T2 literature specific energy consumption |
| 3 | linear extrapolation | ENER-T3 linear scaling of measured lab electricity |
| 4 | heuristic default factor | ENER-T4 rated power and duty time |
| 5 | empirical scaling law | ENER-T5 power-law capacity scaling |
| 6 | engineering equation | ENER-T6 agitation equation (Piccinno et al.) |

**One rule, as stored (ENER-T4):**

| Column | Value |
|---|---|
| `component` / `tier` / `method_id` | Energy / 4 / ENER-T4 |
| `method_name` | Rated power and duty time |
| `operation_scope` | generic, derived from equipment specification |
| `applies_when` | equipment power AND operating time AND load factor AND throughput available |
| `rule_or_equation` | E = P_rated × t × load_factor / throughput |
| `required_inputs` | equipment_nameplate_power_kW; operating_time_h; load_factor; throughput |
| `input_sourcing` | LITERATURE_BENCHMARK_REQUIRED (other values: PROJECT_DATA_ONLY, PHYSICAL_CONSTANT_OK) |
| `produces` | kWh electric per FU |
| `reference` | standard electrical engineering relation |

The workbook also has columns that play **no role** in method recommendation (`confidence`, `confidence_color`, `escalate_if`, `bias_direction`, `limitations`, `scope_gap_flag`). In particular, "red" rules are not filtered out and `escalate_if` is not evaluated. See [Architecture.md §5.1](Architecture.md#51-rules-workbook).

---

## Agent outputs

Each agent writes its output to a YAML file in `outputs/parsed/` and to a worksheet of `outputs/parsed/lci_development_workbook.xlsx`. One row from the baseline case:

**Worksheet 2, Estimation Recommendations (P06, trichloromethane):**

| Recommended | More representative | Additional information required |
|---|---|---|
| SOLV-T3 Linear scaling of lab solvent charge (Tier 3) | SOLV-T4 Recovery fraction heuristic (Tier 4) | assumed recovery fraction |

Each row also carries a free-text rationale stating which evidence made the recommended method available and why each higher tier was not.

**Worksheet 3, Parameter Review** has one row per required parameter of the selected method, with columns `Status` (available / missing), `Value`, `Unit`, `Source`, `Source Type` and `Note`.

---

## Reproducing the paper

### Language model

| Setting | Value |
|---|---|
| Model | `nvidia/nemotron-3-ultra-550b-a55b:free` (NVIDIA Nemotron 3 Ultra) |
| Access | OpenRouter API, through the OpenAI Python SDK ([`config.py`](config.py)) |
| Sampling | `temperature = 0`, `seed = 42`; other settings at provider defaults |
| Call style | One single-turn prompt per agent call; the reply must be JSON |

The first runs (27 Aug 2026) used `nvidia/nemotron-3-super-120b-a12b:free` with provider-default sampling. That free model was withdrawn in Nov 2026, so all scenarios are re-run with the settings above.

Results are **not guaranteed to be bit-reproducible**: providers may not be fully deterministic even at temperature 0, may ignore the seed, and the free-tier endpoint may route requests to different providers. Every prompt and raw response from the reported runs is kept under `cases/*/outputs/prompts/` and `cases/*/outputs/responses/`.

### Scenarios

| Paper scenario | Case folder | What differs from the baseline |
|---|---|---|
| Baseline | [`cases/starch_nanocrystals`](cases/starch_nanocrystals) | — |
| Information removal | [`cases/01_MKS_completeness_DOWN_minimal`](cases/01_MKS_completeness_DOWN_minimal) | Starch (hydrolysis) and water (final homogenising) quantities removed; hydrolysis reaction time and mixture mass removed |
| Information enrichment | [`cases/02_MKS_completeness_UP_ultrasonication`](cases/02_MKS_completeness_UP_ultrasonication) | Ultrasonication rated power, operating time, load factor and throughput added; ultrasonication electricity changed from 3.61 to 225 kWh |

Each scenario was run **once** with the final code (27 Aug 2026). The knowledge base was edited (REACT-T1 and REACT-T2 rows only) between the baseline/enrichment runs and the removal run; see commit `e8b46ba`.

The practitioner decisions made in each run are stored in that case's `outputs/parsed/lci_development_workbook.xlsx`: Worksheet 1 columns "Final Component" and "Include Inventory", and Worksheet 2 column "Human Selected Method ID".

### Setup

Python 3.12. Package versions used for the paper runs:

```text
openai==2.47.0  langgraph==1.2.9  langgraph-checkpoint-sqlite==3.1.1
pydantic==2.13.4  openpyxl==3.1.5  PyYAML==6.0.3  python-dotenv==1.2.2
```

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Then put your `OPENROUTER_API_KEY` in `.env`.

### Running a case

`main.py` runs the case named in its `CASE_DIR` constant; edit that line to choose a scenario. The workflow pauses at each review checkpoint, so a full run is one `start` and two `resume` calls:

```bash
python main.py start
```

Open `cases/<case>/outputs/parsed/lci_development_workbook.xlsx`, complete Worksheet 1 ("Final Component", "Include Inventory"), save, then:

```bash
python main.py resume
```

Complete Worksheet 2 ("Human Selected Method ID": the recommended ID, the more representative ID, or blank for neither), save, then:

```bash
python main.py resume
```

The final result is `outputs/parsed/reviewed_recommendation.yaml` plus Worksheet 3 of the workbook.

### Tests

```bash
python -m pytest -q --ignore=tests/test_estimation_recommendation_diagnostics.py --ignore=tests/test_estimation_recommendation_framework_coverage.py
```

These tests replace the language model with canned responses (349 pass). The two ignored files call the real model and are diagnostics, not regression tests.

---

## Case folder layout

```text
cases/<case>/
    laboratory_case_workbook.xlsx   # input: Technology Overview, Process Inventory, Lab-Derived Parameters
    references/                     # optional; for the practitioner's own use (not read by the code)
    test_notes.xlsx                 # stress-test cases only: what was changed and what is expected
    outputs/
        inputs/      # inputs as passed to each agent (YAML)
        prompts/     # exact prompt sent for every agent call
        responses/   # raw model reply for every agent call
        parsed/      # validated outputs (YAML) and the LCI Development Workbook
        logs/        # workflow.log
        checkpoints.sqlite  # LangGraph state, used to resume after a checkpoint
```

---

## Repository layout

```text
src/
    agents/        Inventory Classification, Estimation Recommendation, Parameter Identification
                   (module: parameter_requirement.py)
    orchestrator/  LangGraph graph (graph_builder.py) and workflow driver (orchestrator.py)
    prompts/       prompt construction for each agent
    skills/        knowledge base (rules workbook + YAML)
    models/        Pydantic schemas for every agent output
    state/         shared LangGraph state
    tools/         deterministic loaders, exporters/importers, Tier 3 pre-computation
tests/
cases/
docs/
main.py               entry point (start / resume)
run_scale_up_demo.py  stand-alone scale-up calculation prototype, not part of the workflow
```

---

## Limitations

- **One run per scenario.** Run-to-run variability has not been measured systematically. Across the reported runs, some flows with identical evidence got different results (see `docs/revision_R2_code_check.md`).
- **No backward routing.** The practitioner cannot send the workflow back to an earlier checkpoint.
- **Two options per flow.** The practitioner chooses between the recommended and one more representative method, or neither; no full ranked list is offered.
- **Input availability is judged by the model**, not checked in code (see the table above).
- **No scale-up calculation.** The workflow ends with the parameter list. `run_scale_up_demo.py` is an unintegrated prototype.
- **One process tested.** Only the starch nanocrystal (SNC) process and two variants of it.
- **Human-in-the-loop not evaluated with users.** The checkpoints have been exercised by the authors but not tested with independent practitioners.

---

## Licence and citation

No licence has been chosen yet. Until one is added, all rights are reserved by the authors. A citation entry will be added when the paper is published.
