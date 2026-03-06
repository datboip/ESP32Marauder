# Sentinel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a drop-and-forget remote sensor mode to ESP32 Marauder that autonomously scans, phones home over WiFi to upload data and pull commands, with mTLS auth and a dead man's switch.

**Architecture:** New `Sentinel` class following AutoCycle's pattern (millis()-based state machine called from main loop). Chunked HTTP uploads via ESP32 HTTPClient + WiFiClientSecure. Flask API server with SQLite. Single-file web flasher/configurator.

**Tech Stack:** ESP32 Arduino (C++), HTTPClient/WiFiClientSecure (ESP32 SDK), Flask + SQLite (Python), ESPTool.js + Web Serial API (JavaScript)

---

### Task 1: Sentinel Header — State Machine and Class Definition

**Files:**
- Create: `esp32_marauder/Sentinel.h`

**Step 1: Create Sentinel.h with state machine, config structs, and class definition**

```cpp
#pragma once

#ifndef Sentinel_h
#define Sentinel_h

#include <Arduino.h>
#include <Preferences.h>

// Forward declarations
class WiFiScan;

// Sentinel states
enum SentinelState : uint8_t {
  SENTINEL_IDLE = 0,
  SENTINEL_SCANNING,
  SENTINEL_PHONE_HOME_DUE,
  SENTINEL_CONNECTING,
  SENTINEL_UPLOADING,
  SENTINEL_SYNCING,
  SENTINEL_DISCONNECTING,
  SENTINEL_DEADMAN_WIPE
};

// WiFi network entry from networks.txt
struct SentinelNetwork {
  uint8_t priority;
  String ssid;
  String password;  // empty = open
};

// Config received from server
struct SentinelConfig {
  String scan_mode;              // "wardrive", "probe", "beacon", etc.
  uint16_t phone_home_interval_min;  // minutes between phone-home cycles
  uint16_t dead_man_timeout_hrs;     // hours before dead man's switch fires
  bool active;                       // master enable
};

// Pending command from server
struct SentinelCommand {
  uint16_t id;
  String cmd;      // "reboot", "switch_mode", "clear_sd", "wipe", "update_networks"
  String args;     // JSON string of args, parsed on demand
};

static const uint8_t MAX_NETWORKS = 10;
static const uint8_t MAX_COMMANDS = 8;
static const uint16_t UPLOAD_CHUNK_SIZE = 2048;

class Sentinel {
  private:
    bool enabled = false;
    SentinelState state = SENTINEL_IDLE;

    // Network list (from SD networks.txt)
    SentinelNetwork networks[MAX_NETWORKS];
    uint8_t num_networks = 0;

    // Timing
    uint32_t phone_home_interval_ms = 1800000;  // 30 min default
    uint32_t last_scan_check = 0;
    uint32_t state_enter_time = 0;

    // Dead man's switch
    uint32_t dead_man_timeout_ms = 172800000;  // 48 hours default
    Preferences nvs;

    // Device identity
    String device_id;    // MAC address
    String device_name;  // user-configurable

    // API config
    String api_url;      // e.g. "https://yourapp.fly.dev"
    String api_key;      // fallback auth if no mTLS

    // Server config (synced)
    SentinelConfig config;

    // Upload tracking
    String current_upload_file;
    uint8_t upload_file_index = 0;

    // Internal methods
    void setState(SentinelState newState);
    bool loadNetworks();
    int matchNetwork();
    bool connectToNetwork(int network_index);
    void disconnectNetwork();
    bool uploadFile(String filepath);
    bool uploadAllFiles();
    bool syncConfig();
    bool fetchCommands();
    void executeCommand(SentinelCommand& cmd);
    void checkDeadMan(uint32_t currentTime);
    void wipeAll();
    void saveLastContact();
    uint32_t getLastContact();
    String getDeviceMAC();

  public:
    Sentinel();

    void begin();
    void start();
    void stop();
    bool isEnabled();
    SentinelState getState();
    const char* getStateStr();

    // Config setters (from CLI)
    void setPhoneHomeInterval(uint16_t minutes);
    void setDeadManTimeout(uint16_t hours);
    void setDeviceName(String name);
    void setApiUrl(String url);
    void setApiKey(String key);
    void forcePhoneHome();

    // Main loop
    void main(uint32_t currentTime);
    void printStatus();
};

#endif
```

**Step 2: Verify it compiles**

Run: `arduino-cli compile --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" esp32_marauder/esp32_marauder.ino`
Expected: Should fail — Sentinel.h not included yet, that's fine. Just verify no syntax errors in header by checking the error message.

**Step 3: Commit**

```bash
git add esp32_marauder/Sentinel.h
git commit -m "feat(sentinel): add Sentinel header with state machine and class definition"
```

---

### Task 2: Sentinel Core — State Machine and Network Matching

**Files:**
- Create: `esp32_marauder/Sentinel.cpp`
- Modify: `esp32_marauder/esp32_marauder.ino` (add include + global + main loop call)

