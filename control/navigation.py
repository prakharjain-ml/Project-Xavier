"""Go-to-object navigation: drive toward the confirmed object while steering around obstacles.

Planner: Dynamic Window Approach (DWA), adapted from PythonRobotics
(https://github.com/AtsushiSakai/PythonRobotics, PathPlanning/DynamicWindowApproach/dynamic_window_approach.py,
MIT License, Atsushi Sakai). Each control step it tries many (speed, turn rate) pairs the wheels can reach within
one step (the "dynamic window"), simulates each for PREDICT_TIME seconds, throws out any path that comes within
robot_radius of an obstacle, and scores the rest: heading toward the goal, keeping speed, staying clear.

Frame: the chair at the origin, x forward, y to the LEFT, angles counter-clockwise, metres and seconds.
Inputs:  goal from the camera (goal_from_target), obstacles from ultrasonics (obstacles_from_ultrasonic).
Output:  (forward speed m/s, turn rate rad/s) -> to_wheels() -> left/right firmware speeds, capped.
Safety:  this only proposes wheel speeds. The state machine still decides IF the chair may move, and the ESP32
         still stops on its own (watchdog, ultrasonic). No reverse: forward and turning only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from shared.protocol import MAX_SPEED

ARRIVE_M = 0.7  # stop this far from the object (the ultrasonic stop at 0.5 m is the hard backstop)
MAX_RANGE_M = 4.0  # HC-SR04 readings beyond this are unreliable: ignored
STUCK_SPEED = 1e-3  # m/s: below this the chair counts as stopped (true on the wheels too: to_wheels() lifts every
#                     slower-than-the-board-can-do command to WHEEL_DEAD_BAND, so "planner moving" = "wheels moving")
WHEEL_DEAD_BAND = 50  # firmware speed units: the hoverboard firmware treats |speed| < 50 as stop (bridge.ino note).
#                       50 units is about 0.2 m/s straight, or about 41 deg/s turning on the spot.
ROUNDS_TO_STOP = 0.5  # firmware speed units: a command smaller than this always rounded to (0, 0) = stop


@dataclass(frozen=True)
class NavConfig:
    max_speed: float = 0.4  # m/s, a slow walk (hoverboard with a rider: keep it gentle)
    min_speed: float = 0.0  # never reverse automatically: the rider cannot see behind
    max_yaw_rate: float = math.radians(40.0)  # rad/s
    max_accel: float = 0.3  # m/s^2
    max_delta_yaw_rate: float = math.radians(60.0)  # rad/s^2
    v_resolution: float = 0.02
    yaw_rate_resolution: float = math.radians(2.0)
    dt: float = 0.1  # s between planner steps
    predict_time: float = 1.5  # s of simulated future per candidate path
    to_goal_cost_gain: float = 0.15
    speed_cost_gain: float = 2.0
    obstacle_cost_gain: float = 1.0  # tuned in simulation: lower gains arrived faster but skimmed obstacles at
    #                                  exactly robot_radius; 1.0 keeps ~0.6 m clearance (Sat Nov 14 sweep)
    robot_radius: float = 0.45  # m: half the chair width plus a margin
    track_width: float = 0.55  # m between the two hoverboard wheels (VERIFY on the chair)


def goal_from_target(steer_offset: float, distance_m: float, hfov_deg: float) -> tuple[float, float]:
    """Camera target -> goal point. steer_offset: -1 (image left edge) .. +1 (right edge)."""
    bearing = -steer_offset * math.radians(hfov_deg) / 2  # right of centre = negative (clockwise) angle
    return distance_m * math.cos(bearing), distance_m * math.sin(bearing)


def obstacles_from_ultrasonic(readings) -> np.ndarray:
    """[(mount angle deg, +left), (distance m or None/-1)] -> (N, 2) obstacle points. Invalid readings dropped."""
    points = [(d * math.cos(math.radians(a)), d * math.sin(math.radians(a)))
              for a, d in readings if d is not None and 0 < d <= MAX_RANGE_M]
    return np.array(points, dtype=float).reshape(-1, 2)


def motion(state: np.ndarray, control: tuple[float, float], dt: float) -> np.ndarray:
    """Advance [x, y, heading, v, w] by dt with constant (v, w). Returns a new array."""
    x, y, yaw, _, _ = state
    v, w = control
    yaw = yaw + w * dt
    return np.array([x + v * math.cos(yaw) * dt, y + v * math.sin(yaw) * dt, yaw, v, w])


def _dynamic_window(v: float, w: float, cfg: NavConfig) -> tuple[float, float, float, float]:
    """Speeds the wheels can reach within one step, limited by the chair's absolute limits."""
    return (max(cfg.min_speed, v - cfg.max_accel * cfg.dt), min(cfg.max_speed, v + cfg.max_accel * cfg.dt),
            max(-cfg.max_yaw_rate, w - cfg.max_delta_yaw_rate * cfg.dt),
            min(cfg.max_yaw_rate, w + cfg.max_delta_yaw_rate * cfg.dt))


def _trajectory(v: float, w: float, cfg: NavConfig) -> np.ndarray:
    state, points = np.array([0.0, 0.0, 0.0, v, w]), []
    for _ in range(int(cfg.predict_time / cfg.dt)):
        state = motion(state, (v, w), cfg.dt)
        points.append(state)
    return np.array(points)


