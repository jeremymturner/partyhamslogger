"""Tiny POTA API client for verifying a park reference.

Hits the public POTA endpoint ``GET https://api.pota.app/park/{ref}`` which
returns JSON describing the park (name, location, grid, etc.). The single public
entry point, :func:`verify_park`, returns a small normalized dict on success or
``None`` on *any* network or parse failure — verification must never block log
creation when offline.

The HTTP fetch is injectable (the ``fetch`` parameter) so the URL, parsing, and
error paths are unit-testable without touching the network.

NOTE: the *live* API call is unverified in this build/test environment; only the
URL construction, JSON parsing, and error handling are exercised by the unit
tests (via an injected ``fetch``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import URLError
from urllib.request import urlopen

# A fetch takes a URL and returns the raw response body as text.
Fetch = Callable[[str], str]

BASE_URL = "https://api.pota.app/park"
_TIMEOUT_S = 5.0


def _default_fetch(url: str) -> str:
    """Fetch ``url`` over HTTPS using only the standard library (no new deps)."""
    with urlopen(url, timeout=_TIMEOUT_S) as resp:  # noqa: S310 - fixed https POTA host
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset)


def park_url(ref: str) -> str:
    """Build the POTA park endpoint URL for a reference like ``US-1234``."""
    return f"{BASE_URL}/{ref.strip().upper()}"


def verify_park(ref: str, *, fetch: Fetch | None = None) -> dict | None:
    """Look up a POTA park reference and return ``{ref, name, location}`` or ``None``.

    Returns ``None`` on any failure — empty ref, network error, non-JSON body, or
    a payload missing a park name — so callers can degrade gracefully offline.
    The ``fetch`` callable is injectable for testing; it defaults to a stdlib
    HTTPS GET.
    """
    ref = ref.strip().upper()
    if not ref:
        return None
    fetch = fetch or _default_fetch
    try:
        body = fetch(park_url(ref))
        data = json.loads(body)
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    except Exception:  # noqa: BLE001 - any injected/transport error degrades to None
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name") or data.get("parkName")
    if not name:
        return None
    location = (
        data.get("locationDesc")
        or data.get("location")
        or data.get("grid")
        or ""
    )
    return {
        "reference": data.get("reference", ref),
        "name": str(name),
        "location": str(location),
    }
