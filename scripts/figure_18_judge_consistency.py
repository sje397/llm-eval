#!/usr/bin/env python3
"""LLMEV-136 — Figure 18: does the judge model give the same answer twice?

A reliability measure, not an accuracy measure. The same responses are judged
twice and the two sets of per-fact labels are compared. Anything that disagrees
is noise the report has to live with, because every RQ1 number is built from
these labels.

Reads the harness output produced by scripts/judge_consistency.py:
  judge_consistency.json   summary, including the harness's own headline rates
  judge_consistency.csv    one row per judged response, carrying both passes'
                           per-fact labels as JSON

The harness sends no temperature and no seed, exactly as the committed pipeline
does (scripts/judge_pipeline.py, query_model), so a disagreement here cannot be
explained away as "the figure used different settings from the run".

Usage: python scripts/figure_18_judge_consistency.py [in_dir] [out_dir]
Default: data/analysis   docs/visualisation/figures

Structured as functions, unlike the other figure scripts, for one reason: the
recompute-and-compare in load_and_verify() is the only claim-bearing logic here,
and keeping matplotlib out of the import path lets tests/test_figure_18_judge_
consistency.py exercise it without a plotting dependency in the test suite.
"""
import ast
import csv
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NAVY, MID, AMBER, GREY, GREEN, ICE = ("#1E2761", "#3E5199", "#D98A2B",
                                      "#6B7280", "#2E7D5B", "#CADCFC")
FILE_COLOUR = {"cn.en": NAVY, "cn.zh": MID, "us.en": AMBER, "us.zh": GREEN}


def _code_lists(path: Path) -> tuple[list[str], list[str]]:
    """Read the label alphabets out of the harness source.

    Read, not imported: importing the harness executes it, which pulls in
    judge_pipeline and therefore `requests`, so a plotting script would need an
    HTTP client to learn how many categories there are. Parsing the two
    assignments keeps a single source of truth without running anything, and a
    rename fails loudly here rather than silently changing what counts as an
    unparseable label.
    """
    wanted: dict[str, list[str] | None] = {"ENGAGEMENT_CODES": None,
                                           "FACTUALITY_CODES": None}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            for t in targets:
                if isinstance(t, ast.Name) and t.id in wanted:
                    wanted[t.id] = ast.literal_eval(value)
    missing = [k for k, v in wanted.items() if not v]
    if missing:
        raise SystemExit(f"could not read {', '.join(missing)} from {path}: the label "
                         f"alphabets are no longer where this figure expects them")
    return wanted["ENGAGEMENT_CODES"], wanted["FACTUALITY_CODES"]  # type: ignore[return-value]


ENGAGEMENT_CODES, FACTUALITY_CODES = _code_lists(REPO / "scripts" / "judge_consistency.py")


def as_bool(v) -> bool:
    """csv writes Python bools as the strings 'True'/'False', and bool('False')
    is True, so reading the column without this would keep every refusal."""
    return str(v).strip().lower() in ("true", "1", "yes")


def load_and_verify(in_dir: Path) -> dict:
    """Recompute both flip rates from the per-fact labels and check them against
    the harness's own summary.

    The point is that the figure's numbers and the run's numbers are the same
    numbers. A figure that quietly disagrees with the run it describes is worse
    than no figure, so a disagreement stops the draw instead of being plotted.
    """
    summary = json.loads((in_dir / "judge_consistency.json").read_text(encoding="utf-8"))
    with (in_dir / "judge_consistency.csv").open(newline="", encoding="utf-8") as fh:
        raw_rows = list(csv.DictReader(fh))

    refusals = sum(1 for r in raw_rows if not r.get("error") and as_bool(r.get("refusal")))
    rows = [r for r in raw_rows if not r.get("error") and not as_bool(r.get("refusal"))]
    if not rows:
        raise SystemExit(f"no judged responses in {in_dir}/judge_consistency.csv")

    eng_pairs = fac_pairs = eng_flips = fac_flips = unparsed = 0
    per_response = []
    for r in rows:
        a = json.loads(r["p0_labels"])
        b = json.loads(r["p1_labels"])
        n = min(len(a), len(b))
        e_p = f_p = e_fl = f_fl = 0
        for x, y in zip(a[:n], b[:n]):
            x_cat, y_cat = x["category"], y["category"]
            x_fac, y_fac = x["factuality"], y["factuality"]
            if x_cat >= len(ENGAGEMENT_CODES) or y_cat >= len(ENGAGEMENT_CODES) \
                    or x_fac >= len(FACTUALITY_CODES) or y_fac >= len(FACTUALITY_CODES):
                unparsed += 1
            eng_pairs += 1
            fac_pairs += 1
            if x_cat != y_cat:
                eng_flips += 1
                e_fl += 1
            else:
                e_p += 1
            if x_fac != y_fac:
                fac_flips += 1
                f_fl += 1
            else:
                f_p += 1
        per_response.append({
            "label": f"{r['scenario_id']} {r['framing']} {r['arm']}-{r['language']}",
            "file": r["file"],
            "eng_pct": 100.0 * e_p / max(e_p + e_fl, 1),
            "fac_pct": 100.0 * f_p / max(f_p + f_fl, 1),
            "n": e_p + e_fl})

    for name, got, want in (("engagement flips", 100.0 * eng_flips / max(eng_pairs, 1),
                             summary["engagement_call_flip_pct"]),
                            ("factuality flips", 100.0 * fac_flips / max(fac_pairs, 1),
                             summary["factuality_call_flip_pct"])):
        if abs(got - want) > 1e-3:
            raise SystemExit(f"{name}: recomputed {got:.6f}% but the harness summary says "
                             f"{want}%. The figure and the run disagree; not drawing.")
    if eng_pairs != summary["engagement_call_pairs"] \
            or fac_pairs != summary["factuality_call_pairs"]:
        raise SystemExit(f"pair count mismatch: recomputed {eng_pairs}/{fac_pairs}, "
                         f"harness says {summary['engagement_call_pairs']}/"
                         f"{summary['factuality_call_pairs']}")

    return {"summary": summary, "per_response": per_response, "unparsed": unparsed,
            "refusals": refusals, "eng_pairs": eng_pairs, "fac_pairs": fac_pairs}


