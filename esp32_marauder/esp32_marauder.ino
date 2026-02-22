/* FLASH SETTINGS
Board: LOLIN D32
Flash Frequency: 80MHz
Partition Scheme: Minimal SPIFFS
https://www.online-utility.org/image/convert/to/XBM
*/

#include "configs.h"

#ifndef HAS_SCREEN
  #define MenuFunctions_h
  #define Display_h
#endif

#include <WiFi.h>
#include "EvilPortal.h"
#include <Wire.h>
#include "esp_wifi.h"
#include "esp_wifi_types.h"
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include <Arduino.h>

#ifdef HAS_GPS
  #include "GpsInterface.h"
#endif

#include "Assets.h"
#include "WiFiScan.h"
#ifdef HAS_SD
  #include "SDInterface.h"
#endif
#include "Buffer.h"

#ifdef HAS_FLIPPER_LED
  #include "flipperLED.h"
#elif defined(XIAO_ESP32_S3)
  #include "xiaoLED.h"
#elif defined(MARAUDER_M5STICKC) || defined(MARAUDER_M5STICKCP2)
  #include "stickcLED.h"
#elif defined(HAS_NEOPIXEL_LED)
  #include "LedInterface.h"
#endif

#include "settings.h"
#include "CommandLine.h"
#include "AutoCycle.h"
#include "lang_var.h"

#ifdef HAS_BATTERY
  #include "BatteryInterface.h"
#endif

#ifdef HAS_SCREEN
  #include "Display.h"
  #include "MenuFunctions.h"
#endif

#ifdef HAS_BUTTONS
  #include "Switches.h"
  
  #if (U_BTN >= 0)
    Switches u_btn = Switches(U_BTN, 1000, U_PULL);
  #endif
  #if (D_BTN >= 0)
    Switches d_btn = Switches(D_BTN, 1000, D_PULL);
  #endif
  #if (L_BTN >= 0)
    Switches l_btn = Switches(L_BTN, 1000, L_PULL);
  #endif
  #if (R_BTN >= 0)
    Switches r_btn = Switches(R_BTN, 1000, R_PULL);
  #endif
  #if (C_BTN >= 0)
    Switches c_btn = Switches(C_BTN, 1000, C_PULL);
  #endif

#endif

WiFiScan wifi_scan_obj;
EvilPortal evil_portal_obj;
Buffer buffer_obj;
Settings settings_obj;
CommandLine cli_obj;
AutoCycle auto_cycle_obj;

#ifdef HAS_GPS
  GpsInterface gps_obj;
#endif

#ifdef HAS_BATTERY
  BatteryInterface battery_obj;
#endif

#ifdef HAS_SCREEN
  Display display_obj;
  MenuFunctions menu_function_obj;
#endif

#if defined(HAS_SD) && !defined(HAS_C5_SD)
  SDInterface sd_obj;
#endif

#ifdef MARAUDER_M5STICKC
  AXP192 axp192_obj;
#endif

#ifdef HAS_FLIPPER_LED
  flipperLED flipper_led;
#elif defined(XIAO_ESP32_S3)
  xiaoLED xiao_led;
#elif defined(MARAUDER_M5STICKC) || defined(MARAUDER_M5STICKCP2)
  stickcLED stickc_led;
#else
  LedInterface led_obj;
#endif

const String PROGMEM version_number = MARAUDER_VERSION;

#ifdef HAS_NEOPIXEL_LED
  Adafruit_NeoPixel strip = Adafruit_NeoPixel(Pixels, PIN, NEO_GRB + NEO_KHZ800);
#endif

uint32_t currentTime  = 0;

// PWM Brightness Control
#ifdef HAS_SCREEN
  #include <Preferences.h>
  #define BL_CHANNEL 0
  #define BL_FREQ 5000
  #define BL_RESOLUTION 8
  const uint8_t BL_LEVELS[] = {64, 128, 192, 255};
  const uint8_t BL_NUM_LEVELS = 4;
  uint8_t bl_level_idx = 3; // default full brightness
  Preferences bl_prefs;
#endif

// ============================================================
// CYBERPUNK BOOT SPLASH — 4 corner quick-launch buttons
// ============================================================
#ifdef HAS_SCREEN

// Boot shortcut mode table
struct BootMode {
  const char* label;
  uint8_t scanMode;
  uint16_t color;
};

