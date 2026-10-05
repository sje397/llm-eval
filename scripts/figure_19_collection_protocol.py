#!/usr/bin/env python3
"""LLMEV-108 — Figure 19: what the 1,024-token cap did to the v1 corpus.

The numbers are the verification figures from PR #21 / docs/corpus-provenance.md.
They are constants here because v1 is no longer in data/raw (retrievable from git at
commit 68ad1715). To recompute, diff v1 against v2 and update the dict below.

Usage:   python scripts/figure_19_collection_protocol.py [out_dir]
"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = sys.argv[1] if len(sys.argv) > 1 else "figures"
os.makedirs(OUT, exist_ok=True)

# ---- PR #21 verification figures ----
V1 = {
    "visible_empty":      {"deepseek-v4-pro": 84,  "claude-sonnet-5": 0},    # empty replies in v1
    "affected_by_cap":    {"deepseek-v4-pro": 177, "claude-sonnet-5": 32},   # v2 reply exceeds 1024
    "detector_counts":    {"Empty reply\n(visible)": 84, "v2 reply exceeds\nold cap": 209,
                           "v1 reply ends\nmid-sentence": 119},
    "detector_overlap":   52,     # rows flagged by all three
    "recovered_as_answer": 83,    # of the 84 empties, re-collected at 8192
    "cost_usd": 5.38,
}

NAVY, MID, AMBER, GREY = "#1E2761", "#3E5199", "#D98A2B", "#6B7280"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#D9E0EF",
                     "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
                     "axes.grid": True, "grid.color": "#E7EEFB", "axes.axisbelow": True,
                     "figure.facecolor": "white"})

fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.8), gridspec_kw={"width_ratios": [1.1, 1]})
arms = ["DeepSeek V4 Pro\n(600 rows)", "Claude Sonnet 5\n(600 rows)"]
keys = ["deepseek-v4-pro", "claude-sonnet-5"]
visible = [V1["visible_empty"][k] for k in keys]
affected = [V1["affected_by_cap"][k] for k in keys]
x = np.arange(2)
b1 = a1.bar(x - 0.19, visible, 0.36, color=AMBER, edgecolor="white", label="Visible damage (empty reply)")
b2 = a1.bar(x + 0.19, affected, 0.36, color=NAVY, edgecolor="white", label="Total affected by 1,024-token cap")
for bb in (b1, b2):
    for r in bb:
        v = r.get_height()
        a1.annotate(f"{v}\n({v / 600 * 100:.1f}%)", (r.get_x() + r.get_width() / 2, v),
                    textcoords="offset points", xytext=(0, 4), ha="center", fontsize=9, color="#5A6B7A")
a1.set_xticks(x); a1.set_xticklabels(arms)
a1.set_ylabel("Rows"); a1.set_ylim(0, max(affected) * 1.22)
a1.set_title("v1 collection damage by arm")
a1.legend(frameon=False, loc="upper right", fontsize=9)

det = list(V1["detector_counts"].keys()); vals = list(V1["detector_counts"].values())
b = a2.bar(det, vals, 0.55, color=[AMBER, NAVY, MID], edgecolor="white")
for r, v in zip(b, vals):
    a2.annotate(str(v), (r.get_x() + r.get_width() / 2, v), textcoords="offset points",
                xytext=(0, 4), ha="center", fontsize=10, fontweight="bold", color=NAVY)
a2.axhline(V1["detector_overlap"], color=AMBER, linestyle="--", linewidth=1.2)
a2.text(0.45, V1["detector_overlap"] + 4, f"{V1['detector_overlap']} rows flagged by all three",
        fontsize=8.5, color=AMBER, ha="left", va="bottom")
a2.set_ylabel("Rows (of 1,200)"); a2.set_ylim(0, max(vals) * 1.15)
a2.set_title("Three ways of detecting truncation disagree")
fig.suptitle("Fig 19 — Collection protocol: what the 1,024-token cap did to v1 (v2 has 0 empty, 0 capped)",
             fontsize=13, fontweight="bold", color=NAVY, y=1.02)
fig.text(0.01, -0.03, f"Source: PR #21 verification. {V1['recovered_as_answer']} of 84 formerly-empty rows "
                      f"recovered as answers at 8,192 tokens; one was a refusal. Re-collection cost ${V1['cost_usd']:.2f}.",
         fontsize=8.5, color=GREY)
fig.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(os.path.join(OUT, f"fig19_v1_token_cap_damage.{ext}"), dpi=200, bbox_inches="tight")
print("wrote fig19_v1_token_cap_damage")
