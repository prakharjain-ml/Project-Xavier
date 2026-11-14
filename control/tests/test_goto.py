"""Drive-to-object: camera obstacles + one planner step per frame (control/goto.py)."""

import math

import numpy as np
import pytest

from control.goto import NavState, nav_step, obstacles_from_tracks
from control.navigation import ARRIVE_M, WHEEL_DEAD_BAND, NavConfig, motion
from vision.detect_track import TYPICAL_HEIGHT_M, Track, estimate_distance_m, focal_length_px

W, H, HFOV = 1920, 1080, 85.5
FOCAL = focal_length_px(W, HFOV)
CFG = NavConfig()
CAMERA_HEIGHT_M = 1.0  # simulated forward camera: this far above the floor, looking level


def track(tid, x_center, width=200, distance=2.0, label="chair"):
    return Track(id=tid, label=label, conf=0.9, bbox=(x_center - width / 2, 300, x_center + width / 2, 700),
                 distance_m=distance)


def test_other_objects_become_obstacles_with_their_width_target_excluded():
    target, chair = track(1, 960), track(2, 1500, width=300, distance=1.5)
    pts = obstacles_from_tracks([target, chair], exclude_id=1, frame_w=W, hfov_deg=HFOV)
    assert pts.shape == (3, 2)  # left edge, centre, right edge of the chair; nothing for the target
    assert all(p[1] < 0 for p in pts)  # chair is right of centre -> negative y (right side)
    assert all(math.hypot(*p) == pytest.approx(1.5, abs=0.01) for p in pts)


def test_objects_without_a_distance_are_skipped():
    no_dist = Track(id=3, label="person", conf=0.9, bbox=(0, 0, 10, 10), distance_m=None)
    assert obstacles_from_tracks([no_dist], exclude_id=1, frame_w=W, hfov_deg=HFOV).shape == (0, 2)


def test_centred_target_drives_straight():
    nav, (left, right), arrived = nav_step(NavState(), track(1, 960, distance=3.0), [], W, HFOV, distance_cm=None)
    assert not arrived and left > 0 and right > 0 and abs(left - right) <= 2


def test_target_on_the_right_turns_right():
    nav = NavState()
    for _ in range(5):  # let the planner ramp up (it limits acceleration)
        nav, (left, right), _ = nav_step(nav, track(1, 1700, distance=2.5), [], W, HFOV, distance_cm=None)
    assert left > right  # left wheel faster = turning right


def test_arrived_stops_and_says_so():
    nav, wheels, arrived = nav_step(NavState(v=0.3), track(1, 960, distance=ARRIVE_M - 0.1), [], W, HFOV, None)
    assert arrived and wheels == (0, 0)


def test_ultrasonic_obstacle_ahead_prevents_driving_into_it():
    nav = NavState()
    speeds = []
    for _ in range(10):
        nav, (left, right), _ = nav_step(nav, track(1, 960, distance=3.0), [], W, HFOV, distance_cm=40)
        speeds.append((left + right) / 2)
    assert max(speeds) <= 0  # something 40 cm ahead: never drives forward into it


def test_nav_state_is_immutable():
    state = NavState()
    nav_step(state, track(1, 960, distance=3.0), [], W, HFOV, None)
    assert (state.v, state.w) == (0.0, 0.0)


# --- Arrival when the camera cannot measure any closer (nav_step(..., frame_h=...)) ---------------------------
# Distance comes from the height of the box, and a box cannot be taller than the picture, so a chair never reads
# under 0.87 m, a dining table 0.72 m, a person 1.63 m (1920x1080, 85.5 deg). ARRIVE_M is 0.7 m. Without the
# frame height the planner drove an ideal chair into all three at full speed (audit finding 2).


def centred_view(label, depth_m):
    """The audit's camera: the box sits in the middle of the picture and stops growing when it fills the frame."""
    box_h = min(float(H), TYPICAL_HEIGHT_M[label] * FOCAL / depth_m)
    return (H - box_h) / 2, (H + box_h) / 2


