# LLMEV visualisation plan and figures

The nineteen figures for the final report, as planned by Joshua Chapman (LLMEV-108,
19 September 2026), plus the eleven that are built and the script that reproduces
their underlying numbers.

## What is here

| Path | Contents |
|---|---|
| `plan/LLMEV_Visualisation_Plan_DTF.pptx` | The plan as a deck: one slide per figure, with the analysis written on it |
| `plan/LLMEV_Analysis_Visualisation_Plan.docx` | The same plan as a document |
| `figures/` | The eleven built figures, named by figure number |
| `../scripts/nonresponse_metrics.py` | Reproduces the numbers behind figures 1-9 from `data/raw/` |

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
| 10 | Bias score by model and language | C | awaiting LLMEV-106 / LLMEV-107 |
| 11 | Bias score distribution | C | awaiting LLMEV-107 |
| 12 | Six-category engagement mix | C | awaiting LLMEV-106 |
| 13 | Bias score by framing | C | awaiting LLMEV-106 / LLMEV-107 |
| 14 | Event-level bias heatmap | C | awaiting LLMEV-107 |
| 15 | Factual accuracy by language | C | awaiting LLMEV-106 |
| 16 | Ground-truth evidence base - coverage and validation | D | built |
| 17 | Retrieval quality | D | awaiting Wikipedia service run |
| 18 | Judge consistency | D | awaiting pilot re-run (LLMEV-136) |
| 19 | Collection protocol - what the 1,024-token cap did to v1 | D | built |

Eleven built, eight awaiting upstream data. The plan's own breakdown agrees (A 6, B 3,
D 2). Its closing slide says "the remaining ten figures"; that count is wrong - see
[Two things to settle](#two-things-to-settle-before-the-report-goes-out).

Dependencies by owner, from the plan's closing slide:

| Owner | Item | Unblocks |
|---|---|---|
| Michael | LLMEV-106 classification | 10, 12, 13, 15 |
| Romit | LLMEV-107 aggregated metrics and its output format | 10, 11, 13, 14 |
| Scott | Wikipedia service run · judge re-run within the pilot (LLMEV-136) | 17, 18 |
| Parminder | Rubric decisions: length dimension, minimal-engagement threshold | 7, 9 |

The plan names Romit's output format as the critical path: every Section C figure has
to read from it, and the acceptance criteria require the figures to be reproducible
from the aggregated analysis script.

## Reproducing the numbers

```
python scripts/nonresponse_metrics.py
```

Reads `data/raw/*.jsonl` only - no judge output, no network. Prints four tables and
writes them as CSV to `data/analysis/` (generated, not committed).

**The numbers in this file describe the v2 corpus** (`data/raw` on
`feat/v2-corpus-recollection`), which is the corpus the plan's figures are drawn from.
The script prints the corpus version it read and refuses a file that mixes two versions,
because a blend of two collection protocols still produces plausible-looking rates.

It will not run against v1 at all: those rows carry no `corpus_version` field, so on a
v1 checkout it stops with `missing field 'corpus_version'` rather than reporting numbers
that would not match the figures below. That is deliberate - v1's non-response count is
different (216 rather than 212) and it has 84 empty rows. Run it against
`feat/v2-corpus-recollection`.

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
