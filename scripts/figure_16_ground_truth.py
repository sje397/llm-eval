#!/usr/bin/env python3
"""LLMEV-108 — Figure 16: ground-truth evidence base, coverage and validation.

Reads the two LLMEV-111 validation reports in data/ground_truth/.

Usage:   python scripts/figure_16_ground_truth.py [final_report.json] [prototype_report.json] [out_dir]
Default: "data/Learnmore FINAL ground truth validation report.json"
         "data/learnmore ground truth validation report.json"  figures/
"""
import json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

FINAL = sys.argv[1] if len(sys.argv) > 1 else "data/Learnmore FINAL ground truth validation report.json"
PROTO = sys.argv[2] if len(sys.argv) > 2 else "data/learnmore ground truth validation report.json"
OUT = sys.argv[3] if len(sys.argv) > 3 else "figures"
os.makedirs(OUT, exist_ok=True)

NAVY, MID, AMBER, GREY, GREEN, ICE = "#1E2761", "#3E5199", "#D98A2B", "#6B7280", "#2E7D5B", "#CADCFC"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#D9E0EF",
                     "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
                     "axes.grid": True, "grid.color": "#E7EEFB", "axes.axisbelow": True,
                     "figure.facecolor": "white"})

d = json.load(open(FINAL, encoding="utf-8"))
t = sorted(d["topics"], key=lambda x: (x["scenario_id"][:2], int(x["scenario_id"][3:])))
proto = json.load(open(PROTO, encoding="utf-8"))

fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [2.2, 1]})
ids = [x["scenario_id"] for x in t]
fc = [x["fact_count"] for x in t]
cn_med = int(np.median([x["fact_count"] for x in t if x["scenario_id"].startswith("CN")]))
us_med = int(np.median([x["fact_count"] for x in t if x["scenario_id"].startswith("US")]))
a1.bar(range(len(ids)), fc, color=[NAVY if i.startswith("CN") else AMBER for i in ids],
       edgecolor="white", linewidth=0.5)
a1.axhline(100, color=GREY, linestyle="--", linewidth=1)
a1.text(0.3, 103, "target ~100", fontsize=8.5, color=GREY, ha="left")
a1.set_xticks(range(len(ids))); a1.set_xticklabels(ids, rotation=90, fontsize=6.5)
a1.set_ylabel("Verified facts in ground-truth set"); a1.set_xlim(-0.7, len(ids) - 0.3)
a1.set_title(f"Ground-truth facts per event — all {len(ids)} pass validation")
a1.legend(handles=[Patch(color=NAVY, label=f"China-centric (median {cn_med})"),
                   Patch(color=AMBER, label=f"US-centric (median {us_med})")],
          frameon=False, loc="upper right", fontsize=9)

p_pass, p_fail = proto["scenarios_passing"], proto["scenarios_failing"]
p_miss = len(proto.get("missing_ground_truth_files", []))
f_pass = sum(1 for x in t if x["status"] == "PASS")
f_fail = len(t) - f_pass
x = np.arange(2)
passing, failing, missing = [p_pass, f_pass], [p_fail, f_fail], [p_miss, 0]
a2.bar(x, passing, 0.55, color=GREEN, edgecolor="white", label="Passing")
a2.bar(x, failing, 0.55, bottom=passing, color=AMBER, edgecolor="white", label="Failing")
a2.bar(x, missing, 0.55, bottom=[p + f for p, f in zip(passing, failing)], color=GREY,
       edgecolor="white", label="Missing")
for i, (p, f, m) in enumerate(zip(passing, failing, missing)):
    a2.text(i, p + f + m + 1.2, f"{p}/{p + f + m} pass", ha="center", fontsize=10,
            fontweight="bold", color=NAVY)
a2.set_xticks(x)
a2.set_xticklabels([f"{proto['generated_at'][:10]}\nprototype\n({p_pass + p_fail + p_miss} scenarios)",
                    f"{d['generated_at'][:10]}\nfinal\n({len(t)} scenarios)"], fontsize=9)
a2.set_ylabel("Scenarios"); a2.set_ylim(0, len(t) + 8)
a2.set_title("Validation: before → after")
a2.legend(frameon=False, loc="upper left", fontsize=9)
fig.suptitle("Fig 16 — Ground-truth evidence base: coverage by event and validation outcome",
             fontsize=13, fontweight="bold", color=NAVY, y=1.02)
fig.text(0.01, -0.04, f"Source: LLMEV-111 validation reports. {sum(fc):,} facts across {len(ids)} events, "
                      f"{min(fc)}–{max(fc)} per event.", fontsize=8.5, color=GREY)
fig.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(os.path.join(OUT, f"fig16_groundtruth_coverage.{ext}"), dpi=200, bbox_inches="tight")
print("wrote fig16_groundtruth_coverage")
