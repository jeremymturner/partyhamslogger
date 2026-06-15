"""Check GitHub for a newer release than the one we're running.

Qt-free and offline-testable: the version comparison and asset selection are
pure functions, and :func:`check_for_update` takes an injectable ``fetch`` (the
default is a thin stdlib ``urllib`` GET). The UI polls this on a timer and, when
a newer version exists, surfaces a "download update" affordance.

The running version is :data:`partyhams.__version__` — already baked into the
build — so there is no separate VERSION file to drift; "latest" comes from the
GitHub Releases API (``releases/latest`` excludes drafts and pre-releases).
"""

from __future__ import annotations

import json
import platform
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

#: Where to look for releases. ``owner/name``.
GITHUB_REPO = "jeremymturner/partyhamslogger"

#: A ``fetch`` takes ``(url, headers)`` and returns the decoded JSON object.
Fetch = Callable[[str, dict[str, str]], dict]


@dataclass(frozen=True)
class UpdateInfo:
    """A newer release than the one running."""

    version: str  # normalized, e.g. "0.1.0" (no leading "v")
    tag: str  # the release tag, e.g. "v0.1.0"
    name: str  # release title
    url: str  # what to open to download (platform asset, else the release page)
    notes: str  # release body (markdown)


def parse_version(text: str) -> tuple[int, ...]:
    """Parse ``"v0.1.2"`` / ``"0.1.2"`` into ``(0, 1, 2)`` for comparison.

    Tolerant: a leading ``v`` is dropped and parsing stops at the first
    non-numeric component (so ``"1.2.0-rc1"`` -> ``(1, 2, 0)``). Garbage yields
    an empty tuple, which compares as the oldest possible version.
    """
    parts: list[int] = []
    for token in text.strip().lstrip("vV").split("."):
        m = re.match(r"\d+", token)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """True iff ``latest`` is a strictly newer version than ``current``."""
    return parse_version(latest) > parse_version(current)


def asset_for_platform(
    assets: list[dict], system: str | None = None, machine: str | None = None
) -> str | None:
    """Pick the download URL of the release asset matching this OS/arch.

    Matches our release artifact names (``…-windows-x64.zip`` /
    ``…-macos-arm64.zip`` / ``…-linux-x64.tar.gz``). Returns ``None`` if nothing
    matches, so the caller can fall back to the release page.
    """
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()

    def find(substr: str) -> str | None:
        for a in assets:
            name = (a.get("name") or "").lower()
            if substr in name and a.get("browser_download_url"):
                return a["browser_download_url"]
        return None

    if system == "windows":
        return find("windows")
    if system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            return find("macos-arm64") or find("macos")
        return find("macos-x64") or find("macos")
    if system == "linux":
        return find("linux")
    return None


def _http_get_json(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (trusted GitHub URL)
        return json.loads(resp.read().decode())


def check_for_update(
    current_version: str,
    repo: str = GITHUB_REPO,
    *,
    system: str | None = None,
    machine: str | None = None,
    fetch: Fetch = _http_get_json,
) -> UpdateInfo | None:
    """Return an :class:`UpdateInfo` if the latest release is newer than
    ``current_version``, else ``None``. Network/parse errors propagate to the
    caller (the UI treats them as "no update, try again later")."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "partyhams-update-check",
    }
    release = fetch(f"https://api.github.com/repos/{repo}/releases/latest", headers)
    tag = release.get("tag_name") or ""
    if not tag or not is_newer(tag, current_version):
        return None
    url = asset_for_platform(release.get("assets") or [], system, machine) or release.get(
        "html_url"
    ) or f"https://github.com/{repo}/releases/latest"
    return UpdateInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        name=release.get("name") or tag,
        url=url,
        notes=release.get("body") or "",
    )
