"""Numeric fields PyUSB populates dynamically from libusb descriptors."""

from collections.abc import Iterator
from typing import Protocol


class Endpoint(Protocol):
    bEndpointAddress: int
    bmAttributes: int
    wMaxPacketSize: int


class Interface(Protocol):
    bInterfaceNumber: int
    bAlternateSetting: int
    bInterfaceClass: int
    bNumEndpoints: int

    def __iter__(self) -> Iterator[Endpoint]: ...


class Configuration(Protocol):
    bConfigurationValue: int
    bNumInterfaces: int

    def __getitem__(self, index: tuple[int, int]) -> Interface: ...


class Device(Protocol):
    idVendor: int
    idProduct: int
    bcdUSB: int
    bcdDevice: int
    bus: int | None
    address: int | None

    def __iter__(self) -> Iterator[Configuration]: ...