def floor_view(label, depth_m):
    """A level camera 1 m above the floor looking at an object that stands on the floor (pinhole rule: a point
    this many metres above/below the camera lands focal * metres / depth pixels above/below the picture's middle).
    The object's foot drops out of the bottom of the picture once it is nearer than about 1.9 m."""
    top = H / 2 - FOCAL * (TYPICAL_HEIGHT_M[label] - CAMERA_HEIGHT_M) / depth_m
    bottom = H / 2 + FOCAL * CAMERA_HEIGHT_M / depth_m
    return max(0.0, top), min(float(H), bottom)


def seen(label, depth_m, view):
    """The Track the detector would report: the distance comes from the (possibly cut-off) box, as in detect()."""
    y1, y2 = view(label, depth_m)
    return Track(1, label, 0.9, (W / 2 - 100, y1, W / 2 + 100, y2), estimate_distance_m(label, y2 - y1, FOCAL))


def approach(label, view, frame_h, start_m=3.0, steps=400):
    """An ideal chair (moves exactly as commanded) drives at an object straight ahead, no ultrasonic.
    Returns (planner said arrived, last wheel command, true distance still left in metres)."""
    pose, nav, wheels = np.zeros(5), NavState(), (0, 0)
    for _ in range(steps):
        remaining = start_m - pose[0]
        if remaining <= 0.05:
            break  # the chair's centre is on top of the object: it drove into it
        target = seen(label, remaining, view)
        nav, wheels, arrived = nav_step(nav, target, [target], W, HFOV, None, frame_h=frame_h)
        if arrived:
            return True, wheels, remaining
        pose = motion(pose, (nav.v, nav.w), CFG.dt)
    return False, wheels, start_m - pose[0]


@pytest.mark.parametrize("view", [centred_view, floor_view])
@pytest.mark.parametrize("label", ["chair", "dining table", "person"])
def test_chair_stops_and_reports_arrived_before_reaching_an_object_it_cannot_measure_closer(label, view):
    # Arrange: these three can never read under ARRIVE_M at this frame size
    assert TYPICAL_HEIGHT_M[label] * FOCAL / H > ARRIVE_M

    # Act
    arrived, wheels, remaining = approach(label, view, frame_h=H)

    # Assert: stopped, said so, and the chair's body (robot_radius) never got to the object
    assert arrived and wheels == (0, 0)
    assert remaining > CFG.robot_radius


@pytest.mark.parametrize("view", [centred_view, floor_view])
def test_without_frame_h_the_same_approach_never_arrives(view):
    # The reason frame_h exists: the old distance-only rule cannot stop for a chair.
    arrived, _, remaining = approach("chair", view, frame_h=None)
    assert not arrived and remaining < CFG.robot_radius


def test_box_cut_off_at_the_bottom_counts_as_arrived_even_though_it_reads_far():
    # Arrange: measured live Sat Nov 14 on a 1280x720 frame: chairs standing 1.40 m away, legs cut off by the
    # bottom edge, read 1.68 to 1.71 m. The reading is too far because part of the box is missing.
    cut_off = Track(1, "chair", 0.9, (540, 354, 740, 720), distance_m=1.70)

    # Act
    nav, wheels, arrived = nav_step(NavState(v=0.3), cut_off, [cut_off], 1280, HFOV, None, frame_h=720)

    # Assert
    assert arrived and wheels == (0, 0) and nav == NavState()


def test_far_object_whose_box_touches_the_bottom_edge_does_not_count_as_arrived_at_3_m():
    # Arrange: a small box that happens to end on the bottom edge and reads 3 m (camera tipped up, or the
    # detector's box wandering). Small and far-reading is what tells it apart from the near chairs above.
    box_h = TYPICAL_HEIGHT_M["chair"] * FOCAL / 3.0
    far = Track(1, "chair", 0.9, (W / 2 - 85, H - box_h, W / 2 + 85, H), distance_m=3.0)

    # Act
    _, _, arrived = nav_step(NavState(v=0.3), far, [far], W, HFOV, None, frame_h=H)

    # Assert
    assert not arrived


