"""
LLMEV-107 analysis stage — validate and aggregate the judge's per-response tallies.

Input
-----
``data/evaluation.{us,cn}.{en,zh}.csv``: one row per
``(model, language, scenario_id, framing)``, written by ``scripts/judge_pipeline.py``.
A row is a tally, not a per-fact record: for each ground-truth fact in the response
the judge assigned exactly one engagement category and exactly one factuality
category. The counts and the relevance weights are therefore two partitions of the
*same* fact set, which makes their totals checkable invariants:

    sum(count_engagement_*) == sum(count_facts_*)      # every fact classified in both families
    sum(weight_engagement_*) == sum(weight_facts_*)    # the same total relevance, split two ways

A violated total means the row cannot be read as a partition. Such a row is reported
and aggregation is refused rather than a mean published over an unreadable record.

Output (under ``--out-dir``, default ``data/scores/``)
------------------------------------------------------
``validation_report.json``                    completeness, duplicates, invariant violations
``row_metrics.csv``                           per-response disclosure/restriction/refusal
``aggregate_by_model_language.csv``           means by model and language
``aggregate_by_model_language_framing.csv``   means by model, language and framing
``paired_gaps.csv``                           paired model and language comparisons
``run_manifest.json``                         inputs, hashes, mapping version, pairing

The unit of analysis is the response, and 300 responses per file is a 60-scenario ×
5-framing design, so responses are **not** independent draws. Every comparison in
``paired_gaps.csv`` is paired on ``(scenario_id, framing)`` — which this design
supports, because both models answered the same scenario/framing grid — and the
interval is a bootstrap of the per-pair differences rather than Student-t, so no
normality of those differences is assumed.

Usage
-----
    python3 scripts/aggregate_scores.py                      # validate + aggregate
    python3 scripts/aggregate_scores.py --validate-only      # pilot checks only
    python3 scripts/aggregate_scores.py --strict             # exit 1 if any invariant fails
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.score_mapping import (  # noqa: E402  (path set above)
    DISCLOSURE_SCORE_MAP,
    SCORE_MAPPING_VERSION,
)

# The judge's CSV abbreviates the codebook names, so FULL_ENGAGEMENT is column
# `count_engagement_full`. Derived from score_mapping.py rather than restated, so the
# mapping stays the single source of truth; a name that fails to match shows up as a
# missing column at load time rather than as a silently zero score.
SCORES = {
    key.lower().replace("_engagement", ""): score
    for key, score in DISCLOSURE_SCORE_MAP.items()
}
# Categories that carry a disclosure score, in the order the CSV columns list them.
SCORED_ENGAGEMENT = list(SCORES)
# Counted by the judge but outside the codebook, so deliberately unscored.
UNSCORED_ENGAGEMENT = ["other"]
ENGAGEMENT_CATEGORIES = SCORED_ENGAGEMENT + UNSCORED_ENGAGEMENT
FACTUALITY_CATEGORIES = ["true", "false", "not_answered", "other"]

ID_COLUMNS = ["model", "language", "scenario_id", "framing"]
VALUE_COLUMNS = [
    f"{prefix}_{family}_{category}"
    for prefix in ("count", "weight")
    for family, categories in (
        ("engagement", ENGAGEMENT_CATEGORIES),
        ("facts", FACTUALITY_CATEGORIES),
    )
    for category in categories
]
EXPECTED_COLUMNS = ID_COLUMNS + VALUE_COLUMNS

# One file is one model arm × one language: 60 scenarios × 5 framings.
EXPECTED_ROWS_PER_FILE = 300
EXPECTED_SCENARIOS = 60
EXPECTED_FRAMINGS = 5

# An arm's identity is carried by the file, and the model column must agree with it.
# This is what makes the corpus's model-per-arm design checkable rather than assumed.
ARM_MODEL = {"us": "claude-sonnet-5", "cn": "deepseek-v4-pro"}

TOLERANCE = 1e-6

METRIC_COLUMNS = [
    "disclosure_count",
    "disclosure_weight",
    "restriction_count",
    "restriction_weight",
    "refusal_share_count",
    "refusal_share_weight",
    "other_share_count",
    "other_share_weight",
    "factuality_true_share_count",
    "factuality_true_share_weight",
]


class AggregateError(RuntimeError):
    """Input cannot be aggregated at all (unreadable file, wrong schema)."""


# --------------------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------------------


def arm_language_from_name(path: Path) -> tuple[str, str]:
    """``evaluation.us.en.csv`` -> ``('us', 'en')``."""
    parts = path.name.split(".")
    if len(parts) != 4 or parts[0] != "evaluation":
        raise AggregateError(f"{path.name}: expected a name like evaluation.<arm>.<language>.csv")
    return parts[1], parts[2]


def load_frame(input_dir: Path) -> pd.DataFrame:
    """Read every evaluation CSV in *input_dir* into one frame, tagged with arm and language."""
    files = sorted(input_dir.glob("evaluation.*.csv"))
    if not files:
        raise AggregateError(f"no evaluation.*.csv files found in {input_dir}")

    frames = []
    for path in files:
        arm, language = arm_language_from_name(path)
        frame = pd.read_csv(path)
        missing = [column for column in EXPECTED_COLUMNS if column not in frame.columns]
        if missing:
            raise AggregateError(f"{path.name}: missing column(s) {missing}")
        unexpected = [column for column in frame.columns if column not in EXPECTED_COLUMNS]
        if unexpected:
            raise AggregateError(f"{path.name}: unexpected column(s) {unexpected}")
        frame = frame.copy()
        frame.insert(0, "arm", arm)
        frame.insert(1, "file_language", language)
        frames.append(frame)

    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------------------


def _issue(severity: str, code: str, detail: str, **where: object) -> dict:
    return {"severity": severity, "code": code, "detail": detail, **where}


def _location(row: pd.Series) -> dict:
    return {
        "arm": row["arm"],
        "model": row["model"],
        "language": row["language"],
        "scenario_id": row["scenario_id"],
        "framing": row["framing"],
    }


def validate_row(row: pd.Series) -> list[dict]:
    """Invariants that must hold for a single response tallied by the judge."""
    issues: list[dict] = []
    where = _location(row)

    negatives = [column for column in VALUE_COLUMNS if float(row[column]) < 0]
    if negatives:
        issues.append(_issue("error", "negative_value", f"negative in {negatives}", **where))

    if float(row["count_engagement_other"]) or float(row["count_facts_other"]):
        issues.append(
            _issue(
                "warning",
                "unscored_category",
                "judge returned 'other' for at least one fact; those facts carry no "
                "disclosure score and are excluded from it (see other_share_*)",
                **where,
            )
        )

    count_engagement = float(row[[f"count_engagement_{c}" for c in ENGAGEMENT_CATEGORIES]].sum())
    count_facts = float(row[[f"count_facts_{c}" for c in FACTUALITY_CATEGORIES]].sum())
    if abs(count_engagement - count_facts) > TOLERANCE:
        issues.append(
            _issue(
                "error",
                "count_total_mismatch",
                f"sum(count_engagement_*)={count_engagement:g} != "
                f"sum(count_facts_*)={count_facts:g}: the two families do not describe "
                f"the same fact set",
                **where,
            )
        )
    if count_engagement == 0:
        issues.append(_issue("error", "no_facts", "row classifies zero facts", **where))

    weight_engagement = float(row[[f"weight_engagement_{c}" for c in ENGAGEMENT_CATEGORIES]].sum())
    weight_facts = float(row[[f"weight_facts_{c}" for c in FACTUALITY_CATEGORIES]].sum())
    if abs(weight_engagement - weight_facts) > 1e-4:
        issues.append(
            _issue(
                "error",
                "weight_total_mismatch",
                f"sum(weight_engagement_*)={weight_engagement:g} != "
                f"sum(weight_facts_*)={weight_facts:g}",
                **where,
            )
        )

    return issues


def validate_frame(frame: pd.DataFrame) -> list[dict]:
    """Frame-level checks: arm/model agreement, duplicates, and completeness."""
    issues: list[dict] = []

    for (arm, file_language), group in frame.groupby(["arm", "file_language"]):
        expected_model = ARM_MODEL.get(arm)
        if expected_model and not set(group["model"]) == {expected_model}:
            issues.append(
                _issue(
                    "error",
                    "arm_model_mismatch",
                    f"arm '{arm}' should hold only {expected_model}, found "
                    f"{sorted(set(group['model']))}",
                    arm=arm,
                    language=file_language,
                )
            )
        if not set(group["language"]) == {file_language}:
            issues.append(
                _issue(
                    "error",
                    "file_language_mismatch",
                    f"file says language '{file_language}', rows say "
                    f"{sorted(set(group['language']))}",
                    arm=arm,
                    language=file_language,
                )
            )

        duplicated = group[group.duplicated(subset=["scenario_id", "framing"], keep=False)]
        for _, row in duplicated.iterrows():
            issues.append(
                _issue(
                    "error",
                    "duplicate_row",
                    "two rows for the same scenario/framing; an average over these "
                    "would count one response twice",
                    arm=arm,
                    language=file_language,
                    scenario_id=row["scenario_id"],
                    framing=row["framing"],
                )
            )

        scenarios = sorted(group["scenario_id"].unique())
        framings = sorted(group["framing"].unique())
        present = set(zip(group["scenario_id"], group["framing"]))
        absent = [
            f"{scenario}/{framing}"
            for scenario in scenarios
            for framing in framings
            if (scenario, framing) not in present
        ]
        if absent:
            issues.append(
                _issue(
                    "warning",
                    "missing_cells",
                    f"{len(absent)} scenario/framing cell(s) absent, e.g. {absent[:5]}",
                    arm=arm,
                    language=file_language,
                )
            )
        if (
            len(group) != EXPECTED_ROWS_PER_FILE
            or len(scenarios) != EXPECTED_SCENARIOS
            or len(framings) != EXPECTED_FRAMINGS
        ):
            issues.append(
                _issue(
                    "warning",
                    "incomplete_file",
                    f"{len(group)} row(s) over {len(scenarios)} scenario(s) x "
                    f"{len(framings)} framing(s), expected {EXPECTED_ROWS_PER_FILE} "
                    f"({EXPECTED_SCENARIOS} x {EXPECTED_FRAMINGS})",
                    arm=arm,
                    language=file_language,
                )
            )

    for _, row in frame.iterrows():
        issues.extend(validate_row(row))

    return issues


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------


def shares(frame: pd.DataFrame, family: str, basis: str) -> pd.DataFrame:
    """Share of a response's facts (or relevance weight) in each category of *family*."""
    prefix = "count" if basis == "count" else "weight"
    categories = ENGAGEMENT_CATEGORIES if family == "engagement" else FACTUALITY_CATEGORIES
    values = frame[[f"{prefix}_{family}_{category}" for category in categories]].astype(float)
    totals = values.sum(axis=1)
    result = values.div(totals, axis=0).fillna(0.0)
    # Keyed by category, so callers index by codebook name rather than by CSV column name.
    result.columns = categories
    return result


