"""Gemini destination ranker: asks Gemini which places in view a wheelchair user most likely wants to go.

How ranking works (see README "Destination ranking"):
1. Every GEMINI_INTERVAL_S a background thread sends one small frame to Gemini and gets back up to 4
   destinations: label ("door", "table with items"), box, score 0-1 (how likely a user wants to go there), reason.
2. Each frame, rank_targets() merges that answer with the YOLO + ByteTrack objects:
   - a tracked object that overlaps a Gemini box (IoU >= MATCH_IOU) takes Gemini's label and score;
   - a Gemini box with no tracked object (doors: YOLO cannot see them) becomes its own target;
   - plain tracked objects fill any remaining slots, steadiest first.
   Sorted by score, highest first; the top 4 get the 4 flicker frequencies.
3. Gemini is advisory only: slow (1-5 s), needs internet, can be wrong. If it fails or its answer is older than
   STALE_AFTER_S, ranking falls back to plain YOLO. It never moves the chair; the EEG choice and the safety
   layers do.
Privacy: frames of the room (and people in it) go to Google. Tell people in frame.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import cv2
import numpy as np

from vision.detect_track import MAX_TARGETS, Track, pick_targets

log = logging.getLogger("vision.destinations")

# Tried in order until one answers. Lite first: ~1 s per answer and good enough for suggestions; the bigger models
# were overloaded (503/504) on Sat Nov 14. Override with GEMINI_MODELS="a,b" if Google renames or retires them.
GEMINI_MODELS = tuple(os.environ.get("GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3.7-flash,gemini-3.8-flash").split(","))
GEMINI_TIMEOUT_MS = 10_000  # give up on one model after 10 s and try the next
GEMINI_INTERVAL_S = 4.0  # one request every few seconds: enough for suggestions, cheap on quota
STALE_AFTER_S = 15.0  # ignore Gemini answers older than this
UPLOAD_WIDTH = 640  # downscale before upload: faster, cheaper, enough detail
MIN_GEMINI_SCORE = 0.3  # drop suggestions Gemini rates as unlikely
MATCH_IOU = 0.3  # overlap needed to say "this YOLO box is that Gemini destination"
TRACKED_ONLY_SCORE = 0.2  # plain YOLO objects rank below anything Gemini recommends
BOX_SCALE = 1000  # Gemini returns box_2d as [ymin, xmin, ymax, xmax] on a 0-1000 scale

# Static context goes in the system instruction (sent once per call, cached by the model); the per-frame turn is short.
SYSTEM_PROMPT = """You are the destination finder for a brain-controlled powered wheelchair.

WHO YOU SERVE
The rider has a severe motor impairment (for example ALS or a high spinal cord injury). They cannot use a
joystick or their hands. They choose where to go by looking at one of up to 4 boxes drawn over this camera
image; each box flickers at its own rate and an EEG headset detects which one they stare at. The chair then
turns toward the chosen box and rolls to it. Choosing is slow and tiring, so every option you offer must be a
place this person would genuinely want to go.

THE IMAGE
One frame from a camera mounted on the chair about 1 m above the floor, facing forward. It shows what is
ahead indoors (classroom, office, hallway, lab, lounge). The chair rolls on flat floor only.

YOUR TASK
Return the up to 4 most useful, reachable destinations visible in this frame, most likely first.

SCORE = how likely this rider wants to go there now
- 0.85-1.00: a doorway, exit, entrance or open hallway leading out; an elevator; a person in the room
  (help, conversation); a table, desk or counter with items on it (to reach things).
- 0.55-0.84: an empty table or desk; a seating area or couch where others sit; a sink, water fountain,
  charging spot or window.
- 0.30-0.54: other large furniture worth approaching.
- Below 0.30: do not list it.

NEVER LIST
- Walls, floor, ceiling, lights, blank areas, or the whole image.
- Pictures, posters, screens or reflections, including framed photos of people: only real, physical things.
- Stairs, escalators or anything only reachable by climbing: the chair cannot use them.
- Small handheld items (phones, cups, pens) as destinations; name the table they sit on instead.
- Anything you cannot clearly see. Do not guess what is outside the frame or behind objects.

