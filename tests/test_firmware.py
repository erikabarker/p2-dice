"""Synthetic command 0x04 frames. A native firmware reply has yet to be captured."""

import pytest

from p2_dice.rfc import FirmwareVersion, FirmwareVersionReply

BUILD = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"
HEADER = bytes.fromhex("b5 24 00 42")
REPLY = HEADER + bytes.fromhex("04 00 fa 81") + BUILD + bytes.fromhex("e7 78")
VERSION = FirmwareVersion(major=250, minor=129, patch=231, build=BUILD)


@pytest.mark.parametrize("split", range(1, len(REPLY)))
def test_decodes_full_width_build_at_every_split(split: int) -> None:
    reply = FirmwareVersionReply()
    assert reply.feed(REPLY[:split]) is None
    assert reply.feed(REPLY[split:]) == VERSION
    assert reply.finish() == VERSION


def test_preserves_nul_padding_and_non_text_build_bytes() -> None:
    build = b"A\x00\xff" + bytes(27)
    reply = HEADER + bytes.fromhex("04 00 00 00") + build + bytes.fromhex("21 ce")
    assert FirmwareVersionReply().feed(reply) == FirmwareVersion(0, 0, 33, build)


@pytest.mark.parametrize(
    ("frame", "error"),
    [
        (b"\xb4", "marker"),
        (bytes.fromhex("b5 23 00 41"), "length"),
        (bytes.fromhex("b5 24 01 43"), "length"),
        (bytes.fromhex("b5 24 00 43"), "header checksum"),
        (REPLY[:-1] + b"\x79", "body checksum"),
        (HEADER + b"\x05" + REPLY[5:-1] + b"\x79", "command 0x05"),
        (HEADER + b"\x04\xff" + REPLY[6:-1] + b"\x77", "status 0xff"),
    ],
)
def test_rejects_invalid_frames(frame: bytes, error: str) -> None:
    reply = FirmwareVersionReply()
    with pytest.raises(ValueError, match=error):
        reply.feed(frame)
    with pytest.raises(ValueError, match="already rejected"):
        reply.finish()


@pytest.mark.parametrize("cut", range(len(REPLY)))
def test_eof_rejects_every_truncated_prefix(cut: int) -> None:
    reply = FirmwareVersionReply()
    assert reply.feed(REPLY[:cut]) is None
    with pytest.raises(ValueError, match="truncated"):
        reply.finish()
    with pytest.raises(ValueError, match="already rejected"):
        reply.feed(REPLY[cut:])


@pytest.mark.parametrize("split", [0, len(REPLY) - 1, len(REPLY)])
def test_rejects_trailing_data_across_reads(split: int) -> None:
    reply = FirmwareVersionReply()
    reply.feed(REPLY[:split])
    with pytest.raises(ValueError, match="trailing bytes"):
        reply.feed(REPLY[split:] + b"\xb5")
    with pytest.raises(ValueError, match="already rejected"):
        reply.finish()
