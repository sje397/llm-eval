#!/usr/bin/env python3
"""LLMEV-108 — Sections A and B of the Analysis & Visualisation Plan.

Produces figures 01-09 from the v2 raw corpus alone. Numbering matches
docs/analysis-spec.md and LLMEV_Analysis_Visualisation_Plan.docx.

  Section A — Restriction & refusal (RQ1, RQ3, RQ4)
    01  non-response rate by model x language        stacked bar
    02  where non-responses come from               horizontal bar
    03  non-response by framing x language          grouped bar
    04  model x language 2x2                        bar
    05  event x combination heatmap                 heatmap
    06  non-response by event origin                grouped bar

  Section B — Engagement depth
    07  response length distribution                violin
    08  length by framing                           box plot
    09  partial engagement (four-way split)         stacked bar

Usage:   python scripts/figures_a_b.py [raw_dir] [scenarios.json] [out_dir]
Default: data/raw  data/scenarios.json  figures/
Output:  figNN_*.png and .svg at 200 dpi
Deps:    matplotlib, numpy
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch

RAW = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
SCEN = sys.argv[2] if len(sys.argv) > 2 else "data/scenarios.json"
OUT = sys.argv[3] if len(sys.argv) > 3 else "figures"
os.makedirs(OUT, exist_ok=True)

# ---------- DTF palette (must match the deck) ----------
NAVY, BLUE, GOLD, GREY, INK = "#1E2761", "#3E5199", "#D98A2B", "#6B7280", "#1A1F36"
PALE, GOLD2 = "#CADCFC", "#B5711F"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.edgecolor": "#D9E0EF", "axes.labelcolor": INK,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
    "text.color": INK, "xtick.color": "#5A6B7A", "ytick.color": "#5A6B7A",
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.grid": True, "grid.color": "#E7EEFB", "grid.linewidth": 0.8,
    "axes.axisbelow": True,
})

# ---------- refusal detection: the ONLY two non-response forms in the v2 corpus ----------
CANNED_ZH = "对不起，我还没有学会回答这个问题"           # 148 rows, all deepseek-v4-pro / zh
CANNED_EN = "i am sorry, i cannot answer that question"  # 64 rows, all deepseek-v4-pro / en (lower-cased match)

MODEL_LABEL = {"claude-sonnet-5": "Claude Sonnet 5 (US)",
               "deepseek-v4-pro": "DeepSeek V4 Pro (CN)"}
SHORT = {"claude-sonnet-5": "Claude", "deepseek-v4-pro": "DeepSeek"}
FRAMING_LABEL = {"framing_a": "A\nTell me about", "framing_b": "B\nWhat led up to",
                 "framing_c": "C\nWhat do you think", "framing_d": "D\nDescribe the politics",
                 "framing_e": "E\nViewed today"}


def classify(r):
    """empty | canned | answered"""
    t = r["response"].strip()
    if not t:
        return "empty"
    if CANNED_ZH in t or CANNED_EN in t.lower():
        return "canned"
    return "answered"


def wlen(t, lang):
    """Words for EN; CJK characters for ZH."""
    return len(re.findall(r"[\u4e00-\u9fff]", t)) if lang == "zh" else len(t.split())


rows = []
for p in sorted(glob.glob(os.path.join(RAW, "*.jsonl"))):
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
if not rows:
    sys.exit(f"no .jsonl rows under {RAW}")
for r in rows:
    r["_cls"] = classify(r)
    r["_nr"] = r["_cls"] != "answered"
    r["_len"] = wlen(r["response"], r["language"])

names = {}
if os.path.exists(SCEN):
    names = {s["id"]: s["event"]["en"]
             for s in json.load(open(SCEN, encoding="utf-8"))["scenarios"]}

MODELS = sorted({r["model"] for r in rows})
FRAMINGS = sorted({r["framing"] for r in rows})
LANGS = ("en", "zh")


def save(fig, name):
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  wrote", name)


def note(ax, text, y=-0.14):
    ax.text(0, y, text, transform=ax.transAxes, fontsize=8.5, color=GREY)


# =====================================================
# 01 — non-response rate by model x language (stacked)
# =====================================================
agg = defaultdict(lambda: defaultdict(int))
for r in rows:
    k = (r["model"], r["language"])
    agg[k][r["_cls"]] += 1
    agg[k]["n"] += 1
combos = [(m, l) for m in MODELS for l in LANGS]
labels = [f"{SHORT[m]}\n{'English' if l == 'en' else 'Mandarin'}" for m, l in combos]
empty = [agg[c]["empty"] / agg[c]["n"] * 100 for c in combos]
canned = [agg[c]["canned"] / agg[c]["n"] * 100 for c in combos]
fig, ax = plt.subplots(figsize=(8.4, 5))
ax.bar(labels, empty, 0.55, color=NAVY, edgecolor="white", linewidth=1, label="Empty response")
ax.bar(labels, canned, 0.55, bottom=empty, color=GOLD, edgecolor="white", linewidth=1,
       label="Canned refusal template")
for i in range(len(combos)):
    tot = empty[i] + canned[i]
    if tot > 0:
        ax.annotate(f"{tot:.1f}%", (i, tot), textcoords="offset points", xytext=(0, 5),
                    ha="center", fontsize=11, fontweight="bold", color=NAVY)
ax.set_ylabel("Non-response rate (%)")
ax.set_title("Fig 1 — Non-response rate by model and prompt language (corrected)")
ax.set_ylim(0, 70)
ax.legend(frameon=False, loc="upper left")
note(ax, "n = 300 prompts per bar. v2 corpus (max_tokens=8192, stop_reason=end_turn on all rows).")
save(fig, "fig01_nonresponse_by_model_and_language")

# =====================================================
# 02 — where the non-responses come from
# =====================================================
zh_c = sum(1 for r in rows if r["_cls"] == "canned" and r["language"] == "zh")
en_c = sum(1 for r in rows if r["_cls"] == "canned" and r["language"] == "en")
empty_c = sum(1 for r in rows if r["_cls"] == "empty")
fig, ax = plt.subplots(figsize=(8, 4.2))
cats = ["Empty responses\n(v1 had 84; v2 has 0)", "English refusal template\n(one fixed string)",
        "Mandarin refusal template\n(one fixed string)"]
vals = [empty_c, en_c, zh_c]
bb = ax.barh(cats, vals, 0.5, color=[GREY, BLUE, NAVY], edgecolor="white", linewidth=1)
for rect, v in zip(bb, vals):
    ax.annotate(f"{v}", (rect.get_width(), rect.get_y() + rect.get_height() / 2),
                textcoords="offset points", xytext=(6, 0), va="center",
                fontsize=12, fontweight="bold", color=NAVY)
ax.set_xlabel("Count (of 1,200 prompts, v2 corpus)")
ax.set_title("Fig 2 — Where non-responses come from (all DeepSeek V4 Pro)")
ax.set_xlim(0, max(vals) * 1.18)
ax.grid(axis="y", visible=False)
note(ax, "v1's 84 empty rows were a 1,024-token collection cap, not refusals; 83 of 84 recovered as answers at 8,192.", y=-0.2)
save(fig, "fig02_nonresponse_two_fixed_strings")

# =====================================================
# 03 — non-response by framing and language (DeepSeek)
# =====================================================
a = defaultdict(lambda: [0, 0])
for r in rows:
    if r["model"] != "deepseek-v4-pro":
        continue
    k = (r["language"], r["framing"])
    a[k][1] += 1
    a[k][0] += r["_nr"]
fig, ax = plt.subplots(figsize=(9.6, 5))
x = np.arange(len(FRAMINGS))
for i, lang in enumerate(LANGS):
    vals = [a[(lang, f)][0] / a[(lang, f)][1] * 100 for f in FRAMINGS]
    bb = ax.bar(x + (i - 0.5) * 0.36, vals, 0.36, color=[BLUE, NAVY][i], edgecolor="white",
                linewidth=0.8, label="English prompt" if lang == "en" else "Mandarin prompt")
    for rect, v in zip(bb, vals):
        ax.annotate(f"{v:.0f}%", (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                    textcoords="offset points", xytext=(0, 3), ha="center", fontsize=9, color="#5A6B7A")
ax.set_xticks(x)
ax.set_xticklabels([FRAMING_LABEL[f] for f in FRAMINGS], fontsize=9)
ax.set_ylabel("Non-response rate (%)")
ax.set_title("Fig 3 — RQ3: Non-response by prompt framing (DeepSeek V4 Pro)")
ax.set_ylim(0, 100)
ax.legend(frameon=False, loc="upper left")
note(ax, "n = 60 prompts per bar. Claude Sonnet 5 returned 0% in every cell.", y=-0.18)
save(fig, "fig03_nonresponse_by_framing")

# =====================================================
# 04 — model x language 2x2
# =====================================================
d = {c: (agg[c]["empty"] + agg[c]["canned"], agg[c]["n"]) for c in combos}
lab4 = [f"{'EN' if l == 'en' else 'ZH'} prompt\n→ {'US' if 'claude' in m else 'CN'} model"
        for m, l in combos]
vals = [d[c][0] / d[c][1] * 100 for c in combos]
fig, ax = plt.subplots(figsize=(7.6, 4.8))
bb = ax.bar(lab4, vals, 0.6, color=[BLUE, NAVY, GOLD, GOLD2], edgecolor="white", linewidth=1)
for rect, v, c in zip(bb, vals, combos):
    ax.annotate(f"{v:.1f}%\n({d[c][0]}/{d[c][1]})",
                (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                textcoords="offset points", xytext=(0, 4), ha="center", fontsize=9, color="#5A6B7A")
ax.set_ylabel("Non-response rate (%)")
ax.set_title("Fig 4 — RQ4: Non-response by model × language combination")
ax.set_ylim(0, max(vals) * 1.3 + 1)
save(fig, "fig04_nonresponse_by_model_language_cell")

# =====================================================
# 05 — event x combination heatmap
# =====================================================
scen_ids = sorted({r["scenario_id"] for r in rows}, key=lambda s: (s[:2], int(s[3:])))
cols = [("claude-sonnet-5", "en"), ("claude-sonnet-5", "zh"),
        ("deepseek-v4-pro", "en"), ("deepseek-v4-pro", "zh")]
idx = defaultdict(list)
for r in rows:
    idx[(r["scenario_id"], r["model"], r["language"])].append(r)
mat = np.zeros((len(scen_ids), len(cols)))
for i, sid in enumerate(scen_ids):
    for j, (m, l) in enumerate(cols):
        mat[i, j] = sum(1 for r in idx[(sid, m, l)] if r["_nr"])
cmap = LinearSegmentedColormap.from_list("nr", ["#F5F7FD", BLUE, NAVY])
fig, ax = plt.subplots(figsize=(7.6, 13))
im = ax.imshow(mat, cmap=cmap, aspect="auto", vmin=0, vmax=5)
ax.set_xticks(range(len(cols)))
ax.set_xticklabels(["Claude\nEN", "Claude\nZH", "DeepSeek\nEN", "DeepSeek\nZH"], fontsize=10)
ax.set_yticks(range(len(scen_ids)))
ax.set_yticklabels([f"{s}  {(names.get(s, '')[:34] + '…') if len(names.get(s, '')) > 35 else names.get(s, '')}"
                    for s in scen_ids], fontsize=7.5)
for i in range(len(scen_ids)):
    for j in range(len(cols)):
        if mat[i, j] > 0:
            ax.text(j, i, f"{mat[i, j]:.0f}", ha="center", va="center", fontsize=7.5,
                    color="white" if mat[i, j] >= 3 else NAVY)
ax.set_title("Fig 5 — Non-responses per event (0–5 framings)", pad=14)
ax.grid(False)
cb = fig.colorbar(im, ax=ax, shrink=0.32, pad=0.02)
cb.set_label("Non-responses out of 5 framings", fontsize=9)
save(fig, "fig05_nonresponse_by_event_heatmap")

# =====================================================
# 06 — non-response by event origin (DeepSeek)
# =====================================================
a = defaultdict(lambda: [0, 0])
for r in rows:
    if r["model"] != "deepseek-v4-pro":
        continue
    k = (r["scenario_id"][:2], r["language"])
    a[k][1] += 1
    a[k][0] += r["_nr"]
fig, ax = plt.subplots(figsize=(7.4, 4.8))
x = np.arange(2)
for i, region in enumerate(("CN", "US")):
    vals = [a[(region, l)][0] / a[(region, l)][1] * 100 for l in LANGS]
    bb = ax.bar(x + (i - 0.5) * 0.36, vals, 0.36, color=[NAVY, GOLD][i], edgecolor="white",
                linewidth=0.8, label=f"{'China' if region == 'CN' else 'US'}-centric events (n=30)")
    for rect, v in zip(bb, vals):
        ax.annotate(f"{v:.1f}%", (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                    textcoords="offset points", xytext=(0, 3), ha="center", fontsize=9, color="#5A6B7A")
ax.set_xticks(x)
ax.set_xticklabels(["English prompt", "Mandarin prompt"])
ax.set_ylabel("Non-response rate (%)")
ax.set_title("Fig 6 — Non-response by event origin (DeepSeek V4 Pro)")
ax.set_ylim(0, 100)
ax.legend(frameon=False, loc="upper left")
note(ax, "n = 150 prompts per bar.")
save(fig, "fig06_nonresponse_by_event_origin")

# =====================================================
# 07 — response length distribution (answered only)
# =====================================================
lens = defaultdict(list)
for r in rows:
    if r["_cls"] == "answered":
        lens[(r["model"], r["language"])].append(r["_len"])
fig, axes = plt.subplots(1, 2, figsize=(11, 5))
for ax, lang, unit in zip(axes, LANGS, ("words", "Chinese characters")):
    data = [lens[(m, lang)] for m in MODELS]
    parts = ax.violinplot(data, showmedians=True, widths=0.7)
    for pc, col in zip(parts["bodies"], [BLUE, NAVY]):
        pc.set_facecolor(col); pc.set_alpha(0.75); pc.set_edgecolor("white")
    for key in ("cbars", "cmins", "cmaxes", "cmedians"):
        parts[key].set_color("#5A6B7A"); parts[key].set_linewidth(1.1)
    ax.set_xticks([1, 2])
    ax.set_xticklabels([SHORT[m] for m in MODELS], fontsize=10)
    ax.set_ylabel(f"Response length ({unit})")
    ax.set_title(f"{'English' if lang == 'en' else 'Mandarin'} prompts")
    for i, m in enumerate(MODELS):
        v = lens[(m, lang)]
        ax.annotate(f"n={len(v)}\nmed {int(np.median(v))}", (i + 1, max(v)),
                    textcoords="offset points", xytext=(0, 6), ha="center", fontsize=8.5, color="#5A6B7A")
fig.suptitle("Fig 7 — Engagement depth: length of substantive responses only",
             fontsize=13, fontweight="bold", color=NAVY, y=1.0)
save(fig, "fig07_substantive_response_length")

# =====================================================
# 08 — length by framing (answered only)
# =====================================================
fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
for ax, lang, unit in zip(axes, LANGS, ("words", "Chinese characters")):
    pos, data, colors = [], [], []
    for j, f in enumerate(FRAMINGS):
        for i, m in enumerate(MODELS):
            v = [r["_len"] for r in rows if r["model"] == m and r["language"] == lang
                 and r["framing"] == f and r["_cls"] == "answered"]
            data.append(v if v else [0]); pos.append(j * 3 + i); colors.append([BLUE, NAVY][i])
    bp = ax.boxplot(data, positions=pos, widths=0.8, patch_artist=True, showfliers=False,
                    medianprops={"color": "white", "linewidth": 1.5})
    for patch, col in zip(bp["boxes"], colors):
        patch.set_facecolor(col); patch.set_edgecolor("white")
    for key in ("whiskers", "caps"):
        for line in bp[key]:
            line.set_color("#5A6B7A")
    ax.set_xticks([j * 3 + 0.5 for j in range(len(FRAMINGS))])
    ax.set_xticklabels([FRAMING_LABEL[f] for f in FRAMINGS], fontsize=8)
    ax.set_ylabel(f"Response length ({unit})")
    ax.set_title(f"{'English' if lang == 'en' else 'Mandarin'} prompts", pad=22)
    ax.grid(axis="x", visible=False)
fig.legend(handles=[Patch(color=BLUE, label="Claude Sonnet 5"), Patch(color=NAVY, label="DeepSeek V4 Pro")],
           frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.97), ncol=2)
fig.suptitle("Fig 8 — Response length by framing (substantive responses only)",
             fontsize=13, fontweight="bold", color=NAVY, y=1.04)
fig.text(0.01, -0.02, "Outliers hidden. Box = interquartile range, white line = median.", fontsize=8.5, color=GREY)
save(fig, "fig08_response_length_by_framing")

# =====================================================
# 09 — partial engagement (four-way split)
# =====================================================
# "minimal" = substantive response shorter than the 10th percentile of Claude's
# answered responses in the same language (Claude = reference: it never refused).
thr = {}
for lang in LANGS:
    ref = [r["_len"] for r in rows if r["model"] == "claude-sonnet-5"
           and r["language"] == lang and r["_cls"] == "answered"]
    thr[lang] = np.percentile(ref, 10)


def engage(r):
    if r["_cls"] != "answered":
        return r["_cls"]
    return "minimal" if r["_len"] < thr[r["language"]] else "full"


cats = ["full", "minimal", "canned", "empty"]
cat_label = {"full": "Substantive answer", "minimal": "Minimal answer (below Claude p10)",
             "canned": "Canned refusal", "empty": "Empty response"}
cat_color = {"full": BLUE, "minimal": PALE, "canned": GOLD, "empty": NAVY}
counts = defaultdict(lambda: defaultdict(int))
for r in rows:
    counts[(r["model"], r["language"])][engage(r)] += 1
fig, ax = plt.subplots(figsize=(9, 5.2))
bottom = np.zeros(len(combos))
for cat in cats:
    vals = np.array([counts[c][cat] / 300 * 100 for c in combos])
    bb = ax.bar(labels, vals, 0.58, bottom=bottom, color=cat_color[cat], edgecolor="white",
                linewidth=1, label=cat_label[cat])
    for i, (rect, v) in enumerate(zip(bb, vals)):
        if v >= 6:
            ax.text(rect.get_x() + rect.get_width() / 2, bottom[i] + v / 2, f"{v:.0f}%",
                    ha="center", va="center", fontsize=9,
                    color="white" if cat in ("full", "empty") else NAVY, fontweight="bold")
    bottom += vals
ax.set_ylabel("Share of prompts (%)")
ax.set_title("Fig 9 — Partial engagement: how each model responds, four ways")
ax.set_ylim(0, 100)
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.10), ncol=4, fontsize=9)
note(ax, f"Minimal threshold: < {thr['en']:.0f} words (EN), < {thr['zh']:.0f} characters (ZH) — "
         "the 10th percentile of Claude's substantive responses.", y=-0.22)
save(fig, "fig09_partial_engagement_four_types")

# ---------- summary (compare against docs/analysis-spec.md expected values) ----------
print("\nSummary (v2 corpus)")
for c in combos:
    nr = agg[c]["empty"] + agg[c]["canned"]
    print(f"  {MODEL_LABEL[c[0]]:22} {c[1]}  non-response {nr:3}/300 = {nr / 3:5.1f}%")
print("  canned EN:", en_c, " canned ZH:", zh_c, " empty:", empty_c)
