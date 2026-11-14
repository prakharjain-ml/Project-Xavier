# Route preview: requirements, constraints and module contract

Status: built and tested (Sat Nov 14, evening); preview only, not yet the route the chair drives. Owner: Prakhar. This file is the contract for the route preview
rebuild. Change it only when Prakhar asks.

## What the screen does
The camera view fills the window. Every detected object has a thin cyan outline (from a segmentation model,
not a box). A cyan cursor follows the rider's eyes (the mouse stands in for the eyes in the preview). The
object under the cursor is filled cyan, with a label pill and a reticle whose arc shows confirm progress. A
glowing cyan route with chevrons runs along the floor from the chair to a stop ring in front of the chosen
object. A top bar shows "XAVIER" and "CAMERA VIEW". A bottom bar shows the mode, a status line and a red STOP
button.

## Who decides what
1. Objects: on-device segmentation model (`yolo11n-seg`), every frame. Precise.
2. Floor and extra no-go zones: Gemini, in a background thread. Measured 2.0 to 9.6 s per answer, and coarse
   (one rough floor outline, boxes around whole objects), but it sees tables, walls and glass that the detector
   does not know. Its boxes for objects the detector also found are dropped: the detector's outline is exact.
3. Route: computed locally on the floor that survives both sources. The free-floor mask is warped to a
   top-down view of the floor in real centimetres (from the camera's height and tilt), the route is planned
   there with the chair's real width, and it is drawn back onto the camera image. Planning in image pixels
   was tried first and was wrong: near the horizon one pixel of height is far more floor than one pixel of
   width. Gemini's suggested route points are only hints, and only those on free floor are used.
4. Motors: unchanged. The existing local planner and the safety state machine drive the chair. The route on
   screen is a preview and is not yet the route the chair drives.

## Constraints that must not be broken
| # | Constraint | Enforced in |
| --- | --- | --- |
| C1 | Every point of the route lies on free floor. Never on an object, a no-go zone, or outside the floor. | `vision/floor_route.py` `route_violations` |
| C2 | The chair fits: at least 30 cm of free floor on both sides of the route, measured in the top-down view. Floor the camera cannot see counts as not drivable. The target itself is exempt, because the route ends next to it. Depends on the camera height and tilt being measured. | `vision/floor_route.py`, `vision/route_scene.py` |
| C3 | The route starts at the bottom edge of the image (the chair) and ends on the floor in front of the target, not on it. | `vision/floor_route.py` |
| C4 | If no route passes C1 to C3: return nothing, draw nothing, show "No safe route". Never draw a best guess as if it were verified. | `vision/floor_route.py`, `vision/nav_preview.py` |
| C5 | Gemini is advice. Detector outlines always override it: Gemini can remove floor, never add floor on an object. | `vision/floor_route.py` `free_floor` |
| C6 | Gemini's answer applies only to the view it saw. If the view changes, or the answer is older than 10 s, discard it. | `vision/scene_ai.py` `advice_valid` |
| C7 | Gemini never commands motors and never blocks the control loop. Its failure or delay changes nothing about STOP. | `vision/scene_ai.py` (background thread only) |
| C8 | Selection rules are unchanged: look at an object, then dwell or clench to confirm; hold-to-move stays. | `vision/object_select.py` (logic untouched) |
| C9 | STOP is always visible and always works (click or key). | `vision/hud.py`, callers |
| C10 | The API key stays in `.env`. Frames are downscaled, sent only when scene AI is on, never saved or logged. | `vision/scene_ai.py` |
| C11 | The screen stays above 15 fps while Gemini works; at most one Gemini call every 3 s. | `vision/scene_ai.py`, `vision/hud.py` |
| C12 | The screen says where the floor came from: Gemini-checked (solid route) or local estimate, unverified (dashed route). | `vision/hud.py`, `vision/nav_preview.py` |

## Module contract
All coordinates are pixels in the working camera frame (x right, y down). Masks are `bool` arrays of shape
(frame height, frame width). Functions return new objects and never modify their inputs.

### `vision/floor_route.py` (pure: numpy, cv2, no I/O)
```python
@dataclass(frozen=True)
class Route:
    points: np.ndarray         # (N, 2) float pixels, from the chair (bottom edge) to the stop point
    half_width_px: np.ndarray  # (N,) chair half-width in pixels at each point (for drawing the ribbon)
    via_gemini: bool           # True if Gemini's suggested via-points were used

def polygons_to_mask(polygons, shape) -> np.ndarray            # list of (N, 2) polygons -> bool mask
def local_floor(shape, horizon_row) -> np.ndarray               # fallback floor: everything below the horizon
def half_width_px(rows, horizon_row, width_gain) -> np.ndarray  # width_gain * (row - horizon_row), min 2 px
def free_floor(floor, objects, no_go) -> np.ndarray             # floor & ~objects & ~no_go  (C5)
def plan_route(free, target, horizon_row, width_gain, via=None, fixed_half_width_px=None) -> Route | None   # None = no safe route (C4)
def route_violations(points, half_widths, free, target) -> list[str]   # [] = C1, C2, C3 all hold
```
`width_gain` = chair half-width in metres / camera height in metres (default 0.3 / 1.0). `target` is the
chosen object's mask. `via` is an optional (N, 2) array of Gemini's suggested points.

### `vision/scene_ai.py` (Gemini; network only inside `query_scene`)
```python
@dataclass(frozen=True)
class SceneAdvice:
    floor: tuple[np.ndarray, ...]              # floor polygons, (N, 2) pixels in the frame that was sent
    no_go: tuple[tuple[str, np.ndarray], ...]  # (label, polygon)
    route: np.ndarray                          # (N, 2) suggested via-points; may be empty
    target_id: int | None                      # the target the route was asked for
    frame_t: float                             # monotonic time of the analysed frame
    thumb: np.ndarray                          # small grey copy of that frame, for the scene-change check
    model: str
    latency_s: float

def parse_scene_json(text, width, height) -> tuple[floor, no_go, route]   # strict; ValueError on junk
def scene_changed(thumb, frame) -> bool
def advice_valid(advice, frame, now, max_age_s=10.0) -> bool               # C6
def query_scene(client, frame, target_label, target_box) -> SceneAdvice
def make_client()                                                          # None when there is no key

class SceneAdvisor:   # background thread, keeps only the newest request and the newest answer
    def __init__(self, client, query=query_scene, min_interval_s=3.0)
    def start(self) -> None
    def stop(self) -> None
    def submit(self, frame, frame_t, target_id, target_label, target_box) -> None   # never blocks
    def latest(self) -> SceneAdvice | None
    def status(self) -> str   # "off" | "analysing" | "ready" | "failed"
```

### `vision/hud.py` (pure drawing: cv2 + Pillow)
```python
@dataclass(frozen=True)
class SceneObject:
    label: str
    bbox: tuple[float, float, float, float]
    outline: np.ndarray | None   # (N, 2) polygon; None = fall back to corner brackets on the bbox
    selected: bool = False
    progress: float = 0.0        # confirm progress 0..1, drawn as the reticle arc

@dataclass(frozen=True)
class HudState:
    objects: tuple[SceneObject, ...] = ()
    cursor: tuple[float, float] | None = None   # gaze point in frame pixels
    route_points: np.ndarray | None = None
    route_half_width: np.ndarray | None = None
    route_verified: bool = True                 # False = dashed, "unverified" (C12)
    title_left: str = "XAVIER"
    title_right: str = "CAMERA VIEW"
    mode: str = "Route preview"
    status: str = "Stopped · Awaiting confirmation"
    phase: float = 0.0                          # animates the chevrons

def render(frame, state) -> np.ndarray          # camera frame with overlays, between a top and a bottom bar
def frame_origin() -> tuple[int, int]           # where the camera image starts inside the rendered image
def stop_button_rect(frame_w, frame_h) -> tuple[int, int, int, int]   # in rendered-image pixels (C9)
```

### `vision/route_scene.py` (pure; shared by the mouse preview and the real gaze screen)
```python
def floor_view(frame_w, frame_h, hfov_deg, cam_height_m, pitch_deg) -> FloorView   # top-down view, 1 px = 1 cm
def top_view(mask, view) -> np.ndarray                 # camera-image mask -> top-down mask (unseen floor = False)
def cursor_hit(tracks, cursor) -> int | None           # object under the cursor; the smallest one wins
def extra_no_go(no_go, tracks, target) -> list         # Gemini boxes for things the detector did not find
def plan(shape, tracks, target, advice, view) -> tuple[Route | None, bool]   # route in image pixels, Gemini-checked?
```

## Known limits (Sat Nov 14)
- The route on screen is not yet the route the chair drives. The motors follow the existing drive planner.
- Gemini misses things. In test runs it missed plants, a side table or a coffee table in some answers, so
  "Gemini-checked" does not mean every obstacle was found. The ultrasonic stop remains the backstop.
- Gemini's answer is only valid while the view is still, so it applies while the chair is stopped.
- With the phone level at 35 in, the nearest floor the camera sees is about 1.7 m away. Tilt it down about
  15 degrees on the chair to see floor from about 1 m.
- Example render: `docs/img/route_preview_design.jpg`.
