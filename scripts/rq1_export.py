"""
LLMEV-107 — export Romit's RQ1 contract CSVs from the judge tallies.

Treats ``scripts/aggregate_scores.py`` (PR #26) as the scoring / validation
harness: disclosure and restriction come from its metrics; this script reshapes
them into the three files agreed for Section C figures.

Output (under ``--out-dir``, default ``data/processed/``)
--------------------------------------------------------
``rq1_response_scores.csv``         1 row per response (1,200)
``rq1_aggregated_metrics.csv``      model × language × framing × topic_origin
``rq1_statistical_comparisons.csv`` paired / topic-gap hypothesis tests

Conventions (analysis-spec §4 corrections)
-----------------------------------------
* ``scenario_id`` is ``CN-01`` / ``US-01`` form (not ``scenario_01``).
* ``language`` is lowercase ``en`` / ``zh``.
* ``topic_origin`` is ``US-centric`` | ``China-centric`` | ``All``.

Refusal (union of the two detectors that now agree on v2)
---------------------------------------------------------
* canned template match on the raw response text (see ``nonresponse_metrics``), or
* ``count_engagement_refusal > 0`` from the LLMEV-106 classifier.

Usage
-----
    python3 scripts/rq1_export.py
    python3 scripts/rq1_export.py --basis weight --bootstrap 10000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
for path in (REPO_ROOT, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import aggregate_scores as agg  # noqa: E402
from nonresponse_metrics import CANNED_TEMPLATES, is_canned, read_corpus  # noqa: E402

RESPONSE_COLUMNS = [
    "response_id",
    "scenario_id",
    "topic_origin",
    "model",
    "language",
    "framing",
    "disclosure_score",
    "restriction_score",
    "refusal_flag",
]

AGGREGATE_COLUMNS = [
    "model",
    "language",
    "framing",
    "topic_origin",
    "sample_size",
    "mean_disclosure_score",
    "std_disclosure_score",
    "variance_disclosure",
    "mean_restriction_score",
    "std_restriction_score",
    "refusal_rate",
]

COMPARISON_COLUMNS = [
    "comparison_type",
    "group_a",
    "group_b",
    "framing",
    "statistic",
    "p_value",
    "effect_size",
    "bias_score_gap",
]

FRAMINGS = ["framing_a", "framing_b", "framing_c", "framing_d", "framing_e"]
TOPIC_ORIGINS = ("China-centric", "US-centric")


class ExportError(RuntimeError):
    """Inputs cannot be turned into the RQ1 contract files."""


def topic_origin_from_scenario(scenario_id: str) -> str:
    prefix, _, _ = str(scenario_id).partition("-")
    if prefix == "CN":
        return "China-centric"
    if prefix == "US":
        return "US-centric"
    raise ExportError(f"scenario_id {scenario_id!r} has no CN-/US- origin prefix")


def load_canned_refusal_index(raw_dir: Path) -> dict[tuple[str, str, str, str], int]:
    """Map (model, language, scenario_id, framing) -> 1 if canned refusal else 0."""
    responses = read_corpus(raw_dir)
    return {
        (r.model, r.language, r.scenario_id, r.framing): int(is_canned(r.text, CANNED_TEMPLATES))
        for r in responses
    }


def build_response_scores(
    metrics: pd.DataFrame,
    canned_index: dict[tuple[str, str, str, str], int],
    basis: str,
) -> pd.DataFrame:
    """One contract row per evaluated response."""
    if basis not in ("count", "weight"):
        raise ExportError(f"basis must be 'count' or 'weight', got {basis!r}")

    rows = metrics.copy()
    rows["topic_origin"] = rows["scenario_id"].map(topic_origin_from_scenario)
    rows["disclosure_score"] = rows[f"disclosure_{basis}"].astype(float)
    rows["restriction_score"] = rows[f"restriction_{basis}"].astype(float)

    keys = list(
        zip(rows["model"], rows["language"], rows["scenario_id"], rows["framing"])
    )
    missing = [key for key in keys if key not in canned_index]
    if missing:
        sample = ", ".join(str(key) for key in missing[:5])
        raise ExportError(
            f"{len(missing)} evaluation row(s) missing from raw corpus, e.g. {sample}"
        )

    canned = np.array([canned_index[key] for key in keys], dtype=int)
    rubric_refusal = (rows["count_engagement_refusal"].astype(float) > 0).to_numpy().astype(int)
    rows["refusal_flag"] = np.maximum(canned, rubric_refusal)

    rows = rows.sort_values(
        ["model", "language", "scenario_id", "framing"], kind="mergesort"
    ).reset_index(drop=True)
    rows.insert(0, "response_id", [f"RESP_{i:04d}" for i in range(1, len(rows) + 1)])
    return rows[RESPONSE_COLUMNS]


def build_aggregated_metrics(scores: pd.DataFrame) -> pd.DataFrame:
    """Means / std / variance / refusal rate per model × language × framing × origin."""
    records: list[dict] = []
    group_cols = ["model", "language", "framing"]

    for keys, cell in scores.groupby(group_cols, dropna=False):
        model, language, framing = keys
        slices = [("All", cell)]
        for origin in TOPIC_ORIGINS:
            slices.append((origin, cell[cell["topic_origin"] == origin]))

        for origin, subset in slices:
            if subset.empty:
                continue
            disclosure = subset["disclosure_score"].to_numpy(dtype=float)
            restriction = subset["restriction_score"].to_numpy(dtype=float)
            records.append(
                {
                    "model": model,
                    "language": language,
                    "framing": framing,
                    "topic_origin": origin,
                    "sample_size": int(len(subset)),
                    "mean_disclosure_score": float(disclosure.mean()),
                    "std_disclosure_score": float(disclosure.std(ddof=1)) if len(subset) > 1 else 0.0,
                    "variance_disclosure": float(disclosure.var(ddof=1)) if len(subset) > 1 else 0.0,
                    "mean_restriction_score": float(restriction.mean()),
                    "std_restriction_score": float(restriction.std(ddof=1)) if len(subset) > 1 else 0.0,
                    "refusal_rate": float(subset["refusal_flag"].mean()),
                }
            )

    table = pd.DataFrame.from_records(records)
    return table.sort_values(
        ["model", "language", "framing", "topic_origin"], kind="mergesort"
    ).reset_index(drop=True)[AGGREGATE_COLUMNS]


def _paired_vectors(
    scores: pd.DataFrame,
    left_mask: pd.Series,
    right_mask: pd.Series,
) -> tuple[np.ndarray, np.ndarray]:
    index = ["scenario_id", "framing"]
    paired = pd.concat(
        {
            "left": scores.loc[left_mask].set_index(index)["disclosure_score"],
            "right": scores.loc[right_mask].set_index(index)["disclosure_score"],
        },
        axis=1,
    ).dropna()
    return paired["left"].to_numpy(dtype=float), paired["right"].to_numpy(dtype=float)


def _paired_test(
    left: np.ndarray,
    right: np.ndarray,
    iterations: int,
    seed: int,
) -> dict[str, float | None]:
    """Paired mean gap with t-statistic, shift-bootstrap p-value, Cohen's d_z."""
    if left.size == 0:
        return {
            "statistic": None,
            "p_value": None,
            "effect_size": None,
            "bias_score_gap": None,
        }

    differences = left - right
    mean = float(differences.mean())
    n = differences.size
    sd = float(differences.std(ddof=1)) if n > 1 else 0.0
    statistic = (mean / (sd / np.sqrt(n))) if sd else None
    effect = (mean / sd) if sd else None

    generator = np.random.default_rng(seed)
    if n == 1:
        p_value = 1.0
    else:
        # Shift-bootstrap under H0: mean difference = 0.
        # Add-one correction so a never-exceeded observed gap reads as
        # 1/(iterations+1) rather than an exact zero.
        centered = differences - mean
        boot_means = generator.choice(
            centered, size=(iterations, n), replace=True
        ).mean(axis=1)
        exceedances = int(np.sum(np.abs(boot_means) >= abs(mean)))
        p_value = (1 + exceedances) / (iterations + 1)

    return {
        "statistic": None if statistic is None else float(statistic),
        "p_value": p_value,
        "effect_size": None if effect is None else float(effect),
        "bias_score_gap": mean,
    }


