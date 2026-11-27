# p2-dice

A macOS command-line tool for inspecting the USB interfaces exposed by a Volvo DiCE diagnostic adapter. The vehicle under study is a 2004 Volvo XC70 on the P2 platform.

## Inspect an adapter

On macOS, install [uv](https://docs.astral.sh/uv/) and [libusb](https://formulae.brew.sh/formula/libusb) through Homebrew. Connect the adapter to the Mac. If a virtual machine has captured it, release the adapter to macOS first.

```sh
brew install uv libusb
uv sync --locked
uv run --locked p2-dice inventory
```

Run the last two commands from this checkout. The inventory looks for USB vendor ID `17aa` and product ID `d1ce` and lists each matching device's configurations, interfaces, alternate settings and endpoints. Endpoint direction is relative to the host. An IN endpoint carries data from the adapter to the Mac. See the [libusb descriptor reference](https://libusb.sourceforge.io/api-1.0/group__libusb__desc.html).

## Support

| Operation | Evidence |
| --- | --- |
| Identify a USB device advertising `17aa:d1ce` | Observed by macOS on one adapter. These IDs alone cannot establish authenticity. |
| Inventory configurations, interfaces and endpoints | Native implementation under validation. |
| Read adapter firmware version | Unverified. |
| Read a vehicle ECU on the 2004 XC70 | Unverified. |

The USB device release field (`bcdDevice`) is vendor-defined. Reporting that field does not establish the installed DiCE firmware version. The inventory reads USB descriptors without opening a vehicle-network channel.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development commands and instructions for reporting hardware observations. The project uses the [GNU General Public License, version 2 only](LICENSE).
