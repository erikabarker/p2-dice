from collections.abc import Iterator

TRANSFER_TYPES = ("control", "isochronous", "bulk", "interrupt")


def configuration_lines(data: bytes) -> Iterator[str]:
    if len(data) < 9 or data[1] != 2 or not 9 <= data[0] <= len(data):
        raise ValueError("invalid configuration descriptor header")
    if int.from_bytes(data[2:4], "little") != len(data):
        raise ValueError("configuration length differs from wTotalLength")
    yield f"  Configuration {data[5]}"
    settings: set[tuple[int, int]] = set()
    addresses: set[int] = set()
    remaining = 0
    offset = data[0]
    while offset < len(data):
        if offset + 2 > len(data):
            raise ValueError("truncated descriptor header")
        size, kind = data[offset : offset + 2]
        if size < 2 or offset + size > len(data):
            raise ValueError(f"invalid descriptor length {size} at offset {offset}")
        row = data[offset : offset + size]
        offset += size
        if kind == 2:
            raise ValueError("unexpected nested configuration descriptor")
        if kind == 4:
            if size < 9 or remaining:
                raise ValueError("incomplete interface descriptor or endpoint list")
            number, alternate, remaining, cls, subclass, protocol = row[2:8]
            if (number, alternate) in settings:
                raise ValueError("duplicate interface alternate setting")
            settings.add((number, alternate))
            addresses.clear()
            yield (
                f"    Interface {number} alternate={alternate} class=0x{cls:02x} "
                f"subclass=0x{subclass:02x} protocol=0x{protocol:02x} endpoints={remaining}"
            )
        elif kind == 5:
            if size < 7 or remaining == 0:
                raise ValueError("unexpected or incomplete endpoint descriptor")
            address, attributes = row[2:4]
            if address in addresses or address & 0x70 or not address & 0x0F:
                raise ValueError(f"invalid or duplicate endpoint address 0x{address:02x}")
            addresses.add(address)
            remaining -= 1
            direction = "IN" if address & 0x80 else "OUT"
            transfer = TRANSFER_TYPES[attributes & 3]
            packet = int.from_bytes(row[4:6], "little") & 0x7FF
            yield (
                f"      Endpoint 0x{address:02x} {direction} {transfer} "
                f"max-packet={packet} bytes interval={row[6]}"
            )

    if remaining:
        raise ValueError("incomplete endpoint list")
    interfaces = {number for number, _ in settings}
    if len(interfaces) != data[4] or any((number, 0) not in settings for number in interfaces):
        raise ValueError("incomplete interface list")
