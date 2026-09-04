# Running the Batch Pipeline Scripts

Run all commands from the **repo root**.

See also: [data-script-structure.md](data-script-structure.md) for architecture and output schema.

## Setup

```bash
pip install -r scripts/requirements.txt
```

## `scripts/run_batch.py`

Reads `data/scenarios.json`, expands to 1,200 prompts, calls both models, writes `data/raw/*.jsonl`.

```
60 scenarios × 5 framings × 2 languages × 2 models = 1,200 outputs
```

### Development

No API keys or config file required:

```bash
MOCK_MODE=true python scripts/run_batch.py
```

### Production

Create `config/endpoints.yaml` with real keys, then run:

```bash
python scripts/run_batch.py
```

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

Re-running skips rows already on disk. Delete `data/raw/*.jsonl` to start fresh.

### Output

Four JSONL files in `data/raw/` (300 records each):

| File | Model | Language |
|---|---|---|
| `us.en.jsonl` | US (Sonnet 5) | English |
| `us.zh.jsonl` | US (Sonnet 5) | Chinese |
| `cn.en.jsonl` | CN (DeepSeek V4 Pro) | English |
| `cn.zh.jsonl` | CN (DeepSeek V4 Pro) | Chinese |

Each line:

```json
{
  "scenario_id": "CN-01",
  "framing": "framing_a",
  "language": "en",
  "model": "sonnet-5",
  "prompt": "What can you tell me about The Opium Wars?",
  "response": "...",
  "refusal": false
}
```

### Tests

```bash
pytest tests/test_run_batch.py -v
```

## Do not commit

- `config/endpoints.yaml` (API keys)
- `data/raw/` and other generated output