BOX RULES (the rider must be able to stare at the box)
- box_2d is [ymin, xmin, ymax, xmax] as integers 0-1000, relative to the image.
- Tight around the physical thing or opening, including where it meets the floor when visible.
- At least 60 units wide and 60 units tall; skip anything smaller (too small to stare at).
- One box per destination. Boxes overlap by less than a third. Two doors are two entries.

LABELS AND REASONS (shown on screen to the rider and to demo judges)
- label: 2-4 lowercase words, specific and distinct from each other: "left door", "table with laptop",
  "person by window". Never generic words like "object" or "area".
- reason: under 8 plain words, about why the rider might go there.
- If a destination from the previous answer is still visible, reuse its exact label so its flicker box stays.

WHEN UNSURE
If the image is dark, blurred or shows nothing worth going to, return []. An empty list is better than a
weak guess. Rate honestly: do not inflate scores.

OUTPUT
Only a JSON array, most likely first, at most 4 items. Example:
[{"label": "open door", "box_2d": [120, 610, 980, 820], "score": 0.92, "reason": "way out of the room"},
 {"label": "table with laptop", "box_2d": [520, 90, 900, 450], "score": 0.78, "reason": "items within reach"}]"""


def build_user_prompt(previous: Sequence["Destination"]) -> str:
    """Short per-frame turn. Previous labels let Gemini keep names stable, so flicker boxes do not jump."""
    if not previous:
        return "Find the destinations in this frame."
    names = ", ".join(f'"{d.label}"' for d in previous)
    return f"Find the destinations in this frame. Previous answer (reuse these labels if still visible): {names}."


@dataclass(frozen=True)
class Destination:
    label: str
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels of the full frame
    score: float
    reason: str


def parse_gemini_json(text: str, width: int, height: int) -> list[Destination]:
    """Turn Gemini's reply into Destinations. Bad or partial replies give [] or fewer items, never an exception."""
    try:
        items = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.warning("Gemini reply was not JSON")
        return []
    destinations = []
    for item in items if isinstance(items, list) else []:
        try:
            ymin, xmin, ymax, xmax = (min(max(float(v), 0.0), BOX_SCALE) for v in item["box_2d"])
            score = min(max(float(item.get("score", 0.5)), 0.0), 1.0)
            label = str(item["label"])[:40]
        except (KeyError, TypeError, ValueError):
            continue  # skip one malformed entry, keep the rest
        if xmax <= xmin or ymax <= ymin or score < MIN_GEMINI_SCORE:
            continue  # empty box, or Gemini itself says it is unlikely (live run gave "unclear target area 0.01")
        bbox = (xmin / BOX_SCALE * width, ymin / BOX_SCALE * height, xmax / BOX_SCALE * width, ymax / BOX_SCALE * height)
        destinations.append(Destination(label, bbox, score, str(item.get("reason", ""))[:80]))
    return destinations[:MAX_TARGETS]


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection over union: 0 = no overlap, 1 = same box."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def gemini_only_id(destination: Destination) -> int:
    """Stable negative id for a Gemini-only target (e.g. a door), from its label and rough position.

    Negative so it can never clash with ByteTrack ids; stable so the door keeps its frequency between answers.
    """
    cell = int((destination.bbox[0] + destination.bbox[2]) / 2 // 200)  # 200 px wide position buckets
    return -(1 + (sum(map(ord, destination.label.lower())) * 31 + cell) % 100_000)


def rank_targets(tracks: Sequence[Track], destinations: Sequence[Destination], first_seen: dict[int, float],
                 max_n: int = MAX_TARGETS) -> list[Track]:
    """Merge Gemini suggestions with tracked objects, highest score first. Inputs are not modified."""
    scored: list[tuple[float, Track]] = []
    used_tracks: set[int] = set()
    for dest in destinations:
        match = max(tracks, key=lambda t: iou(t.bbox, dest.bbox), default=None)
        if match is not None and match.id not in used_tracks and iou(match.bbox, dest.bbox) >= MATCH_IOU:
            used_tracks.add(match.id)
            scored.append((dest.score, replace(match, label=dest.label)))  # keep tracking + distance, take label
        else:
            scored.append((dest.score, Track(gemini_only_id(dest), dest.label, dest.score, dest.bbox, None)))
    leftovers = pick_targets([t for t in tracks if t.id not in used_tracks], first_seen, max_n)
    scored.extend((TRACKED_ONLY_SCORE, t) for t in leftovers)
    # Stable sort: equal scores keep their order (Gemini's own order, then steadiest YOLO objects).
    return [t for _, t in sorted(scored, key=lambda pair: -pair[0])][:max_n]


def encode_jpeg(frame: np.ndarray) -> bytes:
    scale = UPLOAD_WIDTH / frame.shape[1]
    small = cv2.resize(frame, (UPLOAD_WIDTH, int(frame.shape[0] * scale))) if scale < 1 else frame
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("could not encode frame as JPEG")
    return buf.tobytes()


RESPONSE_SCHEMA = {  # the API enforces this shape, so the reply cannot drift from what parse_gemini_json expects
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "label": {"type": "STRING"},
            "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
            "score": {"type": "NUMBER"},
            "reason": {"type": "STRING"},
        },
        "required": ["label", "box_2d", "score", "reason"],
    },
}


