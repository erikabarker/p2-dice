import hashlib
import json
import os
from pathlib import Path

import pytest

from p2_dice.capture import decode_engine_capture
from p2_dice.cli import main

SUPPORTED_PIDS = "48-6B-10-41-00-98-3B-80-11-68"
STORED_P0301 = "48-6B-10-43-03-01-00-00-00-00-0A"
PENDING_THREE = "48-6B-10-47-01-71-40-35-92-34-B7"
EMPTY_STORED = "48-6B-10-43-00-00-00-00-00-00-06"


def entry(operation: str, hex: str | None = None, **fields: object) -> dict[str, object]:
    size = len(bytes.fromhex(hex.replace("-", ""))) if hex and operation == "Read" else 0
    record: dict[str, object] = {
        "Time": "2000-01-01T00:00:00.0000000+00:00",
        "Operation": operation,
        "Status": 0,
        "Count": 0,
        "RxStatus": 0,
        "Timestamp": 0,
        "DataSize": size,
        "ExtraDataIndex": 0,
        "Hex": hex,
        "Error": None,
    }
    return record | fields


def write(hex: str, **fields: object) -> dict[str, object]:
    return entry("Write", hex, **{"Count": 1} | fields)


def reply(hex: str, timestamp: int = 5000, **fields: object) -> list[dict[str, object]]:
    return [
        entry("Read", "", Count=1, RxStatus=2, Timestamp=timestamp),
        entry("Read", hex, Count=1, Timestamp=timestamp, **fields),
    ]


EMPTY_BUFFER = entry("Read", Status=16, Error="Protocol message buffer empty.")


def session(*middle: dict[str, object]) -> list[dict[str, object]]:
    return [
        entry("Open"),
        entry("Connect ISO9141 10400"),
        entry("Pass filter"),
        entry("Five baud init 33", "94-94"),
        *middle,
        entry("Stop filter"),
        entry("Disconnect"),
        entry("Close"),
    ]


STARTED = session()[:4]
CLEANUP = session()[4:]


