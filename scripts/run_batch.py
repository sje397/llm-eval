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

import json
import os
import sys
from pathlib import Path

import requests
import yaml

# --- paths -------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_FILE = REPO_ROOT / "data" / "scenarios.json"
ENDPOINTS_FILE = REPO_ROOT / "config" / "endpoints.yaml"
OUTPUT_DIR = REPO_ROOT / "data" / "raw"

MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() == "true"

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


def output_file(model_name: str, language: str) -> Path:
    """One JSONL file per model + language pair."""
    return OUTPUT_DIR / f"{model_name}.{language}.jsonl"


# --- api ---------------------------------------------------------------------


def ask_model(endpoint: dict, prompt: str) -> str:
    """Send one prompt to an Anthropic-compatible API and return the text reply."""
    if MOCK_MODE:
        return f"[MOCK {endpoint['model']}] Response to: {prompt[:60]}..."

    response = requests.post(
        endpoint["base_url"],
        headers={
            "Authorization": f"Bearer {endpoint['api_key']}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": endpoint["model"],
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    response.raise_for_status()

    for block in response.json().get("content", []):
        if block.get("type") == "text":
            return block["text"]

    return ""


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


# --- main --------------------------------------------------------------------


def main() -> None:
    with open(SCENARIOS_FILE, encoding="utf-8") as f:
        scenarios_data = json.load(f)

    endpoints = load_endpoints()
    prompts = build_all_prompts(scenarios_data)

    mode = "MOCK" if MOCK_MODE else "LIVE"
    print(f"{mode} — {len(prompts)} prompts → {OUTPUT_DIR}/")

    finished_by_file: dict[Path, set[tuple[str, str]]] = {}
    written = 0
    skipped = 0

    for job in prompts:
        result_file = output_file(job["model_name"], job["language"])
        job_key = (job["scenario_id"], job["framing"])

        if result_file not in finished_by_file:
            finished_by_file[result_file] = load_finished_prompts(result_file)

        if job_key in finished_by_file[result_file]:
            skipped += 1
            continue

        endpoint = endpoints[job["model_name"]]
        model_response = ask_model(endpoint, job["prompt"])

        save_result(
            result_file,
            {
                "scenario_id": job["scenario_id"],
                "framing": job["framing"],
                "language": job["language"],
                "model": endpoint["model"],
                "prompt": job["prompt"],
                "response": model_response,
                "refusal": len(model_response.strip()) < 20,
            },
        )

        finished_by_file[result_file].add(job_key)
        written += 1

    print(f"Done: {written} written, {skipped} skipped")


if __name__ == "__main__":
    main()