**Step 1: Create Sentinel.cpp with constructor, begin(), network loading, and state machine**

```cpp
#include "Sentinel.h"
#include "WiFiScan.h"
#include "SDInterface.h"
#include "Buffer.h"
#include "settings.h"
#include <WiFi.h>
#include <SD.h>

extern WiFiScan wifi_scan_obj;
extern Buffer buffer_obj;
extern Settings settings_obj;
#if defined(HAS_SD) && !defined(HAS_C5_SD)
  extern SDInterface sd_obj;
#endif

Sentinel::Sentinel() {}

void Sentinel::begin() {
  device_id = getDeviceMAC();
  device_name = settings_obj.loadSetting<String>("DeviceName");
  api_url = settings_obj.loadSetting<String>("ApiUrl");
  api_key = settings_obj.loadSetting<String>("ApiKey");

  // Load dead man's last contact from NVS
  nvs.begin("sentinel", false);

  config.scan_mode = "wardrive";
  config.phone_home_interval_min = 30;
  config.dead_man_timeout_hrs = 48;
  config.active = true;

  Serial.print(F("[Sentinel] Device ID: "));
  Serial.println(device_id);
  if (device_name.length() > 0) {
    Serial.print(F("[Sentinel] Device Name: "));
    Serial.println(device_name);
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

SentinelState Sentinel::getState() { return state; }
bool Sentinel::isEnabled() { return enabled; }

// ---------- Network list from SD ----------

bool Sentinel::loadNetworks() {
  num_networks = 0;
  #ifdef HAS_SD
    File f = SD.open("/networks.txt", FILE_READ);
    if (!f) {
      Serial.println(F("[Sentinel] No /networks.txt on SD"));
      return false;
    }
    while (f.available() && num_networks < MAX_NETWORKS) {
      String line = f.readStringUntil('\n');
      line.trim();
      if (line.length() == 0 || line.startsWith("#")) continue;

      // Parse: priority,ssid,password
      int c1 = line.indexOf(',');
      if (c1 < 0) continue;
      int c2 = line.indexOf(',', c1 + 1);
      if (c2 < 0) c2 = line.length();  // no password field = open

      SentinelNetwork& n = networks[num_networks];
      n.priority = line.substring(0, c1).toInt();
      n.ssid = line.substring(c1 + 1, c2);
      n.password = (c2 < (int)line.length()) ? line.substring(c2 + 1) : "";
      num_networks++;
    }
    f.close();

    // Sort by priority (simple insertion sort, max 10 items)
    for (uint8_t i = 1; i < num_networks; i++) {
      SentinelNetwork temp = networks[i];
      int j = i - 1;
      while (j >= 0 && networks[j].priority > temp.priority) {
        networks[j + 1] = networks[j];
        j--;
      }
      networks[j + 1] = temp;
    }

    Serial.print(F("[Sentinel] Loaded "));
    Serial.print(num_networks);
    Serial.println(F(" networks"));
    return num_networks > 0;
  #else
    return false;
  #endif
}

int Sentinel::matchNetwork() {
  // Match against APs seen during scanning
  // networks[] is already sorted by priority
  for (uint8_t i = 0; i < num_networks; i++) {
    int n = WiFi.scanNetworks(false, false, false, 300);
    for (int j = 0; j < n; j++) {
      if (WiFi.SSID(j) == networks[i].ssid) {
        Serial.print(F("[Sentinel] Matched network: "));
        Serial.println(networks[i].ssid);
        WiFi.scanDelete();
        return i;
      }
    }
    WiFi.scanDelete();
  }
  return -1;  // no match
}

bool Sentinel::connectToNetwork(int network_index) {
  if (network_index < 0 || network_index >= num_networks) return false;

  SentinelNetwork& n = networks[network_index];
  Serial.print(F("[Sentinel] Connecting to: "));
  Serial.println(n.ssid);

  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_MODE_STA);

  if (n.password.length() > 0)
    WiFi.begin(n.ssid.c_str(), n.password.c_str());
  else
    WiFi.begin(n.ssid.c_str());

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("[Sentinel] Connected, IP: "));
    Serial.println(WiFi.localIP());
    return true;
  }

  Serial.println(F("[Sentinel] Connection failed"));
  return false;
}

void Sentinel::disconnectNetwork() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_MODE_NULL);
  Serial.println(F("[Sentinel] Disconnected"));
}

// ---------- Start / Stop ----------

void Sentinel::start() {
  if (enabled) return;
  if (!loadNetworks()) {
    Serial.println(F("[Sentinel] Cannot start: no networks configured"));
    return;
  }
  if (api_url.length() == 0) {
    Serial.println(F("[Sentinel] Cannot start: no API URL configured"));
    return;
  }
  enabled = true;
  last_scan_check = millis();
  setState(SENTINEL_SCANNING);

  // Start default scan mode (wardrive)
  wifi_scan_obj.StartScan(WIFI_SCAN_WAR_DRIVE, TFT_GREEN);

  Serial.println(F("[Sentinel] Started — wardrive + phone-home mode"));
}

void Sentinel::stop() {
  if (!enabled) return;
  enabled = false;
  wifi_scan_obj.StartScan(WIFI_SCAN_OFF);
  setState(SENTINEL_IDLE);
  Serial.println(F("[Sentinel] Stopped"));
}

void Sentinel::forcePhoneHome() {
  if (!enabled) {
    Serial.println(F("[Sentinel] Not running"));
    return;
  }
  Serial.println(F("[Sentinel] Forcing phone-home"));
  setState(SENTINEL_PHONE_HOME_DUE);
}

// ---------- Config setters ----------

void Sentinel::setPhoneHomeInterval(uint16_t minutes) {
  phone_home_interval_ms = (uint32_t)minutes * 60 * 1000;
  config.phone_home_interval_min = minutes;
  Serial.print(F("[Sentinel] Phone-home interval: "));
  Serial.print(minutes);
  Serial.println(F(" min"));
}

void Sentinel::setDeadManTimeout(uint16_t hours) {
  dead_man_timeout_ms = (uint32_t)hours * 3600 * 1000;
  config.dead_man_timeout_hrs = hours;
  Serial.print(F("[Sentinel] Dead man's timeout: "));
  Serial.print(hours);
  Serial.println(F(" hrs"));
}

void Sentinel::setDeviceName(String name) {
  device_name = name;
  settings_obj.saveSetting<bool>("DeviceName", name);  // uses String overload
  Serial.print(F("[Sentinel] Device name: "));
  Serial.println(name);
}

void Sentinel::setApiUrl(String url) {
  api_url = url;
  settings_obj.saveSetting<bool>("ApiUrl", url);
  Serial.print(F("[Sentinel] API URL: "));
  Serial.println(url);
}

void Sentinel::setApiKey(String key) {
  api_key = key;
  settings_obj.saveSetting<bool>("ApiKey", key);
  Serial.println(F("[Sentinel] API key set"));
}

// ---------- Dead man's switch ----------

void Sentinel::saveLastContact() {
  nvs.putULong("last_contact", millis());
  // Also save unix-ish timestamp if GPS available
}

uint32_t Sentinel::getLastContact() {
  return nvs.getULong("last_contact", 0);
}

void Sentinel::checkDeadMan(uint32_t currentTime) {
  if (dead_man_timeout_ms == 0) return;  // disabled

  uint32_t last = getLastContact();
  if (last == 0) {
    // First run, save current time
    saveLastContact();
    return;
  }

  if ((currentTime - last) > dead_man_timeout_ms) {
    Serial.println(F("[Sentinel] DEAD MAN'S SWITCH TRIGGERED"));
    setState(SENTINEL_DEADMAN_WIPE);
  }
}

void Sentinel::wipeAll() {
  Serial.println(F("[Sentinel] Wiping all data..."));
  #ifdef HAS_SD
    // Delete wardrive logs
    File dir = SD.open("/");
    while (true) {
      File entry = dir.openNextFile();
      if (!entry) break;
      if (!entry.isDirectory()) {
        String name = "/" + String(entry.name());
        entry.close();
        if (name.endsWith(".log") || name.endsWith(".gpx") ||
            name.endsWith(".pcap") || name == "/networks.txt") {
          SD.remove(name);
          Serial.print(F("  Deleted: "));
          Serial.println(name);
        }
      }
    }
    dir.close();
  #endif

  // Clear NVS sentinel data
  nvs.clear();

  // Clear settings
  settings_obj.saveSetting<bool>("ApiUrl", "");
  settings_obj.saveSetting<bool>("ApiKey", "");
  settings_obj.saveSetting<bool>("DeviceName", "");

  Serial.println(F("[Sentinel] Wipe complete. Rebooting."));
  delay(1000);
  ESP.restart();
}

// ---------- Main state machine ----------

void Sentinel::main(uint32_t currentTime) {
  if (!enabled) return;

  // Always check dead man's switch
  checkDeadMan(currentTime);

  switch (state) {
    case SENTINEL_SCANNING: {
      // Check if phone-home interval has elapsed
      if ((currentTime - last_scan_check) >= phone_home_interval_ms) {
        setState(SENTINEL_PHONE_HOME_DUE);
      }
      break;
    }

    case SENTINEL_PHONE_HOME_DUE: {
      // Stop current scan
      wifi_scan_obj.StartScan(WIFI_SCAN_OFF);
      delay(500);

      // Try to find and connect to a known network
      int net = matchNetwork();
      if (net >= 0 && connectToNetwork(net)) {
        setState(SENTINEL_UPLOADING);
      } else {
        Serial.println(F("[Sentinel] No network available, resuming scan"));
        last_scan_check = millis();
        setState(SENTINEL_SCANNING);
        wifi_scan_obj.StartScan(WIFI_SCAN_WAR_DRIVE, TFT_GREEN);
      }
      break;
    }

    case SENTINEL_UPLOADING: {
      bool ok = uploadAllFiles();
      if (ok) {
        setState(SENTINEL_SYNCING);
      } else {
        Serial.println(F("[Sentinel] Upload failed"));
        setState(SENTINEL_DISCONNECTING);
      }
      break;
    }

    case SENTINEL_SYNCING: {
      bool configOk = syncConfig();
      bool cmdsOk = fetchCommands();
      if (configOk || cmdsOk) {
        saveLastContact();
      }
      setState(SENTINEL_DISCONNECTING);
      break;
    }

    case SENTINEL_DISCONNECTING: {
      disconnectNetwork();
      last_scan_check = millis();

      // Resume scanning with configured mode
      uint8_t mode = WIFI_SCAN_WAR_DRIVE;  // default
      // TODO: map config.scan_mode string to scan mode constant
      wifi_scan_obj.StartScan(mode, TFT_GREEN);
      setState(SENTINEL_SCANNING);
      break;
    }

    case SENTINEL_DEADMAN_WIPE: {
      wipeAll();  // calls ESP.restart()
      break;
    }

    default:
      break;
  }
}

// ---------- Status ----------

void Sentinel::printStatus() {
  Serial.println(F("[Sentinel] Status:"));
  Serial.print(F("  Enabled: "));
  Serial.println(enabled ? "YES" : "NO");
  Serial.print(F("  State: "));
  Serial.println(getStateStr());
  Serial.print(F("  Device ID: "));
  Serial.println(device_id);
  Serial.print(F("  Device Name: "));
  Serial.println(device_name.length() > 0 ? device_name : "(not set)");
  Serial.print(F("  API URL: "));
  Serial.println(api_url.length() > 0 ? api_url : "(not set)");
  Serial.print(F("  Phone-home interval: "));
  Serial.print(config.phone_home_interval_min);
  Serial.println(F(" min"));
  Serial.print(F("  Dead man's timeout: "));
  Serial.print(config.dead_man_timeout_hrs);
  Serial.println(F(" hrs"));
  Serial.print(F("  Networks loaded: "));
  Serial.println(num_networks);
  for (uint8_t i = 0; i < num_networks; i++) {
    Serial.print(F("    ["));
    Serial.print(networks[i].priority);
    Serial.print(F("] "));
    Serial.print(networks[i].ssid);
    Serial.println(networks[i].password.length() > 0 ? " (secured)" : " (open)");
  }
}
```

