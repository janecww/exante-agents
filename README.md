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
◆ Review checkpoint 2: practitioner selects, per flow, any rule shown
  (recommended, more representative, or another listed rule), or none
      │
      ▼
[Agent] Parameter Identification ──► Worksheet 3 "Parameter Review"
      │
      ▼
     END  (parameter list per flow; no scale-up calculation)
```

The practitioner can return the current run to checkpoint 1 or 2 with `python main.py back 1|2` (see [Running a case](#running-a-case)); for example, a classification error found at checkpoint 2 is corrected on Worksheet 1 without restarting the run.

---

## What is decided by code, and what by the language model

Both agents that judge evidence (Estimation Recommendation and Parameter Identification) receive **one and the same definition of "available"** ([`src/skills/availability.py`](src/skills/availability.py), summarised under [Knowledge base](#knowledge-base)), inserted verbatim into both prompts.

| Decided by deterministic code | Decided by the language model |
|---|---|
| Routing each flow to the rules of its category (the model never sees other categories' rules) | Classifying each laboratory flow into one of five categories, from the process description |
| Whether Tier 3 linear extrapolation is possible from the laboratory quantity ([`linear_extrapolation.py`](src/tools/linear_extrapolation.py)) | Proposing additional flows that usually appear at industrial scale (e.g. steam) |
| The tag of every input (LAB, CONSTANT, DEFAULT, LITERATURE, TARGET), taken from the framework; DEFAULT values filled in | Whether a named rule's operation matches the flow's process step, and whether its conditions hold (true / false / cannot tell; a rule whose conditions cannot be confirmed is never recommended, but can be offered as the alternative) |
| **Ranking** ([`method_ranking.py`](src/tools/method_ranking.py)): the recommended method (highest-tier available rule), the alternative (higher-tier rule with the fewest missing inputs), the other higher-tier rules, the same- or lower-tier rules, and the rules ruled not applicable (with the agent's reason) | The status of every input (available / missing / ambiguous), with value, unit, source and, for a derived value, the derivation |
| The rationale, written from the same input-by-input assessment, so it cannot contradict the ranking | For the selected method, the value and source of every input, and for each missing one where it could be obtained (Parameter Identification) |
| Calculation readiness: every non-TARGET input available | |
| Checks C1-C7 (below) | |
| Every agent output matches a fixed JSON schema (Pydantic); every agent-proposed flow is flagged for practitioner review; every included flow's Final Component (checkpoint 1) is one of the five categories; the practitioner's selection (checkpoint 2) must be a method shown for that flow (recommended, alternative, or listed under other higher-tier, same- or lower-tier, or not applicable) | |

**Checks.** A response that is not valid JSON or does not match the schema **stops** the workflow, with the raw response kept in `outputs/responses/`; nothing is repaired or retried. Smaller problems are handled conservatively and shown to the practitioner:

| Check | What | Shown in |
|---|---|---|
| C1 | The alternative is a higher tier than the recommended method (holds by construction) | - |
| C2 | Every input of the selected method has the same status in Parameter Identification as in the recommendation step | Worksheet 3, "Consistency Check" |
| C3 | Tier 3: the model's status of the laboratory quantity agrees with the code's linear-extrapolation result (the code wins) | Worksheet 2, "Checks" |
| C4 | Every rule and input was assessed, and none was invented (unassessed = not applicable / missing) | Worksheet 2, "Checks" |
| C5 | An input marked available has a value and a source (otherwise treated as missing) | Worksheets 2 and 3 |
| C6 | Evidence trace ([`evidence_trace.py`](src/tools/evidence_trace.py)): an available LAB value, or every number in its derivation, is found in the case workbook with Provenance Reported or Calculated (LITERATURE: anywhere in the evidence), allowing unit conversions and rounding; a parsed derivation must reproduce the value (otherwise treated as missing; an unparseable derivation is kept with a note) | Worksheets 2 and 3 |
| C7 | A suggestion of where to find a missing input says where to look, never what the value is: a suggestion containing a number is removed | Worksheet 3 |

An invalid practitioner entry (a Final Component outside the five categories, or a selection that is not a method shown for that flow) stops the workflow with a message naming the row, so it can be corrected and resumed.

---

## Knowledge base

| File | What it holds | Used by |
|---|---|---|
| [`src/skills/scaleup_decision_framework.xlsx`](src/skills/scaleup_decision_framework.xlsx), sheet `rules` | 37 scale-up rules, one row per method; the only sheet any agent sees | Estimation Recommendation, Parameter Identification |
| same workbook, sheet `documentation` | Literature basis, confidence and limitations of each rule, for people; never sent to an agent | - |
| same workbook, sheet `how_to_use` | Meaning of every sheet and column, the input tags and the definition of "available" | - |
| [`src/skills/component_definition.yaml`](src/skills/component_definition.yaml) | Definitions of the five categories | Inventory Classification |

How the framework was restructured from its first version (tags, conditions, one output per category) is recorded per rule in [docs/framework_v2_changes.md](docs/framework_v2_changes.md).

**Categories:** reactant, solvent, catalyst, energy and heat ([`component_definition.yaml`](src/skills/component_definition.yaml)). *Energy* is the electricity used to run process equipment (stirrers, pumps, centrifuges, homogenisers, ultrasonic devices). *Heat* is thermal energy for heating or cooling, whatever its source (steam, hot oil, chilled water, electric heating); it is the special case of energy kept as its own category because it is estimated from mass, heat capacity, temperature change and heat losses rather than from equipment power and time. A measured electricity flow that also covers heating stays *energy*, and the practitioner decides at checkpoint 1 whether a separate heat flow would count the same heating twice. Every rule of a category produces the same quantity: kg reactant, kg solvent (fresh, after any recovery), kg catalyst, kWh electricity or kWh heat, per functional unit.

**Tiers** (1 = least representative, 6 = most):

| Tier | Name in the knowledge base | Example (electricity) |
|---|---|---|
| 1 | omission / cut-off | ENER-T1 omission of minor electricity |
| 2 | proxy substitution | ENER-T2 literature specific energy consumption |
| 3 | linear extrapolation | ENER-T3 linear scaling of measured lab electricity |
| 4 | heuristic default factor | ENER-T4 rated power and duty time |
| 5 | empirical scaling law | ENER-T5 power-law capacity scaling |
| 6 | engineering equation | ENER-T6 agitation equation (Piccinno et al.) |

**One rule, as stored (ENER-T3):**

| Column | Value |
|---|---|
| `component` / `tier` / `method_id` | Energy / 3 / ENER-T3 |
| `method_name` | Linear scaling of measured lab electricity |
| `scope` / `operations` | generic / - |
| `conditions` | - |
| `rule_or_equation` | E_ind = E_lab x scale factor |
| `inputs` | `lab_measured_electricity [LAB]; scale_factor [TARGET]` |
| `produces` | kWh electricity per FU |

**Input tags and the definition of "available":**

| Tag | Available when |
|---|---|
| LAB | Stated in the case evidence with Provenance "Reported" or "Calculated", for the same process step, or derived from such values by an allowed derivation (unit conversion; mass to volume with a stated density or 1 kg/L for water; power = energy / time; sums; fractions) |
| CONSTANT | Always: a standard physical property, stated with its reference |
| DEFAULT | Always: the value fixed by the rule |
| LITERATURE | Only if the value and its citation are in the case evidence; the agent never looks up literature |
| TARGET | Never decides availability (industrial scale, supplied later by the practitioner) |

Several candidate values without a way to choose make an input **ambiguous**, which counts as not available. A rule is available when its operation matches, its conditions hold, and every non-TARGET input is available.

---

## Agent outputs

Each agent writes its output to YAML files in `outputs/parsed/` and to a worksheet of `outputs/parsed/lci_development_workbook.xlsx`.

**Worksheet 2, Estimation Recommendations** has one row per flow: the recommended method, the rationale, the alternative ("more representative") method with the inputs it is missing, the other higher-tier methods with what each is missing, the same- or lower-tier methods, the methods the agent ruled not applicable (with its reason), the checks, and the practitioner's selection. Every rule of the flow's category is therefore shown, and the practitioner may select any of them, or none; the choice is recorded as recommended / alternative / other higher tier / lower tier / not applicable, and a not-applicable selection is written to the workflow log with the agent's reason. The full input-by-input assessment of every candidate is in `recommendation.yaml`.

**Worksheet 3, Parameter Review** has one row per input of the selected method: `Tag`, `Status` (available / missing / ambiguous), `Value`, `Unit`, `Source`, `Source Type`, `Derivation`, `Note`, `Where to Find` (for a missing or ambiguous input: the kind of source to consult, written by the agent) and `Consistency Check` (C2/C5/C6/C7).

---

## Reproducing the paper

### Language model

| Setting | Value |
|---|---|
| Model | `nvidia/nemotron-3-ultra-550b-a55b:free` (NVIDIA Nemotron 3 Ultra) |
| Access | OpenRouter API, through the OpenAI Python SDK ([`config.py`](config.py)) |
| Sampling | `temperature = 0`, `seed = 42`; other settings at provider defaults |
| Call style | One single-turn prompt per call; the reply must be JSON. Estimation Recommendation and Parameter Identification make one call per flow |

The first runs (27 Aug 2026) used `nvidia/nemotron-3-super-120b-a12b:free` with provider-default sampling. That free model was withdrawn in Nov 2026, so all scenarios were re-run with the settings above (5 Nov 2026).

Results are **not guaranteed to be bit-reproducible**: providers may not be fully deterministic even at temperature 0, may ignore the seed, and the free-tier endpoint may route requests to different providers. Every prompt and raw response from the reported runs is kept under `cases/*/outputs/prompts/` and `cases/*/outputs/responses/`.

### Scenarios

| Paper scenario | Case folder | What differs from the baseline |
|---|---|---|
| Baseline | [`cases/starch_nanocrystals`](cases/starch_nanocrystals) | — |
| Information removal | [`cases/01_MKS_completeness_DOWN_minimal`](cases/01_MKS_completeness_DOWN_minimal) | Starch (hydrolysis) and water (final homogenising) quantities removed; hydrolysis reaction time and mixture mass removed |
| Information enrichment | [`cases/02_MKS_completeness_UP_ultrasonication`](cases/02_MKS_completeness_UP_ultrasonication) | Ultrasonication rated power, operating time, load factor and throughput added (four rows); nothing else changed |

Each scenario was run **once** (5 Nov 2026), with the same code, knowledge base, model and sampling settings: baseline `bfd9b18`, removal `21c63e3`, enrichment `fcb5f79`. The earlier 27 Aug 2026 runs, with the previous model, remain in commit `e8b46ba`; [docs/revision_R2_code_check.md §5](docs/revision_R2_code_check.md) compares the two.

The practitioner decisions made in each run are stored in that case's `outputs/parsed/lci_development_workbook.xlsx`: Worksheet 1 columns "Final Component" and "Include Inventory", and Worksheet 2 column "Human Selected Method ID".

### Setup

Python 3.12. Package versions used for the paper runs (pinned in `requirements.txt`, which also pins `pytest==9.1.1`):

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

Complete Worksheet 2 ("Human Selected Method ID": any method ID shown in that row, or blank for none), save, then:

```bash
python main.py resume
```

The final result is `outputs/parsed/reviewed_recommendation.yaml` plus Worksheet 3 of the workbook.

To revise a decision later in the same run, go back to a checkpoint, edit that worksheet, and resume:

```bash
python main.py back 1   # Worksheet 1, inventory review
python main.py back 2   # Worksheet 2, method selection
```

This uses LangGraph's checkpoint history: results computed before the checkpoint are restored, not recomputed; after `resume`, an agent calls the model only for a prompt that changed (identical prompts reuse their saved reply). Nothing is deleted, the return is logged, and `back` never reaches into an earlier run of the case. `start` instead begins a new run, which re-runs classification.

### Tests

```bash
python -m pytest -q
```

These tests replace the language model with canned responses (370 pass). The two files `test_estimation_recommendation_diagnostics.py` and `test_estimation_recommendation_framework_coverage.py` call the real model and are skipped unless `PLCA_LIVE_MODEL_TESTS=1` is set (with `OPENROUTER_API_KEY`); they are diagnostics, not regression tests, predate framework v2 and have not been updated.

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
main.py               entry point (start / resume / back 1|2)
run_scale_up_demo.py  stand-alone scale-up calculation prototype, not part of the workflow
```

---

## Limitations

- **One run per scenario.** Run-to-run variability has not been measured systematically. Across the reported runs, some flows with identical evidence got different results (see `docs/revision_R2_code_check.md`).
- **Returning to a checkpoint is limited to the current run.** `python main.py back 1|2` reopens checkpoint 1 or 2 of the current run; it does not rewrite the worksheets, and `start` begins a new run.
- **Evidence matching is done by the model.** Both agents follow one definition of "available" and the code checks the two results against each other (C2), but whether a value in the evidence is the input a rule needs remains the model's judgement.
- **No scale-up calculation.** The workflow ends with the parameter list. `run_scale_up_demo.py` is an unintegrated prototype.
- **One process tested.** Only the starch nanocrystal (SNC) process and two variants of it.
- **Human-in-the-loop not evaluated with users.** The checkpoints have been exercised by the authors but not tested with independent practitioners.

---

## Licence and citation

The code is released under the MIT License (see [LICENSE](LICENSE)). A citation entry will be added when the paper is published.