const BootMode BOOT_MODES[] = {
  {"WARDRIVE",  32, 0x07E0},  // WIFI_SCAN_WAR_DRIVE, green
  {"AUTOCYCLE",  0, 0xF81F},  // special handle, magenta
  {"STATION",   33, 0xFDA0},  // WIFI_SCAN_STATION_WAR_DRIVE, orange
  {"BLE SCAN",  10, 0x001F},  // BT_SCAN_ALL, blue
};

// Returns: 0=normal, 1-4=boot mode index
uint8_t drawCyberpunkSplash() {
  TFT_eSPI& tft = display_obj.tft;
  const uint16_t W = TFT_WIDTH;   // 240
  const uint16_t H = TFT_HEIGHT;  // 320
  const uint16_t cx = W / 2;
  const uint16_t cy = H / 2;      // 160

  // Colors
  const uint16_t CYAN    = 0x07FF;
  const uint16_t MAGENTA = 0xF81F;
  const uint16_t DKCYAN  = 0x0410;
  const uint16_t DIMGRAY = 0x39E7;

  tft.fillScreen(TFT_BLACK);
  backlightOn();

  // === Layout ===
  // Buttons: 100x50 in each corner, with 4px margin from border
  const int m = 4;       // outer margin
  const int btnW = 104;
  const int btnH = 55;
  const int gap = 6;     // gap between buttons and center

  // Button positions (x, y for each corner)
  const uint16_t bx[4] = {
    (uint16_t)(m + 2),                    // top-left
    (uint16_t)(W - m - 2 - btnW),         // top-right
    (uint16_t)(m + 2),                    // bottom-left
    (uint16_t)(W - m - 2 - btnW)          // bottom-right
  };
  const uint16_t by[4] = {
    (uint16_t)(m + 2),                    // top-left
    (uint16_t)(m + 2),                    // top-right
    (uint16_t)(H - m - 2 - btnH - 8),    // bottom-left (room for timeout bar)
    (uint16_t)(H - m - 2 - btnH - 8)     // bottom-right
  };

  // Center area for branding: between buttons
  const uint16_t centerTop = by[0] + btnH + gap;
  const uint16_t centerBot = by[2] - gap;
  const uint16_t centerMid = (centerTop + centerBot) / 2;

  // === Phase 1: Border animation ===
  for (int step = 0; step <= 15; step++) {
    float prog = step / 15.0;
    int hLen = (W - m * 2) * prog;
    int vLen = (H - m * 2) * prog;
    tft.drawFastHLine(m, m, hLen, DKCYAN);
    tft.drawFastHLine(W - m - hLen, H - m, hLen, DKCYAN);
    tft.drawFastVLine(m, m, vLen, DKCYAN);
    tft.drawFastVLine(W - m - 1, H - m - vLen, vLen, DKCYAN);
    delay(10);
  }
  delay(40);

  // === Phase 2: Draw 4 buttons ===
  for (int i = 0; i < 4; i++) {
    uint16_t color = BOOT_MODES[i].color;
    tft.drawRect(bx[i], by[i], btnW, btnH, color);
    tft.setTextColor(color, TFT_BLACK);
    tft.drawCentreString(BOOT_MODES[i].label, bx[i] + btnW / 2, by[i] + btnH / 2 - 7, 2);
    delay(60);
  }
  delay(40);

  // === Phase 3: Center branding ===
  // Title typewriter
  const uint16_t titleY = centerMid - 30;
  const char* letters = "MARAUDER";
  tft.setTextColor(CYAN, TFT_BLACK);
  char spaced[24];
  for (int i = 0; i < 8; i++) {
    int pos = 0;
    for (int j = 0; j <= i; j++) {
      if (j > 0) spaced[pos++] = ' ';
      spaced[pos++] = letters[j];
    }
    spaced[pos] = '\0';
    tft.fillRect(btnW + gap + 2, titleY, W - (btnW + gap + 2) * 2, 18, TFT_BLACK);
    tft.drawCentreString(spaced, cx, titleY, 2);
    delay(45);
  }

  // Underline
  for (int step = 0; step <= 10; step++) {
    int hw = 50 * step / 10;
    tft.drawFastHLine(cx - hw, titleY + 20, hw * 2, MAGENTA);
    delay(8);
  }
  delay(40);

  // Edition
  tft.setTextColor(MAGENTA, TFT_BLACK);
  tft.drawCentreString("datboip edition", cx, titleY + 26, 2);
  delay(50);

  // Version + credit
  tft.setTextColor(DIMGRAY, TFT_BLACK);
  tft.drawCentreString(display_obj.version_number, cx, titleY + 46, 1);
  tft.setTextColor(DKCYAN, TFT_BLACK);
  tft.drawCentreString("by JustCallMeKoko", cx, titleY + 58, 1);
  delay(60);

  // === Phase 4: Timeout bar at very bottom ===
  const uint16_t barX = m + 2;
  const uint16_t barW = W - m * 2 - 4;
  const uint16_t barY = H - m - 5;
  tft.drawRect(barX, barY, barW, 4, DIMGRAY);

  // === Phase 5: Wait for tap or timeout (4 seconds) ===
  uint8_t bootMode = 0;
  uint32_t startWait = millis();
  const uint32_t timeout = 4000;

  while (millis() - startWait < timeout) {
    // Animate timeout bar
    uint32_t elapsed = millis() - startWait;
    uint16_t fillW = (barW - 2) - (uint32_t)(barW - 2) * elapsed / timeout;
    tft.fillRect(barX + 1, barY + 1, fillW, 2, DKCYAN);
    tft.fillRect(barX + 1 + fillW, barY + 1, barW - 2 - fillW, 2, TFT_BLACK);

    uint16_t tx, ty;
    if (display_obj.updateTouch(&tx, &ty)) {
      while (display_obj.updateTouch(&tx, &ty)) delay(10);

      // Check which button was tapped
      for (int i = 0; i < 4; i++) {
        if (tx >= bx[i] && tx <= bx[i] + btnW &&
            ty >= by[i] && ty <= by[i] + btnH) {
          // Highlight button (fill solid)
          uint16_t color = BOOT_MODES[i].color;
          tft.fillRect(bx[i], by[i], btnW, btnH, color);
          tft.setTextColor(TFT_BLACK, color);
          tft.drawCentreString(BOOT_MODES[i].label, bx[i] + btnW / 2, by[i] + btnH / 2 - 7, 2);
          delay(250);
          bootMode = i + 1;
          break;
        }
      }
      if (bootMode > 0) break;
    }
    delay(30);
  }

  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  return bootMode;
}
#endif

