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
    SerialTransport,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pynfcreader-relay",
        description="Relay an ISO14443-A session between two Proxmark3 devices "
        "running the HF_CARDHOPPER standalone firmware. Authorized testing only.",
    )
    parser.add_argument(
        "--card-port",
        required=True,
        help="serial port of the Proxmark3 next to the real CARD (leech / reader mode), "
        "e.g. /dev/ttyACM0",
    )
    parser.add_argument(
        "--reader-port",
        required=True,
        help="serial port of the Proxmark3 next to the real READER (ghost / card mode), "
        "e.g. /dev/rfcomm0",
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

    try:
        leech = CardhopperLink(
            SerialTransport(args.card_port, baudrate=args.baud),
            name="leech",
            ack_timeout=args.ack_timeout,
        )
        ghost = CardhopperLink(
            SerialTransport(args.reader_port, baudrate=args.baud),
            name="ghost",
            ack_timeout=args.ack_timeout,
        )
    except Exception as exc:  # noqa: BLE001 - surface any serial open failure cleanly
        print(f"error opening serial ports: {exc}", file=sys.stderr)
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
