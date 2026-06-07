"""Phase-0 peer-to-peer sync spike — a runnable proof the LAN sync works.

Run two (or more) instances, each with a different ``--call``, on the same LAN:

    make spike CALL=W7ABC
    make spike CALL=K2XYZ           # in another terminal / on another machine

Each instance logs a fake QSO every few seconds and prints a status line. Watch
the **QSO count** climb together and the **log hash** match across instances —
that's the peer-to-peer log converging. ``Ctrl-C`` to quit.

This is a throwaway harness for de-risking the sync design, not the real app.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools

from partyhams.core.clock import new_station_id
from partyhams.core.models import BANDS, Mode
from partyhams.net.engine import SyncEngine
from partyhams.net.transport import DEFAULT_MCAST_GROUP, DEFAULT_PORT, MulticastTransport

# A little rotation of bands/modes so generated traffic looks plausible.
_DEMO_BANDS = [b for b in BANDS if b.label in {"20m", "40m", "15m", "80m"}]
_DEMO_MODES = [Mode.CW, Mode.USB, Mode.FT8]


def _fake_worked_call(my_call: str, n: int) -> str:
    """Deterministic-but-varied worked callsign derived from ours + a counter."""
    suffix = "".join(c for c in my_call if c.isalnum())[-3:].upper() or "QSO"
    return f"{suffix}{n:03d}"


async def _generate(engine: SyncEngine, interval: float) -> None:
    for n in itertools.count(1):
        await asyncio.sleep(interval)
        band = _DEMO_BANDS[n % len(_DEMO_BANDS)]
        mode = _DEMO_MODES[n % len(_DEMO_MODES)]
        freq = (band.low_hz + band.high_hz) // 2
        await engine.log_qso(
            call=_fake_worked_call(engine.call, n),
            freq_hz=freq,
            mode=mode,
            exchange_rcvd={"class": "1B", "section": "DX"},
        )


async def _status(engine: SyncEngine, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        print(
            f"[{engine.call:<8}] QSOs={len(engine.log):<4} "
            f"hash={engine.log.log_hash()[:8]} "
            f"peers={len(engine.peers)} clock={engine.clock.value}",
            flush=True,
        )


async def run(args: argparse.Namespace) -> None:
    station_id = new_station_id()
    transport = MulticastTransport(
        network=args.network,
        station_id=station_id,
        group=args.group,
        port=args.port,
    )
    engine = SyncEngine(transport, operator=args.call, call=args.call)
    await engine.start()
    print(
        f">> {args.call} joined network '{args.network}' "
        f"({args.group}:{args.port}) as station {station_id}",
        flush=True,
    )

    tasks = [asyncio.create_task(_status(engine, args.status_interval))]
    if not args.listen_only:
        tasks.append(asyncio.create_task(_generate(engine, args.interval)))

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)
        await engine.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="PartyHams P2P sync spike")
    parser.add_argument("--call", required=True, help="this station's callsign")
    parser.add_argument("--network", default="spike-demo", help="event network name")
    parser.add_argument(
        "--interval", type=float, default=3.0, help="seconds between generated QSOs"
    )
    parser.add_argument("--status-interval", type=float, default=2.0, help="status print cadence")
    parser.add_argument("--listen-only", action="store_true", help="don't generate QSOs, just sync")
    parser.add_argument("--group", default=DEFAULT_MCAST_GROUP, help="multicast group")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="multicast port")
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n>> bye, 73", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
