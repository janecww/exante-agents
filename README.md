# pLCA-agents

A human-in-the-loop, multi-agent framework that helps LCA practitioners prepare the foreground inventory of an **ex-ante (prospective) LCA** of an emerging bio-based product. For each laboratory inventory flow, it recommends a scale-up estimation method and lists the parameters still needed to apply it.

This repository holds the code, prompts, knowledge base and case input workbooks for the paper *Ex-Ante LCA of Emerging Bio-Based Products: A Human-AI Collaborative Framework for Scale-Up Decision Support* (Procedia CIRP, manuscript PROCIR-D-26-00293).

**Scope.** The workflow ends with a list of the parameters each selected method needs. The scale-up calculations themselves are outside the current scope.

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

## Reproducing the paper

### Language model

| Setting | Value |
|---|---|
| Model | `nvidia/nemotron-3-ultra-550b-a55b:free` (NVIDIA Nemotron 3 Ultra) |
| Access | OpenRouter API, through the OpenAI Python SDK ([`config.py`](config.py)) |
| Sampling | `temperature = 0`, `seed = 42`; other settings at provider defaults |
| Call style | One single-turn prompt per call; the reply must be JSON. Estimation Recommendation and Parameter Identification make one call per flow |

### Scenarios

All scenarios are built on the starch nanocrystal (SNC) process from mango kernel of Müller-Carneiro et al. (2023). The laboratory equipment and operating conditions follow Oliveira et al. (2018).

| Paper scenario | Case folder | What differs from the baseline |
|---|---|---|
| Baseline | [`cases/starch_nanocrystals`](cases/starch_nanocrystals) | — |
| Information removal | [`cases/01_MKS_completeness_DOWN_minimal`](cases/01_MKS_completeness_DOWN_minimal) | Starch (hydrolysis) and water (final homogenising) quantities removed; hydrolysis reaction time and mixture mass removed |
| Information enrichment | [`cases/02_MKS_completeness_UP_ultrasonication`](cases/02_MKS_completeness_UP_ultrasonication) | Ultrasonication rated power, operating time, load factor and throughput added (four rows; operating time Calculated from the lab, the other three constructed from Arvidsson et al. 2014, Provenance Literature); nothing else changed |
| Literature support | [`cases/03_MKS_completeness_UP_literature`](cases/03_MKS_completeness_UP_literature) | The 20 literature values the original study used for its industrial-scale estimate (Müller-Carneiro et al. 2023, SI Table C.1, citing Piccinno et al. 2016 and Arvidsson et al. 2014) added with Provenance Literature: reactor wall loss, agitator and homogeniser impellers, centrifugation specific energy, ultrasonication specific power. Laboratory values unchanged |

Each scenario was run **once** on framework v2.1, with the same code, model and sampling settings. The practitioner decisions follow the same rules in every run, with two exceptions in the enrichment run: P05 electricity was not suggested by the agent and was added at checkpoint 1, and P04 electricity selects the recommended ENER-T4 (the test target) instead of the reference study's method.

The outputs of the reported runs (prompts, raw model responses, parsed outputs and the practitioner's decisions in the LCI Development Workbook) are available from the authors on request.

**References**

- Müller-Carneiro J, Figueirêdo MCB de, Rodrigues C, Azeredo HMC de, Freire F. Ex-ante life cycle assessment framework and application to a nano-reinforced biopolymer film based on mango kernel. Resour Conserv Recycl 2023;188:106637. https://doi.org/10.1016/J.RESCONREC.2022.106637.
- Oliveira AV, da Silva APM, Barros MO, Souza Filho MSM, Rosa MF, Azeredo HMC. Nanocomposite films from mango kernel or corn starch with starch nanocrystals. Starch/Stärke 2018;70:1800028. https://doi.org/10.1002/star.201800028.

### Setup

Python 3.12. Package versions used for the paper runs (pinned in `requirements.txt`):

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

---

## Case folder layout

```text
cases/<case>/
    laboratory_case_workbook.xlsx   # input: Technology Overview, Process Inventory, Lab-Derived Parameters
    references/                     # optional; for the practitioner's own use (not read by the code)
    outputs/                        # created when the case is run
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
                   (also a stand-alone scale-up calculation prototype, not part of the workflow)
cases/             one folder per scenario (see Case folder layout)
main.py            entry point (start / resume / back 1|2)
config.py          OpenRouter client, model and sampling settings
requirements.txt   pinned package versions
```

---


## Licence and citation

The code is released under the MIT License (see [LICENSE](LICENSE)). A citation entry will be added when the paper is published.
