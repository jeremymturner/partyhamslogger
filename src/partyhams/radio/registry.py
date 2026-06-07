"""Registry of available radio backends."""

from __future__ import annotations

from partyhams.radio.base import Radio

_REGISTRY: dict[str, type[Radio]] = {}


def register(cls: type[Radio]) -> type[Radio]:
    """Class decorator registering a backend by ``backend_id``."""
    if not cls.backend_id:
        raise ValueError(f"{cls.__name__} must set a non-empty `backend_id`")
    if cls.backend_id in _REGISTRY:
        raise ValueError(f"duplicate backend id: {cls.backend_id}")
    _REGISTRY[cls.backend_id] = cls
    return cls


def available() -> list[tuple[str, str]]:
    """Return ``(backend_id, backend_name)`` for every backend, sorted by name."""
    return sorted(((c.backend_id, c.backend_name) for c in _REGISTRY.values()),
                  key=lambda t: t[1])


def get_backend(backend_id: str) -> type[Radio]:
    """Look up a backend class by id (caller constructs it with its own args)."""
    try:
        return _REGISTRY[backend_id]
    except KeyError:
        raise KeyError(f"unknown radio backend: {backend_id}") from None
