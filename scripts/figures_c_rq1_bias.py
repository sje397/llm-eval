#!/usr/bin/env python3
"""LLMEV-108 — Section C figures 10, 11, 13 and 14, from the LLMEV-107 export.

  10  bias score by model and language      grouped bar   rq1_aggregated_metrics
  11  bias score distribution               violin        rq1_response_scores
  13  bias score by framing                 grouped bar   rq1_aggregated_metrics
  14  event-level bias heatmap (60 x 4)     heatmap       rq1_response_scores

Bias score is the project's 0-1 Information Disclosure Score
(docs/score-mapping-methodology.md): Full 1.00, Partial 0.75, Non-Answer 0.50,
Deflection 0.25, Not Mentioned 0.00, Refusal 0.00, averaged over the facts scored
for that response. Higher = more disclosed. It is the quantity LLMEV-107 compares:
the difference of two group means is that file's `bias_score_gap`. Restriction score
is 1 - bias score, so a restriction figure would be this one mirrored.

Figures 10, 13 and 14 reuse the layouts of 4, 3 and 5 respectively (spec §5), with the
scored measure in place of non-response rate. The four cells stay inside the deck's two
hues: Claude in mid blue, DeepSeek in navy, with English drawn at alpha 0.55 and
Mandarin at 1.0 (English lighter, Mandarin darker). Gold is not used here.

Inputs are Romit's LLMEV-107 export (PR #29). Until that merges, point the first
argument at a checkout of its data/processed directory.

Usage:   python scripts/figures_c_rq1_bias.py [processed_dir] [scenarios.json] [out_dir]
Default: data/processed  data/scenarios.json  figures/
Output:  figNN_*.png and .svg at 200 dpi
Deps:    pandas, numpy, matplotlib
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

PROC = sys.argv[1] if len(sys.argv) > 1 else "data/processed"
SCEN = sys.argv[2] if len(sys.argv) > 2 else "data/scenarios.json"
OUT = sys.argv[3] if len(sys.argv) > 3 else "figures"
os.makedirs(OUT, exist_ok=True)

# ---------- DTF palette (must match the deck) ----------
NAVY, BLUE, GOLD, GREY, INK = "#1E2761", "#3E5199", "#D98A2B", "#6B7280", "#1A1F36"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.edgecolor": "#D9E0EF", "axes.labelcolor": INK,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
    "text.color": INK, "xtick.color": "#5A6B7A", "ytick.color": "#5A6B7A",
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.grid": True, "grid.color": "#E7EEFB", "grid.linewidth": 0.8,
    "axes.axisbelow": True,
})

CELLS = [("claude-sonnet-5", "en"), ("claude-sonnet-5", "zh"),
         ("deepseek-v4-pro", "en"), ("deepseek-v4-pro", "zh")]
MODEL_SHORT = {"claude-sonnet-5": "Claude", "deepseek-v4-pro": "DeepSeek"}
LANG_SHORT = {"en": "English", "zh": "Mandarin"}
CELL_LABEL = [f"{MODEL_SHORT[m]}\n{LANG_SHORT[l]}" for m, l in CELLS]
# Claude = mid blue, DeepSeek = navy; English lighter, Mandarin darker.
CELL_COLOR = [BLUE, BLUE, NAVY, NAVY]
CELL_ALPHA = [0.55, 1.0, 0.55, 1.0]
CELL_LEGEND = [f"{MODEL_SHORT[m]} {LANG_SHORT[l]}" for m, l in CELLS]
FRAMINGS = ["framing_a", "framing_b", "framing_c", "framing_d", "framing_e"]
FRAMING_LABEL = {"framing_a": "A\nTell me about", "framing_b": "B\nWhat led up to",
                 "framing_c": "C\nWhat do you think", "framing_d": "D\nDescribe the politics",
                 "framing_e": "E\nViewed today"}
MEASURE = "disclosure_score"


def save(fig, name):
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  wrote", name)


def note(ax, text, y=-0.14):
    ax.text(0, y, text, transform=ax.transAxes, fontsize=8.5, color=GREY)


# ---------- inputs ----------
rs = pd.read_csv(os.path.join(PROC, "rq1_response_scores.csv"))
ag = pd.read_csv(os.path.join(PROC, "rq1_aggregated_metrics.csv"))
if len(rs) != 1200:
    sys.exit(f"expected 1,200 response rows, found {len(rs)}")
if set(rs["model"]) != set(MODEL_SHORT) or set(rs["language"]) != {"en", "zh"}:
    sys.exit("unexpected model or language values in rq1_response_scores.csv")
if not np.allclose(rs["disclosure_score"] + rs["restriction_score"], 1.0, atol=1e-9):
    sys.exit("disclosure + restriction != 1: the score mapping has changed, re-read it first")
counts = rs.groupby(["model", "language"]).size().to_dict()
if set(counts.values()) != {300}:
    sys.exit(f"expected 300 responses per cell, found {sorted(set(counts.values()))}")
agg_all = ag[ag["topic_origin"] == "All"]
if len(agg_all) != 20:
    sys.exit(f"expected 20 aggregated rows with topic_origin=All, found {len(agg_all)}")

names = {}
if os.path.exists(SCEN):
    names = {s["id"]: s["event"]["en"]
             for s in json.load(open(SCEN, encoding="utf-8"))["scenarios"]}

# Cell means from both files. Figures 10 and 13 read the aggregated file, so this
# cross-check is what stops a mis-shaped aggregate from being plotted silently.
mean_from_rs = rs.groupby(["model", "language"])[MEASURE].mean()
mean_from_ag = {}
for (m, l) in CELLS:
    d = agg_all[(agg_all["model"] == m) & (agg_all["language"] == l)]
    mean_from_ag[(m, l)] = float(np.average(d["mean_disclosure_score"], weights=d["sample_size"]))
    if abs(mean_from_ag[(m, l)] - mean_from_rs[(m, l)]) > 1e-9:
        sys.exit(f"aggregated and response files disagree for {m}/{l}")

print("bias score (disclosure), cell means:")
for (m, l) in CELLS:
    print(f"  {MODEL_SHORT[m]:8s} {LANG_SHORT[l]:8s} {mean_from_ag[(m, l)]:.4f}")


# =====================================================
# 10 — bias score by model x language (fig 4 layout)
# =====================================================
vals = [mean_from_ag[c] for c in CELLS]
fig, ax = plt.subplots(figsize=(7.6, 4.8))
for rect, v, a in zip(ax.bar(CELL_LABEL, vals, 0.6, color=CELL_COLOR,
                             edgecolor="white", linewidth=1), vals, CELL_ALPHA):
    rect.set_alpha(a)
    ax.annotate(f"{v:.3f}", (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                textcoords="offset points", xytext=(0, 4), ha="center", fontsize=10,
                color="#5A6B7A")
ax.set_ylabel("Bias score (1 = fully disclosed)")
ax.set_title("Fig 10 — RQ4: Bias score by model × language")
ax.set_ylim(0, max(vals) * 1.3 + 0.02)
note(ax, "n = 300 responses per bar. 0.0 = every scored fact withheld; 1.0 = every scored "
         "fact disclosed.\nEnglish bars are drawn lighter than Mandarin.", y=-0.20)
save(fig, "fig10_bias_score_by_model_language")


# =====================================================
# 11 — bias score distribution (violin)
# =====================================================
data = [rs[(rs["model"] == m) & (rs["language"] == l)][MEASURE].to_numpy()
        for m, l in CELLS]
fig, ax = plt.subplots(figsize=(9.6, 5))
parts = ax.violinplot(data, positions=range(len(CELLS)), widths=0.72,
                      showextrema=False, showmedians=False)
for body, c, a in zip(parts["bodies"], CELL_COLOR, CELL_ALPHA):
    body.set_facecolor(c)
    body.set_alpha(a)
    body.set_edgecolor("white")
    body.set_linewidth(1)
for i, v in enumerate(data):
    med = float(np.median(v))
    # white on the dark bodies, navy on the light ones, or the marker disappears
    ax.plot([i - 0.15, i + 0.15], [med, med], color="white" if CELL_ALPHA[i] == 1.0 else NAVY,
            linewidth=2, zorder=4)
    ax.annotate(f"median {med:.3f}", (i, med), textcoords="offset points",
                xytext=(0, 11), ha="center", fontsize=9, color=INK, zorder=5,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=1.5))
ax.set_xticks(range(len(CELLS)))
ax.set_xticklabels(CELL_LABEL)
ax.set_ylabel("Bias score per response (1 = fully disclosed)")
ax.set_ylim(-0.02, 1.02)
ax.set_title("Fig 11 — Bias score distribution by model × language")
note(ax, "n = 300 responses per cell. Each response is the mean of its 50 scored facts, "
         "so the spread is between responses, not between facts.")
save(fig, "fig11_bias_score_distribution")


# =====================================================
# 13 — bias score by framing (fig 3 layout, four cells)
# =====================================================
x = np.arange(len(FRAMINGS))
width = 0.2
fig, ax = plt.subplots(figsize=(11.5, 5))
top = 0.0
for j, (m, l) in enumerate(CELLS):
    d = agg_all[(agg_all["model"] == m) & (agg_all["language"] == l)]
    lookup = dict(zip(d["framing"], d["mean_disclosure_score"]))
    vals13 = [float(lookup[f]) for f in FRAMINGS]
    top = max(top, max(vals13))
    bb = ax.bar(x + (j - 1.5) * width, vals13, width, color=CELL_COLOR[j],
                edgecolor="white", linewidth=0.8, label=CELL_LEGEND[j], alpha=CELL_ALPHA[j])
    for rect, v in zip(bb, vals13):
        ax.annotate(f"{v:.2f}", (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                    textcoords="offset points", xytext=(0, 3), ha="center",
                    fontsize=7.5, color="#5A6B7A")
ax.set_xticks(x)
ax.set_xticklabels([FRAMING_LABEL[f] for f in FRAMINGS], fontsize=9)
ax.set_ylabel("Bias score (1 = fully disclosed)")
ax.set_ylim(0, top * 1.3 + 0.02)
ax.set_title("Fig 13 — RQ3: Bias score by prompt framing")
ax.legend(frameon=False, loc="upper right", ncol=2, fontsize=9)
note(ax, "n = 60 prompts per bar, all 60 events and both origins pooled.", y=-0.19)
save(fig, "fig13_bias_score_by_framing")


# =====================================================
# 14 — event-level bias heatmap, 60 x 4 (fig 5 layout)
# =====================================================
scen_ids = sorted(rs["scenario_id"].unique(), key=lambda s: (s[:2], int(s[3:])))
piv = rs.pivot_table(index="scenario_id", columns=["model", "language"],
                     values=MEASURE, aggfunc="mean")
mat = np.array([[piv.loc[sid, c] for c in CELLS] for sid in scen_ids], dtype=float)
cmap = LinearSegmentedColormap.from_list("bias", ["#F5F7FD", "#8A9BD1", BLUE, NAVY])
fig, ax = plt.subplots(figsize=(7.6, 13))
im = ax.imshow(mat, cmap=cmap, aspect="auto", vmin=0.0, vmax=1.0)
ax.set_xticks(range(len(CELLS)))
ax.set_xticklabels(["Claude\nEN", "Claude\nZH", "DeepSeek\nEN", "DeepSeek\nZH"], fontsize=10)
ax.set_yticks(range(len(scen_ids)))
ax.set_yticklabels([f"{s}  {(names.get(s, '')[:34] + '…') if len(names.get(s, '')) > 35 else names.get(s, '')}"
                    for s in scen_ids], fontsize=7.5)
for i in range(len(scen_ids)):
    for j in range(len(CELLS)):
        ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=7,
                color="white" if mat[i, j] > 0.55 else NAVY)
ax.set_title("Fig 14 — Event-level bias score (60 events × 4 combinations)", pad=14)
ax.grid(False)
cb = fig.colorbar(im, ax=ax, shrink=0.32, pad=0.02)
cb.set_label("Bias score, mean of 5 framings", fontsize=9)
note(ax, "Brighter = more disclosed, on the same 0-1 scale as figures 10 and 13.\n"
         f"Cell means run {mat.min():.2f} to {mat.max():.2f} across the 240 combinations.",
     y=-0.055)
save(fig, "fig14_event_bias_heatmap")

print("\nframing x cell bias score (from rq1_aggregated_metrics):")
for f in FRAMINGS:
    row = []
    for (m, l) in CELLS:
        d = agg_all[(agg_all["model"] == m) & (agg_all["language"] == l) &
                    (agg_all["framing"] == f)]
        row.append(f"{float(d['mean_disclosure_score'].iloc[0]):.4f}")
    print(f"  {f}  " + "  ".join(row))
print("\nper-cell distribution (from rq1_response_scores):")
for i, (m, l) in enumerate(CELLS):
    v = data[i]
    print(f"  {MODEL_SHORT[m]:8s} {LANG_SHORT[l]:8s} n={v.size} median={np.median(v):.4f} "
          f"p10={np.percentile(v, 10):.4f} p90={np.percentile(v, 90):.4f} "
          f"min={v.min():.4f} max={v.max():.4f}")
print(f"\nscenario cells: min {mat.min():.4f}  max {mat.max():.4f}  (240 combinations)")
