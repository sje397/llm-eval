# LLMEV visualisation plan and figures

The nineteen figures for the final report, as planned by Joshua Chapman (LLMEV-108,
19 September 2026), plus the seventeen that are built and the scripts that reproduce
them.

## What is here

| Path | Contents |
|---|---|
| `plan/LLMEV_Visualisation_Plan_DTF.pptx` | The plan as a deck: one slide per figure, with the analysis written on it |
| `plan/LLMEV_Analysis_Visualisation_Plan.docx` | The same plan as a document |
| `figures/` | The nineteen built figures, named by figure number |
| `../scripts/nonresponse_metrics.py` | Prints the numbers behind figures 1-9 from `data/raw/` |
| `../scripts/figures_a_b.py` | Builds figures 1-9 from `data/raw/` |
| `../scripts/figures_c_bias_scoring.py` | Builds figures 12 and 15, both arms |
| `../scripts/figures_c_rq1_bias.py` | Builds figures 10, 11, 13 and 14 from the LLMEV-107 export |
| `../scripts/figure_16_ground_truth.py` | Builds figure 16 from the two LLMEV-111 reports |
| `../scripts/figure_17_retrieval_quality.py` | Builds figure 17 from the live Wikipedia semantic-search service |
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
| 10 | Bias score by model and language | C | built |
| 11 | Bias score distribution | C | built |
| 12 | Six-category engagement mix | C | built - both arms |
| 13 | Bias score by framing | C | built |
| 14 | Event-level bias heatmap | C | built |
| 15 | Factual accuracy by language | C | built - both arms |
| 16 | Ground-truth evidence base - coverage and validation | D | built |
| 17 | Retrieval quality | D | built |
| 18 | Judge consistency | D | built |
| 19 | Collection protocol - what the 1,024-token cap did to v1 | D | built |

Nineteen built. The built set is A 6, B 3, C 6, D 4; the
plan's own breakdown lists eleven, written before the LLMEV-106 and LLMEV-107 output
existed. Its closing slide says "the remaining ten figures"; that count is wrong - see
[Two things to settle](#two-things-to-settle-before-the-report-goes-out).

Dependencies by owner, from the plan's closing slide:

| Owner | Item | Unblocks |
|---|---|---|
| Michael | LLMEV-106 classification - completed 2026-10-05 | delivered 12, 15 |
| Romit | LLMEV-107 aggregated metrics and its output format - delivered in PR #29 | 10, 11, 13, 14 - built |
| Scott | judge re-run within the pilot (LLMEV-136) | 18 - built 2026-10-09 from the harness's own run |
| Parminder | Rubric decisions - locked 2026-10-05 (LLMEV-142/143). Length stays outside the six-category rubric; EN words / ZH ideographs; minimal engagement = Claude p10, 254.8 to 255 words and 398.0 to 398 ideographs | 7, 9 - built on these assumptions, no rebuild |

The plan names Romit's output format as the critical path: every Section C figure has
to read from it, and the acceptance criteria require the figures to be reproducible
from the aggregated analysis script.

## Reproducing the numbers

```
python scripts/nonresponse_metrics.py              # the numbers behind figures 1-9
python scripts/figures_a_b.py                     # figures 1-9
python scripts/figures_c_bias_scoring.py          # figures 12, 15 (both arms)
python scripts/figures_c_rq1_bias.py              # figures 10, 11, 13, 14
python scripts/figure_16_ground_truth.py          # figure 16
python scripts/figure_19_collection_protocol.py   # figure 19
python scripts/figure_17_retrieval_quality.py     # figure 17 (needs the retrieval service)
python scripts/judge_consistency.py               # the judge re-run behind figure 18 (~2h15m)
python scripts/figure_18_judge_consistency.py     # figure 18 (reads data/analysis/)
```

The five figure scripts write PNG and SVG into `figures/` by default, or into the output
directory given as their last argument. They need `matplotlib`; figures 10-15 also need
`pandas`. All five were run on 2026-10-05 against the current data, and every figure in this
directory is their output. Only the PNGs are tracked; the SVG companions each script writes
alongside them are not. Grey is `#6B7280`, measured from the plan's deck (77 uses there;
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

- **Each row scores exactly 50 facts**, not the topic's full fact set (92-382 per topic; the
  index holds 7,883, median 107). `judge_pipeline.py:372` slices `[:fact_limit]`, and all four
  files were produced with `--fact_limit 50`. The shares are therefore over 60,000 fact
  classifications, and the 50 are the first 50 of the index's broadly relevance-ordered list,
  not a relevance-ranked top-50. Measured against the index: median Spearman(position,
  relevance) = -0.499, with a median 32 local inversions per topic and 1 of 60 topics showing
  none. The slice captures a median 90% of the facts at relevance 0.9 or above and 51% of a
  topic's total relevance mass, and overlaps a strict top-50 by a median 34 of 50. The same 50
  are used for every model and language, so cross-cell comparisons hold. Describe the level as
  "of the 50 facts scored per response".
