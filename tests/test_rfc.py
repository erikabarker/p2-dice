import sys
from types import SimpleNamespace

import pytest

from p2_dice.cli import main
from p2_dice.rfc import RfcVersionReply

REPLY = bytes.fromhex("b5 06 00 24 00 00 02 03 04 72")


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


def test_cli_reads_one_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []

    def read() -> bytes:
        calls.append(1)
        return REPLY

    monkeypatch.setitem(sys.modules, "p2_dice._iokit", SimpleNamespace(rfc_version_reply=read))
    assert main(["rfc-version"]) == 0
    assert calls == [1]
    assert capsys.readouterr().out == "RFC version 2.3.4\n"


@pytest.mark.parametrize(
    ("failure", "status", "message"),
    [
        (OSError("interface busy"), 2, "USB transfer failed"),
        (ValueError("trailing bytes"), 3, "Invalid RFC version reply"),
        (REPLY[:-1], 3, "truncated"),
        (bytes.fromhex("b5 06 00 24 00 03 02 03 04 75"), 3, "status 0x03"),
    ],
)
def test_cli_distinguishes_transfer_and_protocol_failures(
    failure: Exception | bytes,
    status: int,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def read() -> bytes:
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setitem(sys.modules, "p2_dice._iokit", SimpleNamespace(rfc_version_reply=read))
    assert main(["rfc-version"]) == status
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
