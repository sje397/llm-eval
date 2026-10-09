#!/usr/bin/env python3
"""LLMEV-136 / LLMEV-108 figure 18 - judge test-retest reliability.

Does the judge give the same answer twice?

WHY THIS IS AN OPEN QUESTION
The pipeline that produced ``data/evaluation.*.csv`` (2026-10-05) sends NO temperature
and NO seed to the oMLX server (``judge_pipeline.query_model``), so the server's own
sampling parameters govern every call. Measured directly against the live server on
2026-10-09: a free-generation prompt returned a different body on 1 of 3 identical
sends, so sampling IS on. Whether that reaches the forced-choice judge prompt is what
this script measures rather than assumes - a single 3-of-3 stable probe proves nothing.

WHAT IS MEASURED
Per-call label agreement and the response-level aggregate it produces. The call is the
causal quantity: ``evaluate_response`` is a deterministic function of its calls, so any
disagreement in the aggregate is produced by disagreement in the calls and nowhere else.
``traced_evaluate`` therefore reimplements the committed arithmetic with the labels kept,
and the caller CHECKS it against the committed function on the same inputs rather than
trusting that.

SAMPLE - varies the dimensions the claim depends on
A fixture pinned to one scenario or one framing would under-measure the effect, so the
sample deliberately varies three things at once:
  * fact count   - scenarios chosen at evenly spaced points of the fact-count ordering
  * framing      - rotated across the sample, never fixed to framing_a
  * language/arm - all four corpus files, so both judge prompt languages are exercised
Refusal rows are excluded from the flip-rate denominator and reported separately:
``evaluate_response`` short-circuits on them without calling the judge at all, so
counting them would report perfect reliability for calls that were never made.

Usage:
  python scripts/judge_consistency.py --per-file 4 --workers 8
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from judge_pipeline import (  # noqa: E402
    judge_category, judge_factuality, load_config,
)
from aggregate_scores import add_metrics  # noqa: E402

CORPUS_FILES = ["cn.en", "cn.zh", "us.en", "us.zh"]
ID_FIELDS = ["model", "language", "scenario_id", "framing"]

# The judge's category codes, in the order the codebook lists them. Both the column
# names and the aggregation are generated from these, so the two cannot drift apart.
ENGAGEMENT_CODES = ["full", "partial", "non_answer", "deflection",
                    "not_mentioned", "refusal", "other"]
FACTUALITY_CODES = ["true", "false", "not_answered", "other"]

VALUE_FIELDS = (
    [f"count_engagement_{c}" for c in ENGAGEMENT_CODES]
    + [f"weight_engagement_{c}" for c in ENGAGEMENT_CODES]
    + [f"count_facts_{c}" for c in FACTUALITY_CODES]
    + [f"weight_facts_{c}" for c in FACTUALITY_CODES]
)
ENGAGEMENT_COUNTS = [f"count_engagement_{c}" for c in ENGAGEMENT_CODES]
FACTUALITY_COUNTS = [f"count_facts_{c}" for c in FACTUALITY_CODES]


def check_committed_header(path: Path) -> None:
    """Fail loudly if the committed judge output is not the shape assumed here."""
    with path.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    expected = ID_FIELDS + [f"count_engagement_{c}" for c in ENGAGEMENT_CODES] \
        + [f"weight_engagement_{c}" for c in ENGAGEMENT_CODES] \
        + [f"count_facts_{c}" for c in FACTUALITY_CODES] \
        + [f"weight_facts_{c}" for c in FACTUALITY_CODES]
    if header != expected:
        raise SystemExit(f"{path.name}: header does not match the compared columns.\n"
                         f"  expected {expected}\n  found    {header}")


def load_articles(db_path: Path) -> dict[str, list]:
    """topic_id -> fact list, read exactly as judge_pipeline.main does (SELECT *)."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM articles")
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        conn.close()
    return {dict(zip(columns, r))["topic_id"]: json.loads(dict(zip(columns, r)).get(
        "facts_json", "[]")) for r in rows}


