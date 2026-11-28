from abc import ABC, abstractmethod
from typing import NamedTuple


class _VersionReply[T](ABC):
    _name: str
    _command: int
    _frame_size: int

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._failed = False

    def feed(self, chunk: bytes) -> T | None:
        if self._failed:
            raise ValueError(f"{self._name} reply was already rejected")
        try:
            return self._consume(chunk)
        except ValueError:
            self._failed = True
            raise

    def _consume(self, chunk: bytes) -> T | None:
        if len(chunk) > self._frame_size - len(self._buffer):
            raise ValueError(f"unexpected trailing bytes or multiple {self._name} replies")
        self._buffer.extend(chunk)
        if self._buffer and self._buffer[0] != 0xB5:
            raise ValueError(f"invalid {self._name} frame marker")
        if len(self._buffer) >= 4:
            if int.from_bytes(self._buffer[1:3], "little") != self._frame_size - 4:
                raise ValueError(f"invalid {self._name} reply length")
            if self._buffer[3] != (0x69 + sum(self._buffer[:3])) & 0xFF:
                raise ValueError(f"invalid {self._name} header checksum")
        if len(self._buffer) != self._frame_size:
            return None
        body = self._buffer[4:-1]
        if self._buffer[-1] != (0x69 + sum(body)) & 0xFF:
            raise ValueError(f"invalid {self._name} body checksum")
        command, status = body[:2]
        if command != self._command:
            raise ValueError(f"unexpected reply command 0x{command:02x}")
        if status != 0:
            raise ValueError(f"{self._name} getter returned status 0x{status:02x}")
        return self._decode(body)

    def finish(self) -> T:
        version = self.feed(b"")
        if version is None:
            self._failed = True
            raise ValueError(
                f"truncated {self._name} reply ({len(self._buffer)}/{self._frame_size} bytes)"
            )
        return version

    @abstractmethod
    def _decode(self, body: bytearray) -> T: ...


class RfcVersionReply(_VersionReply[tuple[int, int, int]]):
    """Decode one RFC version reply across successive USB reads."""

    _name = "RFC version"
    _command = 0x00
    _frame_size = 4 + 5 + 1

    def _decode(self, body: bytearray) -> tuple[int, int, int]:
        return body[2], body[3], body[4]


class FirmwareVersion(NamedTuple):
    """The build field contains all 30 wire bytes. Its encoding is unspecified."""

    major: int
    minor: int
    patch: int
    build: bytes


class FirmwareVersionReply(_VersionReply[FirmwareVersion]):
    """Decode one adapter firmware version reply across successive reads."""

    _name = "firmware version"
    _command = 0x04
    _frame_size = 4 + 35 + 1

    def _decode(self, body: bytearray) -> FirmwareVersion:
        return FirmwareVersion(body[2], body[3], body[34], bytes(body[4:34]))
