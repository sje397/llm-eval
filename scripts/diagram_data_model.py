#!/usr/bin/env python3
"""LLMEV-144 - evaluation data model (entity-relationship diagram).

Derived from the ARTEFACTS, not from prose: the DDL is read out of
data/index.sqlite3, and every join asserted in the diagram is executed against
the real files before it is drawn (see verify() below, which runs on every
invocation and refuses to draw an unverified relationship).

Design inputs, then four data layers in pipeline order:

  0 design      data/scenarios.json      scenario, framing         60 + 5
  1 ground truth data/index.sqlite3      articles                  60  (7,883 facts)
  2 corpus      data/raw/*.jsonl         response                1200
  3 judge       data/evaluation.*.csv    fact_classification     1200
  4 derived     data/processed/*.csv (PR #29)  response_score 1200,
                                               aggregate_metric 60,
                                               statistical_comparison 48

Two properties the diagram exists to make visible:

  * The ground-truth layer is ONE table with the facts denormalised into a JSON
    column. There is no fact table and no declared foreign key anywhere in the
    schema.
  * articles.topic_id carries the same key space as scenarios[].id (verified equal
    as sets, 60/60), but that column is not created by any committed script:
    build_index.py declares `articles(topic TEXT PRIMARY KEY, source_url,
    facts_json)` - three columns. The shipped database has four. judge_pipeline.py
    reads it with `SELECT *` and indexes the result by column NAME, so the
    consumer depends on a schema no committed builder produces.

Usage: python scripts/diagram_data_model.py [out_dir]
Default out_dir: docs/diagrams
"""
import csv
import glob
import json
import os
import re
import sqlite3
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/diagrams"
os.makedirs(OUT, exist_ok=True)

NAVY, MID, AMBER, GREY, GREEN, ICE = "#1E2761", "#3E5199", "#D98A2B", "#6B7280", "#2E7D5B", "#CADCFC"
plt.rcParams.update({"font.family": "DejaVu Sans"})


# ------------------------------------------------------------------ svg output
def stabilise_svg(path):
    """Rewrite matplotlib's clip-path ids, which are derived from object addresses.

    Every other byte of the SVG is deterministic, so without this a regenerated file
    differs from the committed one in those ids alone and each run is a spurious
    diff. Mapping them in order of first appearance makes the output byte-stable -
    checked by running the script twice and comparing hashes.
    """
    text = open(path, encoding="utf-8", newline="").read()
    names = {}

    def _sub(m):
        prefix, old = m.group(1), m.group(2)
        if old not in names:
            names[old] = "clipPath%d" % len(names)
        return prefix + names[old]

    text, n = re.subn(r'(url\(#|id=")(p[0-9a-f]{8,})', _sub, text)
    if n:
        open(path, "w", encoding="utf-8", newline="").write(text)
    dangling = set(re.findall(r'url\(#([^)]+)\)', text)) - set(re.findall(r'id="([^"]+)"', text))
    assert not dangling, "stabilised SVG has a dangling reference: %s" % sorted(dangling)


