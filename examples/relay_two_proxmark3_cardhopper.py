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

"""Minimal two-Proxmark3 ISO14443-A relay using the HF_CARDHOPPER firmware.

Both Proxmark3 devices must be flashed with the HF_CARDHOPPER standalone mode
(see docs/relay-cardhopper.md). One sits next to the real card (here on USB,
``/dev/ttyACM0``) and becomes the leech; the other sits next to the real reader
(here over Bluetooth rfcomm, ``/dev/rfcomm0``) and becomes the ghost.

For authorized security testing and research only.

You can also just run the installed CLI::

    pynfcreader-relay --card-port /dev/ttyACM0 --reader-port /dev/rfcomm0
"""

import logging

from pynfcreader.relay import CardhopperLink, CardhopperRelay, SerialTransport

logging.basicConfig(level=logging.INFO, format="%(message)s")

CARD_PORT = "/dev/ttyACM0"    # Proxmark3 next to the real CARD (leech / reader mode)
READER_PORT = "/dev/rfcomm0"  # Proxmark3 next to the real READER (ghost / card mode)

leech = CardhopperLink(SerialTransport(CARD_PORT), name="leech")
ghost = CardhopperLink(SerialTransport(READER_PORT), name="ghost")

relay = CardhopperRelay(leech=leech, ghost=ghost, tag_type=1, fwi=14, sfgi=0)

try:
    relay.run()
finally:
    leech.close()
    ghost.close()
