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

"""Unit tests for the CardHopper packet link. No hardware required."""

import pytest

from pynfcreader.relay.cardhopper import (
    ACK_BYTE,
    CardhopperError,
    CardhopperLink,
    MAGIC_READ,
    describe_frame,
    is_rats,
)


class FakeTransport:
    """In-memory transport: ``rx`` is the byte stream the host reads, ``tx``
    captures what the host writes."""

    def __init__(self, rx: bytes = b""):
        self.rx = bytearray(rx)
        self.tx = bytearray()
        self.closed = False

    def feed(self, data: bytes):
        self.rx.extend(data)

    def read(self, n: int) -> bytes:
        chunk = bytes(self.rx[:n])
        del self.rx[:n]
        return chunk

    def write(self, data: bytes) -> None:
        self.tx.extend(data)

    def close(self) -> None:
        self.closed = True


def test_send_packet_frames_and_consumes_ack():
    t = FakeTransport(rx=bytes([ACK_BYTE]))
    link = CardhopperLink(t, name="x")
    link.send_packet(b"READ")
    # length prefix + payload
    assert bytes(t.tx) == bytes([4]) + b"READ"
    # ACK was consumed
    assert len(t.rx) == 0


def test_send_packet_rejects_missing_ack():
    t = FakeTransport(rx=bytes([0x00]))  # wrong ACK byte
    link = CardhopperLink(t, name="x", ack_timeout=0.1)
    with pytest.raises(CardhopperError):
        link.send_packet(b"CARD")


def test_send_packet_rejects_oversized_payload():
    link = CardhopperLink(FakeTransport(), name="x")
    with pytest.raises(CardhopperError):
        link.send_packet(b"\x00" * 256)


def test_recv_packet_reads_length_then_data():
    payload = b"\x6f\x45\x84"
    t = FakeTransport(rx=bytes([len(payload)]) + payload)
    link = CardhopperLink(t, name="x")
    assert link.recv_packet() == payload


def test_recv_packet_zero_length_is_empty():
    t = FakeTransport(rx=bytes([0]))
    link = CardhopperLink(t, name="x")
    assert link.recv_packet() == b""


def test_recv_packet_times_out_on_truncated_data():
    t = FakeTransport(rx=bytes([4]) + b"AB")  # claims 4 bytes, only 2 available
    link = CardhopperLink(t, name="x", ack_timeout=0.1)
    with pytest.raises(CardhopperError):
        link.recv_packet(timeout=0.1)


def test_mode_helpers_send_magics():
    t = FakeTransport(rx=bytes([ACK_BYTE]))
    link = CardhopperLink(t, name="x")
    link.become_reader()
    assert bytes(t.tx) == bytes([len(MAGIC_READ)]) + MAGIC_READ


def test_describe_and_is_rats():
    assert is_rats(b"\xe0\x50")
    assert not is_rats(b"\x02\x00")
    assert "RATS" in describe_frame(b"\xe0\x50")
    assert "I-block" in describe_frame(b"\x02\x00\xa4\x04")
    assert describe_frame(b"") == "<empty>"