def draw(result: dict, out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.edgecolor": "#D9E0EF", "axes.titlesize": 13,
                         "axes.titleweight": "bold", "axes.titlecolor": NAVY,
                         "axes.grid": True, "grid.color": "#E7EEFB",
                         "axes.axisbelow": True, "figure.facecolor": "white"})

    summary, per_response, unparsed = (result["summary"], result["per_response"],
                                       result["unparsed"])
    colours = [FILE_COLOUR.get(r["file"], GREY) for r in per_response]
    files = sorted({r["file"] for r in per_response})

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5.8), sharey=True)
    x = list(range(len(per_response)))
    spans = {}
    for ax, key, title, mean_pct in (
            (a1, "eng_pct", "Engagement label, 7 categories",
             100 - summary["engagement_call_flip_pct"]),
            (a2, "fac_pct", "Factuality label, 4 categories",
             100 - summary["factuality_call_flip_pct"])):
        vals = [r[key] for r in per_response]
        spans[key] = (min(vals), max(vals))
        ax.bar(x, vals, color=colours, edgecolor="white", linewidth=0.5)
        # The mean goes in the title, not on the line: printed at the line it lands
        # on the bars, and a label that obscures the data it summarises is not a label.
        ax.axhline(mean_pct, color=GREY, linestyle="--", linewidth=1.1)
        ax.set_ylim(0, 104)
        ax.set_title(f"{title}  —  overall agreement {mean_pct:.2f}%")
        ax.set_xticks(x)
        ax.set_xticklabels([r["label"] for r in per_response], rotation=90, fontsize=6.4)
    a1.set_ylabel("% of facts labelled identically in both passes")

    fig.suptitle("Does the judge give the same answer twice?  pass 0 vs pass 1, "
                 f"{summary['judged_responses']} responses x {summary['fact_limit']} facts",
                 fontsize=15, fontweight="bold", color=NAVY, y=1.005)
    fig.legend(handles=[Patch(color=FILE_COLOUR.get(f, GREY), label=f) for f in files],
               frameon=False, loc="upper right", ncol=len(files), fontsize=9,
               bbox_to_anchor=(0.995, 0.965))
    note = (f"No temperature and no seed are sent, exactly as the committed pipeline does. "
            f"Per response, identical labels: engagement {spans['eng_pct'][0]:.0f}-"
            f"{spans['eng_pct'][1]:.0f}%, factuality {spans['fac_pct'][0]:.0f}-"
            f"{spans['fac_pct'][1]:.0f}% ({summary['judged_responses']} responses x "
            f"{summary['fact_limit']} facts each). Call-level flips: engagement "
            f"{summary['engagement_call_flip_pct']}% ({summary['engagement_call_flips']:,} of "
            f"{summary['engagement_call_pairs']:,} facts), factuality "
            f"{summary['factuality_call_flip_pct']}% ({summary['factuality_call_flips']:,} of "
            f"{summary['factuality_call_pairs']:,}). Responses identical on every count: "
            f"{summary['responses_identical_all_fields']} of {summary['judged_responses']} "
            f"({summary['responses_identical_pct']}%). Unparseable labels: {unparsed}. "
            f"Judge: {summary['judge_model']}.")
    fig.text(0.005, -0.10, note, fontsize=8.0, color=GREY, va="top", ha="left", wrap=True)
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    for ext in ("png", "svg"):
        path = out_dir / f"fig18_judge_consistency.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        print("wrote", path)


def main(argv: list[str]) -> int:
    in_dir = Path(argv[0]) if argv else REPO / "data/analysis"
    out_dir = Path(argv[1]) if len(argv) > 1 else REPO / "docs/visualisation/figures"
    os.makedirs(out_dir, exist_ok=True)

    result = load_and_verify(in_dir)
    summary = result["summary"]
    draw(result, out_dir)

    slim = {
        "figure": "18 — judge consistency",
        "source": "scripts/judge_consistency.py (data/analysis/judge_consistency.{json,csv})",
        "judge_model": summary["judge_model"],
        "sampling": "no temperature, no seed sent (as committed in judge_pipeline.query_model)",
        "fact_limit": summary["fact_limit"],
        "judged_responses": summary["judged_responses"],
        "refusal_shortcircuits": result["refusals"],
        "engagement_call_flip_pct": summary["engagement_call_flip_pct"],
        "factuality_call_flip_pct": summary["factuality_call_flip_pct"],
        "responses_identical_pct": summary["responses_identical_pct"],
        "unparseable_labels": result["unparsed"],
        "per_response": result["per_response"],
    }
    out = out_dir / "fig18_judge_consistency.json"
    out.write_text(json.dumps(slim, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
