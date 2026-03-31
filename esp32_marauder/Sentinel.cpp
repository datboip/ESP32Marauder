#include "Sentinel.h"
#include "WiFiScan.h"
#include "Buffer.h"
#include "MenuFunctions.h"
#include "Display.h"

#include <WiFi.h>
#include <esp_wifi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#ifdef HAS_BT
  #include <NimBLEDevice.h>
#endif

#ifdef HAS_SD
  #include "SD.h"
#endif

#ifdef HAS_BATTERY
  #include "BatteryInterface.h"
#endif

#ifdef HAS_GPS
  #include "GpsInterface.h"
#endif

extern WiFiScan wifi_scan_obj;
extern Buffer buffer_obj;
extern MenuFunctions menu_function_obj;
extern Display display_obj;

// Backlight control from esp32_marauder.ino
#ifdef HAS_SCREEN
  extern void backlightOn();
  extern void backlightOff();
#endif

// Scan mode constants (must match WiFiScan.h)
#define SN_SCAN_OFF        0
#define SN_SCAN_WAR_DRIVE 32

Sentinel::Sentinel() {
}

void Sentinel::begin() {
  device_id = getDeviceMAC();
  device_name = "marauder-" + device_id.substring(device_id.length() - 5);
  device_name.replace(":", "");

  config.scan_mode = "wardrive";
  config.phone_home_interval_min = 30;
  config.dead_man_timeout_hrs = 48;
  config.active = false;

  nvs.begin("sentinel", false);
  api_url = nvs.getString("api_url", "");
  api_key = nvs.getString("api_key", "");
  String saved_name = nvs.getString("dev_name", "");
  if (saved_name.length() > 0) {
    device_name = saved_name;
  }

  // Load PIN
  String saved_pin = nvs.getString("pin", "");
  if (saved_pin.length() > 0 && saved_pin.length() <= MAX_PIN_LEN) {
    strncpy(pin, saved_pin.c_str(), MAX_PIN_LEN);
    pin[MAX_PIN_LEN] = '\0';
    pin_enabled = true;
  }

  // Load wake keys
  ble_wake_mac = nvs.getString("ble_wake", "");
  wifi_wake_ssid = nvs.getString("wifi_wake", "");

  Serial.println(F("[Sentinel] Initialized"));
  Serial.print(F("[Sentinel] Device ID: "));
  Serial.println(device_id);
  Serial.print(F("[Sentinel] Device Name: "));
  Serial.println(device_name);
  if (pin_enabled) Serial.println(F("[Sentinel] PIN lock enabled"));
  if (ble_wake_mac.length() > 0) {
    Serial.print(F("[Sentinel] BLE wake MAC: "));
    Serial.println(ble_wake_mac);
  }
  if (wifi_wake_ssid.length() > 0) {
    Serial.print(F("[Sentinel] WiFi wake SSID: "));
    Serial.println(wifi_wake_ssid);
  }
}

String Sentinel::getDeviceMAC() {
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char macStr[18];
  snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  return String(macStr);
}

void Sentinel::setState(SentinelState newState) {
  state = newState;
  state_enter_time = millis();
  Serial.print(F("[Sentinel] State -> "));
  Serial.println(getStateStr());
}

const char* Sentinel::getStateStr() {
  switch (state) {
    case SENTINEL_IDLE:           return "IDLE";
    case SENTINEL_SCANNING:       return "SCANNING";
    case SENTINEL_PHONE_HOME_DUE: return "PHONE_HOME_DUE";
    case SENTINEL_CONNECTING:     return "CONNECTING";
    case SENTINEL_UPLOADING:      return "UPLOADING";
    case SENTINEL_SYNCING:        return "SYNCING";
    case SENTINEL_DISCONNECTING:  return "DISCONNECTING";
    case SENTINEL_DEADMAN_WIPE:   return "DEADMAN_WIPE";
    default:                      return "UNKNOWN";
  }
}

SentinelState Sentinel::getState() {
  return state;
}

bool Sentinel::isEnabled() {
  return enabled;
}

