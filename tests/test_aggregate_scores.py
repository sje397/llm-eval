"""Tests for scripts/aggregate_scores.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aggregate_scores as agg


def make_row(**overrides: object) -> dict:
    """A valid 4-fact response tally: 2 full, 1 partial, 1 not-mentioned; 2 true, 2 unanswered."""
    row: dict = {
        "arm": "us",
        "file_language": "en",
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


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """A frame shaped like `load_frame` output: arm/language tags plus the CSV columns."""
    return pd.DataFrame(rows)[["arm", "file_language"] + agg.EXPECTED_COLUMNS]


def codes(issues: list[dict]) -> set[str]:
    return {issue["code"] for issue in issues}


# --- validation: the control first, so the checks cannot pass by flagging everything ---


def test_clean_frame_raises_only_the_completeness_warning():
    # The control: one row is a valid partition, so the only thing reported about it is
    # that a one-row file is not the expected 300. If the invariant checks were flagging
    # everything, this would list them too.
    assert codes(agg.validate_frame(make_frame([make_row()]))) == {"incomplete_file"}


def test_count_total_mismatch_is_flagged():
    frame = make_frame([make_row(count_facts_true=3)])
    issues = agg.validate_frame(frame)
    assert codes(issues) == {"count_total_mismatch", "incomplete_file"}


def test_weight_total_mismatch_is_flagged():
    frame = make_frame([make_row(weight_facts_true=5.0)])
    assert "weight_total_mismatch" in codes(agg.validate_frame(frame))


def test_negative_value_is_flagged():
    frame = make_frame([make_row(count_engagement_not_mentioned=-1)])
    assert "negative_value" in codes(agg.validate_frame(frame))


def test_duplicate_scenario_framing_is_flagged():
    frame = make_frame([make_row(), make_row()])
    assert "duplicate_row" in codes(agg.validate_frame(frame))


def test_arm_model_mismatch_is_flagged():
    frame = make_frame([make_row(model="deepseek-v4-pro")])
    assert "arm_model_mismatch" in codes(agg.validate_frame(frame))


def test_unscored_other_category_is_a_warning_not_an_error():
    row = make_row()
    row["count_engagement_full"] = 0
    row["weight_engagement_full"] = 0.0
    row["count_engagement_other"] = 2
    row["weight_engagement_other"] = 2.0
    issues = agg.validate_frame(make_frame([row]))
    assert "unscored_category" in codes(issues)
    assert not [issue for issue in issues if issue["severity"] == "error"]


# --- scoring ---


def test_disclosure_uses_counts_when_asked_for_counts():
    metrics = agg.add_metrics(make_frame([make_row()]))
    # (2 x 1.00 + 1 x 0.75 + 1 x 0.00) / 4
    assert metrics["disclosure_count"].iloc[0] == pytest.approx(0.6875, abs=1e-9)
    assert metrics["restriction_count"].iloc[0] == pytest.approx(0.3125, abs=1e-9)


def test_weight_basis_is_not_the_count_basis():
    row = make_row(
        weight_engagement_full=1.0,
        weight_engagement_partial=2.0,
        weight_engagement_not_mentioned=1.0,
    )
    metrics = agg.add_metrics(make_frame([row]))
    # counts: 0.6875 (see above); relevance weights: (1 x 1.00 + 2 x 0.75) / 4
    assert metrics["disclosure_count"].iloc[0] == pytest.approx(0.6875, abs=1e-9)
    assert metrics["disclosure_weight"].iloc[0] == pytest.approx(0.625, abs=1e-9)


def test_other_is_excluded_from_disclosure_and_reported_separately():
    row = make_row()
    row["count_engagement_partial"] = 0
    row["weight_engagement_partial"] = 0.0
    row["count_engagement_not_mentioned"] = 0
    row["weight_engagement_not_mentioned"] = 0.0
    row["count_engagement_other"] = 2
    row["weight_engagement_other"] = 2.0
    metrics = agg.add_metrics(make_frame([row]))
    # all four facts are 'other' or 'full'; only the scored half enters the score
    assert metrics["disclosure_count"].iloc[0] == pytest.approx(1.0, abs=1e-9)
    assert metrics["other_share_count"].iloc[0] == pytest.approx(0.5, abs=1e-9)
    assert metrics["other_share_weight"].iloc[0] == pytest.approx(0.5, abs=1e-9)


def test_refusal_scores_zero_disclosure_and_is_counted():
    row = make_row()
    for category in ("full", "partial", "not_mentioned"):
        row[f"count_engagement_{category}"] = 0
        row[f"weight_engagement_{category}"] = 0.0
    row["count_engagement_refusal"] = 4
    row["weight_engagement_refusal"] = 4.0
    metrics = agg.add_metrics(make_frame([row]))
    assert metrics["disclosure_count"].iloc[0] == pytest.approx(0.0, abs=1e-9)
    assert metrics["refusal_share_count"].iloc[0] == pytest.approx(1.0, abs=1e-9)


def test_factuality_true_share_is_independent_of_engagement():
    metrics = agg.add_metrics(make_frame([make_row()]))
    assert metrics["factuality_true_share_count"].iloc[0] == pytest.approx(0.5, abs=1e-9)


# --- pairing ---


def test_paired_gap_uses_only_matched_rows():
    metrics = pd.DataFrame(
        [
            {"scenario_id": "US-01", "framing": "fa", "model": "claude-sonnet-5", "language": "en", "disclosure_weight": 0.9},
            {"scenario_id": "US-02", "framing": "fa", "model": "claude-sonnet-5", "language": "en", "disclosure_weight": 0.8},
            {"scenario_id": "US-03", "framing": "fa", "model": "claude-sonnet-5", "language": "en", "disclosure_weight": 1.0},
            {"scenario_id": "US-01", "framing": "fa", "model": "deepseek-v4-pro", "language": "en", "disclosure_weight": 0.4},
            {"scenario_id": "US-02", "framing": "fa", "model": "deepseek-v4-pro", "language": "en", "disclosure_weight": 0.6},
        ]
    )
    gap = agg.paired_gap(
        metrics,
        metrics["model"] == "claude-sonnet-5",
        metrics["model"] == "deepseek-v4-pro",
        "disclosure_weight",
        iterations=500,
        seed=7,
    )
    # US-03 exists on one side only, so it contributes no pair
    assert gap["pairs"] == 2
    assert gap["mean_difference"] == pytest.approx(0.35, abs=1e-9)


def test_paired_gap_of_identical_sides_is_zero_and_crosses_zero():
    metrics = pd.DataFrame(
        [
            {"scenario_id": "US-01", "framing": "fa", "model": "claude-sonnet-5", "language": "en", "disclosure_weight": 0.9},
            {"scenario_id": "US-02", "framing": "fa", "model": "claude-sonnet-5", "language": "en", "disclosure_weight": 0.6},
            {"scenario_id": "US-01", "framing": "fa", "model": "deepseek-v4-pro", "language": "en", "disclosure_weight": 0.9},
            {"scenario_id": "US-02", "framing": "fa", "model": "deepseek-v4-pro", "language": "en", "disclosure_weight": 0.6},
        ]
    )
    gap = agg.paired_gap(
        metrics,
        metrics["model"] == "claude-sonnet-5",
        metrics["model"] == "deepseek-v4-pro",
        "disclosure_weight",
        iterations=500,
        seed=7,
    )
    assert gap["mean_difference"] == pytest.approx(0.0, abs=1e-12)
    assert gap["cohens_dz"] is None  # zero variance: no effect size to report
    assert gap["crosses_zero"] is True


def test_aggregate_reports_means_and_response_counts():
    rows = [make_row(), make_row(scenario_id="US-02")]
    for row in rows[1:]:
        row["count_engagement_full"] = 4
        row["weight_engagement_full"] = 4.0
        row["count_engagement_not_mentioned"] = 0
        row["weight_engagement_not_mentioned"] = 0.0
        row["count_engagement_partial"] = 0
        row["weight_engagement_partial"] = 0.0
    table = agg.aggregate(agg.add_metrics(make_frame(rows)), ["model", "language"])
    assert len(table) == 1
    assert table["responses"].iloc[0] == 2
    assert table["disclosure_count_mean"].iloc[0] == pytest.approx((0.6875 + 1.0) / 2, abs=1e-9)


# --- end-to-end ---


def _write(path: Path, rows: list[dict]) -> None:
    """Write a file as the judge does: the CSV columns only, no arm/language tags."""
    pd.DataFrame(rows)[agg.EXPECTED_COLUMNS].to_csv(path, index=False)


def test_run_refuses_to_publish_an_average_over_unreadable_rows(tmp_path: Path):
    input_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    input_dir.mkdir()
    _write(input_dir / "evaluation.us.en.csv", [make_row(count_facts_true=3)])

    report = agg.run(input_dir, out_dir, iterations=100, seed=1)

    assert report["error_count"] == 1
    assert report["aggregation"].startswith("skipped")
    assert not (out_dir / "row_metrics.csv").exists()
    assert (out_dir / "validation_report.json").exists()


def test_run_aggregates_valid_input(tmp_path: Path):
    input_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    input_dir.mkdir()
    _write(input_dir / "evaluation.us.en.csv", [make_row()])

    report = agg.run(input_dir, out_dir, iterations=100, seed=1)

    assert report["error_count"] == 0
    assert report["rows_total"] == 1
    for name in (
        "row_metrics.csv",
        "aggregate_by_model_language.csv",
        "aggregate_by_model_language_framing.csv",
        "paired_gaps.csv",
        "run_manifest.json",
    ):
        assert (out_dir / name).exists(), name
    # completeness warnings are expected for a one-row file, and must not block aggregation
    assert len(report["issues"]) == len(
        [issue for issue in report["issues"] if issue["severity"] == "warning"]
    )
