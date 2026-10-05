# LLMEV visualisation plan and figures

The nineteen figures for the final report, as planned by Joshua Chapman (LLMEV-108,
19 September 2026), plus the thirteen that are built and the scripts that reproduce
them.

## What is here

| Path | Contents |
|---|---|
| `plan/LLMEV_Visualisation_Plan_DTF.pptx` | The plan as a deck: one slide per figure, with the analysis written on it |
| `plan/LLMEV_Analysis_Visualisation_Plan.docx` | The same plan as a document |
| `figures/` | The thirteen built figures, named by figure number |
| `../scripts/nonresponse_metrics.py` | Prints the numbers behind figures 1-9 from `data/raw/` |
| `../scripts/figures_a_b.py` | Builds figures 1-9 from `data/raw/` |
| `../scripts/figures_c_bias_scoring.py` | Builds figures 12 and 15, both arms |
| `../scripts/figure_16_ground_truth.py` | Builds figure 16 from the two LLMEV-111 reports |
| `../scripts/figure_19_collection_protocol.py` | Builds figure 19 from the v1 damage constants |
| `../docs/analysis-spec.md` | The executable spec: contracts, expected values, known issues |

Both plan documents were provided by the team. They are committed here unchanged so
the figures below can be checked against the analysis that accompanies them.

## Status of the nineteen figures

| # | Figure | Section | Status |
|---|---|---|---|
| 1 | Non-response rate by model and prompt language | A | built |
| 2 | Where the non-responses come from | A | built |
| 3 | Non-response by prompt framing | A | built |
| 4 | Non-response by model x language combination | A | built |
| 5 | Non-responses by event, all four combinations | A | built |
| 6 | Non-response by event origin | A | built |
| 7 | Length of substantive responses | B | built |
| 8 | Response length by framing | B | built |
| 9 | Partial engagement - four response types | B | built |
| 10 | Bias score by model and language | C | data ready (`data/processed/rq1_aggregated_metrics.csv`) |
| 11 | Bias score distribution | C | data ready (`data/processed/rq1_response_scores.csv`) |
| 12 | Six-category engagement mix | C | built - both arms |
| 13 | Bias score by framing | C | data ready (`data/processed/rq1_aggregated_metrics.csv`) |
| 14 | Event-level bias heatmap | C | data ready (`data/processed/rq1_response_scores.csv`) |
| 15 | Factual accuracy by language | C | built - both arms |
| 16 | Ground-truth evidence base - coverage and validation | D | built |
| 17 | Retrieval quality | D | awaiting Wikipedia service run |
| 18 | Judge consistency | D | awaiting pilot re-run (LLMEV-136) |
| 19 | Collection protocol - what the 1,024-token cap did to v1 | D | built |

Thirteen built, six awaiting upstream data. The built set is A 6, B 3, C 2, D 2; the
plan's own breakdown lists eleven, because figures 12 and 15 were blocked on LLMEV-106
until it completed on 2026-10-05. Its closing slide says "the remaining ten figures";
that count is wrong - see
[Two things to settle](#two-things-to-settle-before-the-report-goes-out).

Dependencies by owner, from the plan's closing slide:

| Owner | Item | Unblocks |
|---|---|---|
| Michael | LLMEV-106 classification - completed 2026-10-05 | delivered 12, 15 |
| Romit | LLMEV-107 aggregated metrics and its output format (`scripts/rq1_export.py` → `data/processed/rq1_*.csv`) | 10, 11, 13, 14 |
| Scott | Wikipedia service run · judge re-run within the pilot (LLMEV-136) | 17, 18 |
| Parminder | Rubric decisions: length dimension, minimal-engagement threshold | 7, 9 |

The plan names Romit's output format as the critical path: every Section C figure has
to read from it, and the acceptance criteria require the figures to be reproducible
from the aggregated analysis script.

## Reproducing the numbers

```
python scripts/nonresponse_metrics.py              # the numbers behind figures 1-9
python scripts/figures_a_b.py                     # figures 1-9
python scripts/figures_c_bias_scoring.py          # figures 12, 15 (both arms)
python scripts/figure_16_ground_truth.py          # figure 16
python scripts/figure_19_collection_protocol.py   # figure 19
```

The four figure scripts write PNG and SVG into `figures/` by default, or into the output
directory given as their last argument. They need `matplotlib`; figures 12 and 15 also need
`pandas`. All four were run on 2026-10-05 against the current data, and every figure in this
directory is their output. Grey is `#6B7280`, measured from the plan's deck (77 uses there;
the earlier `#9AA3B2` appears zero times in it).

