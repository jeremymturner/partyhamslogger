"""FlexRadio native-API spike — discover a radio and watch its slices/bands.

With the FLEX-6500 powered on and on the same LAN:

    make flex-spike            # discover, connect, watch live
    make flex-spike HOST=192.168.1.50   # skip discovery, connect directly

Prints the radio info and band table once, then the active slice's
frequency/mode/band as you tune. Ctrl-C to stop. De-risks the native API before
wiring it into the logger alongside the Hamlib path.
"""

from __future__ import annotations

import argparse
import asyncio

from partyhams.radio.flex import FlexRadio, discover


async def run(args: argparse.Namespace) -> int:
    if args.host:
        radio = FlexRadio(args.host, args.port)
    else:
        print(">> discovering FlexRadios (VITA-49 broadcast)...", flush=True)
        radios = await discover(timeout=args.timeout)
        if not radios:
            print("!! no FlexRadio found. Is it powered on and on this LAN?")
            return 1
        for r in radios:
            print(f"   found: {r.label()}  serial={r.serial}  v{r.version}", flush=True)
        radio = FlexRadio(radios[0].ip, radios[0].port)
        radio.info = radios[0]  # carry the discovered identity through

    await radio.connect()
    info = radio.radio_info()
    print(f">> connected to {info.label()}  API v{radio.version}", flush=True)

    if args.raw:
        print(f">> discovery: {info.raw}")
        print(f">> radio status: {radio.radio_status()}")
        print(f">> slices: {radio.raw_slices()}")

    bands = radio.bands()
    if bands:
        print(">> band settings reported by the radio:")
        for band_id, fields in sorted(bands.items()):
            print(f"     band {band_id}: {fields}")

    print(">> tuning the radio should update this (Ctrl-C to stop):", flush=True)
    last = None
    try:
        while True:
            state = await radio.read_state()
            band = radio.current_band()
            current = (state.freq_hz, state.mode)
            if current != last:
                last = current
                blabel = band.label if band else "?"
                print(
                    f"   {state.freq_hz / 1_000_000:.6f} MHz  {state.mode.value:<4} band={blabel}",
                    flush=True,
                )
            await asyncio.sleep(args.interval)
    finally:
        await radio.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PartyHams FlexRadio native-API spike")
    parser.add_argument("--host", default=None, help="radio IP (skip discovery)")
    parser.add_argument("--port", type=int, default=4992, help="control port")
    parser.add_argument("--timeout", type=float, default=2.0, help="discovery seconds")
    parser.add_argument("--interval", type=float, default=0.3, help="poll seconds")
    parser.add_argument("--raw", action="store_true", help="dump raw discovery/status fields")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n>> 73")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