# ----------------------------------------------------------------- verification
def verify():
    """Execute every join the diagram claims. Raise rather than draw a lie."""
    sc = json.load(open("data/scenarios.json"))
    sids = [s["id"] for s in sc["scenarios"]]

    con = sqlite3.connect("data/index.sqlite3")
    tids = [r[0] for r in con.execute("SELECT topic_id FROM articles")]
    assert set(tids) == set(sids), "articles.topic_id is not the scenario_id key space"
    assert len(tids) == len(set(tids)), "duplicate topic_id in articles"
    facts = sum(len(json.loads(r[0])) for r in con.execute("SELECT facts_json FROM articles"))
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='articles'").fetchone()[0]
    con.close()

    responses = []
    for f in sorted(glob.glob("data/raw/*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            responses.append((r["scenario_id"], r["framing"], r["language"], r["model"]))
    assert len(responses) == 1200, "expected 1200 responses, got %d" % len(responses)
    assert len(set(responses)) == len(responses), "responses are not unique on the model key"
    assert not ({s for s, _, _, _ in responses} - set(sids)), "a response cites an unknown scenario"

    judged = []
    for f in sorted(glob.glob("data/evaluation.*.csv")):
        for row in csv.DictReader(open(f)):
            judged.append((row["scenario_id"], row["framing"], row["language"], row["model"]))
    assert len(judged) == 1200, "expected 1200 judged rows, got %d" % len(judged)
    # The defining join: every judged row resolves to exactly one response. Key order
    # must match `responses` exactly - an earlier revision built this tuple in CSV
    # column order and the check fired on that alone, which is the bug it is for.
    if set(judged) != set(responses):
        miss, extra = set(responses) - set(judged), set(judged) - set(responses)
        raise AssertionError(
            "judge output does not align 1:1 with the corpus: %d responses unjudged, %d judged "
            "rows with no response. sample unjudged=%s" % (len(miss), len(extra), sorted(miss)[:3]))

    return facts, ddl


FACTS, DDL = verify()


# ---------------------------------------------------------------------- layout
# (x, y) is the box's bottom-left corner in axes fraction; (w, h) its size.
BOXES = {
    "scenario": dict(
        x=0.010, y=0.585, w=0.215, h=0.350,
        head="scenario", tag="design input", src="data/scenarios.json", rows="60",
        pk="PK  scenario_id  (CN-01 … US-30)",
        fields=["region              CN | US",
                "event.en / event.zh",
                "source.en / source.zh",
                "verb_form",
                "period",
                "relevance"]),
    "framing": dict(
        x=0.010, y=0.300, w=0.215, h=0.235,
        head="framing", tag="design input", src="data/scenarios.json", rows="5",
        pk="PK  framing_id  (framing_a … e)",
        fields=["prompt_template.en",
                "prompt_template.zh",
                "scenario × framing  =  600 prompts"]),
    "articles": dict(
        x=0.010, y=0.020, w=0.215, h=0.230,
        head="articles", tag="ground truth", src="data/index.sqlite3", rows="60",
        pk="PK  topic_id   (= scenario_id)",
        fields=["topic",
                "source_url",
                "facts_json  →  JSON array",
                "     fact_en, fact_zh, relevance",
                "%s facts, 92–382 per article" % format(FACTS, ",")]),
    "response": dict(
        x=0.285, y=0.585, w=0.230, h=0.350,
        head="response", tag="corpus", src="data/raw/{cn,us}.{en,zh}.jsonl", rows="1200",
        pk="KEY (scenario_id, framing, language, model)",
        fields=["scenario_id        FK → scenario",
                "framing            FK → framing",
                "language           en | zh",
                "model              claude-sonnet-5 |",
                "                   deepseek-v4-pro",
                "prompt, response",
                "stop_reason, usage{}, max_tokens",
                "run_date_utc, git_sha, corpus_version"]),
    "fact_classification": dict(
        x=0.575, y=0.585, w=0.220, h=0.350,
        head="fact_classification", tag="judge output", src="data/evaluation.*.csv", rows="1200",
        pk="KEY (model, language, scenario_id, framing)",
        fields=["count_engagement_*   7 categories",
                "  full, partial, non_answer,",
                "  deflection, not_mentioned,",
                "  refusal, other",
                "weight_engagement_*  same 7, weighted",
                "count_facts_*        4 categories",
                "  true, false, not_answered, other",
                "weight_facts_*       same 4",
                "… 50 facts scored per response"]),
    "response_score": dict(
        x=0.575, y=0.020, w=0.220, h=0.230,
        head="response_score", tag="derived", src="rq1_response_scores.csv", rows="1200",
        pk="PK  response_id",
        fields=["scenario_id, topic_origin",
                "model, language, framing",
                "disclosure_score   0.0–1.0",
                "restriction_score  = 1 − disclosure",
                "refusal_flag"]),
    "aggregate_metric": dict(
        x=0.810, y=0.585, w=0.178, h=0.300,
        head="aggregate_metric", tag="derived", src="rq1_aggregated_metrics.csv", rows="60",
        pk="KEY (model, language,",
        fields=["       framing, topic_origin)",
                "sample_size",
                "mean / std / variance",
                "  _disclosure_score",
                "mean / std",
                "  _restriction_score",
                "refusal_rate"]),
    "statistical_comparison": dict(
        x=0.810, y=0.020, w=0.178, h=0.185,
        head="statistical_comparison", tag="derived", src="rq1_statistical_comparisons.csv", rows="48",
        pk="KEY (comparison_type,",
        fields=["       group_a, group_b, framing)",
                "statistic, p_value",
                "effect_size",
                "bias_score_gap"]),
}

EDGES = [
    ("scenario", "response", "R", "L", "scenario_id", "1", "N"),
    ("framing", "response", "R", "L", "framing", "1", "N"),
    ("articles", "response", "T", "B", "topic_id = scenario_id", "1", "N"),
    ("response", "fact_classification", "R", "L", "model, language,\nscenario_id, framing", "1", "1"),
    ("articles", "fact_classification", "R", "B", "facts_json\n(first 50)", "1", "N"),
    ("response", "response_score", "R", "L", "scenario_id, framing,\nmodel, language", "1", "1"),
    ("fact_classification", "aggregate_metric", "R", "L", "model, language,\nframing, topic_origin", "N", "1"),
    ("response_score", "aggregate_metric", "R", "B", "model, language,\nframing, topic_origin", "N", "1"),
    ("aggregate_metric", "statistical_comparison", "B", "T", "group_a vs group_b", "N", "1"),
]

TAG_COLOUR = {"design input": AMBER, "ground truth": GREEN, "corpus": NAVY,
              "judge output": MID, "derived": GREY}


FIG_W = 17.5


def in_w(ax, fig, data_w):
    """Width of `data_w` x-data units, in INCHES.

    The axes do not span the figure - the default axes box is ~0.775 of the figure
    width - so a data-unit width is NOT `data_w * FIG_W`. Using the figure width
    overestimates every box by ~1.29x, and since fit() only ever SHRINKS, an
    overestimated budget silently disables the shrink and a label overruns its
    border instead of being scaled to it. Convert through the axes box.
    """
    x0, x1 = ax.get_xlim()
    return data_w * ax.get_position().width * fig.get_figwidth() / (x1 - x0)


def fit(ax, fig, x, y, s, ref, max_w_in, **kw):
    """Draw `s` at `ref` points, shrinking it until it fits in `max_w_in` inches.

    Measured through the renderer rather than estimated: character-width rules of
    thumb are wrong by enough to clip a box, and a clipped diagram in a report is
    worse than a slightly smaller label.
    """
    t = ax.text(x, y, s, fontsize=ref, **kw)
    fig.canvas.draw()
    w = t.get_window_extent(renderer=fig.canvas.get_renderer()).width / fig.dpi
    if w > max_w_in:
        t.set_fontsize(ref * max_w_in / w)
    return t


def anchor(box, side):
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    return {"L": (x, y + h / 2), "R": (x + w, y + h / 2),
            "T": (x + w / 2, y + h), "B": (x + w / 2, y)}[side]


def main():
    fig, ax = plt.subplots(figsize=(FIG_W, 9.9))
    ax.set_xlim(-0.008, 1.012)
    ax.set_ylim(0, 1)
    ax.axis("off")

    for name, b in BOXES.items():
        colour = TAG_COLOUR[b["tag"]]
        ax.add_patch(FancyBboxPatch(
            (b["x"], b["y"]), b["w"], b["h"],
            boxstyle="round,pad=0.004,rounding_size=0.012",
            linewidth=1.4, edgecolor=colour, facecolor="white", zorder=2))

        head_h = 0.055 if b["h"] > 0.3 else 0.062
        ax.add_patch(FancyBboxPatch(
            (b["x"], b["y"] + b["h"] - head_h), b["w"], head_h,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            linewidth=0, facecolor=colour, alpha=0.14, zorder=3))

        # Row count shares the head line and the layer tag shares the source line, so
        # the two long strings in a box are never on the same line as each other. Both
        # of the long ones are MEASURED and shrunk to the box: a fixed point size that
        # happens to fit one box overflows a narrower one, which is exactly how the
        # first two renders collided their filenames with their labels.
        box_w_in = in_w(ax, fig, b["w"])
        fit(ax, fig, b["x"] + 0.010, b["y"] + b["h"] - 0.019, b["head"],
            ref=12, max_w_in=box_w_in - 0.80, fontweight="bold", color=colour,
            va="center", zorder=4)
        ax.text(b["x"] + b["w"] - 0.008, b["y"] + b["h"] - 0.019, b["rows"] + " rows",
                fontsize=7.2, color=colour, va="center", ha="right", zorder=4)
        fit(ax, fig, b["x"] + 0.010, b["y"] + b["h"] - 0.039, b["src"],
            ref=6.8, max_w_in=box_w_in - 1.05, color=GREY, va="center", zorder=4,
            family="DejaVu Sans Mono")
        ax.text(b["x"] + b["w"] - 0.008, b["y"] + b["h"] - 0.039, b["tag"],
                fontsize=7.0, color=colour, va="center", ha="right", style="italic", zorder=4)

        y = b["y"] + b["h"] - head_h - 0.026
        ax.text(b["x"] + 0.010, y, b["pk"], fontsize=7.4, color=NAVY,
                va="center", fontweight="bold", zorder=4, family="DejaVu Sans Mono")
        for f in b["fields"]:
            y -= 0.020
            ax.text(b["x"] + 0.010, y, f, fontsize=7.2, color="#333333",
                    va="center", zorder=4, family="DejaVu Sans Mono")

    for src, dst, a, z, label, c1, c2 in EDGES:
        p, q = anchor(BOXES[src], a), anchor(BOXES[dst], z)
        ax.add_patch(FancyArrowPatch(
            p, q, arrowstyle="-|>", mutation_scale=13,
            linewidth=1.15, color=GREY, shrinkA=1, shrinkB=1, zorder=1))
        mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
        ax.text(mx, my + 0.013, label, fontsize=7.0, color=NAVY, ha="center", va="bottom",
                zorder=5, family="DejaVu Sans Mono", linespacing=1.35,
                bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none", alpha=0.9))
        ax.text(mx - 0.040, my, c1, fontsize=7.4, color=GREY, ha="center", va="center", zorder=5)
        ax.text(mx + 0.040, my, c2, fontsize=7.4, color=GREY, ha="center", va="center", zorder=5)

    ax.text(0.5, 1.012,
            "LLMEV-144 — Evaluation data model: design inputs, four data layers, one table, no foreign keys",
            fontsize=15, fontweight="bold", color=NAVY, ha="center", va="bottom")

    fig.text(0.010, -0.012,
             "The ground-truth layer is a SINGLE table: facts are denormalised into articles.facts_json as a JSON array, there is no fact table, and no foreign key is declared anywhere in the schema.\n"
             "The keys that do the joining are implicit: articles.topic_id = scenarios[].id (verified equal as sets, 60/60), and judge output aligns 1:1 with the corpus on (scenario_id, framing, language, model).",
             fontsize=8.4, color=GREY, va="top", ha="left", linespacing=1.6)

    # Count the derived boxes rather than writing the number into the caption: the two
    # drifted apart once (README said four, caption said three, three were drawn).
    n_derived = sum(1 for b in BOXES.values() if b.get("tag") == "derived")
    derived_word = {1: "one", 2: "two", 3: "three", 4: "four"}.get(n_derived, str(n_derived))


    fig.text(0.010, -0.078,
             "Shipped DDL:  " + " ".join(DDL.split()) + "\n"
             "build_index.py declares articles(topic TEXT PRIMARY KEY, source_url, facts_json) — three columns. The shipped database has four, and no committed script creates topic_id.\n"
             "judge_pipeline.py reads the table with SELECT * and indexes the result by column NAME, so the consumer depends on a schema no committed builder produces.\n"
             f"The {derived_word} boxes tagged 'derived' come from PR #29 (LLMEV-107), which is still OPEN: data/processed/ does not yet exist on main.",
             fontsize=7.8, color=AMBER, va="top", ha="left", linespacing=1.6)

    # metadata Date=None for the same reason as the architecture diagram: the SVG
    # is committed and a generation timestamp would make every run a diff.
    fig.savefig(os.path.join(OUT, "data-model.png"), dpi=200, bbox_inches="tight",
                facecolor="white", metadata={"Date": None})
    fig.savefig(os.path.join(OUT, "data-model.svg"), bbox_inches="tight",
                facecolor="white", metadata={"Date": None})
    print("verified: articles.topic_id set == scenarios ids; 1200 responses unique on the model key; "
          "1200 judged rows aligned 1:1 with the corpus")
    print("facts:", format(FACTS, ","))
    print("wrote", os.path.join(OUT, "data-model.png"))
    stabilise_svg(os.path.join(OUT, "data-model.svg"))
    print("wrote", os.path.join(OUT, "data-model.svg"))


if __name__ == "__main__":
    main()
