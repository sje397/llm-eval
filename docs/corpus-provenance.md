# Corpus provenance

How each version of the response corpus was produced, what is frozen, and what is
known to be wrong with it. Written because the v1 corpus has three defects that are
invisible in the data itself, and because a reader of a results table cannot tell
which collection protocol produced the rows behind it.

**Rule: a flawed collection is never silently repaired.** When a collection turns
out to be flawed, the response is to collect a fresh corpus and record the
supersession — hashes, defects, and the commit that still holds the original —
rather than to edit the bytes in place and say nothing. The original is the only
surviving evidence that the flaw existed.

`data/raw/` holds **one** corpus: the current one. Superseded versions are not kept
beside it as second directories; git holds them and this document names where, so
that "byte-identical" stays a checkable claim rather than an assurance.

| | v1 | v2 (current) |
|---|---|---|
| directory | `data/raw/` | `data/raw/` — replaced v1 in place, 2026-09-18 |
| bytes retrievable at | `68ad171` (2026-09-07) | current `HEAD` |
| `max_tokens` | 1024 | 8192 |
| rows | 1,200 (300 per file) | 1,200 (300 per file) |
| `stop_reason` | absent | recorded per row |
| `usage` | absent | recorded per row |
| `refusal` | present, inverted | absent by construction |
| defects | 3, below | — |

Files are one per model arm and language: `{us,cn}.{en,zh}.jsonl`, where `us` is
`claude-sonnet-5` and `cn` is `deepseek-v4-pro`.


## Replacement record

|  |  |
|---|---|
| replaced | 2026-09-18 |
| what | v1's four files replaced by v2's four files, same names, inside `data/raw/` |
| verified | all four sha256 match the collected v2 corpus byte for byte |
| v1 retrievable at | `68ad171` — e.g. `git show 68ad171:data/raw/cn.zh.jsonl` |
| v1 defects | three, below, and restated in `data/raw/_protocol.json` |

Keeping one corpus in the tree is a deliberate choice, not an accident of tidiness:
two directories meant the pipeline documentation named one while the analysis read
the other. The trade is that v1's survival now depends on git rather than on the
working tree, which is why its hashes and its retrieval commit are recorded here.

## v1 — superseded, held by git at `68ad171`

Collected at `max_tokens=1024` and committed in `68ad171`, which is where these bytes
still live. The collection date itself is **not recorded anywhere in the corpus**,
which is one of the reasons v2 stamps provenance onto every row.

Hashes (sha256, so a re-collection can prove it did not touch these):

```
88841ea6b0a1852bc232340e7e32f9a4a7f6f09fac0ea5d9ce09d8f9c090a5bb  cn.en.jsonl
4ccf9587bd3a5d2bc06e56044b03abdc04d48438d7a78bce5988fca8b49d724c  cn.zh.jsonl
e91d4cd35a1c4a0e5f22c87197208de68790deb6d3bc25431c6062cdbf7565ca  us.en.jsonl
09ffb472b04489e75dfd2c2d3f80e8cba50a8a5768fcd3ad89408016e167aba3  us.zh.jsonl
```

### Defect 1 — 84 empty replies, all truncation artefacts

67 rows in `cn.en.jsonl` and 17 in `cn.zh.jsonl` have an empty `response`; the two
`us.*` files have none. All 84 are `deepseek-v4-pro`.

They are an artefact of the output budget rather than a model behaviour: when the
model spends its whole output allowance before emitting a text block, the reply
carries no text at all and `ask_model` stored `""`. Raising the cap recovers text —
**all 84** produced a substantive reply when re-collected for v2 (mean 3,392
characters), and an earlier probe recovered 10/10 at `max_tokens=16384`.

They are not refusals, and the distinction is measurable: exactly **one** of the 84
is the DeepSeek refusal template in v2, and the other 83 are answers. That matters
beyond the corpus. The rubric's proposal for empty replies scores them as REFUSAL,
which on this evidence would have been wrong on 83 of 84 rows.

**Be precise about what v1 proves here.** v1 does not record `stop_reason`, so the
truncation cannot be *read off* the data — it is inferred from the fact that raising
the cap restores the reply. The mechanism is consistent with everything measured;
it is not directly attested by these rows. Recording `stop_reason` is what turns
this from an inference into an observation, which is the substantive reason for v2.

### Defect 2 — the `refusal` field is inverted, and unused

v1 wrote `refusal` as `len(text.strip()) < 20`. Measured against the stored bytes:

| | |
|---|---|
| rows with `refusal == True` | 84 |
| of those, empty | **84** |
| of those, non-empty (true positives) | **0** |
| rows carrying the actual refusal template | 159 |
| of those, flagged `refusal == True` | **0** |
| shortest non-empty reply in the corpus | **38 characters** |

The 38-character floor is the refusal template itself
(`对不起，我还没有学会回答这个问题。如果你有其他问题，我非常乐意为你提供帮助。`),
which appears on 159 rows in `cn.zh.jsonl` — none flagged. So the threshold cannot
produce a true positive on any row in the corpus: it is False for every reply that
is actually long enough to exist, and True only for replies that are empty.

The field is therefore inverted on both counts, and nothing read it:
`src/evaluation/score_mapping.py` derives its `refusal_flag` from the judge's
category, and `engagement_rubric.py` classifies refusals from the reply text.
It is retained in v1 because deleting it would erase the evidence that the
threshold was ever applied, and omitted from v2 by construction.

