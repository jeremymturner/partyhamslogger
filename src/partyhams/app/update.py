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
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from partyhams.core.certs import ssl_context

#: Where to look for releases. ``owner/name``.
GITHUB_REPO = "jeremymturner/partyhamslogger"

#: How often the app may check for updates — clamped to this range (hours).
UPDATE_MIN_HOURS = 1
UPDATE_MAX_HOURS = 7 * 24  # 7 days

#: A ``fetch`` takes ``(url, headers)`` and returns the decoded JSON object.
Fetch = Callable[[str, dict[str, str]], dict]
#: A ``progress`` callback receives ``(bytes_received, bytes_total)`` (total 0 if unknown).
Progress = Callable[[int, int], None]


def clamp_interval_hours(hours: int) -> int:
    """Clamp an update-check interval into the supported 1-hour .. 7-day range."""
    return max(UPDATE_MIN_HOURS, min(UPDATE_MAX_HOURS, int(hours)))


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
    with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as resp:  # noqa: S310
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


# --- in-app download + install ------------------------------------------- #
def is_asset_url(url: str) -> bool:
    """True if ``url`` points at a downloadable build (not the HTML release page)."""
    return url.lower().endswith((".zip", ".tar.gz", ".tgz"))


def _urlopen(url: str):  # noqa: ANN202 - returns an http.client.HTTPResponse
    req = urllib.request.Request(url, headers={"User-Agent": "partyhams-update-check"})
    return urllib.request.urlopen(req, timeout=30, context=ssl_context())  # noqa: S310


def download_asset(
    url: str,
    dest_dir: str | Path,
    *,
    progress: Progress | None = None,
    opener: Callable = _urlopen,
    chunk: int = 65536,
) -> Path:
    """Stream ``url`` to a file in ``dest_dir``, reporting progress as it goes.

    ``opener(url)`` returns a context-manager response with ``.read(n)`` and a
    ``.headers`` mapping (the stdlib default); inject a fake in tests. Returns the
    downloaded file path.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / (url.rsplit("/", 1)[-1] or "update-download")
    with opener(url) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        received = 0
        with open(out, "wb") as fh:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                fh.write(buf)
                received += len(buf)
                if progress is not None:
                    progress(received, total)
    return out


def _archive_top(names: list[str]) -> str:
    """The single top-level directory shared by archive members (skips __MACOSX)."""
    tops = {n.split("/", 1)[0] for n in names if n and not n.startswith("__MACOSX")}
    tops.discard("")
    if len(tops) != 1:
        raise ValueError(f"expected one top-level entry in the archive, got {sorted(tops)}")
    return tops.pop()


def extract_bundle(archive_path: str | Path, dest_dir: str | Path) -> Path:
    """Extract a release archive into ``dest_dir`` and return the app bundle path
    inside it (the ``PartyHamsLogger`` folder, or ``PartyHamsLogger.app`` on macOS)."""
    archive_path = Path(archive_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            top = _archive_top(zf.namelist())
            zf.extractall(dest)
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path) as tf:
            top = _archive_top(tf.getnames())
            tf.extractall(dest, filter="data")  # py3.12 safe-extraction filter
    else:
        raise ValueError(f"unsupported archive type: {archive_path.name}")
    return dest / top


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle (vs. a source checkout)."""
    return bool(getattr(sys, "frozen", False))


def install_root(executable: str | None = None, system: str | None = None) -> Path:
    """The directory/bundle to replace on update, derived from the running exe.

    macOS: the ``.app`` bundle; Windows/Linux one-dir builds: the folder holding
    the executable.
    """
    exe = Path(executable or sys.executable)
    system = (system or platform.system()).lower()
    if system == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
    return exe.parent


def relaunch_command(app_root: str | Path, system: str | None = None) -> list[str]:
    """The command that starts the (newly installed) app at ``app_root``."""
    app_root = Path(app_root)
    system = (system or platform.system()).lower()
    if system == "darwin":
        return ["open", str(app_root)]
    if system == "windows":
        return [str(app_root / "PartyHamsLogger.exe")]
    return [str(app_root / "PartyHamsLogger")]


def swap_script(
    system: str, pid: int, app_root: str | Path, new_bundle: str | Path, relaunch: list[str]
) -> tuple[str, str]:
    """Build the helper-script ``(suffix, text)`` that waits for us to exit, swaps
    the bundle, and relaunches. Pure (no I/O) so it's unit-tested; the actual
    write+spawn lives in :func:`apply_update`."""
    app_root, new_bundle = str(app_root), str(new_bundle)
    if system == "windows":
        relaunch_line = 'start "" ' + " ".join(f'"{a}"' for a in relaunch)
        text = (
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >nul\r\n"
            "  goto wait\r\n"
            ")\r\n"
            f'rmdir /s /q "{app_root}"\r\n'
            f'move "{new_bundle}" "{app_root}" >nul\r\n'
            f"{relaunch_line}\r\n"
        )
        return ".bat", text
    relaunch_line = " ".join(_shquote(a) for a in relaunch)
    text = (
        "#!/bin/sh\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
        f'rm -rf "{app_root}"\n'
        f'mv "{new_bundle}" "{app_root}"\n'
        f"{relaunch_line}\n"
    )
    return ".sh", text


def _shquote(s: str) -> str:
    import shlex

    return shlex.quote(s)


def apply_update(
    new_bundle: str | Path,
    *,
    app_root: str | Path | None = None,
    pid: int | None = None,
    system: str | None = None,
    runner: Callable | None = None,
) -> None:
    """Spawn a detached helper that replaces the running app with ``new_bundle``
    and relaunches it. The caller should quit immediately afterwards so the helper
    can take over. ``runner`` (defaults to a detached ``subprocess.Popen``) and the
    other args are injectable for tests.

    Best-effort and **unverified against packaged builds on every OS** — overwriting
    a running app is inherently platform-specific (file locks, permissions).
    """
    import os
    import stat
    import subprocess
    import tempfile

    system = (system or platform.system()).lower()
    pid = pid if pid is not None else os.getpid()
    app_root = Path(app_root) if app_root is not None else install_root(system=system)
    relaunch = relaunch_command(app_root, system=system)
    suffix, text = swap_script(system, pid, app_root, new_bundle, relaunch)

    fd, script_path = tempfile.mkstemp(suffix=suffix, prefix="partyhams-update-")
    with os.fdopen(fd, "w", newline="") as fh:
        fh.write(text)
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC)

    if runner is not None:
        runner(system, script_path)
        return
    if system == "windows":
        subprocess.Popen(  # noqa: S603
            ["cmd", "/c", script_path],
            creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | NEW_PROCESS_GROUP
            close_fds=True,
        )
    else:
        subprocess.Popen(["/bin/sh", script_path], start_new_session=True)  # noqa: S603
