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

"""Tests for the usbipd list parser (no Windows / no WSL required)."""

from pynfcreader.relay.wsl import parse_usbipd_list

SAMPLE = """\
Connected:
BUSID  VID:PID    DEVICE                                                        STATE
1-4    9ac4:4b8f  USB Serial Device (COM5)                                      Not shared
1-7    0a5c:5842  Realtek Bluetooth Adapter                                     Not shared
2-1    9ac4:4b8f  USB Serial Device (COM7)                                      Attached

Persisted:
GUID                                  DEVICE
f1b2...                               Some persisted device
"""


def test_parses_connected_rows_only():
    devices = parse_usbipd_list(SAMPLE)
    busids = [d.busid for d in devices]
    assert busids == ["1-4", "1-7", "2-1"]


def test_identifies_proxmark_by_vidpid():
    devices = parse_usbipd_list(SAMPLE)
    pm = [d for d in devices if d.is_proxmark]
    assert [d.busid for d in pm] == ["1-4", "2-1"]
    assert pm[0].vid == 0x9AC4 and pm[0].pid == 0x4B8F


def test_state_and_device_split_on_padding():
    devices = parse_usbipd_list(SAMPLE)
    d = devices[0]
    assert d.device == "USB Serial Device (COM5)"
    assert d.state == "Not shared"
    assert not d.is_shared and not d.is_attached


def test_attached_state_detected():
    devices = parse_usbipd_list(SAMPLE)
    attached = devices[2]
    assert attached.busid == "2-1"
    assert attached.is_attached
    assert attached.is_shared  # "Attached" implies shared


def test_empty_input():
    assert parse_usbipd_list("") == []
