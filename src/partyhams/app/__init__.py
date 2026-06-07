"""Application layer — wiring that ties the domain, networking, persistence, and
export together for the UI. Kept Qt-free so it can be driven headless in tests.
"""

from partyhams.app.session import LogSession, build_session, default_rst

__all__ = ["LogSession", "build_session", "default_rst"]