def query_gemini(client, frame: np.ndarray, previous: Sequence[Destination] = ()) -> list[Destination]:
    from google.genai import types  # imported lazily so tests and --no-gemini runs do not need it

    image = types.Part.from_bytes(data=encode_jpeg(frame), mime_type="image/jpeg")
    config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json",
                                         response_schema=RESPONSE_SCHEMA, temperature=0.2)
    last_error: Exception | None = None
    for model in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model, contents=[image, build_user_prompt(previous)], config=config)
            return parse_gemini_json(response.text, frame.shape[1], frame.shape[0])
        except Exception as error:  # overloaded, retired or timed out: try the next model
            log.warning("gemini model %s failed: %s", model, str(error)[:80])
            last_error = error
    raise RuntimeError("every Gemini model failed") from last_error


def load_api_key(env_path: str = ".env") -> str | None:
    """GEMINI_API_KEY from the environment, else from the repo's .env (gitignored). Never logged."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key or not os.path.exists(env_path):
        return key
    with open(env_path, encoding="utf-8") as handle:
        for line in handle:
            name, _, value = line.strip().partition("=")
            if name in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and value:
                return value.strip().strip("'\"")
    return None


class GeminiRanker:
    """Background thread: every GEMINI_INTERVAL_S, send the newest frame to Gemini and keep the answer."""

    def __init__(self, client, get_frame: Callable[[], np.ndarray | None], query=query_gemini) -> None:
        self._client, self._get_frame, self._query = client, get_frame, query
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._answer: tuple[list[Destination], float] = ([], -STALE_AFTER_S * 2)
        self._thread = threading.Thread(target=self._run, name="gemini-ranker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def latest(self) -> list[Destination]:
        """The newest answer, or [] if there is none or it is stale (then ranking falls back to YOLO)."""
        with self._lock:
            destinations, t = self._answer
        return destinations if time.monotonic() - t <= STALE_AFTER_S else []

    def _run(self) -> None:
        while not self._stop.is_set():
            frame = self._get_frame()
            if frame is not None:
                started = time.monotonic()
                try:
                    destinations = self._query(self._client, frame, self.latest())
                    with self._lock:
                        self._answer = (destinations, time.monotonic())
                    log.info("gemini %.1fs: %s", time.monotonic() - started,
                             ", ".join(f"{d.label} {d.score:.2f}" for d in destinations) or "nothing")
                except Exception:  # network/quota/model errors: keep the old answer, it will expire
                    log.exception("gemini request failed")
            self._stop.wait(GEMINI_INTERVAL_S)
