#!/usr/bin/env python3
"""
Batch runner for LLMEV-100.

1. Read scenarios from data/scenarios.json
2. Build every prompt (60 scenarios × 5 framings × 2 languages × 2 models)
3. Call the US or CN model for each prompt
4. Save results to data/raw/*.jsonl

Dev (no API keys):
    MOCK_MODE=true python scripts/run_batch.py

Production:
    python scripts/run_batch.py

See docs/running-scripts.md for full details.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

# --- paths -------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_FILE = REPO_ROOT / "data" / "scenarios.json"
ENDPOINTS_FILE = REPO_ROOT / "config" / "endpoints.yaml"
OUTPUT_DIR = REPO_ROOT / "data" / "raw"

MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() == "true"

# Which corpus this run produces. v1 is the 2026-09-06 collection at
# max_tokens=1024, which is frozen and must not be rewritten (see
# docs/corpus-provenance.md); v2 is the re-collection at MAX_TOKENS.
CORPUS_VERSION = "v2"

# Retry policy for transient transport and rate-limit failures. A 1,200-request
# run crosses several hours and one dropped connection should not end it.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5.0
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def git_sha() -> str | None:
    """Commit the collector was run from, or None outside a git checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return result.stdout.strip() or None


def sha256_file(path: Path) -> str | None:
    """Hash a file, or None if it is missing (a manifest must not invent one)."""
    if not path.exists():
        return None

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _relative_to_repo(path: Path) -> str:
    """Repo-relative path when possible, absolute otherwise (never raise here)."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# Provenance stamped onto every row, so a single row read on its own still says
# when it was collected and from which code. Resolved once at import.
RUN_DATE_UTC = datetime.now(timezone.utc).isoformat(timespec="seconds")
GIT_SHA = git_sha()

# Output-token budget per request.
#
# This was 1024, which is too small for these prompts and silently damaged the
# corpus: measured on 2026-09-17 by re-running the corpus's own prompts at the
# original settings, 23% of DeepSeek calls and ~2-3% of Claude calls hit the cap,
# and 14% of the stored DeepSeek rows contain no text at all because a hidden
# thinking block consumed the entire budget before any answer was emitted.
# Both providers put thinking tokens inside this budget; ask_model can only see
# the text block, so a cap hit leaves a truncated reply and no trace of why.
# 8192 leaves enough headroom that stop_reason == "end_turn" is the norm.
MAX_TOKENS = 8192

# 120s was too tight once max_tokens grew: a request that thinks for thousands of
# tokens before answering can exceed it.
REQUEST_TIMEOUT = 600

# stop_reason values the Anthropic-compatible APIs may return. Anything else is a
# vendor change we have not accounted for, and is raised rather than recorded.
STOP_REASONS = frozenset(
    {
        "end_turn",      # model finished its reply normally
        "max_tokens",    # reply was cut off at max_tokens -- data is incomplete
        "stop_sequence",
        "tool_use",
        "pause_turn",
        "refusal",
    }
)

MOCK_ENDPOINTS = {
    "us": {
        "base_url": "https://api.anthropic.com/v1/messages",
        "api_key": "mock",
        "model": "sonnet-5",
    },
    "cn": {
        "base_url": "https://api.deepseek.com/anthropic/v1/messages",
        "api_key": "mock",
        "model": "deepseek-v4-pro",
    },
}


# --- config ------------------------------------------------------------------


def load_endpoints() -> dict:
    """Load API settings from config/endpoints.yaml."""
    if ENDPOINTS_FILE.exists():
        with open(ENDPOINTS_FILE, encoding="utf-8") as f:
            return yaml.safe_load(f)

    if MOCK_MODE:
        return MOCK_ENDPOINTS

    sys.exit(f"Missing {ENDPOINTS_FILE}. Create it before running in production.")


# --- prompt building ---------------------------------------------------------


def render_prompt(template: str, event_name: str, verb_form: str) -> str:
    """Fill a framing template like 'What can you tell me about {event}?'."""
    return template.replace("{event}", event_name).replace("{verb}", verb_form)


def build_all_prompts(scenarios_data: dict) -> list[dict]:
    """
    Turn scenarios.json into runnable rows.

    Each row says which model to call and what prompt to send.
    Total rows: 60 × 5 × 2 languages × 2 models = 1,200.
    """
    framings = {framing["id"]: framing for framing in scenarios_data["framings"]}
    prompts = []

    for scenario in scenarios_data["scenarios"]:
        for framing_id, framing in framings.items():
            for language in ("en", "zh"):
                prompt_text = render_prompt(
                    framing[language],
                    scenario["event"][language],
                    scenario["verb_form"],
                )

                for model_name in ("us", "cn"):
                    prompts.append(
                        {
                            "scenario_id": scenario["id"],
                            "framing": framing_id,
                            "language": language,
                            "model_name": model_name,
                            "prompt": prompt_text,
                        }
                    )

    return prompts


def output_file(model_name: str, language: str, base_dir: Path = OUTPUT_DIR) -> Path:
    """
    One JSONL file per model + language pair, under the chosen corpus directory.

    base_dir is explicit so a re-collection can be written to a new versioned
    directory while the frozen v1 corpus is left untouched.
    """
    return base_dir / f"{model_name}.{language}.jsonl"


# --- api ---------------------------------------------------------------------


def validate_stop_reason(stop_reason: str) -> str:
    """
    Return stop_reason if the API reported a value we understand, else raise.

    Recording an unrecognised value as though it were ordinary would let a vendor
    change pass unnoticed; failing here instead makes it a build-time problem.
    """
    if stop_reason not in STOP_REASONS:
        raise ValueError(
            f"Unexpected stop_reason {stop_reason!r} from API. "
            f"Known values: {sorted(STOP_REASONS)}. "
            "Check the provider's docs before trusting this batch."
        )
    return stop_reason


def ask_model(endpoint: dict, prompt: str, max_tokens: int = MAX_TOKENS) -> dict:
    """
    Send one prompt to an Anthropic-compatible API.

    Returns {"text", "stop_reason", "usage"}. text is empty when the model emitted
    no text block -- which happens when a thinking block consumed the whole budget,
    so the caller must read stop_reason rather than infer anything from an empty
    string. All text blocks are joined: a reply can interleave text and thinking.
    """
    if MOCK_MODE:
        return {
            "text": f"[MOCK {endpoint['model']}] Response to: {prompt[:60]}...",
            "stop_reason": "end_turn",
            "usage": {},
            "response_model": endpoint["model"],
        }

    response = requests.post(
        endpoint["base_url"],
        headers={
            "Authorization": f"Bearer {endpoint['api_key']}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": endpoint["model"],
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    text = "".join(
        block["text"] for block in payload.get("content", []) if block.get("type") == "text"
    )

    return {
        "text": text,
        "stop_reason": validate_stop_reason(payload.get("stop_reason")),
        "usage": payload.get("usage", {}),
        # The model the provider says it served, which is the authoritative
        # snapshot identifier. Recorded rather than asserted: a model name in a
        # config file is a request, not a fact about what answered.
        "response_model": payload.get("model"),
    }


# --- output ------------------------------------------------------------------


def load_finished_prompts(file_path: Path) -> set[tuple[str, str]]:
    """Read prompts already saved in a JSONL file."""
    if not file_path.exists():
        return set()

    finished = set()
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            finished.add((record["scenario_id"], record["framing"]))

    return finished


def save_result(file_path: Path, record: dict) -> None:
    """Append one result row to a JSONL file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_record(
    job: dict, endpoint: dict, reply: dict, max_tokens: int = MAX_TOKENS
) -> dict:
    """
    Assemble one output row.

    stop_reason and usage travel with the response so a row can be checked later:
    stop_reason == "max_tokens" means the reply is incomplete, and for Claude
    usage.output_tokens_details.thinking_tokens shows how much of the budget was
    spent reasoning rather than answering.
    """
    text = reply["text"]

    return {
        "scenario_id": job["scenario_id"],
        "framing": job["framing"],
        "language": job["language"],
        "model": endpoint["model"],
        "response_model": reply.get("response_model"),
        "prompt": job["prompt"],
        "response": text,
        "stop_reason": reply["stop_reason"],
        "usage": reply["usage"],
        "max_tokens": max_tokens,
        "run_date_utc": RUN_DATE_UTC,
        "git_sha": GIT_SHA,
        "corpus_version": CORPUS_VERSION,
    }
    # No `refusal` field. v1 wrote one as `len(text.strip()) < 20`, which
    # labelled 84 truncated rows as refusals and missed all 159 rows carrying
    # the actual refusal template -- inverted on both counts, and read by
    # nothing. stop_reason supersedes it as the truncation signal, and refusal
    # is classified semantically from the reply text by the rubric. See
    # docs/corpus-provenance.md.