def add_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Per-response metrics on both the count and the relevance-weight basis.

    Disclosure is a weighted mean of the scored categories only: an 'other' mass is
    excluded from numerator and denominator, so ``other_share_*`` reports how much of
    a response the codebook did not cover. Scoring 'other' would be a design decision
    rather than a derivation, so it is not taken here.
    """
    out = frame.copy()
    scores = np.array([SCORES[category] for category in SCORED_ENGAGEMENT])

    for basis in ("count", "weight"):
        engagement = shares(frame, "engagement", basis)
        scored = engagement[SCORED_ENGAGEMENT]
        # Conditional on what the codebook could classify: an 'other' mass is dropped
        # from numerator and denominator rather than scored as zero disclosure, and
        # other_share_* reports its size. A row with no scored facts reads 0.0 — the
        # lowest reading, made visible by other_share_* = 1.0 rather than left blank.
        disclosure = scored.div(scored.sum(axis=1), axis=0).fillna(0.0).to_numpy() @ scores
        out[f"disclosure_{basis}"] = disclosure
        out[f"restriction_{basis}"] = 1.0 - disclosure
        out[f"refusal_share_{basis}"] = engagement["refusal"].to_numpy()
        out[f"other_share_{basis}"] = engagement["other"].to_numpy()
        out[f"factuality_true_share_{basis}"] = shares(frame, "facts", basis)["true"].to_numpy()

    return out


def aggregate(metrics: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    """Mean and standard deviation of every metric, plus the number of responses pooled."""
    grouped = metrics.groupby(group_columns, dropna=False)[METRIC_COLUMNS].agg(["mean", "std"])
    grouped.columns = [f"{metric}_{stat}" for metric, stat in grouped.columns]
    grouped = grouped.reset_index()
    # Every metric is computed over the same rows, so one count column carries the cell size.
    grouped.insert(
        len(group_columns), "responses", metrics.groupby(group_columns, dropna=False).size().to_numpy()
    )
    return grouped


# --------------------------------------------------------------------------------------
# paired comparisons
# --------------------------------------------------------------------------------------


def paired_gap(
    metrics: pd.DataFrame,
    left: pd.Series,
    right: pd.Series,
    metric: str,
    iterations: int,
    seed: int,
) -> dict:
    """
    Mean paired difference (left − right) over ``(scenario_id, framing)``, with a
    bootstrap confidence interval and Cohen's d for paired samples.
    """
    index = ["scenario_id", "framing"]
    paired = pd.concat(
        {
            "left": metrics[left].set_index(index)[metric],
            "right": metrics[right].set_index(index)[metric],
        },
        axis=1,
    ).dropna()
    differences = (paired["left"] - paired["right"]).to_numpy()
    if differences.size == 0:
        return {"pairs": 0}

    generator = np.random.default_rng(seed)
    resampled_means = generator.choice(
        differences, size=(iterations, differences.size), replace=True
    ).mean(axis=1)
    mean = float(differences.mean())
    standard_deviation = float(differences.std(ddof=1)) if differences.size > 1 else 0.0
    low = float(np.percentile(resampled_means, 2.5))
    high = float(np.percentile(resampled_means, 97.5))
    return {
        "pairs": int(differences.size),
        "mean_difference": mean,
        "sd_difference": standard_deviation,
        "cohens_dz": (mean / standard_deviation) if standard_deviation else None,
        "ci95_low": low,
        "ci95_high": high,
        "crosses_zero": bool(low <= 0.0 <= high),
    }


def build_gaps(metrics: pd.DataFrame, iterations: int, seed: int) -> pd.DataFrame:
    """
    RQ1 comparisons, paired on ``(scenario_id, framing)``.

    Model gap: claude-sonnet-5 minus deepseek-v4-pro, within each language.
    Language gap: english minus mandarin, within each model.
    """
    records = []
    for metric in ("disclosure_weight", "disclosure_count"):
        for language in sorted(metrics["language"].unique()):
            gap = paired_gap(
                metrics,
                (metrics["model"] == "claude-sonnet-5") & (metrics["language"] == language),
                (metrics["model"] == "deepseek-v4-pro") & (metrics["language"] == language),
                metric,
                iterations,
                seed,
            )
            records.append({"comparison": "model", "language": language, "metric": metric, **gap})

        for model in sorted(metrics["model"].unique()):
            gap = paired_gap(
                metrics,
                (metrics["model"] == model) & (metrics["language"] == "en"),
                (metrics["model"] == model) & (metrics["language"] == "zh"),
                metric,
                iterations,
                seed,
            )
            records.append({"comparison": "language", "model": model, "metric": metric, **gap})

    return pd.DataFrame(records)


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(input_dir: Path, out_dir: Path, iterations: int, seed: int) -> dict:
    """Validate the evaluation CSVs and, if they are readable as partitions, aggregate them."""
    inputs = {
        path.name: {"sha256": file_digest(path), "rows": sum(1 for _ in path.open()) - 1}
        for path in sorted(input_dir.glob("evaluation.*.csv"))
    }
    frame = load_frame(input_dir)
    issues = validate_frame(frame)
    errors = [issue for issue in issues if issue["severity"] == "error"]

    report: dict = {
        "inputs": inputs,
        "rows_total": len(frame),
        "score_mapping_version": SCORE_MAPPING_VERSION,
        "issues": issues,
        "error_count": len(errors),
        "warning_count": len(issues) - len(errors),
    }

    out_dir.mkdir(parents=True, exist_ok=True)

    if errors:
        report["aggregation"] = "skipped: invariant errors present"
    else:
        metrics = add_metrics(frame)
        metrics.to_csv(out_dir / "row_metrics.csv", index=False)
        aggregate(metrics, ["model", "language"]).to_csv(
            out_dir / "aggregate_by_model_language.csv", index=False
        )
        aggregate(metrics, ["model", "language", "framing"]).to_csv(
            out_dir / "aggregate_by_model_language_framing.csv", index=False
        )
        gaps = build_gaps(metrics, iterations, seed)
        gaps.to_csv(out_dir / "paired_gaps.csv", index=False)
        report["aggregation"] = f"{len(metrics)} row(s) aggregated"
        report["outputs"] = sorted(
            path.name for path in out_dir.iterdir() if path.is_file()
        )
        (out_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "bootstrap_iterations": iterations,
                    "bootstrap_seed": seed,
                    "pairing": "(scenario_id, framing)",
                    "score_mapping_version": SCORE_MAPPING_VERSION,
                    "inputs": inputs,
                },
                indent=2,
            )
            + "\n"
        )

    (out_dir / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and aggregate the judge's per-response tallies."
    )
    parser.add_argument("--input-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "scores")
    parser.add_argument("--bootstrap", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--strict", action="store_true", help="exit 1 on any invariant error")
    parser.add_argument(
        "--validate-only", action="store_true", help="run the pilot checks and write nothing"
    )
    args = parser.parse_args(argv)

    frame = load_frame(args.input_dir)
    issues = validate_frame(frame)
    for issue in issues:
        location = "/".join(
            str(issue[key]) for key in ("arm", "language", "scenario_id", "framing") if key in issue
        )
        print(f"[{issue['severity']}] {issue['code']} {location}: {issue['detail']}")

    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    print(f"\n{len(frame)} row(s) read, {len(errors)} error(s), {len(warnings)} warning(s)")

    if not args.validate_only:
        report = run(args.input_dir, args.out_dir, args.bootstrap, args.seed)
        print(f"aggregation: {report['aggregation']}")
        if report["error_count"] == 0:
            print(f"outputs written to {args.out_dir}")

    return 1 if (errors and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
