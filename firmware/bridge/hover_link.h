#pragma once
#include <Arduino.h>

#define FEEDBACK_LEN 22   // hoverboard feedback frame: 0xABCD + 6 x int16 + 2 x int32 ... + CRC = 22 bytes

// One hoverboard board link with automatic TX/RX detection (see bridge.ino).
struct HoverLink {
  HardwareSerial *ser;
  const char *name;
  int pinA, pinB, parkPin;
  bool locked, swapped;
  uint32_t tSwitch, lastFrameMs;
  uint8_t fb[FEEDBACK_LEN];
  uint8_t fi, prev;
  float volt;
};