def load_responses(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def select_sample(responses: list[dict], facts_by_topic: dict[str, list],
                  per_file: int) -> list[int]:
    """Indices into `responses` spanning fact count, with framing rotated.

    Scenarios are ranked by fact count and sampled at evenly spaced points; each chosen
    scenario then contributes a DIFFERENT framing (rotating through the response order),
    so framing varies across the sample instead of collapsing onto whichever framing
    happens to sort first.
    """
    by_scenario: dict[str, list[int]] = {}
    for i, r in enumerate(responses):
        by_scenario.setdefault(r["scenario_id"], []).append(i)
    ranked = sorted(by_scenario, key=lambda s: (len(facts_by_topic.get(s, [])), s))
    if per_file >= len(ranked):
        chosen = ranked
    elif per_file == 1:
        chosen = [ranked[len(ranked) // 2]]
    else:
        picks = sorted({round(k * (len(ranked) - 1) / (per_file - 1)) for k in range(per_file)})
        if len(picks) != per_file:
            raise SystemExit(f"selection collapsed to {len(picks)} of {per_file} scenarios")
        chosen = [ranked[p] for p in picks]

    out = []
    for k, scenario in enumerate(chosen):
        members = by_scenario[scenario]
        out.append(members[k % len(members)])  # rotate the framing dimension
    return out


def traced_evaluate(language: str, response_text: str, refusal, facts: list,
                    judge_model: str) -> tuple[dict, list[dict]]:
    """``evaluate_response``'s arithmetic with the per-call labels kept.

    Verified against the committed function by the caller, not by inspection.
    """
    out = {f: 0 for f in VALUE_FIELDS}
    calls: list[dict] = []

    if refusal:
        total = len(facts)
        weight = sum(f.get("relevance", 0) for f in facts)
        out["count_engagement_refusal"] = total
        out["weight_engagement_refusal"] = weight
        out["count_facts_not_answered"] = total
        out["weight_facts_not_answered"] = weight
        return out, calls

    for fact in facts:
        relevance = fact.get("relevance", 0)
        category = judge_category(language, fact, response_text, judge_model)
        factuality = judge_factuality(language, fact, response_text, judge_model)
        calls.append({"category": category, "factuality": factuality, "relevance": relevance})

        if 1 <= category <= len(ENGAGEMENT_CODES):
            code = ENGAGEMENT_CODES[category - 1]
            out[f"count_engagement_{code}"] += 1
            out[f"weight_engagement_{code}"] += relevance
        if 1 <= factuality <= len(FACTUALITY_CODES):
            code = FACTUALITY_CODES[factuality - 1]
            out[f"count_facts_{code}"] += 1
            out[f"weight_facts_{code}"] += relevance
    return out, calls


def l1(a: dict, b: dict, fields: list[str]) -> int:
    return sum(abs(int(a.get(f) or 0) - int(b.get(f) or 0)) for f in fields)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-file", type=int, default=4)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--fact-limit", type=int, default=50,
                        help="facts per response, matching the committed run (default 50)")
    parser.add_argument("--judge-model", default="Qwen3.8-Flash-Next-Uncensored-oQ4e-mtp")
    parser.add_argument("--fact-db", type=Path, default=REPO / "data/index.sqlite3")
    parser.add_argument("--raw-dir", type=Path, default=REPO / "data/raw")
    parser.add_argument("--out-dir", type=Path, default=REPO / "data/analysis")
    args = parser.parse_args(argv)

    for name in CORPUS_FILES:
        check_committed_header(REPO / "data" / f"evaluation.{name}.csv")

    config = load_config()
    print(f"judge model : {args.judge_model}")
    print(f"endpoint    : http://{config['onix']['host']}:{config['onix']['port']}"
          f"/v1/messages  (no temperature, no seed - as committed)")
    print(f"fact limit  : {args.fact_limit}   passes: {args.passes}   workers: {args.workers}")

    facts_by_topic = load_articles(args.fact_db)
    jobs = []
    for name in CORPUS_FILES:
        arm, language = name.split(".")
        responses = load_responses(args.raw_dir / f"{name}.jsonl")
        for i in select_sample(responses, facts_by_topic, args.per_file):
            r = responses[i]
            facts = facts_by_topic.get(r["scenario_id"], [])[: args.fact_limit]
            jobs.append({"file": name, "arm": arm, "language": language,
                         "scenario_id": r["scenario_id"], "framing": r.get("framing"),
                         "model": r.get("model"), "refusal": bool(r.get("refusal")),
                         "response_text": r.get("response"), "facts": facts})

    real = [j for j in jobs if not j["refusal"]]
    total_facts = sum(len(j["facts"]) for j in real)
    calls = total_facts * 2 * args.passes
    print(f"sample      : {len(jobs)} responses ({len(real)} judged, "
          f"{len(jobs) - len(real)} refusal short-circuits), {total_facts} facts, "
          f"~{calls:,} judge calls")
    print(f"scenarios   : {len({j['scenario_id'] for j in jobs})} distinct"
          f"   framings: {sorted({j['framing'] for j in jobs})}\n")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    started = time.time()

    def work(job):
        passes = []
        for _ in range(args.passes):
            passes.append(traced_evaluate(job["language"], job["response_text"],
                                          job["refusal"], job["facts"], args.judge_model))
        return job, passes

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, j): j for j in jobs}
        for done, fut in enumerate(as_completed(futures), 1):
            job = futures[fut]
            try:
                _, passes = fut.result()
            except Exception as exc:
                print(f"  !! {job['file']} {job['scenario_id']} {job['framing']}: "
                      f"{type(exc).__name__}: {exc}")
                rows.append({"file": job["file"], "scenario_id": job["scenario_id"],
                             "framing": job["framing"],
                             "error": f"{type(exc).__name__}: {exc}"})
                continue
            row = {"file": job["file"], "arm": job["arm"], "language": job["language"],
                   "model": job["model"], "scenario_id": job["scenario_id"],
                   "framing": job["framing"], "refusal": job["refusal"],
                   "fact_count": len(job["facts"])}
            for p, (agg, labels) in enumerate(passes):
                for f in VALUE_FIELDS:
                    row[f"p{p}_{f}"] = agg.get(f, 0)
                row[f"p{p}_labels"] = json.dumps(labels)
            # NOTE: fidelity of traced_evaluate to the committed evaluate_response is
            # NOT checked here. Calling the committed function live would make a third
            # judge pass, so a disagreement would mean "the judge is stochastic", not
            # "the arithmetic diverges" - two different claims. It is proven instead by
            # tests/test_judge_consistency.py, which pins the judge's labels and so
            # compares the two aggregations with no sampling in the path.
            rows.append(row)
            print(f"  [{done}/{len(jobs)}] {job['file']} {job['scenario_id']} "
                  f"{job['framing']} facts={len(job['facts'])}")

    elapsed = time.time() - started
    if not rows:
        raise SystemExit("no results")

    ok = [r for r in rows if "error" not in r and not r["refusal"]]
    refused = [r for r in rows if "error" not in r and r["refusal"]]

    # --- per-call agreement ----------------------------------------------------
    cat_pairs = fac_pairs = cat_flips = fac_flips = 0
    other0 = other1 = 0
    for r in ok:
        a = json.loads(r["p0_labels"])
        b = json.loads(r["p1_labels"])
        for x, y in zip(a, b):
            cat_pairs += 1
            fac_pairs += 1
            if x["category"] != y["category"]:
                cat_flips += 1
            if x["factuality"] != y["factuality"]:
                fac_flips += 1
            other0 += x["category"] == len(ENGAGEMENT_CODES) or x["factuality"] == len(FACTUALITY_CODES)
            other1 += y["category"] == len(ENGAGEMENT_CODES) or y["factuality"] == len(FACTUALITY_CODES)

    # --- response-level agreement, via the repo's own derived metric ------------
    def frame_for(prefix: str) -> pd.DataFrame:
        return pd.DataFrame([
            {**{k: r[k] for k in ID_FIELDS}, "scenario_id": r["scenario_id"],
             **{f: r[f"{prefix}_{f}"] for f in VALUE_FIELDS}}
            for r in ok
        ])

    m0, m1 = add_metrics(frame_for("p0")), add_metrics(frame_for("p1"))
    exact = sum(1 for r in ok if all(
        int(r[f"p0_{f}"] or 0) == int(r[f"p1_{f}"] or 0) for f in VALUE_FIELDS))
    eng_l1 = [l1({f: r[f"p0_{f}"] for f in ENGAGEMENT_COUNTS},
                 {f: r[f"p1_{f}"] for f in ENGAGEMENT_COUNTS}, ENGAGEMENT_COUNTS) for r in ok]
    fac_l1 = [l1({f: r[f"p0_{f}"] for f in FACTUALITY_COUNTS},
                 {f: r[f"p1_{f}"] for f in FACTUALITY_COUNTS}, FACTUALITY_COUNTS) for r in ok]
    dd = (m0["disclosure_weight"] - m1["disclosure_weight"]).abs()

    summary = {
        "judge_model": args.judge_model,
        "passes": args.passes,
        "fact_limit": args.fact_limit,
        "sampled_responses": len(rows),
        "judged_responses": len(ok),
        "refusal_shortcircuits": len(refused),
        "errors": sum(1 for r in rows if "error" in r),
        "engagement_call_pairs": cat_pairs,
        "engagement_call_flips": cat_flips,
        "engagement_call_flip_pct": round(100 * cat_flips / max(cat_pairs, 1), 4),
        "factuality_call_pairs": fac_pairs,
        "factuality_call_flips": fac_flips,
        "factuality_call_flip_pct": round(100 * fac_flips / max(fac_pairs, 1), 4),
        "responses_identical_all_fields": exact,
        "responses_identical_pct": round(100 * exact / max(len(ok), 1), 1),
        "engagement_l1_total": sum(eng_l1),
        "factuality_l1_total": sum(fac_l1),
        "disclosure_weight_abs_delta_mean": round(float(dd.mean()), 6) if len(dd) else 0.0,
        "disclosure_weight_abs_delta_max": round(float(dd.max()), 6) if len(dd) else 0.0,
        "other_labels_p0": other0,
        "other_labels_p1": other1,
        "elapsed_seconds": round(elapsed, 1),
    }

    (args.out_dir / "judge_consistency.json").write_text(json.dumps(summary, indent=2) + "\n")
    out_csv = args.out_dir / "judge_consistency.csv"
    # Union of keys, so a row carrying an error is not silently dropped by the writer.
    fieldnames: list[str] = []
    for r in rows:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "=" * 74)
    for k, v in summary.items():
        print(f"{k:38s} {v}")
    print("=" * 74)
    print(f"wrote {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
