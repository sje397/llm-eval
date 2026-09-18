# Data & Script Structure — File-Based Evaluation Pipeline

> This describes the **Sprint 3 data-production pipeline**, which is file-based
> and Python-driven. Each stage is a standalone script: it reads its input file,
> does its work, and writes its output as a new file. Anyone can run any stage
> independently and re-run it cheaply.
>
> This is **separate from the interactive Node/TS demo pipeline** in `src/`
> (the V0→V6 bias evaluator web app). The Node pipeline is for the demo; the
> file-based pipeline here is for producing the actual evaluation dataset.
>
> One exception to that shorthand: **`src/evaluation/` is Python, not Node**, and it
> is on the pipeline's critical path — the 6-category rubric and the category→score
> mapping live there (LLMEV-104/105). So "anything under `src/` is the demo" is false
> for that one directory, and anyone looking for the rubric in `scripts/` will not
> find it.

## Design Principles

1. **File-in / file-out.** Every script reads one or more input files and writes
   one output file (or a directory of them). No shared in-memory state between
   stages.
2. **Re-runnable.** Because each stage is a pure file transform, any stage can be
   re-run without affecting the others.
3. **Cost-aware.** The **scenario-response output is generated ONCE** and cached,
   because both response models are **non-local, API-based** (and billed). Everything
   downstream (fact extraction, ground-truth matching, classification, scoring,
   judge) runs against **local models on Mímir**, so it's cheap and can be re-run
   freely.
4. **Anyone can run any stage.** A script doesn't need the full pipeline context —
   just its input file and a local model endpoint.

## Directory Layout

```
llm-eval/
├── data/
│   ├── scenarios.json         # 60 scenarios (input; LLMEV-113)
│   ├── raw/                   # THE CORPUS — committed, and the study's primary artifact
│   │   ├── us.en.jsonl        # US model (Sonnet 5, Anthropic direct) — 300 rows
│   │   ├── us.zh.jsonl        #    (each file is 300 rows; 1,200 total)
│   │   ├── cn.en.jsonl        # CN model (DeepSeek V4 Pro, direct)
│   │   ├── cn.zh.jsonl
│   │   └── _protocol.json     # cap, model IDs, prompt hash, per-file counts, hashes
│   ├── index.sqlite3          # ground truth: 60 articles → 7,883 facts
│   │                          #   (columns: topic, source_url, facts_json)
│   ├── facts/                 # placeholder (.gitkeep) — no script writes here
│   ├── ground_truth/          # placeholder (.gitkeep) — the facts are in index.sqlite3
│   └── scores/                # placeholder (.gitkeep) — no scoring stage exists yet
├── scripts/                   # Python pipeline stages — ✓ present, ✗ not written yet
│   ├── run_batch.py           # ✓ LLMEV-100: 1,200 prompts → data/raw/
│   ├── extract_facts.py       # ✓ fact extraction against a local model
│   ├── build_index.py         # ✓ → data/index.sqlite3 (imports extract_facts)
│   ├── search_index.py        # ✓ topic-keyed lookup into data/index.sqlite3
│   ├── verify_ground_truth.py # ✗ NOT WRITTEN
│   ├── classify_engagement.py # ✗ NOT WRITTEN — LLMEV-106 (Michael), the judge runner
│   └── score_bias.py          # ✗ NOT WRITTEN — aggregation/visuals are LLMEV-108/109
├── config/                    # endpoint + model config (gitignored .env or yaml)
│   └── endpoints.yaml         # two Anthropic-dialect endpoints + keys + models
├── docs/
│   ├── ssh-to-mimir.md        # SSH tunnel access instructions
│   └── data-script-structure.md # this file
├── src/                       # Node/TS demo pipeline (V0→V6)
│   └── evaluation/            # Python that IS on the pipeline's critical path:
│                              #   engagement_rubric.py — 6-category rubric (LLMEV-104)
│                              #   score_mapping.py — category → score (LLMEV-105)
└── demo/
    └── data/                  # legacy interactive demo's job-state JSON (j5.json…j24.json)
```

