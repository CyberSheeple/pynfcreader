# Two-Proxmark3 ISO14443-A relay (CardHopper host bridge)

> ⚠️ **Authorized security testing and research only.** Relaying contactless
> credentials against systems you do not own or have explicit written permission
> to test is illegal in most jurisdictions.

This tool relays a full ISO14443-A (NFC type A) session between two
[Proxmark3](https://github.com/RfidResearchGroup/proxmark3) devices running the
built-in `HF_CARDHOPPER` standalone firmware. `pynfcreader` provides the
**host-side bridge** that CardHopper needs — the piece that shuttles frames
between the two Proxmarks — which is otherwise only available as a closed-source
Android app.

```
   real card                                                 real reader
      ))) ──▶ [ PM3 #1  "leech" ] ──USB──┐        ┌──BT──▶ [ PM3 #2 "ghost" ] ──▶ (((
             (HF_CARDHOPPER, READ mode)   │        │       (HF_CARDHOPPER, CARD mode)
                                          ▼        ▼
                                     ┌──────────────────┐
                                     │  pynfcreader      │
                                     │  CardhopperRelay  │  ← this host bridge
                                     └──────────────────┘
```

- **Leech** (`--card-port`): placed on the **real card**, told `READ`, acts as a
  reader and reads the card.
- **Ghost** (`--reader-port`): placed at the **real reader**, told `CARD`, emulates
  the card using the leech's UID/ATS.

## Hardware

| Role  | Device                              | Link                       |
|-------|-------------------------------------|----------------------------|
| Leech | Proxmark3 Easy (or any PM3)         | USB CDC (`/dev/ttyACM0`)   |
| Ghost | Proxmark3 X (built-in Bluetooth)    | Bluetooth (`/dev/rfcomm0`) |

> The Bluetooth end needs a PM3 whose Bluetooth is a **classic-BT SPP serial
> bridge** (the firmware's FPC/usart channel bridged to Bluetooth). The
> **Proxmark3 X** (MTools) has one built in: it pairs with PIN `1234`, runs at
> 115200 baud and exposes a serial port — functionally equivalent to an RDV4 +
> BlueShark. A plain **Proxmark3 Easy has no Bluetooth**, so it is the USB end
> here. Either device can be leech or ghost; both ends can also run over USB for a
> fully wired bench. (An RDV4 + BlueShark works too — same firmware recipe below.)

## Firmware

Flash **both** devices with `HF_CARDHOPPER` (Iceman / RfidResearchGroup fork).

**USB end** — the relay channel must use USB CDC, enabled with the
`CARDHOPPER_USB` define. Add this line to `Makefile.platform`:

```
STANDALONE_PLATFORM_DEFS += -DCARDHOPPER_USB
```

then build and flash:

```bash
make clean
make STANDALONE=HF_CARDHOPPER PLATFORM=PM3GENERIC -j
./pm3-flash-fullimage
```

> Note: the Proxmark Makefile marks `HF_CARDHOPPER` as a Bluetooth mode
> (`STANDALONE_MODES_REQ_BT`), which also adds `-DWITH_FPC_USART_HOST`. With
> `-DCARDHOPPER_USB` the mode talks over USB instead; confirm the build succeeds
> for your platform.

**Bluetooth end (Proxmark3 X)** — BlueShark-style build over the BT/usart channel
(no `CARDHOPPER_USB`). MTools builds the Proxmark3 X as `PLATFORM=PM3GENERIC` with
the BT add-on, which is exactly what CardHopper's `STANDALONE_MODES_REQ_BT` path
expects:

```bash
make clean
make STANDALONE=HF_CARDHOPPER PLATFORM=PM3GENERIC PLATFORM_EXTRAS=BTADDON -j
./pm3-flash-fullimage
```

(An RDV4 + BlueShark uses the same recipe with `PLATFORM=PM3RDV4`.) Make sure the
Proxmark3 X's "Blue Shark" BT switch is ON, pair it (PIN `1234`; the BT module runs
at 115200 baud to match the BTADDON firmware), then bind an rfcomm device:

```bash
sudo rfcomm bind /dev/rfcomm0 <pm3x-bt-mac> 1
```

> **Caveat:** the Proxmark3 X is a generic-platform clone with a BlueShark-style
> classic-BT SPP bridge, so this recipe should satisfy CardHopper — but running
> `HF_CARDHOPPER` on a PM3 X specifically is not independently confirmed, and
> MTools warns that generic-platform firmware does not support every command.
> Verify the standalone build boots and pairs before relying on it.

### Normal use vs. relay use (no reflash to switch)

A `STANDALONE=HF_CARDHOPPER` build is a **complete, normal Iceman firmware** that
*also* contains the CardHopper standalone mode — flashing it does **not** remove
any normal functionality. So:

- **Normal use:** connect the `pm3` client over USB as usual; all `hf`/`lf`
  commands work. `hw status` lists `HF_CARDHOPPER` as the installed standalone
  mode. No reflash is needed to use the device normally.
- **Relay use:** enter the standalone mode by **holding the button for ~1 second**
  (the device shows its LED pattern); the host bridge then drives it. Sending a
  USB command / resetting the device returns it to normal operation.

Only **one** standalone mode can be compiled per image (unless you use
DANKARMULTI), so you would only reflash to swap CardHopper for a *different*
standalone mode — not to return to normal client use. Note: with
`-DCARDHOPPER_USB` the mode uses the USB link, so a USB device cannot be in
CardHopper mode and attached to the `pm3` client at the same time; the Bluetooth
device relays over BT and leaves its USB free.

## Install

```bash
pip install -e .          # from the repo root; pulls in pyserial
```

## Make targets

A `Makefile` wraps the whole workflow (`make help` lists everything):

```bash
make dev                              # editable install + test tooling
make test                             # relay unit tests (no hardware)
make build END=usb PM3_DIR=../proxmark3   # build HF_CARDHOPPER firmware (usb|bt)
make flash FLASH_PORT=/dev/ttyACM0    # flash the built image (over USB)
make wsl-attach                       # (WSL) usbipd bind+attach the USB Proxmark3
make list-devices                     # show Proxmark3 ports + USB serials
make start CARD_PORT=/dev/ttyACM0 READER_PORT=/dev/rfcomm0   # run in background
make status / make stop               # manage the background relay
```

Firmware targets need a RfidResearchGroup/proxmark3 checkout (`PM3_DIR`) and the
`arm-none-eabi` toolchain; they write `PM3_DIR/Makefile.platform` (backing up any
existing one) with the correct platform config for each end.

## Usage

```bash
pynfcreader-relay --card-port /dev/ttyACM0 --reader-port /dev/rfcomm0
```

Operational order:

1. Put **each** Proxmark3 into CardHopper mode first: hold its button for ~1
   second until the standalone LED pattern shows. (The host bridge talks to a
   device only once it is in this mode.)
2. Start the command. The **leech** enters reader mode and waits for a card.
3. Present the target card to the leech — it reports the UID and ATS.
4. The **ghost** is configured with that identity and starts emulating.
5. Present the ghost to the target reader; the session is relayed live. A decoded
   frame trace is printed. `Ctrl-C` to stop.

Options:

| Flag             | Default | Meaning                                                        |
|------------------|---------|----------------------------------------------------------------|
| `--card-port`    | —       | serial port of the PM3 on the real card (leech)                |
| `--reader-port`  | —       | serial port of the PM3 on the real reader (ghost)              |
| `--baud`         | 115200  | serial baudrate                                                |
| `--tag-type`     | 1       | ghost emulation tag type                                       |
| `--fwi`          | 14      | Frame Waiting time Integer in the ghost ATS (higher = more latency tolerated) |
| `--sfgi`         | 0       | Start-up Frame Guard time Integer                              |
| `--ack-timeout`  | 2.0     | seconds to wait for a Proxmark3 ACK                            |
| `-v`             | —       | debug logging                                                  |

## WSL2 (Windows) setup

WSL2 has no USB or Bluetooth stack of its own, so the two links are handled
differently.

### USB Proxmark3 (the Easy) — `usbipd`

Forward the USB device into WSL with [`usbipd-win`](https://github.com/dorssel/usbipd-win)
(install it on Windows). The repo ships a helper that calls `usbipd.exe` for you
from inside WSL:

```bash
pynfcreader-relay-wsl --list     # show Proxmark3 USB devices usbipd can see
pynfcreader-relay-wsl --bind     # bind (first time, needs admin) + attach + wait for /dev/ttyACM*
```

`--bind` shares the device, which requires admin **once**; use `--elevate` to pop
a UAC prompt, or run `usbipd bind --busid <id>` yourself in an elevated Windows
shell and then `pynfcreader-relay-wsl` (attach needs no admin). After attach the
device shows up as `/dev/ttyACM0` in WSL.

### Bluetooth Proxmark3 (the X) — TCP bridge, *not* usbipd

`usbipd` forwards **USB** devices only. A Bluetooth-paired Proxmark3 X is a
Windows **COM port**, not a USB device, and WSL2 cannot map Windows COM ports to
`/dev/ttyS*`. Two options:

1. **Simplest:** attach the Proxmark3 X over **USB** as well (with
   `pynfcreader-relay-wsl`) and run both ends over USB on the bench. You lose the
   wireless reach but the setup is trivial.
2. **Keep it wireless:** pair the X on Windows (PIN `1234`) to get its COM port,
   then bridge that COM port to TCP on Windows and point the relay at it. For
   example with [`com0com`/`com2tcp`](https://sourceforge.net/projects/com0com/)
   or a one-liner Python bridge on Windows exposing `COM5` on TCP `5555`, then:

   ```bash
   pynfcreader-relay --card-port /dev/ttyACM0 --reader-port tcp:<windows-ip>:5555
   ```

   The relay's `tcp:HOST:PORT` transport speaks the same packet protocol over the
   socket.

### Telling the two Proxmark3s apart

Software cannot know which device is physically on the card vs the reader — that
is placement. It *can* identify the Proxmark3 ports and their stable USB serials:

```bash
pynfcreader-relay --list-devices
```

Then pin each role by serial (stable across reboots) or by port:

```bash
# by USB serial
pynfcreader-relay --card-serial <serialA> --reader-serial <serialB>
# by port (Bluetooth/TCP reader + auto-detected lone USB card)
pynfcreader-relay --reader-port tcp:<windows-ip>:5555
```

In the common "1 USB + 1 Bluetooth/TCP" layout you only need to give the
Bluetooth/TCP side; the single USB Proxmark3 is auto-assigned to the other role.
With two USB devices you must pin them (by serial or port) so the card/reader
roles are never guessed wrong.

## How it works

The firmware (`armsrc/Standalone/hf_cardhopper.c`) handles all low-level 14a
housekeeping on-device (ATQA, anticollision, SAK, PPS, WTX, HALT) and "cooks" the
emulated ATS with a large Frame Waiting Time so the reader tolerates relay
latency. Only RATS and application APDUs are forwarded to the host.

The host speaks a simple length-prefixed packet protocol on each link
(`[len][data]`; host→PM3 packets are ACKed with `0xFE`, PM3→host packets are
raw). The bridge:

1. sends `READ` to the leech and captures the reported UID + ATS,
2. sends `CARD` to the ghost followed by `tag_type`, `fwi/sfgi`, `uid`, `ats`,
3. loops: read a forwarded reader command from the ghost → send it to the leech →
   read the card response → send it back to the ghost (except for RATS, which the
   ghost answers locally).

See `pynfcreader/relay/cardhopper.py` for the implementation and
`tests/test_cardhopper_*.py` for the protocol in executable form.

## Limitations / scope

- **ISO14443-A only.** No 14443-B / 15693 relay.
- **No LF (125 kHz).** True live LF relay is impractical (continuous read-only
  broadcasts with no transaction to relay); clone-and-emulate the tag instead.
- **Single host.** Both Proxmarks connect to one machine. A two-host split over
  TCP/IP (for genuine long-range relay) is a natural extension — the link
  abstraction is designed to allow it — but is not implemented here.
