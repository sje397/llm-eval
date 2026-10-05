"""Tests for scripts/rq1_export.py — Romit's LLMEV-107 contract adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import aggregate_scores as agg
import rq1_export as rq1
from nonresponse_metrics import CANNED_TEMPLATES


def make_eval_row(**overrides: object) -> dict:
    """Valid 4-fact tally matching aggregate_scores expectations."""
    row: dict = {
        "model": "claude-sonnet-5",
        "language": "en",
        "scenario_id": "US-01",
        "framing": "framing_a",
    }
    for category in agg.ENGAGEMENT_CATEGORIES:
        row[f"count_engagement_{category}"] = 0
        row[f"weight_engagement_{category}"] = 0.0
    for category in agg.FACTUALITY_CATEGORIES:
        row[f"count_facts_{category}"] = 0
        row[f"weight_facts_{category}"] = 0.0

    row["count_engagement_full"] = 2
    row["count_engagement_partial"] = 1
    row["count_engagement_not_mentioned"] = 1
    row["weight_engagement_full"] = 2.0
    row["weight_engagement_partial"] = 1.0
    row["weight_engagement_not_mentioned"] = 1.0
    row["count_facts_true"] = 2
    row["count_facts_not_answered"] = 2
    row["weight_facts_true"] = 2.0
    row["weight_facts_not_answered"] = 2.0
    row.update(overrides)
    return row


def write_eval(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows)[agg.EXPECTED_COLUMNS].to_csv(path, index=False)


def write_raw(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def raw_row(
    scenario_id: str,
    framing: str,
    language: str,
    model: str,
    text: str = "A substantive answer about the event.",
) -> dict:
    return {
        "scenario_id": scenario_id,
        "framing": framing,
        "language": language,
        "model": model,
        "response": text,
        "corpus_version": "v2",
    }


def seed_mini_corpus(tmp_path: Path) -> tuple[Path, Path]:
    """Two models × two languages × two origins × one framing = 8 responses."""
    input_dir = tmp_path / "data"
    raw_dir = tmp_path / "raw"
    input_dir.mkdir()
    raw_dir.mkdir()

    eval_rows = [
        make_eval_row(model="claude-sonnet-5", language="en", scenario_id="US-01", framing="framing_a"),
        make_eval_row(model="claude-sonnet-5", language="en", scenario_id="CN-01", framing="framing_a"),
        make_eval_row(model="claude-sonnet-5", language="zh", scenario_id="US-01", framing="framing_a"),
        make_eval_row(model="claude-sonnet-5", language="zh", scenario_id="CN-01", framing="framing_a"),
        make_eval_row(
            model="deepseek-v4-pro",
            language="en",
            scenario_id="US-01",
            framing="framing_a",
            count_engagement_full=0,
            weight_engagement_full=0.0,
            count_engagement_partial=0,
            weight_engagement_partial=0.0,
            count_engagement_not_mentioned=0,
            weight_engagement_not_mentioned=0.0,
            count_engagement_refusal=4,
            weight_engagement_refusal=4.0,
        ),
        make_eval_row(model="deepseek-v4-pro", language="en", scenario_id="CN-01", framing="framing_a"),
        make_eval_row(
            model="deepseek-v4-pro",
            language="zh",
            scenario_id="US-01",
            framing="framing_a",
            count_engagement_full=0,
            weight_engagement_full=0.0,
            count_engagement_partial=0,
            weight_engagement_partial=0.0,
            count_engagement_not_mentioned=0,
            weight_engagement_not_mentioned=0.0,
            count_engagement_refusal=4,
            weight_engagement_refusal=4.0,
        ),
        make_eval_row(model="deepseek-v4-pro", language="zh", scenario_id="CN-01", framing="framing_a"),
    ]

    # Split by arm/language into the four evaluation filenames.
    for arm, model in (("us", "claude-sonnet-5"), ("cn", "deepseek-v4-pro")):
        for language in ("en", "zh"):
            subset = [r for r in eval_rows if r["model"] == model and r["language"] == language]
            write_eval(input_dir / f"evaluation.{arm}.{language}.csv", subset)

    raw_rows = [
        raw_row("US-01", "framing_a", "en", "claude-sonnet-5"),
        raw_row("CN-01", "framing_a", "en", "claude-sonnet-5"),
        raw_row("US-01", "framing_a", "zh", "claude-sonnet-5"),
        raw_row("CN-01", "framing_a", "zh", "claude-sonnet-5"),
        raw_row("US-01", "framing_a", "en", "deepseek-v4-pro", CANNED_TEMPLATES[0]),
        raw_row("CN-01", "framing_a", "en", "deepseek-v4-pro"),
        raw_row("US-01", "framing_a", "zh", "deepseek-v4-pro", CANNED_TEMPLATES[1]),
        raw_row("CN-01", "framing_a", "zh", "deepseek-v4-pro"),
    ]
    write_raw(raw_dir / "mini.jsonl", raw_rows)
    return input_dir, raw_dir


def test_topic_origin_from_scenario():
    assert rq1.topic_origin_from_scenario("CN-17") == "China-centric"
    assert rq1.topic_origin_from_scenario("US-05") == "US-centric"
    with pytest.raises(rq1.ExportError):
        rq1.topic_origin_from_scenario("XX-01")


def test_export_writes_contract_schema(tmp_path: Path):
    input_dir, raw_dir = seed_mini_corpus(tmp_path)
    out_dir = tmp_path / "processed"

    manifest = rq1.export_rq1(input_dir, raw_dir, out_dir, basis="count", iterations=200, seed=1)

    scores = pd.read_csv(out_dir / "rq1_response_scores.csv")
    aggregated = pd.read_csv(out_dir / "rq1_aggregated_metrics.csv")
    comparisons = pd.read_csv(out_dir / "rq1_statistical_comparisons.csv")

    assert list(scores.columns) == rq1.RESPONSE_COLUMNS
    assert list(aggregated.columns) == rq1.AGGREGATE_COLUMNS
    assert list(comparisons.columns) == rq1.COMPARISON_COLUMNS
    assert len(scores) == 8
    assert set(scores["language"]) == {"en", "zh"}
    assert set(scores["topic_origin"]) == {"US-centric", "China-centric"}
    assert scores["response_id"].tolist() == [f"RESP_{i:04d}" for i in range(1, 9)]
    assert "All" in set(aggregated["topic_origin"])
    assert set(comparisons["comparison_type"]) == {
        "model_comparison",
        "language_comparison",
        "topic_gap",
    }
    assert manifest["refusal_total"] == 2
    assert (out_dir / "rq1_export_manifest.json").exists()


def test_refusal_flag_is_union_of_canned_and_rubric(tmp_path: Path):
    input_dir, raw_dir = seed_mini_corpus(tmp_path)
    out_dir = tmp_path / "processed"
    rq1.export_rq1(input_dir, raw_dir, out_dir, basis="count", iterations=50, seed=1)
    scores = pd.read_csv(out_dir / "rq1_response_scores.csv")

    refused = scores[scores["refusal_flag"] == 1]
    assert len(refused) == 2
    assert set(zip(refused["model"], refused["language"], refused["scenario_id"])) == {
        ("deepseek-v4-pro", "en", "US-01"),
        ("deepseek-v4-pro", "zh", "US-01"),
    }


def test_disclosure_matches_aggregate_scores_count_basis(tmp_path: Path):
    input_dir, raw_dir = seed_mini_corpus(tmp_path)
    frame = agg.load_frame(input_dir)
    metrics = agg.add_metrics(frame)
    out_dir = tmp_path / "processed"
    rq1.export_rq1(input_dir, raw_dir, out_dir, basis="count", iterations=50, seed=1)
    scores = pd.read_csv(out_dir / "rq1_response_scores.csv")

    merged = scores.merge(
        metrics[
            ["model", "language", "scenario_id", "framing", "disclosure_count", "restriction_count"]
        ],
        on=["model", "language", "scenario_id", "framing"],
    )
    assert (merged["disclosure_score"] - merged["disclosure_count"]).abs().max() < 1e-12
    assert (merged["restriction_score"] - merged["restriction_count"]).abs().max() < 1e-12


def test_aggregated_variance_is_std_squared(tmp_path: Path):
    input_dir, raw_dir = seed_mini_corpus(tmp_path)
    out_dir = tmp_path / "processed"
    rq1.export_rq1(input_dir, raw_dir, out_dir, basis="count", iterations=50, seed=1)
    aggregated = pd.read_csv(out_dir / "rq1_aggregated_metrics.csv")
    cell = aggregated[
        (aggregated["topic_origin"] == "All")
        & (aggregated["model"] == "claude-sonnet-5")
        & (aggregated["language"] == "en")
    ].iloc[0]
    assert cell["variance_disclosure"] == pytest.approx(
        cell["std_disclosure_score"] ** 2, abs=1e-12
    )


def test_invariant_errors_block_export(tmp_path: Path):
    input_dir, raw_dir = seed_mini_corpus(tmp_path)
    # Corrupt one tally so engagement/facts totals disagree.
    path = input_dir / "evaluation.us.en.csv"
    frame = pd.read_csv(path)
    frame.loc[0, "count_facts_true"] = int(frame.loc[0, "count_facts_true"]) + 1
    frame.to_csv(path, index=False)

    with pytest.raises(rq1.ExportError, match="invariant"):
        rq1.export_rq1(input_dir, raw_dir, tmp_path / "processed", "count", 50, 1)