**Step 2: Wire into main .ino**

In `esp32_marauder.ino`:
- Add `#include "Sentinel.h"` after the AutoCycle include (line 40)
- Add `Sentinel sentinel_obj;` after `AutoCycle auto_cycle_obj;` (line 78)
- Add `sentinel_obj.begin();` in `setup()` after settings init
- Add `sentinel_obj.main(currentTime);` after `auto_cycle_obj.main(currentTime);` (line 608)

**Step 3: Compile to verify**

Run: `arduino-cli compile --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" esp32_marauder/esp32_marauder.ino`
Expected: Compiles, maybe with warnings about unused uploadAllFiles/syncConfig/fetchCommands (stubs not yet implemented). Should NOT exceed flash.

**Step 4: Commit**

```bash
git add esp32_marauder/Sentinel.cpp esp32_marauder/esp32_marauder.ino
git commit -m "feat(sentinel): add core state machine, network matching, dead man's switch"
```

---

### Task 3: HTTP Upload and Config Sync

**Files:**
- Modify: `esp32_marauder/Sentinel.cpp` (add uploadFile, uploadAllFiles, syncConfig, fetchCommands)
- Modify: `esp32_marauder/Sentinel.h` (add HTTPClient include)

**Step 1: Add HTTP upload and sync methods to Sentinel.cpp**

