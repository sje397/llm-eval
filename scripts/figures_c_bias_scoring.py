#!/usr/bin/env python3
"""LLMEV-108 — Section C figures 12 and 15, from the LLMEV-106 classifier output.

Covers both arms: Claude Sonnet 5 (evaluation.us.*.csv) and DeepSeek V4 Pro
(evaluation.cn.*.csv), 300 rows per file, four files, 60,000 fact classifications.
LLMEV-106 completed on 2026-10-05, so the DeepSeek arm is no longer excluded.

Input schema (one row per response; counts are per ground-truth fact, ~50 per response):
  model, language, scenario_id, framing,
  count_engagement_{full,partial,non_answer,deflection,not_mentioned,refusal,other},
  weight_engagement_{...}, count_facts_{true,false,not_answered,other}, weight_facts_{...}

Usage:   python scripts/figures_c_bias_scoring.py [eval_glob] [out_dir]
Default: 'data/evaluation.*.csv'  figures/
"""
import sys, os
EVAL_GLOB = sys.argv[1] if len(sys.argv) > 1 else "data/evaluation.*.csv"
OUT = sys.argv[2] if len(sys.argv) > 2 else "figures"
os.makedirs(OUT, exist_ok=True)
import pandas as pd, glob, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np
NAVY,MID,ICE,AMBER,GREY,INK,GREEN="#1E2761","#3E5199","#CADCFC","#D98A2B","#6B7280","#1A1F36","#2E7D5B"
PALE="#8A9BD1"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.edgecolor":"#D9E0EF",
 "axes.titlesize":13,"axes.titleweight":"bold","axes.titlecolor":NAVY,"axes.grid":True,
 "grid.color":"#E7EEFB","axes.axisbelow":True,"figure.facecolor":"white","axes.facecolor":"white"})

FILES = sorted(glob.glob(EVAL_GLOB))
df = pd.concat([pd.read_csv(f) for f in FILES])
assert len(df) == 300 * len(FILES), f"expected 300 rows per file, got {len(df)} across {len(FILES)} files"

MODEL = {"claude-sonnet-5": "Claude", "deepseek-v4-pro": "DeepSeek"}
LANG = {"en": "English", "zh": "Mandarin"}
order = sorted(set(zip(df["model"], df["language"])))
x = [f"{MODEL.get(m, m)}\n{LANG.get(l, l)}" for m, l in order]
df["_cell"] = list(zip(df["model"], df["language"]))

# ---- fig 12: six-category engagement mix, same style as fig 9 ----
ENG = ["full","partial","non_answer","deflection","not_mentioned","refusal"]
lab = {"full":"Full engagement","partial":"Partial engagement","non_answer":"Non-answer",
       "deflection":"Deflection","not_mentioned":"Not mentioned","refusal":"Refusal"}
col = {"full":NAVY,"partial":MID,"non_answer":PALE,"deflection":GREY,"not_mentioned":ICE,"refusal":AMBER}
g = df.groupby("_cell")[[f"count_engagement_{c}" for c in ENG + ["other"]]].sum().reindex(order)
g = g.div(g.sum(axis=1), axis=0) * 100
fig, ax = plt.subplots(figsize=(11, 5.4))
bottom = np.zeros(len(order))
for c in ENG:
    v = g[f"count_engagement_{c}"].values
    b = ax.bar(x, v, 0.6, bottom=bottom, color=col[c], edgecolor="white", linewidth=1, label=lab[c])
    for i, (r, val) in enumerate(zip(b, v)):
        if val >= 4:
            ax.text(r.get_x()+r.get_width()/2, bottom[i]+val/2, f"{val:.0f}%", ha="center", va="center",
                    fontsize=10, fontweight="bold", color="white" if c in ("full","partial") else NAVY)
    bottom += v