def _unpaired_test(
    left: np.ndarray,
    right: np.ndarray,
    iterations: int,
    seed: int,
) -> dict[str, float | None]:
    """Unpaired mean gap (topic origin) with Welch-style t and bootstrap p."""
    if left.size == 0 or right.size == 0:
        return {
            "statistic": None,
            "p_value": None,
            "effect_size": None,
            "bias_score_gap": None,
        }

    mean_l = float(left.mean())
    mean_r = float(right.mean())
    gap = mean_l - mean_r
    n_l, n_r = left.size, right.size
    var_l = float(left.var(ddof=1)) if n_l > 1 else 0.0
    var_r = float(right.var(ddof=1)) if n_r > 1 else 0.0
    se = np.sqrt(var_l / n_l + var_r / n_r) if (n_l and n_r) else 0.0
    statistic = (gap / se) if se else None

    pooled = np.sqrt(
        ((n_l - 1) * var_l + (n_r - 1) * var_r) / max(n_l + n_r - 2, 1)
    )
    effect = (gap / pooled) if pooled else None

    generator = np.random.default_rng(seed)
    # Bootstrap the mean difference under the observed samples; p-value via
    # recentering so H0 is gap == 0.
    boot = np.empty(iterations, dtype=float)
    for i in range(iterations):
        boot[i] = (
            generator.choice(left, size=n_l, replace=True).mean()
            - generator.choice(right, size=n_r, replace=True).mean()
        )
    centered = boot - boot.mean()
    exceedances = int(np.sum(np.abs(centered) >= abs(gap)))
    p_value = (1 + exceedances) / (iterations + 1)

    return {
        "statistic": None if statistic is None else float(statistic),
        "p_value": p_value,
        "effect_size": None if effect is None else float(effect),
        "bias_score_gap": gap,
    }