void brightnessInit() {
  #ifdef HAS_SCREEN
    ledcAttach(TFT_BL, BL_FREQ, BL_RESOLUTION);
    bl_prefs.begin("backlight", false);
    bl_level_idx = bl_prefs.getUChar("level", 3);
    if (bl_level_idx >= BL_NUM_LEVELS) bl_level_idx = 3;
    ledcWrite(TFT_BL, BL_LEVELS[bl_level_idx]);
  #endif
}

void brightnessCycle() {
  #ifdef HAS_SCREEN
    bl_level_idx = (bl_level_idx + 1) % BL_NUM_LEVELS;
    ledcWrite(TFT_BL, BL_LEVELS[bl_level_idx]);
    bl_prefs.putUChar("level", bl_level_idx);
    Serial.print(F("[Brightness] Level "));
    Serial.print(bl_level_idx + 1);
    Serial.print(F("/"));
    Serial.print(BL_NUM_LEVELS);
    Serial.print(F(" ("));
    Serial.print(BL_LEVELS[bl_level_idx] * 100 / 255);
    Serial.println(F("%)"));
  #endif
}

uint8_t getBrightnessLevel() {
  #ifdef HAS_SCREEN
    return bl_level_idx;
  #else
    return 0;
  #endif
}

void brightnessSave(uint8_t level) {
  #ifdef HAS_SCREEN
    if (level >= BL_NUM_LEVELS) level = BL_NUM_LEVELS - 1;
    bl_level_idx = level;
    ledcWrite(TFT_BL, BL_LEVELS[bl_level_idx]);
    bl_prefs.putUChar("level", bl_level_idx);
  #endif
}

void backlightOn() {
  #ifdef HAS_SCREEN
    ledcWrite(TFT_BL, BL_LEVELS[bl_level_idx]);
  #endif
}

void backlightOff() {
  #ifdef HAS_SCREEN
    ledcWrite(TFT_BL, 0);
  #endif
}

#ifdef HAS_C5_SD
  SPIClass sharedSPI(SPI);
  SDInterface sd_obj = SDInterface(&sharedSPI, SD_CS);
#endif

