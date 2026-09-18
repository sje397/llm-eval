# Running the Batch Pipeline Scripts

Run all commands from the **repo root**.

See also: [data-script-structure.md](data-script-structure.md) for architecture, and
[corpus-provenance.md](corpus-provenance.md) for what is in `data/raw/` and why.

## Setup

```bash
pip install -r scripts/requirements.txt
```

## `scripts/run_batch.py`

Reads `data/scenarios.json`, expands to 1,200 prompts, calls both models, writes the
corpus.

```
60 scenarios × 5 framings × 2 languages × 2 models = 1,200 outputs
```

### Development

No API keys or config file required:

```bash
MOCK_MODE=true python scripts/run_batch.py --out-dir data/raw-demo
```

**Always pass `--out-dir`, including in mock mode.** The default is `data/raw`, which
is the live corpus the analysis reads, and the collector resumes rather than
overwrites — so a mock run into the default would silently fill any missing
`(scenario_id, framing)` slot with fake text. Mock rows are self-identifying
(`[MOCK <model>] ...`), but the cheapest guard is not to point the command at the
corpus in the first place.

### Production

Create `config/endpoints.yaml` with real keys, then run:

```bash
.venv-llm/bin/python scripts/run_batch.py --out-dir <new-dir> --workers 4
```

A re-collection is a **different protocol**, and it must never be merged into an
existing corpus silently. Two ways satisfy that, and both have been used here:
collect into a new directory and keep both, or **supersede in place and let git hold
the old corpus** — which is what was done for v2, with v1 preserved at the commit
recorded in [corpus-provenance.md](corpus-provenance.md) together with its four
hashes. What is not acceptable is overwriting rows in place with no record that the
protocol changed. Re-running into the same directory skips rows already on disk, so an
interrupted collection resumes where it stopped.

Example `config/endpoints.yaml`:

```yaml
us:
  base_url: "https://api.anthropic.com/v1/messages"
  api_key: "<anthropic-api-key>"
  model: "sonnet-5"
cn:
  base_url: "https://api.deepseek.com/anthropic/v1/messages"
  api_key: "<deepseek-api-key>"
  model: "deepseek-v4-pro"
```

### Output

Four JSONL files in the target directory (300 records each):

| File | Model | Language |
|---|---|---|
| `us.en.jsonl` | US (Sonnet 5) | English |
| `us.zh.jsonl` | US (Sonnet 5) | Chinese |
| `cn.en.jsonl` | CN (DeepSeek V4 Pro) | English |
| `cn.zh.jsonl` | CN (DeepSeek V4 Pro) | Chinese |

Each line, as written by the current collector:

```json
{
  "scenario_id": "CN-01",
  "framing": "framing_a",
  "language": "en",
  "model": "sonnet-5",
  "prompt": "What can you tell me about ...?",
  "response": "...",
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 412, "output_tokens": 388},
  "response_model": "claude-sonnet-5",
  "run_date_utc": "2026-09-17T02:11:58+00:00",
  "git_sha": "7c31dc1",
  "corpus_version": "v2"
}
```

The run also writes `_protocol.json` beside the rows: the cap, worker count, model IDs
and base URLs (never credentials), a sha256 of the prompt source, per-file row and
empty counts, the `stop_reason` distribution, and the previous corpus's hashes and
defects.

The corpus in `data/raw/` was collected with this schema. An earlier corpus carried
an extra `refusal` field written as a length heuristic; it was inverted, read by
nothing, and is absent by construction here — see corpus-provenance.md.

### Tests

```bash
pytest tests/test_run_batch.py -v
```

## Do not commit

- `config/endpoints.yaml` (API keys)
- `.env`, `local-notes.md`

The corpus is the exception: **do** commit `data/raw/*.jsonl`. It is the study's
primary artifact, it cannot be regenerated without spending money, and its hashes are
the evidence behind the provenance claims in corpus-provenance.md.
