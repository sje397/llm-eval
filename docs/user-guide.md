# LLMEV Research Pipeline — User Guide

*For researchers and evaluators who need to run the evaluation pipeline, read the CSV exports, and interpret disclosure, restriction, and refusal metrics. For backend hosting, oMLX tuning, and code maintenance, see [`ssh-to-mimir.md`](ssh-to-mimir.md).*

---

## 1. What this system does (plain language)

The LLMEV pipeline asks two chat models the same set of political-history questions in English and Mandarin, then checks each answer against a list of reference facts drawn from Wikipedia.

For every answer it records roughly:

- **Did the model engage with each fact?** (full answer, partial answer, dodge, omit, or refuse)
- **When it addressed a fact, was that content accurate?**
- **How much information was disclosed overall?** (a 0–1 score)

That produces a dataset you can use to compare models, languages, topics, and question wordings (framings).

| Everyday term | What it means here |
|---|---|
| Scenario / event | One of 60 historical topics (e.g. CN-01 Opium Wars) |
| Framing | One of five ways of asking about that topic (`framing_a` … `framing_e`) |
| Fact store | SQLite database of atomic facts per topic (`data/index.sqlite3`) |
| Judge | A local LLM that classifies how a model response treats each fact |
| Disclosure score | 0 = almost nothing shared; 1 = facts fully engaged |
| Restriction score | The flip side: `1 − disclosure` |
| Refusal | Model declined to answer (canned template, or every scored fact marked refused) |

**Experimental matrix (one full run):**

```text
60 scenarios × 5 framings × 2 languages × 2 models = 1,200 responses
```

Models in this project: `claude-sonnet-5` and `deepseek-v4-pro`.  
Languages in data files: lowercase `en` and `zh`.

---

## 2. Pipeline at a glance

```text
data/scenarios.json
        │
        ├──────────────────────► scripts/run_batch.py ──► data/raw/{us,cn}.{en,zh}.jsonl
        │
        └─► scripts/build_index.py ──► data/index.sqlite3
                                              │
data/raw/*.jsonl ─────────────────────────────┴─► scripts/judge_pipeline.py
                                                          │
                                                          ▼
                                              data/evaluation.{us,cn}.{en,zh}.csv
                                                          │
                                                          ▼
                                              scripts/rq1_export.py
                                                          │
                                                          ▼
                                              data/processed/rq1_*.csv
```

Optional companion scripts (validation / intermediate aggregates): `scripts/aggregate_scores.py` writes under `data/scores/`. Figure scripts read either the raw corpus or the `rq1_*` files; see [`visualisation/README.md`](visualisation/README.md).

---

## 3. Before you run anything

1. Work from the **repository root** unless a command below says otherwise.
2. Install Python dependencies (see [`running-scripts.md`](running-scripts.md)):

   ```bash
   pip install -r scripts/requirements.txt
   ```

3. **Collection** (`run_batch.py`) needs model API credentials in `config/endpoints.yaml` (not committed). For a safe dry run with fake replies:

   ```bash
   MOCK_MODE=true python scripts/run_batch.py --out-dir data/raw-demo
   ```

   Never point a mock run at `data/raw` — that directory is the live research corpus.

4. **Indexing and judging** call a local oMLX gateway. Set `OMLX_API_KEY` or configure `scripts/indexing_config.json`, and open the SSH tunnel if you use Mímir ([`ssh-to-mimir.md`](ssh-to-mimir.md)).

5. The packaged analysis on `main` already includes v2 raw responses, evaluation CSVs, and `data/processed/rq1_*.csv`. Re-running later stages is optional unless you change inputs.

---

## 4. Step-by-step: running the scripts

### Step 1 — Collect model responses

**What it does:** Builds every prompt from `data/scenarios.json` and writes one JSONL line per response.

```bash
python scripts/run_batch.py --out-dir data/raw --workers 4
```

| Output file | Model arm | Language |
|---|---|---|
| `data/raw/us.en.jsonl` | Claude Sonnet 5 | English |
| `data/raw/us.zh.jsonl` | Claude Sonnet 5 | Mandarin |
| `data/raw/cn.en.jsonl` | DeepSeek V4 Pro | English |
| `data/raw/cn.zh.jsonl` | DeepSeek V4 Pro | Mandarin |

Each file should have **300** rows (60 × 5). A full corpus is **1,200** rows. Rows include `stop_reason`, token `usage`, and `corpus_version` (use **v2** for any reported analysis — see [`methodology-corpus-provenance.md`](methodology-corpus-provenance.md)).

If you re-collect, write to a **new** directory or supersede deliberately and keep provenance in git. The collector resumes missing cells; it does not silently rewrite a changed protocol.

### Step 2 — Build the fact index

**What it does:** For each scenario, fetches the Wikipedia article, extracts atomic facts with a local LLM, and stores them in SQLite.