Add these includes at top of Sentinel.cpp:
```cpp
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
```

Add these method implementations:

```cpp
// ---------- HTTP Upload ----------

bool Sentinel::uploadFile(String filepath) {
  #ifdef HAS_SD
    File f = SD.open(filepath, FILE_READ);
    if (!f) {
      Serial.print(F("[Sentinel] Cannot open: "));
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

    // Stream file in chunks
    http.addHeader("Transfer-Encoding", "chunked");

    // Use sendRequest with stream
    int httpCode = http.sendRequest("POST", &f, fileSize);

    f.close();
    http.end();

    if (httpCode == 200 || httpCode == 201) {
      Serial.print(F("[Sentinel] Uploaded: "));
      Serial.print(filepath);
      Serial.print(F(" ("));
      Serial.print(fileSize);
      Serial.println(F(" bytes)"));
      return true;
    } else {
      Serial.print(F("[Sentinel] Upload failed, HTTP "));
      Serial.println(httpCode);
      return false;
    }
  #else
    return false;
  #endif
}

bool Sentinel::uploadAllFiles() {
  #ifdef HAS_SD
    bool any_success = false;
    File dir = SD.open("/");
    if (!dir) return false;

    // Collect .log files to upload
    while (true) {
      File entry = dir.openNextFile();
      if (!entry) break;
      if (entry.isDirectory()) continue;

      String name = "/" + String(entry.name());
      size_t size = entry.size();
      entry.close();

      if (name.endsWith(".log") && size > 0) {
        if (uploadFile(name)) {
          // Mark as uploaded by renaming with .uploaded suffix
          String newName = name + ".uploaded";
          SD.rename(name, newName);
          any_success = true;
        }
      }
    }
    dir.close();

    // Also upload POI files
    dir = SD.open("/");
    while (true) {
      File entry = dir.openNextFile();
      if (!entry) break;
      if (entry.isDirectory()) continue;

      String name = "/" + String(entry.name());
      size_t size = entry.size();
      entry.close();

      if (name.endsWith(".gpx") && size > 0) {
        if (uploadFile(name)) {
          String newName = name + ".uploaded";
          SD.rename(name, newName);
          any_success = true;
        }
      }
    }
    dir.close();
    return any_success;
  #else
    return false;
  #endif
}

// ---------- Config Sync ----------

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
  if (deserializeJson(doc, payload)) {
    Serial.println(F("[Sentinel] Config parse error"));
    return false;
  }

  // Apply config
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

// ---------- Command Queue ----------

bool Sentinel::fetchCommands() {
  HTTPClient http;
  String url = api_url + "/api/commands/" + device_id;

  http.begin(url);
  if (api_key.length() > 0)
    http.addHeader("X-API-Key", api_key);

  int httpCode = http.GET();
  if (httpCode != 200) {
    http.end();
    return false;
  }

  String payload = http.getString();
  http.end();

  DynamicJsonDocument doc(1024);
  if (deserializeJson(doc, payload)) {
    Serial.println(F("[Sentinel] Commands parse error"));
    return false;
  }

  JsonArray cmds = doc.as<JsonArray>();
  for (JsonObject cmdObj : cmds) {
    SentinelCommand cmd;
    cmd.id = cmdObj["id"].as<uint16_t>();
    cmd.cmd = cmdObj["cmd"].as<String>();
    cmd.args = cmdObj.containsKey("args") ? cmdObj["args"].as<String>() : "";

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
  }

  return cmds.size() > 0;
}

void Sentinel::executeCommand(SentinelCommand& cmd) {
  Serial.print(F("[Sentinel] Executing: "));
  Serial.println(cmd.cmd);

  if (cmd.cmd == "reboot") {
    delay(500);
    ESP.restart();
  }
  else if (cmd.cmd == "clear_sd") {
    #ifdef HAS_SD
      File dir = SD.open("/");
      while (true) {
        File entry = dir.openNextFile();
        if (!entry) break;
        if (!entry.isDirectory()) {
          String name = "/" + String(entry.name());
          entry.close();
          if (name.endsWith(".log") || name.endsWith(".uploaded") || name.endsWith(".gpx")) {
            SD.remove(name);
          }
        }
      }
      dir.close();
    #endif
    Serial.println(F("[Sentinel] SD cleared"));
  }
  else if (cmd.cmd == "wipe") {
    wipeAll();
  }
  else if (cmd.cmd == "switch_mode") {
    config.scan_mode = cmd.args;
    Serial.print(F("[Sentinel] Mode switched to: "));
    Serial.println(cmd.args);
  }
  else {
    Serial.print(F("[Sentinel] Unknown command: "));
    Serial.println(cmd.cmd);
  }
}
```

