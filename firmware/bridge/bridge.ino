// firmware/bridge/bridge.ino - ESP32-S3 safety bridge: laptop (USB serial) -> hoverboard master board (UART)
//
// Laptop side follows docs/INTERFACES.md "Laptop to ESP32 bridge" exactly:
//   in : "C,<seq>,<left>,<right>\n"  wheel speeds in firmware units (+-1000 scale), every 50 ms
//        "S,<seq>\n"                 explicit stop
//   out: "D,<distance_cm>,<state>\n" every 50 ms, state = OK | OBSTACLE | WATCHDOG
// Rules enforced HERE, never trusted to the laptop:
//   - no valid line for BRIDGE_WATCHDOG_MS (200 ms)  -> speed zero (state WATCHDOG) until lines resume
//   - malformed line                                  -> speed zero immediately
//   - 0 < distance_cm < OBSTACLE_STOP_CM and (left + right) > 0 (net forward) -> speed zero (state OBSTACLE);
//     in-place turns and reverse stay allowed so the rider is never trapped
//   - every speed clamped again to MAX_SPEED
//
// Hoverboard side: VERIFIED 2026-11-14 against the flashed firmware (RoboDurden Hoverboard-Firmware-Hack-Gen2.x-GD32,
// REMOTE_UART, file Src/remoteUart.c). This REPLACES the provisional 0xABCD/115200 format in docs/INTERFACES.md:
//   19200 baud 8N1, 9 bytes, little-endian, packed:
//   uint8 '/' | int16 speed | int16 steer | uint8 wStateMaster | uint8 wStateSlave | uint16 CRC16
//   CRC16 = CCITT poly 0x1021, init 0, over the first 7 bytes. The board stops by itself after 500 ms without a frame.
//
// TWO WIRING MODES (pick with DUAL_SINGLE below):
//  DUAL_SINGLE 1 (default, no soldering): each board runs e235_single_usart1.bin and is driven through ITS OWN 4-pin
//    master-slave plug (USART1: PA2 = board TX, PA3 = board RX). The original cable between the boards is NOT used.
//      LEFT  board: ESP32 GPIO17 (TX) -> PA3 pin,  ESP32 GPIO18 (RX) <- PA2 pin,  GND -- GND
//      RIGHT board: ESP32 GPIO15 (TX) -> PA3 pin,  ESP32 GPIO16 (RX) <- PA2 pin,  GND -- GND
//    Each board gets its own wheel speed (steer = 0). LEFT_SIGN / RIGHT_SIGN fix mirrored mounting.
//  DUAL_SINGLE 0: one master board (e235_master.bin) on GPIO17/18, slave via the original cable, speed+steer mixing.
//    Needs the board's PB6/PB7 pads, which on the YK187 are NOT connected (R10/R11 not fitted) -> needs soldering.
//  NEVER connect a plug's VCC / 15 V pin to the ESP32.
// HC-SR04: TRIG -> GPIO4, ECHO -> GPIO5 THROUGH A VOLTAGE DIVIDER (ECHO is 5 V; e.g. 1k to GPIO5, 2k from GPIO5 to GND).
//
// Humans compile and upload (Arduino IDE, board "ESP32S3 Dev Module"). Agents never upload.

#include <Arduino.h>

// ---- constants from docs/INTERFACES.md ----
#define BRIDGE_WATCHDOG_MS 200
#define MAX_SPEED 150
#define OBSTACLE_STOP_CM 50
#define LINE_PERIOD_MS 50          // D line + hoverboard frame period

// ---- hoverboard wiring mode and pins (change here if your shield uses others) ----
#define DUAL_SINGLE 1              // 1 = two boards, one UART each (see top); 0 = master/slave on one UART
#define HOVER_TX_PIN 17            // LEFT board (or the master board when DUAL_SINGLE 0)
#define HOVER_RX_PIN 18
#define HOVER2_TX_PIN 15           // RIGHT board (DUAL_SINGLE 1 only)
#define HOVER2_RX_PIN 16
#define LEFT_SIGN 1                // VERIFY wheels-up: set to -1 if that wheel turns backwards on a forward command
#define RIGHT_SIGN 1               // (the two motors are mirror images, so one of them usually needs -1)
#define HOVER_BAUD 19200
#define US_TRIG_PIN 4
#define US_ECHO_PIN 5
#define US_ECHO_TIMEOUT_US 20000   // ~20 ms, ~340 cm; keeps pulseIn from stalling the watchdog loop

int16_t cmdLeft = 0, cmdRight = 0;   // last valid command (already clamped)
uint32_t lastValidLineMs = 0;
uint32_t lastPeriodMs = 0;
int distanceCm = -1;
char lineBuf[64];
uint8_t lineLen = 0;

