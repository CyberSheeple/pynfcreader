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

"""Host-side bridge for the Proxmark3 ``HF_CARDHOPPER`` standalone relay.

Two Proxmark3 devices are flashed with the ``HF_CARDHOPPER`` standalone mode.
One is placed near the victim's **card** and is told to become a *reader*
(``READ`` mode, the "leech"); the other is placed near the target **reader** and
is told to become a *card* (``CARD`` mode, the "ghost"). This module is the host
that bridges the two serial links and relays the ISO14443-A session between them.

Wire protocol (decoded from ``armsrc/Standalone/hf_cardhopper.c``):

* A packet is ``[len:1][data:len]`` on both links.
* **host -> PM3** packets are acknowledged by the PM3 with a single ``0xFE`` byte.
  The host must consume that ACK after every send.
* **PM3 -> host** packets are raw ``[len][data]`` with no ACK.
* Mode magics (sent host -> PM3, as ordinary packets): ``READ``, ``CARD``,
  ``\\xffEND``, ``RESTART``.

Handshake:

1. Leech: send ``READ``. The firmware selects the real card, then sends two raw
   packets back: the UID, then the ATS.
2. Ghost: send ``CARD``. The firmware then reads four packets from the host:
   ``tag_type`` (1 byte), ``time_mode`` (2 bytes: fwi, sfgi), ``uid``, ``ats``.
3. Relay loop (reader-driven): read a forwarded reader command from the ghost,
   send it to the leech, read the card response from the leech, send it back to
   the ghost. The firmware answers all low-level 14a housekeeping (ATQA /
   anticollision / SAK / PPS / WTX / HALT) locally and only forwards RATS and
   application APDUs. For RATS the ghost replies with its own cooked ATS and does
   *not* consume a relayed reply, so the host must not forward one.
"""

import logging
import time
from typing import List, Optional, Protocol

from pynfcreader.sessions.iso14443.tpdu import Tpdu

# Mode / control magics (host -> PM3)
MAGIC_READ = b"READ"
MAGIC_CARD = b"CARD"
MAGIC_END = b"\xffEND"
MAGIC_RESTART = b"RESTART"

# Sentinels from PM3 -> host
MAGIC_ERR = b"\xffERR"

# Single-byte ACK the firmware sends after reading a host packet
ACK_BYTE = 0xFE

# Max payload a cardhopper packet can carry (len field is one byte)
MAX_PACKET_LEN = 255

# ISO14443-A RATS command byte. The ghost answers RATS locally with a cooked ATS,
# so a relayed reply for it must not be sent back to the ghost.
RATS_CMD = 0xE0

logger = logging.getLogger(__name__)


class CardhopperError(Exception):
    """Raised on a protocol / transport error while bridging."""