def _goal_cost(traj: np.ndarray, goal) -> float:
    """How far the path's final heading points away from the goal (radians, 0 = straight at it)."""
    angle = math.atan2(goal[1] - traj[-1, 1], goal[0] - traj[-1, 0]) - traj[-1, 2]
    return abs(math.atan2(math.sin(angle), math.cos(angle)))


def _obstacle_cost(traj: np.ndarray, obstacles: np.ndarray, cfg: NavConfig) -> float:
    if len(obstacles) == 0:
        return 0.0
    gaps = np.hypot(traj[:, None, 0] - obstacles[None, :, 0], traj[:, None, 1] - obstacles[None, :, 1])
    closest = float(gaps.min())
    return math.inf if closest <= cfg.robot_radius else 1.0 / closest


def dwa_control(v: float, w: float, goal, obstacles: np.ndarray, cfg: NavConfig = NavConfig()) -> tuple[float, float]:
    """Best (speed, turn rate) for this step, given the current (v, w), goal and obstacles (chair frame).
    Returns (0, 0) when arrived or when every candidate path would hit something."""
    if math.hypot(goal[0], goal[1]) < ARRIVE_M:
        return 0.0, 0.0
    v_min, v_max, w_min, w_max = _dynamic_window(v, w, cfg)
    best, best_cost = (0.0, 0.0), math.inf
    for cand_v in np.arange(v_min, v_max + 1e-9, cfg.v_resolution):
        for cand_w in np.arange(w_min, w_max + 1e-9, cfg.yaw_rate_resolution):
            traj = _trajectory(cand_v, cand_w, cfg)
            ob = _obstacle_cost(traj, obstacles, cfg)
            if math.isinf(ob):
                continue  # this path would hit something
            cost = (cfg.to_goal_cost_gain * _goal_cost(traj, goal)
                    + cfg.speed_cost_gain * (cfg.max_speed - cand_v)
                    + cfg.obstacle_cost_gain * ob)
            if cost < best_cost:
                best, best_cost = (float(cand_v), float(cand_w)), cost
    if best[0] < STUCK_SPEED and abs(v) < STUCK_SPEED:
        return _unstick(w, goal, obstacles, cfg)
    return best


def _unstick(w: float, goal, obstacles: np.ndarray, cfg: NavConfig) -> tuple[float, float]:
    """Stopped, and standing still scores best: rotate in place so new paths open up (PythonRobotics' "stuck"
    rule; without it the chair froze 1.6 m short of an obstacle in simulation). Turn away from the nearest
    obstacle, else toward the goal side. Never turn if something is already within the chair's radius."""
    if len(obstacles):
        nearest = obstacles[np.argmin(np.hypot(obstacles[:, 0], obstacles[:, 1]))]
        if math.hypot(*nearest) <= cfg.robot_radius:
            return 0.0, 0.0
        direction = -1.0 if nearest[1] >= 0 else 1.0  # obstacle on the left -> turn right (clockwise)
    else:
        direction = 1.0 if goal[1] >= 0 else -1.0
    return 0.0, direction * min(cfg.max_yaw_rate, abs(w) + cfg.max_delta_yaw_rate * cfg.dt)


def _out_of_dead_band(left: float, right: float) -> tuple[float, float]:
    """Make sure the board acts on what the planner asked for: each wheel ends up 0 or at least WHEEL_DEAD_BAND.
    Before this, the fastest turn on the spot came out as (-49, 49) and anything under 0.2 m/s under 50: the
    board ignored it and the chair stood still while the planner believed it was moving."""
    fastest = max(abs(left), abs(right))
    if fastest < ROUNDS_TO_STOP:
        return 0.0, 0.0  # the planner asked for stop (or rounding noise): stay stopped
    if fastest < WHEEL_DEAD_BAND:
        # Motion is wanted but even the faster wheel is too slow for the board. Scale BOTH wheels by the same
        # factor until the faster one is exactly at the dead band: same curve, at the slowest speed that exists.
        left, right = left * WHEEL_DEAD_BAND / fastest, right * WHEEL_DEAD_BAND / fastest
    return _snap_wheel(left), _snap_wheel(right)


def _snap_wheel(speed: float) -> float:
    """One wheel still inside the dead band (the slower one of a turn) goes to whichever is nearer, stop or the
    dead band. Nearest keeps the error under 25 units and keeps a wheel hovering around 0 at 0, where "always
    lift" would flip it between -50 and +50."""
    if abs(speed) >= WHEEL_DEAD_BAND:
        return speed
    return math.copysign(WHEEL_DEAD_BAND, speed) if abs(speed) >= WHEEL_DEAD_BAND / 2 else 0.0


def to_wheels(v: float, w: float, cfg: NavConfig = NavConfig()) -> tuple[int, int]:
    """(m/s, rad/s) -> (left, right) firmware speeds. Differential drive: the outer wheel runs faster.
    Scaled so the fastest wheel the planner can ask for equals MAX_SPEED; the conversion is VERIFY on the chair.
    Each wheel comes out as 0 or at least WHEEL_DEAD_BAND (see _out_of_dead_band); the top speed is unchanged."""
    half = cfg.track_width / 2
    top = cfg.max_speed + cfg.max_yaw_rate * half
    left, right = _out_of_dead_band((v - w * half) / top * MAX_SPEED, (v + w * half) / top * MAX_SPEED)
    clamp = lambda s: int(max(-MAX_SPEED, min(MAX_SPEED, round(s))))  # noqa: E731
    return clamp(left), clamp(right)