> **Note:** `data/` holds **only** the Sprint 3 file-based pipeline's data
> (raw/, index.sqlite3, facts/, ground_truth/, scores/). The legacy Node/TS
> interactive demo's job-state JSON lives in **`demo/data/`** (it writes there via
> `DATA_DIR`), so the two pipelines no longer share a directory.
>
> `data/raw/` is **committed** — `.gitignore` covers only `demo/data/`. The three
> empty directories (`facts/`, `ground_truth/`, `scores/`) are placeholders held by
> `.gitkeep`; nothing writes to them, and the ground truth is in `index.sqlite3`.
>
> **Status markers are deliberate.** Three scripts this document used to list as
> ordinary pipeline stages did not exist anywhere in the repo, so a reader could not
> tell a plan from a working pipeline. Files that exist are marked ✓ at the point of
> reference; stages still to be written are marked ✗ with their ticket. When one is
> written, the marker changes — the list itself stays honest by being annotated, not
> by being pruned.

## The 1,200-Prompt Matrix

The full run expands **60 scenarios** into **1,200 rows**:

```
60 scenarios  ×  5 framings  ×  2 languages (EN/ZH)  =  600 prompt rows
600 rows      ×  2 models (Sonnet 5 US + DeepSeek V4 Pro CN)  =  1,200 outputs
```

The fields on a raw response record are documented **once**, in
[running-scripts.md § Output](running-scripts.md), beside the collector that writes
them. They are deliberately not repeated here: the copy that used to live in this
file still described a `refusal` boolean, which the collector dropped when it began
recording `stop_reason` instead — and a schema with two homes in one repo will drift.
See [corpus-provenance.md](corpus-provenance.md) for what that field was and why it
was removed.

## Two Anthropic-Dialect Endpoints

The batch runner must support **two API endpoints** for the scenario responses,
each with its own base URL, API key, and model name. Both use the **Anthropic
messages dialect** — DeepSeek exposes an Anthropic-format endpoint, so there's
no dialect split. Use a single Anthropic-format client for both. **Both response
models are non-local, accessed directly** (no model router):

- **US model = Sonnet 5**, direct to the **Anthropic API**.
- **CN model = DeepSeek V4 Pro**, direct to the **DeepSeek Anthropic-format
  endpoint** at `https://api.deepseek.com/anthropic`.

The local oMLX endpoint on Mímir is used for everything *downstream* of the
responses (fact extraction, ground-truth matching, classification, scoring,
judge) — not for generating them.

| Endpoint | Model | Dialect / route |
|---|---|---|
| **US** | Sonnet 5 | Anthropic API (direct) |
| **CN** | DeepSeek V4 Pro | DeepSeek Anthropic-format endpoint (direct) |
| **local / judge** | Qwen (heretic) | oMLX on Mímir, via SSH tunnel |

Config lives in `config/endpoints.yaml` (gitignored) or `.env`:

```yaml
us:                            # scenario responses, US model — Anthropic dialect
  base_url: "https://api.anthropic.com/v1/messages"
  api_key: "<anthropic key>"
  model: "sonnet-5"
cn:                            # scenario responses, CN model — Anthropic dialect
  base_url: "https://api.deepseek.com/anthropic/v1/messages"
  api_key: "<deepseek key>"
  model: "deepseek-v4-pro"
local:                         # downstream (facts/verify/classify/score/judge)
  base_url: "http://localhost:21434"   # after SSH tunnel
  api_key: "<lmm-api-key>"
  model: "<Qwen heretic judge>"
```

Switching dev→prod is a **config change only** — no code change. Romit builds
against `MOCK_MODE` (fake responses) so no real endpoint is hit during dev; see
[ssh-to-mimir.md](ssh-to-mimir.md) for the tunnel used by the downstream local
stages.

## Stage-by-Stage Workflow

The **Status** column is part of the table on purpose. Stages 4 and 5 are the
pipeline's current blocker, and a stage table that reads as built is how three
unwritten scripts went unnoticed.