Reads `data/raw/*.jsonl` only - no judge output, no network. Prints four tables and
writes them as CSV to `data/analysis/` (generated, not committed).

**The numbers in this file describe the v2 corpus** (`data/raw` on `main`, which has held v2 since PR #21), which is the corpus the plan's figures are drawn from.
The script prints the corpus version it read and refuses a file that mixes two versions,
because a blend of two collection protocols still produces plausible-looking rates.

It will not run against v1 at all: those rows carry no `corpus_version` field, so on a
v1 checkout it stops with `missing field 'corpus_version'` rather than reporting numbers
that would not match the figures below. That is deliberate - v1's non-response count is
different (216 rather than 212) and it has 84 empty rows. Run it on
`main`. v1's bytes remain reachable at commit `68ad171`, and the superseded hashes are
recorded in `data/raw/_protocol.json`.

### Figures 12 and 15 read the LLMEV-106 classifier

Both are computed from `data/evaluation.*.csv`, complete for all four cells since 2026-10-05
(300 rows each, 60 scenarios x 5 framings). Two properties of that output matter when reading
them:

- **Each row scores exactly 50 facts**, not the topic's full fact set (92-382 per topic).
  `judge_pipeline.py:372` slices `[:fact_limit]`, and all four files were produced with
  `--fact_limit 50`. The shares are therefore over 60,000 fact classifications, and the 50 are
  the first 50 in document order, not a relevance-ranked subset. The same 50 are used for every
  model and language, so cross-cell comparisons hold - but describe the level as "of the 50
  facts scored per response", and ask Michael whether the prefix is representative before
  calling it all facts.
- **The classifier's refusal column agrees with string matching.** Joining all 1,200 rows back
  to `data/raw/`: every canned-template response carries `count_engagement_refusal=50`, and no
  other row carries any refusal count - 0 mismatches. The inconsistency reported to Michael on
  2026-10-03 was a property of the 10-row partial run, not of this output.

Measured on that output:

| Cell | full | partial | not mentioned | refusal | verified true | accurate when addressed |
|---|---|---|---|---|---|---|
| Claude English | 26% | 43% | 28% | 0.1% | 21.6% | 95.6% |
| Claude Mandarin | 22% | 39% | 33% | 0.0% | 18.4% | 96.2% |
| DeepSeek English | 24% | 30% | 22% | 21.3% | 18.7% | 94.6% |
| DeepSeek Mandarin | 10% | 18% | 21% | 49.3% | 8.2% | 96.0% |

### Verified against the plan

The numbers the plan states for figures 1, 2, 3, 4, 6, 7, 8 and 9 were checked
against the corpus and reproduce. The plan's figures are, on this evidence, correct:
21.3% and 49.3%
non-response by language; a three-fold English gap by event origin (32.7% vs 10.0%)
that closes in Mandarin (54.0% vs 44.7%); framing C and D highest in Mandarin at
63.3% each; Claude's English median of 308 words with IQR 279-346; and Claude at 90%
substantive in both languages.

| Figure | Measured (v2) |
|---|---|
| 1 | Claude 0/600 non-responses. DeepSeek 212/600: 64 English (21.3%), 148 Mandarin (49.3%) |
| 2 | Two fixed strings account for all 212; no third template appears at any repeat count |
| 3 | Framing C 46.7% English / 63.3% Mandarin; framing D 5.0% English / 63.3% Mandarin |
| 4 | Claude 0% / 0%; DeepSeek 21.3% English / 49.3% Mandarin |
| 6 | China-centric 32.7% English, 54.0% Mandarin; US-centric 10.0% English, 44.7% Mandarin |
| 7 | See the length table below |
| 9 | Claude 90.0% substantive English, 90.3% Mandarin; DeepSeek 54.3% / 29.0% |

Not re-derived here: figure 5's per-event ranking and figure 8's per-framing split
beyond the English range the plan states (268-373 words, which reproduces). Both need
groupings the script does not yet produce. Figure 16's coverage figures were checked
separately against `data/index.sqlite3` and all reproduce: 60 events, 7,883 facts, 92
to 382 per event, median 107; China-centric median 112 with 4,209 facts, US-centric
median 104 with 3,674, both bottoming out at 92.

One detail worth knowing when reproducing any of these: the plan rounds halves to even
(189.5 -> 190 words, 345.5 -> 346 for the IQR, but 112.5 -> 112 facts), which is
Python's built-in `round`, not round-half-up. Matching the plan's stated figures means
using `round()`; matching them with a different convention will differ by one on every
half, which is enough to look like a disagreement.

### Length unit convention

**English length is whitespace-separated words. Mandarin length is the count of CJK
ideographs, not `len()`.** The distinction is not cosmetic: `len()` over the same
Mandarin responses is about 35% larger, because it also counts punctuation, spaces
and Markdown.

This was verified rather than assumed. The plan's Mandarin figures (median 473, p10
398) reproduce *only* under the ideograph count; under `len()` the same responses give
638.5 and 545.0. Since p10 defines the minimal-engagement threshold, choosing the
wrong unit would move the boundary that separates a substantive answer from a minimal
one, and every Mandarin figure downstream of it.

