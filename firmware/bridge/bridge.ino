// bridge.ino - ESP32-S3 safety bridge: laptop (USB serial) -> hoverboard boards (UART)
//
// Laptop side follows docs/INTERFACES.md "Laptop to ESP32 bridge" exactly:
//   in : "C,<seq>,<left>,<right>\n"  wheel speeds in firmware units (+-1000 scale), every 50 ms
//        "S,<seq>\n"                 explicit stop
//   out: "D,<distance_cm>,<state>\n" every 50 ms, state = OK | OBSTACLE | WATCHDOG
//   (plus, only when a board link changes, one info line starting with '#'. Laptop parsers must ignore '#' lines.)
// Rules enforced HERE, never trusted to the laptop:
//   - no valid line for BRIDGE_WATCHDOG_MS (200 ms)  -> speed zero (state WATCHDOG) until lines resume
//   - malformed line                                  -> speed zero immediately
//   - 0 < distance_cm < OBSTACLE_STOP_CM and (left + right) > 0 (net forward) -> speed zero (state OBSTACLE)
//   - every speed clamped again to MAX_SPEED
//
// Hoverboard side (VERIFIED 2026-11-14 with the debugger: firmware e235_single_usart1 runs, USART1 = 19200 baud and
// sends feedback frames): RoboDurden Hoverboard-Firmware-Hack-Gen2.x-GD32, REMOTE_UART, 19200 8N1.
//   command  9 bytes: '/' | int16 speed | int16 steer | u8 0 | u8 0 | u16 CRC16-CCITT(poly 0x1021, init 0) over 7 bytes
//   feedback 22 bytes every 100 ms: 0xABCD | speedL | speedR | volt | ampL | ampR | int32 odomL | int32 odomR | CRC
//   The board stops by itself after 500 ms without a valid command.
//
// AUTO TX/RX: each board gets TWO ESP32 data wires, in ANY order. The ESP32 listens (without sending) on one wire,
// then the other, until it hears the board's feedback frames; then it knows which wire is the board's TX, makes the
// other one its own TX and starts driving. Until a board is found, nothing is sent to it (wheel stays off).
//
// WIRING (each board runs e235_single_usart1.bin):
//   LEFT  board (master): ESP32 GPIO17 + GPIO18 -> the two 3.3 V data pins of its 5-pin plug (any order), GND -> GND pin
//   RIGHT board (slave) : ESP32 GPIO15 + GPIO16 -> the two 3.3 V data pins of its 5-pin plug (any order), GND -> GND pin
//   NEVER connect the plug's ~14 V pin.
// HC-SR04: TRIG -> GPIO4, ECHO -> GPIO5 THROUGH A VOLTAGE DIVIDER (ECHO is 5 V; e.g. 1k to GPIO5, 2k from GPIO5 to GND).
//
// Humans compile and upload (Arduino IDE, board "ESP32S3 Dev Module"). Agents never upload.

#include <Arduino.h>
#include "hover_link.h"

// ---- constants from docs/INTERFACES.md ----
#define BRIDGE_WATCHDOG_MS 200
#define MAX_SPEED 910              // 91% of full motor power (firmware range +-1000)
#define OBSTACLE_STOP_CM 50
#define LINE_PERIOD_MS 50          // D line + hoverboard frame period

// ---- hoverboard wiring ----
#define LEFT_PIN_A 18              // the two wires to the LEFT board, any order
#define LEFT_PIN_B 17
#define RIGHT_PIN_A 16             // the two wires to the RIGHT board, any order
#define RIGHT_PIN_B 15
#define LEFT_PARK_PIN 47           // unused GPIOs where the UART TX is parked while listening
#define RIGHT_PARK_PIN 21
#define LEFT_SIGN 1                // VERIFY wheels-up: set to -1 if that wheel turns backwards on a forward command
#define RIGHT_SIGN -1              // (the two motors are mirror images, so one of them usually needs -1)
#define HOVER_BAUD 19200
#define DETECT_WINDOW_MS 350       // listen this long on one wire before trying the other (board sends every 100 ms)
#define LINK_LOST_MS 1500          // no feedback for this long -> search again (and stop sending)
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

// Known-good examples: speed=100 steer=0 -> 2F 64 00 00 00 00 00 A6 BD ; speed=0 -> 2F 00 00 00 00 00 00 1F E4
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

// ---- one board link with automatic TX/RX detection ----
// struct HoverLink is in hover_link.h (Arduino needs types used in function signatures in a header)