bool Sentinel::loadNetworks() {
  num_networks = 0;
#ifdef HAS_SD
  File f = SD.open("/networks.txt", FILE_READ);
  if (!f) {
    Serial.println(F("[Sentinel] Failed to open /networks.txt"));
    return false;
  }

  while (f.available() && num_networks < MAX_NETWORKS) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (line.length() == 0 || line.startsWith("#")) continue;

    // Format: priority,ssid,password
    int firstComma = line.indexOf(',');
    if (firstComma < 0) continue;

    int secondComma = line.indexOf(',', firstComma + 1);

    SentinelNetwork& net = networks[num_networks];
    net.priority = line.substring(0, firstComma).toInt();
    if (secondComma > 0) {
      net.ssid = line.substring(firstComma + 1, secondComma);
      net.password = line.substring(secondComma + 1);
    } else {
      net.ssid = line.substring(firstComma + 1);
      net.password = "";
    }
    net.ssid.trim();
    net.password.trim();

    if (net.ssid.length() > 0) {
      Serial.print(F("[Sentinel] Network: "));
      Serial.print(net.ssid);
      Serial.print(F(" (pri="));
      Serial.print(net.priority);
      Serial.println(F(")"));
      num_networks++;
    }
  }
  f.close();

  // Sort by priority (simple insertion sort, lowest number = highest priority)
  for (uint8_t i = 1; i < num_networks; i++) {
    SentinelNetwork tmp = networks[i];
    int j = i - 1;
    while (j >= 0 && networks[j].priority > tmp.priority) {
      networks[j + 1] = networks[j];
      j--;
    }
    networks[j + 1] = tmp;
  }

  Serial.print(F("[Sentinel] Loaded "));
  Serial.print(num_networks);
  Serial.println(F(" networks"));
  return num_networks > 0;
#else
  Serial.println(F("[Sentinel] No SD support"));
  return false;
#endif
}

int Sentinel::matchNetwork() {
  if (num_networks == 0) return -1;

  Serial.println(F("[Sentinel] Scanning for known networks..."));
  int found = WiFi.scanNetworks(false, false, false, 300);
  if (found <= 0) {
    Serial.println(F("[Sentinel] No WiFi networks found"));
    WiFi.scanDelete();
    return -1;
  }

  Serial.print(F("[Sentinel] Found "));
  Serial.print(found);
  Serial.println(F(" networks"));

  // Check each network by priority order
  for (uint8_t i = 0; i < num_networks; i++) {
    for (int j = 0; j < found; j++) {
      if (WiFi.SSID(j) == networks[i].ssid) {
        Serial.print(F("[Sentinel] Matched: "));
        Serial.println(networks[i].ssid);
        WiFi.scanDelete();
        return i;
      }
    }
  }

  Serial.println(F("[Sentinel] No known networks in range"));
  WiFi.scanDelete();
  return -1;
}

bool Sentinel::connectToNetwork(int network_index) {
  if (network_index < 0 || network_index >= num_networks) return false;

  SentinelNetwork& net = networks[network_index];
  Serial.print(F("[Sentinel] Connecting to: "));
  Serial.println(net.ssid);

  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_STA);

  if (net.password.length() > 0) {
    WiFi.begin(net.ssid.c_str(), net.password.c_str());
  } else {
    WiFi.begin(net.ssid.c_str());
  }

  uint32_t start = millis();
  uint32_t timeout = 15000;
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeout) {
    delay(250);
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("[Sentinel] Connected, IP: "));
    Serial.println(WiFi.localIP());
    return true;
  }

  Serial.println(F("[Sentinel] Connection failed"));
  WiFi.disconnect(true);
  return false;
}

void Sentinel::disconnectNetwork() {
  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_MODE_NULL);
  Serial.println(F("[Sentinel] Disconnected"));
}

void Sentinel::start() {
  if (api_url.length() == 0) {
    Serial.println(F("[Sentinel] Cannot start: no API URL configured"));
    return;
  }

  if (!loadNetworks()) {
    Serial.println(F("[Sentinel] Cannot start: no networks loaded"));
    return;
  }

  enabled = true;
  last_scan_check = millis();

  Serial.println(F("[Sentinel] Starting wardrive scan"));
  wifi_scan_obj.StartScan(SN_SCAN_WAR_DRIVE, 0x07E0);

  setState(SENTINEL_SCANNING);

  // Enter stealth mode (screen off, touch disabled)
  enterStealth();

  Serial.println(F("[Sentinel] Started"));
}

void Sentinel::stop() {
  if (!enabled) return;

  enabled = false;
  exitStealth();
  locked = false;
  wifi_scan_obj.StartScan(SN_SCAN_OFF);
  setState(SENTINEL_IDLE);
  Serial.println(F("[Sentinel] Stopped"));
}

void Sentinel::forcePhoneHome() {
  if (!enabled) {
    Serial.println(F("[Sentinel] Not enabled"));
    return;
  }
  Serial.println(F("[Sentinel] Forcing phone home"));
  setState(SENTINEL_PHONE_HOME_DUE);
}

