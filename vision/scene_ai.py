"""Gemini scene advisor: asks Gemini where the floor is, what stands on it, and for a suggested route.

How it fits (docs/ROUTE_REQUIREMENTS.md):
1. A background thread sends one downscaled camera frame to Gemini, at most once every MIN_INTERVAL_S (C11).
2. Gemini answers with the outline of the floor, a box around everything standing on the floor (it sees tables,
   walls and glass that the on-device detector misses), and a few route points toward the chosen target.
3. parse_scene_json() checks that answer strictly and turns it into pixel polygons. vision/floor_route.py then
   validates everything again against the detector's outlines. Gemini is advice only (C5).
4. advice_valid() throws the answer away when the camera view changed or the answer is older than 10 s (C6).

Safety (C7): nothing here produces a motor command or runs on the control loop. If Gemini is slow, wrong or
down, the advisor's status becomes "failed" and the chair behaves exactly as it does without scene AI.
Privacy (C10): the API key is read by vision.destinations.load_api_key and is never printed or logged. Frames
are only sent to Gemini, never written to disk. Logs carry the model name, the latency and counts, nothing else.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

import cv2
import numpy as np

from vision.destinations import GEMINI_MODELS, encode_jpeg, load_api_key

log = logging.getLogger("vision.scene_ai")

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels of the camera frame
NoGo = tuple[str, np.ndarray]  # (label, 4-corner polygon in pixels)

COORD_SCALE = 1000  # Gemini gives every coordinate as an integer 0-1000, relative to the image
MIN_POLYGON_POINTS = 3
MIN_POLYGON_AREA_PX2 = 1.0  # smaller than one pixel = a line or a dot, not an area
MAX_LABEL_CHARS = 40
MAX_REPLY_CHARS = 20_000  # a real reply is about 2,000 characters; anything far bigger is not what we asked for

THUMB_WIDTH, THUMB_HEIGHT = 32, 24  # the small grey copy kept for the scene-change check
# Mean grey-level difference (0-255) between two thumbnails above which the view counts as changed. Measured on
# three room photos: sensor noise gives 0.5, panning the camera by 1 % of the image width gives 4.0 to 6.6, a
# person stepping into view gives 8 to 9. Known limit: a small object entering (about 2) stays under it; the
# on-device detector, which runs on every frame, is what catches those.
SCENE_CHANGE_MEAN_ABS_DIFF = 6.0
MAX_ADVICE_AGE_S = 10.0  # C6
MIN_INTERVAL_S = 3.0  # C11: at most one Gemini call every 3 s

# Give up on one model after 10 s. A normal answer takes 2 to 3 s; shorter is not possible, because the API
# refuses deadlines under 10 s (HTTP 400 "Minimum allowed deadline is 10s", measured Nov 14). An answer that
# slow is discarded by advice_valid() anyway (C6).
SCENE_TIMEOUT_MS = 10_000
# After a failure, try the next model only if this little time has passed. A quick refusal (overloaded, retired
# model) falls through to the next one; after a slow failure any answer would be too old to use (C6).
RETRY_WINDOW_S = 4.0
MAX_OUTPUT_TOKENS = 1_200  # replies in this format measured about 560 tokens; the cap bounds the worst-case latency
TEMPERATURE = 0.1
# Thinking adds seconds and no accuracy here. Measured Nov 14: flash-lite refuses thinking_budget=0 (HTTP 400)
# but accepts level MINIMAL; gemini-3.7-flash refuses MINIMAL (HTTP 400), so the bigger models get LOW.
THINKING_LEVEL_LITE = "MINIMAL"
THINKING_LEVEL_OTHER = "LOW"
STOP_JOIN_TIMEOUT_S = 2.0  # stop() waits this long for the thread; a call stuck in the network must not hang quit
THREAD_NAME = "scene-advisor"

SYSTEM_PROMPT = """You are the eyes of a powered wheelchair. The photo is the view from a camera on the chair, \
about 1 m above the floor, facing forward. The chair is just below the bottom centre of the image. All \
coordinates are integers 0-1000: x from the left edge of the image, y from the top edge.

