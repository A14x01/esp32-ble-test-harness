"""Wire protocol for the BLE thermostat device.

This module is the single source of truth for UUIDs, encoding and the
validation rules the firmware enforces. The mock device implements the same
rules, so a test that passes against the mock is a meaningful statement about
the real firmware.
"""

from __future__ import annotations

import struct
from enum import IntEnum

# ---------------------------------------------------------------------------
# GATT identifiers
# ---------------------------------------------------------------------------

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"

CHAR_TEMPERATURE = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # read/notify, int16
CHAR_THRESHOLD = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"    # read/write,  int16
CHAR_STATUS = "6e400004-b5a3-f393-e0a9-e50e24dcca9e"       # read,        uint8

DEVICE_NAME = "ESP32-Thermostat"

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
# Temperatures travel as signed 16-bit centi-degrees Celsius, little-endian.
# 21.50 C -> 2150. This avoids floats on the wire entirely.

CENTI = 100

TEMP_MIN_C = -40.0
TEMP_MAX_C = 125.0

THRESHOLD_MIN_RAW = int(TEMP_MIN_C * CENTI)   # -4000
THRESHOLD_MAX_RAW = int(TEMP_MAX_C * CENTI)   # 12500

PAYLOAD_LEN = 2  # bytes; any other length is a protocol error


class Status(IntEnum):
    """Result of the most recent write to CHAR_THRESHOLD."""

    OK = 0
    BAD_LENGTH = 1
    OUT_OF_RANGE = 2


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def encode_centi(value_raw: int) -> bytes:
    """Encode a raw centi-degree integer as the 2-byte wire payload."""
    return struct.pack("<h", value_raw)


def decode_centi(payload: bytes) -> int:
    """Decode a 2-byte wire payload into raw centi-degrees."""
    if len(payload) != PAYLOAD_LEN:
        raise ValueError(f"expected {PAYLOAD_LEN} bytes, got {len(payload)}")
    return struct.unpack("<h", payload)[0]


def celsius_to_raw(celsius: float) -> int:
    return round(celsius * CENTI)


def raw_to_celsius(raw: int) -> float:
    return raw / CENTI


def encode_celsius(celsius: float) -> bytes:
    return encode_centi(celsius_to_raw(celsius))


# ---------------------------------------------------------------------------
# Validation — mirrors the firmware exactly
# ---------------------------------------------------------------------------


def classify_write(payload: bytes) -> Status:
    """Return the Status the firmware will report for this payload.

    Length is checked before range, because a payload of the wrong length
    cannot be decoded into a value at all.
    """
    if len(payload) != PAYLOAD_LEN:
        return Status.BAD_LENGTH

    raw = struct.unpack("<h", payload)[0]
    if raw < THRESHOLD_MIN_RAW or raw > THRESHOLD_MAX_RAW:
        return Status.OUT_OF_RANGE

    return Status.OK