void Sentinel::setPhoneHomeInterval(uint16_t minutes) {
  phone_home_interval_ms = (uint32_t)minutes * 60UL * 1000UL;
  config.phone_home_interval_min = minutes;
  Serial.print(F("[Sentinel] Phone home interval: "));
  Serial.print(minutes);
  Serial.println(F(" min"));
}

void Sentinel::setDeadManTimeout(uint16_t hours) {
  dead_man_timeout_ms = (uint32_t)hours * 3600UL * 1000UL;
  config.dead_man_timeout_hrs = hours;
  Serial.print(F("[Sentinel] Dead man timeout: "));
  Serial.print(hours);
  Serial.println(F(" hrs"));
}

void Sentinel::setDeviceName(String name) {
  device_name = name;
  nvs.putString("dev_name", name);
  Serial.print(F("[Sentinel] Device name: "));
  Serial.println(name);
}

void Sentinel::setApiUrl(String url) {
  api_url = url;
  nvs.putString("api_url", url);
  Serial.print(F("[Sentinel] API URL: "));
  Serial.println(url);
}

void Sentinel::setApiKey(String key) {
  api_key = key;
  nvs.putString("api_key", key);
  Serial.println(F("[Sentinel] API key updated"));
}

void Sentinel::saveLastContact() {
  uint32_t now = millis();
  nvs.putULong("last_contact", now);
}

uint32_t Sentinel::getLastContact() {
  return nvs.getULong("last_contact", 0);
}

void Sentinel::checkDeadMan(uint32_t currentTime) {
  if (dead_man_timeout_ms == 0) return;

  uint32_t lastContact = getLastContact();
  if (lastContact == 0) {
    // No contact ever recorded, save current time
    saveLastContact();
    return;
  }

  uint32_t elapsed = currentTime - lastContact;
  if (elapsed >= dead_man_timeout_ms) {
    Serial.println(F("[Sentinel] DEAD MAN SWITCH TRIGGERED"));
    setState(SENTINEL_DEADMAN_WIPE);
  }
}

void Sentinel::wipeAll() {
  Serial.println(F("[Sentinel] !!! WIPING ALL DATA !!!"));

#ifdef HAS_SD
  // Remove wardrive files
  File root = SD.open("/");
  if (root) {
    File entry = root.openNextFile();
    while (entry) {
      String name = String("/") + entry.name();
      if (name.endsWith(".csv") || name.endsWith(".log") || name.endsWith(".pcap")) {
        Serial.print(F("[Sentinel] Deleting: "));
        Serial.println(name);
        entry.close();
        SD.remove(name);
      } else {
        entry.close();
      }
      entry = root.openNextFile();
    }
    root.close();
  }
#endif

  // Clear NVS sentinel data
  nvs.clear();
  Serial.println(F("[Sentinel] Wipe complete"));

  enabled = false;
  setState(SENTINEL_IDLE);
}

// === HTTP METHODS ===

bool Sentinel::uploadFile(String filepath) {
#ifdef HAS_SD
  File f = SD.open(filepath, FILE_READ);
  if (!f) {
    Serial.print(F("[Sentinel] Failed to open: "));
    Serial.println(filepath);
    return false;
  }

  size_t fileSize = f.size();
  if (fileSize == 0) {
    f.close();
    return true;  // skip empty files
  }

  HTTPClient http;
  String url = api_url + "/api/upload";

  http.begin(url);
  http.addHeader("Content-Type", "application/octet-stream");
  http.addHeader("X-Device-Id", device_id);
  http.addHeader("X-Device-Name", device_name);
  http.addHeader("X-Filename", filepath);
  if (api_key.length() > 0)
    http.addHeader("X-API-Key", api_key);

  Serial.print(F("[Sentinel] Uploading: "));
  Serial.print(filepath);
  Serial.print(F(" ("));
  Serial.print(fileSize);
  Serial.println(F(" bytes)"));

  int httpCode = http.sendRequest("POST", &f, fileSize);
  f.close();
  http.end();

  if (httpCode == 200 || httpCode == 201) {
    Serial.println(F("[Sentinel] Upload OK"));
    return true;
  }

  Serial.print(F("[Sentinel] Upload failed, HTTP "));
  Serial.println(httpCode);
  return false;
#else
  return false;
#endif
}