HoverLink leftLink  = {&Serial1, "LEFT",  LEFT_PIN_A,  LEFT_PIN_B,  LEFT_PARK_PIN,  false, false, 0, 0, {0}, 0, 0, 0};
HoverLink rightLink = {&Serial2, "RIGHT", RIGHT_PIN_A, RIGHT_PIN_B, RIGHT_PARK_PIN, false, false, 0, 0, {0}, 0, 0, 0};

int linkRx(const HoverLink &l) { return l.swapped ? l.pinB : l.pinA; }
int linkTx(const HoverLink &l) { return l.swapped ? l.pinA : l.pinB; }

void linkListen(HoverLink &l) {                 // listen only; our TX parked on an unused pin
  l.ser->end();
  pinMode(l.pinA, INPUT);
  pinMode(l.pinB, INPUT);
  l.ser->begin(HOVER_BAUD, SERIAL_8N1, linkRx(l), l.parkPin);
  l.fi = 0; l.prev = 0;
}

void linkLock(HoverLink &l, uint32_t now) {     // board found: drive it
  l.ser->end();
  l.ser->begin(HOVER_BAUD, SERIAL_8N1, linkRx(l), linkTx(l));
  l.locked = true;
  l.lastFrameMs = now;
  l.fi = 0; l.prev = 0;
  Serial.printf("# %s board found (battery %.1f V): board TX -> GPIO%d, board RX <- GPIO%d\n",
                l.name, l.volt, linkRx(l), linkTx(l));
}

void linkPoll(HoverLink &l, uint32_t now) {
  while (l.ser->available()) {
    uint8_t b = l.ser->read();
    if (l.fi > 0) {
      l.fb[l.fi++] = b;
      if (l.fi == FEEDBACK_LEN) {
        l.fi = 0;
        uint16_t crc = l.fb[FEEDBACK_LEN - 2] | (l.fb[FEEDBACK_LEN - 1] << 8);
        if (calcCRC(l.fb, FEEDBACK_LEN - 2) == crc) {
          l.volt = (uint16_t)(l.fb[6] | (l.fb[7] << 8)) / 100.0f;
          l.lastFrameMs = now;
          if (!l.locked) { linkLock(l, now); return; }
        }
      }
    } else if (l.prev == 0xCD && b == 0xAB) {   // 0xABCD start, little-endian
      l.fb[0] = 0xCD; l.fb[1] = 0xAB; l.fi = 2;
    }
    l.prev = b;
  }
  if (!l.locked) {
    if (now - l.tSwitch >= DETECT_WINDOW_MS) {   // nothing heard on this wire: try the other one
      l.tSwitch = now;
      l.swapped = !l.swapped;
      linkListen(l);
    }
  } else if (now - l.lastFrameMs > LINK_LOST_MS) {
    l.locked = false;
    l.tSwitch = now;
    Serial.printf("# %s board lost, searching again\n", l.name);
    linkListen(l);
  }
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
  pinMode(US_TRIG_PIN, OUTPUT);
  pinMode(US_ECHO_PIN, INPUT);
  linkListen(leftLink);
  linkListen(rightLink);
  lastValidLineMs = millis() - BRIDGE_WATCHDOG_MS - 1;   // start in WATCHDOG (stopped) until the laptop talks
}

void loop() {
  readLaptop();
  uint32_t now = millis();
  linkPoll(leftLink, now);
  linkPoll(rightLink, now);
  if (now - lastPeriodMs < LINE_PERIOD_MS) return;
  lastPeriodMs = now;

  distanceCm = readDistanceCm();

  int16_t left = cmdLeft, right = cmdRight;
  const char *state = "OK";
  static bool wasWatchdog = true;
  bool watchdog = now - lastValidLineMs > BRIDGE_WATCHDOG_MS;
  if (wasWatchdog && !watchdog) {                 // laptop just (re)started talking: report the board links once
    Serial.printf("# LEFT board %s, RIGHT board %s\n", leftLink.locked ? "OK" : "NOT FOUND",
                  rightLink.locked ? "OK" : "NOT FOUND");
  }
  wasWatchdog = watchdog;
  if (watchdog) {
    left = right = 0;
    state = "WATCHDOG";
  } else if (distanceCm > 0 && distanceCm < OBSTACLE_STOP_CM && (left + right) > 0) {
    left = right = 0;                             // net forward into an obstacle -> stop (turns/reverse allowed)
    state = "OBSTACLE";
  }

  // One board per wheel: each gets its own speed, steer 0. The firmware treats |speed| < 50 as stop.
  if (leftLink.locked)  sendHoverFrame(*leftLink.ser,  LEFT_SIGN * left, 0);
  if (rightLink.locked) sendHoverFrame(*rightLink.ser, RIGHT_SIGN * right, 0);

  Serial.printf("D,%d,%s\n", distanceCm, state);
}
