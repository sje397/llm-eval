"""Tests for scripts/run_batch.py."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_batch
from run_batch import (
    build_all_prompts,
    load_finished_prompts,
    render_prompt,
    validate_stop_reason,
)

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


# --- validate_stop_reason ----------------------------------------------------

def test_validate_stop_reason_accepts_known_values() -> None:
    for value in ("end_turn", "max_tokens", "stop_sequence", "tool_use", "refusal"):
        assert validate_stop_reason(value) == value


def test_validate_stop_reason_rejects_unknown_value() -> None:
    # A provider renaming or adding a stop reason must fail loudly, not be stored.
    with pytest.raises(ValueError, match="Unexpected stop_reason"):
        validate_stop_reason("content_filter")


def test_validate_stop_reason_rejects_none() -> None:
    # A response with no stop_reason at all is not the same as a normal one.
    with pytest.raises(ValueError, match="Unexpected stop_reason"):
        validate_stop_reason(None)


# --- ask_model ---------------------------------------------------------------

def make_endpoint() -> dict:
    return {"base_url": "https://example.invalid/v1/messages", "api_key": "k", "model": "m"}


@pytest.fixture
def captured_request(monkeypatch):
    """Stub requests.post, capturing the request body and returning a set payload."""
    box: dict = {}

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        box["url"] = url
        box["body"] = json
        box["timeout"] = timeout
        return FakeResponse(box["_payload"])

    monkeypatch.setattr(run_batch.requests, "post", fake_post)
    monkeypatch.setattr(run_batch, "MOCK_MODE", False)
    return box


def test_ask_model_returns_text_and_stop_reason(captured_request) -> None:
    captured_request["_payload"] = {
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"output_tokens": 3},
    }

    reply = run_batch.ask_model(make_endpoint(), "hi")

    assert reply["text"] == "hello"
    assert reply["stop_reason"] == "end_turn"
    assert reply["usage"] == {"output_tokens": 3}


def test_ask_model_joins_all_text_blocks(captured_request) -> None:
    # A reply can interleave text and thinking; keeping only the first text block
    # silently drops the rest.
    captured_request["_payload"] = {
        "content": [
            {"type": "text", "text": "part one. "},
            {"type": "thinking", "thinking": "secret"},
            {"type": "text", "text": "part two."},
        ],
        "stop_reason": "end_turn",
        "usage": {},
    }

    reply = run_batch.ask_model(make_endpoint(), "hi")

    assert reply["text"] == "part one. part two."


def test_ask_model_reports_cap_hit_with_no_text(captured_request) -> None:
    # The exact production failure: a thinking block eats the whole budget, the
    # provider returns no text block, and the old code stored "" with no reason.
    captured_request["_payload"] = {
        "content": [{"type": "thinking", "thinking": ""}],
        "stop_reason": "max_tokens",
        "usage": {"output_tokens": 1024},
    }

    reply = run_batch.ask_model(make_endpoint(), "hi")

    assert reply["text"] == ""
    assert reply["stop_reason"] == "max_tokens"


def test_ask_model_sends_requested_max_tokens(captured_request) -> None:
    captured_request["_payload"] = {
        "content": [{"type": "text", "text": "x"}],
        "stop_reason": "end_turn",
        "usage": {},
    }

    run_batch.ask_model(make_endpoint(), "hi", max_tokens=2048)

    assert captured_request["body"]["max_tokens"] == 2048


def test_default_max_tokens_is_above_the_cap_that_truncated_the_corpus(captured_request) -> None:
    captured_request["_payload"] = {
        "content": [{"type": "text", "text": "x"}],
        "stop_reason": "end_turn",
        "usage": {},
    }

    run_batch.ask_model(make_endpoint(), "hi")

    assert captured_request["body"]["max_tokens"] == run_batch.MAX_TOKENS
    assert run_batch.MAX_TOKENS > 1024


# --- build_record ------------------------------------------------------------

def test_build_record_carries_stop_reason_and_usage() -> None:
    job = {
        "scenario_id": "CN-01",
        "framing": "framing_a",
        "language": "zh",
        "prompt": "p",
    }
    endpoint = {"model": "deepseek-v4-pro"}
    reply = {
        "text": "some answer that is comfortably longer than twenty characters",
        "stop_reason": "end_turn",
        "usage": {"output_tokens": 42},
    }

    record = run_batch.build_record(job, endpoint, reply)

    assert record["stop_reason"] == "end_turn"
    assert record["usage"] == {"output_tokens": 42}
    assert record["model"] == "deepseek-v4-pro"
    assert record["max_tokens"] == run_batch.MAX_TOKENS
    assert record["refusal"] is False


def test_build_record_marks_a_truncated_empty_reply_as_not_a_refusal() -> None:
    # An empty reply cut off at the cap must not be readable as a refusal; the
    # stop_reason is what distinguishes them.
    job = {"scenario_id": "CN-01", "framing": "framing_a", "language": "zh", "prompt": "p"}
    reply = {"text": "", "stop_reason": "max_tokens", "usage": {"output_tokens": 1024}}

    record = run_batch.build_record(job, {"model": "deepseek-v4-pro"}, reply)

    assert record["stop_reason"] == "max_tokens"
    assert record["max_tokens"] == run_batch.MAX_TOKENS
