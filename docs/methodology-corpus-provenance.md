# Corpus provenance — the v1 → v2 correction (methodology note)

*Report-ready text for the Methodology section. The full record — per-file hashes,
the replacement record, and the defects restated — is in
[`corpus-provenance.md`](corpus-provenance.md) (PR #21).*

## Summary

The 1,200-response evaluation corpus was re-collected once, on 2026-09-17, and the
corrected collection replaced the original in place on 2026-09-18. Every result reported here is
computed on the corrected corpus. The original is preserved in git at commit
`68ad171` and is no longer read by any stage of the pipeline.

The correction was not cosmetic. The first collection ran with a 1,024-token output
cap, which cost the Chinese arm 84 of its 600 rows outright and — more importantly —
made every *other* truncation invisible.

## What the 1,024-token cap did

Both response models spend part of the output budget on reasoning before emitting an
answer. When the reasoning consumed the whole allowance, the API returned a reasoning
block with no text block, and the collection script stored the reply as an empty
string. Measured on the original corpus: **84 of 1,200 rows (7.0%) were empty, and all
84 belong to the CN model** (`deepseek-v4-pro`) — 67 of the 600 `cn.en` rows and 17 of
the 600 `cn.zh` rows. Neither US-model file (`claude-sonnet-5`) contained an empty
response.

These rows are an artefact of the cap, not a model behaviour and not a refusal.
Re-running the corpus's own prompts at the original settings (2026-09-17) found
**23% of DeepSeek calls and 2–3% of Claude calls ending at the cap**. The 84 rows are
therefore the *visible* part of the damage rather than its extent: a reply cut off
mid-sentence is indistinguishable from a complete one when nothing records why the
model stopped, and the original rows recorded neither `stop_reason` nor `usage`.

Two further defects were invisible in the data itself:

- The `refusal` field was written as `len(response) < 20`. It flagged exactly the 84
  empty rows and nothing else — 100% false positives — while the **216 rows carrying
  the CN model's canned refusal template** (159 `cn.zh`, 57 `cn.en`) were flagged zero
  times.
- No field identified the protocol that produced a row, so two collections could not be
  told apart from the files themselves.

## How it was fixed

| Change | From → to |
|---|---|
| output cap | 1,024 → 8,192 tokens |
| request timeout | 120 s → 600 s |
| per-row record | `{text}` → `{text, stop_reason, usage}` |
| text assembly | first text block only → all text blocks joined |
| unrecognised `stop_reason` | stored as normal → raises |
| truncation signal | inverted `refusal` boolean → `stop_reason`, recorded per row |

The collection script now stamps every row with the protocol that produced it: the cap
in force, `stop_reason`, token usage, the model identifier, the run date, and the git
SHA of the collection code.

## Final state of v2

- 1,200 rows, 300 per file — the same 60 scenarios × 5 framings × 2 languages × 2 models
- **0 empty responses; 0 rows ending at the cap**
- `stop_reason = end_turn` for all 1,200 rows
- the inverted `refusal` field is absent by construction

v2 is a **fresh collection, not a repair**: 1,023 of the 1,200 response texts differ from
v1. All 177 byte-identical rows are deterministic refusal templates (128 `cn.zh`, 49
`cn.en`) — refusals recur across collections, stochastic answers do not. That is worth
stating as a result in its own right: the corpus holds one draw per cell, so per-cell
labels are conditional on that draw, and the stable part of the corpus is the models'
refusal behaviour rather than their answers.

## Consequences for the analysis

1. Every disclosure, restriction, and factuality metric reported here is computed on v2.
2. Because the v1 damage was concentrated entirely in one arm, a v1-based comparison
   would have penalised the CN model for reasons unrelated to its behaviour.
3. The rubric rule treating an empty response as an explicit refusal is inert on v2
   (there are no empty rows), and would have been wrong on 83 of the 84 v1 rows: on
   re-collection with a larger cap, those 83 returned substantive answers and the
   remaining one returned a genuine refusal.

## Where the record lives

- Full provenance, per-file sha256, and the replacement record: `docs/corpus-provenance.md`
- Original corpus bytes: `git show 68ad171:data/raw/{cn,us}.{en,zh}.jsonl`
- Code and protocol changes: PR #20 (`stop_reason` capture) and PR #21 (corrected corpus)
