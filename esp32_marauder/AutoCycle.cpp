#include "AutoCycle.h"

AutoCycle::AutoCycle() {
  this->loadDefaults();
}

void AutoCycle::loadDefaults() {
  num_modes = 5;
  modes[0] = {WIFI_SCAN_PROBE,     TFT_CYAN,    60,  "Probe Sniff"};
  modes[1] = {WIFI_SCAN_AP,        TFT_MAGENTA, 45,  "Beacon Sniff"};
  modes[2] = {WIFI_SCAN_TARGET_AP, TFT_GREEN,   30,  "AP Scan"};
  modes[3] = {WIFI_SCAN_DEAUTH,    TFT_RED,     30,  "Deauth Detect"};
  modes[4] = {BT_SCAN_ALL,         TFT_BLUE,    45,  "BLE Scan"};
  pause_duration = 5;
}

void AutoCycle::start() {
  if (running) return;
  running = true;
  current_index = 0;
  pausing = false;
  cycle_count = 0;
  Serial.println(F("[AutoCycle] Started"));
  startNextMode();
}

void AutoCycle::stop() {
  if (!running) return;
  running = false;
  pausing = false;
  wifi_scan_obj.StartScan(WIFI_SCAN_OFF);
  Serial.println(F("[AutoCycle] Stopped"));
}

bool AutoCycle::isRunning() {
  return running;
}

uint8_t AutoCycle::getCurrentIndex() {
  return current_index;
}

uint8_t AutoCycle::getNumModes() {
  return num_modes;
}

uint16_t AutoCycle::getCycleCount() {
  return cycle_count;
}

uint16_t AutoCycle::getElapsedSec() {
  if (pausing)
    return (millis() - pause_start_time) / 1000;
  return (millis() - mode_start_time) / 1000;
}

uint16_t AutoCycle::getCurrentDuration() {
  if (pausing) return pause_duration;
  if (current_index < num_modes) return modes[current_index].duration_sec;
  return 0;
}

const char* AutoCycle::getCurrentLabel() {
  if (pausing) return "Pause";
  if (current_index < num_modes) return modes[current_index].label;
  return "Idle";
}

void AutoCycle::setPauseDuration(uint16_t sec) {
  pause_duration = sec;
}

void AutoCycle::setModeDuration(uint8_t index, uint16_t sec) {
  if (index < num_modes) {
    modes[index].duration_sec = sec;
  }
}

void AutoCycle::startNextMode() {
  if (!running || current_index >= num_modes) return;

  CycleMode& m = modes[current_index];
  Serial.print(F("[AutoCycle] ["));
  Serial.print(current_index + 1);
  Serial.print(F("/"));
  Serial.print(num_modes);
  Serial.print(F("] "));
  Serial.print(m.label);
  Serial.print(F(" for "));
  Serial.print(m.duration_sec);
  Serial.println(F("s"));

  wifi_scan_obj.StartScan(m.scan_mode, m.color);
  mode_start_time = millis();
  pausing = false;
}

void AutoCycle::stopCurrentMode() {
  wifi_scan_obj.StartScan(WIFI_SCAN_OFF);

  if (current_index < num_modes) {
    Serial.print(F("[AutoCycle] "));
    Serial.print(modes[current_index].label);
    Serial.println(F(" done"));
  }
}

void AutoCycle::main(uint32_t currentTime) {
  if (!running) return;

  if (pausing) {
    // Waiting between scans
    uint32_t elapsed = (currentTime - pause_start_time) / 1000;
    if (elapsed >= pause_duration) {
      pausing = false;
      startNextMode();
    }
    return;
  }

  // Check if current scan duration is up
  uint32_t elapsed = (currentTime - mode_start_time) / 1000;
  if (elapsed >= modes[current_index].duration_sec) {
    stopCurrentMode();

    current_index++;

    if (current_index >= num_modes) {
      // Cycle complete
      cycle_count++;
      Serial.print(F("[AutoCycle] Cycle #"));
      Serial.print(cycle_count);
      Serial.println(F(" complete"));
      current_index = 0;
    }

    // Pause before next mode
    pausing = true;
    pause_start_time = millis();
  }
}

void AutoCycle::printStatus() {
  Serial.println(F("[AutoCycle] Configuration:"));
  for (uint8_t i = 0; i < num_modes; i++) {
    Serial.print(F("  "));
    if (running && i == current_index && !pausing) Serial.print(F(">> "));
    else Serial.print(F("   "));
    Serial.print(modes[i].label);
    Serial.print(F(": "));
    Serial.print(modes[i].duration_sec);
    Serial.println(F("s"));
  }
  Serial.print(F("  Pause: "));
  Serial.print(pause_duration);
  Serial.println(F("s"));
  Serial.print(F("  Status: "));
  Serial.println(running ? F("RUNNING") : F("STOPPED"));
  if (running) {
    Serial.print(F("  Cycle: #"));
    Serial.println(cycle_count + 1);
    Serial.print(F("  Current: "));
    Serial.print(getCurrentLabel());
    Serial.print(F(" ("));
    Serial.print(getElapsedSec());
    Serial.print(F("/"));
    Serial.print(getCurrentDuration());
    Serial.println(F("s)"));
  }
}
