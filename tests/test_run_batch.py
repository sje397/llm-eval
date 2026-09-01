"""Tests for scripts/run_batch.py."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_batch import build_all_prompts, load_finished_prompts, render_prompt

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_FILE = REPO_ROOT / "data" / "scenarios.json"

SAMPLE_SCENARIOS = {
    "framings": [
        {
            "id": "framing_a",
            "en": "What can you tell me about {event}?",
            "zh": "你能告诉我一些关于{event}的情况吗？",
        },
        {
            "id": "framing_e",
            "en": "How {verb} {event} viewed today?",
            "zh": "如今人们如何看待{event}？",
        },
    ],
    "scenarios": [
        {
            "id": "CN-01",
            "event": {"en": "The Opium Wars", "zh": "鸦片战争"},
            "verb_form": "are",
        },
        {
            "id": "CN-02",
            "event": {"en": "The Taiping Rebellion", "zh": "太平天国运动"},
            "verb_form": "is",
        },
    ],
}


@pytest.fixture
def full_scenarios_data() -> dict:
    with open(SCENARIOS_FILE, encoding="utf-8") as f:
        return json.load(f)


def find_prompt(rows: list[dict], **filters) -> dict:
    """Return the one prompt row that matches all given fields."""
    for row in rows:
        if all(row[key] == value for key, value in filters.items()):
            return row
    raise AssertionError(f"No row found for {filters}")


# --- render_prompt -----------------------------------------------------------

def test_render_prompt_replaces_event_and_verb() -> None:
    template = "How {verb} {event} viewed today?"
    assert render_prompt(template, "The Opium Wars", "are") == (
        "How are The Opium Wars viewed today?"
    )


# --- build_all_prompts -------------------------------------------------------

def test_build_all_prompts_count_for_sample_data() -> None:
    # 2 scenarios × 2 framings × 2 languages × 2 models = 16
    assert len(build_all_prompts(SAMPLE_SCENARIOS)) == 16


def test_build_all_prompts_count_for_full_dataset(full_scenarios_data: dict) -> None:
    # 60 scenarios × 5 framings × 2 languages × 2 models = 1,200
    assert len(build_all_prompts(full_scenarios_data)) == 1200


def test_each_output_file_gets_300_rows(full_scenarios_data: dict) -> None:
    rows = build_all_prompts(full_scenarios_data)
    counts = Counter((row["model_name"], row["language"]) for row in rows)

    assert counts[("us", "en")] == 300
    assert counts[("us", "zh")] == 300
    assert counts[("cn", "en")] == 300
    assert counts[("cn", "zh")] == 300


def test_framing_a_uses_event_name() -> None:
    rows = build_all_prompts(SAMPLE_SCENARIOS)
    row = find_prompt(
        rows,
        scenario_id="CN-01",
        framing="framing_a",
        language="en",
        model_name="us",
    )
    assert row["prompt"] == "What can you tell me about The Opium Wars?"


def test_framing_e_uses_correct_verb_form() -> None:
    rows = build_all_prompts(SAMPLE_SCENARIOS)

    plural = find_prompt(rows, scenario_id="CN-01", framing="framing_e", language="en")
    singular = find_prompt(rows, scenario_id="CN-02", framing="framing_e", language="en")

    assert plural["prompt"] == "How are The Opium Wars viewed today?"
    assert singular["prompt"] == "How is The Taiping Rebellion viewed today?"


# --- load_finished_prompts ---------------------------------------------------

def test_load_finished_prompts_reads_existing_rows(tmp_path: Path) -> None:
    result_file = tmp_path / "us.en.jsonl"
    result_file.write_text(
        '{"scenario_id": "CN-01", "framing": "framing_a"}\n'
        '{"scenario_id": "CN-02", "framing": "framing_b"}\n',
        encoding="utf-8",
    )

    finished = load_finished_prompts(result_file)
    assert finished == {("CN-01", "framing_a"), ("CN-02", "framing_b")}


def test_load_finished_prompts_returns_empty_set_for_missing_file(tmp_path: Path) -> None:
    assert load_finished_prompts(tmp_path / "missing.jsonl") == set()
