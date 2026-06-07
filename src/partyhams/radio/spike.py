"""Hamlib CAT spike — watch live frequency/mode from a running ``rigctld``.

Start rigctld for your radio first, e.g. for the Yaesu FT-891 (Hamlib model 1041):

    rigctld -m 1041 -r /dev/cu.usbserial-XXXX -s 38400

then, in another terminal:

    make rig-spike            # or: python -m partyhams.radio.spike

Tune the radio and change modes — the readout should follow. Ctrl-C to stop.
This de-risks CAT before wiring it into the logging window.
"""

from __future__ import annotations

import argparse
import asyncio

from partyhams.app.radio import RadioPoller
from partyhams.core.models import band_for_freq
from partyhams.radio.hamlib import HamlibRadio


def format_freq(freq_hz: int) -> str:
    mhz, khz, hz = freq_hz // 1_000_000, (freq_hz // 1000) % 1000, (freq_hz % 1000) // 10
    band = band_for_freq(freq_hz)
    return f"{mhz:>3}.{khz:03d}.{hz:02d} MHz  {band.label if band else '?':>5}"


async def run(args: argparse.Namespace) -> int:
    radio = HamlibRadio(args.host, args.port)
    poller = RadioPoller(
        radio,
        on_state=lambda s: print(f"   {format_freq(s.freq_hz)}   {s.mode.value}", flush=True),
        on_status=lambda ok, err: print(
            f">> {'connected' if ok else 'DISCONNECTED'}{f' ({err})' if err else ''}", flush=True
        ),
        interval=args.interval,
    )
    try:
        await poller.start()
    except Exception as exc:  # noqa: BLE001 - friendly message for a down daemon
        print(f"!! could not reach rigctld at {args.host}:{args.port}: {exc}")
        print("   Start it first, e.g.:  rigctld -m 1041 -r /dev/cu.usbserial-XXXX -s 38400")
        return 1

    print(f">> polling rigctld at {args.host}:{args.port} — tune the radio (Ctrl-C to stop)")
    try:
        await asyncio.Event().wait()  # run until interrupted
    finally:
        await poller.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PartyHams Hamlib CAT spike")
    parser.add_argument("--host", default="127.0.0.1", help="rigctld host")
    parser.add_argument("--port", type=int, default=4532, help="rigctld port")
    parser.add_argument("--interval", type=float, default=0.3, help="poll seconds")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n>> 73")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
