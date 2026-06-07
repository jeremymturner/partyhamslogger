"""Registry of available contest definitions.

Contest modules call :func:`register` at import time; the UI lists :func:`available`
and instantiates the chosen one with :func:`get`.
"""

from __future__ import annotations

from partyhams.contest.base import ContestDefinition

_REGISTRY: dict[str, type[ContestDefinition]] = {}


def register(cls: type[ContestDefinition]) -> type[ContestDefinition]:
    """Class decorator that registers a contest by its ``id``."""
    if not cls.id:
        raise ValueError(f"{cls.__name__} must set a non-empty `id`")
    if cls.id in _REGISTRY:
        raise ValueError(f"duplicate contest id: {cls.id}")
    _REGISTRY[cls.id] = cls
    return cls


def available() -> list[tuple[str, str]]:
    """Return ``(id, name)`` for every registered contest, sorted by name."""
    return sorted(((c.id, c.name) for c in _REGISTRY.values()), key=lambda t: t[1])


def get(contest_id: str) -> ContestDefinition:
    """Instantiate a registered contest by id."""
    try:
        return _REGISTRY[contest_id]()
    except KeyError:
        raise KeyError(f"unknown contest id: {contest_id}") from None
