# Wikipedia Semantic Search Service

Local Wikipedia fact-check evidence service for the llm-eval bias evaluator.
Replaces direct calls to the rate-limited public Wikimedia API with fast
semantic search over article intros + full-text retrieval from a local dump.

This folder is the **source of truth** for the service. It runs on **Mímir**
(port 21500), reachable by the AU server / the team via the tunnels described
in [`docs/ssh-to-mimir.md`](../docs/ssh-to-mimir.md). The live deployment is
under `/Users/sje/wikipedia/` on Mímir (its own git repo, no remote) — the two
are kept in lockstep; this repo copy is what the team reads and works from.

## Architecture

```
AU server (llm-eval)                       Mímir (Mac Studio)
┌──────────────────────┐    autossh -R    ┌──────────────────────────┐
│ fact-verifier.ts     │◄── 21500:21500 ──┤ FastAPI service :21500   │
│  local service first │                  │  ├─ /search  (semantic)  │
│  Wikimedia fallback  │                  │  ├─ /extract (full text) │
└──────────────────────┘                  │  └─ /article/{lang}/{t}  │
                                          │  embedding: oMLX :21434  │
                                          │  per-lang bge-small      │
                                          └──────────────────────────┘
```

## Components

| File | Purpose |
|---|---|
| `parser.py`  | Streaming bz2 XML → SQLite (`parsed/{en,zh}.sqlite`): articles(title, intro, zlib full_text, len), redirects |
| `indexer.py` | SQLite → LanceDB (`index/`): per-language bge-small intros, IVF_PQ cosine index |
| `service.py` | FastAPI: search/extract/article endpoints, query embedding via oMLX |
| `cleaner.py` | Wikitext → plain text (templates, refs, links, tables, nesting) |

> **Embedding model — why it says bge-small and not bge-m3:** the live code
> (both `indexer.py` and `service.py`) uses **`bge-small-en-v1.5-bf16`** /
> **`bge-small-zh-v1.5-mlx`** per language. These are BERT-class models (33M /
> 24M params) that are ~17× faster than `bge-m3` (570M) on MPS and plenty for
> fact-check retrieval. The old README and some docstrings still say `bge-m3`
> — that's stale. **Index and query MUST use the same per-language model**, so
> if you change one you change both, or vectors land in different spaces.

## Build pipeline

```bash
# 1. Parse (streaming, ~20 min per language)
~/venv/wikipedia/bin/python3 parser.py --dump dumps/enwiki-latest-pages-articles.xml.bz2 --out parsed/en.sqlite --lang en
~/venv/wikipedia/bin/python3 parser.py --dump dumps/zhwiki-latest-pages-articles.xml.bz2 --out parsed/zh.sqlite --lang zh

# 2. Index (~3-5 min per language at ~40k docs/s)
~/venv/wikipedia/bin/python3 indexer.py --sqlite parsed/en.sqlite --index index --lang en
~/venv/wikipedia/bin/python3 indexer.py --sqlite parsed/zh.sqlite --index index --lang zh

# 3. Restart service (picks up new index)
launchctl kickstart -k gui/$(id -u)/com.lex.wikipedia-service
```

Or in one shot (Mímir only; assumes dumps are in `dumps/`):

```bash
./run-pipeline.sh            # both languages
./run-pipeline.sh --en-only  # just English
```

The `run-pipeline.sh` restart step therefore only works on Mímir — that's the
deployment host. Data (`index/`, `parsed/`, `dumps/`) is gitignored and never
committed.

## Config

Config is **env-overridable** with sensible Mímir defaults baked in:

| Env var | Default | Meaning |
|---|---|---|
| `OMLX_URL` | `http://localhost:21434` | oMLX gateway (`.env` defines it; `/v1/embeddings` is appended) |
| `OMLX_KEY` | `lmm-api-key` | oMLX API key |
| `WIKI_PARSED_DIR` | `~/wikipedia/parsed` | Parser SQLite dir |
| `WIKI_INDEX_DIR` | `~/wikipedia/index` | LanceDB index dir |
| `WIKI_BATCH_SIZE` / `WIKI_MAX_TOKENS` / `WIKI_IVF_PARTITIONS` | `512` / `128` / `256` | indexer tunables |