floor: the outline of the room's floor, as 1 or 2 polygons of at most 12 points each. Include all the floor you \
can see, also the floor visible under and between furniture (furniture is handled by no_go). Start at the \
bottom-left corner of the image, go up to where the floor meets the wall, follow the line where the floor meets \
walls, windows and doors across the image, and come back down to the bottom-right corner. Never include walls, \
windows or anything above that line.

no_go: one entry for EVERY thing standing on the floor: chairs, sofas, tables (small side tables too), plants \
and their pots, bins, bags, people, pillars. left, top, right and bottom are the edges of a box around the \
whole visible thing, down to where it touches the floor. label is 1-2 lowercase words. Nearest first, at most 12.

route: 4 to 6 points on bare floor, from the bottom edge of the image (y = 1000) to the floor just in front of \
the target. Take the shortest way that keeps a 0.7 m wide chair clear of every no_go box. No point may lie \
inside a no_go box. If no target is given, or there is no safe way, return an empty list."""

# Named fields (x/y, left/top/right/bottom) on purpose: when asked for bare [x1, y1, x2, y2] arrays, flash-lite
# mixed up the order of the numbers. Names cost a few tokens and remove the ambiguity.
_POINT_SCHEMA = {"type": "OBJECT", "required": ["x", "y"],
                 "properties": {"x": {"type": "INTEGER"}, "y": {"type": "INTEGER"}}}
_POLYGON_SCHEMA = {"type": "ARRAY", "items": _POINT_SCHEMA}
_BOX_EDGES = ("left", "top", "right", "bottom")
RESPONSE_SCHEMA = {  # the API enforces this shape; parse_scene_json still checks all of it again
    "type": "OBJECT",
    "required": ["floor", "no_go", "route"],
    "property_ordering": ["floor", "no_go", "route"],  # route last, so the model has listed the obstacles first
    "properties": {
        "floor": {"type": "ARRAY", "items": _POLYGON_SCHEMA},
        "no_go": {"type": "ARRAY", "items": {
            "type": "OBJECT", "required": ["label", *_BOX_EDGES], "property_ordering": ["label", *_BOX_EDGES],
            "properties": {"label": {"type": "STRING"}, **{edge: {"type": "INTEGER"} for edge in _BOX_EDGES}}}},
        "route": _POLYGON_SCHEMA,
    },
}


@dataclass(frozen=True, eq=False)  # eq=False: comparing numpy fields with == would raise; identity is what callers need
class SceneAdvice:
    floor: tuple[np.ndarray, ...]  # floor polygons, (N, 2) pixels in the frame that was sent
    no_go: tuple[NoGo, ...]  # (label, polygon)
    route: np.ndarray  # (N, 2) suggested via-points; may be empty
    target_id: int | None  # the target the route was asked for
    frame_t: float  # monotonic time of the analysed frame
    thumb: np.ndarray  # small grey copy of that frame, for the scene-change check
    model: str
    latency_s: float


# ---------------------------------------------------------------- strict parsing of Gemini's reply

def _number(value: object) -> float:
    """A finite number, or ValueError. bool is refused although Python counts True as 1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("coordinate is not a number")
    try:
        number = float(value)
    except OverflowError as error:  # an integer too large for a float
        raise ValueError("coordinate is too large") from error
    if not math.isfinite(number):  # json.loads accepts NaN and Infinity, we do not
        raise ValueError("coordinate is not finite")
    return number


def _to_pixel(value: object, size: int) -> float:
    """0-1000 -> pixels along an axis of `size` pixels, clamped so the point lies inside the frame."""
    return min(max(_number(value) / COORD_SCALE * size, 0.0), float(size - 1))


def _field(item: object, key: str) -> object:
    if not isinstance(item, dict) or key not in item:
        raise ValueError(f"expected an object with '{key}'")
    return item[key]


def _list(item: object, key: str) -> list:
    value = _field(item, key)
    if not isinstance(value, list):
        raise ValueError(f"'{key}' is not a list")
    return value