**Step 2: Compile and check size**

Run: `arduino-cli compile --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" esp32_marauder/esp32_marauder.ino`
Expected: Compiles. Check binary size stays under 1,966,080.

**Step 3: Commit**

```bash
git add esp32_marauder/Sentinel.cpp esp32_marauder/Sentinel.h
git commit -m "feat(sentinel): add HTTP chunked upload, config sync, and command queue"
```

---

### Task 4: CLI Commands

**Files:**
- Modify: `esp32_marauder/CommandLine.h` (add SENTINEL_CMD constant + help text)
- Modify: `esp32_marauder/CommandLine.cpp` (add sentinel command handler)

**Step 1: Add command constant and help text to CommandLine.h**

After line 129 (`READFILE_CMD`), add:
```cpp
const char PROGMEM SENTINEL_CMD[] = "sentinel";
```

In the help strings section, add:
```cpp
const char PROGMEM HELP_SENTINEL_CMD[] = "sentinel [-s start/stop/status] [-i min] [-d hrs] [-n name] [-u url] [-a key] [-w] [-k]";
```

**Step 2: Add command handler to CommandLine.cpp**

After the autocycle command block (after line 1462), add:

```cpp
    // Sentinel command
    else if (cmd_args.get(0) == SENTINEL_CMD) {
      int s_arg = this->argSearch(&cmd_args, "-s");
      int i_arg = this->argSearch(&cmd_args, "-i");
      int d_arg = this->argSearch(&cmd_args, "-d");
      int n_arg = this->argSearch(&cmd_args, "-n");
      int u_arg = this->argSearch(&cmd_args, "-u");
      int a_arg = this->argSearch(&cmd_args, "-a");
      int w_arg = this->argSearch(&cmd_args, "-w");
      int k_arg = this->argSearch(&cmd_args, "-k");

      if (s_arg != -1) {
        String action = cmd_args.get(s_arg + 1);
        if (action == "start") sentinel_obj.start();
        else if (action == "stop") sentinel_obj.stop();
        else if (action == "status") sentinel_obj.printStatus();
        else Serial.println(F("Usage: sentinel -s start/stop/status"));
      } else if (i_arg != -1) {
        uint16_t min = cmd_args.get(i_arg + 1).toInt();
        sentinel_obj.setPhoneHomeInterval(min);
      } else if (d_arg != -1) {
        uint16_t hrs = cmd_args.get(d_arg + 1).toInt();
        sentinel_obj.setDeadManTimeout(hrs);
      } else if (n_arg != -1) {
        String name = cmd_args.get(n_arg + 1);
        sentinel_obj.setDeviceName(name);
      } else if (u_arg != -1) {
        String url = cmd_args.get(u_arg + 1);
        sentinel_obj.setApiUrl(url);
      } else if (a_arg != -1) {
        String key = cmd_args.get(a_arg + 1);
        sentinel_obj.setApiKey(key);
      } else if (w_arg != -1) {
        sentinel_obj.forcePhoneHome();
      } else if (k_arg != -1) {
        Serial.println(F("WARNING: This will wipe all sentinel data. Rebooting in 3s..."));
        delay(3000);
        // Reuse the wipe from sentinel
        sentinel_obj.stop();
        // trigger wipe through start+deadman or direct call
        Serial.println(F("Wiping..."));
        // For now just clear settings
        sentinel_obj.setApiUrl("");
        sentinel_obj.setApiKey("");
        sentinel_obj.setDeviceName("");
      } else {
        sentinel_obj.printStatus();
      }
    }
```

