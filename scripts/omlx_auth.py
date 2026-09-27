"""oMLX API-key resolution, and auth failures worth reading.

oMLX 0.7 enforces API-key auth on ``/v1/*``: an unauthenticated request is
refused with 401. The key must arrive as ``x-api-key`` or
``Authorization: Bearer`` -- the legacy ``api-key`` header is rejected even
when it carries a valid key, and ``/health`` stays open. Both facts are
verified against the live server, not inferred; see docs/running-scripts.md.

The key is read from the environment first, so rotating it does not require
editing a tracked file, and falls back to the shared ``indexing_config.json``
so a fresh clone runs with no setup at all.

Both failure modes raise :class:`OmlxAuthError` with a message that names the
fix. That is the whole point of this module: the bug it replaces presented as
a bare ``401 Client Error: Unauthorized``, which does not distinguish "no key
was sent" from "the wrong key was sent", and cost a teammate an afternoon.
"""

from __future__ import annotations

import os
from typing import Any, Dict

ENV_VAR = "OMLX_API_KEY"


class OmlxAuthError(RuntimeError):
    """oMLX refused a request for want of a usable API key."""


def resolve_api_key(config: Dict[str, Any]) -> str:
    """Return the oMLX API key: ``$OMLX_API_KEY`` if set, else the shared config.

    Raises :class:`OmlxAuthError` when neither source yields a non-empty key,
    rather than sending an empty header and letting the server's 401 imply the
    key was wrong when in fact none was sent.
    """
    key = (os.environ.get(ENV_VAR) or "").strip()
    if key:
        return key

    key = str(config.get("onix", {}).get("api_key") or "").strip()
    if key:
        return key

    raise OmlxAuthError(
        f"No oMLX API key: set {ENV_VAR}, or add onix.api_key to "
        f"scripts/indexing_config.json. See docs/running-scripts.md."
    )


def raise_if_unauthorized(status_code: int) -> None:
    """Turn a 401/403 from oMLX into a message that names the fix.

    Called before ``raise_for_status()`` so the specific cause wins over the
    generic HTTP error.
    """
    if status_code in (401, 403):
        raise OmlxAuthError(
            f"oMLX refused the API key ({status_code}). Set {ENV_VAR} to the key "
            f"configured on the oMLX server, or correct onix.api_key in "
            f"scripts/indexing_config.json. The header must be x-api-key or "
            f"Authorization: Bearer -- the legacy 'api-key' header is rejected. "
            f"See docs/running-scripts.md."
        )
