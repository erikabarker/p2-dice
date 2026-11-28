# p2-dice

A macOS command-line tool for inspecting the USB interfaces exposed by a Volvo DiCE diagnostic adapter. The vehicle under study is a 2004 Volvo XC70 on the P2 platform.

## Inspect an adapter

On macOS, install the Xcode Command Line Tools and [uv](https://docs.astral.sh/uv/). The compiler builds the small IOKit extension when uv installs the package. Connect the adapter to the Mac. If a virtual machine has captured it, release the adapter to macOS first.

```sh
brew install uv
uv sync --locked
uv run --locked p2-dice inventory
```

Run the last two commands from this checkout. The inventory looks for USB vendor ID `17aa` and product ID `d1ce` and lists each matching device's configurations, interfaces, alternate settings and endpoints. Endpoint direction is relative to the host. An IN endpoint carries data from the adapter to the Mac. The command reads the configuration descriptors macOS cached during USB enumeration. See [Apple’s USB device interface reference](https://developer.apple.com/documentation/iokit/iousbdeviceinterface942/2977148-getconfigurationdescriptorptr).

The command exits with status 0 on success, 1 when no matching adapter is present, or 2 on an inventory error. A failed read prints its diagnostic to standard error.

## Read the RFC interface version

`uv run --locked p2-dice rfc-version` queries the adapter's RFC protocol version. This operation is experimental. On one powered DiCE adapter, the native macOS command returned RFC version `1.1.24` with the engine and ignition off.

The command selects a single matching adapter and checks its active USB configuration. If the adapter is unconfigured, it opens the device without seizing it, verifies that it advertises configuration 1, selects that configuration once and releases the device. It then opens interface 0 and sends the fixed version request once. It reports a version only after the command identifier, status, length and checksums validate. The RFC version identifies the protocol spoken by the adapter. The native CLI does not yet implement the separate firmware-version query.

## Import a saved engine capture

`uv run --locked p2-dice import-engine-capture PATH` decodes the JSON log written by the separate Windows engine reader, which ran the official J2534 driver. It reads the file offline and opens no device. The command reports the generic stored (mode 03) and pending (mode 07) emission codes. Each reply keeps its source address, host time, adapter timestamp and raw frame. It validates every received frame's ISO 9141-2 header, length and checksum.

Each mode has one status. `replied` with an empty `dtcs` list means the module confirmed no codes. `no_reply`, `write_failed` and `read_failed` mean the read did not establish a code list, and `not_requested` means the reader never sent that mode. A negative response counts as a read failure. Failures outside the code queries, such as a failed open, initialization or cleanup, appear in `session_errors`. The command exits with status 3 and prints no result on malformed or unsupported input. Keep real captures and their decoded output outside this repository.

## Support

| Operation | Evidence |
| --- | --- |
| Identify a USB device advertising `17aa:d1ce` | Observed by macOS on one adapter. These IDs alone cannot establish authenticity. |
| Inventory configurations, interfaces and endpoints | The packaged CLI on Apple silicon read configuration 1, interface 0, alternate setting 0 on one adapter. Bulk endpoints were IN `0x81` and OUT `0x01`, both with a 512-byte maximum packet. |
| Read adapter RFC protocol version | On Apple silicon, the packaged CLI received a valid `1.1.24` reply from one adapter. |
| Decode a saved adapter firmware-version reply | Offline parser tested with synthetic command `0x04` frames. No native firmware reply captured. |
| Read adapter firmware version | The native macOS command is unimplemented. |
| Decode a saved Windows ISO 9141-2 engine-code capture | One real capture decoded offline. Its result matched the separately saved baseline. |
| Read a vehicle ECU natively from macOS | Unverified. |

The USB device release field (`bcdDevice`) is vendor-defined. Reporting that field does not establish the installed DiCE firmware version. The inventory reads USB descriptors without opening a vehicle-network channel.

## Development direction

The target is independent module diagnostics and customization: a complete controller and sensor/output map, live readings, fault clearing, learned adaptations, configuration, service routines, firmware reading/programming and custom calibration or code. These are development targets; implemented and observed support is listed above. Each module and software version needs its own verified operation. Factory software packages and update availability are separate from diagnostic protocol access.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development commands and instructions for reporting hardware observations. The project uses the [GNU General Public License, version 2 only](LICENSE).
