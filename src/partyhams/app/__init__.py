"""Application layer — wiring that ties the domain, networking, persistence, and
export together for the UI. Kept Qt-free so it can be driven headless in tests.
"""

from partyhams.app.session import (
    LogSession,
    build_session,
    default_rst,
    list_logs,
    open_session,
    summarize_log,
)

__all__ = [
    "LogSession",
    "build_session",
    "open_session",
    "list_logs",
    "summarize_log",
    "default_rst",
]