def _points(items: object, width: int, height: int) -> np.ndarray:
    """A list of {"x", "y"} objects -> (N, 2) float pixels. An empty list gives shape (0, 2)."""
    if not isinstance(items, list):
        raise ValueError("expected a list of points")
    pixels = [(_to_pixel(_field(p, "x"), width), _to_pixel(_field(p, "y"), height)) for p in items]
    return np.array(pixels, dtype=np.float64).reshape(-1, 2)


def _no_go_entry(item: object, width: int, height: int) -> NoGo | None:
    """{"label", "left", "top", "right", "bottom"} -> (label, the box's 4 corners clockwise from the top left).

    None for a box without area (zero width or height, or edges the wrong way round): it is dropped.
    """
    label = _field(item, "label")
    if not isinstance(label, str):
        raise ValueError("no_go label is not text")
    left, right = (_to_pixel(_field(item, edge), width) for edge in ("left", "right"))
    top, bottom = (_to_pixel(_field(item, edge), height) for edge in ("top", "bottom"))
    if right <= left or bottom <= top or (right - left) * (bottom - top) < MIN_POLYGON_AREA_PX2:
        return None
    corners = np.array([(left, top), (right, top), (right, bottom), (left, bottom)], dtype=np.float64)
    return label[:MAX_LABEL_CHARS], corners


def _has_area(polygon: np.ndarray) -> bool:
    """False for fewer than 3 points and for shapes with no area (points on one line, a repeated point)."""
    if len(polygon) < MIN_POLYGON_POINTS:
        return False
    x, y = polygon[:, 0], polygon[:, 1]
    # Shoelace formula: sums the cross products of neighbouring corners; abs() because the points may run
    # clockwise or anticlockwise.
    area = abs(0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    return area >= MIN_POLYGON_AREA_PX2


def _load_reply(text: object) -> object:
    if not isinstance(text, str):
        raise ValueError("reply is not text")
    if len(text) > MAX_REPLY_CHARS:
        raise ValueError("reply is too long")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("reply is not JSON") from error


def _check_frame_size(width: object, height: object) -> None:
    for size in (width, height):
        if isinstance(size, bool) or not isinstance(size, (int, np.integer)) or size <= 0:
            raise ValueError("frame width and height must be positive whole numbers")


def parse_scene_json(text: str, width: int, height: int) -> tuple[tuple[np.ndarray, ...], tuple[NoGo, ...], np.ndarray]:
    """Gemini's reply -> (floor polygons, no-go (label, polygon) pairs, route points), all in frame pixels.

    Strict, because this decides where the screen says the chair may roll: anything that is not exactly the
    expected shape, and any number that is not finite, raises ValueError and the whole reply is discarded.
    Two things are tolerated: coordinates outside 0-1000 are clamped to the frame, and shapes without area
    (fewer than 3 points, a line, an inside-out box) are dropped.
    """
    _check_frame_size(width, height)
    data = _load_reply(text)
    floor_polygons = [_points(item, width, height) for item in _list(data, "floor")]
    no_go_entries = [_no_go_entry(item, width, height) for item in _list(data, "no_go")]
    route = _points(_list(data, "route"), width, height)
    floor = tuple(polygon for polygon in floor_polygons if _has_area(polygon))
    no_go = tuple(entry for entry in no_go_entries if entry is not None)
    return floor, no_go, route


# ---------------------------------------------------------------- does the advice still apply? (C6)

def _is_usable_frame(frame: object) -> bool:
    return isinstance(frame, np.ndarray) and frame.ndim in (2, 3) and frame.size > 0


def make_thumb(frame: np.ndarray) -> np.ndarray:
    """A 32 x 24 grey copy of the frame. Averaging over large cells makes it blind to sensor noise."""
    if not _is_usable_frame(frame):
        raise ValueError("frame must be a non-empty image array")
    grey = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (THUMB_WIDTH, THUMB_HEIGHT), interpolation=cv2.INTER_AREA)


def scene_changed(thumb: np.ndarray, frame: np.ndarray) -> bool:
    """True when the current frame no longer shows the view the thumbnail was taken from.

    No usable frame also counts as changed: without proof that the view is the same, the advice is not used.
    """
    if not _is_usable_frame(frame):
        return True
    current = make_thumb(frame)
    if current.shape != thumb.shape:
        return True
    # int16 so that the subtraction of two uint8 images cannot wrap around
    difference = np.abs(current.astype(np.int16) - thumb.astype(np.int16)).mean()
    return bool(difference > SCENE_CHANGE_MEAN_ABS_DIFF)


