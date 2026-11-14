"""Tests for vision/destinations.py. No network: Gemini is replaced by fakes."""

import json
import time

import numpy as np

from vision.destinations import (
    Destination,
    GeminiRanker,
    gemini_only_id,
    iou,
    parse_gemini_json,
    rank_targets,
)
from vision.detect_track import Track


def track(tid, bbox, label="chair"):
    return Track(id=tid, label=label, conf=0.9, bbox=bbox, distance_m=2.0)


def test_parse_converts_0_1000_boxes_to_pixels_and_skips_bad_items():
    reply = json.dumps([
        {"label": "door", "box_2d": [100, 500, 900, 700], "score": 0.9, "reason": "exit"},
        {"label": "broken"},  # missing box: skipped
        {"label": "flat", "box_2d": [500, 500, 500, 600], "score": 0.5},  # zero height: skipped
    ])
    result = parse_gemini_json(reply, width=1000, height=500)
    assert result == [Destination("door", (500.0, 50.0, 700.0, 450.0), 0.9, "exit")]


def test_parse_never_raises_on_garbage():
    assert parse_gemini_json("not json", 640, 480) == []
    assert parse_gemini_json('{"label": "door"}', 640, 480) == []


def test_iou_basic_cases():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == 5 * 10 / (100 + 100 - 50)


def test_rank_puts_gemini_matches_first_and_relabels_them():
    table = track(1, (100, 100, 300, 300), label="dining table")
    chair = track(2, (500, 100, 600, 300))
    dest = Destination("table with items", (110, 110, 290, 290), 0.8, "has a bottle")
    ranked = rank_targets([chair, table], [dest], first_seen={1: 0.0, 2: 0.0})
    assert [t.id for t in ranked] == [1, 2]
    assert ranked[0].label == "table with items"
    assert ranked[0].distance_m == 2.0  # keeps YOLO tracking data
    assert table.label == "dining table"  # input not modified


def test_rank_adds_gemini_only_targets_like_doors():
    door = Destination("door", (800, 0, 950, 400), 0.9, "exit")
    ranked = rank_targets([track(1, (0, 0, 100, 100))], [door], first_seen={1: 0.0})
    assert ranked[0].label == "door" and ranked[0].id < 0
    assert ranked[1].id == 1


def test_rank_falls_back_to_yolo_when_gemini_has_nothing():
    tracks = [track(i, (i * 100, 0, i * 100 + 50, 50)) for i in range(1, 6)]
    first_seen = {1: 4.0, 2: 0.0, 3: 1.0, 4: 2.0, 5: 3.0}
    assert [t.id for t in rank_targets(tracks, [], first_seen)] == [2, 3, 4, 5]


def test_gemini_only_id_is_stable_for_the_same_place():
    a = Destination("door", (800, 0, 950, 400), 0.9, "")
    b = Destination("door", (810, 5, 940, 390), 0.7, "")  # next answer, slightly moved box
    assert gemini_only_id(a) == gemini_only_id(b) < 0


def test_ranker_keeps_answer_and_survives_errors():
    calls = []

    def fake_query(_client, _frame, _previous=()):
        calls.append(1)
        if len(calls) == 1:
            return [Destination("door", (0, 0, 10, 10), 0.9, "")]
        raise RuntimeError("network down")

    ranker = GeminiRanker(None, lambda: np.zeros((10, 10, 3), np.uint8), query=fake_query)
    ranker.start()
    time.sleep(0.2)
    ranker.stop()
    assert [d.label for d in ranker.latest()] == ["door"]


def test_parse_drops_low_score_suggestions():
    reply = json.dumps([{"label": "unclear target area", "box_2d": [0, 0, 1000, 1000], "score": 0.01}])
    assert parse_gemini_json(reply, 640, 480) == []


def test_user_prompt_carries_previous_labels():
    from vision.destinations import build_user_prompt

    assert "Previous" not in build_user_prompt([])
    assert '"left door"' in build_user_prompt([Destination("left door", (0, 0, 1, 1), 0.9, "")])