bool Sentinel::uploadAllFiles() {
#ifdef HAS_SD
  bool anyUploaded = false;
  File root = SD.open("/");
  if (!root) {
    Serial.println(F("[Sentinel] Failed to open SD root"));
    return false;
  }

  // Collect filenames first (avoid modifying dir while iterating)
  String files[32];
  int fileCount = 0;

  File entry = root.openNextFile();
  while (entry && fileCount < 32) {
    String name = String("/") + entry.name();
    size_t sz = entry.size();
    entry.close();

    if (sz > 0 && (name.endsWith(".log") || name.endsWith(".gpx"))) {
      files[fileCount++] = name;
    }
    entry = root.openNextFile();
  }
  root.close();

  for (int i = 0; i < fileCount; i++) {
    if (uploadFile(files[i])) {
      String newName = files[i] + ".uploaded";
      SD.rename(files[i], newName);
      Serial.print(F("[Sentinel] Renamed to: "));
      Serial.println(newName);
      anyUploaded = true;
    }
  }

  return anyUploaded;
#else
  return false;
#endif
}

bool Sentinel::syncConfig() {
  HTTPClient http;
  String url = api_url + "/api/config/" + device_id;

  http.begin(url);
  if (api_key.length() > 0)
    http.addHeader("X-API-Key", api_key);

  int httpCode = http.GET();
  if (httpCode != 200) {
    Serial.print(F("[Sentinel] Config sync failed, HTTP "));
    Serial.println(httpCode);
    http.end();
    return false;
  }

  String payload = http.getString();
  http.end();

  DynamicJsonDocument doc(512);
  DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    Serial.print(F("[Sentinel] Config JSON error: "));
    Serial.println(err.f_str());
    return false;
  }

  if (doc.containsKey("scan_mode"))
    config.scan_mode = doc["scan_mode"].as<String>();
  if (doc.containsKey("phone_home_interval_min"))
    setPhoneHomeInterval(doc["phone_home_interval_min"].as<uint16_t>());
  if (doc.containsKey("dead_man_timeout_hrs"))
    setDeadManTimeout(doc["dead_man_timeout_hrs"].as<uint16_t>());
  if (doc.containsKey("active"))
    config.active = doc["active"].as<bool>();

  Serial.println(F("[Sentinel] Config synced"));
  return true;
}

bool Sentinel::fetchCommands() {
  HTTPClient http;
  String url = api_url + "/api/commands/" + device_id;

  http.begin(url);
  if (api_key.length() > 0)
    http.addHeader("X-API-Key", api_key);

  int httpCode = http.GET();
  if (httpCode != 200) {
    Serial.print(F("[Sentinel] Fetch commands failed, HTTP "));
    Serial.println(httpCode);
    http.end();
    return false;
  }

  String payload = http.getString();
  http.end();

  DynamicJsonDocument doc(1024);
  DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    Serial.print(F("[Sentinel] Commands JSON error: "));
    Serial.println(err.f_str());
    return false;
  }

  JsonArray arr = doc.as<JsonArray>();
  bool anyProcessed = false;

  for (JsonObject obj : arr) {
    SentinelCommand cmd;
    cmd.id = obj["id"].as<uint16_t>();
    cmd.cmd = obj["cmd"].as<String>();
    cmd.args = obj["args"].as<String>();

    executeCommand(cmd);

    // ACK the command
    HTTPClient ackHttp;
    String ackUrl = api_url + "/api/ack";
    ackHttp.begin(ackUrl);
    ackHttp.addHeader("Content-Type", "application/json");
    if (api_key.length() > 0)
      ackHttp.addHeader("X-API-Key", api_key);

    String ackBody = "{\"device_id\":\"" + device_id + "\",\"command_id\":" + String(cmd.id) + ",\"status\":\"ok\"}";
    ackHttp.POST(ackBody);
    ackHttp.end();

    anyProcessed = true;
  }

  if (anyProcessed)
    Serial.println(F("[Sentinel] Commands processed"));
  return anyProcessed;
}

bool Sentinel::sendHeartbeat() {
  HTTPClient http;
  String url = api_url + "/api/heartbeat";

  DynamicJsonDocument doc(512);
  doc["device_id"] = device_id;
  doc["device_name"] = device_name;
  doc["scan_mode"] = config.scan_mode;
  doc["uptime_sec"] = millis() / 1000;
  doc["free_heap"] = ESP.getFreeHeap();
  doc["state"] = getStateStr();

  #ifdef HAS_BATTERY
    extern BatteryInterface battery_obj;
    doc["battery_pct"] = battery_obj.getBatteryLevel();
  #endif

  #ifdef HAS_GPS
    extern GpsInterface gps_obj;
    if (gps_obj.getFixStatus()) {
      doc["lat"] = gps_obj.getLat();
      doc["lon"] = gps_obj.getLon();
    }
  #endif

  String body;
  serializeJson(doc, body);

  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  if (api_key.length() > 0)
    http.addHeader("X-API-Key", api_key);

  int httpCode = http.POST(body);
  http.end();

  if (httpCode == 200) {
    Serial.println(F("[Sentinel] Heartbeat sent"));
    return true;
  }
  Serial.print(F("[Sentinel] Heartbeat failed, HTTP "));
  Serial.println(httpCode);
  return false;
}

