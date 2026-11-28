import importlib.util
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import ModuleType

import pytest

from p2_dice.cli import main

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="uses the macOS IOKit SDK")


@pytest.fixture(scope="module")
def native(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    source = Path(__file__).with_name("rfc_transport_fixture.c")
    library = tmp_path_factory.mktemp("legacy_usb") / "_rfc_fixture.so"
    subprocess.run(
        [
            "clang",
            "-bundle",
            "-undefined",
            "dynamic_lookup",
            "-I",
            sysconfig.get_path("include"),
            "-framework",
            "IOKit",
            "-framework",
            "CoreFoundation",
            str(source),
            "-o",
            str(library),
        ],
        check=True,
    )
    spec = importlib.util.spec_from_file_location("_rfc_fixture", library)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_writes_fixed_getter_once_and_joins_two_reads(native: ModuleType) -> None:
    assert native.simulate("success") == bytes.fromhex("b5 06 00 24 00 00 02 03 04 72")
    assert native.counts() == (1, 1, 2, 1)


@pytest.mark.parametrize(
    ("scenario", "error", "counts"),
    [
        ("wrong-alt", OSError, (0, 0, 0, 0)),
        ("occupied", OSError, (1, 0, 0, 0)),
        ("changed-alt", OSError, (1, 0, 0, 1)),
        ("wrong-packet-size", OSError, (1, 0, 0, 1)),
        ("duplicate-out", OSError, (1, 0, 0, 1)),
        ("interrupt", OSError, (1, 0, 0, 1)),
        ("write-error", OSError, (1, 1, 0, 1)),
        ("read-error", OSError, (1, 1, 1, 1)),
        ("extra", ValueError, (1, 1, 1, 1)),
        ("deadline", TimeoutError, (1, 1, 1, 1)),
    ],
)
def test_native_failure_stops_and_releases_owned_interface(
    native: ModuleType, scenario: str, error: type[Exception], counts: tuple[int, int, int, int]
) -> None:
    with pytest.raises(error):
        native.simulate(scenario)
    assert native.counts() == counts


def test_native_bounds_empty_reads(native: ModuleType) -> None:
    assert native.simulate("empty") == b""
    assert native.counts() == (1, 1, 16, 1)


def test_matching_returns_only_the_selected_service(native: ModuleType) -> None:
    assert native.select_service("one") == 2
    assert native.release_counts() == (1, 1, 0, 1)


@pytest.mark.parametrize(
    ("scenario", "message", "released"),
    [
        ("none", "No matching", (1, 0, 0, 1)),
        ("two", "Multiple matching", (1, 1, 1, 1)),
        ("changed", "list changed", (1, 1, 0, 1)),
    ],
)
def test_matching_rejects_ambiguous_or_missing_devices_and_releases_references(
    native: ModuleType, scenario: str, message: str, released: tuple[int, int, int, int]
) -> None:
    with pytest.raises(OSError, match=message):
        native.select_service(scenario)
    assert native.release_counts() == released


@pytest.mark.parametrize(
    ("command", "exit_code", "message"),
    [
        ("inventory", 1, "No DiCE USB device found (17aa:d1ce)"),
        ("rfc-version", 2, "No matching DiCE USB device (17aa:d1ce)"),
    ],
)
def test_successful_iokit_lookup_without_an_iterator(
    native: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    exit_code: int,
    message: str,
) -> None:
    monkeypatch.setitem(sys.modules, "p2_dice._iokit", native)
    assert main([command]) == exit_code
    output = capsys.readouterr()
    assert output.out == ""
    assert message in output.err