`EMBED_MODELS` per language are hardcoded in `service.py`/`indexer.py` (they
must match between the two). Titles are normalized (`_`→space) and zh is
converted Simplified→Traditional at the boundary.

## LaunchD agents (Mímir)

- `com.lex.wikipedia-service` — uvicorn on 127.0.0.1:21500 (KeepAlive)
- `com.lex.wikipedia-tunnel` — autossh -R 21500:localhost:21500 → AU server
  (13.54.219.192), mirroring the oMLX 21434 tunnel

Logs: `/tmp/wikipedia-service.{log,err}`, `/tmp/wikipedia-tunnel.{log,err}`

## API

```
POST /search  {"query": "...", "lang": "en|zh", "mode": "text|title",
               "top_k": 5, "constrain": ["taiwan"]}
              -> {"results": [{"title", "score", "intro", "exact"?}]}
              constrain = titles must contain ≥1 keyword (intitle: replication)
              score is a cosine DISTANCE (lower = more similar);
              an exact title/redirect match returns score 0.0 + exact:true.

POST /extract {"titles": [...], "lang": "en|zh", "max_chars": 12000}
              -> {"articles": [{"title", "intro", "extract", "paragraphs"}]}
              Titles are normalized (underscore -> space).

GET  /article/{lang}/{title}   -> {"title", "intro", "extract"} (redirects resolved)
GET  /health, /stats
```

## llm-eval integration

`fact-verifier.ts` calls the local service first (`WIKI_SERVICE_URL`, default
`http://localhost:21500`) and falls back to the Wikimedia API when the service
is unreachable. Paragraph scoring, entity boosts, and intitle constraints are
preserved. The `intitle:` prefix in queries is parsed into the `constrain`
field.

## Search behavior — and the "Great Leap Forward" fix

There are **two important behaviors** to know before you "muck around":

1. **Exact title/redirect match always wins (added).** `/search` now attempts
   an exact title + redirect lookup **before** semantic search, in *both* `text`
   and `title` mode, and prepends it (`score: 0.0`, `exact: true`). This is
   what makes `The Great Leap Forward` resolve to the `Great Leap Forward`
   article. The `mode` field is kept for backward-compat; `title` just emphasises
   the exact path, `text` uses it as a precision fallback before ANN.

2. **Semantic recall is weak for short entity phrases — that's by design, not
   a bug.** The ANN index embeds article *intros* (up to 128 tokens) with a
   small bge-small model. It works well for rich, descriptive phrases
   (`Taiwan presidential election 2024` → correct article at distance ~0.36),
   but a bare 4-word entity like `Great Leap Forward` genuinely does not
   surface the article in the semantic top-K — the exact-match path is what
   rescues it. If you're testing a new query and get unexpected results, first
   check whether it's an exact title/redirect; if so, the exact-match path wins.
   If you need better semantic recall for short phrases, raise `WIKI_MAX_TOKENS`
   (costs index time) or add a title-hybrid candidate set.

3. **Titles come in two spellings (fixed).** Wikimedia URLs/APIs encode spaces
   as underscores (`Great_Leap_Forward`); the DB stores spaces
   (`Great Leap Forward`). `/extract` and `/article` now normalize `_`→space so
   both spellings resolve. Before the fix, `Great_Leap_Forward` returned empty —
   the most likely cause of "isn't returning the data we want."

## Notes

- Query embedding goes through oMLX `/v1/embeddings` (per-language bge-small),
  the same model `indexer.py` used offline, so runtime and index vectors share
  a space. The runtime path shares model/memory with the rest of the system.
- Offline indexing loads bge-small directly via mlx-embeddings (~40k docs/s).
- Full text is stored as zlib-compressed wikitext and cleaned on demand; intro
  text is cleaned at parse time for the vector index.
- Known limitation: articles created after the dump snapshot aren't in the
  local index — the Wikimedia fallback covers service-down, not missing
  articles. Rare in practice (dumps are weekly).
