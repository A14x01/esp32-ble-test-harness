/*
 * ESP32 BLE thermostat - device under test.
 *
 * Exposes three characteristics:
 *   temperature (read)        int16, centi-degrees C, little-endian
 *   threshold   (read/write)  int16, centi-degrees C, little-endian
 *   status      (read)        uint8, result of the most recent threshold write
 *
 * The validation in onWrite() is the behaviour the test suite exercises.
 * Length is checked before the value is decoded, deliberately: decoding a
 * 1-byte payload as int16 reads one byte past the end of the buffer.
 *
 * Board: ESP32 Dev Module. Library: NimBLE-Arduino (Library Manager).
 */

#include <NimBLEDevice.h>

// --- Protocol constants: must match harness/protocol.py ---------------------

#define SERVICE_UUID      "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define CHAR_TEMPERATURE  "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define CHAR_THRESHOLD    "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
#define CHAR_STATUS       "6e400004-b5a3-f393-e0a9-e50e24dcca9e"

#define DEVICE_NAME       "ESP32-Thermostat"

static const int16_t THRESHOLD_MIN_RAW = -4000;   // -40.00 C
static const int16_t THRESHOLD_MAX_RAW = 12500;   // 125.00 C
static const size_t  PAYLOAD_LEN       = 2;

enum Status : uint8_t {
  STATUS_OK           = 0,
  STATUS_BAD_LENGTH   = 1,
  STATUS_OUT_OF_RANGE = 2
};

// --- Device state ----------------------------------------------------------

static int16_t g_thresholdRaw = 2500;   // 25.00 C default
static uint8_t g_status       = STATUS_OK;

static NimBLECharacteristic* g_temperatureChar = nullptr;
static NimBLECharacteristic* g_thresholdChar   = nullptr;
static NimBLECharacteristic* g_statusChar      = nullptr;

// --- Threshold write handling ---------------------------------------------

class ThresholdCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic) override {
    std::string value = characteristic->getValue();

    // 1. Length first. Anything other than exactly 2 bytes is a protocol
    //    error, and we must not decode it.
    if (value.length() != PAYLOAD_LEN) {
      g_status = STATUS_BAD_LENGTH;
      g_statusChar->setValue(&g_status, 1);
      // Restore the stored value so a read-back after a bad write shows the
      // old setting rather than whatever the client sent.
      characteristic->setValue((uint8_t*)&g_thresholdRaw, sizeof(g_thresholdRaw));
      return;
    }

    // 2. Decode only now that the length is known good.
    int16_t candidate;
    memcpy(&candidate, value.data(), sizeof(candidate));

    // 3. Range check, inclusive at both bounds.
    if (candidate < THRESHOLD_MIN_RAW || candidate > THRESHOLD_MAX_RAW) {
      g_status = STATUS_OUT_OF_RANGE;
      g_statusChar->setValue(&g_status, 1);
      characteristic->setValue((uint8_t*)&g_thresholdRaw, sizeof(g_thresholdRaw));
      return;
    }

    // 4. Accept. Commit only after every check has passed.
    g_thresholdRaw = candidate;
    g_status = STATUS_OK;
    g_statusChar->setValue(&g_status, 1);
    characteristic->setValue((uint8_t*)&g_thresholdRaw, sizeof(g_thresholdRaw));
  }
};

// --- Temperature source ----------------------------------------------------

static int16_t readTemperatureRaw() {
  // Stand-in for a real sensor: a slow sweep around 21 C so the value moves
  // between reads. Replace with your DHT/DS18B20/internal sensor read.
  static int16_t t = 2100;
  static int16_t direction = 10;

  t += direction;
  if (t > 2400 || t < 1800) direction = -direction;
  return t;
}

// --- Setup / loop ----------------------------------------------------------

void setup() {
  Serial.begin(115200);
  Serial.println("Starting BLE thermostat");

  NimBLEDevice::init(DEVICE_NAME);
  NimBLEServer* server = NimBLEDevice::createServer();
  NimBLEService* service = server->createService(SERVICE_UUID);

  g_temperatureChar = service->createCharacteristic(
      CHAR_TEMPERATURE, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);

  g_thresholdChar = service->createCharacteristic(
      CHAR_THRESHOLD, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE);
  g_thresholdChar->setCallbacks(new ThresholdCallbacks());
  g_thresholdChar->setValue((uint8_t*)&g_thresholdRaw, sizeof(g_thresholdRaw));

  g_statusChar = service->createCharacteristic(
      CHAR_STATUS, NIMBLE_PROPERTY::READ);
  g_statusChar->setValue(&g_status, 1);

  service->start();

  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setName(DEVICE_NAME);
  advertising->start();

  Serial.println("Advertising as " DEVICE_NAME);
}

void loop() {
  int16_t t = readTemperatureRaw();
  g_temperatureChar->setValue((uint8_t*)&t, sizeof(t));
  g_temperatureChar->notify();
  delay(1000);
}
