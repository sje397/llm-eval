#!/usr/bin/env python3
"""LLMEV-108 figure 17 - Wikipedia retrieval quality.

How the 60 evaluation events resolve against the local Wikipedia semantic-search
service (FastAPI on Mimir, 127.0.0.1:21500).

QUERY CONVENTION
  Each event is queried with its `topic` string exactly as stored in
  data/index.sqlite3 ("The Opium Wars", "The Xinhai Revolution", ...). That string
  is the event name the corpus prompts use, so it is the query the pipeline has.
  The ground-truth article for the event is identified from its `source_url`.

THREE OUTCOMES, because two of them are not a distance
  exact      the service's exact title/redirect path returned the ground-truth
             article at score 0.0
  semantic   intro-ANN search returned the article, at _distance > 0
  not found  the article was not in the top_k results at all

NOTE ON `mode`
  The service accepts mode="text"|"title", validates it against a regex, and echoes
  it in the response - but service.py never reads it. The exact-title lookup and the
  ANN search are both unconditional (service.py:237-273), so the two modes return
  identical payloads. This script issues BOTH modes for every event and asserts the
  payloads are identical, so the figure's numbers do not depend on which is used.

Requires the service and oMLX query embeddings. 120 HTTP calls, ~2 minutes.

Usage:
  python scripts/figure_17_retrieval_quality.py [index_db] [out_dir] [service_url]
Defaults:
  data/index.sqlite3   docs/visualisation/figures   http://127.0.0.1:21500
"""
import json
import os
import sqlite3
import statistics
import sys
import urllib.parse
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

INDEX_DB = sys.argv[1] if len(sys.argv) > 1 else "data/index.sqlite3"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/visualisation/figures"
SERVICE = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:21500"
TOP_K = 20
os.makedirs(OUT, exist_ok=True)

NAVY, MID, AMBER, GREY, GREEN, ICE = "#1E2761", "#3E5199", "#D98A2B", "#6B7280", "#2E7D5B", "#CADCFC"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#D9E0EF",
                     "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
                     "axes.grid": True, "grid.color": "#E7EEFB", "axes.axisbelow": True,
                     "figure.facecolor": "white"})


