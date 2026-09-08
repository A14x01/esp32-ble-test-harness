"""In-process fake of the ESP32 thermostat.

This mirrors `firmware/thermostat_ble/thermostat_ble.ino` clause for clause. It
exists so the suite runs in CI with no hardware attached, and so a failure can
be localised: mock red means the test or the shared protocol logic is wrong,
mock green plus hardware red means the firmware is wrong.

It is deliberately not "nice" - it rejects exactly what the firmware rejects
and stays alive exactly where the firmware stays alive.
"""

from __future__ import annotations

import itertools

from . import protocol
from .device import DeviceClient, DeviceError


class MockDeviceClient(DeviceClient):
    def __init__(self, start_temp_c: float = 21.0, threshold_c: float = 25.0):
        self._connected = False
        self._threshold_raw = protocol.celsius_to_raw(threshold_c)
        self._status = protocol.Status.OK
        self._rejected_writes = 0

        # Temperature drifts on each read so tests can't accidentally depend on
        # a frozen value, but stays inside a believable band.
        base = protocol.celsius_to_raw(start_temp_c)
        self._temp_cycle = itertools.cycle(
            [base - 30, base - 10, base, base + 10, base + 30]
        )

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    def _require_connection(self) -> None:
        if not self._connected:
            raise DeviceError("not connected")

    # -- GATT ---------------------------------------------------------------

    async def read_raw(self, char_uuid: str) -> bytes:
        self._require_connection()

        if char_uuid == protocol.CHAR_TEMPERATURE:
            return protocol.encode_centi(next(self._temp_cycle))

        if char_uuid == protocol.CHAR_THRESHOLD:
            return protocol.encode_centi(self._threshold_raw)

        if char_uuid == protocol.CHAR_STATUS:
            return bytes([int(self._status)])

        raise DeviceError(f"unknown characteristic {char_uuid}")

    async def write_raw(self, char_uuid: str, payload: bytes) -> None:
        self._require_connection()

        if char_uuid != protocol.CHAR_THRESHOLD:
            raise DeviceError(f"characteristic {char_uuid} is not writable")

        status = protocol.classify_write(payload)
        self._status = status

        if status is protocol.Status.OK:
            self._threshold_raw = protocol.decode_centi(payload)
        else:
            # The critical behaviour: a bad write updates status, leaves the
            # stored value untouched, and does NOT take the device down.
            self._rejected_writes += 1

    # -- introspection for tests -------------------------------------------

    @property
    def rejected_writes(self) -> int:
        return self._rejected_writes
