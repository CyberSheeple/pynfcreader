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

"""Attach USB Proxmark3 devices into WSL2 via ``usbipd-win``.

WSL2 has no USB stack of its own; USB devices are forwarded from Windows with
`usbipd-win <https://github.com/dorssel/usbipd-win>`_. This module calls the
Windows ``usbipd.exe`` from inside WSL (Windows interop) to list, bind and attach
Proxmark3 devices, then waits for the ``/dev/ttyACM*`` node to appear.

Note: ``usbipd`` forwards **USB** devices only. A Bluetooth-paired Proxmark3 X is
a Windows COM port, not a USB device, so it cannot be attached this way -- bridge
its COM port over TCP instead (see ``docs/relay-cardhopper.md``) and point the
relay at ``tcp:HOST:PORT``.

Exposed as the ``pynfcreader-relay-wsl`` console command.
"""

import argparse
import glob
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional

from pynfcreader.relay.detect import PROXMARK_USB_IDS

USBIPD = "usbipd.exe"

# State strings usbipd-win prints for a device that is already forwarded.
_ATTACHED_STATES = ("Attached",)
_SHARED_STATES = ("Shared", "Shared (forced)", "Attached")


@dataclass
class UsbipDevice:
    busid: str
    vid: int
    pid: int
    device: str
    state: str

    @property
    def is_proxmark(self) -> bool:
        return (self.vid, self.pid) in PROXMARK_USB_IDS or "proxmark" in self.device.lower()

    @property
    def is_shared(self) -> bool:
        return any(self.state.startswith(s) for s in _SHARED_STATES)

    @property
    def is_attached(self) -> bool:
        return any(self.state.startswith(s) for s in _ATTACHED_STATES)


def in_wsl() -> bool:
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


_LINE_RE = re.compile(
    r"^(?P<busid>\d+-\d+)\s+(?P<vidpid>[0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(?P<rest>.+)$"
)


def parse_usbipd_list(text: str) -> List[UsbipDevice]:
    """Parse ``usbipd list`` output into the connected device rows."""
    devices: List[UsbipDevice] = []
    in_connected = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("Connected:"):
            in_connected = True
            continue
        if line.startswith("Persisted:"):
            in_connected = False
            continue
        if not in_connected or not line.strip():
            continue
        if line.lstrip().startswith("BUSID"):
            continue  # header row
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        vid, pid = m.group("vidpid").split(":")
        # DEVICE and STATE are separated by 2+ spaces of column padding.
        parts = re.split(r"\s{2,}", m.group("rest").strip())
        device = parts[0] if parts else ""
        state = parts[-1] if len(parts) > 1 else ""
        devices.append(
            UsbipDevice(
                busid=m.group("busid"),
                vid=int(vid, 16),
                pid=int(pid, 16),
                device=device,
                state=state,
            )
        )
    return devices


def _run(args: List[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            f"'{args[0]}' not found. Install usbipd-win on Windows "
            "(https://github.com/dorssel/usbipd-win) and ensure WSL interop is enabled."
        )


def usbipd_list() -> List[UsbipDevice]:
    proc = _run([USBIPD, "list"])
    if proc.returncode != 0:
        raise RuntimeError(f"usbipd list failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return parse_usbipd_list(proc.stdout)


def usbipd_bind(busid: str, elevate: bool = False) -> None:
    """Share a device so it can be attached (requires admin once, persistent).

    With ``elevate`` a UAC prompt is raised via PowerShell ``Start-Process -Verb
    RunAs``; otherwise a plain (non-elevated) bind is attempted.
    """
    if elevate:
        ps = (
            "Start-Process usbipd -Verb RunAs -Wait -ArgumentList "
            f"'bind','--busid','{busid}'"
        )
        proc = _run(["powershell.exe", "-NoProfile", "-Command", ps])
    else:
        proc = _run([USBIPD, "bind", "--busid", busid])
    if proc.returncode != 0:
        raise RuntimeError(
            f"usbipd bind --busid {busid} failed: {proc.stderr.strip() or proc.stdout.strip()}\n"
            f"Run it once in an elevated (Administrator) Windows shell: usbipd bind --busid {busid}\n"
            f"or re-run this command with --elevate."
        )


def usbipd_attach(busid: str) -> None:
    proc = _run([USBIPD, "attach", "--wsl", "--busid", busid])
    if proc.returncode != 0:
        raise RuntimeError(
            f"usbipd attach --busid {busid} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )


def attach_proxmarks(bind: bool = False, elevate: bool = False, timeout: float = 10.0) -> List[str]:
    """Attach all connected Proxmark3 USB devices into WSL.

    Returns the list of ``/dev/ttyACM*`` nodes that appeared.
    """
    before = set(glob.glob("/dev/ttyACM*"))
    devices = [d for d in usbipd_list() if d.is_proxmark]
    if not devices:
        raise RuntimeError("no Proxmark3 USB devices found by usbipd (is it plugged in?)")

    for dev in devices:
        if dev.is_attached:
            print(f"  {dev.busid} {dev.device}: already attached")
            continue
        if not dev.is_shared:
            if bind:
                print(f"  {dev.busid} {dev.device}: binding ...")
                usbipd_bind(dev.busid, elevate=elevate)
            else:
                raise RuntimeError(
                    f"device {dev.busid} ({dev.device}) is not shared. "
                    f"Run once as admin: usbipd bind --busid {dev.busid} "
                    f"(or re-run with --bind [--elevate])."
                )
        print(f"  {dev.busid} {dev.device}: attaching ...")
        usbipd_attach(dev.busid)

    # Wait for the new serial nodes to show up in WSL.
    deadline = time.monotonic() + timeout
    new: set = set()
    while time.monotonic() < deadline:
        new = set(glob.glob("/dev/ttyACM*")) - before
        if len(new) >= len([d for d in devices if not d.is_attached]):
            break
        time.sleep(0.3)
    return sorted(new)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pynfcreader-relay-wsl",
        description="Attach USB Proxmark3 devices into WSL2 via usbipd-win, for the relay tool.",
    )
    parser.add_argument("--list", action="store_true", help="list Proxmark3 USB devices and exit")
    parser.add_argument(
        "--bind",
        action="store_true",
        help="run 'usbipd bind' for devices that are not shared yet (needs admin)",
    )
    parser.add_argument(
        "--elevate",
        action="store_true",
        help="raise a UAC prompt to perform bind (implies --bind)",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="seconds to wait for /dev/ttyACM* (default 10)"
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not in_wsl():
        print("warning: this does not look like a WSL environment; running anyway.", file=sys.stderr)

    try:
        if args.list:
            devices = usbipd_list()
            pm = [d for d in devices if d.is_proxmark]
            if not pm:
                print("No Proxmark3 USB devices found by usbipd.")
                return 1
            print("Proxmark3 USB devices (usbipd):")
            for d in pm:
                print(f"  busid={d.busid}  {d.vid:04x}:{d.pid:04x}  {d.device}  [{d.state}]")
            return 0

        print("Attaching Proxmark3 USB devices into WSL ...")
        nodes = attach_proxmarks(bind=args.bind or args.elevate, elevate=args.elevate, timeout=args.timeout)
        if nodes:
            print("Attached. New serial nodes:")
            for n in nodes:
                print(f"  {n}")
        else:
            print("Attach issued; no new /dev/ttyACM* detected (they may already be attached).")
        print("\nTip: run 'pynfcreader-relay --list-devices' to see Proxmark3 ports and serials.")
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