void Sentinel::executeCommand(SentinelCommand& cmd) {
  Serial.print(F("[Sentinel] Execute command: "));
  Serial.println(cmd.cmd);

  if (cmd.cmd == "reboot") {
    Serial.println(F("[Sentinel] Rebooting..."));
    ESP.restart();
  } else if (cmd.cmd == "clear_sd") {
#ifdef HAS_SD
    File root = SD.open("/");
    if (root) {
      File entry = root.openNextFile();
      while (entry) {
        String name = String("/") + entry.name();
        entry.close();
        if (name.endsWith(".log") || name.endsWith(".uploaded") || name.endsWith(".gpx")) {
          Serial.print(F("[Sentinel] Deleting: "));
          Serial.println(name);
          SD.remove(name);
        }
        entry = root.openNextFile();
      }
      root.close();
    }
#endif
  } else if (cmd.cmd == "wipe") {
    wipeAll();
  } else if (cmd.cmd == "switch_mode") {
    config.scan_mode = cmd.args;
    Serial.print(F("[Sentinel] Mode switched to: "));
    Serial.println(cmd.args);
  } else {
    Serial.print(F("[Sentinel] Unknown command: "));
    Serial.println(cmd.cmd);
  }
}

// === LOCK & STEALTH ===

void Sentinel::setPIN(const char* newPIN) {
  if (strlen(newPIN) == 0 || strlen(newPIN) > MAX_PIN_LEN) {
    Serial.println(F("[Sentinel] PIN must be 1-8 digits"));
    return;
  }
  strncpy(pin, newPIN, MAX_PIN_LEN);
  pin[MAX_PIN_LEN] = '\0';
  pin_enabled = true;
  nvs.putString("pin", String(pin));
  Serial.println(F("[Sentinel] PIN set"));
}

void Sentinel::clearPIN() {
  memset(pin, 0, sizeof(pin));
  pin_enabled = false;
  nvs.remove("pin");
  Serial.println(F("[Sentinel] PIN cleared"));
}

void Sentinel::setBLEWakeMAC(const String& mac) {
  ble_wake_mac = mac;
  ble_wake_mac.toUpperCase();
  nvs.putString("ble_wake", ble_wake_mac);
  Serial.print(F("[Sentinel] BLE wake MAC: "));
  Serial.println(ble_wake_mac);
}

void Sentinel::setWiFiWakeSSID(const String& ssid) {
  wifi_wake_ssid = ssid;
  nvs.putString("wifi_wake", wifi_wake_ssid);
  Serial.print(F("[Sentinel] WiFi wake SSID: "));
  Serial.println(wifi_wake_ssid);
}

bool Sentinel::isLocked() {
  return locked;
}

bool Sentinel::isStealth() {
  return stealth_active;
}

void Sentinel::enterStealth() {
  if (stealth_active) return;
  stealth_active = true;
  locked = true;

  #ifdef HAS_SCREEN
    backlightOff();
  #endif

  #ifdef HAS_ILI9341
    menu_function_obj.disable_touch = true;
  #endif

  Serial.println(F("[Sentinel] Stealth mode ON"));
}

void Sentinel::exitStealth() {
  if (!stealth_active) return;
  stealth_active = false;

  #ifdef HAS_SCREEN
    backlightOn();
  #endif

  #ifdef HAS_ILI9341
    menu_function_obj.disable_touch = false;
  #endif

  Serial.println(F("[Sentinel] Stealth mode OFF"));
}

void Sentinel::unlock() {
  if (!locked) return;

  if (pin_enabled) {
    #ifdef HAS_ILI9341
      // Temporarily enable touch for PIN entry
      menu_function_obj.disable_touch = false;
      backlightOn();
      if (!showPINScreen()) {
        // Wrong PIN, go back to stealth
        if (stealth_active) {
          menu_function_obj.disable_touch = true;
          backlightOff();
        }
        return;
      }
    #else
      Serial.println(F("[Sentinel] No screen for PIN entry, use 'sentinel -unlock <pin>' via serial"));
      return;
    #endif
  }

  locked = false;
  exitStealth();
  Serial.println(F("[Sentinel] Unlocked"));
}

