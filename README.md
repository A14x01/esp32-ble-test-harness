[![tests](https://github.com/A14x01/esp32-ble-test-harness/actions/workflows/tests.yml/badge.svg)](https://github.com/A14x01/esp32-ble-test-harness/actions/workflows/tests.yml)

# ESP32 BLE Test Harness

An automated test suite for a BLE thermostat running on an ESP32, built to
practise the kind of security-focused product testing the EU Cyber Resilience
Act pushes toward: not just *does the feature work*, but *what does the device
do when it is handed input nobody designed for*.

The same tests run against a real board over Bluetooth and against an
in-process mock, so the suite runs in CI on a machine with no radio.

```bash
pip install -r requirements.txt

pytest                      # mock device (no hardware needed)
pytest --target=hardware    # real ESP32 over BLE
```

## Why this exists

I spent 18 months as an L1 SOC analyst triaging alerts, which is mostly the
work of asking *what would this look like if it were malicious* and then
checking. This project applies the same instinct one layer down, to a device
instead of a log stream.

The happy-path tests are the easy half. The interesting file is
[`tests/test_negative.py`](tests/test_negative.py), where every case asserts
three things rather than one:

1. the malformed write is rejected with the correct status code
2. the previously stored value is unchanged
3. **the device is still alive and serving reads afterwards**

The third point is the one that catches real firmware bugs. A device that
rejects a malformed packet by crashing has still failed. Rejecting bad input
is not the same as remaining available while doing it, and only the second is
a security property.

## The device under test

A thermostat exposing three GATT characteristics:

| Characteristic | Access     | Format                              |
| -------------- | ---------- | ----------------------------------- |
| temperature    | read       | `int16` centi-degrees C, LE         |
| threshold      | read/write | `int16` centi-degrees C, LE         |
| status         | read       | `uint8`, result of last write       |

Temperatures travel as signed 16-bit centi-degrees (21.50 C becomes `2150`),
which keeps floats off the wire entirely. Valid thresholds run from -40.00 C
to 125.00 C inclusive.

`status` exists so that rejection is observable from outside the device. Without
it, a client cannot distinguish "the write was refused" from "the write was
accepted and happened to be a no-op", which makes the negative tests
unassertable.

## What the suite covers

**Happy path** — connection, encoding width, and threshold round-trips
parametrised across the range *including both boundary values*. Off-by-one
errors in range checks live exactly at the bounds, and a `<` where `<=` was
meant would reject a legal setting at the edge.

**Malformed length** — empty, truncated, overlong, and a 512-byte payload that
exceeds the default BLE MTU. The oversized case is the classic route to a
buffer overflow in a naive characteristic callback.

**Out of range** — one past each bound, plus both `int16` extremes. Firmware
that stores before it validates will accept these and misbehave much later,
far from the write that caused it.

**Validation ordering** — a 1-byte payload must report `BAD_LENGTH`, not
`OUT_OF_RANGE`. An implementation that decodes before checking length reads
past the end of the buffer to make that decision, and the status code is how we
detect the ordering from outside.

**Robustness** — 200 malformed writes back to back, then a check that the
device is still connected, still holds the correct value, and still accepts
valid input. Firmware leaking a buffer per rejected write tends to fall over
somewhere in there.

## Layout

```
firmware/thermostat_ble/    ESP32 Arduino sketch (NimBLE)
harness/
  protocol.py               UUIDs, encoding, validation rules - one source of truth
  device.py                 abstract DeviceClient + real BLE implementation
  mock_device.py            in-process fake mirroring the firmware
  logging_setup.py          one JSON object per line, per interaction
tests/
  conftest.py               fixtures, --target selection
  test_happy_path.py        requirements-derived normal operation
  test_negative.py          malformed input and robustness
```

`protocol.py` is shared by the firmware constants, the harness and the mock, so
the three cannot drift apart silently. The mock implements the firmware's
validation clause for clause, which makes a failure localisable: mock red means
the test or the shared logic is wrong; mock green plus hardware red means the
firmware is wrong.

Every device interaction emits a structured JSON log line, because a test that
fails on the bench at 2am should leave behind something readable:

```json
{"ts": "2026-09-08T14:26:56.776Z", "level": "INFO", "event": "write_threshold", "payload": "ffff", "length": 2}
{"ts": "2026-09-08T14:26:56.776Z", "level": "INFO", "event": "read_status", "status": "OUT_OF_RANGE"}
```

## Hardware

An ESP32 dev board is the only requirement. Open
`firmware/thermostat_ble/thermostat_ble.ino` in the Arduino IDE, install
**NimBLE-Arduino** from the Library Manager, select **ESP32 Dev Module**, and
flash. The sketch advertises as `ESP32-Thermostat`; the harness finds it by
name.

`readTemperatureRaw()` is a stand-in sweep rather than a sensor read — swap in
a DHT22 or DS18B20 if you have one. The tests don't care where the number comes
from.

## Known limitations

- The robustness test is a light stress case, not a real fuzzer. A proper
  version would drive random payloads through Hypothesis and track coverage.
- The mock cannot catch memory-safety bugs, since it isn't C. It verifies the
  *contract*; only a hardware run verifies the implementation.
- No notification/subscription tests yet, though the firmware supports notify
  on the temperature characteristic.
