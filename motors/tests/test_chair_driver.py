"""Route-follower commands -> Keshav's chair_control functions (motors/chair_driver.py). Fake Chair, no port."""

import time

from motors.chair_driver import ChairDriver, describe
from shared.protocol import MotorCommand


class FakeChair:
    def __init__(self, _port):
        self.calls, self.state, self.distance_cm, self.closed = [], "OK", 0, False

    def forward(self, s): self.calls.append(("forward", s))
    def backward(self, s): self.calls.append(("backward", s))
    def turn_left(self, s): self.calls.append(("turn_left", s))
    def turn_right(self, s): self.calls.append(("turn_right", s))
    def drive(self, l, r): self.calls.append(("drive", l, r))
    def stop(self): self.calls.append(("stop",))
    def close(self): self.closed = True


def make():
    chairs = []
    driver = ChairDriver("PORT", chair_factory=lambda p: chairs.append(FakeChair(p)) or chairs[-1])
    driver.start()
    return driver, chairs[0]


def test_every_wheel_pair_maps_to_the_matching_chair_function():
    driver, chair = make()
    try:
        for left, right in ((120, 120), (-80, -80), (90, -90), (-70, 70), (120, 60), (0, 0)):
            driver.send(MotorCommand(left, right, False, time.monotonic()))
        driver.send(MotorCommand.halt(time.monotonic()))
    finally:
        driver.stop()
    assert chair.calls[:6] == [("forward", 120), ("backward", 80), ("turn_right", 90), ("turn_left", 70),
                               ("drive", 120, 60), ("stop",)]
    assert chair.calls[-1] == ("stop",) and chair.closed


def test_watchdog_stops_the_wheels_when_commands_stop_coming():
    driver, chair = make()
    try:
        driver.send(MotorCommand(120, 120, False, time.monotonic()))
        time.sleep(0.6)  # nothing sent: the screen froze
        assert chair.calls[-1] == ("stop",)
    finally:
        driver.stop()


def test_describe_reads_like_the_library():
    assert describe(0, 0) == "chair.stop()"
    assert describe(100, 100) == "chair.forward(100)" and describe(-50, -50) == "chair.backward(50)"
    assert describe(80, -80) == "chair.turn_right(80)" and describe(-80, 80) == "chair.turn_left(80)"
    assert describe(120, 60).startswith("chair.drive(120, 60)") and "right" in describe(120, 60)
