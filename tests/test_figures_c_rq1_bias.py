"""Tests for scripts/figures_c_rq1_bias.py — figures 10, 11, 13 and 14.

The script cross-checks the cell means in rq1_aggregated_metrics.csv against means
recomputed from rq1_response_scores.csv and refuses to draw if they disagree. That check
is the only thing between a mis-shaped aggregate and a plotted figure, and nothing
exercised it.

On 2026-10-08 rq1_export.py began rounding the scores it writes (SCORE_DECIMALS, added so
regenerated CSVs stay byte-stable across numpy/pandas builds). Rounding moved the two
files' agreement from ~1e-16 to ~2e-07, and the check — written for 1e-9, a precision
neither file has — started refusing every run. Figures 10, 11, 13 and 14 stopped
rendering from a clean checkout, and no test noticed, because no test ran this script.

So the check is tested from both sides here: it accepts the committed export, and it
still refuses a mis-shaped one. A guard that has never refused anything proves nothing;
neither does one that refuses everything.

These tests run the script in a subprocess. It is a top-level script rather than an
importable module, so the drawing cannot be isolated the way
scripts/figure_18_judge_consistency.py isolates it. One full render takes about two
seconds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("matplotlib", reason="the figure scripts need matplotlib to draw")

import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "figures_c_rq1_bias.py"
PROCESSED = REPO_ROOT / "data" / "processed"
SCENARIOS = REPO_ROOT / "data" / "scenarios.json"

# The aggregate keys a cell is identified by, and the columns that carry its numbers.
KEYS = ["model", "language", "framing"]
SCORE_COLUMNS = ["mean_disclosure_score", "mean_restriction_score", "refusal_rate"]

FIGURES = [
    "fig10_bias_score_by_model_language.png",
    "fig11_bias_score_distribution.png",
    "fig13_bias_score_by_framing.png",
    "fig14_event_bias_heatmap.png",
]


def run_figures(processed: Path, out_dir: Path) -> subprocess.CompletedProcess:
    """Run the figure script against `processed`, writing into `out_dir`."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(processed), str(SCENARIOS), str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def copy_export(tmp_path: Path) -> Path:
    """A writable copy of the export, so a test can mis-shape one file."""
    destination = tmp_path / "processed"
    destination.mkdir()
    for source in PROCESSED.iterdir():
        if source.is_file():
            shutil.copy(source, destination / source.name)
    return destination


def mis_shape_all_rows(processed: Path) -> None:
    """Give the topic_origin='All' rows the US-centric means.

    A realistic mis-shape: the right file with the right columns, holding the wrong slice
    of the data. It moves the cell means by 1.5e-02 to 7.7e-02, which is four orders of
    magnitude above the tolerance the check can work at.
    """
    path = processed / "rq1_aggregated_metrics.csv"
    frame = pd.read_csv(path)
    all_rows = frame["topic_origin"] == "All"
    us_rows = frame.loc[frame["topic_origin"] == "US-centric", KEYS + SCORE_COLUMNS]
    frame = pd.concat([
        frame.loc[~all_rows],
        frame.loc[all_rows].drop(columns=SCORE_COLUMNS).merge(us_rows, on=KEYS, how="left"),
    ]).sort_index()
    frame.to_csv(path, index=False)


def rewrite_manifest(processed: Path, **changes: object) -> None:
    """Edit the export manifest, dropping a key when its value is None."""
    path = processed / "rq1_export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            manifest.pop(key, None)
        else:
            manifest[key] = value
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def test_the_check_accepts_the_committed_export(tmp_path: Path) -> None:
    """The export on disk must draw. This is what broke on 2026-10-08."""
    out_dir = tmp_path / "figures"
    result = run_figures(PROCESSED, out_dir)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in out_dir.glob("*.png")) == sorted(FIGURES)


def test_the_check_refuses_a_mis_shaped_aggregate(tmp_path: Path) -> None:
    """Loosening the tolerance must not have cost the check its teeth."""
    processed = copy_export(tmp_path)
    mis_shape_all_rows(processed)
    out_dir = tmp_path / "figures"
    result = run_figures(processed, out_dir)
    assert result.returncode != 0, "a mis-shaped aggregate was plotted anyway"
    assert "disagree" in result.stderr
    assert not list(out_dir.glob("*.png")), "it refused, but only after drawing"


def test_the_tolerance_follows_the_declared_precision(tmp_path: Path) -> None:
    """A manifest declaring more decimals restores the strictness that broke the run.

    This is the control for the fix being a derivation rather than a hardcoded number: if
    the tolerance were fixed at 1e-06, declaring nine decimals would change nothing.
    """
    processed = copy_export(tmp_path)
    rewrite_manifest(processed, score_decimals=9)
    result = run_figures(processed, tmp_path / "figures")
    assert result.returncode != 0
    assert "1e-09" in result.stderr


def test_a_manifest_without_score_decimals_falls_back_to_six(tmp_path: Path) -> None:
    """Manifests predating the field still run, with a note rather than a crash.

    The 2026-10-05 export's manifest has no `score_decimals` (reachable at commit
    6d5f19d), so this is a real state of the repository, not a hypothetical one.
    """
    processed = copy_export(tmp_path)
    rewrite_manifest(processed, score_decimals=None)
    out_dir = tmp_path / "figures"
    result = run_figures(processed, out_dir)
    assert result.returncode == 0, result.stderr
    assert "declares no score_decimals" in result.stdout
    assert sorted(p.name for p in out_dir.glob("*.png")) == sorted(FIGURES)