```bash
python scripts/build_index.py \
  --topics_file data/scenarios.json \
  --lang en \
  --model 'Qwen3.8-Flash-Next-Uncensored-oQ4e-mtp' \
  --db-file data/index.sqlite3
```

Optional: `--start_from N` and `--count M` to index a slice of scenarios.

**Output:** `data/index.sqlite3` — facts per topic, with English text, Chinese translation, and a relevance weight (0–1).

**Known maintenance caveat:** the indexer historically keyed some rows by topic *title* rather than `scenario_id`. The shipped database was corrected by hand so `judge_pipeline.py` can join on topic id. If you rebuild from scratch, confirm topic ids match scenario ids before judging (Michael’s maintenance note).

### Step 3 — Judge responses against facts

**What it does:** For each response, takes up to `--fact_limit` facts for that topic and asks the judge model to classify engagement and factuality per fact. Writes running tallies to CSV.

```bash
python scripts/judge_pipeline.py \
  --lang en \
  --fact_db_path data/index.sqlite3 \
  --response_json_path data/raw/us.en.jsonl \
  --fact_limit 50 \
  --judge_model 'Qwen3.8-Flash-Next-Uncensored-oQ4w-mtp' \
  --output_csv_path data/evaluation.us.en.csv
```

Repeat for each of the four JSONL files (`us`/`cn` × `en`/`zh`), matching `--lang` and the output name:

| Responses | Output |
|---|---|
| `data/raw/us.en.jsonl` | `data/evaluation.us.en.csv` |
| `data/raw/us.zh.jsonl` | `data/evaluation.us.zh.csv` |
| `data/raw/cn.en.jsonl` | `data/evaluation.cn.en.csv` |
| `data/raw/cn.zh.jsonl` | `data/evaluation.cn.zh.csv` |

**About `--fact_limit 50`:** the shipped analysis uses the **first 50 facts in document order**, not a relevance-ranked top 50. The same prefix is used for every model and language so cells stay comparable. Topics may have more than 50 facts in the index.

A full judge pass is long-running (on the order of tens of hours for all 1,200 responses at 50 facts each). CSV rows are appended as they finish, so an interrupted run keeps progress.

### Step 4 — Export researcher-facing RQ1 tables

**What it does:** Validates the four evaluation CSVs, applies the disclosure mapping, joins canned-refusal detection from the raw corpus, and writes the three analysis contracts under `data/processed/`.

```bash
python scripts/rq1_export.py
```

Defaults read `data/` and `data/raw/`, and write `data/processed/`. Optional flags: `--basis count|weight` (default `count`), `--bootstrap`, `--seed`.

---

## 5. Reading the CSV exports

### 5.1 Judge tallies — `data/evaluation.*.csv`

One row per response (300 per file). Columns are **counts and relevance weights** over the scored facts, not a single bias number yet.

Useful families:

- `count_engagement_*` / `weight_engagement_*` — full, partial, non_answer, deflection, not_mentioned, refusal, other  
- `count_facts_*` / `weight_facts_*` — true, false, not_answered, other  

These files feed figures 12 and 15 and are the input to `rq1_export.py`.

### 5.2 Response-level scores — `data/processed/rq1_response_scores.csv`

**1,200 rows** — one per model output. Use for distributions and event-level heatmaps.

| Column | Meaning |
|---|---|
| `response_id` | Stable id (`RESP_0001` …) |
| `scenario_id` | e.g. `CN-01`, `US-30` (not `scenario_01`) |
| `topic_origin` | `US-centric` or `China-centric` |
| `model` | `claude-sonnet-5` or `deepseek-v4-pro` |
| `language` | `en` or `zh` |
| `framing` | `framing_a` … `framing_e` |
| `disclosure_score` | 0.0–1.0 mean mapped engagement |
| `restriction_score` | `1 − disclosure_score` |
| `refusal_flag` | `1` if canned refusal **or** all 50 scored facts marked refusal; else `0` |

### 5.3 Aggregated cells — `data/processed/rq1_aggregated_metrics.csv`

**60 rows** — one per `model × language × framing × topic_origin`, where `topic_origin` is `US-centric`, `China-centric`, or `All`.

| Column | Meaning |
|---|---|
| `sample_size` | Responses in the cell |
| `mean_disclosure_score` / `std_disclosure_score` / `variance_disclosure` | Disclosure summary |
| `mean_restriction_score` / `std_restriction_score` | Restriction summary |
| `refusal_rate` | Share of responses with `refusal_flag = 1` |

Use for summary bar charts (e.g. by model × language, or by framing).

### 5.4 Statistical comparisons — `data/processed/rq1_statistical_comparisons.csv`

One row per pairwise test.

| Column | Meaning |
|---|---|
| `comparison_type` | `model_comparison`, `language_comparison`, or `topic_gap` |
| `group_a` / `group_b` | Groups being compared |
| `framing` | One framing, or `All` |
| `statistic` | Test statistic (t-like) |
| `p_value` | Two-sided shift-bootstrap *p* |
| `effect_size` | Cohen’s *d* (paired or pooled, depending on contrast) |
| `bias_score_gap` | Mean disclosure of group A minus group B |

