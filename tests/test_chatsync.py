"""Durable + synced chat: store round-trip, engine sync, and session replay."""

from __future__ import annotations

from partyhams.app.session import build_session, open_session
from partyhams.core.clock import new_station_id
from partyhams.db.store import SqliteLog
from partyhams.net.engine import SyncEngine
from partyhams.net.loopback import LoopbackBus, LoopbackTransport
from partyhams.net.protocol import Chat

NETWORK = "test-net"


async def make_engine(bus: LoopbackBus, call: str) -> SyncEngine:
    transport = LoopbackTransport(bus, NETWORK, station_id=new_station_id())
    engine = SyncEngine(transport, operator=call, call=call)
    await engine.join()
    return engine


async def converge(*engines: SyncEngine, max_rounds: int = 200) -> None:
    for _ in range(max_rounds):
        progressed = False
        for engine in engines:
            if await engine.pump_once():
                progressed = True
        if not progressed:
            return
    raise AssertionError("engines did not reach a quiescent state")


# --------------------------------------------------------------------------- #
# store round-trip
# --------------------------------------------------------------------------- #
def test_store_add_chat_ordered_and_idempotent(tmp_path):
    store = SqliteLog(tmp_path / "log.sqlite")
    store.add_chat({"uuid": "b", "from_op": "W1A", "to_op": "*",
                    "text": "second", "ts": "2026-01-01T00:01:00", "station_id": "s1"})
    store.add_chat({"uuid": "a", "from_op": "K2B", "to_op": "*",
                    "text": "first", "ts": "2026-01-01T00:00:00", "station_id": "s2"})
    # Re-adding the same uuid must not duplicate.
    assert store.add_chat({"uuid": "a", "from_op": "K2B", "to_op": "*",
                           "text": "first", "ts": "2026-01-01T00:00:00",
                           "station_id": "s2"}) is False

    rows = store.all_chat()
    assert [r["text"] for r in rows] == ["first", "second"]  # ordered by ts
    assert len(rows) == 2
    store.close()


def test_store_chat_persists_across_reopen(tmp_path):
    path = tmp_path / "log.sqlite"
    store = SqliteLog(path)
    store.add_chat({"uuid": "x", "from_op": "W1A", "to_op": "*",
                    "text": "hi", "ts": "2026-01-01T00:00:00", "station_id": "s1"})
    store.close()

    reopened = SqliteLog(path)
    assert [r["text"] for r in reopened.all_chat()] == ["hi"]
    reopened.close()


# --------------------------------------------------------------------------- #
# engine sync
# --------------------------------------------------------------------------- #
async def test_full_log_request_pulls_chat():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA")
    await a.send_chat("*", "hello everyone")
    await a.send_chat("*", "second message")

    b = await make_engine(bus, "K2BBB")
    received: list[Chat] = []
    b.on_chat = lambda msg, sender: received.append(msg)
    await b.request_full_log()
    await converge(a, b)

    assert [c.text for c in received] == ["hello everyone", "second message"]
    assert set(b.chats) == set(a.chats)


async def test_chat_sync_dedups_by_uuid():
    bus = LoopbackBus()
    a = await make_engine(bus, "W1AAA")
    await a.send_chat("*", "once")

    b = await make_engine(bus, "K2BBB")
    received: list[Chat] = []
    b.on_chat = lambda msg, sender: received.append(msg)

    # Two full-log requests => A answers twice, but B must apply the chat once.
    await b.request_full_log()
    await converge(a, b)
    await b.request_full_log()
    await converge(a, b)

    assert [c.text for c in received] == ["once"]


def test_apply_chat_is_idempotent():
    bus = LoopbackBus()
    transport = LoopbackTransport(bus, NETWORK, station_id=new_station_id())
    engine = SyncEngine(transport, operator="W1A", call="W1A")
    chat = Chat(from_op="W1A", to_op="*", text="x", ts="t", uuid="u1", station_id="s1")
    assert engine.apply_chat(chat) is True
    assert engine.apply_chat(chat) is False
    assert len(engine.chats) == 1


# --------------------------------------------------------------------------- #
# session replay
# --------------------------------------------------------------------------- #
def _new_session(db_path):
    return build_session(
        contest_id="arrl-field-day",
        my_call="W1AW",
        sent_exchange={"class": "1B", "section": "CT"},
        network=None,
        db_path=db_path,
    )


def test_session_replays_chat_history_in_order(tmp_path):
    db_path = tmp_path / "log.sqlite"
    session = _new_session(db_path)
    session.post_chat("*", "first")
    session.post_chat("*", "second")
    session.store.close()

    reopened = open_session(db_path)
    msgs = reopened.chat_messages()
    assert [m["text"] for m in msgs] == ["first", "second"]
    # Engine also holds them for serving (re)joiners a full log.
    assert len(reopened.engine.chats) == 2
    reopened.store.close()


def test_session_post_chat_persists_and_echoes(tmp_path):
    session = _new_session(tmp_path / "log.sqlite")
    echoed: list[dict] = []
    session.add_chat_listener(echoed.append)
    entry = session.post_chat("*", "hello")

    assert entry["incoming"] is False
    assert entry["uuid"]
    assert echoed and echoed[0]["text"] == "hello"
    assert [r["text"] for r in session.store.all_chat()] == ["hello"]
    session.store.close()
