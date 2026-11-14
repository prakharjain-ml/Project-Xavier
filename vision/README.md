# vision/

**Owner:** Vani

**Purpose:** Mode 2 stretch: find objects, track them, and help steer toward the chosen one.

| In | Out |
| --- | --- |
| Webcam frames | `TargetSet`, servo suggestion for control |

## Planned files (created during the hackathon, not before)
- detect_track.py - YOLO + ByteTrack, top 4 stable tracks, FPS log
- servo.py - turn-to-center / approach suggestion; nothing on lost track
- tests/ - track stability on a recorded clip

## Done when
Track ids stable for 10 s while objects move; FPS logged. Only after Mode 1 gate for integration.

Rules: `.cursor/rules/` (auto-attached for this folder) and `AGENTS.md`. Contracts: `docs/INTERFACES.md`.

## Camera viewer (built Fri Nov 13 by Prakhar's agent; Vani: `camera_source.py` is where YOLO plugs in)
- `camera_source.py`: `LatestFrameReader` reads a webcam, RTSP URL or file on a thread and keeps only the newest frame.
- `camera_view.py`: window with status, FPS and frame age; prints a `summary:` line at exit.

```bash
python -m vision.camera_view --synthetic --seconds 10   # no camera
python -m vision.camera_view --source 0                 # webcam (fallback, zero setup)
export RING_RTSP_URL=rtsp://localhost:8554/<camera_id>_live && python -m vision.camera_view   # Ring
```

Ring bridge (human-run, outside the repo, needs internet + Ring login): `colima start`, then run an MQTT broker
(Mosquitto) and `tsightler/ring-mqtt` in Docker per https://github.com/tsightler/ring-mqtt/wiki, publishing port
8554. Log in to Ring once through ring-mqtt (the token stays in the Docker volume, never in the repo). The camera id
is in the ring-mqtt log. Glass-to-glass latency: hold a phone stopwatch in front of the Ring and photograph phone +
laptop together.