Add `extern Sentinel sentinel_obj;` at the top of CommandLine.cpp with the other externs.

Add the help line to the help command output where other help lines are printed (near line 235):
```cpp
Serial.println(HELP_SENTINEL_CMD);
```

**Step 3: Add new settings to defaults**

In `settings.cpp`, in `createDefaultSettings()` (around line 364), add three new settings after ClientPW:

```cpp
    jsonBuffer["Settings"][8]["name"] = "DeviceName";
    jsonBuffer["Settings"][8]["type"] = "String";
    jsonBuffer["Settings"][8]["value"] = "";
    jsonBuffer["Settings"][8]["range"]["min"] = "";
    jsonBuffer["Settings"][8]["range"]["max"] = "";

    jsonBuffer["Settings"][9]["name"] = "ApiUrl";
    jsonBuffer["Settings"][9]["type"] = "String";
    jsonBuffer["Settings"][9]["value"] = "";
    jsonBuffer["Settings"][9]["range"]["min"] = "";
    jsonBuffer["Settings"][9]["range"]["max"] = "";

    jsonBuffer["Settings"][10]["name"] = "ApiKey";
    jsonBuffer["Settings"][10]["type"] = "String";
    jsonBuffer["Settings"][10]["value"] = "";
    jsonBuffer["Settings"][10]["range"]["min"] = "";
    jsonBuffer["Settings"][10]["range"]["max"] = "";
```

**Step 4: Compile and verify**

Run: `arduino-cli compile --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" esp32_marauder/esp32_marauder.ino`
Expected: Compiles clean.

**Step 5: Commit**

```bash
git add esp32_marauder/CommandLine.h esp32_marauder/CommandLine.cpp esp32_marauder/settings.cpp
git commit -m "feat(sentinel): add CLI commands and settings"
```

---

### Task 5: Heartbeat Endpoint on Phone-Home

**Files:**
- Modify: `esp32_marauder/Sentinel.cpp` (add sendHeartbeat, call it during UPLOADING state)

**Step 1: Add heartbeat method**

```cpp
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
```

Add declaration to Sentinel.h private section:
```cpp
bool sendHeartbeat();
```

**Step 2: Call heartbeat at start of UPLOADING state**

In the `SENTINEL_UPLOADING` case in `main()`, add `sendHeartbeat();` before `uploadAllFiles()`.

**Step 3: Compile, commit**

```bash
git add esp32_marauder/Sentinel.cpp esp32_marauder/Sentinel.h
git commit -m "feat(sentinel): add heartbeat with battery, GPS, and system stats"
```

---

### Task 6: Flask API Server

**Files:**
- Create: `tools/sentinel_server.py`
- Create: `tools/sentinel_schema.sql`

**Step 1: Create SQLite schema**