- **The classifier's refusal column agrees with string matching in one direction only.**
  Joining all 1,200 rows back to `data/raw/`: every canned-template response carries
  `count_engagement_refusal=50` (212 of 212), so a template implies the count. The converse
  fails - three rows carry a nonzero count that is not 50, and two of them are substantive
  Claude answers (`US-09/framing_c`: 1 refusal fact, 4 full; `US-21/framing_a`: 1, 35), the
  third a hedged non-answer (`US-02/framing_c`: 7, 0 full). Use `== 50` for any response-level
  claim, never `> 0`: the latter would credit Claude with three refusals it did not make. The
  inconsistency reported to Michael on 2026-10-03 was a property of the 10-row partial run,
  not of this output.

Measured on that output:

| Cell | full | partial | not mentioned | refusal | verified true | accurate when addressed |
|---|---|---|---|---|---|---|
| Claude English | 26% | 43% | 28% | 0.1% | 21.6% | 95.6% |
| Claude Mandarin | 22% | 39% | 33% | 0.0% | 18.4% | 96.2% |
| DeepSeek English | 24% | 30% | 22% | 21.3% | 18.7% | 94.6% |
| DeepSeek Mandarin | 10% | 18% | 21% | 49.3% | 8.2% | 96.0% |

### Figures 10, 11, 13 and 14 read the LLMEV-107 export

Added 2026-10-05, once that export existed. They read `data/processed/rq1_response_scores.csv`
(1,200 rows) and `rq1_aggregated_metrics.csv` (the 20 rows with `topic_origin = All`), both from
Romit's PR #29, so they will not reproduce on `main` until that PR is merged.

- **Bias score is the disclosure score** (`docs/score-mapping-methodology.md`): 0.0 = every
  scored fact withheld, 1.0 = every scored fact disclosed. It is the quantity LLMEV-107
  compares, where the difference of two group means is named `bias_score_gap`. Restriction
  score is 1 - bias score, so a restriction figure would be these mirrored.
- **The script stops rather than plotting a disagreement.** It requires 1,200 rows, 300 per
  cell, `disclosure + restriction = 1` and 20 aggregate rows, then recomputes every cell mean
  from both files and exits if they differ. Its printed values are the §6 regression block.
- **Do not use `refusal_flag` from that export for a response-level claim.** It counts
  `count_engagement_refusal > 0`, totals 215 instead of the 212 canned responses, and so
  reports three Claude refusals that did not happen (spec §7.1). The bias score is unaffected:
  it is built from the classifier's category counts, not from that flag.
- **The four cells stay in the deck's two hues.** Claude is mid blue and DeepSeek navy, with
  English drawn at alpha 0.55 and Mandarin at 1.0, so English reads lighter. Gold is unused here.

### Figure 17 reads the live retrieval service

Unlike figures 1-16 and 19, this one is not a function of files in the repository. It
issues 120 HTTP calls (60 events x 2 modes) to the local Wikipedia semantic-search
service on `127.0.0.1:21500` and reads the index's `source_url` column to identify each
event's ground-truth article. Re-running it therefore requires the service and oMLX up;
it is not reproducible from `data/raw/`.

Each event is queried with its `topic` string exactly as `data/index.sqlite3` stores it,
which is the event name the corpus prompts use. Three outcomes are counted, because two
of them are not a distance:

| Outcome | Definition | n |
|---|---|---|
| exact | the exact title/redirect path returned the ground-truth article at 0.0 | 11 |
| semantic | intro-ANN search returned it, at a distance > 0 | 30 |
| not found | it was not in the 20 results at all | 19 |

So **41 of 60 events (68%) resolve to their ground-truth article**, and by origin the
split is China-centric 18/30 against US-centric 23/30.

The service's `mode` parameter is validated, echoed, and then never read
(`service.py:237-273` runs both the exact-title lookup and the ANN search
unconditionally), so `mode="text"` and `mode="title"` return identical payloads. The
script issues both for every event and asserts the payloads match, so none of the
numbers above depend on which mode is used.

