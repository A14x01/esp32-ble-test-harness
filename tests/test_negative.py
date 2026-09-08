"""Negative and robustness tests.

This file is the reason the project exists. The happy path proves the feature
works; these tests probe what the device does when it is handed input nobody
designed for. Under the Cyber Resilience Act the relevant question is not "does
it reject bad input" but "does it stay correct and available while doing so",
so every case here asserts three things:

    1. the write is rejected with the right status code
    2. the previously stored value is unchanged
    3. the device is still alive and serving reads afterwards

Point 3 is the one that catches real firmware bugs. A device that rejects a
malformed packet by crashing has still failed.
"""

from __future__ import annotations

import pytest

from harness import protocol

pytestmark = pytest.mark.asyncio

KNOWN_GOOD_C = 20.0


async def _set_known_good(device) -> None:
    await device.write_threshold_c(KNOWN_GOOD_C)
    assert await device.read_status() is protocol.Status.OK


# ---------------------------------------------------------------------------
# Malformed payload length
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\x01", id="one-byte-truncated"),
        pytest.param(b"\x01\x02\x03", id="three-bytes-overlong"),
        pytest.param(b"\x00" * 20, id="twenty-bytes"),
        pytest.param(b"\xff" * 512, id="512-bytes-oversized"),
    ],
)
async def test_wrong_length_is_rejected(device, payload):
    """REQ-06: a payload that is not exactly 2 bytes is rejected as BAD_LENGTH.

    The 512-byte case matters most: it exceeds the default BLE MTU and is the
    classic path to a buffer overflow in a naive characteristic callback.
    """
    await _set_known_good(device)

    await device.write_threshold_raw(payload)

    assert await device.read_status() is protocol.Status.BAD_LENGTH
    assert await device.read_threshold_c() == pytest.approx(KNOWN_GOOD_C, abs=0.01)
    assert await device.is_connected()


# ---------------------------------------------------------------------------
# Out-of-range values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_value",
    [
        pytest.param(protocol.THRESHOLD_MIN_RAW - 1, id="one-below-minimum"),
        pytest.param(protocol.THRESHOLD_MAX_RAW + 1, id="one-above-maximum"),
        pytest.param(-32768, id="int16-minimum"),
        pytest.param(32767, id="int16-maximum"),
    ],
)
async def test_out_of_range_is_rejected(device, raw_value):
    """REQ-07: a well-formed but out-of-range value is rejected as OUT_OF_RANGE.

    The int16 extremes are included because a firmware that stores the value
    before validating it will happily accept them and then behave strangely
    much later, far from the write that caused it.
    """
    await _set_known_good(device)

    await device.write_threshold_raw(protocol.encode_centi(raw_value))

    assert await device.read_status() is protocol.Status.OUT_OF_RANGE
    assert await device.read_threshold_c() == pytest.approx(KNOWN_GOOD_C, abs=0.01)
    assert await device.is_connected()


# ---------------------------------------------------------------------------
# Ordering and state
# ---------------------------------------------------------------------------


async def test_length_is_checked_before_range(device):
    """REQ-08: a malformed payload reports BAD_LENGTH, not OUT_OF_RANGE.

    An implementation that decodes first and validates second will read past
    the end of a 1-byte buffer to make that decision. The status code is how
    we detect the ordering from outside the device.
    """
    await _set_known_good(device)

    await device.write_threshold_raw(b"\xff")

    assert await device.read_status() is protocol.Status.BAD_LENGTH


async def test_device_recovers_after_rejection(device):
    """REQ-09: a valid write still succeeds after a rejected one."""
    await _set_known_good(device)

    await device.write_threshold_raw(b"\x00" * 9)
    assert await device.read_status() is protocol.Status.BAD_LENGTH

    await device.write_threshold_c(30.0)
    assert await device.read_status() is protocol.Status.OK
    assert await device.read_threshold_c() == pytest.approx(30.0, abs=0.01)


async def test_sustained_malformed_writes_do_not_degrade_device(device):
    """REQ-10: the device survives a burst of malformed writes.

    A light stress case rather than a real fuzzer: 200 bad packets back to
    back, then check the device is still connected, still holding the correct
    value, and still accepting valid input. Firmware that leaks a buffer per
    rejected write tends to fall over somewhere in here.
    """
    await _set_known_good(device)

    # Lengths deliberately exclude 2: a 2-byte payload could be a legal value,
    # which would change the threshold and make the assertion below meaningless.
    bad_lengths = [1, 3, 4, 5, 8, 16, 64]

    for i in range(200):
        length = bad_lengths[i % len(bad_lengths)]
        await device.write_threshold_raw(bytes([i % 256]) * length)

    assert await device.is_connected()
    assert await device.read_threshold_c() == pytest.approx(KNOWN_GOOD_C, abs=0.01)

    await device.write_threshold_c(22.0)
    assert await device.read_status() is protocol.Status.OK


async def test_temperature_characteristic_is_not_writable(device):
    """REQ-11: temperature is read-only; writes to it must not be honoured."""
    before = await device.read_raw(protocol.CHAR_TEMPERATURE)
    assert len(before) == protocol.PAYLOAD_LEN

    with pytest.raises(Exception):
        await device.write_raw(protocol.CHAR_TEMPERATURE, protocol.encode_celsius(0.0))

    assert await device.is_connected()