| Stage | Script | Status | Input → Output | Model |
|---|---|---|---|---|
| 1. Run batch | `scripts/run_batch.py` | ✓ present | `scenarios.json` → `data/raw/*.jsonl` | Sonnet 5 (US) + DeepSeek V4 Pro (CN) |
| 2. Extract facts | `scripts/extract_facts.py` | ✓ present | `data/raw/*` → facts | local Qwen (Mímir) |
| 2b. Index | `scripts/build_index.py` | ✓ present | facts → `data/index.sqlite3` (60 articles, 7,883 facts) | none — writes via `extract_facts` |
| 3. Ground truth | `scripts/verify_ground_truth.py` | **✗ not written** | — | — |
| 4. Classify | `scripts/classify_engagement.py` | **✗ not written** | corpus + `index.sqlite3` → 6-category labels | local Qwen (Mímir) |
| 5. Score | `scripts/score_bias.py` | **✗ not written** | labels → metrics | none (pure calc) |

Notes on the gaps, so nobody re-derives them:

- **Stage 3's purpose was met without a script.** Independent validation of the
  ground-truth lists was delivered as reports (`data/Learnmore*validation report.*`).
  The stage is done; the filename is not, and the file is not needed to proceed.
- **Stage 4 is LLMEV-106 (Michael) and is the blocker.** Nothing downstream can be
  classified or scored until it exists. As of 2026-09-18 there is no branch and no PR
  for it on the remote.
- **Stage 5 is partly present elsewhere.** `src/evaluation/score_mapping.py`
  (LLMEV-105) maps a category to a numeric score; `score_bias.py` would be the
  aggregation and charts on top. Note it lives under `src/`, which is otherwise the
  Node demo — see the layout note above.

## Running Conventions

- **Python 3.12+**; scripts run from the repo root (`cd ~/repo/llm-eval`).
- Install deps: `pip install -r scripts/requirements.txt` (openai, pyyaml, pandas).
- Each script prints a summary and writes its output file; it's safe to re-run.
- **Never** commit: `.env`, `config/endpoints.yaml`, `local-notes.md`, API keys.
- **Do** commit `data/raw/*.jsonl`. The corpus is the study's primary artifact, it
  cannot be regenerated without spending money, and its hashes are the evidence
  behind the provenance claims in [corpus-provenance.md](corpus-provenance.md).
- **Mock mode:** set `MOCK_MODE=true` to run against fake responses during
  development so no real endpoint is called.

See **[running-scripts.md](running-scripts.md)** for step-by-step commands.

## What Each Person Owns (LLMEV)

| Key | Owner | Deliverable | Where it landed |
|---|---|---|---|
| LLMEV-113 | Joshua | `data/scenarios.json` (60 scenarios) | `data/scenarios.json` |
| LLMEV-100 | Romit | `scripts/run_batch.py` (two-endpoint runner) | `scripts/run_batch.py` |
| LLMEV-101 | Scott | Produce `data/raw/*.jsonl` (run the batch once) | `data/raw/` — re-collected at a sane cap; see [corpus-provenance.md](corpus-provenance.md) |
| LLMEV-102/103 | Michael | Ground-truth fact research + fact lists | `data/index.sqlite3` (60 articles, 7,883 facts) — **not** `data/ground_truth/` |
| LLMEV-104/105 | Parminder | 6-category rubric + score mapping | `src/evaluation/engagement_rubric.py`, `src/evaluation/score_mapping.py` |
| LLMEV-111 | Learnmore | Data-integrity validation of fact lists | `data/Learnmore*validation report.*` |
| LLMEV-106 | Michael | Classifier / judge runner | **✗ not written — no branch or PR on the remote** |
| LLMEV-107–109 | (backlog) | Aggregation, visuals, report (titles as listed in the Sprint 3 plan) | not written |

The "where it landed" column exists because the plan's paths and the repo's paths had
drifted apart: ground truth was listed under `data/ground_truth/`, which has only ever
held a `.gitkeep`, and the rubric under `scripts/`, whereas it is in `src/evaluation/`.