No length threshold can identify a refusal. `stop_reason` supersedes it as the
truncation signal; refusal is a semantic judgement made from the reply text.

### Defect 3 — no `stop_reason`, so truncation was undetectable

All 1,200 v1 rows lack `stop_reason` and `usage`. The only available signal that a
reply had been cut off was that it was empty, which is exactly the signal Defect 2
mislabels. A partially truncated reply — one that emitted some text and then hit
the cap — is indistinguishable in v1 from a complete one, and there are many of
them.

**The 84 empty rows are the visible minority of the damage.** Two independent
measurements of the same corpus:

| measurement | rows |
|---|---|
| empty in v1 (visible) | 84 (7.0% of 1,200) |
| v2 reply exceeds the old 1024-token cap | 209 (17.4%) |
| v1 reply ends without terminal punctuation | 119 |

The second and third are different estimates of the same underlying quantity and
they **agree on only 52 rows**. That disagreement is the point: neither a re-run
nor a punctuation heuristic is an adequate detector. A reply that ends mid-sentence
is a plausible truncation but not a certain one, and a reply cut off at a sentence
boundary leaves no textual trace at all. Had v1 recorded `stop_reason`, all of this
would be a query rather than an inference.

All of the visible damage is in the `cn` arm (84 of 600 rows, 14%); the `us` arm has
none. Counting silent truncations as well, roughly 177 of 600 `cn` rows (29.5%) and
32 of 600 `us` rows (5.3%) were affected by the 1024-token cap. This is consistent
with the live probe recorded on #20, which measured 23% of DeepSeek calls ending at
`max_tokens`.

## v2 — current corpus, `data/raw/`

Collected at `max_tokens=8192` with the same prompts, scenarios and model arms as
v1, in the same canonical order. The only intended difference is the cap and the
instrumentation; the protocol is recorded in `data/raw/_protocol.json` so that
the change is a stated finding rather than something a reader has to infer from
differing token counts.

Every row now carries:

| field | meaning |
|---|---|
| `stop_reason` | `end_turn` for a complete reply, `max_tokens` if it hit the cap |
| `usage` | input and output tokens as reported by the provider |
| `response_model` | the model the provider **reports it served** |
| `run_date_utc` | when the row was collected |
| `git_sha` | the collector commit that produced it |
| `corpus_version` | `v2` |

`response_model` is recorded rather than inferred deliberately: a model name in a
config file is a request, not a statement about what answered. If the provider
serves a different snapshot than the one configured, this is where it shows.

### Outcome

Collected 2026-09-17, ~70 minutes at 4 workers, **$5.38** in API spend (computed
from the recorded usage; DeepSeek priced at peak). 1,200 rows, 0 failures.

| | v1 | v2 |
|---|---|---|
| empty replies | 84 | **0** |
| rows hitting the cap | undetectable | **0** |
| `stop_reason` | absent | `end_turn` × 1,200 |
| longest reply | (capped) | 4,363 output tokens — 47% of the budget unused |
| formerly-empty rows recovered | — | **84 / 84** |

`max_tokens=8192` left roughly half the budget unused on the longest reply in the
corpus, so the cap is no longer the binding constraint it was at 1024.

One incidental finding, flagged because it bears on the RQ rather than on the
corpus: the DeepSeek refusal template appears on 148 rows and **all of them are in
`cn.zh`** — zero in `cn.en`, where the same model answers the same scenarios in
English. 128 of v1's 159 refusals recur (81%), so this is a stable model behaviour
rather than sampling noise. Note the scope of what string-matching can see: it
finds this one canned template and nothing else. A refusal phrased any other way —
and every refusal by the `us` model — has to be found by the judge.


The manifest also carries the model IDs and base URLs used (never credentials), a
sha256 of the prompt source, per-file row and empty counts, the `stop_reason`
distribution, and v1's hashes and defects.

### Ordering, and why it matters

Rows are written as they complete and then sorted back into canonical prompt order
at the end of the run, so v1 and v2 line up row-for-row and a diff between them is
meaningful rather than just noisy. A resumed run re-sorts, so an interrupted
collection still lands in canonical order.

### Re-running

The collector skips any `(scenario_id, framing)` already present in the target
directory, so an interrupted run resumes by re-invoking it with the same
`--out-dir`. Always pass `--out-dir` explicitly: the default is `data/raw`, the live
corpus, and a re-collection under a different protocol belongs in a directory of its
own.

```bash
.venv-llm/bin/python scripts/run_batch.py --out-dir <new-dir> --workers 4
```

## Verifying these claims

```bash
# the live corpus, byte for byte
shasum -a 256 data/raw/*.jsonl

# v1 is unchanged and still retrievable from history
git show 68ad171:data/raw/cn.zh.jsonl | shasum -a 256
#   → 4ccf9587bd3a5d2bc06e56044b03abdc04d48438d7a78bce5988fca8b49d724c

# no row is empty and none hit the cap
python3 - <<'PY'
import json, glob, collections
rows = [json.loads(l) for f in glob.glob("data/raw/*.jsonl")
        for l in open(f, encoding="utf-8") if l.strip()]
print("rows:", len(rows))
print("empty:", sum(1 for r in rows if not r["response"].strip()))
print("stop_reason:", dict(collections.Counter(r["stop_reason"] for r in rows)))
print("refusal field present:", any("refusal" in r for r in rows))
PY
```