ax.set_ylabel("Share of evaluated facts (%)"); ax.set_ylim(0,100)
ax.set_title("Fig 12 — Six-category engagement mix (LLMEV-104 rubric)")
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5,-0.10), ncol=6, fontsize=9)
ax.text(0,-0.22,"Claude Sonnet 5 and DeepSeek V4 Pro: 300 responses × 50 ground-truth facts per language "
                "(60,000 fact classifications). Six categories per the LLMEV-104 rubric; 'other' is 0.0%.",
        transform=ax.transAxes, fontsize=8.5, color=GREY)
fig.tight_layout()
for ext in ("png","svg"): fig.savefig(f"{OUT}/fig12_six_category_engagement_mix.{ext}",dpi=200,bbox_inches="tight")

# ---- fig 15: factual accuracy by language, both models ----
FAC = ["true","false","not_answered","other"]
g2 = df.groupby("_cell")[[f"count_facts_{c}" for c in FAC]].sum().reindex(order)
g2p = g2.div(g2.sum(axis=1), axis=0) * 100
acc = g2["count_facts_true"] / (g2["count_facts_true"] + g2["count_facts_false"]) * 100
fig, ax = plt.subplots(figsize=(11, 5.4))
bottom = np.zeros(len(order))
for c, cc, l in zip(("true","false","not_answered"), [GREEN, AMBER, ICE],
                    ["Verified true","Verified false","Not addressed"]):
    v = g2p[f"count_facts_{c}"].values
    bb = ax.bar(x, v, 0.6, bottom=bottom, color=cc, edgecolor="white", linewidth=1, label=l)
    for i, (r, val) in enumerate(zip(bb, v)):
        if val >= 3:
            ax.text(r.get_x()+r.get_width()/2, bottom[i]+val/2, f"{val:.1f}%", ha="center", va="center",
                    fontsize=10, fontweight="bold", color="white" if c == "true" else NAVY)
    bottom += v
for i, a in enumerate(acc.values):
    ax.text(i, 103, f"{a:.1f}% accurate\nwhen addressed", ha="center", va="bottom",
            fontsize=9.5, fontweight="bold", color=GREEN)
ax.set_ylabel("Share of ground-truth facts (%)"); ax.set_ylim(0,116)
ax.set_title("Fig 15 — Factual accuracy by language (RQ2)")
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5,-0.10), ncol=3, fontsize=9)
ax.text(0,-0.22,"Claude Sonnet 5 and DeepSeek V4 Pro: 300 responses × 50 ground-truth facts per language. "
                "Accuracy = verified true ÷ (verified true + verified false).",
        transform=ax.transAxes, fontsize=8.5, color=GREY)
fig.tight_layout()
for ext in ("png","svg"): fig.savefig(f"{OUT}/fig15_factual_accuracy_by_language.{ext}",dpi=200,bbox_inches="tight")

# ---- numbers, so a run can be checked without reading the images ----
# .at, not .loc: the index is (model, language), and a tuple key passed to .loc
# is read as multi-axis indexing rather than a single MultiIndex label.
print("engagement mix (% of evaluated facts)")
print(f"  {'cell':<18}" + "".join(f"{c:>14}" for c in ENG))
for cell in order:
    name = f"{MODEL.get(cell[0], cell[0])}/{cell[1]}"
    print(f"  {name:<18}" + "".join(f"{g.at[cell, f'count_engagement_{c}']:>13.1f}%" for c in ENG))
print("\nfactual accuracy (% of ground-truth facts)")
print(f"  {'cell':<18}{'true':>8}{'false':>8}{'not addressed':>15}{'accurate when addressed':>26}")
for cell in order:
    name = f"{MODEL.get(cell[0], cell[0])}/{cell[1]}"
    print(f"  {name:<18}{g2p.at[cell,'count_facts_true']:>7.1f}%{g2p.at[cell,'count_facts_false']:>7.1f}%"
          f"{g2p.at[cell,'count_facts_not_answered']:>14.1f}%{acc.at[cell]:>25.1f}%")
