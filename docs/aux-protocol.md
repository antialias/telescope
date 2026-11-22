# The mount's control protocol

What we know about driving the NexStar Evolution from our own software, and
how we know it. Celestron publishes no document for this protocol; everything
here comes from open-source code and community reverse engineering, and is
marked by how far it has been checked.

Checked means one of:
- **source**: read in the code or document named.
- **simulator**: our client does it against `caux-simulator`.
- **mount**: seen on our own mount. Nothing is at this level yet.

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
from captures and reverse engineering. None of it is Celestron's, and none of
it has been tried by us.

- **Original camera (`0xB4`)**: it can be told to capture (`0x94`), polled for
  status (`0x91`) and asked for its data (`0x92`). The data is a list of star
  positions in pixels, not a sky position, so the solving happens in the
  StarSense hand control. To use it ourselves we would have to solve the star
  list.
- **V2 (`0xBD`)**: it has commands to start a plate solve (`0x01`) and to read
  the result as RA and Dec (`0x02`), and takes location (`0x31`) and time
  (`0x32`). The payload of the start command is not decoded.
- Which camera we have is still to be confirmed (see `AGENTS.md`).

## Not yet known

- What our own mount answers: which devices are present, firmware versions,
  positions at power-on.
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