def advice_valid(advice: SceneAdvice | None, frame: np.ndarray, now: float, max_age_s: float = MAX_ADVICE_AGE_S) -> bool:
    """C6: Gemini's answer applies only to the view it saw, and only for max_age_s seconds.

    `now` and advice.frame_t are both time.monotonic() values.
    """
    if advice is None:
        return False
    age_s = now - advice.frame_t
    if not 0.0 <= age_s <= max_age_s:  # also False for NaN and for advice stamped later than `now`
        return False
    return not scene_changed(advice.thumb, frame)


# ---------------------------------------------------------------- the one place that talks to the network

def build_user_prompt(target_label: str | None, target_box: Box | None, width: int, height: int) -> str:
    """The short per-frame turn: which object the route should lead to, with its box in Gemini's 0-1000 units."""
    if not target_label or target_box is None:
        return "No target: return an empty route."
    label = " ".join(str(target_label).split())[:MAX_LABEL_CHARS]  # one line, bounded length
    x1, y1, x2, y2 = target_box
    left, right = (round(min(max(x / width, 0.0), 1.0) * COORD_SCALE) for x in (x1, x2))
    top, bottom = (round(min(max(y / height, 0.0), 1.0) * COORD_SCALE) for y in (y1, y2))
    return f"Target: {label}, inside the box left {left}, top {top}, right {right}, bottom {bottom}."


def _describe(error: Exception) -> str:
    """What gets logged about a failure: the error's type and HTTP code, never its text (C10)."""
    code = getattr(error, "code", None)
    return f"{type(error).__name__} {code}" if isinstance(code, int) else type(error).__name__


def _request_config(types, model: str):
    level = THINKING_LEVEL_LITE if "lite" in model else THINKING_LEVEL_OTHER
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT, response_mime_type="application/json", response_schema=RESPONSE_SCHEMA,
        temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(thinking_level=getattr(types.ThinkingLevel, level)),
        http_options=types.HttpOptions(timeout=SCENE_TIMEOUT_MS))


def query_scene(client, frame: np.ndarray, target_label: str | None, target_box: Box | None) -> SceneAdvice:
    """One blocking Gemini call (background thread only). Raises when no model gives a usable answer.

    The frame is downscaled to 640 px wide for the upload, but the answer comes back in pixels of the frame
    that was passed in. frame_t is set to the start of this call and target_id to None; SceneAdvisor
    overwrites both with the values of the request.
    """
    if not _is_usable_frame(frame):
        raise ValueError("frame must be a non-empty image array")
    from google.genai import types  # imported lazily so tests and runs without scene AI do not need it

    started = time.monotonic()
    height, width = frame.shape[:2]
    image = types.Part.from_bytes(data=encode_jpeg(frame), mime_type="image/jpeg")
    prompt = build_user_prompt(target_label, target_box, width, height)
    for model in GEMINI_MODELS:
        if time.monotonic() - started > RETRY_WINDOW_S:
            break  # too late for another try: the answer would be stale before it could be used
        try:
            response = client.models.generate_content(
                model=model, contents=[image, prompt], config=_request_config(types, model))
            floor, no_go, route = parse_scene_json(response.text, width, height)
        except Exception as error:  # overloaded, retired, timed out, or a reply that failed the strict parse
            log.warning("scene AI model %s failed: %s", model, _describe(error))
            continue
        latency_s = time.monotonic() - started
        log.info("scene AI %s %.1fs: %d floor polygons, %d no-go zones, %d route points",
                 model, latency_s, len(floor), len(no_go), len(route))
        return SceneAdvice(floor=floor, no_go=no_go, route=route, target_id=None, frame_t=started,
                           thumb=make_thumb(frame), model=model, latency_s=latency_s)
    raise RuntimeError("no Gemini model gave a usable scene answer")


def make_client():
    """A Gemini client, or None when there is no API key (the advisor's status is then "off")."""
    key = load_api_key()
    if not key:
        return None
    from google import genai

    return genai.Client(api_key=key)


