#include "Sentinel.h"
#include "WiFiScan.h"
#include "Buffer.h"

#include <WiFi.h>
#include <esp_wifi.h>

#ifdef HAS_SD
  #include "SD.h"
#endif

extern WiFiScan wifi_scan_obj;
extern Buffer buffer_obj;

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

  Serial.println(F("[Sentinel] Initialized"));
  Serial.print(F("[Sentinel] Device ID: "));
  Serial.println(device_id);
  Serial.print(F("[Sentinel] Device Name: "));
  Serial.println(device_name);
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
  Serial.println(F("[Sentinel] Started"));
}

void Sentinel::stop() {
  if (!enabled) return;

  enabled = false;
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

// === STUB METHODS (implemented in Task 3) ===

bool Sentinel::uploadFile(String filepath) {
  // TODO: implement HTTP upload
  return false;
}

bool Sentinel::uploadAllFiles() {
  // TODO: implement bulk upload
  return false;
}

bool Sentinel::syncConfig() {
  // TODO: implement config sync
  return false;
}

bool Sentinel::fetchCommands() {
  // TODO: implement command fetch
  return false;
}

bool Sentinel::sendHeartbeat() {
  // TODO: implement heartbeat
  return false;
}

void Sentinel::executeCommand(SentinelCommand& cmd) {
  Serial.print(F("[Sentinel] Execute command: "));
  Serial.println(cmd.cmd);
  // TODO: implement command execution
}

// === STATE MACHINE ===

void Sentinel::main(uint32_t currentTime) {
  if (!enabled) return;

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
