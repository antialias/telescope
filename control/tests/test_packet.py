from celestron_aux import Command, Device, Packet, Parser

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
