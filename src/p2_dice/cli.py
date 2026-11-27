import argparse
import sys
from collections.abc import Sequence

from p2_dice.descriptors import configuration_lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p2-dice")
    commands = parser.add_subparsers(required=True)
    commands.add_parser("inventory", help="list DiCE USB descriptors")
    parser.parse_args(argv)

    try:
        from p2_dice._iokit import devices
    except ImportError:
        print(
            "The native IOKit extension is required. Build and run p2-dice on macOS.",
            file=sys.stderr,
        )
        return 2
    lines: list[str] = []
    try:
        for vendor, product, usb, release, bus, address, configs in devices():
            location = "".join(
                f" {name}={value}"
                for name, value in (("bus", bus), ("address", address))
                if value >= 0
            )
            lines.append(
                f"Device {vendor:04x}:{product:04x}{location} bcdUSB=0x{usb:04x} bcdDevice=0x{release:04x}"
            )
            for config in configs:
                lines.extend(configuration_lines(config))
    except (OSError, ValueError) as error:
        print(f"USB descriptor inventory failed: {error}", file=sys.stderr)
        return 2
    if not lines:
        print("No DiCE USB device found (17aa:d1ce).", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0