# --- retry ------------------------------------------------------------------


def ask_model_with_retry(
    endpoint: dict, prompt: str, max_tokens: int = MAX_TOKENS
) -> dict:
    """
    ask_model with a bounded retry on transient failures.

    A four-hour batch should not die on one dropped connection or one 429, and it
    must never write a partial reply: either ask_model returns a complete response
    or this raises and the caller records a failure.
    """
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return ask_model(endpoint, prompt, max_tokens)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in RETRYABLE_STATUS:
                raise
            last_error = exc
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc

        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise RuntimeError(f"gave up after {MAX_ATTEMPTS} attempts: {last_error}")


# --- ordering and manifest ---------------------------------------------------


def canonicalise(out_dir: Path, order: dict[tuple[str, str, str, str], int]) -> None:
    """
    Rewrite each file in canonical prompt order.

    Concurrent collection finishes jobs out of order, and a resumed run appends.
    Sorting here means v1 and v2 are row-comparable and a diff between them is
    meaningful rather than just noisy.
    """
    for path in sorted(out_dir.glob("*.jsonl")):
        parts = path.stem.split(".")
        if len(parts) != 2:
            continue
        model_name, language = parts

        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]

        rows.sort(
            key=lambda r: order.get(
                (model_name, language, r.get("scenario_id"), r.get("framing")), 10**9
            )
        )

        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_manifest(
    out_dir: Path,
    endpoints: dict,
    args: "argparse.Namespace",
    failures: list[str],
    stop_reasons: Counter,
) -> None:
    """
    Record the collection protocol inside the corpus itself.

    The point is that the report can state the protocol change as a finding
    instead of a reader having to infer it, and that nothing about how these rows
    were produced depends on remembering this conversation.
    """
    row_counts: dict[str, int] = {}
    empty_rows = 0
    total = 0

    for path in sorted(out_dir.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        row_counts[path.name] = len(rows)
        total += len(rows)
        empty_rows += sum(1 for r in rows if not str(r.get("response", "")).strip())

    manifest = {
        "corpus_version": CORPUS_VERSION,
        "label": args.label,
        "collected_at_utc": RUN_DATE_UTC,
        "git_sha": GIT_SHA,
        "collector": "scripts/run_batch.py",
        "max_tokens": MAX_TOKENS,
        "request_timeout_s": REQUEST_TIMEOUT,
        "workers": args.workers,
        "limit": args.limit,
        "endpoints": {
            name: {"base_url": cfg.get("base_url"), "model": cfg.get("model")}
            for name, cfg in endpoints.items()
        },
        "prompt_source": {
            "path": _relative_to_repo(SCENARIOS_FILE),
            "sha256": sha256_file(SCENARIOS_FILE),
        },
        "rows_total": total,
        "rows_per_file": row_counts,
        "stop_reason_counts": dict(stop_reasons),
        "rows_with_empty_response": empty_rows,
        "failures": failures,
        "supersedes": {
            "dir": "data/raw",
            "sha256": {
                path.name: sha256_file(path) for path in sorted(OUTPUT_DIR.glob("*.jsonl"))
            },
            "known_defects": [
                "max_tokens was 1024; a model that spends its budget in a hidden "
                "thinking block returns no text block at all, so 84 rows are empty "
                "truncation artefacts rather than model behaviour",
                "the refusal field was written as len(text.strip()) < 20, which is "
                "inverted: True on all 84 truncated rows, False on all 159 rows "
                "carrying the actual refusal template, and read by nothing",
                "no stop_reason or usage was recorded, so a truncated row cannot be "
                "told apart from a complete one after the fact",
            ],
        },
    }

    path = out_dir / "_protocol.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Manifest: {path}")


