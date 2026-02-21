#pragma once

#ifndef AutoCycle_h
#define AutoCycle_h

#include "configs.h"
#include "WiFiScan.h"

extern WiFiScan wifi_scan_obj;

// Scan modes to cycle through
struct CycleMode {
  uint8_t scan_mode;     // WIFI_SCAN_PROBE, WIFI_SCAN_AP, etc.
  uint16_t color;        // TFT display color
  uint16_t duration_sec; // How long to run this scan
  const char* label;     // Human-readable name
};

class AutoCycle {
  private:
    bool running = false;
    uint8_t current_index = 0;
    uint8_t num_modes = 0;
    uint32_t mode_start_time = 0;
    uint32_t pause_start_time = 0;
    bool pausing = false;
    uint16_t pause_duration = 5; // seconds between scans
    uint16_t cycle_count = 0;

    static const uint8_t MAX_MODES = 8;
    CycleMode modes[MAX_MODES];

    void startNextMode();
    void stopCurrentMode();

  public:
    AutoCycle();

    void start();
    void stop();
    bool isRunning();
    uint8_t getCurrentIndex();
    uint8_t getNumModes();
    uint16_t getCycleCount();
    uint16_t getElapsedSec();
    uint16_t getCurrentDuration();
    const char* getCurrentLabel();

    void setPauseDuration(uint16_t sec);
    void setModeDuration(uint8_t index, uint16_t sec);
    void loadDefaults();

    void main(uint32_t currentTime);
    void printStatus();
};

#endif
