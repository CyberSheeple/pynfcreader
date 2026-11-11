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

| Role  | Device                         | Link                       |
|-------|--------------------------------|----------------------------|
| Leech | Proxmark3 Easy (or any PM3)    | USB CDC (`/dev/ttyACM0`)   |
| Ghost | Proxmark3 **RDV4 + BlueShark** | Bluetooth (`/dev/rfcomm0`) |

> A **Proxmark3 Easy has no Bluetooth hardware**. The Bluetooth end must be an
> RDV4 with the BlueShark module (or a PM3 with an FPC/BT add-on). Either device
> can be leech or ghost; the table above matches "1× USB + 1× Bluetooth". Both
> ends can also run over USB if you prefer a fully wired bench setup.

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

**Bluetooth end** — standard BlueShark build (no `CARDHOPPER_USB`):

```bash
make clean
make STANDALONE=HF_CARDHOPPER PLATFORM=PM3RDV4 PLATFORM_EXTRAS=BTADDON -j
./pm3-flash-fullimage
```

Pair the BlueShark and bind an rfcomm device, e.g.:

```bash
sudo rfcomm bind /dev/rfcomm0 <blueshark-mac> 1
```

Each device enters CardHopper automatically on boot (standalone mode) and waits
for the host to assign it a role.

## Install

```bash
pip install -e .          # from the repo root; pulls in pyserial
```

## Usage

```bash
pynfcreader-relay --card-port /dev/ttyACM0 --reader-port /dev/rfcomm0
```

Operational order:

1. Start the command. The **leech** enters reader mode and waits for a card.
2. Present the target card to the leech — it reports the UID and ATS.
3. The **ghost** is configured with that identity and starts emulating.
4. Present the ghost to the target reader; the session is relayed live. A decoded
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