def test_cut_off_box_that_reads_far_is_not_driven_at_because_the_reading_cannot_be_trusted():
    # Arrange: a chair only 0.5 m ahead, seen from above by the camera 1 m up: just its top is in the picture, so
    # the box is short and reads 2.8 m. One frame cannot tell this from the far box in the test above.
    near = seen("chair", 0.5, floor_view)
    assert near.bbox[3] == H and near.distance_m > 2.5

    # Act
    nav, wheels, arrived = nav_step(NavState(v=0.3), near, [near], W, HFOV, None, frame_h=H)

    # Assert: no claim of arrival, and no motion on a number known to be too far (stop is the default)
    assert not arrived and wheels == (0, 0) and nav == NavState()


def test_box_filling_nearly_the_whole_frame_height_counts_as_arrived_without_touching_the_bottom():
    # Arrange: 92% of the frame height, clear of both edges; reads 0.94 m, which is as near as a chair can read
    box_h = 0.92 * H
    full = Track(1, "chair", 0.9, (660, 0.04 * H, 1260, 0.04 * H + box_h), estimate_distance_m("chair", box_h, FOCAL))

    # Act
    _, wheels, arrived = nav_step(NavState(v=0.3), full, [full], W, HFOV, None, frame_h=H)

    # Assert
    assert arrived and wheels == (0, 0)


def test_large_box_fully_inside_the_frame_is_still_measurable_so_it_does_not_arrive():
    # Arrange: 60% of the frame height, foot well above the bottom edge: the camera can still see it grow
    box_h = 0.6 * H
    near = Track(1, "chair", 0.9, (760, 0.2 * H, 1160, 0.2 * H + box_h), estimate_distance_m("chair", box_h, FOCAL))

    # Act
    _, (left, right), arrived = nav_step(NavState(v=0.3), near, [near], W, HFOV, None, frame_h=H)

    # Assert
    assert not arrived and left > 0 and right > 0


def test_frame_h_changes_nothing_for_a_box_the_camera_can_still_measure():
    for distance in (ARRIVE_M - 0.1, 1.5, 3.0):
        target = track(1, 1200, distance=distance)  # box 300..700 px: inside the frame
        assert (nav_step(NavState(v=0.2), target, [target], W, HFOV, None, frame_h=H)
                == nav_step(NavState(v=0.2), target, [target], W, HFOV, None))


def test_without_frame_h_a_frame_filling_box_behaves_exactly_as_before():
    # Old behaviour, kept for callers that do not pass frame_h: only the distance reading decides.
    full = Track(1, "chair", 0.9, (660, 0, 1260, H), estimate_distance_m("chair", H, FOCAL))
    _, (left, right), arrived = nav_step(NavState(v=0.3), full, [full], W, HFOV, None)
    assert not arrived and left > 0 and right > 0


def test_nonsense_frame_h_stops_without_claiming_arrival():
    target = track(1, 960, distance=3.0)
    assert nav_step(NavState(v=0.3), target, [target], W, HFOV, None, frame_h=0) == (NavState(), (0, 0), False)


# --- Motor dead band (audit finding 8) -------------------------------------------------------------------------


def test_stuck_behind_something_60_cm_ahead_the_turn_in_place_really_reaches_the_wheels():
    # Arrange: before the fix these 40 commands stayed within (7..49, -49..-7): the board ignored every one
    nav, commands = NavState(), []

    # Act
    for _ in range(40):
        nav, wheels, _ = nav_step(nav, track(1, 960, distance=3.0), [], W, HFOV, distance_cm=60)
        commands.append(wheels)

    # Assert
    assert all(s == 0 or abs(s) >= WHEEL_DEAD_BAND for pair in commands for s in pair)
    assert any(left * right < 0 for left, right in commands)  # wheels in opposite directions: turning on the spot