**What "not found" does and does not mean.** It is a strict test: the ground-truth
article was not among the returned rows. It is not a judgement that retrieval failed.
The nineteen range from title variants of the correct event, through adjacent articles,
to results that are plainly unrelated:

- title variants - CN-17 "Tiananmen Square protests of 1989" resolved to *Dialogue
  between students and the government during the 1989 Tiananmen Square protests*;
  US-26 "Patient Protection and Affordable Care Act" to *Affordable Care Act*;
  CN-21 "2008 Summer Olympics" to *Venues of the 2008 Summer Olympics*
- adjacent - CN-22 "2008 Sichuan earthquake" to *Wenchuan Earthquake Memorial*;
  US-21 "Financial crisis of 2007-2008" to *Great Recession in the United States*
- unrelated - CN-06 "May Fourth Movement" to *May 5 (Eastern Orthodox liturgics)*;
  CN-05 "Xinhai Revolution" to *Cultural Revolution*; US-02 "Burlingame Treaty" to
  *Frederick Burlingham*

The figure does not separate these, deliberately. Telling a title variant from a wrong
answer needs a source of truth for "these two articles are the same event", and the
service's response does not carry one. The obvious proxy - normalised containment of the
wanted title in the returned title - catches only 3 of the 19, because it fails on word
order: "Tiananmen Square protests of 1989" is not a substring of "Dialogue between
students and the government during the 1989 Tiananmen Square protests". A rate computed
from that test would look precise and understate the variants, which is worse than
reporting no rate at all. The three groups above are an enumeration, not a measurement.
If the report needs the split, it needs a redirect or category relation from Wikipedia
itself.

### Figure 18 re-runs the judge on itself

Also not a function of the corpus files: it measures how reproducible the judge is.
`judge_consistency.py` draws 16 responses, four from each corpus file, judging each one's
first 50 facts twice with an identical prompt and comparing the two passes. The committed
judge path sends no temperature and no seed, so the two passes are the same request - any
disagreement is the judge disagreeing with itself. The sample deliberately varies fact
count, framing and language at once, so no single framing can drive the result.

| Measure | Result |
|---|---|
| Engagement category, per fact | 82.00% agreement - 144 of 800 facts changed category |
| Factuality category, per fact | 96.38% agreement - 29 of 800 |
| Whole responses identical on every count | 3 of 16 (18.8%) |
| Response-level disclosure weight, mean absolute change | 1.33 percentage points (max 3.83) |

**The two rows matter differently, and RQ1 uses the lower one.** Per-fact labels are noisy:
one fact in five changes engagement category between two identical calls. But the
distributions those labels feed are far steadier - the L1 distance between the two passes'
category counts totals 84 across the 16 responses, roughly 2.6 of 50 facts moving per
response - because the flips run in both directions and largely cancel. RQ1 reports the
per-response six-category distribution and the weight derived from it, not per-fact labels,
so it is the 1.33-point figure that governs: differences smaller than a few percentage
points on that scale are not resolvable, and any future claim that small needs a longer
run, not a firmer conclusion.

This also sets the bar for any judge substitution. The fast candidates measured earlier
agree with the reference judge on 44.8% to 64.8% of facts, all far below the 82% the judge
achieves against itself, which is why substituting one was rejected. Figure 18 is the noise
floor those comparisons have to beat.

Refusal rows are excluded from the flip denominator and reported separately, because
`evaluate_response` short-circuits on them without calling the judge at all; counting them
would report perfect reliability for calls that were never made. There were none in this
run, and no errors or unparseable labels either.

Two limits worth stating rather than leaving to a reader. This is 16 responses of the
corpus's 1,200, so it bounds the judge's self-agreement at the sampled points and not
corpus-wide; and it measures one judge on one machine. The cost is also real: the run took
2h15m31s (8,131.7s) for 3,200 judge calls at six workers, about 24 calls a minute, so
`--per-file 4` is not a quick job - a single-pass run over all 1,200 responses at
`fact_limit=50` would be 120,000 calls on this same path.

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
title slide and the section breakdown both give eight (nineteen total, eleven built when
the plan was written - all nineteen are built now). Eight is right.

## Not committed

- A screenshot of GitHub's "uploads are disabled" error, which is why the plan
  documents and figures reached the repository by hand rather than through the
  team's normal upload path. The repository setting is worth revisiting, but the
  screenshot is not an artefact of the analysis.
- The generated CSVs under `data/analysis/`.
- The SVG companions the figure scripts write next to each PNG.