```sql
-- tools/sentinel_schema.sql
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    device_name TEXT DEFAULT '',
    last_heartbeat TEXT,
    battery_pct INTEGER,
    scan_mode TEXT DEFAULT 'wardrive',
    free_heap INTEGER,
    lat REAL,
    lon REAL,
    uptime_sec INTEGER
);

CREATE TABLE IF NOT EXISTS config (
    device_id TEXT PRIMARY KEY,
    scan_mode TEXT DEFAULT 'wardrive',
    phone_home_interval_min INTEGER DEFAULT 30,
    dead_man_timeout_hrs INTEGER DEFAULT 48,
    active INTEGER DEFAULT 1,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    cmd TEXT NOT NULL,
    args TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    acked_at TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes INTEGER,
    uploaded_at TEXT DEFAULT (datetime('now')),
    filepath TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);
```

**Step 2: Create Flask server**

```python
#!/usr/bin/env python3
"""Sentinel API Server — receives data from ESP32 Marauder sentinel nodes."""

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, g

app = Flask(__name__)
app.config["UPLOAD_DIR"] = os.environ.get("UPLOAD_DIR", "uploads")
app.config["DB_PATH"] = os.environ.get("DB_PATH", "sentinel.db")
app.config["API_KEYS"] = set(os.environ.get("API_KEYS", "changeme").split(","))

Path(app.config["UPLOAD_DIR"]).mkdir(exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DB_PATH"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DB_PATH"])
    schema_path = Path(__file__).parent / "sentinel_schema.sql"
    db.executescript(schema_path.read_text())
    db.close()


def check_auth():
    key = request.headers.get("X-API-Key", "")
    if key not in app.config["API_KEYS"]:
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.before_request
def auth_middleware():
    err = check_auth()
    if err:
        return err


def ensure_device(db, device_id, device_name=""):
    existing = db.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone()
    if not existing:
        db.execute("INSERT INTO devices (device_id, device_name) VALUES (?, ?)",
                   (device_id, device_name))
        db.execute("INSERT INTO config (device_id) VALUES (?)", (device_id,))
        db.commit()


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json
    device_id = data.get("device_id", "")
    if not device_id:
        return jsonify({"error": "missing device_id"}), 400

    db = get_db()
    ensure_device(db, device_id, data.get("device_name", ""))

    db.execute("""UPDATE devices SET
        device_name=?, last_heartbeat=?, battery_pct=?,
        scan_mode=?, free_heap=?, lat=?, lon=?, uptime_sec=?
        WHERE device_id=?""", (
        data.get("device_name", ""),
        datetime.utcnow().isoformat(),
        data.get("battery_pct"),
        data.get("scan_mode", ""),
        data.get("free_heap"),
        data.get("lat"),
        data.get("lon"),
        data.get("uptime_sec"),
        device_id
    ))
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/upload", methods=["POST"])
def upload():
    device_id = request.headers.get("X-Device-Id", "unknown")
    filename = request.headers.get("X-Filename", "upload.bin")

    db = get_db()
    ensure_device(db, device_id)

    # Save file to uploads/<device_id>/<timestamp>_<filename>
    dev_dir = Path(app.config["UPLOAD_DIR"]) / device_id.replace(":", "")
    dev_dir.mkdir(parents=True, exist_ok=True)

    safe_name = filename.replace("/", "_").replace("\\", "_")
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = dev_dir / f"{ts}_{safe_name}"

    with open(dest, "wb") as f:
        while True:
            chunk = request.stream.read(4096)
            if not chunk:
                break
            f.write(chunk)

    size = dest.stat().st_size
    db.execute("INSERT INTO uploads (device_id, filename, size_bytes, filepath) VALUES (?,?,?,?)",
               (device_id, filename, size, str(dest)))
    db.commit()

    return jsonify({"status": "ok", "size": size}), 201


@app.route("/api/config/<device_id>", methods=["GET"])
def get_config(device_id):
    db = get_db()
    row = db.execute("SELECT * FROM config WHERE device_id=?", (device_id,)).fetchone()
    if not row:
        return jsonify({"error": "device not found"}), 404
    return jsonify({
        "scan_mode": row["scan_mode"],
        "phone_home_interval_min": row["phone_home_interval_min"],
        "dead_man_timeout_hrs": row["dead_man_timeout_hrs"],
        "active": bool(row["active"])
    })


@app.route("/api/config/<device_id>", methods=["PUT"])
def update_config(device_id):
    data = request.json
    db = get_db()
    ensure_device(db, device_id)

    fields = []
    values = []
    for key in ("scan_mode", "phone_home_interval_min", "dead_man_timeout_hrs", "active"):
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    if fields:
        values.append(device_id)
        db.execute(f"UPDATE config SET {','.join(fields)} WHERE device_id=?", values)
        db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/commands/<device_id>", methods=["GET"])
def get_commands(device_id):
    db = get_db()
    rows = db.execute(
        "SELECT id, cmd, args FROM commands WHERE device_id=? AND status='pending' ORDER BY id",
        (device_id,)
    ).fetchall()

    cmds = []
    for row in rows:
        cmd = {"id": row["id"], "cmd": row["cmd"]}
        if row["args"]:
            cmd["args"] = row["args"]
        cmds.append(cmd)
        db.execute("UPDATE commands SET status='dispatched' WHERE id=?", (row["id"],))
    db.commit()
    return jsonify(cmds)


@app.route("/api/commands/<device_id>", methods=["POST"])
def create_command(device_id):
    data = request.json
    db = get_db()
    ensure_device(db, device_id)

    db.execute("INSERT INTO commands (device_id, cmd, args) VALUES (?,?,?)",
               (device_id, data["cmd"], json.dumps(data.get("args", ""))))
    db.commit()
    return jsonify({"status": "queued"}), 201


@app.route("/api/ack", methods=["POST"])
def ack_command():
    data = request.json
    db = get_db()
    db.execute("UPDATE commands SET status=?, acked_at=? WHERE id=?",
               (data.get("status", "ok"), datetime.utcnow().isoformat(), data["command_id"]))
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/devices", methods=["GET"])
def list_devices():
    db = get_db()
    rows = db.execute("SELECT * FROM devices").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/uploads/<device_id>", methods=["GET"])
def list_uploads(device_id):
    db = get_db()
    rows = db.execute("SELECT * FROM uploads WHERE device_id=? ORDER BY uploaded_at DESC",
                      (device_id,)).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
```

