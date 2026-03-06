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
  String scan_mode;
  uint16_t phone_home_interval_min;
  uint16_t dead_man_timeout_hrs;
  bool active;
};

// Pending command from server
struct SentinelCommand {
  uint16_t id;
  String cmd;
  String args;
};

static const uint8_t MAX_NETWORKS = 10;
static const uint8_t MAX_COMMANDS = 8;
static const uint16_t UPLOAD_CHUNK_SIZE = 2048;

class Sentinel {
  private:
    bool enabled = false;
    SentinelState state = SENTINEL_IDLE;
    SentinelNetwork networks[MAX_NETWORKS];
    uint8_t num_networks = 0;
    uint32_t phone_home_interval_ms = 1800000;
    uint32_t last_scan_check = 0;
    uint32_t state_enter_time = 0;
    uint32_t dead_man_timeout_ms = 172800000;
    Preferences nvs;
    String device_id;
    String device_name;
    String api_url;
    String api_key;
    SentinelConfig config;
    String current_upload_file;
    uint8_t upload_file_index = 0;

    void setState(SentinelState newState);
    bool loadNetworks();
    int matchNetwork();
    bool connectToNetwork(int network_index);
    void disconnectNetwork();
    bool uploadFile(String filepath);
    bool uploadAllFiles();
    bool syncConfig();
    bool fetchCommands();
    bool sendHeartbeat();
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
    void setPhoneHomeInterval(uint16_t minutes);
    void setDeadManTimeout(uint16_t hours);
    void setDeviceName(String name);
    void setApiUrl(String url);
    void setApiKey(String key);
    void forcePhoneHome();
    void main(uint32_t currentTime);
    void printStatus();
};

#endif
