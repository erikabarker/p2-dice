import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from p2_dice.capture import decode_engine_capture
from p2_dice.descriptors import configuration_lines
from p2_dice.rfc import RfcVersionReply


def import_engine_capture(path: Path) -> int:
    try:
        raw = path.read_bytes()
        capture = decode_engine_capture(json.loads(raw))
    except OSError as error:
        print(f"Cannot read engine capture: {error}", file=sys.stderr)
        return 2
    except (ValueError, RecursionError) as error:
        print(f"Invalid engine capture: {error}", file=sys.stderr)
        return 3
    result: dict[str, object] = {
        "source_file": str(path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }
    result |= asdict(capture)
    print(json.dumps(result, indent=2))
    return 0


def rfc_version() -> int:
    from p2_dice._iokit import rfc_version_reply

    reply = RfcVersionReply()
    try:
        reply.feed(rfc_version_reply())
        major, minor, patch = reply.finish()
    except OSError as error:
        print(f"RFC version USB transfer failed: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"Invalid RFC version reply: {error}", file=sys.stderr)
        return 3
    print(f"RFC version {major}.{minor}.{patch}")
    return 0


def inventory() -> int:
    from p2_dice._iokit import devices

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p2-dice")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory", help="list DiCE USB descriptors")
    commands.add_parser("rfc-version", help="read the adapter RFC version")
    capture = commands.add_parser(
        "import-engine-capture", help="decode DTCs from a saved Windows engine-reader log"
    )
    capture.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    if args.command == "import-engine-capture":
        return import_engine_capture(args.path)
    try:
        return rfc_version() if args.command == "rfc-version" else inventory()
    except ImportError:
        print(
            "The native IOKit extension is required. Build and run p2-dice on macOS.",
            file=sys.stderr,
        )
        return 2