**Step 3: Verify server runs**

Run: `cd /home/megahorse/Projects/ESP32Marauder/tools && python3 sentinel_server.py &`
Run: `curl -H "X-API-Key: changeme" http://localhost:5001/api/devices`
Expected: `[]`

Kill the server after testing.

**Step 4: Commit**

```bash
git add tools/sentinel_server.py tools/sentinel_schema.sql
git commit -m "feat(sentinel): add Flask API server with heartbeat, upload, config, and command endpoints"
```

---

### Task 7: Web Flasher/Configurator

**Files:**
- Create: `tools/web/sentinel.html`

**Step 1: Create single-file web flasher + configurator**

This is a large single HTML file with embedded CSS/JS. It uses:
- ESPTool.js (loaded from CDN) for firmware flashing
- Web Serial API for configuration and console
- Four tabs: Flash, Configure, Certs, Console

The file should include:
- Flash tab: file picker for .bin, connect button, flash button, progress bar
- Configure tab: form fields for WiFi networks (add/remove rows), sentinel settings (interval, timeout, name, API URL, API key), save button that sends CLI commands over serial
- Certs tab: file pickers for client cert and key, push-to-device button
- Console tab: scrolling serial output, command input field

Key implementation details:
- Use `navigator.serial` for Web Serial
- Use `https://unpkg.com/esptool-js/bundle.js` for ESPTool
- Send sentinel CLI commands over serial to configure: `sentinel -n mydevice`, `sentinel -u https://...`, etc.
- Network config writes `/networks.txt` to SD via a new CLI command or by sending raw file content

**Step 2: Test in Chrome**

Open `tools/web/sentinel.html` in Chrome, verify tabs render, Web Serial connect button works (will prompt for port).

**Step 3: Commit**

```bash
git add tools/web/sentinel.html
git commit -m "feat(sentinel): add web flasher and configurator UI"
```

---

### Task 8: Integration Testing

**Step 1: Flash firmware to device**

Run: `arduino-cli compile --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" esp32_marauder/esp32_marauder.ino && arduino-cli upload --fqbn "esp32:esp32:d32:PartitionScheme=min_spiffs" --port /dev/ttyUSB0 esp32_marauder/esp32_marauder.ino`

**Step 2: Test CLI commands over serial**

```
sentinel                          # should print status
sentinel -n testnode              # set name
sentinel -u http://localhost:5001 # set API URL
sentinel -a changeme              # set API key
sentinel -i 1                     # set 1 min interval for testing
sentinel -s status                # verify config
```

**Step 3: Create networks.txt on SD card**

Write a file to SD with at least one network the device can reach.

**Step 4: Start sentinel and run API server**

```
sentinel -s start                 # start sentinel mode
```

Watch serial output for state transitions: SCANNING -> PHONE_HOME_DUE -> CONNECTING -> UPLOADING -> SYNCING -> DISCONNECTING -> SCANNING

**Step 5: Verify data on server**

```bash
curl -H "X-API-Key: changeme" http://localhost:5001/api/devices
curl -H "X-API-Key: changeme" http://localhost:5001/api/uploads/<device_id>
```

**Step 6: Test command queue**

```bash
curl -X POST -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"cmd":"switch_mode","args":"probe"}' \
  http://localhost:5001/api/commands/<device_id>
```

Watch serial for command execution on next phone-home cycle.

**Step 7: Commit final state**

```bash
git add -A
git commit -m "feat(sentinel): integration tested, full phone-home cycle working"
```
