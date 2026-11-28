from typing import NamedTuple

# Four header bytes, five reply-body bytes and one body checksum.
_REPLY_SIZE = 10


class RfcVersionReply:
    """Decode one RFC version reply across successive USB reads."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._failed = False

    def feed(self, chunk: bytes) -> tuple[int, int, int] | None:
        if self._failed:
            raise ValueError("RFC version reply was already rejected")
        try:
            return self._consume(chunk)
        except ValueError:
            self._failed = True
            raise

    def _consume(self, chunk: bytes) -> tuple[int, int, int] | None:
        if len(chunk) > _REPLY_SIZE - len(self._buffer):
            raise ValueError("unexpected trailing bytes or multiple RFC version replies")
        self._buffer.extend(chunk)
        if self._buffer and self._buffer[0] != 0xB5:
            raise ValueError("invalid RFC version frame marker")
        if len(self._buffer) >= 4:
            if int.from_bytes(self._buffer[1:3], "little") != _REPLY_SIZE - 4:
                raise ValueError("invalid RFC version reply length")
            if self._buffer[3] != (0x69 + sum(self._buffer[:3])) & 0xFF:
                raise ValueError("invalid RFC version header checksum")
        if len(self._buffer) != _REPLY_SIZE:
            return None
        body = self._buffer[4:-1]
        if self._buffer[-1] != (0x69 + sum(body)) & 0xFF:
            raise ValueError("invalid RFC version body checksum")
        command, status, major, minor, patch = body
        if command != 0:
            raise ValueError(f"unexpected reply command 0x{command:02x}")
        if status != 0:
            raise ValueError(f"RFC version getter returned status 0x{status:02x}")
        return major, minor, patch

    def finish(self) -> tuple[int, int, int]:
        version = self.feed(b"")
        if version is None:
            self._failed = True
            raise ValueError(
                f"truncated RFC version reply ({len(self._buffer)}/{_REPLY_SIZE} bytes)"
            )
        return version


_FIRMWARE_REPLY_SIZE = 4 + 35 + 1


class FirmwareVersion(NamedTuple):
    """The build field contains all 30 wire bytes. Its encoding is unspecified."""

    major: int
    minor: int
    patch: int
    build: bytes


class FirmwareVersionReply:
    """Decode one adapter firmware version reply across successive reads."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._failed = False

    def feed(self, chunk: bytes) -> FirmwareVersion | None:
        if self._failed:
            raise ValueError("firmware version reply was already rejected")
        try:
            return self._consume(chunk)
        except ValueError:
            self._failed = True
            raise

    def _consume(self, chunk: bytes) -> FirmwareVersion | None:
        if len(chunk) > _FIRMWARE_REPLY_SIZE - len(self._buffer):
            raise ValueError("unexpected trailing bytes or multiple firmware version replies")
        self._buffer.extend(chunk)
        if self._buffer and self._buffer[0] != 0xB5:
            raise ValueError("invalid firmware version frame marker")
        if len(self._buffer) >= 4:
            if int.from_bytes(self._buffer[1:3], "little") != _FIRMWARE_REPLY_SIZE - 4:
                raise ValueError("invalid firmware version reply length")
            if self._buffer[3] != (0x69 + sum(self._buffer[:3])) & 0xFF:
                raise ValueError("invalid firmware version header checksum")
        if len(self._buffer) != _FIRMWARE_REPLY_SIZE:
            return None
        body = self._buffer[4:-1]
        if self._buffer[-1] != (0x69 + sum(body)) & 0xFF:
            raise ValueError("invalid firmware version body checksum")
        command, status = body[:2]
        if command != 0x04:
            raise ValueError(f"unexpected reply command 0x{command:02x}")
        if status != 0:
            raise ValueError(f"firmware version getter returned status 0x{status:02x}")
        return FirmwareVersion(body[2], body[3], body[34], bytes(body[4:34]))

    def finish(self) -> FirmwareVersion:
        version = self.feed(b"")
        if version is None:
            self._failed = True
            raise ValueError(
                f"truncated firmware version reply ({len(self._buffer)}/{_FIRMWARE_REPLY_SIZE} bytes)"
            )
        return version