void setup()
{
  randomSeed(esp_random());
  
  #ifndef DEVELOPER
    esp_log_level_set("*", ESP_LOG_NONE);
  #endif
  
  #ifndef HAS_IDF_3
    esp_spiram_init();
  #endif

  Serial.begin(115200);

  while(!Serial)
    delay(10);

  #ifdef HAS_C5_SD
    sharedSPI.begin(SD_SCK, SD_MISO, SD_MOSI);
    delay(100);
  #endif

  #ifdef defined(MARAUDER_M5STICKC) && !defined(MARAUDER_M5STICKCP2)
    axp192_obj.begin();
  #endif

  #if defined(MARAUDER_M5STICKCP2) // Prevent StickCP2 from turning off when disconnect USB cable
    pinMode(POWER_HOLD_PIN, OUTPUT);
    digitalWrite(POWER_HOLD_PIN, HIGH);
  #endif
  
  // Early backlight off (before display init — use direct GPIO, not PWM)
  #ifdef HAS_SCREEN
    pinMode(TFT_BL, OUTPUT);
    digitalWrite(TFT_BL, LOW);
  #endif
  #if BATTERY_ANALOG_ON == 1
    pinMode(BATTERY_PIN, OUTPUT);
    pinMode(CHARGING_PIN, INPUT);
  #endif
  
  // Preset SPI CS pins to avoid bus conflicts
  #ifdef HAS_SCREEN
    digitalWrite(TFT_CS, HIGH);
  #endif
  
  #if defined(HAS_SD) && !defined(HAS_C5_SD)
    pinMode(SD_CS, OUTPUT);

    delay(10);
  
    digitalWrite(SD_CS, HIGH);

    delay(10);
  #endif

  //Serial.begin(115200);

  //while(!Serial)
  //  delay(10);

  Serial.println("ESP-IDF version is: " + String(esp_get_idf_version()));

  #ifdef HAS_PSRAM
    if (psramInit()) {
      Serial.println(F("PSRAM is correctly initialized"));
    } else {
      Serial.println(F("PSRAM not available"));
    }
  #endif

  #ifdef HAS_SIMPLEX_DISPLAY
    #if defined(HAS_SD)
      // Do some SD stuff
      if(!sd_obj.initSD())
        Serial.println(F("SD Card NOT Supported"));

    #endif
  #endif

  #ifdef HAS_SCREEN
    display_obj.RunSetup();
    display_obj.tft.setTextColor(TFT_WHITE, TFT_BLACK);
  #endif

  // Init PWM brightness AFTER display init (so ledcAttach overrides TFT_eSPI's pinMode)
  brightnessInit();
  backlightOff();

  uint8_t boot_shortcut = 0;
  #ifdef HAS_SCREEN
    #ifndef MARAUDER_CARDPUTER
      boot_shortcut = drawCyberpunkSplash();
    #else
      display_obj.tft.drawCentreString("ESP32 Marauder", TFT_HEIGHT/2, TFT_WIDTH * 0.20, 1);
      display_obj.tft.drawCentreString("JustCallMeKoko", TFT_HEIGHT/2, TFT_WIDTH * 0.38, 1);
      display_obj.tft.drawCentreString(display_obj.version_number, TFT_HEIGHT/2, TFT_WIDTH * 0.52, 1);
      display_obj.tft.setTextColor(TFT_CYAN, TFT_BLACK);
      display_obj.tft.drawCentreString("~ datboip edition ~", TFT_HEIGHT/2, TFT_WIDTH * 0.68, 1);
      display_obj.tft.setTextColor(TFT_WHITE, TFT_BLACK);
    #endif
  #endif


  backlightOn(); // Need this

  #ifdef HAS_SCREEN
    // Headless mode: hold SELECT during boot to disable screen
    // Disabled on V6/V6.1/CYD — C_BTN is GPIO0 (BOOT), always low after USB reset
    #if defined(HAS_BUTTONS) && (C_BTN != 0)
      if (c_btn.justPressed()) {
        display_obj.headless_mode = true;
        backlightOff();
        Serial.println(F("Headless Mode enabled"));
      }
    #endif
  #endif

  settings_obj.begin();

  buffer_obj = Buffer();

  #ifndef HAS_SIMPLEX_DISPLAY
    #if defined(HAS_SD)
      // Do some SD stuff
      if(!sd_obj.initSD())
        Serial.println(F("SD Card NOT Supported"));

    #endif
  #endif

  wifi_scan_obj.RunSetup();

  evil_portal_obj.setup();

  #ifdef HAS_BATTERY
    battery_obj.RunSetup();
  #endif

  #ifdef HAS_BATTERY
    battery_obj.battery_level = battery_obj.getBatteryLevel();
  #endif

  // Do some LED stuff
  #ifdef HAS_FLIPPER_LED
    flipper_led.RunSetup();
  #elif defined(XIAO_ESP32_S3)
    xiao_led.RunSetup();
  #elif defined(MARAUDER_M5STICKC)
    stickc_led.RunSetup();
  #else
    led_obj.RunSetup();
  #endif

  #ifdef HAS_GPS
    gps_obj.begin();
  #endif

  #ifdef HAS_SCREEN  
    display_obj.tft.setTextColor(TFT_WHITE, TFT_BLACK);
  #endif

  #ifdef HAS_SCREEN
    menu_function_obj.RunSetup();
  #endif

  wifi_scan_obj.StartScan(WIFI_SCAN_OFF);

  Serial.println(F("CLI Ready"));
  cli_obj.RunSetup();

  // Boot shortcuts: launch mode based on touch during splash
  #ifdef HAS_SCREEN
    if (boot_shortcut == 1) {
      // Wardrive
      Serial.println(F("[Boot] Wardrive shortcut"));
      display_obj.clearScreen();
      menu_function_obj.drawStatusBar();
      wifi_scan_obj.StartScan(WIFI_SCAN_WAR_DRIVE, TFT_GREEN);
    } else if (boot_shortcut == 2) {
      // AutoCycle
      Serial.println(F("[Boot] AutoCycle shortcut"));
      auto_cycle_obj.start();
      menu_function_obj.drawAutoCycleStatus();
    } else if (boot_shortcut == 3) {
      // Station Wardrive
      Serial.println(F("[Boot] Station Wardrive shortcut"));
      display_obj.clearScreen();
      menu_function_obj.drawStatusBar();
      wifi_scan_obj.StartScan(WIFI_SCAN_STATION_WAR_DRIVE, TFT_ORANGE);
    } else if (boot_shortcut == 4) {
      // BLE Scan
      Serial.println(F("[Boot] BLE Scan shortcut"));
      display_obj.clearScreen();
      menu_function_obj.drawStatusBar();
      wifi_scan_obj.StartScan(BT_SCAN_ALL, TFT_BLUE);
    }
  #endif
}


