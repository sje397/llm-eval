# Trade Show Demo Website

## Purpose

The demo website at [llm-eval.lxg2it.com](https://llm-eval.lxg2it.com) is the interactive component of the IDP_OL_LLMEval_G6 booth at the virtual trade show. It demonstrates the LLM bias evaluation pipeline to visitors in real time — they enter a politically sensitive scenario, watch it flow through the pipeline, and see bias indicators across four model-language combinations.

## Relationship to the final deliverable

This website was the trade-show prototype. It is **not** the project's final deliverable, and the two share no code.

| | Trade-show demo (this document) | Final deliverable |
|---|---|---|
| **Language and shape** | TypeScript, Node/Express, WebSocket, served in a browser | Python scripts, file in and file out, run locally |
| **Audience** | A booth visitor who types a scenario and watches it run | A researcher who wants to run the pipeline and inspect the data |
| **Where the code lives** | `src/` and `src/web/` | `scripts/`, `config/`, `data/` |
| **Delivered as** | D6, trade-show presentation, one of three components alongside the pre-recorded videos and the booth material | D1, working evaluation pipeline |

What the two share is the pipeline **design**: the same stage decomposition (translation, four model slots, refusal detection, fact extraction, verification, scoring), the verification approach developed through V0 to V5, and the same four model-and-language slots. The final pipeline reimplements that design in Python, because that deliverable is meant to be run and modified locally by a researcher rather than served to a visitor. There is no website in the final deliverable.

This distinction was not always recorded here. An earlier version of this document described the `src/pipeline/` modules as "shared with real evaluation" and as modules that "will also be used by the batch evaluation runner". That was the intention when the demo was written, and it did not happen: the batch runner was built as Python scripts and no code is shared between the two.

## User Flow

```
Landing Page
  │
  ├─ Project description (what we're doing, why it matters)
  ├─ Scenario input form
  │   ├─ English text area
  │   └─ Chinese translation (auto-generated, editable)
  │
  └─ [Run Evaluation]
       │
       ▼
  Pipeline Visualization Page
  │
  ├─ Real-time flowchart (left panel)
  │   ├─ Translation
  │   ├─ US Model (English)
  │   ├─ US Model (Chinese)
  │   ├─ CN Model (English)
  │   ├─ CN Model (Chinese)
  │   ├─ Detect Refusals
  │   ├─ Extract Facts
  │   ├─ Verify Facts
  │   └─ Score Bias
  │
  ├─ Results panel (right panel)
  │   └─ Per-slot: refusal status, fact count, accuracy, bias indicators
  │
  └─ Bias Summary Grid (bottom)
      └─ 4 cards showing overall bias scores per slot
```

## Technical Architecture

```
Browser (WebSocket) ←→ Express Server (port 3007) ←→ oMLX (Mímir:21434)
                              │
                              ├─ Pipeline orchestrator
                              ├─ Modular pipeline components
                              └─ Static file serving (HTML/CSS/JS)
```

- **Frontend:** Vanilla HTML/CSS/JS — no framework. Keeps it lightweight, fast to load, and easy for other team members to understand.
- **Real-time updates:** WebSocket (ws library). The server emits progress events as each pipeline step completes. The frontend updates the flowchart in real time without polling.
- **Server:** Node.js/Express, TypeScript. Docker container on the AU EC2 server (13.54.219.192).
- **Model backend:** oMLX on Mímir (Mac Studio M4 Max). OpenAI-compatible API at `/v1/chat/completions`.
- **SSL:** Let's Encrypt via nginx reverse proxy on the AU server.

## Pipeline Steps (as shown in flowchart)

| Step | Description | What the visitor sees |
|------|-------------|----------------------|
| Translation | English scenario translated to Chinese | "Translating scenario..." |
| US Model (EN) | US-origin model queried with English prompt | "Querying us-model-en..." |
| US Model (ZH) | US-origin model queried with Chinese prompt | "Querying us-model-zh..." |
| CN Model (EN) | Chinese-origin model queried with English prompt | "Querying cn-model-en..." |
| CN Model (ZH) | Chinese-origin model queried with Chinese prompt | "Querying cn-model-zh..." |
| Detect Refusals | Each response checked for refusal patterns | "Detecting refusals..." |
| Extract Facts | Non-refusal responses decomposed into atomic claims | "Extracted N facts" |
| Verify Facts | Each fact checked for accuracy | "Verifying facts..." |
| Score Bias | Bias indicators computed per slot | "Bias scoring complete" |

## Models Used

Read back from the recorded runs in `demo/data/j*.json`, which store the resolved model names per job:

| Slot | Model | Language | Purpose |
|------|-------|----------|---------|
| `us-model-en` | `gemma-4-31B-it-oQ4e` | English | US-origin LLM responding in English |
| `us-model-zh` | `gemma-4-31B-it-oQ4e` | Chinese | US-origin LLM responding in Chinese |
| `cn-model-en` | `Qwen3.6-27B-oQ4e-mtp` | English | Chinese-origin LLM responding in English |
| `cn-model-zh` | `Qwen3.6-27B-oQ4e-mtp` | Chinese | Chinese-origin LLM responding in Chinese |
| `judge` | `Qwen3.6-35B-A3B-uncensored-heretic-oQ8-fp16-mtp` | — | Verifies extracted facts against Wikipedia |

**Note:** all four slots ran locally through oMLX on Mímir, as did the judge, which is why the demo needed no API keys and cost nothing per call. These are the demo's models, chosen because they run on one machine: they are **not** the models under test in the study, which are the hosted Claude Sonnet 5 (US arm) and DeepSeek V4 Pro (CN arm).

An earlier version of this table recorded the US slots as "TBD (currently Qwen placeholder)" and both CN slots as "Qwen 3.6 35B A3B". The first was true on 28 July 2026, when this document was written, and untrue of every recorded run. The second named the judge's model rather than the Chinese arm's.

## Bias Indicators Displayed

After pipeline completion, each model slot shows:

1. **Refusal status** — green "RESPONSE" badge or red "REFUSAL" badge with reason
2. **Fact count** — number of extractable factual claims
3. **Accuracy** — X/N facts verified, with badge: ACCURATE (≥80%), PARTIAL (50-80%), INACCURATE (<50%)
4. **Bias indicators** — per-dimension severity ratings:
   - `refusal` — was the model evasive?
   - `accuracy` — how factually correct?
   - `substance` — did it say anything verifiable at all?
5. **Overall bias score** — 0-100% across all indicators

## Development

### Local development with mock mode:
```bash
cd ~/repo/llm-eval
MOCK_MODE=true npm run dev
# Visit http://localhost:3007
```

Mock mode returns hardcoded responses per slot — useful for UI development without running models.

### With real models (requires oMLX):
```bash
cd ~/repo/llm-eval
OMLX_URL=http://mimir.local:21434 npm run dev
```

## Deployment

```bash
# On AU server:
cd ~/repo/llm-eval
git pull
docker compose build
docker compose up -d
```

## Design Decisions

1. **Pipeline design reused, code not shared** — the demo was not throwaway: it is where the pipeline's stages and the verification approach were worked out, and the final deliverable uses the same design. The code itself was not carried over. The batch evaluation runner is written in Python, because by then the audience had changed: a researcher running scripts and inspecting data files locally, not a visitor watching a browser. See "Relationship to the final deliverable" above.

2. **Vanilla frontend** — no React/Vue/Svelte. The team has junior programmers. Vanilla JS is the most accessible. It also means zero build step for the frontend.

3. **WebSocket over polling** — visitors at a trade show booth want to see things happen. Polling feels sluggish. WebSocket gives instant visual feedback as each step completes.

4. **Dark theme** — professional look, easy on the eyes, looks good on a trade show monitor. The gradient accent (indigo → purple) gives it a research-tool identity distinct from a generic website.

5. **Auto-translation** — the demo translates English input to Chinese automatically. This shows visitors that cross-lingual evaluation is a core feature, not an afterthought. Visitors don't need to know Chinese to see the pipeline work.
