"""Requirements-derived tests for normal operation.

Each test names the requirement it covers, so a failure points at a spec line
rather than at a line of Python.
"""

from __future__ import annotations

import pytest

from harness import protocol

pytestmark = pytest.mark.asyncio


async def test_device_connects(device):
    """REQ-01: the device advertises and accepts a connection."""
    assert await device.is_connected()


async def test_temperature_is_within_sensor_range(device):
    """REQ-02: reported temperature lies inside the sensor's rated range."""
    celsius = await device.read_temperature_c()
    assert protocol.TEMP_MIN_C <= celsius <= protocol.TEMP_MAX_C


async def test_temperature_payload_is_two_bytes(device):
    """REQ-03: temperature is transmitted as int16 centi-degrees."""
    payload = await device.read_raw(protocol.CHAR_TEMPERATURE)
    assert len(payload) == protocol.PAYLOAD_LEN


@pytest.mark.parametrize(
    "threshold_c",
    [
        pytest.param(-40.0, id="lower-bound"),
        pytest.param(0.0, id="zero"),
        pytest.param(21.5, id="typical"),
        pytest.param(99.99, id="fractional"),
        pytest.param(125.0, id="upper-bound"),
    ],
)
async def test_threshold_round_trips(device, threshold_c):
    """REQ-04: a valid threshold is stored and read back unchanged.

    The bounds are included deliberately: off-by-one errors in range checks
    live exactly there, and a naive `<` instead of `<=` would reject a legal
    setting at the edge.
    """
    await device.write_threshold_c(threshold_c)

    assert await device.read_status() is protocol.Status.OK
    assert await device.read_threshold_c() == pytest.approx(threshold_c, abs=0.01)


async def test_status_reports_ok_after_valid_write(device):
    """REQ-05: status reflects the outcome of the most recent write."""
    await device.write_threshold_c(18.0)
    assert await device.read_status() is protocol.Status.OK
