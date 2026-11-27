import pytest

from p2_dice.rfc import RFC_VERSION_REQUEST, RfcVersionReply

REPLY = bytes.fromhex("b5 06 00 24 00 00 02 03 04 72")


def test_request_is_the_fixed_no_argument_getter() -> None:
    assert RFC_VERSION_REQUEST == b"\xb5\x02\x00\x20\x00\x69"


@pytest.mark.parametrize("split", range(1, len(REPLY)))
def test_accepts_every_split_of_a_single_reply(split: int) -> None:
    reply = RfcVersionReply()
    assert reply.feed(REPLY[:split]) is None
    assert reply.feed(REPLY[split:]) == (2, 3, 4)
    assert reply.finish() == (2, 3, 4)


def test_body_checksum_wraps_and_all_version_fields_are_unsigned() -> None:
    reply = RfcVersionReply()
    assert reply.feed(bytes.fromhex("b5 06 00 24 00 00 ff 80 ff e7")) == (255, 128, 255)


@pytest.mark.parametrize(
    ("frame", "error"),
    [
        ("b4", "marker"),
        ("b5 ff ff 1c", "length"),
        ("b5 06 00 25", "header checksum"),
        ("b5 06 00 24 00 00 02 03 04 73", "body checksum"),
        ("b5 06 00 24 01 00 02 03 04 73", "command 0x01"),
        ("b5 06 00 24 00 02 02 03 04 74", "status 0x02"),
    ],
)
def test_rejects_mismatched_and_unsuccessful_replies(frame: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        RfcVersionReply().feed(bytes.fromhex(frame))


@pytest.mark.parametrize("split", range(len(REPLY)))
def test_eof_rejects_every_truncated_prefix(split: int) -> None:
    reply = RfcVersionReply()
    assert reply.feed(REPLY[:split]) is None
    with pytest.raises(ValueError, match="truncated"):
        reply.finish()


@pytest.mark.parametrize("split", [0, 4, 9, 10])
def test_rejects_concatenated_replies_across_chunk_boundaries(split: int) -> None:
    reply = RfcVersionReply()
    combined = REPLY * 2
    reply.feed(combined[:split])
    with pytest.raises(ValueError, match="trailing bytes"):
        reply.feed(combined[split:])


def test_rejects_oversized_chunk_before_buffering_it() -> None:
    with pytest.raises(ValueError, match="trailing bytes"):
        RfcVersionReply().feed(REPLY + bytes(65536))


def test_extra_data_invalidates_an_otherwise_complete_reply() -> None:
    reply = RfcVersionReply()
    assert reply.feed(REPLY) == (2, 3, 4)
    with pytest.raises(ValueError, match="trailing bytes"):
        reply.feed(b"\xb5")
    with pytest.raises(ValueError, match="already rejected"):
        reply.finish()
