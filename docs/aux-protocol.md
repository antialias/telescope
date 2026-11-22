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
- Whether SkyPortal and our client can be connected at the same time.

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
