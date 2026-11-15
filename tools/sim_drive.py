"""Simulate a full drive session: the real object_select.run() with the real state machine, route planner,
follower and motor driver, writing into a fake serial port. Only the camera picture, the detections, the gaze
and the key presses are scripted. Prints what was calculated and sent, and saves screenshots."""
import logging, queue, sys, time, types
import cv2, numpy as np
sys.path.insert(0, ".")
import vision.object_select as osel
from vision.detect_track import Track
from vision.gaze import GazeSample
from motors.driver import MotorDriver
from motors.mock_serial import MockSerial

OUT = sys.argv[1]
SCENE = sys.argv[2] if len(sys.argv) > 2 else "detour"
W, H = 1920, 1080
picture = cv2.resize(cv2.imread(f"{OUT}/hall.png"), (W, H))
target = Track(4, "couch", 0.9, (1300, 420, 1700, 640), 3.2)   # destination, right of centre, 3.2 m
obstacle = Track(7, "chair", 0.9, (820, 380, 1100, 900), 1.8)  # a chair in the way, 1.8 m
in_way = Track(7, "chair", 0.9, (1340, 400, 1640, 900), 1.6)  # a chair right on the line to the couch
tracks = {"detour": [target, obstacle], "blocked": [target, in_way]}.get(SCENE, [target])
osel.detect = lambda *a, **k: list(tracks)

class Camera:
    def latest(self): return picture, time.monotonic()

log_lines, shots, statuses = [], {}, []
class Grab(logging.Handler):
    def emit(self, r): log_lines.append(r.getMessage())
logging.getLogger("vision.object_select").addHandler(Grab()); logging.getLogger("vision.object_select").setLevel(logging.INFO)

gaze_point = (0.862, 0.48) if SCENE == "blocked" else ((target.bbox[0] + target.bbox[2]) / 2 / W, 0.5)  # blocked: the strip of couch beside the chair
class Gaze:
    flip = False
    def get_nowait(self):
        self.flip = not self.flip
        if not self.flip: raise queue.Empty
        return GazeSample(gaze_point, False, True, time.monotonic())

t0 = time.monotonic()
def wait_key(_ms):
    time.sleep(0.01)
    el = time.monotonic() - t0
    if 1.0 < el < 1.05: return ord("j")      # the "clench" (key mode stands in for the headset)
    return 255
real_draw = osel.draw
def draw_and_keep(*a, **k):
    img = real_draw(*a, **k)
    shots[round(time.monotonic() - t0, 1)] = img
    statuses.append((round(time.monotonic() - t0, 2), a[7] if len(a) > 7 else k.get("status")))
    global last_args
    last_args = a
    return img
osel.draw = draw_and_keep
fake_cv2 = types.SimpleNamespace(**{n: getattr(cv2, n) for n in dir(cv2) if not n.startswith("_")})
fake_cv2.imshow, fake_cv2.waitKey = (lambda *a: None), wait_key

port = MockSerial(); driver = MotorDriver(lambda: port); driver.start()
try:
    osel.run(fake_cv2, Camera(), None, None, Gaze(), 85.5, "cpu", 5.0, confirm_mode="key", driver=driver,
             follow="route", cam_h=0.89, cam_pitch=0.0)
finally:
    driver.stop()
lines = port.lines()
drive = [l for l in lines if l.startswith("C,")]
print(f"--- scene: {SCENE}")
print("log:", [l for l in log_lines if any(w in l for w in ("CONFIRMED", "state", "ARRIVED", "route"))][:8])
print(f"serial lines: {len(lines)} total, {len(drive)} drive lines; first drive: {drive[:3]}; last: {drive[-3:]}")
for t, s in statuses[::40][:8]: print(f"  t={t:4.1f}s status: {s}")
from vision.chevrons import place_guides
rm, cam = (last_args[11] if len(last_args) > 11 else None), (last_args[12] if len(last_args) > 12 else None)
print("route (m, forward/left):", None if rm is None else rm.round(2).tolist(), "camera:", cam)
if rm is not None: print("guides:", place_guides(rm, W, H, *cam))
key = max(shots); cv2.imwrite(f"{OUT}/sim_{SCENE}.png", shots[key]); print("screenshot", f"{OUT}/sim_{SCENE}.png", "at", key, "s")
