# The mount's control protocol

What we know about driving the NexStar Evolution from our own software, and
how we know it. Celestron publishes no document for this protocol; everything
here comes from open-source code and community reverse engineering, and is
marked by how far it has been checked.

Checked means one of:
- **source**: read in the code or document named.
- **simulator**: our client does it against `caux-simulator`.
- **mount**: seen on our own mount. See "Seen on our mount" below.

## Transport

- The mount's WiFi board is a transparent bridge to its internal AUX bus, on
  TCP port 2000. On the mount's own hotspot its address is `1.2.3.4`
  (source: indi-celestronaux `auxproto.h`).
- Every packet a client sends comes back as an echo, followed by the reply
  from the addressed device (source: the simulator's `handle_cmd`; simulator).
- A device that is not on the bus sends nothing. A client learns that only by
  timing out (simulator).
- Other traffic on the bus reaches the client too, such as a plugged-in hand
  control talking to the motors. A client keeps only packets addressed to
  `0x20` (source: indi-celestronaux `processResponse`).
- **Finding the mount on a home network**: the WiFi board broadcasts a UDP
  datagram to port 55555 every few seconds, and apps take the sender's
  address. The payload differs by board generation: 110 bytes of binary on the
  older WiFly board, the text `{"AMW007"}` on the newer one. Source for the
  older board: the WiFly vendor manual and jochym's `nexstar-evo` client; for
  the newer one only reverse-engineered emulators. Our `discover()` uses the
  sender's address and ignores the payload.
- **One client at a time.** Celestron's own WiFi tips warn that two devices
  contending for one telescope cause connection problems. How many TCP
  clients the board accepts is not documented anywhere we found.
- **Idle connections may be dropped.** The `celestron-aux` toolkit sends a
  version request after 10 seconds of silence to keep the link up. Our client
  does not do this yet; a long-running service will need it.
- **The hand control's ASCII protocol is not on WiFi.** Celestron's "NexStar
  Communication Protocol" document says those commands go to the port on the
  base of the hand control. Over WiFi there is only the AUX bus.

## Wired to an AUX port

For a microcontroller plugged into one of the mount's AUX jacks. Source: the
schematic and firmware of a community ESP32 board that does this (g7ltt's
board, Mark Lord's firmware). Neither is Celestron's, and we have wired
nothing yet.

- The jack has six contacts (6P6C). On that board pin 3 carries 12 V from the
  mount, pin 5 is ground, pin 2 is data from the bus, pin 4 is data to the
  bus, pin 6 is the busy line and pin 1 is unused.
- Serial at 19200 baud, 8 data bits, 2 stop bits.
- Data-to-bus and busy are pulled up to 5 V, and a device only ever pulls them
  low. An ESP32's pins are 3.3 V, so an interface chip sits between; that
  board uses a 74HC125, and a 12 V to 5 V converter for power.
- Taking a turn on the bus: see that busy is high, pull it low, wait at least
  100 microseconds, send the packet, release busy.
- A device hears its own packet come back and has to discard it.
- The bus carries several devices at once (hand control, WiFi board, camera),
  so a wired device joins them rather than replacing one.
- That firmware also answers as the GPS accessory (`0xB0`) when it has a GPS
  receiver: `GPS_LINKED` (`0x37`), `GPS_TIME_VALID` (`0x36`) and
  `GPS_GET_TIME` (`0x33`: hour, minute, second), with the date and position
  requests beside them. That is how a hand control gets time and place
  without typing. Our StarSense hand control showed a date in January 2000
  when alignment began (2026-11-21) and had to be set by hand; a board of
  ours could answer the same requests from network time. Not tried.
- Confirm the pin numbering with a meter before plugging anything in: a
  mirrored cable would put 12 V on a data line.

## Packet

```
0x3B  length  source  destination  command  data...  checksum
```

- `length` counts source, destination, command and data.
- `checksum` is the two's complement of the sum of the bytes from `length` to
  the last data byte.
- A reply repeats the command id with source and destination swapped.
- Multi-byte values are big-endian.

Source: indi-celestronaux `auxproto.cpp` (`fillBuf`, `checksum`). Example:
asking the azimuth motor for its version is `3B 03 20 10 FE CF`.

## Addresses

| Address | Device |
|---|---|
| `0x01` | Main board |
| `0x04` | Hand control (older) |
| `0x0D` | NexStar+ hand control |
| `0x0E` | StarSense hand control |
| `0x10` | Azimuth motor controller |
| `0x11` | Altitude motor controller |
| `0x12` | Focuser |
| `0x20` | An app, which is the address we use |
| `0xB0` | GPS |
| `0xB4` | StarSense camera, original |
| `0xB5` | WiFi board |
| `0xB6` | Battery controller |
| `0xB7` | Charge port |
| `0xBD` | StarSense AutoAlign V2 |
| `0xBF` | Lights |

Source: indi-celestronaux `auxproto.h`, except the StarSense addresses, which
are from the `celestron-aux` toolkit's `docs/protocol.md`.

## Commands the client uses

All are sent to a motor controller unless noted.

| Id | Name | Data sent | Reply |
|---|---|---|---|
| `0xFE` | GET_VER (any device) | none | 2 or 4 bytes: major, minor, build |
| `0x05` | MC_GET_MODEL | none | 2 bytes; `0x1687` is the NexStar Evolution |
| `0x01` | MC_GET_POSITION | none | 3 bytes, encoder position |
| `0x02` | MC_GOTO_FAST | 3 bytes, target position | empty |
| `0x17` | MC_GOTO_SLOW | 3 bytes, target position | empty |
| `0x13` | MC_SLEW_DONE | none | 1 byte: `0xFF` done, `0x00` still moving |
| `0x24` | MC_MOVE_POS | 1 byte, rate 0 to 9; 0 stops | empty |
| `0x25` | MC_MOVE_NEG | 1 byte, rate 0 to 9 | empty |
| `0x10` | GET_VOLTAGE (battery controller) | none | 6 bytes: state, level, microvolts (4 bytes) |

Battery state is 0 discharging, 1 charging, 2 full; level is 0 low, 1 medium,
2 high. Source: indi-celestronaux `auxproto.h` and `celestronaux.cpp`
(`processResponse`); simulator for all of them.

Known but not used yet (source: indi-celestronaux):

| Id | Name | Notes |
|---|---|---|
| `0x04` | MC_SET_POSITION | 3 bytes; tells an axis what its current position is |
| `0x06`, `0x07` | MC_SET_POS_GUIDERATE, MC_SET_NEG_GUIDERATE | 3 bytes, tracking rate in units of 1/1024 arcsecond per second |
| `0x38` to `0x3C` | Cord wrap | enable, disable, set, poll, get |
| `0x46`, `0x47` | Autoguide rate | set, get |

## Units

- A position is a 24-bit fraction of a full turn: 16,777,216 steps per
  revolution, about 0.077 arcsecond per step.
- A position is relative to wherever the axis was last told zero is. It is not
  an altitude or an azimuth until an alignment says how the two relate.

## What the mount does not do

These decide the shape of our software.

- **Alignment lives in the client.** The motor controllers know encoder angles
  only. Turning "Saturn" into two encoder angles is the client's job, which is
  why SkyPortal and the hand controls each hold their own alignment model.
- **Tracking lives in the client.** On an alt-az mount both axes must move at
  changing rates to follow the sky. indi-celestronaux recomputes the two rates
  on a timer and sends them (source: `TimerHit`, `trackByRate`).
- **Startup state is unknown.** With no hand control on the bus,
  indi-celestronaux sets both positions to zero and enables cord wrap
  (`startupWithoutHC`). What our mount reports at power-on is to be read, not
  assumed.

## The StarSense camera

From the `celestron-aux` toolkit (GPL-3), whose author says the names come
from captures and reverse engineering. None of it is Celestron's. We have read
the toolkit's source and its recordings of real hardware; we have not yet
talked to our own camera (the mount was switched off when this was written).

- **Original camera (`0xB4`)**, the one we have (see `AGENTS.md`): it returns
  a list of star positions in pixels, not a sky position, so the solving
  happens in whoever asked. To use it ourselves we solve the star list.
- **V2 (`0xBD`)**: it has commands to start a plate solve (`0x01`) and to read
  the result as RA and Dec (`0x02`), and takes location (`0x31`) and time
  (`0x32`). The payload of the start command is not decoded.

### Commands of the original camera

| Command | Name in the toolkit | What the toolkit's code shows |
|---|---|---|
| `0x3E` | set align centre | Not used by us: it would overwrite the stored centre calibration. |
| `0x3F` | get align centre | Asked with one data byte `00`. Reply: 8 bytes, x then y as little-endian 32-bit integers. |
| `0x90` | reset capture | Sent with data `03 E8 00`. `0x03E8` is 1000, perhaps the exposure in milliseconds (our guess). |
| `0x91` | get status | Reply: a status byte (1 "Error", 3 "Ready", 9 "Finished" in the toolkit's decoder) and a star count. |
| `0x92` | get capture data | Sent without data. The star list follows. Reply decoded like status. |
| `0x94` | start capture | Sent with data `00`. Reply decoded like status. |
| `0x9F` | image request | Reply decoded like status. Not used by us. |
| `0xFE` | version | Four bytes, like the other devices. |

The toolkit's capture sequence (`starsense.py`, `run_capture_sequence`) is
reset, wait 4 s, start, wait 4 s, get capture data. It sends each command
without waiting for a reply.

### The star list frame

The star list does not come in an AUX packet and carries no addresses:

    0x3C  length (4 bytes, big-endian)  payload...  checksum

Every `0x3B` in the length and payload is sent as `3B 02 02`. The checksum is
over the length and payload before that escaping. The payload is 8 bytes per
star: x and y in pixels as two little-endian 32-bit floats, on a sensor the
toolkit gives as 1280 by 960. A record of eight zero bytes is not a star.

Our parser reads this frame (`packet.py`, `StarFrame`). Checked 2026-11-21
against the toolkit's recording of a real star list
(`tests/fixtures/starsense_frame.hex`): 808 bytes on the wire with one escaped
byte gave 800 payload bytes and 99 stars, all inside 1280 by 960, and encoding
them again gave the same 808 bytes. The recording is the toolkit's and is not
copied into this repository.

### Evidence that the camera can be reached over WiFi

- The toolkit ships a recording of a real WiFi session
  (`tests/fixtures/cpwi_wifi_nexstar_slt.pcap`: Celestron's CPWI program, a
  NexStar SLT with a WiFi module, a StarSense camera and its hand control).
  Read with our own parser, 2026-11-21:
  - CPWI, as `0x20` over WiFi, asked the camera for its version and its
    centre, and the camera answered: version `01 02 34 1F` (1.02.13343),
    centre eight zero bytes.
  - The hand control's own exchange with the camera (`0x0E` to `0xB4`:
    version, `0x05` answered `01`, status answered `01 00`, centre) appears
    in what the WiFi module sent to CPWI. So the module passes on bus traffic
    that is not addressed to the WiFi client.
  - The toolkit's notes say the same recording holds two packets from the
    hand control with a wrong checksum. A bridge that passes those is not
    checking packets, which suggests it would pass a star list too. That is
    an inference: the recording holds no star list.
- That is a WiFi module on another mount, not the Evolution's built-in board.
- Celestron's quick setup guide for our model has the SkyPortal app align
  with StarSense over the mount's WiFi ("Connect and Align").
- A search on 2026-11-21 found no account of a hobbyist reading and solving
  the star list end to end.

### First contact with ours, in order

1. `python -m celestron_aux <host> --camera`: version, status and stored
   centre. Reads only.
2. `python -m celestron_aux <host> --listen 120` while the owner runs an
   alignment on the hand control. We send nothing. If the bridge passes it,
   this shows the hand control's real capture sequence and a real star list.
3. `python -m celestron_aux <host> --capture`, with the owner's agreement:
   the toolkit's sequence from our own address. It makes the camera take an
   exposure and moves nothing.

## Seen on our mount (2026-11-21)

First contact, over the house WiFi in Access Point mode, with the read-only
probe. The StarSense hand control and camera were plugged in.

- It announces itself about once a second on UDP port 55555 with 66 bytes of
  JSON that begin `{"version":"CELEST-AMW0`. That is the newer WiFi board, and
  not the payload the emulators send.
- The probe's requests and replies work as they do against the simulator.
- Motor controllers (`0x10`, `0x11`): version 7.17.98. Model `0x1687`.
- WiFi board `0xB5`: version 0.00.256. Battery, charge port and lights
  (`0xB6`, `0xB7`, `0xBF`): version 1.01.16418.
- Battery read 9.64 V, "medium", discharging. The pack is nominally 9.6 V, so
  the simulator's 12 V is not what the real one shows.
- No reply from `0x01`, `0x04`, `0x0D`, `0x12` or `0xB0`.
- Port 2000 does not always accept: of four connections a few seconds apart,
  one timed out, two connected and one was refused. The SkyPortal app was
  open on a phone at the time. Not yet explained; a client must expect it.

- **First motion**, with the owner at the telescope: a slow goto
  (`MC_GOTO_SLOW`) of azimuth by +5 degrees and back. It ran at about
  0.5 degrees a second, `MC_SLEW_DONE` turned true on arrival, and the axis
  returned to its starting reading within 0.001 degree. Altitude did not
  change. Positive azimuth turned the tube to the right as seen from behind
  it, which is clockwise seen from above (the owner watched).

## Not yet known

- What our own mount answers: which devices are present, firmware versions,
  positions at power-on.
- Whether the Evolution's WiFi board passes the camera's star list frame, and
  whether the camera answers a capture requested from the app's address.
- Whether the echo and reply behaviour on the real WiFi board matches the
  simulator.
- Whether SkyPortal and our client can be connected at the same time, and
  what happens to SkyPortal's alignment if our client moves the mount.
- Which WiFi board our 2025 mount has, what it broadcasts, and how long it
  keeps an idle connection.
- Whether macOS lets a terminal program receive the discovery broadcast
  without a Local Network permission prompt.
- What the motors do when whoever set a tracking rate goes silent. In the
  simulator a rate runs until it is changed, with nothing to stop it.

## Sources

- [indi-celestronaux](https://github.com/indilib/indi-3rdparty/tree/master/indi-celestronaux):
  INDI's driver for this protocol, tested by its authors on the NexStar
  Evolution over WiFi. Files read: `auxproto.h`, `auxproto.cpp`,
  `celestronaux.h`, `celestronaux.cpp`, `README.md`, `simulator/`.
- [caux-simulator](https://github.com/jochym/caux-simulator): the emulator our
  tests run against, by the driver's author.
- [celestron-aux](https://github.com/platini2/celestron-aux): a
  reverse-engineered catalogue of AUX devices and commands, including
  StarSense.
- [nexstar-evo](https://github.com/jochym/nexstar-evo/blob/master/nsevo/nexstarevo.py):
  an earlier Python client by the driver's author; shows discovery on UDP
  55555.
- [Celestron GPS, WiFi and Bluetooth interface](https://github.com/g7ltt/Celestron-GPS-WiFi-BT-Interface):
  a community ESP32 board for the AUX port, with Mark Lord's firmware. Files
  read: `esp32_wifi-V3.8.ino` and the version 2.0 schematic.
- [NexStar Communication Protocol](https://s3.amazonaws.com/celestron-site-support-files/support_files/1154108406_nexstarcommprot.pdf):
  Celestron's document for the hand control's ASCII protocol.
- [WiFi tips for NexStar Evolution](https://www.celestron.com/blogs/knowledgebase/wifi-tips-for-nexstar-evolution):
  Celestron's knowledge base.
