# Copyright (C) 2015-2024 Guillaume VINET
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Command-line entry point for the two-Proxmark3 CardHopper relay.

Example::

    pynfcreader-relay --card-port /dev/ttyACM0 --reader-port /dev/rfcomm0

``--card-port`` is the Proxmark3 next to the real **card** (it becomes a reader /
leech). ``--reader-port`` is the Proxmark3 next to the real **reader** (it becomes
a card / ghost).

This tool is for authorized security testing and research only.
"""

import argparse
import logging
import sys

from pynfcreader.relay.cardhopper import (
    CardhopperError,
    CardhopperLink,
    CardhopperRelay,
    open_transport,
)
from pynfcreader.relay.detect import (
    RoleResolutionError,
    list_proxmark_ports,
    resolve_roles,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pynfcreader-relay",
        description="Relay an ISO14443-A session between two Proxmark3 devices "
        "running the HF_CARDHOPPER standalone firmware. Authorized testing only.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="list detected Proxmark3 USB ports (with serials) and exit",
    )
    parser.add_argument(
        "--card-port",
        help="serial port (or tcp:HOST:PORT) of the Proxmark3 next to the real CARD "
        "(leech / reader mode), e.g. /dev/ttyACM0. Auto-detected if omitted.",
    )
    parser.add_argument(
        "--reader-port",
        help="serial port (or tcp:HOST:PORT) of the Proxmark3 next to the real READER "
        "(ghost / card mode), e.g. /dev/rfcomm0 or tcp:172.20.0.1:5555",
    )
    parser.add_argument(
        "--card-serial",
        help="pick the CARD-side Proxmark3 by its USB serial number (stable across reboots)",
    )
    parser.add_argument(
        "--reader-serial",
        help="pick the READER-side Proxmark3 by its USB serial number",
    )
    parser.add_argument("--baud", type=int, default=115200, help="serial baudrate (default 115200)")
    parser.add_argument(
        "--tag-type", type=lambda s: int(s, 0), default=1, help="ghost emulation tag type (default 1)"
    )
    parser.add_argument(
        "--fwi",
        type=int,
        default=14,
        choices=range(0, 15),
        metavar="0-14",
        help="Frame Waiting time Integer baked into the ghost ATS; higher tolerates more "
        "relay latency (default 14)",
    )
    parser.add_argument(
        "--sfgi",
        type=int,
        default=0,
        choices=range(0, 15),
        metavar="0-14",
        help="Start-up Frame Guard time Integer (default 0)",
    )
    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=2.0,
        help="seconds to wait for a Proxmark3 ACK before erroring (default 2.0)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if args.list_devices:
        ports = list_proxmark_ports()
        if not ports:
            print("No Proxmark3 USB serial ports detected.")
            print("On WSL, attach them first: pynfcreader-relay-wsl")
            return 1
        print("Detected Proxmark3 USB ports:")
        for p in ports:
            print(f"  {p.describe()}")
        return 0

    # Resolve which physical Proxmark3 is the card side (leech) and the reader
    # side (ghost): explicit port > USB serial > auto-detect the lone USB device.
    try:
        card_spec, reader_spec = resolve_roles(
            card_port=args.card_port,
            reader_port=args.reader_port,
            card_serial=args.card_serial,
            reader_serial=args.reader_serial,
        )
    except RoleResolutionError as exc:
        print(f"could not determine device roles: {exc}", file=sys.stderr)
        return 2
    print(f"card-side (leech):  {card_spec}")
    print(f"reader-side (ghost): {reader_spec}")

    try:
        leech = CardhopperLink(
            open_transport(card_spec, baudrate=args.baud),
            name="leech",
            ack_timeout=args.ack_timeout,
        )
        ghost = CardhopperLink(
            open_transport(reader_spec, baudrate=args.baud),
            name="ghost",
            ack_timeout=args.ack_timeout,
        )
    except Exception as exc:  # noqa: BLE001 - surface any port open failure cleanly
        print(f"error opening ports: {exc}", file=sys.stderr)
        return 2

    relay = CardhopperRelay(
        leech=leech,
        ghost=ghost,
        tag_type=args.tag_type,
        fwi=args.fwi,
        sfgi=args.sfgi,
    )
    try:
        relay.run()
    except CardhopperError as exc:
        print(f"relay error: {exc}", file=sys.stderr)
        return 1
    finally:
        leech.close()
        ghost.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
