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
// CYBERPUNK BOOT SPLASH — matches marauder_preview.html style
// ============================================================
#ifdef HAS_SCREEN
void drawCyberpunkSplash() {
  TFT_eSPI& tft = display_obj.tft;
  const uint16_t W = TFT_WIDTH;   // 240
  const uint16_t H = TFT_HEIGHT;  // 320
  const uint16_t cx = W / 2;

  // Colors
  const uint16_t CYAN    = 0x07FF;
  const uint16_t MAGENTA = 0xF81F;
  const uint16_t DKCYAN  = 0x0410;
  const uint16_t DIMCYAN = 0x0208;
  const uint16_t DIMGRAY = 0x39E7;

  tft.fillScreen(TFT_BLACK);

  // Turn backlight on so the animation is visible!
  backlightOn();

  // === Phase 1: Static accent lines (top & bottom, avoid corners/traces) ===
  // Top lines: y 40-100, x constrained to middle 60% to avoid corner traces
  for (int g = 0; g < 3; g++) {
    int gy = 40 + g * 22;
    int gw = 15 + random(0, 30);
    int gx = 50 + random(0, W - 100 - gw);  // center area only
    tft.fillRect(gx, gy, gw, 1, (g % 2 == 0) ? CYAN : MAGENTA);
  }
  // Bottom lines: y 245-290, same center constraint
  for (int g = 0; g < 3; g++) {
    int gy = 245 + g * 18;
    int gw = 15 + random(0, 30);
    int gx = 50 + random(0, W - 100 - gw);
    tft.fillRect(gx, gy, gw, 1, (g % 2 == 0) ? MAGENTA : CYAN);
  }
  delay(120);

  // === Phase 2: Border draws in from corners ===
  const int m = 8; // margin
  const int bw = W - m * 2;
  const int bh = H - m * 2;
  for (int step = 0; step <= 20; step++) {
    float prog = step / 20.0;
    int topLen = bw * prog;
    int sideLen = bh * prog;
    // Top edge left to right
    tft.drawFastHLine(m, m, topLen, CYAN);
    // Bottom edge right to left
    tft.drawFastHLine(W - m - topLen, H - m, topLen, CYAN);
    // Left edge top to bottom
    tft.drawFastVLine(m, m, sideLen, CYAN);
    // Right edge bottom to top
    tft.drawFastVLine(W - m - 1, H - m - sideLen, sideLen, CYAN);
    delay(15);
  }
  delay(60);

  // === Phase 3: Corner chevrons in magenta ===
  const int cs = 18;
  // Top-left
  tft.drawFastHLine(m, m, cs, MAGENTA);
  tft.drawFastVLine(m, m, cs, MAGENTA);
  // Top-right
  tft.drawFastHLine(W - m - cs, m, cs, MAGENTA);
  tft.drawFastVLine(W - m - 1, m, cs, MAGENTA);
  // Bottom-left
  tft.drawFastHLine(m, H - m - 1, cs, MAGENTA);
  tft.drawFastVLine(m, H - m - cs, cs, MAGENTA);
  // Bottom-right
  tft.drawFastHLine(W - m - cs, H - m - 1, cs, MAGENTA);
  tft.drawFastVLine(W - m - 1, H - m - cs, cs, MAGENTA);
  delay(80);

  // === Phase 4: Title — "M A R A U D E R" typewriter ===
  const uint16_t titleY = 125;
  const char* letters = "MARAUDER";
  const int numChars = 8;

  tft.setTextColor(CYAN, TFT_BLACK);
  // Build up the spaced string one letter at a time (typewriter)
  char spaced[24]; // "M A R A U D E R" = 15 chars + null
  for (int i = 0; i < numChars; i++) {
    // Build string so far with spaces between letters
    int pos = 0;
    for (int j = 0; j <= i; j++) {
      if (j > 0) spaced[pos++] = ' ';
      spaced[pos++] = letters[j];
    }
    spaced[pos] = '\0';
    // Clear title area (inside border margins only)
    tft.fillRect(m + 2, titleY, W - (m + 2) * 2, 20, TFT_BLACK);
    tft.drawCentreString(spaced, cx, titleY, 2);
    delay(55);
  }
  delay(80);

  // === Phase 5: Magenta underline sweeps out from center ===
  const uint16_t underY = titleY + 22;
  const int underMaxW = 160;
  for (int step = 0; step <= 15; step++) {
    int hw = (underMaxW / 2) * step / 15;
    tft.drawFastHLine(cx - hw, underY, hw * 2, MAGENTA);
    delay(12);
  }
  delay(80);

  // === Phase 6: "datboip edition" fades in (simulated with color steps) ===
  const uint16_t edY = underY + 14;
  // Draw dim first, then bright
  tft.setTextColor(0x3808, TFT_BLACK);  // very dim magenta
  tft.drawCentreString("datboip edition", cx, edY, 2);
  delay(60);
  tft.setTextColor(0x780F, TFT_BLACK);  // medium magenta
  tft.drawCentreString("datboip edition", cx, edY, 2);
  delay(60);
  tft.setTextColor(MAGENTA, TFT_BLACK);  // full magenta
  tft.drawCentreString("datboip edition", cx, edY, 2);
  delay(80);

  // === Phase 7: Version + credit ===
  const uint16_t verY = edY + 22;
  tft.setTextColor(DIMGRAY, TFT_BLACK);
  tft.drawCentreString(display_obj.version_number, cx, verY, 1);
  delay(30);
  tft.setTextColor(DKCYAN, TFT_BLACK);
  tft.drawCentreString("by JustCallMeKoko", cx, verY + 12, 1);
  delay(40);

  // === Phase 8: Circuit traces from corners ===
  // Top-left: horizontal then down then right
  tft.drawFastHLine(m + cs, m, 20, DKCYAN);
  tft.drawFastVLine(m + cs + 20, m, 12, DKCYAN);
  tft.drawFastHLine(m + cs + 20, m + 12, 15, DKCYAN);
  tft.fillCircle(m + cs + 20, m, 2, MAGENTA);      // node
  tft.fillCircle(m + cs + 35, m + 12, 2, MAGENTA);  // node
  // Top-right mirror
  tft.drawFastHLine(W - m - cs - 20, m, 20, DKCYAN);
  tft.drawFastVLine(W - m - cs - 20, m, 12, DKCYAN);
  tft.drawFastHLine(W - m - cs - 35, m + 12, 15, DKCYAN);
  tft.fillCircle(W - m - cs - 20, m, 2, MAGENTA);
  tft.fillCircle(W - m - cs - 35, m + 12, 2, MAGENTA);
  // Bottom-left
  tft.drawFastHLine(m + cs, H - m - 1, 20, DKCYAN);
  tft.drawFastVLine(m + cs + 20, H - m - 12, 12, DKCYAN);
  tft.fillCircle(m + cs + 20, H - m - 1, 2, MAGENTA);
  // Bottom-right
  tft.drawFastHLine(W - m - cs - 20, H - m - 1, 20, DKCYAN);
  tft.drawFastVLine(W - m - cs - 20, H - m - 12, 12, DKCYAN);
  tft.fillCircle(W - m - cs - 20, H - m - 1, 2, MAGENTA);
  delay(80);

  // === Phase 9: Feature tags at bottom ===
  const uint16_t tagY = H - m - 35;
  tft.setTextColor(DKCYAN, TFT_BLACK);
  tft.drawCentreString("AutoCycle | PWM Dim | BigTouch", cx, tagY, 1);

  delay(100);

  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  delay(500);
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

  #ifdef HAS_SCREEN
    #ifndef MARAUDER_CARDPUTER
      drawCyberpunkSplash();
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
    delay(2000); // Show splash screen
    menu_function_obj.RunSetup();
  #endif

  /*char ssidBuf[64] = {0};  // or prefill with existing SSID
  if (keyboardInput(ssidBuf, sizeof(ssidBuf), "Enter SSID")) {
    // user pressed OK
    Serial.println(ssidBuf);
  } else {
    Serial.println(F("User exited keyboard"));
  }

  menu_function_obj.changeMenu(menu_function_obj.current_menu);*/

  wifi_scan_obj.StartScan(WIFI_SCAN_OFF);
  
  Serial.println(F("CLI Ready"));
  cli_obj.RunSetup();
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
