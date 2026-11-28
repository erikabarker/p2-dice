from dataclasses import dataclass, field

# SAE J1979 modes 03 and 07 report stored and pending emission DTCs.
MODES = {3: "stored", 7: "pending"}
# Fixed by the Windows engine reader: it records nothing else between Open and Close.
_SESSION = {
    "Open",
    "Connect ISO9141 10400",
    "Pass filter",
    "Five baud init 33",
    "Stop filter",
    "Disconnect",
    "Close",
}
# J2534 STATUS_NOERROR, ERR_TIMEOUT and ERR_BUFFER_EMPTY.
_QUIET = {0, 9, 16}
_START_OF_MESSAGE = 0x02


@dataclass
class Response:
    source_address: str
    host_time: str
    adapter_timestamp: int
    raw_hex: str
    dtcs: list[str]


@dataclass
class Query:
    status: str = "not_requested"
    request_time: str | None = None
    request_hex: str | None = None
    errors: list[str] = field(default_factory=list)
    responses: list[Response] = field(default_factory=list)


@dataclass
class EngineCapture:
    stored: Query = field(default_factory=Query)
    pending: Query = field(default_factory=Query)
    session_errors: list[str] = field(default_factory=list)


def decode_engine_capture(entries: object) -> EngineCapture:
    """Decode the stored and pending DTC queries in a read-engine-faults.ps1 log."""
    # ConvertTo-Json writes a one-entry log, such as a failed Open, as a bare object.
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise ValueError("capture must be a JSON array or object of J2534 log entries")
    capture = EngineCapture()
    queries = {"stored": capture.stored, "pending": capture.pending}
    active: tuple[int, Query] | None = None
    ready = False
    for index, entry in enumerate(entries):
        try:
            active, ready = _apply(entry, active, ready, queries, capture.session_errors)
        except ValueError as error:
            raise ValueError(f"entry {index}: {error}") from None
    for query in queries.values():
        if query.status == "requested":
            query.status = (
                "read_failed" if query.errors else "replied" if query.responses else "no_reply"
            )
    return capture


def _apply(
    entry: object,
    active: tuple[int, Query] | None,
    ready: bool,
    queries: dict[str, Query],
    session_errors: list[str],
) -> tuple[tuple[int, Query] | None, bool]:
    if not isinstance(entry, dict):
        raise ValueError("log entry must be an object")
    operation = _field(entry, "Operation", str)
    status = _field(entry, "Status", int)
    if operation == "Write":
        # The reader only queries after a successful init and stops at its first failure.
        if not ready:
            raise ValueError("request outside a successfully initialized session")
        return _write(entry, status, queries, session_errors), True
    if operation == "Read":
        _read(entry, status, active, active[1].errors if active else session_errors)
        return active, ready
    if operation not in _SESSION | {"Exception"}:
        raise ValueError(f"unsupported operation {operation!r}")
    if status != 0:
        errors = active[1].errors if active and operation == "Exception" else session_errors
        errors.append(_error(entry, status))
    return None, operation == "Five baud init 33" and status == 0


def _write(
    entry: dict, status: int, queries: dict[str, Query], session_errors: list[str]
) -> tuple[int, Query] | None:
    request = _bytes(entry)
    if request[:3] != b"\x68\x6a\xf1" or len(request) < 4:
        raise ValueError("request is not an ISO 9141-2 functional OBD request")
    mode = request[3]
    failed = status != 0 or _field(entry, "Count", int) != 1
    if mode not in MODES:
        if failed:
            session_errors.append(_error(entry, status))
        return None
    if len(request) != 4:
        raise ValueError(f"mode {mode:02x} request carries unexpected parameters")
    query = queries[MODES[mode]]
    if query.status != "not_requested":
        raise ValueError(f"repeated mode {mode:02x} request")
    query.request_time = _field(entry, "Time", str)
    query.request_hex = _field(entry, "Hex", str)
    if failed:
        query.status = "write_failed"
        query.errors.append(_error(entry, status))
        return None
    query.status = "requested"
    return mode, query


def _read(entry: dict, status: int, active: tuple[int, Query] | None, errors: list[str]) -> None:
    count = _field(entry, "Count", int)
    if count not in (0, 1):
        raise ValueError(f"read count {count} is not 0 or 1")
    if count == 0 and status in _QUIET:
        return
    if count == 0 or status not in (0, 9):
        errors.append(_error(entry, status))
        return
    # The reader throws on an oversized driver message after logging only its count.
    if entry.get("Hex") is None:
        errors.append(f"Read status {status}: message data was not recorded")
        return
    data = _bytes(entry)
    if len(data) != _field(entry, "DataSize", int):
        raise ValueError("Hex length differs from DataSize")
    rx_status = _field(entry, "RxStatus", int)
    if rx_status == _START_OF_MESSAGE and not data:
        return
    if rx_status != 0:
        raise ValueError(f"unsupported RxStatus 0x{rx_status:x}")
    # ISO 9141-2: three header bytes, one to seven data bytes, one checksum byte.
    if not 5 <= len(data) <= 11:
        raise ValueError(f"{len(data)}-byte frame is outside ISO 9141-2 bounds")
    if data[:2] != b"\x48\x6b":
        raise ValueError("frame lacks the ISO 9141-2 OBD response header")
    if data[-1] != sum(data[:-1]) & 0xFF:
        raise ValueError("frame checksum mismatch")
    if not active:
        return
    mode, query = active
    if len(data) == 7 and data[3:5] == bytes([0x7F, mode]):
        errors.append(f"negative response 0x{data[5]:02X} from 0x{data[2]:02X}")
        return
    if data[3] != mode + 0x40:
        raise ValueError(f"mode {mode:02x} request answered by service {data[3]:02x}")
    if len(data) != 11:
        raise ValueError(f"mode {mode:02x} reply must carry three DTC slots")
    query.responses.append(
        Response(
            source_address=f"0x{data[2]:02X}",
            host_time=_field(entry, "Time", str),
            adapter_timestamp=_field(entry, "Timestamp", int),
            raw_hex=_field(entry, "Hex", str),
            dtcs=[_dtc(data[i : i + 2]) for i in range(4, 10, 2) if data[i : i + 2] != b"\0\0"],
        )
    )


def _dtc(pair: bytes) -> str:
    return f"{'PCBU'[pair[0] >> 6]}{pair[0] >> 4 & 3}{pair[0] & 0xF:X}{pair[1]:02X}"


def _bytes(entry: dict) -> bytes:
    text = _field(entry, "Hex", str)
    data = bytes.fromhex(text.replace("-", ""))
    if data.hex("-").upper() != text:
        raise ValueError("Hex is not dash-separated uppercase bytes")
    return data


def _error(entry: dict, status: int) -> str:
    error = entry.get("Error")
    return f"{entry['Operation']} status {status}" + (f": {error}" if error else "")


def _field[T](entry: dict, name: str, kind: type[T]) -> T:
    value = entry.get(name)
    if type(value) is not kind:
        raise ValueError(f"{name} must be {kind.__name__}")
    return value
