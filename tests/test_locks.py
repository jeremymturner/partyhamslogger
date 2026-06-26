"""Cross-process log lock: detect when a log is held by another live instance."""

from __future__ import annotations

from partyhams.app.locks import (
    LOCK_STALE_S,
    acquire_log_lock,
    is_log_in_use,
    lock_path,
    read_lock,
    release_log_lock,
)


def test_acquire_writes_lock_and_release_removes_it(tmp_path):
    log = tmp_path / "fd.sqlite"
    acquire_log_lock(log, now=1000.0, pid=4242)
    data = read_lock(log)
    assert data["pid"] == 4242 and data["ts"] == 1000.0
    assert lock_path(log).exists()

    release_log_lock(log, pid=4242)
    assert not lock_path(log).exists()


def test_no_lock_means_not_in_use(tmp_path):
    assert is_log_in_use(tmp_path / "nope.sqlite", now=1000.0) is False


def test_memory_and_blank_paths_never_lock(tmp_path):
    acquire_log_lock(":memory:", now=1.0)  # no-op, no crash
    assert is_log_in_use(":memory:", now=1.0) is False
    assert is_log_in_use("", now=1.0) is False


def test_live_owner_is_in_use(tmp_path):
    log = tmp_path / "fd.sqlite"
    acquire_log_lock(log, now=1000.0, pid=4242)
    # A different PID that the injected liveness check reports as alive.
    assert is_log_in_use(log, now=1000.0, pid_alive=lambda _p: True) is True


def test_dead_owner_is_reclaimable_even_with_fresh_heartbeat(tmp_path):
    # A crash-and-quick-relaunch: the lock's heartbeat is still fresh, but the
    # owning process is gone — so the log is NOT in use and can be reopened.
    log = tmp_path / "fd.sqlite"
    acquire_log_lock(log, now=1000.0, pid=4242)
    assert is_log_in_use(log, now=1000.5, pid_alive=lambda _p: False) is False


def test_unknown_liveness_falls_back_to_heartbeat(tmp_path):
    log = tmp_path / "fd.sqlite"
    acquire_log_lock(log, now=1000.0, pid=4242)
    # Liveness undeterminable (e.g. Windows) -> trust heartbeat freshness.
    fresh = is_log_in_use(log, now=1000.0 + LOCK_STALE_S - 1, pid_alive=lambda _p: None)
    stale = is_log_in_use(log, now=1000.0 + LOCK_STALE_S + 1, pid_alive=lambda _p: None)
    assert fresh is True
    assert stale is False


def test_own_lock_is_not_in_use(tmp_path):
    log = tmp_path / "fd.sqlite"
    acquire_log_lock(log, now=1000.0, pid=4242)
    # Our own PID holding it shouldn't read as "another instance".
    assert is_log_in_use(log, now=1000.0, self_pid=4242, pid_alive=lambda _p: True) is False


def test_release_does_not_remove_another_instances_lock(tmp_path):
    log = tmp_path / "fd.sqlite"
    acquire_log_lock(log, now=1000.0, pid=4242)  # owned by 4242
    release_log_lock(log, pid=9999)  # a different instance must not clobber it
    assert lock_path(log).exists()
    assert read_lock(log)["pid"] == 4242


def test_corrupt_lock_is_ignored(tmp_path):
    log = tmp_path / "fd.sqlite"
    lock_path(log).write_text("not json{")
    assert read_lock(log) is None
    assert is_log_in_use(log, now=1000.0) is False
