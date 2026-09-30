"""Tests for scripts/run_batch.py."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import requests

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
    # `refusal` is absent by construction. v1 wrote it as len(text) < 20, which
    # was inverted on both counts; no length threshold can identify a refusal.
    assert "refusal" not in record
    assert record["corpus_version"] == run_batch.CORPUS_VERSION
    assert record["git_sha"] == run_batch.GIT_SHA
    assert record["run_date_utc"] == run_batch.RUN_DATE_UTC


def test_build_record_truncated_empty_reply_is_identifiable_without_a_flag() -> None:
    # An empty reply cut off at the cap must be tellable apart from a complete one,
    # and must not be labelled a refusal by a character count.
    job = {"scenario_id": "CN-01", "framing": "framing_a", "language": "zh", "prompt": "p"}
    reply = {"text": "", "stop_reason": "max_tokens", "usage": {"output_tokens": 1024}}

    record = run_batch.build_record(job, {"model": "deepseek-v4-pro"}, reply)

    assert record["stop_reason"] == "max_tokens"
    assert record["max_tokens"] == run_batch.MAX_TOKENS
    assert record["response"] == ""
    assert "refusal" not in record


# --- provenance --------------------------------------------------------------

def test_build_record_records_the_served_model_not_the_requested_one() -> None:
    # The name in the config is a request; the payload's model is what answered,
    # and only the latter is a snapshot identifier worth recording.
    job = {"scenario_id": "US-01", "framing": "framing_a", "language": "en", "prompt": "p"}
    reply = {
        "text": "an answer",
        "stop_reason": "end_turn",
        "usage": {},
        "response_model": "claude-sonnet-5-20260101",
    }

    record = run_batch.build_record(job, {"model": "claude-sonnet-5"}, reply)

    assert record["model"] == "claude-sonnet-5"
    assert record["response_model"] == "claude-sonnet-5-20260101"


def test_ask_model_captures_the_served_model(captured_request) -> None:
    captured_request["_payload"] = {
        "model": "claude-sonnet-5-20260101",
        "content": [{"type": "text", "text": "hi"}],
        "stop_reason": "end_turn",
        "usage": {},
    }

    assert run_batch.ask_model(make_endpoint(), "hi")["response_model"] == "claude-sonnet-5-20260101"


def test_ask_model_leaves_the_served_model_null_when_the_api_omits_it(captured_request) -> None:
    # Absent must surface as None. Inventing the configured name here would be
    # exactly the substitution this field exists to prevent.
    captured_request["_payload"] = {"content": [], "stop_reason": "end_turn", "usage": {}}

    assert run_batch.ask_model(make_endpoint(), "hi")["response_model"] is None


# --- retry -------------------------------------------------------------------

def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(str(status), response=response)


def test_retry_recovers_from_a_rate_limit(monkeypatch) -> None:
    calls = {"n": 0}

    def flaky(endpoint, prompt, max_tokens=run_batch.MAX_TOKENS):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429)
        return {"text": "ok", "stop_reason": "end_turn", "usage": {}, "response_model": "m"}

    monkeypatch.setattr(run_batch, "ask_model", flaky)
    monkeypatch.setattr(run_batch.time, "sleep", lambda _s: None)

    assert run_batch.ask_model_with_retry(make_endpoint(), "p")["text"] == "ok"
    assert calls["n"] == 2


def test_retry_does_not_retry_a_client_error(monkeypatch) -> None:
    # A 400 is our bug, not a transient failure; retrying it wastes an hour.
    calls = {"n": 0}

    def bad_request(endpoint, prompt, max_tokens=run_batch.MAX_TOKENS):
        calls["n"] += 1
        raise _http_error(400)

    monkeypatch.setattr(run_batch, "ask_model", bad_request)
    monkeypatch.setattr(run_batch.time, "sleep", lambda _s: None)

    with pytest.raises(requests.HTTPError):
        run_batch.ask_model_with_retry(make_endpoint(), "p")
    assert calls["n"] == 1


def test_retry_gives_up_loudly_rather_than_returning_a_partial(monkeypatch) -> None:
    def always_timeout(endpoint, prompt, max_tokens=run_batch.MAX_TOKENS):
        raise requests.Timeout("slow")

    monkeypatch.setattr(run_batch, "ask_model", always_timeout)
    monkeypatch.setattr(run_batch.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="gave up after"):
        run_batch.ask_model_with_retry(make_endpoint(), "p")


# --- ordering ----------------------------------------------------------------

def test_canonicalise_sorts_rows_into_prompt_order(tmp_path: Path) -> None:
    path = tmp_path / "us.en.jsonl"
    rows = [
        {"scenario_id": "US-02", "framing": "framing_a", "response": "b"},
        {"scenario_id": "US-01", "framing": "framing_a", "response": "a"},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    order = {
        ("us", "en", "US-01", "framing_a"): 0,
        ("us", "en", "US-02", "framing_a"): 1,
    }
    run_batch.canonicalise(tmp_path, order)

    with open(path, encoding="utf-8") as f:
        got = [json.loads(line)["scenario_id"] for line in f if line.strip()]

    assert got == ["US-01", "US-02"]


def test_canonicalise_tolerates_an_empty_directory(tmp_path: Path) -> None:
    run_batch.canonicalise(tmp_path, {})  # must not raise


# --- manifest ----------------------------------------------------------------

def test_manifest_records_the_protocol_and_never_a_credential(
    tmp_path: Path, monkeypatch
) -> None:
    v1 = tmp_path / "raw"
    v1.mkdir()
    (v1 / "us.en.jsonl").write_text('{"scenario_id": "US-01"}\n', encoding="utf-8")

    v2 = tmp_path / "raw-v2"
    v2.mkdir()
    (v2 / "us.en.jsonl").write_text(
        json.dumps({"scenario_id": "US-01", "response": "text"}) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(run_batch, "OUTPUT_DIR", v1)

    args = run_batch.parse_args(["--out-dir", str(v2), "--workers", "4", "--label", "pilot"])
    endpoints = {
        "us": {
            "base_url": "https://api.anthropic.com/v1/messages",
            "api_key": "sk-do-not-write-this",
            "model": "claude-sonnet-5",
        }
    }

    run_batch.write_manifest(v2, endpoints, args, [], Counter({"end_turn": 1}))

    raw = (v2 / "_protocol.json").read_text(encoding="utf-8")
    manifest = json.loads(raw)

    assert manifest["max_tokens"] == run_batch.MAX_TOKENS
    assert manifest["workers"] == 4
    assert manifest["label"] == "pilot"
    assert manifest["corpus_version"] == run_batch.CORPUS_VERSION
    assert manifest["stop_reason_counts"] == {"end_turn": 1}
    assert manifest["rows_with_empty_response"] == 0
    assert manifest["rows_total"] == 1

    # v1's frozen hashes travel with v2, and its defects are stated not implied
    assert "us.en.jsonl" in manifest["supersedes"]["sha256"]
    assert len(manifest["supersedes"]["known_defects"]) == 3

    # the protocol is recorded in the corpus, but no credential is
    assert "sk-do-not-write-this" not in raw


# --- end to end --------------------------------------------------------------

def test_main_writes_a_new_corpus_and_leaves_v1_byte_identical(
    tmp_path: Path, monkeypatch
) -> None:
    v1 = tmp_path / "raw"
    v1.mkdir()
    (v1 / "us.en.jsonl").write_text(
        '{"scenario_id": "US-01", "framing": "framing_a"}\n', encoding="utf-8"
    )
    before = {p.name: p.read_bytes() for p in v1.glob("*.jsonl")}

    monkeypatch.setattr(run_batch, "MOCK_MODE", True)
    monkeypatch.setattr(run_batch, "OUTPUT_DIR", v1)
    monkeypatch.setattr(run_batch, "ENDPOINTS_FILE", tmp_path / "absent.yaml")

    v2 = tmp_path / "raw-v2"
    run_batch.main(["--out-dir", str(v2), "--limit", "4"])

    # the frozen corpus is untouched, byte for byte
    assert {p.name: p.read_bytes() for p in v1.glob("*.jsonl")} == before

    rows = [
        json.loads(line)
        for path in sorted(v2.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(rows) == 4
    assert all(row["stop_reason"] == "end_turn" for row in rows)
    assert all("refusal" not in row for row in rows)
    assert all(row["corpus_version"] == run_batch.CORPUS_VERSION for row in rows)
    assert (v2 / "_protocol.json").exists()