def _framing_masks(scores: pd.DataFrame, framing: str) -> pd.Series:
    if framing == "All":
        return pd.Series(True, index=scores.index)
    return scores["framing"] == framing


def build_statistical_comparisons(
    scores: pd.DataFrame,
    iterations: int,
    seed: int,
) -> pd.DataFrame:
    """Model, language, and topic-origin hypothesis tests for the report tables."""
    records: list[dict] = []
    framing_levels = ["All", *FRAMINGS]
    languages = sorted(scores["language"].unique())
    models = sorted(scores["model"].unique())

    for framing in framing_levels:
        frame_mask = _framing_masks(scores, framing)

        for language in languages:
            left = frame_mask & (scores["model"] == "claude-sonnet-5") & (scores["language"] == language)
            right = frame_mask & (scores["model"] == "deepseek-v4-pro") & (scores["language"] == language)
            left_v, right_v = _paired_vectors(scores, left, right)
            stats = _paired_test(left_v, right_v, iterations, seed)
            records.append(
                {
                    "comparison_type": "model_comparison",
                    "group_a": f"claude-sonnet-5_{language}",
                    "group_b": f"deepseek-v4-pro_{language}",
                    "framing": framing,
                    **stats,
                }
            )

        for model in models:
            left = frame_mask & (scores["model"] == model) & (scores["language"] == "en")
            right = frame_mask & (scores["model"] == model) & (scores["language"] == "zh")
            left_v, right_v = _paired_vectors(scores, left, right)
            stats = _paired_test(left_v, right_v, iterations, seed)
            records.append(
                {
                    "comparison_type": "language_comparison",
                    "group_a": f"{model}_en",
                    "group_b": f"{model}_zh",
                    "framing": framing,
                    **stats,
                }
            )

        for model in models:
            for language in languages:
                cell = scores[frame_mask & (scores["model"] == model) & (scores["language"] == language)]
                left_v = cell.loc[cell["topic_origin"] == "US-centric", "disclosure_score"].to_numpy(
                    dtype=float
                )
                right_v = cell.loc[
                    cell["topic_origin"] == "China-centric", "disclosure_score"
                ].to_numpy(dtype=float)
                stats = _unpaired_test(left_v, right_v, iterations, seed)
                records.append(
                    {
                        "comparison_type": "topic_gap",
                        "group_a": f"{model}_{language}_US-centric",
                        "group_b": f"{model}_{language}_China-centric",
                        "framing": framing,
                        **stats,
                    }
                )

    return pd.DataFrame.from_records(records)[COMPARISON_COLUMNS]


