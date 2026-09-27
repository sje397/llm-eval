"""Tests for scripts/omlx_auth.py and the auth path in the oMLX scripts.

The server behaviour these rely on was measured against the live gateway, not
inferred from it: an unauthenticated request is refused with 401, ``x-api-key``
and ``Authorization: Bearer`` are both accepted, and the legacy ``api-key``
header is rejected even when it carries a valid key.

The wire tests are the ones that matter. They fail for any client that sends a
key other than the one the resolver returned, which is the shape of the bug
that cost a teammate an afternoon: a stale literal in ``indexing_config.json``
quietly overriding the real key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import judge_pipeline
import omlx_auth
from omlx_auth import OmlxAuthError, raise_if_unauthorized, resolve_api_key

SENTINEL = "sentinel-key-used-only-by-tests"
CONFIG_KEY = "key-from-config"

CONFIG = {
    "onix": {
        "host": "localhost",
        "port": 21434,
        "api_key": CONFIG_KEY,
        "max_tokens": 8,
        "timeout": 5,
    }
}


# --- key resolution ----------------------------------------------------------


def test_env_key_wins_over_config(monkeypatch):
    monkeypatch.setenv(omlx_auth.ENV_VAR, SENTINEL)
    assert resolve_api_key(CONFIG) == SENTINEL


def test_falls_back_to_config_when_env_unset(monkeypatch):
    monkeypatch.delenv(omlx_auth.ENV_VAR, raising=False)
    assert resolve_api_key(CONFIG) == CONFIG_KEY


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_env_falls_back_to_config(monkeypatch, blank):
    monkeypatch.setenv(omlx_auth.ENV_VAR, blank)
    assert resolve_api_key(CONFIG) == CONFIG_KEY


def test_surrounding_whitespace_is_trimmed(monkeypatch):
    monkeypatch.setenv(omlx_auth.ENV_VAR, f"  {SENTINEL}\n")
    assert resolve_api_key(CONFIG) == SENTINEL


@pytest.mark.parametrize("config", [{"onix": {}}, {"onix": {"api_key": ""}}, {}])
def test_no_key_anywhere_raises_and_names_the_fix(monkeypatch, config):
    monkeypatch.delenv(omlx_auth.ENV_VAR, raising=False)
    with pytest.raises(OmlxAuthError) as excinfo:
        resolve_api_key(config)
    assert omlx_auth.ENV_VAR in str(excinfo.value)
    assert "indexing_config.json" in str(excinfo.value)


# --- rejection vs everything else --------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_rejection_raises_and_names_the_working_headers(status):
    with pytest.raises(OmlxAuthError) as excinfo:
        raise_if_unauthorized(status)
    message = str(excinfo.value)
    assert "x-api-key" in message
    assert "Bearer" in message


@pytest.mark.parametrize("status", [200, 201, 400, 413, 429, 500, 502])
def test_non_auth_statuses_pass_through(status):
    """Only 401/403 are auth. A 400 is the caller's payload, a 500 is the
    server's fault, a 429 is a quota -- none of them mean "wrong key"."""
    raise_if_unauthorized(status)


# --- the wire ----------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str = "3", status_code: int = 200):
        self._text = text
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return {"content": [{"type": "text", "text": self._text}]}


def _capture_post(monkeypatch, response):
    """Replace requests.post, recording the outbound headers."""
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        seen["json"] = json
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    return seen


def test_wire_carries_the_env_key(monkeypatch):
    monkeypatch.setenv(omlx_auth.ENV_VAR, SENTINEL)
    seen = _capture_post(monkeypatch, _FakeResponse())
    assert judge_pipeline.query_model("a prompt", "a-model") == "3"
    assert seen["headers"]["x-api-key"] == SENTINEL


def test_wire_carries_the_config_key_when_env_unset(monkeypatch):
    monkeypatch.delenv(omlx_auth.ENV_VAR, raising=False)
    seen = _capture_post(monkeypatch, _FakeResponse())
    judge_pipeline.query_model("a prompt", "a-model")
    # load_config() reads the shipped file, so this asserts the wire matches
    # whatever the resolver returns for it -- not that it equals some literal.
    assert seen["headers"]["x-api-key"] == resolve_api_key(judge_pipeline.load_config())


def test_header_name_is_the_accepted_one(monkeypatch):
    """The legacy 'api-key' header is rejected by the server, so the name is
    part of the contract, not a detail."""
    monkeypatch.setenv(omlx_auth.ENV_VAR, SENTINEL)
    seen = _capture_post(monkeypatch, _FakeResponse())
    judge_pipeline.query_model("a prompt", "a-model")
    assert "api-key" not in seen["headers"]


@pytest.mark.parametrize("judge_fn", ["judge_category", "judge_factuality"])
def test_rejected_key_is_not_swallowed_by_the_category_fallback(monkeypatch, judge_fn):
    """Both judge functions have a broad `except Exception` that returns a
    default category. An auth failure must not become "category 7" for every
    fact in the run -- that turns a broken key into silent bad data."""
    monkeypatch.setenv(omlx_auth.ENV_VAR, SENTINEL)
    _capture_post(monkeypatch, _FakeResponse(status_code=401))
    with pytest.raises(OmlxAuthError):
        getattr(judge_pipeline, judge_fn)("en", "a fact", "a response", "a-model")


def test_malformed_output_still_uses_the_fallback(monkeypatch):
    """The fallback itself must survive: junk output is not an auth failure."""
    monkeypatch.setenv(omlx_auth.ENV_VAR, SENTINEL)
    _capture_post(monkeypatch, _FakeResponse(text="not-a-number"))
    assert judge_pipeline.judge_category("en", "a fact", "a response", "a-model") == 7
    assert judge_pipeline.judge_factuality("en", "a fact", "a response", "a-model") == 4


# --- live --------------------------------------------------------------------


def _oMLX_reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=1.5)
        return True
    except requests.exceptions.RequestException:
        return False


@pytest.mark.skipif(
    not _oMLX_reachable("http://localhost:21434/health"),
    reason="oMLX not reachable (no tunnel, or not running) -- live check skipped",
)
def test_live_configured_key_is_accepted():
    """The resolvable key is one the running server accepts.

    No unit test can know the server's key, so a rotation is only detectable
    against the live gateway. Skips where oMLX is unreachable; fails where it
    is reachable but rejects what we would send.
    """
    config = judge_pipeline.load_config()
    base = f"http://{config['onix']['host']}:{config['onix']['port']}"
    response = requests.get(
        f"{base}/v1/models",
        headers={"x-api-key": resolve_api_key(config)},
        timeout=5,
    )
    assert response.status_code == 200, response.text