void Sentinel::drawPINKeypad(uint8_t entered) {
  #ifdef HAS_ILI9341
    TFT_eSPI& tft = display_obj.tft;
    const uint16_t W = TFT_WIDTH;

    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(0x07FF, TFT_BLACK);
    tft.drawCentreString("ENTER PIN", W / 2, 10, 2);

    // Show dots for entered digits
    for (uint8_t i = 0; i < MAX_PIN_LEN; i++) {
      int dotX = W / 2 - (MAX_PIN_LEN * 12) / 2 + i * 12 + 6;
      if (i < entered)
        tft.fillCircle(dotX, 40, 4, 0x07FF);
      else
        tft.drawCircle(dotX, 4, 4, 0x39E7);
    }

    // 3x3 grid for digits 1-9, plus 0 and OK
    const uint8_t btnW = 60;
    const uint8_t btnH = 40;
    const uint8_t gap = 8;
    const uint16_t gridX = (W - 3 * btnW - 2 * gap) / 2;
    const uint16_t gridY = 60;

    for (int i = 0; i < 9; i++) {
      int col = i % 3;
      int row = i / 3;
      uint16_t bx = gridX + col * (btnW + gap);
      uint16_t by = gridY + row * (btnH + gap);
      tft.drawRect(bx, by, btnW, btnH, 0x07FF);
      tft.setTextColor(TFT_WHITE, TFT_BLACK);
      tft.drawCentreString(String(i + 1), bx + btnW / 2, by + btnH / 2 - 7, 2);
    }

    // Bottom row: CLR, 0, OK
    uint16_t bottomY = gridY + 3 * (btnH + gap);
    tft.drawRect(gridX, bottomY, btnW, btnH, TFT_RED);
    tft.setTextColor(TFT_RED, TFT_BLACK);
    tft.drawCentreString("CLR", gridX + btnW / 2, bottomY + btnH / 2 - 7, 2);

    tft.drawRect(gridX + btnW + gap, bottomY, btnW, btnH, 0x07FF);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.drawCentreString("0", gridX + btnW + gap + btnW / 2, bottomY + btnH / 2 - 7, 2);

    tft.drawRect(gridX + 2 * (btnW + gap), bottomY, btnW, btnH, TFT_GREEN);
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.drawCentreString("OK", gridX + 2 * (btnW + gap) + btnW / 2, bottomY + btnH / 2 - 7, 2);
  #endif
}

bool Sentinel::showPINScreen() {
  #ifdef HAS_ILI9341
    char entered[MAX_PIN_LEN + 1] = {0};
    uint8_t pos = 0;
    uint8_t attempts = 0;
    const uint8_t MAX_ATTEMPTS = 5;

    const uint8_t btnW = 60;
    const uint8_t btnH = 40;
    const uint8_t gap = 8;
    const uint16_t gridX = (TFT_WIDTH - 3 * btnW - 2 * gap) / 2;
    const uint16_t gridY = 60;

    drawPINKeypad(0);

    while (attempts < MAX_ATTEMPTS) {
      uint16_t tx, ty;
      if (display_obj.updateTouch(&tx, &ty)) {
        // Debounce
        delay(150);
        while (display_obj.updateTouch(&tx, &ty)) delay(10);

        // Check which button was pressed
        int digit = -1;
        bool clearPressed = false;
        bool okPressed = false;

        // Check 1-9 grid
        for (int i = 0; i < 9; i++) {
          int col = i % 3;
          int row = i / 3;
          uint16_t bx = gridX + col * (btnW + gap);
          uint16_t by = gridY + row * (btnH + gap);
          if (tx >= bx && tx < bx + btnW && ty >= by && ty < by + btnH) {
            digit = i + 1;
            break;
          }
        }

        // Check bottom row
        uint16_t bottomY = gridY + 3 * (btnH + gap);
        if (ty >= bottomY && ty < bottomY + btnH) {
          if (tx >= gridX && tx < gridX + btnW) clearPressed = true;
          else if (tx >= gridX + btnW + gap && tx < gridX + 2 * btnW + gap) digit = 0;
          else if (tx >= gridX + 2 * (btnW + gap) && tx < gridX + 3 * btnW + 2 * gap) okPressed = true;
        }

        if (digit >= 0 && pos < MAX_PIN_LEN) {
          entered[pos++] = '0' + digit;
          entered[pos] = '\0';
          drawPINKeypad(pos);
        } else if (clearPressed) {
          pos = 0;
          memset(entered, 0, sizeof(entered));
          drawPINKeypad(0);
        } else if (okPressed && pos > 0) {
          if (strcmp(entered, pin) == 0) {
            display_obj.tft.fillScreen(TFT_BLACK);
            display_obj.tft.setTextColor(TFT_GREEN, TFT_BLACK);
            display_obj.tft.drawCentreString("UNLOCKED", TFT_WIDTH / 2, TFT_HEIGHT / 2 - 7, 2);
            delay(500);
            return true;
          } else {
            attempts++;
            pos = 0;
            memset(entered, 0, sizeof(entered));
            display_obj.tft.fillScreen(TFT_BLACK);
            display_obj.tft.setTextColor(TFT_RED, TFT_BLACK);
            String msg = "WRONG (" + String(MAX_ATTEMPTS - attempts) + " left)";
            display_obj.tft.drawCentreString(msg, TFT_WIDTH / 2, TFT_HEIGHT / 2 - 7, 2);
            delay(1000);
            if (attempts < MAX_ATTEMPTS) drawPINKeypad(0);
          }
        }
      }
      delay(20);
    }

    // Max attempts exceeded
    display_obj.tft.fillScreen(TFT_BLACK);
    display_obj.tft.setTextColor(TFT_RED, TFT_BLACK);
    display_obj.tft.drawCentreString("LOCKED OUT", TFT_WIDTH / 2, TFT_HEIGHT / 2 - 7, 2);
    delay(2000);
    return false;
  #else
    return false;
  #endif
}

