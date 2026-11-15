"""
chair.py - drive the SSVEP hoverboard wheelchair from Python.

Quick use (full docs: README.md in this folder):

    from chair import Chair

    with Chair("COM4") as chair:
        chair.forward(200, 2)       # speed 200 for 2 seconds, then stop
        chair.turn_left(150, 1)     # spin left in place for 1 second
        chair.backward(200, 2)
        chair.turn_right(150, 1)

How the commands reach the wheels:

    this script --USB serial 115200--> ESP32-S3 bridge (bridge/bridge.ino)
                --UART 19200 x2-->     left board (master) + right board (slave), GD32E235 hoverboard firmware
                -->                    hub motors

Speed unit = the hoverboard firmware unit: -1000 .. +1000 (1000 = 100 % motor power, NOT km/h).
    |speed| < ~50 does nothing (firmware dead zone). Positive = forward for both wheels
    (the bridge already flips the mirrored right motor, so callers never deal with signs).

Speed limits, applied in this order (the lowest one wins):
    1. Chair(max_speed=...)   here, default 850
    2. MAX_SPEED in bridge.ino on the ESP32 (910 at time of writing)
    3. firmware range +-1000 and its 15 A motor current limit

Safety built in:
    - A background thread re-sends the current command every 50 ms. If this program ends, crashes or freezes,
      the ESP32 stops the wheels after 200 ms (bridge state WATCHDOG); the boards stop after 500 ms by themselves.
    - Speed changes are ramped (accel), so the chair does not jerk the rider. stop() is immediate
      (the firmware itself brakes softly over about a second).
    - Ctrl+C during a timed move stops the chair. Leaving a "with Chair(...)" block stops the chair.
    - The ESP32 blocks forward motion while its ultrasonic sensor reads < 50 cm (bridge state OBSTACLE).
"""

import atexit
import threading
import time

import serial  # pip install pyserial

# ---------------------------------------------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------------------------------------------
DEFAULT_PORT = "COM4"        # Windows: Device Manager -> Ports. macOS/Linux: /dev/cu.usbmodem... or /dev/ttyACM0
# The two wheels are wired to the opposite bridge channels from what this library assumed: in the live test (Sun Nov 15)
# forward and backward were right, but turn_left spun the chair to the RIGHT. Equal speeds hide a swap; opposite speeds
# show it. True = swap left/right in drive(), so turn_left really is left wheel back + right wheel forward.
SWAP_SIDES = True
DEFAULT_MAX_SPEED = 850      # 85 % power. The motors handle full power fine; this cap is for the rider's safety.
DEFAULT_ACCEL = 60           # max speed change per 50 ms tick when speeding up -> 0..850 in about 0.7 s
SEND_INTERVAL_S = 0.05       # 20 commands/s. Must stay well below the bridge watchdog (200 ms).
BAUD = 115200                # USB serial speed of the ESP32 bridge
STARTUP_WAIT_S = 2.0         # the ESP32 may reboot when the port opens; give it time to find both boards


