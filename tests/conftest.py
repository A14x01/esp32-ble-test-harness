"""Fixtures and target selection.

    pytest                    # mock device (default, no hardware needed)
    pytest --target=hardware  # real ESP32 over BLE

The same test bodies run against both.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from harness import BleDeviceClient, MockDeviceClient
from harness.logging_setup import log_event


def pytest_addoption(parser):
    parser.addoption(
        "--target",
        action="store",
        default="mock",
        choices=("mock", "hardware"),
        help="run against the in-process mock or a real ESP32 over BLE",
    )


@pytest.fixture(scope="session")
def target(request) -> str:
    return request.config.getoption("--target")


@pytest_asyncio.fixture
async def device(target):
    """A connected device, torn down after each test."""
    client = BleDeviceClient() if target == "hardware" else MockDeviceClient()

    log_event("test_setup", target=target)
    await client.connect()
    try:
        yield client
    finally:
        await client.disconnect()
        log_event("test_teardown", target=target)
