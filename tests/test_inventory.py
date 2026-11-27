import sys
from types import SimpleNamespace

import pytest

from p2_dice.cli import main


def configuration(*rows: bytes, count: int = 1, value: int = 5) -> bytes:
    payload = b"".join(rows)
    total = (9 + len(payload)).to_bytes(2, "little")
    return bytes([9, 2]) + total + bytes([count, value, 0, 0x80, 50]) + payload


def interface(number: int = 1, alternate: int = 0, endpoints: int = 0) -> bytes:
    return bytes([9, 4, number, alternate, endpoints, 0xFF, 7, 8, 0])


ENDPOINT_IN = bytes([7, 5, 0x81, 3, 0x40, 0x10, 9])
ENDPOINT_OUT = bytes([7, 5, 2, 2, 64, 0, 0])


def test_lists_devices_configurations_and_alternates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = configuration(
        interface(),
        interface(alternate=3, endpoints=2),
        bytes([4, 0x24, 0, 0]),
        ENDPOINT_IN,
        ENDPOINT_OUT,
        interface(number=2),
        count=2,
    )
    second = configuration(interface(), value=9)
    devices = [
        (0x17AA, 0xD1CE, 0x0200, 0x0110, 4, 8, [first, second]),
        (0x17AA, 0xD1CE, 0x0110, 0x0100, -1, -1, [second]),
    ]
    monkeypatch.setitem(sys.modules, "p2_dice._iokit", SimpleNamespace(devices=lambda: devices))
    assert main(["inventory"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Device 17aa:d1ce bus=4 address=8 bcdUSB=0x0200 bcdDevice=0x0110",
        "  Configuration 5",
        "    Interface 1 alternate=0 class=0xff subclass=0x07 protocol=0x08 endpoints=0",
        "    Interface 1 alternate=3 class=0xff subclass=0x07 protocol=0x08 endpoints=2",
        "      Endpoint 0x81 IN interrupt max-packet=64 bytes interval=9",
        "      Endpoint 0x02 OUT bulk max-packet=64 bytes interval=0",
        "    Interface 2 alternate=0 class=0xff subclass=0x07 protocol=0x08 endpoints=0",
        "  Configuration 9",
        "    Interface 1 alternate=0 class=0xff subclass=0x07 protocol=0x08 endpoints=0",
        "Device 17aa:d1ce bcdUSB=0x0110 bcdDevice=0x0100",
        "  Configuration 9",
        "    Interface 1 alternate=0 class=0xff subclass=0x07 protocol=0x08 endpoints=0",
    ]


def test_no_match(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(sys.modules, "p2_dice._iokit", SimpleNamespace(devices=list))
    assert main(["inventory"]) == 1
    assert "No DiCE USB device found (17aa:d1ce)" in capsys.readouterr().err


def test_missing_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "p2_dice._iokit", None)
    assert main(["inventory"]) == 2
    assert "native IOKit extension" in capsys.readouterr().err


def test_backend_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def disconnected() -> None:
        raise OSError("adapter disconnected")

    monkeypatch.setitem(sys.modules, "p2_dice._iokit", SimpleNamespace(devices=disconnected))
    assert main(["inventory"]) == 2
    assert "adapter disconnected" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        configuration(interface())[:-1],
        configuration(interface(), b"\x04"),
        configuration(interface(), b"\x00\x24"),
        configuration(interface(), b"\x07\x24"),
        configuration(b"\x04\x04\x00\x00"),
        configuration(interface(endpoints=1)),
        configuration(ENDPOINT_IN),
        configuration(interface(), interface()),
        configuration(interface(alternate=1)),
        configuration(interface(), count=2),
        configuration(interface(endpoints=2), ENDPOINT_IN, ENDPOINT_IN),
        configuration(interface(endpoints=1), bytes([3, 5, 0x81])),
    ],
)
def test_malformed_tree_discards_complete_devices_and_partial_rows(
    bad: bytes, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    devices = [
        (0x17AA, 0xD1CE, 0x0200, 0x0100, 1, 1, [configuration(interface())]),
        (0x17AA, 0xD1CE, 0x0200, 0x0100, 1, 2, [bad]),
    ]
    monkeypatch.setitem(sys.modules, "p2_dice._iokit", SimpleNamespace(devices=lambda: devices))
    assert main(["inventory"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "USB descriptor inventory failed" in output.err