# --- main --------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect the llm-eval response corpus.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Corpus directory to write (default: data/raw). Use a NEW directory "
        "for a re-collection so the frozen v1 corpus is never rewritten.",
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Concurrent requests (default 1)."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after N new jobs, for a pilot."
    )
    parser.add_argument(
        "--label", default="", help="Free-text label recorded in the manifest."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    out_dir: Path = args.out_dir

    with open(SCENARIOS_FILE, encoding="utf-8") as f:
        scenarios_data = json.load(f)

    endpoints = load_endpoints()
    prompts = build_all_prompts(scenarios_data)

    order = {
        (job["model_name"], job["language"], job["scenario_id"], job["framing"]): index
        for index, job in enumerate(prompts)
    }

    mode = "MOCK" if MOCK_MODE else "LIVE"
    print(f"{mode} — {len(prompts)} prompts → {out_dir}/ (workers={args.workers})")

    finished_by_file: dict[Path, set[tuple[str, str]]] = {}
    pending: list[dict] = []
    skipped = 0

    for job in prompts:
        result_file = output_file(job["model_name"], job["language"], out_dir)
        if result_file not in finished_by_file:
            finished_by_file[result_file] = load_finished_prompts(result_file)

        if (job["scenario_id"], job["framing"]) in finished_by_file[result_file]:
            skipped += 1
            continue

        pending.append(job)

    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"{len(pending)} to collect, {skipped} already present")
    if not pending:
        canonicalise(out_dir, order)
        write_manifest(out_dir, endpoints, args, [], Counter())
        return

    write_lock = threading.Lock()
    written = 0
    failures: list[str] = []
    stop_reasons: Counter = Counter()

    def run_one(job: dict) -> None:
        nonlocal written
        endpoint = endpoints[job["model_name"]]
        label = f"{job['scenario_id']}/{job['framing']}/{job['language']}"

        try:
            reply = ask_model_with_retry(endpoint, job["prompt"])
        except Exception as exc:  # noqa: BLE001 -- reported, and never written
            with write_lock:
                failures.append(f"{label}: {exc}")
            print(f"FAILED {label}: {exc}", file=sys.stderr)
            return

        record = build_record(job, endpoint, reply)

        with write_lock:
            save_result(
                output_file(job["model_name"], job["language"], out_dir), record
            )
            written += 1
            stop_reasons[reply["stop_reason"]] += 1

            if reply["stop_reason"] == "max_tokens":
                print(
                    f"WARNING: {label} hit the {record['max_tokens']}-token cap "
                    "— response is incomplete",
                    file=sys.stderr,
                )
            elif not reply["text"].strip():
                print(
                    f"NOTE: {label} ended normally but produced no text",
                    file=sys.stderr,
                )

    if args.workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(run_one, pending))
    else:
        for job in pending:
            run_one(job)

    canonicalise(out_dir, order)
    write_manifest(out_dir, endpoints, args, failures, stop_reasons)

    print(f"Done: {written} written, {skipped} skipped, {len(failures)} failed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
