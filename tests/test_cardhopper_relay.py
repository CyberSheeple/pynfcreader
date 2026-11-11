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

"""End-to-end relay logic test driven by scripted fake Proxmark3 links.

A real relay is reader-driven ping-pong; here both links are pre-loaded with the
exact byte streams the firmware would send, and we assert the bytes the host
bridge writes back. No hardware required.
"""

from pynfcreader.relay.cardhopper import ACK_BYTE, CardhopperLink, CardhopperRelay

from tests.test_cardhopper_link import FakeTransport

ACK = bytes([ACK_BYTE])
UID = bytes.fromhex("04112233")
ATS = bytes.fromhex("0578807002")


def _packet(data: bytes) -> bytes:
    return bytes([len(data)]) + data


def build_relay():
    # What the host READS from the leech (near the real card, READER mode):
    leech_rx = (
        ACK  # ack of READ
        + _packet(UID)  # UID reported after select
        + _packet(ATS)  # ATS reported after select
        + ACK + _packet(ATS)  # exchange 1 (RATS): ack of cmd + card response
        + ACK + _packet(bytes.fromhex("029000"))  # exchange 2 (APDU): ack + response
    )
    # What the host READS from the ghost (near the real reader, CARD mode):
    ghost_rx = (
        ACK * 5  # become_card + 4 config packets
        + _packet(bytes.fromhex("e050"))  # exchange 1: forwarded RATS (no reply consumed)
        + _packet(bytes.fromhex("0200"))  # exchange 2: forwarded APDU
        + ACK  # exchange 2: ack of the relayed response
    )
    leech = CardhopperLink(FakeTransport(leech_rx), name="leech", ack_timeout=0.5)
    ghost = CardhopperLink(FakeTransport(ghost_rx), name="ghost", ack_timeout=0.5)
    frames = []
    relay = CardhopperRelay(
        leech, ghost, tag_type=1, fwi=14, sfgi=0,
        on_frame=lambda direction, data: frames.append((direction, data)),
    )
    return relay, leech, ghost, frames


def test_read_card_identity_captures_uid_and_ats():
    relay, leech, _ghost, _ = build_relay()
    relay.read_card_identity()
    assert relay.uid == UID
    assert relay.ats == ATS
    assert bytes(leech.transport.tx) == _packet(b"READ")


def test_configure_ghost_sends_expected_config():
    relay, _leech, ghost, _ = build_relay()
    relay.read_card_identity()
    relay.configure_ghost()
    expected = (
        _packet(b"CARD")
        + _packet(bytes([1]))  # tag type
        + _packet(bytes([14, 0]))  # fwi, sfgi
        + _packet(UID)
        + _packet(ATS)
    )
    assert bytes(ghost.transport.tx) == expected


def test_relay_rats_is_not_replied_to_ghost():
    relay, leech, ghost, frames = build_relay()
    relay.read_card_identity()
    relay.configure_ghost()

    assert relay.relay_once(timeout=0.5) is True  # RATS exchange

    # RATS was forwarded to the leech ...
    assert bytes(leech.transport.tx) == _packet(b"READ") + _packet(bytes.fromhex("e050"))
    # ... but no card response was pushed back to the ghost (it answered locally).
    assert bytes(ghost.transport.tx).endswith(_packet(ATS))  # last write was the ATS config
    assert ("reader->card", bytes.fromhex("e050")) in frames


def test_relay_apdu_round_trips_response():
    relay, leech, ghost, frames = build_relay()
    relay.read_card_identity()
    relay.configure_ghost()
    relay.relay_once(timeout=0.5)  # RATS
    ghost_tx_before = bytes(ghost.transport.tx)

    assert relay.relay_once(timeout=0.5) is True  # APDU

    # command relayed to the leech, response relayed back to the ghost
    assert bytes(leech.transport.tx).endswith(_packet(bytes.fromhex("0200")))
    assert bytes(ghost.transport.tx) == ghost_tx_before + _packet(bytes.fromhex("029000"))
    assert ("card->reader", bytes.fromhex("029000")) in frames