class Chair:
    """One connection to the ESP32 bridge. Create one Chair per program (only one program can open the COM port)."""

    def __init__(self, port=DEFAULT_PORT, max_speed=DEFAULT_MAX_SPEED, accel=DEFAULT_ACCEL, verbose=True):
        """
        port       serial port of the ESP32 (e.g. "COM4"). Close the Arduino Serial Monitor first.
        max_speed  hard cap for every command (0..1000). Requests above it are clamped, never refused.
        accel      max increase of |speed| per 50 ms tick. None or 0 = no ramp (instant speed changes).
        verbose    print the bridge's '#' info lines (board found / lost) and obstacle warnings.
        """
        self.max_speed = max(0, min(1000, int(max_speed)))
        self.accel = int(accel) if accel else 0
        self.verbose = verbose

        # Status reported by the bridge (updated ~20x per second by the reader thread)
        self.state = "?"          # "OK" | "OBSTACLE" | "WATCHDOG"  ("?" = nothing received yet)
        self.distance_cm = 0      # ultrasonic distance in cm, 0 = no echo / no sensor

        self._target = [0, 0]     # what the caller asked for (left, right), already clamped
        self._current = [0, 0]    # what is being sent right now (ramps toward _target)
        self._seq = 0             # sequence number in every line (protocol requirement, used for debugging)
        self._lock = threading.Lock()
        self._running = True

        self._ser = serial.serial_for_url(port, BAUD, timeout=0.1)
        time.sleep(STARTUP_WAIT_S)
        self._ser.reset_input_buffer()

        threading.Thread(target=self._reader_loop, daemon=True).start()
        threading.Thread(target=self._sender_loop, daemon=True).start()
        atexit.register(self.close)            # stop the wheels even if the caller forgets close()
        self._wait_for_bridge()

    # ===========================================================================================================
    # Simple moves. speed: 0..max_speed (sign is handled for you). seconds: block that long, then stop.
    # seconds=None: keep moving until the next command or stop() (use this inside your own control loop).
    # ===========================================================================================================
    def forward(self, speed, seconds=None):
        """Drive straight forward."""
        self.drive(abs(speed), abs(speed), seconds)

    def backward(self, speed, seconds=None):
        """Drive straight backward."""
        self.drive(-abs(speed), -abs(speed), seconds)

    def turn_left(self, speed, seconds=None):
        """Spin in place to the left (counter-clockwise seen from above): left wheel back, right wheel forward."""
        self.drive(-abs(speed), abs(speed), seconds)

    def turn_right(self, speed, seconds=None):
        """Spin in place to the right (clockwise seen from above): left wheel forward, right wheel back."""
        self.drive(abs(speed), -abs(speed), seconds)

    def stop(self):
        """Stop both wheels immediately (no ramp). Safe to call any time, any number of times."""
        with self._lock:
            self._target = [0, 0]
            self._current = [0, 0]
        self._send_current()

    # ===========================================================================================================
    # General control
    # ===========================================================================================================
    def drive(self, left, right, seconds=None):
        """
        Set each wheel's speed separately (-max_speed..+max_speed, positive = forward).
        Equal values = straight, different values = curve, opposite values = spin in place.
        With seconds: blocks for that long (ramp-up time included), then stops. Ctrl+C also stops.
        """
        if SWAP_SIDES:
            left, right = right, left  # wheels are on the opposite bridge channels (see SWAP_SIDES)
        with self._lock:
            self._target = [self._clamp(left), self._clamp(right)]
            self._step_toward_target()          # apply the first ramp step right away (no 50 ms lag)
        self._send_current()
        if seconds is not None:
            try:
                time.sleep(max(0.0, seconds))
            finally:                            # runs on normal end AND on Ctrl+C / exceptions
                self.stop()

    def close(self):
        """Stop the chair and release the COM port. Called automatically at program exit and by 'with'."""
        if not self._running:
            return
        try:
            for _ in range(3):                  # a few stop lines in case one gets lost
                self.stop()
                time.sleep(SEND_INTERVAL_S)
        except serial.SerialException:
            pass
        self._running = False
        time.sleep(0.1)                         # let the threads notice before the port disappears
        try:
            self._ser.close()
        except serial.SerialException:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ===========================================================================================================
    # Internals
    # ===========================================================================================================
    def _clamp(self, v):
        return max(-self.max_speed, min(self.max_speed, int(v)))

    def _step_toward_target(self):
        """Move _current one ramp step (accel) toward _target. Caller holds the lock.
        Every change is ramped: speeding up, slowing down, and reversing (which passes through zero).
        Only stop() skips the ramp and goes to zero at once."""
        for i in range(2):
            t, c = self._target[i], self._current[i]
            if not self.accel or abs(t - c) <= self.accel:
                self._current[i] = t
            else:
                self._current[i] = c + self.accel if t > c else c - self.accel

    def _send_current(self):
        """Send one protocol line with the current speeds. 'S' when both are zero, otherwise 'C'."""
        with self._lock:
            l, r = self._current
            self._seq += 1
            line = f"C,{self._seq},{l},{r}\n" if (l or r) else f"S,{self._seq}\n"
            self._ser.write(line.encode())

    def _sender_loop(self):
        """Every 50 ms: advance the ramp and re-send. This is also the keep-alive for the bridge watchdog."""
        while self._running:
            try:
                with self._lock:
                    self._step_toward_target()
                self._send_current()
            except serial.SerialException:
                print("[chair] serial port lost - the bridge watchdog has stopped the wheels")
                return
            time.sleep(SEND_INTERVAL_S)

    def _reader_loop(self):
        """Read the bridge's lines: 'D,<cm>,<state>' status and '#...' info messages."""
        while self._running:
            try:
                line = self._ser.readline().decode(errors="ignore").strip()
            except serial.SerialException:
                return
            if line.startswith("#"):
                if self.verbose:
                    print("[bridge]", line[1:].strip())
            elif line.startswith("D,"):
                parts = line.split(",")
                if len(parts) != 3:
                    continue
                try:
                    self.distance_cm = int(parts[1])
                except ValueError:
                    pass
                if self.verbose and parts[2] == "OBSTACLE" and self.state != "OBSTACLE":
                    print(f"[chair] OBSTACLE at {self.distance_cm} cm - forward motion blocked by the bridge")
                self.state = parts[2]

    def _wait_for_bridge(self, timeout=3.0):
        """Wait until the first status line arrives, so the caller knows the bridge is alive."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.state != "?":
                return
            time.sleep(0.05)
        print("[chair] WARNING: no status from the ESP32 bridge. Wrong COM port? Arduino Serial Monitor still open?")