void loop()
{
  currentTime = millis();
  bool mini = false;

  #ifdef SCREEN_BUFFER
    #ifndef HAS_ILI9341
      mini = true;
    #endif
  #endif

  #if (defined(HAS_ILI9341) && !defined(MARAUDER_CYD_2USB))
    #ifdef HAS_BUTTONS
      if (c_btn.isHeld()) {
        if (menu_function_obj.disable_touch)
          menu_function_obj.disable_touch = false;
        else
          menu_function_obj.disable_touch = true;

        menu_function_obj.updateStatusBar();

        while (!c_btn.justReleased())
          delay(1);
      }
    #endif
  #endif

  // Update all of our objects
  cli_obj.main(currentTime);
  #ifdef HAS_SCREEN
    display_obj.main(wifi_scan_obj.currentScanMode);
  #endif
  wifi_scan_obj.main(currentTime);
  auto_cycle_obj.main(currentTime);
  // AutoCycle status is CLI-only; no display overlay

  #ifdef HAS_GPS
    gps_obj.main();
  #endif
  
  // Detect SD card
  #if defined(HAS_SD)
    sd_obj.main();
  #endif

  // Save buffer to SD and/or serial
  buffer_obj.save();

  #ifdef HAS_BATTERY
    battery_obj.main(currentTime);
  #endif
  settings_obj.main(currentTime);
  if ((wifi_scan_obj.currentScanMode != WIFI_PACKET_MONITOR) ||
      (mini)) {
    #ifdef HAS_SCREEN
      menu_function_obj.main(currentTime);
    #endif
  }
  #ifdef HAS_FLIPPER_LED
    flipper_led.main();
  #elif defined(XIAO_ESP32_S3)
    xiao_led.main();
  #elif defined(MARAUDER_M5STICKC)
    stickc_led.main();
  #else
    led_obj.main(currentTime);
  #endif

  #ifdef HAS_SCREEN
    delay(1);
  #else
    delay(50);
  #endif
}