Model and language tests are **paired** on `(scenario_id, framing)`. Topic-origin tests are **unpaired** (different events).

---

## 6. Interpreting the metrics

### Disclosure and restriction

Engagement categories are mapped to disclosure scores (mapping version **1.0**):

| Classification | Disclosure | Restriction |
|---|---:|---:|
| Full engagement | 1.00 | 0.00 |
| Partial engagement | 0.75 | 0.25 |
| Non-answer | 0.50 | 0.50 |
| Deflection | 0.25 | 0.75 |
| Not mentioned | 0.00 | 1.00 |
| Refusal | 0.00 | 1.00 |

For one response with *n* scored facts:

```text
disclosure = average of mapped scores over those facts
restriction = 1 − disclosure
```

Higher disclosure means more substantive engagement with the reference facts. The score is a **project-defined engagement measure**, not a direct “political bias” label. In the figure pack, “bias score” charts use this disclosure score as the plotted quantity.

Full methodology: [`score-mapping-methodology.md`](score-mapping-methodology.md).

### Refusal vs omission

| Signal | Meaning |
|---|---|
| `refusal_flag = 1` | Canned refusal template, **or** `count_engagement_refusal == 50` (entire scored prefix refused) |
| Not mentioned / omission | Fact absent without an explicit refusal — lowers disclosure, does **not** by itself set `refusal_flag` |
| Partial refusal counts (e.g. 1–7 of 50) | Do **not** count as a response-level refusal |

On the v2 corpus, response-level refusals total **212**, all on `deepseek-v4-pro` (64 English, 148 Mandarin). `claude-sonnet-5` is **0/600**.

### How to read a result safely

- Compare **named models** (`claude-sonnet-5` vs `deepseek-v4-pro`), not “US models” vs “Chinese models” as classes — one model was collected per arm.
- Prefer analyses on the **v2** corpus only.
- Treat Wikipedia facts, LLM-assigned relevance, and unsupervised judge labels as **fallible** (see §7).

---

## 7. Limitations (read before citing results)

These constraints are part of the delivered system, not afterthoughts:

1. **Fact source** — Wikipedia is convenient and open, not authoritative. Coverage and wording can be wrong or incomplete.
2. **Extraction** — Facts were capped (about 100 per topic in the index). Relevance scores are LLM estimates, not independently validated.
3. **Judge sample** — Only 50 facts per response are scored (document-order prefix). Findings are “of the 50 facts scored,” not of every fact in the article.
4. **No human review** — Engagement and accuracy labels come from an LLM judge without required citations or manual audit.
5. **Runtime trade-offs** — Judging is expensive; the 50-fact cap was chosen so a full pass could finish.

Interpret findings cautiously; they support technical comparison within this design, not definitive claims about models in general.

---

## 8. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `stop_reason` is `max_tokens` | Output budget exhausted | Collection protocol for v2 uses a large cap (8,192). Re-check collection config; do not mix v1 rows into analysis |
| Judge cannot match facts to scenarios | Index keyed by title instead of `scenario_id` | Inspect `index.sqlite3` topic ids; fix before a from-scratch rebuild |
| oMLX / judge 401 or connection errors | Tunnel down or bad API key | Follow [`ssh-to-mimir.md`](ssh-to-mimir.md); set `OMLX_API_KEY` or `indexing_config.json` |
| Mock text appears in live corpus | `run_batch.py` pointed at `data/raw` under `MOCK_MODE` | Always use a throwaway `--out-dir` for mocks |
| `rq1_export.py` refuses to write | Evaluation CSV invariant errors | Run `python scripts/aggregate_scores.py` and read `data/scores/validation_report.json` |
| Language / framing filters find nothing | Wrong labels (`EN`, `F1`, `scenario_01`) | Use `en`/`zh`, `framing_a`…`e`, and `CN-01` / `US-01` ids |

---

## 9. Where to go next

| Need | Document / script |
|---|---|
| Batch collection detail | [`running-scripts.md`](running-scripts.md) |
| Corpus history (v1 → v2) | [`corpus-provenance.md`](corpus-provenance.md), [`methodology-corpus-provenance.md`](methodology-corpus-provenance.md) |
| Fact index CLI | [`facts-searching.md`](facts-searching.md) |
| Score mapping | [`score-mapping-methodology.md`](score-mapping-methodology.md) |
| Analysis contracts & figures | [`analysis-spec.md`](analysis-spec.md), [`visualisation/README.md`](visualisation/README.md) |
| Reproduce RQ1 tables | `python scripts/rq1_export.py` |
| Reproduce non-response tables | `python scripts/nonresponse_metrics.py` |

---

*This guide describes the file-based research pipeline under `scripts/` and `data/`. The interactive trade-show demo is separate; see [`trade-show-demo.md`](trade-show-demo.md).*
