/*  FarmIQ — ESP32 + BME680 field node
 *  ==========================================================================
 *  Measures air temperature, relative humidity and barometric pressure with a
 *  Bosch BME680 and posts them to the FarmIQ backend:
 *
 *      POST {API_BASE_URL}/api/sensor-readings/ingest
 *
 *  The values land in the same `sensor_readings` row the dashboard, the alert
 *  engine and the AI agent already read, so no backend contract changes are
 *  needed. Temperature and humidity are consumed by the decision engine and
 *  the alert rules today; pressure is stored (see
 *  supabase/migrations/0006_sensor_pressure.sql) and shown as a live context
 *  value in the agent's sensor observations.
 *
 *  ---------------------------------------------------------------------------
 *  WIRING (ESP32 DevKit, 3.3 V only — the BME680 is NOT 5 V tolerant)
 *  ---------------------------------------------------------------------------
 *      BME680 VIN/VCC  ->  3V3
 *      BME680 GND      ->  GND
 *      BME680 SDA      ->  GPIO 21
 *      BME680 SCL      ->  GPIO 22
 *      BME680 SDO      ->  GND      (selects I2C address 0x76; HIGH = 0x77)
 *
 *  Optional capacitive soil-moisture probe (enable with HAS_SOIL_PROBE 1):
 *      probe VCC       ->  3V3
 *      probe GND       ->  GND
 *      probe AOUT      ->  GPIO 34  (ADC1 — do NOT use GPIO 0/2/15/25-27)
 *
 *  ---------------------------------------------------------------------------
 *  LIBRARIES (Arduino IDE → Tools → Manage Libraries)
 *  ---------------------------------------------------------------------------
 *      "Adafruit BME680 Library"  (which pulls in Adafruit Unified Sensor)
 *
 *  Board: "ESP32 Dev Module". The ESP32 core already ships WiFi/HTTPClient.
 *
 *  ---------------------------------------------------------------------------
 *  BEFORE FLASHING — fill in the CONFIG block below
 *  ---------------------------------------------------------------------------
 *  1. Pair the node in FarmIQ (Devices → Pair). The pairing response contains
 *     the device `id` (uuid) and its `device_token`. The token is the device's
 *     password — never print it or commit it.
 *  2. Set DEVICE_ID and DEVICE_TOKEN from that response.
 *  3. Set API_BASE_URL to the LAN address of the backend. `localhost` means
 *     the ESP32 itself and will never work; use the host machine's LAN IP,
 *     e.g. "http://192.168.1.42:8001". The backend must be bound to 0.0.0.0.
 *  4. If a soil probe is wired, set SOIL_ADC_DRY / SOIL_ADC_WET from your own
 *     measurement (see the note there). Leave them at 0 to send no soil value.
 *
 *  ---------------------------------------------------------------------------
 *  DATA HONESTY
 *  ---------------------------------------------------------------------------
 *  Only values that were actually read are sent. If the sensor is missing, a
 *  reading is NaN, or a value falls outside its physical range, that field is
 *  omitted from the JSON entirely — the backend then records it as absent
 *  rather than receiving a plausible-looking placeholder. The backend stamps
 *  `created_at` itself, so the node needs no RTC or NTP.
 *  ==========================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <math.h>
#include <Adafruit_Sensor.h>
#include "Adafruit_BME680.h"

// ─────────────────────────────────────────────────────────────────────────────
// CONFIG — edit these
// ─────────────────────────────────────────────────────────────────────────────
static const char *WIFI_SSID     = "YOUR_WIFI_SSID";
static const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// LAN address of the FarmIQ backend. Never "localhost".
static const char *API_BASE_URL  = "http://192.168.1.42:8001";

// From the POST /api/devices/pair response.
static const char *DEVICE_ID     = "bf8b1489-237e-4b0f-ac65-fa40048a4e4e";
static const char *DEVICE_TOKEN  = "22EIGOZFsCd2c5A9w-VZtWjWblSAxQXBgX91IND2I3M";

// How often a reading is taken and posted.
static const uint32_t SEND_INTERVAL_MS = 5UL * 60UL * 1000UL;  // 5 minutes

// I2C pins and address. SDO tied to GND = 0x76, tied to 3V3 = 0x77.
static const int    I2C_SDA   = 21;
static const int    I2C_SCL   = 22;
static const uint8_t BME_ADDR = 0x76;

// ── Optional soil-moisture probe ─────────────────────────────────────────────
#define HAS_SOIL_PROBE 0

#if HAS_SOIL_PROBE
static const int SOIL_ADC_PIN = 34;

// Raw ESP32 ADC counts with the probe in AIR (dry) and in WATER (saturated).
// Measure them yourself: log analogRead() in air, then in a cup of water, and
// put the two numbers here. They are probe-specific, so there is no safe
// default — an uncalibrated value would be invented data. Leave both at 0 and
// the firmware sends no soil field at all.
static const int SOIL_ADC_DRY = 0;   // e.g. 3050
static const int SOIL_ADC_WET = 0;   // e.g. 1250

// FarmIQ's documented raw moisture full scale (dry 0 → saturated 2000), the
// same convention the DEMO simulator uses.
static const float FARM_RAW_FULL_SCALE = 2000.0f;
#endif

// ─────────────────────────────────────────────────────────────────────────────
// Physical ranges. Mirrors app/alerts_service.py PHYSICAL_BOUNDS: a value
// outside these cannot have come from a working sensor, so it is not sent.
// ─────────────────────────────────────────────────────────────────────────────
static const float AIR_TEMP_MIN_C  = -20.0f, AIR_TEMP_MAX_C  = 60.0f;
static const float HUMIDITY_MIN    = 0.0f,   HUMIDITY_MAX    = 100.0f;
static const float PRESSURE_MIN_HPA = 300.0f, PRESSURE_MAX_HPA = 1100.0f;

static const uint32_t HTTP_TIMEOUT_MS   = 10000;
static const uint8_t  RETRY_ATTEMPTS    = 3;
static const uint32_t RETRY_BACKOFF_MS  = 2000;

// ─────────────────────────────────────────────────────────────────────────────
// Globals
// ─────────────────────────────────────────────────────────────────────────────
static Adafruit_BME680 bme;
static WiFiClient      wifi_client;

static uint32_t last_send_ms = 0;

// ─────────────────────────────────────────────────────────────────────────────
// Wi-Fi
// ─────────────────────────────────────────────────────────────────────────────
static bool ensure_wifi(uint32_t timeout_ms = 15000) {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[wifi] connecting to \"%s\"\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }

  const uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < timeout_ms) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[wifi] connected, ip=%s rssi=%d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
    return true;
  }
  Serial.println("[wifi] not connected yet");
  return false;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sensor
// ─────────────────────────────────────────────────────────────────────────────
static bool init_sensor() {
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!bme.begin(BME_ADDR)) {
    Serial.printf("[bme680] not found at 0x%02X — check wiring and SDO\n", BME_ADDR);
    return false;
  }

  bme.setTemperatureOversampling(BME680_OS_8X);
  bme.setHumidityOversampling(BME680_OS_2X);
  bme.setPressureOversampling(BME680_OS_4X);
  bme.setIIRFilterSize(BME680_FILTER_SIZE_3);

  // A heater profile has to be configured for the library to complete a
  // reading. FarmIQ does not consume the VOC / gas value, so the shortest
  // standard profile (320 °C, 150 ms) is used to keep self-heating — and
  // therefore the air-temperature bias — as small as possible. For an
  // accurate soil temperature, use a probe in the soil instead.
  bme.setGasHeater(320, 150);

  Serial.printf("[bme680] ready at 0x%02X\n", BME_ADDR);
  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// Payload
// ─────────────────────────────────────────────────────────────────────────────
static void append_number(String &json, const char *field, float value,
                          uint8_t decimals) {
  if (isnan(value) || isinf(value)) {
    return;  // a value we did not read is never sent
  }
  char buf[40];
  snprintf(buf, sizeof(buf), ",\"%s\":%.*f", field, decimals, value);
  json += buf;
}

static String build_payload() {
  String json = String("{\"device_id\":\"") + DEVICE_ID + "\"";

  // The return value is deliberately not used as a success signal: it reports
  // false when the gas stage fails, while the temperature, humidity and
  // pressure members are still populated. Each value is range-checked
  // individually instead, and a value that fails is left out of the request.
  bme.performReading();

  const float t = bme.temperature;
  const float h = bme.humidity;
  const float p = bme.pressure / 100.0f;  // Pa -> hPa

  bool any = false;
  if (!isnan(t) && t >= AIR_TEMP_MIN_C && t <= AIR_TEMP_MAX_C) {
    append_number(json, "temperature", t, 2);
    any = true;
  } else {
    Serial.printf("[bme680] temperature rejected (%s)\n",
                  isnan(t) ? "NaN" : "out of range");
  }
  if (!isnan(h) && h >= HUMIDITY_MIN && h <= HUMIDITY_MAX) {
    append_number(json, "humidity", h, 2);
    any = true;
  } else {
    Serial.printf("[bme680] humidity rejected (%s)\n",
                  isnan(h) ? "NaN" : "out of range");
  }
  if (!isnan(p) && p >= PRESSURE_MIN_HPA && p <= PRESSURE_MAX_HPA) {
    append_number(json, "pressure", p, 2);
    any = true;
  } else {
    Serial.printf("[bme680] pressure rejected (%s)\n",
                  isnan(p) ? "NaN" : "out of range");
  }

#if HAS_SOIL_PROBE
  if (SOIL_ADC_DRY != 0 && SOIL_ADC_WET != 0 && SOIL_ADC_DRY != SOIL_ADC_WET) {
    const int adc = analogRead(SOIL_ADC_PIN);
    // A capacitive probe's ADC count rises as it dries, whereas FarmIQ's raw
    // scale rises with moisture, so dry maps to 0 and saturated to 2000.
    long raw = map(adc, SOIL_ADC_DRY, SOIL_ADC_WET, 0, (long)FARM_RAW_FULL_SCALE);
    raw = constrain(raw, 0L, (long)FARM_RAW_FULL_SCALE);
    append_number(json, "soil_moisture_raw", (float)raw, 0);
    // Same documented linear conversion the DEMO simulator applies
    // (simulator.py: soil_moisture / full_scale * 100).
    append_number(json, "soil_moisture", (float)raw * 100.0f / FARM_RAW_FULL_SCALE, 1);
    any = true;
  } else {
    Serial.println("[soil] probe uncalibrated — no soil field sent");
  }
#endif

  json += "}";
  return any ? json : String();
}

// ─────────────────────────────────────────────────────────────────────────────
// Transport
// ─────────────────────────────────────────────────────────────────────────────
static int post_reading(const String &body) {
  HTTPClient http;
  const String url = String(API_BASE_URL) + "/api/sensor-readings/ingest";

  if (!http.begin(wifi_client, url)) {
    Serial.printf("[http] could not start request to %s\n", url.c_str());
    return -1;
  }
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Id", DEVICE_ID);
  http.addHeader("Authorization", String("Bearer ") + DEVICE_TOKEN);

  const int status = http.POST(body);
  if (status > 0) {
    Serial.printf("[http] %d %s\n", status, http.getString().c_str());
  } else {
    Serial.printf("[http] transport error: %s\n", http.errorToString(status).c_str());
  }
  http.end();
  return status;
}

// The backend's device path touches `devices.last_seen_at` on every accepted
// reading, so a 401/400 is a configuration problem and a 5xx is worth
// retrying. Retries are bounded and backed off so a backend outage cannot
// turn into a request storm.
static bool send_with_retry(const String &body) {
  for (uint8_t attempt = 1; attempt <= RETRY_ATTEMPTS; attempt++) {
    const int status = post_reading(body);
    if (status == 201 || status == 200) {
      return true;
    }
    if (status == 400 || status == 401) {
      Serial.printf("[http] rejected (%d) — check DEVICE_ID / DEVICE_TOKEN\n", status);
      return false;
    }
    if (attempt < RETRY_ATTEMPTS) {
      delay(RETRY_BACKOFF_MS);
      ensure_wifi();
    }
  }
  return false;
}

// ─────────────────────────────────────────────────────────────────────────────
// Arduino entry points
// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[farmiq] ESP32 + BME680 node starting");

  init_sensor();       // logs and returns false on failure; the loop keeps
                       // retrying so a loose wire does not need a reflash
  ensure_wifi();
}

void loop() {
  if (!ensure_wifi(5000)) {
    delay(30000);
    return;
  }

  if (millis() - last_send_ms < SEND_INTERVAL_MS && last_send_ms != 0) {
    delay(1000);
    return;
  }
  last_send_ms = millis();

  if (!init_sensor()) {
    delay(30000);
    return;
  }

  const String body = build_payload();
  if (body.isEmpty()) {
    Serial.println("[farmiq] nothing readable — no request sent");
    return;
  }

  Serial.printf("[farmiq] posting %s\n", body.c_str());
  send_with_retry(body);
}