| Model | Language | Unit | n | median | p10 | IQR |
|---|---|---|---|---|---|---|
| Claude | English | words | 300 | 308.0 | 254.8 | 279.0-345.5 |
| Claude | Mandarin | CJK ideographs | 300 | 473.0 | 398.0 | 431.0-527.0 |
| DeepSeek | English | words | 236 | 365.5 | 122.5 | 226.8-584.5 |
| DeepSeek | Mandarin | CJK ideographs | 152 | 466.5 | 151.7 | 205.0-692.8 |

Canned non-responses are excluded from these distributions: a refusal is not a short
answer, and including one would move the percentile that defines minimal engagement.
The DeepSeek cells therefore have a smaller n than the Claude cells, and the difference
is itself the finding - DeepSeek's remaining answers are widely spread (English max
1,405 words, Mandarin max 1,918 ideographs) where Claude's are tight.

### The decision figures 7 and 9 are waiting on

The plan lists two rubric decisions under Parminder that lock figures 7 and 9. The
measurements above supply the input for both:

- **Length dimension** - language-dependent units are required. A single unit across
  both languages is not available: words undercount Mandarin (no spaces), and
  characters overcount it (punctuation and Markdown).
- **Minimal-engagement threshold** - Claude's p10 by language, 254.8 English words
  (measured 255 by the plan) and 398.0 Mandarin ideographs.

## Two things to settle before the report goes out

**1. Figure 4's axis notation collides with figure 6's.** Figure 4's four cells are
labelled `EN->US`, `ZH->US`, `EN->CN`, `ZH->CN`, but they are model-by-language cells -
the plan's own analysis on that slide says "Claude is flat across languages. DeepSeek is
not", and the values are Claude 0%/0% and DeepSeek 21.3%/49.3%. Read as prompt-language
by scenario-origin, which is how the same arrow notation reads two slides later,
`ZH->US 0%` is false: DeepSeek's Mandarin responses to US-centric events are refused
44.7% of the time (figure 6). A reader comparing the two figures sees a contradiction
that exists in the labels, not in the data. Suggest `EN / Claude`, `ZH / Claude`,
`EN / DeepSeek`, `ZH / DeepSeek`.

**2. The figure count on the closing slide.** It says "the remaining ten figures"; the
title slide and the section breakdown both give eight (nineteen total, eleven built).
Eight is right.

## Not committed

- A screenshot of GitHub's "uploads are disabled" error, which is why the plan
  documents and figures reached the repository by hand rather than through the
  team's normal upload path. The repository setting is worth revisiting, but the
  screenshot is not an artefact of the analysis.
- The generated CSVs under `data/analysis/`.