class Transport(Protocol):
    """Minimal byte transport used by :class:`CardhopperLink`.

    Implemented by :class:`SerialTransport` for real hardware and by fakes in the
    tests. ``read`` returns *up to* ``n`` bytes (possibly fewer on timeout).
    """

    def read(self, n: int) -> bytes: ...

    def write(self, data: bytes) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    """``pyserial``-backed :class:`Transport`.

    ``timeout`` is the per-read poll timeout; :class:`CardhopperLink` loops on top
    of it to read exact byte counts with its own deadline.
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.2):
        import serial  # imported lazily so the package can be used/tested without hardware

        self.port = port
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)

    def read(self, n: int) -> bytes:
        return self._serial.read(n)

    def write(self, data: bytes) -> None:
        self._serial.write(data)
        self._serial.flush()

    def reset_input_buffer(self) -> None:
        self._serial.reset_input_buffer()

    def close(self) -> None:
        self._serial.close()


class CardhopperLink:
    """One serial link to a Proxmark3 running ``HF_CARDHOPPER``.

    Wraps a :class:`Transport` and speaks the length-prefixed packet protocol,
    handling the ``0xFE`` ACK that follows every host -> PM3 packet.
    """

    def __init__(self, transport: Transport, name: str = "", ack_timeout: float = 2.0):
        self.transport = transport
        self.name = name or "pm3"
        self.ack_timeout = ack_timeout

    # -- low level -----------------------------------------------------------

    def _read_exact(self, n: int, timeout: Optional[float]) -> bytes:
        """Read exactly ``n`` bytes. ``timeout=None`` blocks indefinitely."""
        if n == 0:
            return b""
        buf = bytearray()
        deadline = None if timeout is None else time.monotonic() + timeout
        while len(buf) < n:
            chunk = self.transport.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
                continue
            if deadline is not None and time.monotonic() >= deadline:
                raise CardhopperError(
                    f"[{self.name}] timed out reading {n} bytes (got {len(buf)})"
                )
        return bytes(buf)

    # -- packet protocol -----------------------------------------------------

    def send_packet(self, data: bytes) -> None:
        """Send one packet (``[len][data]``) and consume the ``0xFE`` ACK."""
        if len(data) > MAX_PACKET_LEN:
            raise CardhopperError(
                f"[{self.name}] packet too long: {len(data)} > {MAX_PACKET_LEN}"
            )
        self.transport.write(bytes([len(data)]) + data)
        ack = self._read_exact(1, timeout=self.ack_timeout)
        if ack[0] != ACK_BYTE:
            raise CardhopperError(
                f"[{self.name}] expected ACK 0x{ACK_BYTE:02x}, got 0x{ack[0]:02x}"
            )

    def recv_packet(self, timeout: Optional[float] = None) -> bytes:
        """Receive one raw packet (``[len][data]``). Blocks when ``timeout`` is None."""
        length = self._read_exact(1, timeout=timeout)[0]
        if length == 0:
            return b""
        return self._read_exact(length, timeout=self.ack_timeout)

    # -- mode helpers --------------------------------------------------------

    def become_reader(self) -> None:
        """Tell this PM3 to become a reader (leech, near the real card)."""
        self.send_packet(MAGIC_READ)

    def become_card(self) -> None:
        """Tell this PM3 to become a card (ghost, near the real reader)."""
        self.send_packet(MAGIC_CARD)

    def restart(self) -> None:
        self.send_packet(MAGIC_RESTART)

    def end(self) -> None:
        self.send_packet(MAGIC_END)

    def close(self) -> None:
        self.transport.close()


def decode_frame(data: bytes) -> Optional[Tpdu]:
    """Best-effort decode of a CRC-less relayed frame into a :class:`Tpdu`.

    CardHopper strips the 2-byte CRC before forwarding, but :class:`Tpdu` expects
    a trailing CRC, so a placeholder is appended. Used for logging only.
    """
    if not data:
        return None
    try:
        return Tpdu(data + b"\x00\x00")
    except Exception:  # noqa: BLE001 - logging helper must never raise
        return None


def describe_frame(data: bytes) -> str:
    """Human-readable one-line description of a relayed frame, for the trace log."""
    if not data:
        return "<empty>"
    if data == MAGIC_ERR:
        return "ERR (no card response)"
    tpdu = decode_frame(data)
    kind = "?"
    if tpdu is not None:
        if tpdu.i:
            kind = "I-block" + (" (chaining)" if tpdu.is_chaining() else "")
        elif tpdu.r:
            kind = "R-block"
        elif tpdu.s:
            kind = "S-block"
    if data[0] == RATS_CMD:
        kind = "RATS"
    return f"{kind} {data.hex()}"


def is_rats(data: bytes) -> bool:
    return len(data) >= 1 and data[0] == RATS_CMD


class CardhopperRelay:
    """Bridge a full ISO14443-A session between a leech and a ghost Proxmark3.

    :param leech: link to the PM3 near the real **card** (becomes a reader).
    :param ghost: link to the PM3 near the real **reader** (becomes a card).
    :param tag_type: ``hf 14a sim`` tag type byte sent to the ghost.
    :param fwi: Frame Waiting time Integer (0-14) baked into the ghost's cooked
        ATS; a high value buys time for relay latency.
    :param sfgi: Start-up Frame Guard time Integer (0-14).
    """

    def __init__(
        self,
        leech: CardhopperLink,
        ghost: CardhopperLink,
        tag_type: int = 1,
        fwi: int = 14,
        sfgi: int = 0,
        on_frame=None,
    ):
        self.leech = leech
        self.ghost = ghost
        self.tag_type = tag_type & 0xFF
        self.fwi = fwi & 0x0F
        self.sfgi = sfgi & 0x0F
        self.on_frame = on_frame or self._default_on_frame
        self.uid: bytes = b""
        self.ats: bytes = b""

    @staticmethod
    def _default_on_frame(direction: str, data: bytes) -> None:
        logger.info("%s %s", direction, describe_frame(data))

    # -- setup ---------------------------------------------------------------

    def read_card_identity(self) -> None:
        """Start the leech and capture the real card's UID and ATS.

        Blocks until a card is present on the leech's antenna.
        """
        logger.info("Leech: entering READER mode, waiting for a card ...")
        self.leech.become_reader()
        self.uid = self.leech.recv_packet()
        self.ats = self.leech.recv_packet()
        logger.info("Leech: card UID %s", self.uid.hex())
        logger.info("Leech: card ATS %s", self.ats.hex() or "<none>")

    def configure_ghost(self) -> None:
        """Start the ghost and push the emulation parameters it expects."""
        if not self.uid:
            raise CardhopperError("read_card_identity() must run before configure_ghost()")
        logger.info("Ghost: entering CARD mode, configuring emulation ...")
        self.ghost.become_card()
        self.ghost.send_packet(bytes([self.tag_type]))
        self.ghost.send_packet(bytes([self.fwi, self.sfgi]))
        self.ghost.send_packet(self.uid)
        self.ghost.send_packet(self.ats)
        logger.info("Ghost: ready, emulating UID %s", self.uid.hex())

    # -- relay ---------------------------------------------------------------

    def relay_once(self, timeout: Optional[float] = None) -> bool:
        """Relay a single reader command / card response exchange.

        Returns ``False`` when the ghost signalled a restart/teardown, ``True``
        otherwise.
        """
        cmd = self.ghost.recv_packet(timeout=timeout)
        if not cmd:
            return True
        if cmd == MAGIC_RESTART:
            logger.info("Ghost: RESTART received, ending relay")
            return False
        self.on_frame("reader->card", cmd)

        self.leech.send_packet(cmd)
        resp = self.leech.recv_packet()
        self.on_frame("card->reader", resp)

        # On RATS the ghost already answered with its cooked ATS and is not
        # waiting for a relayed reply, so we must not send one.
        if is_rats(cmd):
            return True

        self.ghost.send_packet(resp)
        return True

    def run(self) -> None:
        """Full relay session: capture identity, configure ghost, then loop."""
        self.read_card_identity()
        self.configure_ghost()
        logger.info("Relay running. Present the ghost to a reader. Ctrl-C to stop.")
        try:
            while self.relay_once():
                pass
        except KeyboardInterrupt:
            logger.info("Interrupted, tearing down ...")
        finally:
            self.teardown()

    def teardown(self) -> None:
        for link in (self.ghost, self.leech):
            try:
                link.restart()
            except Exception:  # noqa: BLE001 - best effort on shutdown
                pass
