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

"""Tests for Proxmark3 role resolution and transport-spec parsing. No hardware."""

import pytest

from pynfcreader.relay.cardhopper import CardhopperError, parse_transport_spec
from pynfcreader.relay.detect import ProxmarkPort, RoleResolutionError, resolve_roles


def _port(device, serial):
    return ProxmarkPort(device=device, serial_number=serial, vid=0x9AC4, pid=0x4B8F, description="Proxmark3")


TWO = [_port("/dev/ttyACM0", "AAAA"), _port("/dev/ttyACM1", "BBBB")]
ONE = [_port("/dev/ttyACM0", "AAAA")]


def test_explicit_ports_win():
    card, reader = resolve_roles("/dev/ttyACM9", "tcp:host:5555", None, None, ports=TWO)
    assert card == "/dev/ttyACM9"
    assert reader == "tcp:host:5555"


def test_resolve_by_serial():
    card, reader = resolve_roles(None, None, "BBBB", "AAAA", ports=TWO)
    assert card == "/dev/ttyACM1"
    assert reader == "/dev/ttyACM0"


def test_bluetooth_reader_autofills_lone_usb_card():
    # Common setup: 1 USB Proxmark (card) + Bluetooth/TCP reader given explicitly.
    card, reader = resolve_roles(None, "/dev/rfcomm0", None, None, ports=ONE)
    assert card == "/dev/ttyACM0"
    assert reader == "/dev/rfcomm0"


def test_two_usb_without_pins_is_ambiguous():
    with pytest.raises(RoleResolutionError):
        resolve_roles(None, None, None, None, ports=TWO)


def test_unknown_serial_errors():
    with pytest.raises(RoleResolutionError):
        resolve_roles(None, "/dev/rfcomm0", "ZZZZ", None, ports=ONE)


def test_no_usb_and_no_specs_errors():
    with pytest.raises(RoleResolutionError):
        resolve_roles(None, None, None, None, ports=[])


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("/dev/ttyACM0", ("serial", "/dev/ttyACM0", None)),
        ("/dev/rfcomm0", ("serial", "/dev/rfcomm0", None)),
        ("tcp:1.2.3.4:5555", ("tcp", "1.2.3.4", 5555)),
        ("tcp://host.local:9999", ("tcp", "host.local", 9999)),
    ],
)
def test_parse_transport_spec(spec, expected):
    assert parse_transport_spec(spec) == expected


def test_parse_transport_spec_rejects_bad_tcp():
    with pytest.raises(CardhopperError):
        parse_transport_spec("tcp:host-without-port")