bool Sentinel::bleScanForMAC(const String& targetMAC) {
  #ifdef HAS_BT
    NimBLEDevice::init("");
    NimBLEScan* pScan = NimBLEDevice::getScan();
    pScan->setActiveScan(false);
    pScan->start(BLE_WAKE_SCAN_DURATION_SEC);
    NimBLEScanResults results = pScan->getResults();
    bool found = false;

    for (int i = 0; i < results.getCount(); i++) {
      const NimBLEAdvertisedDevice* dev = results.getDevice(i);
      String addr = String(dev->getAddress().toString().c_str());
      addr.toUpperCase();
      if (addr == targetMAC) {
        found = true;
        break;
      }
    }

    pScan->clearResults();
    NimBLEDevice::deinit();
    return found;
  #else
    return false;
  #endif
}

bool Sentinel::wifiScanForSSID(const String& targetSSID) {
  int found = WiFi.scanNetworks(false, false, false, 300);
  bool matched = false;
  for (int i = 0; i < found; i++) {
    if (WiFi.SSID(i) == targetSSID) {
      matched = true;
      break;
    }
  }
  WiFi.scanDelete();
  return matched;
}

void Sentinel::checkProximityWake(uint32_t currentTime) {
  if (!stealth_active || !locked) return;
  if (ble_wake_mac.length() == 0 && wifi_wake_ssid.length() == 0) return;

  if (currentTime - last_ble_wake_check < BLE_WAKE_SCAN_INTERVAL_MS) return;
  last_ble_wake_check = currentTime;

  bool wakeUp = false;

  // Check BLE proximity (only when not actively WiFi scanning)
  if (ble_wake_mac.length() > 0 && state == SENTINEL_SCANNING) {
    // Pause WiFi scan briefly for BLE
    wifi_scan_obj.StartScan(SN_SCAN_OFF);
    delay(100);
    wakeUp = bleScanForMAC(ble_wake_mac);
    if (!wakeUp) {
      // Resume wardrive
      wifi_scan_obj.StartScan(SN_SCAN_WAR_DRIVE, 0x07E0);
    }
  }

  // Check WiFi SSID (uses quick WiFi scan — only when paused anyway)
  if (!wakeUp && wifi_wake_ssid.length() > 0 && state == SENTINEL_SCANNING) {
    wifi_scan_obj.StartScan(SN_SCAN_OFF);
    delay(100);
    wakeUp = wifiScanForSSID(wifi_wake_ssid);
    if (!wakeUp) {
      wifi_scan_obj.StartScan(SN_SCAN_WAR_DRIVE, 0x07E0);
    }
  }

  if (wakeUp) {
    Serial.println(F("[Sentinel] Proximity device detected — waking up"));
    wake_triggered = true;
    unlock();  // Shows PIN screen if PIN set, otherwise just unlocks
    // Resume scan after unlock attempt
    if (stealth_active) {
      wifi_scan_obj.StartScan(SN_SCAN_WAR_DRIVE, 0x07E0);
    }
  }
}

// === STATE MACHINE ===

