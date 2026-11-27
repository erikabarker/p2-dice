import argparse
import sys
from collections.abc import Iterator, Sequence
from itertools import count
from typing import cast

from usb import core, util
from usb.backend import libusb1

from p2_dice.descriptors import Configuration, Device, Interface

VENDOR_ID = 0x17AA
PRODUCT_ID = 0xD1CE
TRANSFER_TYPES = ("control", "isochronous", "bulk", "interrupt")


def interfaces(configuration: Configuration) -> Iterator[Interface]:
    # PyUSB's configuration iterator also treats a USBError as the end of the alternates.
    for index in range(configuration.bNumInterfaces):
        yield configuration[index, 0]
        for alternate in count(1):
            try:
                interface = configuration[index, alternate]
            except IndexError:
                break
            yield interface


def describe(device: Device) -> Iterator[str]:
    location = "".join(
        f" {name}={value}"
        for name, value in (("bus", device.bus), ("address", device.address))
        if value is not None
    )
    yield (
        f"Device {device.idVendor:04x}:{device.idProduct:04x}{location} "
        f"bcdUSB=0x{device.bcdUSB:04x} bcdDevice=0x{device.bcdDevice:04x}"
    )
    for configuration in device:
        yield f"  Configuration {configuration.bConfigurationValue}"
        for interface in interfaces(configuration):
            yield (
                f"    Interface {interface.bInterfaceNumber} alternate={interface.bAlternateSetting} "
                f"class=0x{interface.bInterfaceClass:02x} endpoints={interface.bNumEndpoints}"
            )
            for endpoint in interface:
                address = endpoint.bEndpointAddress
                direction = "IN" if util.endpoint_direction(address) == util.ENDPOINT_IN else "OUT"
                transfer = TRANSFER_TYPES[util.endpoint_type(endpoint.bmAttributes)]
                yield (
                    f"      Endpoint 0x{address:02x} {direction} {transfer} "
                    f"max-packet={endpoint.wMaxPacketSize & 0x7FF} bytes"
                )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p2-dice")
    commands = parser.add_subparsers(required=True)
    commands.add_parser("inventory", help="list DiCE USB descriptors")
    parser.parse_args(argv)

    backend = libusb1.get_backend()
    if backend is None:
        print(
            "Cannot load libusb 1.0. On macOS, install it with 'brew install libusb'.",
            file=sys.stderr,
        )
        return 2
    try:
        devices = core.find(
            find_all=True, backend=backend, idVendor=VENDOR_ID, idProduct=PRODUCT_ID
        )
        # With find_all=True PyUSB always returns an iterator, even for zero matches.
        lines = [line for device in cast(Iterator[Device], devices) for line in describe(device)]
    except (core.USBError, IndexError) as error:
        print(f"USB descriptor inventory failed: {error}", file=sys.stderr)
        return 2

    if not lines:
        print("No DiCE USB device found (17aa:d1ce).", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0
