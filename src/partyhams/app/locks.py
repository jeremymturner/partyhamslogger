"""Cross-process "is this log open in another instance?" lock.

When you launch a second copy of the app on the same machine, it must NOT silently
reopen the log the first copy is using — they'd share one ``station_id`` and collide
on the network (each treats the other as its own echo). Instead the second launch is
sent through the setup flow to pick a *different* log (see ``ui/app.py``).

We detect this with a tiny sidecar lock file next to the log (``<log>.lock``) holding
the owning process's PID and a heartbeat timestamp the owner refreshes periodically.
A log is "in use" only while that process is actually alive — so a crash followed by a
quick relaunch still reopens (reconnects to) the same log; a genuinely concurrent
instance is the only thing that's blocked.

Qt-free and unit-testable: the liveness/staleness decision takes injectable ``now``
and PID-liveness so tests don't depend on real processes or the wall clock.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

#: If we can't tell whether the owning PID is alive (e.g. on Windows), treat the
#: lock as stale once its heartbeat is older than this many seconds.
LOCK_STALE_S = 180

#: Paths that never get a lock (in-memory/transient stores used by tests).
_NO_LOCK = ("", ":memory:")


def lock_path(log_path: str | Path) -> Path:
    """The sidecar lock file path for a log file."""
    p = Path(log_path)
    return p.with_name(p.name + ".lock")


def _pid_alive(pid: int) -> bool | None:
    """Is ``pid`` a live process? ``True``/``False``, or ``None`` if undeterminable
    (e.g. signal 0 unsupported), so the caller can fall back to the heartbeat."""
    if not pid:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by another user
    except (OSError, ValueError):
        return None  # can't tell (Windows, etc.) -> let the heartbeat decide


def read_lock(log_path: str | Path) -> dict | None:
    """Read and parse a log's lock file, or ``None`` if absent/corrupt."""
    try:
        return json.loads(lock_path(log_path).read_text())
    except (OSError, ValueError):
        return None


def is_log_in_use(
    log_path: str | Path,
    *,
    now: float,
    stale_s: int = LOCK_STALE_S,
    pid_alive: Callable[[int], bool | None] = _pid_alive,
    self_pid: int | None = None,
) -> bool:
    """True if another live instance currently holds ``log_path``.

    Decided by the owning PID's liveness; when that can't be determined, falls back
    to whether the heartbeat is still fresh. A lock owned by *this* process (or a
    dead one) is not "in use", so a crash-and-relaunch reopens the same log.
    """
    if str(log_path) in _NO_LOCK:
        return False
    data = read_lock(log_path)
    if not data:
        return False
    pid = int(data.get("pid", 0) or 0)
    if self_pid is not None and pid == self_pid:
        return False  # our own lock
    alive = pid_alive(pid)
    if alive is True:
        return True
    if alive is False:
        return False  # owner is gone — reclaimable
    # Couldn't determine liveness: trust the heartbeat freshness.
    return (now - float(data.get("ts", 0) or 0)) < stale_s


def acquire_log_lock(log_path: str | Path, *, now: float, pid: int | None = None) -> None:
    """Claim ``log_path`` for this process (writes/overwrites the lock file)."""
    if str(log_path) in _NO_LOCK:
        return
    pid = pid if pid is not None else os.getpid()
    payload = json.dumps({"pid": pid, "ts": now})
    try:
        lock_path(log_path).write_text(payload)
    except OSError:
        pass  # best-effort; never block opening a log on a lock-write failure


def refresh_log_lock(log_path: str | Path, *, now: float, pid: int | None = None) -> None:
    """Update the heartbeat timestamp so the lock stays fresh while we run."""
    acquire_log_lock(log_path, now=now, pid=pid)


def release_log_lock(log_path: str | Path, *, pid: int | None = None) -> None:
    """Remove our lock file when closing/switching logs (best-effort)."""
    if str(log_path) in _NO_LOCK:
        return
    data = read_lock(log_path)
    pid = pid if pid is not None else os.getpid()
    # Only remove a lock we actually own, so we don't clobber another instance's.
    if data is not None and int(data.get("pid", 0) or 0) not in (0, pid):
        return
    try:
        lock_path(log_path).unlink()
    except OSError:
        pass
