import struct

from celestron_aux import Command, Device, Packet, Parser, Star, StarFrame

# Hand-computed frames: the checksum is the two's complement of the sum of the
# bytes between the preamble and the checksum.
GET_VER_AZM = bytes.fromhex("3b032010fecf")
GET_POSITION_ALT = bytes.fromhex("3b03201101cb")
GOTO_FAST_AZM_90_DEG = bytes.fromhex("3b0620100240000088")


def test_encode_matches_known_frames() -> None:
    assert Packet(Device.APP, Device.AZM, Command.GET_VER).encode() == GET_VER_AZM
    assert Packet(Device.APP, Device.ALT, Command.MC_GET_POSITION).encode() == GET_POSITION_ALT
    assert Packet(Device.APP, Device.AZM, Command.MC_GOTO_FAST, bytes.fromhex("400000")).encode() == GOTO_FAST_AZM_90_DEG


def test_parser_round_trips_a_frame() -> None:
    assert Parser().feed(GOTO_FAST_AZM_90_DEG) == [Packet(0x20, 0x10, 0x02, bytes.fromhex("400000"))]


def test_parser_joins_a_frame_split_across_reads() -> None:
    parser = Parser()
    assert parser.feed(GET_VER_AZM[:2]) == []
    assert parser.feed(GET_VER_AZM[2:5]) == []
    assert parser.feed(GET_VER_AZM[5:]) == [Packet(0x20, 0x10, 0xFE)]


def test_parser_returns_echo_then_reply_from_one_read() -> None:
    reply = Packet(Device.AZM, Device.APP, Command.GET_VER, bytes([7, 11, 0x14, 0x22]))
    assert Parser().feed(GET_VER_AZM + reply.encode()) == [Packet(0x20, 0x10, 0xFE), reply]


def test_parser_skips_noise_and_a_frame_with_a_bad_checksum() -> None:
    parser = Parser()
    corrupt = GET_VER_AZM[:-1] + b"\x00"
    assert parser.feed(b"\x00\xff" + corrupt + GET_POSITION_ALT) == [Packet(0x20, 0x11, 0x01)]
    assert parser.dropped == 2 + len(corrupt)


def test_parser_resynchronises_on_a_preamble_byte_inside_noise() -> None:
    assert Parser().feed(b"\x3b\x02" + GET_VER_AZM) == [Packet(0x20, 0x10, 0xFE)]


# Star lists. ESCAPED_X is a coordinate whose four bytes hold a 0x3B, the byte
# that begins a packet and so has to be escaped inside a star list.
ESCAPED_X = struct.unpack("<f", bytes.fromhex("003b8044"))[0]
STARS = [Star(269.0, 800.25), Star(ESCAPED_X, 12.5)]


def test_star_frame_matches_a_hand_built_frame() -> None:
    payload = bytes.fromhex("00808643" "00104844")  # 269.0 and 800.25 as little-endian floats
    body = bytes.fromhex("00000008") + payload
    frame = StarFrame.of([Star(269.0, 800.25)])
    assert frame.encode() == b"\x3c" + body + bytes([-sum(body) & 0xFF])
    assert Parser().feed(frame.encode()) == [frame]


def test_star_frame_escapes_the_packet_preamble_and_reads_it_back() -> None:
    encoded = StarFrame.of(STARS).encode()
    assert bytes.fromhex("003b020280") in encoded
    parsed = Parser().feed(encoded)
    assert parsed == [StarFrame.of(STARS)]
    assert isinstance(parsed[0], StarFrame) and parsed[0].stars() == STARS


def test_star_frame_escapes_a_preamble_in_its_length() -> None:
    stars = StarFrame.of(STARS).payload
    frame = StarFrame(stars + bytes(0x3B00 - len(stars)))
    assert frame.encode().startswith(bytes.fromhex("3c00003b020200"))
    assert Parser().feed(frame.encode()) == [frame]
    assert frame.stars() == STARS  # the padding is empty records, which are not stars


def test_star_frame_split_at_every_byte_between_packets() -> None:
    star_frame = StarFrame.of(STARS)
    stream = GET_VER_AZM + star_frame.encode() + GET_POSITION_ALT
    for cut in range(1, len(stream)):
        parser = Parser()
        assert parser.feed(stream[:cut]) + parser.feed(stream[cut:]) == [
            Packet(0x20, 0x10, 0xFE),
            star_frame,
            Packet(0x20, 0x11, 0x01),
        ]
        assert parser.dropped == 0


def test_a_packet_cutting_into_a_star_frame_is_still_read() -> None:
    broken = StarFrame.of(STARS).encode()[:9]
    parser = Parser()
    assert parser.feed(broken + GET_VER_AZM) == [Packet(0x20, 0x10, 0xFE)]
    assert parser.dropped == len(broken)


def test_a_star_frame_with_a_bad_checksum_or_an_absurd_length_is_dropped() -> None:
    good = StarFrame.of(STARS).encode()
    corrupt = good[:-1] + bytes([good[-1] ^ 0xFF])
    assert Parser().feed(corrupt + GET_VER_AZM) == [Packet(0x20, 0x10, 0xFE)]
    assert Parser().feed(bytes.fromhex("3c00010000") + GET_VER_AZM) == [Packet(0x20, 0x10, 0xFE)]
