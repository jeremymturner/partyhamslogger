"""Outbound notifications (e.g. announcing a new release to Discord).

Like the other integrations, the wire format is pure + the transport is injected,
so the payload builder and orchestration are unit-tested fully offline.
"""

from partyhams.notify.discord import announce_release, build_payload, fetch_release

__all__ = ["announce_release", "build_payload", "fetch_release"]
