"""Tests for scripts/figure_18_judge_consistency.py (LLMEV-136).

Figure 18 makes one claim-bearing computation: it recomputes the judge's flip
rates from the per-fact labels and refuses to draw if they disagree with the
harness's own summary. A figure that quietly contradicts the run it describes
is worse than no figure, so that check is tested rather than trusted - on both
sides, because a guard that has never refused anything proves nothing.

matplotlib is deliberately NOT needed here: the drawing is isolated in draw(),
so the test suite stays free of a plotting dependency.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import figure_18_judge_consistency as fig18  # noqa: E402


def _labels(n: int, eng_diffs=(), fac_diffs=()):
    """Pass 0 labels, plus pass 1 as pass 0 with the named fact indices changed."""
    p0, p1 = [], []
    for i in range(n):
        cat, fac = i % 7, i % 4
        p0.append({"category": cat, "factuality": fac})
        p1.append({"category": (cat + 1) % 7 if i in eng_diffs else cat,
                   "factuality": (fac + 1) % 4 if i in fac_diffs else fac})
    return p0, p1


def _row(scenario, p0, p1, *, refusal=False, arm="us", language="en", error=None):
    row = {"file": f"{arm}.{language}", "arm": arm, "language": language,
           "model": "test-model", "scenario_id": scenario, "framing": "a",
           "refusal": refusal, "fact_count": len(p0),
           "p0_labels": json.dumps(p0), "p1_labels": json.dumps(p1)}
    if error:
        row["error"] = error
    return row


def _write(tmp_path, responses, extra_rows=(), **summary_overrides):
    """Write a harness-style fixture and return its summary."""
    rows, eng_pairs = [], 0
    eng_flips = fac_flips = 0
    for scenario, p0, p1 in responses:
        rows.append(_row(scenario, p0, p1))
        for x, y in zip(p0, p1):
            eng_pairs += 1
            eng_flips += x["category"] != y["category"]
            fac_flips += x["factuality"] != y["factuality"]
    rows.extend(extra_rows)

    with (tmp_path / "judge_consistency.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        writer.writeheader()
        writer.writerows(rows)

    summary = {"judge_model": "test-model", "passes": 2, "fact_limit": 50,
               "sampled_responses": len(rows), "judged_responses": len(rows),
               "refusal_shortcircuits": 0, "errors": 0,
               "engagement_call_pairs": eng_pairs, "engagement_call_flips": eng_flips,
               "engagement_call_flip_pct": round(100 * eng_flips / eng_pairs, 4)
               if eng_pairs else 0.0,
               "factuality_call_pairs": eng_pairs, "factuality_call_flips": fac_flips,
               "factuality_call_flip_pct": round(100 * fac_flips / eng_pairs, 4)
               if eng_pairs else 0.0,
               "responses_identical_all_fields": 0, "responses_identical_pct": 0.0}
    summary.update(summary_overrides)
    (tmp_path / "judge_consistency.json").write_text(json.dumps(summary), encoding="utf-8")
    return summary


def test_agreement_is_recomputed_per_response(tmp_path):
    _write(tmp_path, [("US-01", *_labels(10, eng_diffs=(0,))),
                      ("US-02", *_labels(10, eng_diffs=(1, 2)))])
    result = fig18.load_and_verify(tmp_path)
    rates = [round(r["eng_pct"]) for r in result["per_response"]]
    assert rates == [90, 80], rates
    assert result["eng_pairs"] == 20
    assert result["unparsed"] == 0


def test_refuses_when_the_summary_contradicts_the_csv(tmp_path):
    summary = _write(tmp_path, [("US-01", *_labels(10, eng_diffs=(0,)))])
    summary["engagement_call_flip_pct"] = summary["engagement_call_flip_pct"] + 5
    (tmp_path / "judge_consistency.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(SystemExit, match="disagree"):
        fig18.load_and_verify(tmp_path)


def test_refuses_when_the_pair_count_contradicts_the_csv(tmp_path):
    summary = _write(tmp_path, [("US-01", *_labels(10))])
    summary["engagement_call_pairs"] = 999
    (tmp_path / "judge_consistency.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(SystemExit, match="pair count mismatch"):
        fig18.load_and_verify(tmp_path)


def test_refusal_rows_are_excluded_not_treated_as_judged(tmp_path):
    """csv stores the flag as the string 'False', and bool('False') is True. A row
    that wrote bool(row['refusal']) here would count every refusal as judged."""
    _write(tmp_path, [("US-01", *_labels(10))],
           extra_rows=[_row("US-02", *_labels(10), refusal=True)])
    result = fig18.load_and_verify(tmp_path)
    assert result["refusals"] == 1
    assert result["eng_pairs"] == 10, "the refusal row leaked into the judged set"
    assert [r["label"].split()[0] for r in result["per_response"]] == ["US-01"]


def test_a_row_that_keeps_the_string_false_is_still_judged(tmp_path):
    _write(tmp_path, [("US-01", *_labels(10))])
    result = fig18.load_and_verify(tmp_path)
    assert result["refusals"] == 0
    assert result["eng_pairs"] == 10


def test_error_rows_are_excluded(tmp_path):
    _write(tmp_path, [("US-01", *_labels(10))],
           extra_rows=[_row("US-02", *_labels(10), error="TimeoutError: boom")])
    result = fig18.load_and_verify(tmp_path)
    assert [r["label"].split()[0] for r in result["per_response"]] == ["US-01"]


def test_unparseable_labels_are_counted_and_still_compared(tmp_path):
    p0, _ = _labels(10)
    _, p1 = _labels(10)
    p0[3]["category"] = len(fig18.ENGAGEMENT_CODES)  # the harness's sentinel
    _write(tmp_path, [("US-01", p0, p1)])
    result = fig18.load_and_verify(tmp_path)
    assert result["unparsed"] == 1
    assert result["eng_pairs"] == 10, "an unparsed label is still a compared pair"


def test_no_judged_responses_stops(tmp_path):
    _write(tmp_path, [], extra_rows=[_row("US-02", *_labels(10), refusal=True)])
    with pytest.raises(SystemExit, match="no judged responses"):
        fig18.load_and_verify(tmp_path)
