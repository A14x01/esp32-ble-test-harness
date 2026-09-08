"""Device interface and the real BLE implementation.

The tests are written against `DeviceClient`. Two things implement it: this
module's `BleDeviceClient`, which talks to actual hardware over Bluetooth Low
Energy, and `MockDeviceClient` in mock_device.py. Same tests, both targets.
"""

from __future__ import annotations

import abc

from . import protocol
from .logging_setup import log_event


class DeviceError(RuntimeError):
    """Raised when the transport itself fails (not a device-side rejection)."""


class DeviceClient(abc.ABC):
    """Everything a test is allowed to do to the device."""

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...

    @abc.abstractmethod
    async def is_connected(self) -> bool: ...

    @abc.abstractmethod
    async def read_raw(self, char_uuid: str) -> bytes: ...

    @abc.abstractmethod
    async def write_raw(self, char_uuid: str, payload: bytes) -> None: ...

    # -- Convenience wrappers used by the tests -----------------------------

    async def read_temperature_c(self) -> float:
        payload = await self.read_raw(protocol.CHAR_TEMPERATURE)
        celsius = protocol.raw_to_celsius(protocol.decode_centi(payload))
        log_event("read_temperature", celsius=celsius)
        return celsius

    async def read_threshold_c(self) -> float:
        payload = await self.read_raw(protocol.CHAR_THRESHOLD)
        celsius = protocol.raw_to_celsius(protocol.decode_centi(payload))
        log_event("read_threshold", celsius=celsius)
        return celsius

    async def write_threshold_raw(self, payload: bytes) -> None:
        """Write arbitrary bytes. Used by the negative tests deliberately."""
        log_event("write_threshold", payload=payload.hex(), length=len(payload))
        await self.write_raw(protocol.CHAR_THRESHOLD, payload)

    async def write_threshold_c(self, celsius: float) -> None:
        await self.write_threshold_raw(protocol.encode_celsius(celsius))

    async def read_status(self) -> protocol.Status:
        payload = await self.read_raw(protocol.CHAR_STATUS)
        if len(payload) != 1:
            raise DeviceError(f"status must be 1 byte, got {len(payload)}")
        status = protocol.Status(payload[0])
        log_event("read_status", status=status.name)
        return status


class BleDeviceClient(DeviceClient):
    """Talks to a real ESP32 over BLE using bleak.

    Import of bleak is deferred so that the mock path has no Bluetooth
    dependency and CI can run on a machine with no radio at all.
    """

    def __init__(self, device_name: str = protocol.DEVICE_NAME, timeout: float = 10.0):
        self.device_name = device_name
        self.timeout = timeout
        self._client = None

    async def connect(self) -> None:
        from bleak import BleakClient, BleakScanner

        log_event("scan_start", name=self.device_name, timeout=self.timeout)
        device = await BleakScanner.find_device_by_name(
            self.device_name, timeout=self.timeout
        )
        if device is None:
            raise DeviceError(
                f"no BLE device advertising as {self.device_name!r} within "
                f"{self.timeout}s - is the board powered and in range?"
            )

        log_event("connecting", address=device.address)
        self._client = BleakClient(device)
        await self._client.connect()
        log_event("connected", address=device.address)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            log_event("disconnected")
            self._client = None

    async def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def read_raw(self, char_uuid: str) -> bytes:
        if self._client is None:
            raise DeviceError("not connected")
        return bytes(await self._client.read_gatt_char(char_uuid))

    async def write_raw(self, char_uuid: str, payload: bytes) -> None:
        if self._client is None:
            raise DeviceError("not connected")
        # response=True so the peripheral acknowledges; without it a rejected
        # write looks identical to an accepted one from the host side.
        await self._client.write_gatt_char(char_uuid, payload, response=True)