// CRC16-CCITT (poly 0x1021, init 0) - identical to CalcCRC() in the hoverboard firmware.
uint16_t calcCRC(const uint8_t *ptr, int count) {
  uint16_t crc = 0;
  while (--count >= 0) {
    crc = crc ^ (uint16_t)(*ptr++) << 8;
    for (uint8_t i = 0; i < 8; i++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
  }
  return crc;
}

// Hoverboard frame encoder (the only place that knows the frame format).
// Known-good examples (computed with the same CRC, little-endian):
//   speed=100 steer=0   -> 2F 64 00 00 00 00 00 A6 BD
//   speed=0   steer=0   -> 2F 00 00 00 00 00 00 1F E4
//   speed=-50 steer=25  -> 2F CE FF 19 00 00 00 F3 68
void sendHoverFrame(HardwareSerial &port, int16_t speed, int16_t steer) {
  uint8_t f[9];
  f[0] = '/';
  f[1] = speed & 0xFF;  f[2] = (speed >> 8) & 0xFF;
  f[3] = steer & 0xFF;  f[4] = (steer >> 8) & 0xFF;
  f[5] = 0;             // wStateMaster (LED/disable bits) - unused
  f[6] = 0;             // wStateSlave
  uint16_t crc = calcCRC(f, 7);
  f[7] = crc & 0xFF;    f[8] = crc >> 8;
  port.write(f, 9);
}

int16_t clampSpeed(long v) { return (int16_t)constrain(v, -MAX_SPEED, MAX_SPEED); }

// Parse one line. Returns true for a valid C or S line. Anything else is malformed.
bool parseLine(const char *s) {
  long seq, l, r;
  char tail;
  if (s[0] == 'C' && sscanf(s, "C,%ld,%ld,%ld%c", &seq, &l, &r, &tail) == 3) {
    cmdLeft = clampSpeed(l);
    cmdRight = clampSpeed(r);
    return true;
  }
  if (s[0] == 'S' && sscanf(s, "S,%ld%c", &seq, &tail) == 1) {
    cmdLeft = cmdRight = 0;
    return true;
  }
  return false;
}

void readLaptop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuf[lineLen] = 0;
      if (lineLen && parseLine(lineBuf)) lastValidLineMs = millis();
      else { cmdLeft = cmdRight = 0; }           // malformed -> zero immediately
      lineLen = 0;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {                                      // overlong line -> malformed
      lineLen = 0;
      cmdLeft = cmdRight = 0;
    }
  }
}

int readDistanceCm() {
  digitalWrite(US_TRIG_PIN, LOW);  delayMicroseconds(2);
  digitalWrite(US_TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(US_TRIG_PIN, LOW);
  unsigned long us = pulseIn(US_ECHO_PIN, HIGH, US_ECHO_TIMEOUT_US);
  if (us == 0) return -1;                         // timeout = out of range, never 0 cm
  int cm = (int)(us / 58);
  return cm > 0 ? cm : -1;
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(HOVER_BAUD, SERIAL_8N1, HOVER_RX_PIN, HOVER_TX_PIN);
#if DUAL_SINGLE
  Serial2.begin(HOVER_BAUD, SERIAL_8N1, HOVER2_RX_PIN, HOVER2_TX_PIN);
#endif
  pinMode(US_TRIG_PIN, OUTPUT);
  pinMode(US_ECHO_PIN, INPUT);
  lastValidLineMs = millis() - BRIDGE_WATCHDOG_MS - 1;   // start in WATCHDOG (stopped) until the laptop talks
}

void loop() {
  readLaptop();
  uint32_t now = millis();
  if (now - lastPeriodMs < LINE_PERIOD_MS) return;
  lastPeriodMs = now;

  distanceCm = readDistanceCm();

  int16_t left = cmdLeft, right = cmdRight;
  const char *state = "OK";
  if (now - lastValidLineMs > BRIDGE_WATCHDOG_MS) {
    left = right = 0;
    state = "WATCHDOG";
  } else if (distanceCm > 0 && distanceCm < OBSTACLE_STOP_CM && (left + right) > 0) {
    left = right = 0;                             // net forward into an obstacle -> stop (turns/reverse allowed)
    state = "OBSTACLE";
  }

#if DUAL_SINGLE
  // One board per wheel: each gets its own speed, steer 0. Note the firmware treats |speed| < 50 as stop.
  sendHoverFrame(Serial1, LEFT_SIGN * left, 0);
  sendHoverFrame(Serial2, RIGHT_SIGN * right, 0);
#else
  // docs/INTERFACES.md: speed = (left + right) / 2, steer = (right - left) / 2. Sign conventions on the real chair:
  // VERIFY with wheels in the air; flip SPEED_COEFFICIENT / STEER_COEFFICIENT in the firmware config if reversed.
  int16_t speed = (left + right) / 2;
  int16_t steer = (right - left) / 2;
  sendHoverFrame(Serial1, speed, steer);
#endif

  Serial.printf("D,%d,%s\n", distanceCm, state);
}