def export_rq1(
    input_dir: Path,
    raw_dir: Path,
    out_dir: Path,
    basis: str,
    iterations: int,
    seed: int,
) -> dict:
    """Validate tallies, score them, and write the three contract CSVs."""
    frame = agg.load_frame(input_dir)
    issues = agg.validate_frame(frame)
    errors = [issue for issue in issues if issue["severity"] == "error"]
    if errors:
        raise ExportError(
            f"refusing to export: {len(errors)} invariant error(s) in evaluation tallies "
            f"(run scripts/aggregate_scores.py for the validation report)"
        )

    metrics = agg.add_metrics(frame)
    canned_index = load_canned_refusal_index(raw_dir)
    scores = build_response_scores(metrics, canned_index, basis)
    aggregated = build_aggregated_metrics(scores)
    comparisons = build_statistical_comparisons(scores, iterations, seed)

    out_dir.mkdir(parents=True, exist_ok=True)
    scores.to_csv(out_dir / "rq1_response_scores.csv", index=False)
    aggregated.to_csv(out_dir / "rq1_aggregated_metrics.csv", index=False)
    comparisons.to_csv(out_dir / "rq1_statistical_comparisons.csv", index=False)

    manifest = {
        "basis": basis,
        "bootstrap_iterations": iterations,
        "bootstrap_seed": seed,
        "score_mapping_version": agg.SCORE_MAPPING_VERSION,
        "pairing": "(scenario_id, framing) for model_comparison and language_comparison",
        "topic_gap": "unpaired US-centric vs China-centric within model × language",
        "refusal": "canned template OR count_engagement_refusal > 0",
        "rows": {
            "rq1_response_scores.csv": len(scores),
            "rq1_aggregated_metrics.csv": len(aggregated),
            "rq1_statistical_comparisons.csv": len(comparisons),
        },
        "refusal_total": int(scores["refusal_flag"].sum()),
        "languages": sorted(scores["language"].unique()),
        "models": sorted(scores["model"].unique()),
    }
    (out_dir / "rq1_export_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export Romit's RQ1 contract CSVs from judge tallies."
    )
    parser.add_argument("--input-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "processed")
    parser.add_argument(
        "--basis",
        choices=("count", "weight"),
        default="count",
        help="disclosure basis from aggregate_scores (default: count, per LLMEV-105)",
    )
    parser.add_argument("--bootstrap", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20261005)
    args = parser.parse_args(argv)

    try:
        manifest = export_rq1(
            args.input_dir,
            args.raw_dir,
            args.out_dir,
            args.basis,
            args.bootstrap,
            args.seed,
        )
    except (ExportError, agg.AggregateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote {manifest['rows']['rq1_response_scores.csv']} response scores, "
        f"{manifest['rows']['rq1_aggregated_metrics.csv']} aggregate rows, "
        f"{manifest['rows']['rq1_statistical_comparisons.csv']} comparisons "
        f"to {args.out_dir}"
    )
    print(
        f"basis={manifest['basis']} refusals={manifest['refusal_total']} "
        f"languages={manifest['languages']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
