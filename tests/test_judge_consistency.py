"""Tests for scripts/judge_consistency.py (LLMEV-136 / figure 18).

The load-bearing test here is the FIDELITY one. ``traced_evaluate`` reimplements
``judge_pipeline.evaluate_response``'s arithmetic in order to keep the per-call labels,
and a reimplementation that drifts from the thing it mirrors would make the whole
reliability measurement report on code nobody runs.

It cannot be checked by calling both functions live: the judge samples, so a
disagreement would be ambiguous between "the arithmetic diverges" and "the judge gave a
different answer". The judge functions are therefore MONKEYPATCHED to a fixed script,
which removes sampling from the path entirely - any difference that remains is
arithmetic, and nothing else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import judge_consistency as jc  # noqa: E402
import judge_pipeline as jp  # noqa: E402


def facts(n: int) -> list[dict]:
    return [{"fact": f"fact {i}", "relevance": (i % 5) + 1} for i in range(n)]


@pytest.fixture
def scripted(monkeypatch):
    """Pin the judge to supplied label sequences, with no HTTP in the path.

    BOTH module namespaces are patched with INDEPENDENT iterators over the same script.
    ``judge_consistency`` did ``from judge_pipeline import judge_category``, which binds
    the function into its own namespace at import time - patching only ``judge_pipeline``
    would leave the traced path calling the real judge, and the two aggregations would
    then be compared across two different label sequences.
    """

    def install(categories: list[int], factualities: list[int]):
        def make():
            cat, fac = iter(categories), iter(factualities)
            return (lambda *a, **k: next(cat)), (lambda *a, **k: next(fac))

        for module in (jc, jp):
            cat_fn, fac_fn = make()
            monkeypatch.setattr(module, "judge_category", cat_fn)
            monkeypatch.setattr(module, "judge_factuality", fac_fn)

    return install


# --------------------------------------------------------------------------- fidelity


@pytest.mark.parametrize(
    "categories,factualities",
    [
        # all seven engagement codes and all four factuality codes
        ([1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 4, 1, 2, 3]),
        # weighted: relevance must land in the matching weight column, not just the count
        ([1, 1, 5, 5, 2], [3, 3, 1, 1, 2]),
        # a single fact
        ([7], [4]),
    ],
)
def test_traced_matches_committed_on_scripted_labels(scripted, categories, factualities):
    """Every label the judge can emit, aggregated both ways with sampling removed."""
    scripted(categories, factualities)
    fs = facts(len(categories))
    traced, labels = jc.traced_evaluate("en", "some response", False, fs, "m")
    committed = jp.evaluate_response("en", "some response", False, fs, "m")

    for f in jc.VALUE_FIELDS:
        assert traced[f] == committed[f], f"{f}: traced={traced[f]} committed={committed[f]}"
    assert len(labels) == len(categories)


def test_weight_columns_use_that_fact_s_relevance(scripted):
    """A weight attributed to the wrong fact still totals correctly - so check per-code."""
    scripted([1, 5], [3, 3])
    fs = [{"fact": "a", "relevance": 2}, {"fact": "b", "relevance": 7}]
    traced, _ = jc.traced_evaluate("en", "r", False, fs, "m")
    assert traced["count_engagement_full"] == 1
    assert traced["weight_engagement_full"] == 2
    assert traced["count_engagement_not_mentioned"] == 1
    assert traced["weight_engagement_not_mentioned"] == 7


def test_refusal_short_circuit_makes_no_judge_calls(monkeypatch):
    """evaluate_response returns before judging on a refusal; the trace must too."""
    calls = []

    def explode(*a, **k):
        calls.append(1)
        raise AssertionError("judge must not be called for a refusal row")

    monkeypatch.setattr(jp, "judge_category", explode)
    monkeypatch.setattr(jp, "judge_factuality", explode)

    fs = facts(4)
    traced, labels = jc.traced_evaluate("en", "r", True, fs, "m")
    assert labels == []
    assert calls == []
    assert traced["count_engagement_refusal"] == 4
    assert traced["count_facts_not_answered"] == 4
    assert traced["weight_engagement_refusal"] == sum(f["relevance"] for f in fs)
    assert traced["weight_facts_not_answered"] == sum(f["relevance"] for f in fs)


def test_out_of_range_labels_are_counted_as_other_not_dropped(scripted):
    """7 and 4 are the coercion targets for a malformed or failed judge call."""
    scripted([7, 7], [4, 4])
    traced, _ = jc.traced_evaluate("en", "r", False, facts(2), "m")
    assert traced["count_engagement_other"] == 2
    assert traced["count_facts_other"] == 2
    # nothing may be lost: the two categorical blocks must still sum to the fact count
    assert sum(traced[f] for f in jc.ENGAGEMENT_COUNTS) == 2
    assert sum(traced[f] for f in jc.FACTUALITY_COUNTS) == 2


# ----------------------------------------------------------------------------- sample


def test_select_sample_varies_framing_and_spans_fact_counts():
    """The sample must not collapse onto one scenario or one framing.

    An earlier version sorted by (fact_count, index) and took the first member of each
    scenario, so every file yielded the same three scenarios all at framing_a - a fixture
    pinned to one value of a dimension the reliability claim depends on.
    """
    facts_by_topic = {f"S{i:02d}": [{}] * (10 + i) for i in range(10)}
    responses = [
        {"scenario_id": f"S{i:02d}", "framing": f"framing_{j}"}
        for i in range(10)
        for j in range(4)
    ]
    idx = jc.select_sample(responses, facts_by_topic, per_file=4)
    picked = [responses[i] for i in idx]

    assert len(picked) == 4
    assert len({p["scenario_id"] for p in picked}) == 4, "scenarios collapsed"
    assert len({p["framing"] for p in picked}) > 1, "framing did not vary"
    counts = [len(facts_by_topic[p["scenario_id"]]) for p in picked]
    assert counts == sorted(counts), "fact counts are not ordered across the sample"
    assert counts[0] == min(len(v) for v in facts_by_topic.values())
    assert counts[-1] == max(len(v) for v in facts_by_topic.values())


def test_select_sample_is_deterministic():
    facts_by_topic = {f"S{i:02d}": [{}] * (5 + i) for i in range(8)}
    responses = [{"scenario_id": f"S{i:02d}", "framing": "framing_a"} for i in range(8)]
    assert jc.select_sample(responses, facts_by_topic, 3) == \
        jc.select_sample(responses, facts_by_topic, 3)


# ------------------------------------------------------------------------- arithmetic


def test_l1_bound_counts_both_directions():
    """Each flip moves mass out of one count and into another, so L1 grows by 2."""
    a = {"count_engagement_full": 3, "count_engagement_partial": 1}
    b = {"count_engagement_full": 2, "count_engagement_partial": 2}
    assert jc.l1(a, b, ["count_engagement_full", "count_engagement_partial"]) == 2


def test_l1_ignores_missing_keys_as_zero():
    assert jc.l1({"count_engagement_full": 2}, {}, ["count_engagement_full"]) == 2
