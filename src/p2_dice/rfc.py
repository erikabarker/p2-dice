RFC_VERSION_REQUEST = bytes.fromhex("b5 02 00 20 00 69")

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
