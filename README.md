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

`uv run --locked p2-dice rfc-version` queries the adapter's RFC protocol version. This operation is experimental. The request and reply format were checked against the host driver, and the transport has been tested offline. A physical adapter has yet to return a verified reply to this command.

The command selects a single matching adapter, temporarily opens its USB interface and sends the fixed version request once. It reports a version only after the command identifier, status, length and checksums validate. The RFC version identifies the protocol spoken by the adapter. The separate firmware-version query remains unverified.

## Support

| Operation | Evidence |
| --- | --- |
| Identify a USB device advertising `17aa:d1ce` | Observed by macOS on one adapter. These IDs alone cannot establish authenticity. |
| Inventory configurations, interfaces and endpoints | The packaged CLI on Apple silicon read configuration 1, interface 0, alternate setting 0 on one adapter. Bulk endpoints were IN `0x81` and OUT `0x01`, both with a 512-byte maximum packet. |
| Read adapter RFC protocol version | Fixed getter implemented and tested offline. Hardware reply pending. |
| Read adapter firmware version | Unverified. |
| Read a vehicle ECU on the 2004 XC70 | Unverified. |

The USB device release field (`bcdDevice`) is vendor-defined. Reporting that field does not establish the installed DiCE firmware version. The inventory reads USB descriptors without opening a vehicle-network channel.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development commands and instructions for reporting hardware observations. The project uses the [GNU General Public License, version 2 only](LICENSE).
