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

"""Detect connected Proxmark3 serial ports and resolve them to relay roles.

Software cannot know which Proxmark3 is physically near the card and which is near
the reader -- that is a placement decision. What it *can* do is enumerate the
Proxmark3 USB serial ports and their stable USB serial numbers, so a role can be
pinned by ``--card-serial`` / ``--reader-serial`` (stable across reboots) or, in
the common "1 USB + 1 Bluetooth" setup, the single USB device can be auto-assigned
to the side whose port was not given explicitly.
"""

from dataclasses import dataclass
from typing import List, Optional

# USB VID:PID advertised by RfidResearchGroup / Iceman Proxmark3 CDC firmware.
PROXMARK_USB_IDS = {(0x9AC4, 0x4B8F)}


@dataclass
class ProxmarkPort:
    device: str
    serial_number: Optional[str]
    vid: Optional[int]
    pid: Optional[int]
    description: str

    def describe(self) -> str:
        vidpid = (
            f"{self.vid:04x}:{self.pid:04x}" if self.vid is not None and self.pid is not None else "????:????"
        )
        return f"{self.device}  [{vidpid}]  serial={self.serial_number or '-'}  {self.description}"


def _looks_like_proxmark(vid, pid, description, manufacturer) -> bool:
    if vid is not None and pid is not None and (vid, pid) in PROXMARK_USB_IDS:
        return True
    for field in (description, manufacturer):
        if field and "proxmark" in field.lower():
            return True
    return False


def list_proxmark_ports() -> List[ProxmarkPort]:
    """Enumerate connected Proxmark3 USB serial ports (requires ``pyserial``)."""
    from serial.tools import list_ports

    found = []
    for p in list_ports.comports():
        if _looks_like_proxmark(p.vid, p.pid, p.description, p.manufacturer):
            found.append(
                ProxmarkPort(
                    device=p.device,
                    serial_number=p.serial_number,
                    vid=p.vid,
                    pid=p.pid,
                    description=p.description or "",
                )
            )
    return sorted(found, key=lambda x: (x.serial_number or "", x.device))


def find_port_by_serial(serial_number: str, ports: Optional[List[ProxmarkPort]] = None) -> str:
    """Return the device path of the Proxmark3 with the given USB serial number."""
    if ports is None:
        ports = list_proxmark_ports()
    matches = [p.device for p in ports if p.serial_number == serial_number]
    if not matches:
        raise LookupError(f"no Proxmark3 with USB serial '{serial_number}' found")
    if len(matches) > 1:
        raise LookupError(f"multiple Proxmark3 ports share USB serial '{serial_number}': {matches}")
    return matches[0]


class RoleResolutionError(Exception):
    """Raised when the card/reader port cannot be determined unambiguously."""


def resolve_roles(
    card_port: Optional[str],
    reader_port: Optional[str],
    card_serial: Optional[str],
    reader_serial: Optional[str],
    ports: Optional[List[ProxmarkPort]] = None,
):
    """Resolve the card-side and reader-side port specs.

    Priority per side: explicit ``*_port`` > ``*_serial`` lookup > auto-assign the
    remaining single USB Proxmark3. A ``tcp:`` / rfcomm spec given for one side lets
    the lone USB device fall to the other side automatically. Raises
    :class:`RoleResolutionError` when it stays ambiguous.
    """
    if ports is None:
        ports = list_proxmark_ports()

    def resolve_explicit(port, serial, label):
        if port:
            return port
        if serial:
            try:
                return find_port_by_serial(serial, ports)
            except LookupError as exc:
                raise RoleResolutionError(str(exc))
        return None

    card = resolve_explicit(card_port, card_serial, "card")
    reader = resolve_explicit(reader_port, reader_serial, "reader")

    taken = {p for p in (card, reader) if p}
    pool = [p.device for p in ports if p.device not in taken]

    def auto(label):
        if len(pool) == 0:
            raise RoleResolutionError(
                f"no USB Proxmark3 available to auto-assign the {label} side; "
                f"pass --{label}-port or --{label}-serial (see --list-devices)"
            )
        if len(pool) > 1:
            raise RoleResolutionError(
                f"multiple USB Proxmark3 devices found; cannot tell which is the {label} side. "
                f"Pin each with --card-serial/--reader-serial (see --list-devices)"
            )
        return pool.pop(0)

    if card is None:
        card = auto("card")
    if reader is None:
        reader = auto("reader")
    return card, reader