def search(query, lang="en", mode="text", top_k=TOP_K):
    """POST /search. Raises on a non-200 rather than silently returning nothing."""
    req = urllib.request.Request(
        SERVICE + "/search",
        data=json.dumps({"query": query, "lang": lang, "mode": mode, "top_k": top_k}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def wiki_title(source_url):
    """'https://en.wikipedia.org/wiki/Opium_Wars' -> 'Opium Wars'."""
    title = urllib.parse.unquote(source_url.rsplit("/", 1)[-1]).replace("_", " ")
    return title.split("#", 1)[0].strip()


def norm(title):
    """Case- and article-insensitive comparison key.

    The exact-title path is case-sensitive (measured: 'The Opium Wars' resolves at
    0.0, 'opium wars' does not), but the ANN index is not, so the *reported*
    resolution of a correct article must not depend on casing.
    """
    t = title.strip().lower()
    for art in ("the ", "a ", "an "):
        if t.startswith(art):
            t = t[len(art):]
            break
    return t


def matches(a, b):
    return norm(a) == norm(b)


def main():
    con = sqlite3.connect(INDEX_DB)
    events = con.execute("SELECT topic_id, topic, source_url FROM articles ORDER BY topic_id").fetchall()
    if not events:
        sys.exit("no events in %s" % INDEX_DB)

    rows = []
    mode_mismatches = []
    for topic_id, topic, url in events:
        want = wiki_title(url)
        per_mode = {}
        for mode in ("text", "title"):
            res = search(topic, mode=mode)["results"]
            exact = [r for r in res if r.get("exact")]
            hit_idx = next((i for i, r in enumerate(res) if matches(r["title"], want)), None)
            per_mode[mode] = {
                "results": res,
                "outcome": "exact" if (exact and matches(exact[0]["title"], want))
                           else ("semantic" if hit_idx is not None else "not_found"),
                "distance": 0.0 if (exact and matches(exact[0]["title"], want))
                            else (res[hit_idx]["score"] if hit_idx is not None else None),
                "rank": hit_idx + 1 if hit_idx is not None else None,
                "top_title": res[0]["title"] if res else None,
                "top_distance": res[0]["score"] if res else None,
                "n_results": len(res),
            }
        if per_mode["text"]["results"] != per_mode["title"]["results"]:
            mode_mismatches.append(topic_id)
        rows.append({"topic_id": topic_id, "topic": topic, "wanted": want, **per_mode["text"]})

    if mode_mismatches:
        sys.exit("mode is NOT inert for %s - the figure's mode assumption is wrong" % mode_mismatches)

    n = len(rows)
    exact = [r for r in rows if r["outcome"] == "exact"]
    semantic = [r for r in rows if r["outcome"] == "semantic"]
    missing = [r for r in rows if r["outcome"] == "not_found"]
    dists = [r["distance"] for r in semantic]

    print("events                      : %d" % n)
    print("resolved by exact title     : %d (%.0f%%)" % (len(exact), 100 * len(exact) / n))
    print("resolved by ANN only        : %d (%.0f%%)" % (len(semantic), 100 * len(semantic) / n))
    print("ground-truth article absent : %d (%.0f%%)" % (len(missing), 100 * len(missing) / n))
    if dists:
        print("ANN distance  min/median/max: %.4f / %.4f / %.4f"
              % (min(dists), statistics.median(dists), max(dists)))
    print("mode='text' == mode='title' : %d/%d events" % (n - len(mode_mismatches), n))

    def split(prefix):
        sub = [r for r in rows if r["topic_id"].startswith(prefix)]
        return (sum(r["outcome"] == "exact" for r in sub),
                sum(r["outcome"] == "semantic" for r in sub),
                sum(r["outcome"] == "not_found" for r in sub))

    cn, us = split("CN"), split("US")

    # ---------------------------------------------------------------- figure
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.45, 1]})

    bins = np.arange(0.0, 0.65, 0.05)
    a1.hist(dists, bins=bins, color=MID, edgecolor="white", linewidth=0.7,
            label=f"resolved by ANN search (n={len(semantic)})")
    a1.bar(0.025, len(exact), width=0.05, color=NAVY, edgecolor="white", linewidth=0.7,
           label=f"resolved by exact title match (n={len(exact)})")
    a1.set_xlim(-0.03, 0.62)
    a1.set_ylim(0, 15)
    a1.set_xlabel("Cosine distance to the event's ground-truth article  (lower = closer)")
    a1.set_ylabel("Events")
    a1.set_title("Where each event's evidence resolves")
    a1.text(0.06, 13.9,
            f"{len(missing)} events ({round(100 * len(missing) / n)}%) never returned\ntheir ground-truth article",
            fontsize=9, color=GREY, ha="left", va="top")
    a1.legend(frameon=False, loc="upper right", fontsize=9)

    x = np.arange(2)
    ex = np.array([cn[0], us[0]])
    se = np.array([cn[1], us[1]])
    mi = np.array([cn[2], us[2]])
    a2.bar(x, ex, 0.5, color=NAVY, edgecolor="white", label="exact title match")
    a2.bar(x, se, 0.5, bottom=ex, color=MID, edgecolor="white", label="ANN search")
    a2.bar(x, mi, 0.5, bottom=ex + se, color=GREY, edgecolor="white", label="not retrieved")
    for i in range(2):
        tot = ex[i] + se[i] + mi[i]
        a2.text(i, tot + 0.6, f"{ex[i] + se[i]}/{tot} found", ha="center",
                fontsize=10, fontweight="bold", color=NAVY)
    a2.set_xticks(x)
    a2.set_xticklabels([f"China-centric\n({cn[0] + cn[1] + cn[2]} events)",
                        f"US-centric\n({us[0] + us[1] + us[2]} events)"])
    a2.set_ylabel("Events")
    a2.set_ylim(0, 37)
    a2.set_title("By event origin")
    a2.legend(frameon=False, loc="upper center", fontsize=9, ncol=3,
              handlelength=1.2, columnspacing=1.4, handletextpad=0.5)

    fig.suptitle("Fig 17 - Wikipedia retrieval quality: how the 60 events resolve",
                 fontsize=13, fontweight="bold", color=NAVY, y=1.02)
    fig.text(0.01, -0.03,
             f"Source: local Wikipedia semantic-search service (bge-small per-language index, "
             f"{TOP_K} results/query), queried with each event's stored topic. "
             f"mode='text' and mode='title' returned byte-identical results for all {n} events.",
             fontsize=8.5, color=GREY)
    fig.tight_layout()
    png = os.path.join(OUT, "fig17_retrieval_quality.png")
    svg = os.path.join(OUT, "fig17_retrieval_quality.svg")
    fig.savefig(png, dpi=200, bbox_inches="tight")
    fig.savefig(svg, bbox_inches="tight")
    print("wrote", png)
    print("wrote", svg)

    # The raw `results` payload carries every article intro (~1 MB per run); only the
    # per-event outcome is committed, and it is enough to redraw the figure's numbers.
    slim = [{k: v for k, v in r.items() if k != "results"} for r in rows]
    json.dump(slim, open(os.path.join(OUT, "fig17_retrieval_quality.json"), "w"), indent=1)
    print("wrote", os.path.join(OUT, "fig17_retrieval_quality.json"))


if __name__ == "__main__":
    main()
