"""The small JSON snapshot the page draws from (~15 times a second). No pictures in here: video goes over its own
MJPEG stream. Every value carries what it is about (frame time, gaze age) so the page never shows old data as new."""

from __future__ import annotations

import math

from interface.web.workflow import Flow

ROUTE_POINTS_MAX = 60  # the route is down-sampled for drawing


def _objects(session, now: float) -> list[dict]:
    from vision.object_select import MIN_LOOK_S, dwell_fraction

    d = session.drive
    out = []
    for t in d.targets:
        confirmed, candidate = t.id == d.sel.confirmed, t.id == d.sel.candidate
        if confirmed:
            progress = 1.0
        elif candidate and session.confirm == "dwell":
            progress = dwell_fraction(d.sel, now, 1.5)
        elif candidate:  # clench / key / blink: full ring = looked long enough, confirm now
            progress = 1.0 if d.sel.since is not None and now - d.sel.since >= MIN_LOOK_S else 0.0
        else:
            progress = 0.0
        out.append({"id": t.id, "label": t.label, "box": [round(v, 1) for v in t.bbox],
                    "distance_m": t.distance_m, "candidate": candidate, "confirmed": confirmed,
                    "progress": round(progress, 3), "remembered": confirmed and d.held})
    return out


def _route(session) -> dict:
    d = session.drive
    if d.sel.confirmed is None:
        return {"status": "none", "points_m": []}
    if d.route_m is None:
        status = "planning" if d.planned_for != d.sel.confirmed else "no_route"
        return {"status": status, "points_m": []}
    path = d.route_m.tolist()
    points = path[:: max(1, math.ceil(len(path) / ROUTE_POINTS_MAX))]
    length = float(sum(math.dist(a, b) for a, b in zip([[0.0, 0.0], *path], path)))
    return {"status": "held" if d.held else "ready", "points_m": [[round(x, 2), round(y, 2)] for x, y in points],
            "length_m": round(length, 2)}


def _obstacles(session) -> list[list[float]]:
    """Floor points (metres) of every object except the destination: what the planner steers around."""
    from vision.object_select import obstacle_points

    d = session.drive
    if not d.tracks or d.frame_size[0] == 0 or session.perception is None:
        return []
    pts = obstacle_points(d.tracks, d.sel.confirmed, d.frame_size[0], session.perception.hfov)
    return [[round(x, 2), round(y, 2)] for x, y in pts[::2]]


def snapshot(session, client_id: str, now: float) -> dict:
    d = session.drive
    controller = session.controller is not None and session.controller.id == client_id
    motor = session.driver.last if session.driver is not None else None
    return {
        "flow": session.flow.value,
        "session": session.session_id,
        "mode": session.mode,
        "confirm": session.confirm,
        "you_control": controller,
        "controller_fresh": session.controller_fresh(now),
        "calibrated": session.calibrated,
        "stop_reason": session.estop_reason,
        "error": session.error,
        "arrived_at": session.arrived_at,
        "frame": None if d.frame_t is None else {"t": round(d.frame_t, 3), "w": d.frame_size[0],
                                                 "h": d.frame_size[1], "age_s": round(now - d.frame_t, 3)},
        "objects": _objects(session, now) if session.flow != Flow.IDLE else [],
        "gaze": {"point": None if d.gaze_point is None else [round(d.gaze_point[0], 4), round(d.gaze_point[1], 4)],
                 "age_s": d.gaze_age_s, "on": d.hit},
        "route": _route(session),
        "obstacles_m": _obstacles(session),
        "motor": None if motor is None else {"left": motor.left, "right": motor.right, "stop": motor.stop,
                                             "port": session.driver.port_label},
        "devices": session.perception.devices() if session.perception is not None else {},
        "events": list(session.events)[-8:],
        "diag": {"tick_ms": round(session.tick_ms, 2), "note": d.note.strip(" |")},
    }
