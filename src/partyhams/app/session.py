"""LogSession — the contest logging controller the UI binds to.

Owns the active contest, the station config, the peer-to-peer
:class:`~partyhams.net.engine.SyncEngine`, and the SQLite store, and exposes a
clean API for the entry window: log a QSO, check dupes, validate the exchange,
read the live score, list peers, and export. Every applied QSO — whether logged
here or received from a peer — is persisted and fans out to UI listeners.

Qt-free on purpose, so it's fully unit-testable.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from partyhams.contest import get as get_contest
from partyhams.contest.base import ContestConfig, ContestDefinition, ScoreSummary
from partyhams.core.clock import new_station_id
from partyhams.core.models import QSO, Mode, ModeGroup, mode_group_for
from partyhams.db.store import SqliteLog
from partyhams.export import write_adif, write_cabrillo
from partyhams.net.engine import SyncEngine
from partyhams.net.transport import MulticastTransport, NullTransport


def default_rst(mode: Mode) -> str:
    """Sensible default report: ``59`` for phone, ``599`` otherwise."""
    return "59" if mode_group_for(mode) == ModeGroup.PHONE else "599"


class LogSession:
    def __init__(
        self,
        *,
        contest: ContestDefinition,
        config: ContestConfig,
        engine: SyncEngine,
        store: SqliteLog,
    ) -> None:
        self.contest = contest
        self.config = config
        self.engine = engine
        self.store = store
        self._listeners: list[Callable[[], None]] = []
        self._dupe_keys: set[tuple] = set()

        engine.on_qso = self._on_applied
        # Load the persisted log into the in-memory merge, clock, and dupe set.
        for qso in store.all(include_deleted=True):
            engine.log.apply(qso)
            engine.clock.update(qso.lamport)
        self._rebuild_dupes()

    # ------------------------------------------------------------------ #
    # listeners / lifecycle
    # ------------------------------------------------------------------ #
    def add_listener(self, callback: Callable[[], None]) -> None:
        """Register a no-arg callback fired whenever the log changes."""
        self._listeners.append(callback)

    def _emit(self) -> None:
        for callback in self._listeners:
            callback()

    async def start(self) -> None:
        await self.engine.start()

    async def stop(self) -> None:
        await self.engine.stop()

    # ------------------------------------------------------------------ #
    # apply hook (local + remote QSOs)
    # ------------------------------------------------------------------ #
    def _on_applied(self, qso: QSO) -> None:
        self.store.upsert(qso)
        self._rebuild_dupes()
        self._emit()

    def _rebuild_dupes(self) -> None:
        self._dupe_keys = {self.contest.dupe_key(q) for q in self.engine.log.qsos()}

    # ------------------------------------------------------------------ #
    # logging
    # ------------------------------------------------------------------ #
    async def log_qso(
        self,
        *,
        call: str,
        freq_hz: int,
        mode: Mode,
        exchange: dict[str, str],
        rst_sent: str | None = None,
        rst_rcvd: str = "599",
    ) -> QSO:
        return await self.engine.log_qso(
            call=call,
            freq_hz=freq_hz,
            mode=mode,
            exchange_rcvd=exchange,
            rst_sent=rst_sent or default_rst(mode),
            rst_rcvd=rst_rcvd,
        )

    # ------------------------------------------------------------------ #
    # exchange parsing / validation
    # ------------------------------------------------------------------ #
    def parse_exchange(self, raw: str) -> dict[str, str]:
        return self.contest.parse_exchange(raw)

    def validate_exchange(self, parsed: dict[str, str]) -> list[str]:
        """Return a list of human-readable problems ([] means valid)."""
        errors: list[str] = []
        for fld in self.contest.exchange_fields():
            value = parsed.get(fld.name, "")
            if fld.required and not value:
                errors.append(f"{fld.label} is required")
            elif value and fld.validator and not fld.validator(value):
                errors.append(f"{fld.label} '{value}' is invalid")
        return errors

    # ------------------------------------------------------------------ #
    # dupe / partial check
    # ------------------------------------------------------------------ #
    def is_dupe(self, call: str, freq_hz: int, mode: Mode) -> bool:
        if not call:
            return False
        probe = QSO(
            uuid="", station_id="", operator="", call=call.upper(), freq_hz=freq_hz, mode=mode
        )
        return self.contest.dupe_key(probe) in self._dupe_keys

    def partial_matches(self, fragment: str, limit: int = 20) -> list[str]:
        """Worked calls beginning with ``fragment`` (a simple partial check)."""
        frag = fragment.upper()
        if not frag:
            return []
        calls = sorted({q.call for q in self.engine.log.qsos() if q.call.startswith(frag)})
        return calls[:limit]

    # ------------------------------------------------------------------ #
    # views
    # ------------------------------------------------------------------ #
    def qsos(self) -> list[QSO]:
        return self.engine.log.qsos()

    def recent(self, n: int = 50) -> list[QSO]:
        return self.engine.log.qsos()[-n:]

    def score(self) -> ScoreSummary:
        return self.contest.score(self.engine.log.qsos(), self.config)

    @property
    def peers(self) -> dict[str, str]:
        return self.engine.peers

    def allowed_bands(self) -> set[str]:
        return self.contest.allowed_bands()

    # ------------------------------------------------------------------ #
    # export
    # ------------------------------------------------------------------ #
    def export_adif(self) -> str:
        return write_adif(self.engine.log.qsos(), self.config, self.contest)

    def export_cabrillo(self) -> str:
        operators = {q.operator for q in self.engine.log.qsos()}
        return write_cabrillo(
            self.engine.log.qsos(), self.config, self.contest, self.score(), operators
        )


def build_session(
    *,
    contest_id: str,
    my_call: str,
    sent_exchange: dict[str, str],
    power: str,
    network: str | None,
    operator: str | None = None,
    db_path: str | Path = ":memory:",
    bonus_points: int = 0,
) -> LogSession:
    """Construct a fully-wired session. ``network`` blank/None => offline."""
    contest = get_contest(contest_id)
    config = ContestConfig(
        my_call=my_call,
        sent_exchange=sent_exchange,
        extra={"power": power, "bonus_points": bonus_points},
    )
    store = SqliteLog(db_path)
    station_id = new_station_id()
    if network:
        transport: NullTransport | MulticastTransport = MulticastTransport(network, station_id)
    else:
        transport = NullTransport("offline", station_id)
    engine = SyncEngine(transport, operator=operator or my_call, call=my_call)
    return LogSession(contest=contest, config=config, engine=engine, store=store)