def test_cli_decodes_stored_and_pending_codes_with_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = tmp_path / "capture.json"
    capture.write_text(
        json.dumps(
            session(
                write("68-6A-F1-01-00"),
                *reply(SUPPORTED_PIDS),
                EMPTY_BUFFER,
                write("68-6A-F1-03", Time="2000-01-01T00:00:01.0000000+00:00"),
                *reply(STORED_P0301, Time="2000-01-01T00:00:01.5000000+00:00"),
                EMPTY_BUFFER,
                write("68-6A-F1-07"),
                *reply(PENDING_THREE, timestamp=7000),
                EMPTY_BUFFER,
            )
        )
    )

    assert main(["import-engine-capture", str(capture)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source_file"] == str(capture)
    assert result["source_sha256"] == hashlib.sha256(capture.read_bytes()).hexdigest()
    assert result["session_errors"] == []
    assert result["stored"] == {
        "status": "replied",
        "request_time": "2000-01-01T00:00:01.0000000+00:00",
        "request_hex": "68-6A-F1-03",
        "errors": [],
        "responses": [
            {
                "source_address": "0x10",
                "host_time": "2000-01-01T00:00:01.5000000+00:00",
                "adapter_timestamp": 5000,
                "raw_hex": STORED_P0301,
                "dtcs": ["P0301"],
            }
        ],
    }
    assert result["pending"]["status"] == "replied"
    assert result["pending"]["responses"][0]["adapter_timestamp"] == 7000
    assert result["pending"]["responses"][0]["dtcs"] == ["P0171", "C0035", "B1234"]


def test_keeps_each_frame_of_a_multi_frame_reply() -> None:
    capture = decode_engine_capture(
        session(
            write("68-6A-F1-03"),
            *reply("48-6B-18-43-C1-00-04-20-03-00-F6"),
            *reply("48-6B-18-43-01-33-00-00-00-00-42"),
            EMPTY_BUFFER,
        )
    )
    assert [r.source_address for r in capture.stored.responses] == ["0x18", "0x18"]
    assert [r.dtcs for r in capture.stored.responses] == [["U0100", "P0420", "P0300"], ["P0133"]]


@pytest.mark.parametrize(
    ("mode", "frame", "codes"),
    [
        ("03", "48-6B-10-43-03-01-01-71-C1-00-3D", ["P0301", "P0171", "U0100"]),
        ("03", "48-6B-10-43-04-20-00-00-00-00-2A", ["P0420"]),
        ("07", "48-6B-18-47-03-00-00-00-00-00-15", ["P0300"]),
        ("07", "48-6B-18-47-00-00-00-00-00-00-12", []),
    ],
)
def test_decodes_independently_derived_vectors(mode: str, frame: str, codes: list[str]) -> None:
    capture = decode_engine_capture(session(write(f"68-6A-F1-{mode}"), *reply(frame)))
    query = capture.stored if mode == "03" else capture.pending
    assert query.status == "replied"
    assert [r.dtcs for r in query.responses] == [codes]


def test_all_zero_reply_is_a_confirmed_empty_code_list() -> None:
    stored = decode_engine_capture(session(write("68-6A-F1-03"), *reply(EMPTY_STORED))).stored
    assert stored.status == "replied"
    assert [r.dtcs for r in stored.responses] == [[]]


def test_negative_response_is_a_read_failure_beside_other_replies() -> None:
    stored = decode_engine_capture(
        session(write("68-6A-F1-03"), *reply("48-6B-10-7F-03-12-57"), *reply(EMPTY_STORED))
    ).stored
    assert stored.status == "read_failed"
    assert stored.errors == ["negative response 0x12 from 0x10"]
    assert [r.dtcs for r in stored.responses] == [[]]


def test_failed_supported_pid_request_is_a_session_error() -> None:
    capture = decode_engine_capture(
        session(write("68-6A-F1-01-00", Status=8, Count=0, Error="Synthetic write fault"))
    )
    assert capture.session_errors == ["Write status 8: Synthetic write fault"]
    assert capture.stored.status == capture.pending.status == "not_requested"


def test_read_error_before_the_code_queries_is_a_session_error() -> None:
    capture = decode_engine_capture(
        session(write("68-6A-F1-01-00"), entry("Read", Status=8, Error="Synthetic bus fault"))
    )
    assert capture.session_errors == ["Read status 8: Synthetic bus fault"]
    assert capture.stored.status == capture.pending.status == "not_requested"


def test_silence_is_no_reply_and_unrequested_modes_are_distinct() -> None:
    capture = decode_engine_capture(session(write("68-6A-F1-03"), EMPTY_BUFFER, EMPTY_BUFFER))
    assert (capture.stored.status, capture.stored.responses) == ("no_reply", [])
    assert capture.pending.status == "not_requested"


def test_driver_errors_are_read_failures_not_empty_lists() -> None:
    capture = decode_engine_capture(
        session(
            write("68-6A-F1-03", Status=8, Count=0, Error="Device not connected."),
            write("68-6A-F1-07"),
            entry("Read", Status=8, Error="Device not connected."),
        )
    )
    assert capture.stored.status == "write_failed"
    assert capture.stored.errors == ["Write status 8: Device not connected."]
    assert capture.pending.status == "read_failed"
    assert capture.pending.errors == ["Read status 8: Device not connected."]


def test_unrecorded_oversized_message_is_a_read_failure() -> None:
    stored = decode_engine_capture(
        [
            *STARTED,
            write("68-6A-F1-03"),
            entry("Read", Count=1),
            entry("Exception", Status=-1, Error="Invalid driver message size"),
            *CLEANUP,
        ]
    ).stored
    assert stored.status == "read_failed"
    assert stored.errors == [
        "Read status 0: message data was not recorded",
        "Exception status -1: Invalid driver message size",
    ]


def test_exception_during_a_query_is_a_read_failure() -> None:
    capture = decode_engine_capture(
        session(write("68-6A-F1-07"), entry("Exception", Status=-1, Error="Synthetic fault"))
    )
    assert capture.pending.status == "read_failed"
    assert capture.session_errors == []


@pytest.mark.parametrize(
    "capture",
    [
        entry("Open", Status=8, Error="Device not connected."),
        entry("Exception", Status=-1, Error="Synthetic DLL load fault"),
    ],
    ids=["open-failure", "pre-open-exception"],
)
def test_accepts_the_single_entry_object_a_failed_start_produces(
    capture: dict[str, object], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(capture))
    assert main(["import-engine-capture", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["session_errors"] == [
        f"{capture['Operation']} status {capture['Status']}: {capture['Error']}"
    ]
    assert result["stored"]["status"] == result["pending"]["status"] == "not_requested"


def test_setup_failure_keeps_its_cause_and_cleanup_status() -> None:
    capture = decode_engine_capture(
        [
            entry("Open"),
            entry("Connect ISO9141 10400"),
            entry("Pass filter"),
            entry("Five baud init 33", Status=8, Error="Synthetic init fault"),
            entry("Stop filter"),
            entry("Disconnect", Status=2, Error="Synthetic disconnect fault"),
            entry("Close"),
        ]
    )
    assert capture.session_errors == [
        "Five baud init 33 status 8: Synthetic init fault",
        "Disconnect status 2: Synthetic disconnect fault",
    ]
    assert capture.stored.status == capture.pending.status == "not_requested"


@pytest.mark.parametrize(
    ("capture", "error"),
    [
        ("Open", "JSON array or object"),
        ({"Operation": "Read"}, "Status must be int"),
        ([[]], "entry 0: log entry must be an object"),
        ([entry("Open", Status=True)], "Status must be int"),
        ([entry("Open", Status=None)], "Status must be int"),
        ([entry("Calibrate")], "unsupported operation"),
        ([*STARTED, write("68-6A-F1-03"), *reply(STORED_P0301[:-3])], "entry 6: frame checksum"),
        ([*STARTED, write("68-6A-F1-03"), *reply(STORED_P0301[:-1] + "B")], "frame checksum"),
        ([*STARTED, write("68-6A-F1-03"), *reply("48-6B-10-43-03-01-0A")], "three DTC slots"),
        ([*STARTED, write("68-6A-F1-03"), *reply(STORED_P0301, DataSize=10)], "DataSize"),
        ([*STARTED, write("68-6A-F1-03"), *reply(STORED_P0301.lower())], "uppercase"),
        ([*STARTED, write("68-6A-F1-03"), *reply("486B1043030100000000 0A")], "uppercase"),
        ([*STARTED, write("68-6A-F1-03"), *reply("48-6B-10-41-00-98-3B-80-11-68")], "service 41"),
        ([*STARTED, write("68-6A-F1-03"), *reply("49-6B-10-43-03-01-00-00-00-00-0B")], "header"),
        ([*STARTED, write("68-6A-F1-03"), *reply(STORED_P0301, RxStatus=1)], "RxStatus 0x1"),
        ([*STARTED, write("68-6A-F1-03"), *reply(STORED_P0301 + "-00" * 2)], "outside ISO 9141-2"),
        ([*STARTED, *reply("48-6B-10-41-00-98-3B-80-11-69")], "frame checksum"),
        ([*STARTED, write("68-6A-F1-03"), write("68-6A-F1-03")], "repeated mode 03"),
        ([*STARTED, write("68-6A-F1-03-00")], "unexpected parameters"),
        ([*STARTED, write("C1-33-F1-03")], "functional OBD request"),
        ([entry("Open", Status=8), write("68-6A-F1-03")], "entry 1: request outside"),
        ([*STARTED[:3], write("68-6A-F1-03")], "request outside"),
        ([*session(), write("68-6A-F1-03")], "request outside"),
        ([entry("Read", Count=2)], "read count 2"),
    ],
)
def test_rejects_malformed_or_unsupported_input(capture: object, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        decode_engine_capture(capture)


@pytest.mark.parametrize(
    ("content", "status", "message"),
    [
        (b'[{"Operation": "Read"', 3, "Invalid engine capture"),
        (json.dumps([{"Operation": "Read"}]).encode(), 3, "Status must be int"),
        (b"[" * 100_000, 3, "Invalid engine capture"),
        (None, 2, "Cannot read engine capture"),
    ],
)
def test_cli_reports_invalid_capture_without_a_result(
    content: bytes | None,
    status: int,
    message: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capture = tmp_path / "capture.json"
    if content is not None:
        capture.write_bytes(content)
    assert main(["import-engine-capture", str(capture)]) == status
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_accepts_windows_powershell_utf16_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps(session()), encoding="utf-16")
    assert main(["import-engine-capture", str(capture)]) == 0
    assert json.loads(capsys.readouterr().out)["stored"]["status"] == "not_requested"


@pytest.mark.skipif(
    "P2_DICE_ENGINE_SESSION" not in os.environ,
    reason="set P2_DICE_ENGINE_SESSION to a private session folder to compare a real capture",
)
def test_private_capture_matches_its_saved_baseline() -> None:
    folder = Path(os.environ["P2_DICE_ENGINE_SESSION"])
    baseline = json.loads((folder / "baseline.json").read_text())
    capture = decode_engine_capture(json.loads((folder / "raw-driver-log.json").read_bytes()))
    saved = {
        (r["source_address"], r["host_time"], r["adapter_timestamp"], r["raw_hex"])
        for r in baseline["raw_replies"]
    }
    assert capture.session_errors == []
    for name, query in (("stored", capture.stored), ("pending", capture.pending)):
        assert query.status == "replied"
        for response in query.responses:
            key = (response.source_address, response.host_time, response.adapter_timestamp)
            assert (*key, response.raw_hex) in saved
            codes = baseline[f"source_{response.source_address.lower()}"][f"{name}_dtcs"]
            assert response.dtcs == codes
