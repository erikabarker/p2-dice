from types import SimpleNamespace

import pytest
from usb import core
from usb.backend import libusb1

from p2_dice.cli import main


class Descriptor(SimpleNamespace):
    def __getattr__(self, name: str) -> int:
        # PyUSB copies every standard field from the backend, including reserved zeros.
        return 0


class FakeUSB:
    def __init__(self, ids: list[tuple[int, int]], fail_at: str = "") -> None:
        self.ids = ids
        self.fail_at = fail_at

    def enumerate_devices(self) -> range:
        return range(len(self.ids))

    def get_device_descriptor(self, dev: int) -> Descriptor:
        vendor, product = self.ids[dev]
        return Descriptor(
            idVendor=vendor,
            idProduct=product,
            bcdUSB=0x0200,
            bcdDevice=0x0110,
            bus=4 if dev == 0 else None,
            address=8 if dev == 0 else None,
            bNumConfigurations=2,
        )

    def get_configuration_descriptor(self, dev: int, config: int) -> Descriptor:
        return Descriptor(bConfigurationValue=(2, 5)[config], bNumInterfaces=2 - config)

    def get_interface_descriptor(self, dev: int, index: int, alt: int, config: int) -> Descriptor:
        if self.fail_at == "alternate" and alt == 1:
            raise core.USBError("adapter disconnected")
        if alt >= (2 if index == 0 and config == 0 else 1):
            raise IndexError(alt)
        return Descriptor(
            bInterfaceNumber=index + 2,
            bAlternateSetting=alt * 3,
            bInterfaceClass=0xFF,
            bNumEndpoints=2 if alt == 1 else 0,
        )

    def get_endpoint_descriptor(
        self, dev: int, endpoint: int, index: int, alt: int, config: int
    ) -> Descriptor:
        if self.fail_at == "endpoint" and endpoint == 1:
            raise core.USBError("adapter disconnected")
        return Descriptor(
            bEndpointAddress=(0x81, 0x02)[endpoint],
            bmAttributes=(0x03, 0x02)[endpoint],
            wMaxPacketSize=(0x1040, 64)[endpoint],
        )


def test_lists_only_matching_devices_and_their_descriptor_trees(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    usb = FakeUSB([(0x17AA, 0xD1CE), (0x9999, 0xD1CE), (0x17AA, 0x1234), (0x17AA, 0xD1CE)])
    monkeypatch.setattr(libusb1, "get_backend", lambda: usb)

    assert main(["inventory"]) == 0
    tree = (
        "  Configuration 2\n"
        "    Interface 2 alternate=0 class=0xff endpoints=0\n"
        "    Interface 2 alternate=3 class=0xff endpoints=2\n"
        "      Endpoint 0x81 IN interrupt max-packet=64 bytes\n"
        "      Endpoint 0x02 OUT bulk max-packet=64 bytes\n"
        "    Interface 3 alternate=0 class=0xff endpoints=0\n"
        "  Configuration 5\n"
        "    Interface 2 alternate=0 class=0xff endpoints=0\n"
    )
    assert capsys.readouterr().out == (
        f"Device 17aa:d1ce bus=4 address=8 bcdUSB=0x0200 bcdDevice=0x0110\n{tree}"
        f"Device 17aa:d1ce bcdUSB=0x0200 bcdDevice=0x0110\n{tree}"
    )


def test_no_match(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(libusb1, "get_backend", lambda: FakeUSB([(0xFFFF, 0x0001)]))
    assert main(["inventory"]) == 1
    assert "No DiCE USB device found (17aa:d1ce)" in capsys.readouterr().err


def test_missing_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(libusb1, "get_backend", lambda: None)
    assert main(["inventory"]) == 2
    assert "brew install libusb" in capsys.readouterr().err


@pytest.mark.parametrize("fail_at", ["alternate", "endpoint"])
def test_descriptor_failure_discards_partial_output(
    fail_at: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(libusb1, "get_backend", lambda: FakeUSB([(0x17AA, 0xD1CE)], fail_at))
    assert main(["inventory"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "adapter disconnected" in output.err