void Sentinel::main(uint32_t currentTime) {
  if (!enabled) return;

  // Proximity wake check runs even while scanning
  if (stealth_active) {
    checkProximityWake(currentTime);
  }

  switch (state) {
    case SENTINEL_SCANNING: {
      // Check if it's time to phone home
      uint32_t elapsed = currentTime - last_scan_check;
      if (elapsed >= phone_home_interval_ms) {
        Serial.println(F("[Sentinel] Phone home interval reached"));
        setState(SENTINEL_PHONE_HOME_DUE);
      }
      // Check dead man switch periodically
      checkDeadMan(currentTime);
      break;
    }

    case SENTINEL_PHONE_HOME_DUE: {
      // Stop current scan
      Serial.println(F("[Sentinel] Stopping scan for phone home"));
      wifi_scan_obj.StartScan(SN_SCAN_OFF);
      delay(500);

      // Try to find and connect to a known network
      int netIdx = matchNetwork();
      if (netIdx >= 0) {
        if (connectToNetwork(netIdx)) {
          setState(SENTINEL_UPLOADING);
        } else {
          // Connection failed, resume scanning
          Serial.println(F("[Sentinel] Connect failed, resuming scan"));
          wifi_scan_obj.StartScan(SN_SCAN_WAR_DRIVE, 0x07E0);
          last_scan_check = millis();
          setState(SENTINEL_SCANNING);
        }
      } else {
        // No network found, resume scanning
        Serial.println(F("[Sentinel] No network found, resuming scan"));
        wifi_scan_obj.StartScan(SN_SCAN_WAR_DRIVE, 0x07E0);
        last_scan_check = millis();
        setState(SENTINEL_SCANNING);
      }
      break;
    }

    case SENTINEL_UPLOADING: {
      sendHeartbeat();
      bool uploaded = uploadAllFiles();
      if (uploaded) {
        Serial.println(F("[Sentinel] Upload complete"));
      } else {
        Serial.println(F("[Sentinel] Upload failed (stub)"));
      }
      setState(SENTINEL_SYNCING);
      break;
    }

    case SENTINEL_SYNCING: {
      sendHeartbeat();
      syncConfig();
      fetchCommands();
      saveLastContact();
      setState(SENTINEL_DISCONNECTING);
      break;
    }

    case SENTINEL_DISCONNECTING: {
      disconnectNetwork();
      delay(500);

      // Resume scanning
      Serial.println(F("[Sentinel] Resuming wardrive scan"));
      wifi_scan_obj.StartScan(SN_SCAN_WAR_DRIVE, 0x07E0);
      last_scan_check = millis();
      setState(SENTINEL_SCANNING);
      break;
    }

    case SENTINEL_DEADMAN_WIPE: {
      wipeAll();
      break;
    }

    case SENTINEL_IDLE:
    default:
      break;
  }
}

void Sentinel::printStatus() {
  Serial.println(F("[Sentinel] === Status ==="));
  Serial.print(F("  Enabled:    "));
  Serial.println(enabled ? F("YES") : F("NO"));
  Serial.print(F("  State:      "));
  Serial.println(getStateStr());
  Serial.print(F("  Device ID:  "));
  Serial.println(device_id);
  Serial.print(F("  Dev Name:   "));
  Serial.println(device_name);
  Serial.print(F("  API URL:    "));
  Serial.println(api_url.length() > 0 ? api_url : F("(not set)"));
  Serial.print(F("  API Key:    "));
  Serial.println(api_key.length() > 0 ? F("(set)") : F("(not set)"));
  Serial.print(F("  Phone Home: "));
  Serial.print(phone_home_interval_ms / 60000);
  Serial.println(F(" min"));
  Serial.print(F("  Dead Man:   "));
  Serial.print(dead_man_timeout_ms / 3600000);
  Serial.println(F(" hrs"));
  Serial.print(F("  Networks:   "));
  Serial.println(num_networks);
  for (uint8_t i = 0; i < num_networks; i++) {
    Serial.print(F("    ["));
    Serial.print(networks[i].priority);
    Serial.print(F("] "));
    Serial.println(networks[i].ssid);
  }
  Serial.print(F("  PIN Lock:   "));
  Serial.println(pin_enabled ? F("ON") : F("OFF"));
  Serial.print(F("  Stealth:    "));
  Serial.println(stealth_active ? F("ON") : F("OFF"));
  Serial.print(F("  Locked:     "));
  Serial.println(locked ? F("YES") : F("NO"));
  if (ble_wake_mac.length() > 0) {
    Serial.print(F("  BLE Wake:   "));
    Serial.println(ble_wake_mac);
  }
  if (wifi_wake_ssid.length() > 0) {
    Serial.print(F("  WiFi Wake:  "));
    Serial.println(wifi_wake_ssid);
  }
#ifdef HAS_GPS
  Serial.println(F("  GPS:        available"));
#else
  Serial.println(F("  GPS:        not available"));
#endif
#ifdef HAS_BATTERY
  Serial.println(F("  Battery:    available"));
#else
  Serial.println(F("  Battery:    not available"));
#endif
}