# ---------------------------------------------------------------- background thread

@dataclass(frozen=True)
class _Request:
    frame: np.ndarray
    frame_t: float
    target_id: int | None
    target_label: str | None
    target_box: Box | None


SceneQuery = Callable[[object, np.ndarray, str | None, Box | None], SceneAdvice]


class SceneAdvisor:
    """Background thread that keeps only the newest request and the newest answer.

    The control loop and the screen call submit(), latest() and status(); none of them waits for Gemini. The
    lock is only ever held for a few assignments, never during a call (C7, C11). Use once: start(), then stop().
    """

    def __init__(self, client, query: SceneQuery = query_scene, min_interval_s: float = MIN_INTERVAL_S) -> None:
        self._client, self._query, self._min_interval_s = client, query, min_interval_s
        self._wake = threading.Condition()  # guards every field below; notified on a new request and on stop
        self._pending: _Request | None = None
        self._latest: SceneAdvice | None = None
        self._last_outcome: str | None = None  # "ready" or "failed" once a call has finished
        self._running = False
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)

    def start(self) -> None:
        if self._client is None:  # no API key: stay "off", start no thread
            return
        with self._wake:
            if self._running or self._thread.ident is not None:
                return  # already started (a thread can only be started once)
            self._running = True
        self._thread.start()

    def stop(self) -> None:
        with self._wake:
            self._running = False
            self._pending = None
            self._wake.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_S)

    def submit(self, frame: np.ndarray, frame_t: float, target_id: int | None, target_label: str | None,
               target_box: Box | None) -> None:
        """Ask for advice on this frame. Returns at once; an older request that has not been sent is dropped.

        Ignored when there is no client, before start() and after stop().
        """
        if self._client is None or not _is_usable_frame(frame):
            return
        # Copy, because the caller may reuse its frame buffer before the thread gets to this request.
        request = _Request(frame.copy(), frame_t, target_id, target_label, target_box)
        with self._wake:
            if not self._running:
                return
            self._pending = request
            self._wake.notify_all()

    def latest(self) -> SceneAdvice | None:
        """The newest answer, or None. It may be stale: check it with advice_valid() before use (C6)."""
        with self._wake:
            return self._latest

    def status(self) -> str:
        """One of four words for the screen.

        "off": no key, not started, or stopped. "analysing": started, no call has finished yet.
        "ready" / "failed": how the most recent finished call went.
        """
        with self._wake:
            if self._client is None or not self._running:
                return "off"
            return self._last_outcome or "analysing"

    def _run(self) -> None:
        not_before = time.monotonic()
        while True:
            request = self._next_request(not_before)
            if request is None:
                return  # stopped
            not_before = time.monotonic() + self._min_interval_s  # C11: measured from the start of each call
            self._answer(request)

    def _next_request(self, not_before: float) -> _Request | None:
        """Wait until there is a request AND the rate limit allows a call. None once the advisor is stopped.

        The request is taken only at the moment the call may start, so requests submitted during the wait
        replace older ones and the call is made for the newest frame.
        """
        with self._wake:
            while self._running:
                wait_s = not_before - time.monotonic()
                if self._pending is not None and wait_s <= 0:
                    request, self._pending = self._pending, None
                    return request
                # No request: sleep until submit() or stop() notifies. Request but too early: sleep it off.
                self._wake.wait(timeout=wait_s if self._pending is not None else None)
            return None

    def _answer(self, request: _Request) -> None:
        try:
            advice = self._query(self._client, request.frame, request.target_label, request.target_box)
            if not isinstance(advice, SceneAdvice):
                raise TypeError("the query did not return a SceneAdvice")
            stamped = replace(advice, frame_t=request.frame_t, target_id=request.target_id)
        except Exception as error:  # C7: a failed call must never reach the caller or end this thread
            log.warning("scene AI call failed: %s", _describe(error))
            with self._wake:
                self._last_outcome = "failed"  # the last good answer stays; advice_valid() retires it by age
            return
        with self._wake:
            self._latest, self._last_outcome = stamped, "ready"
