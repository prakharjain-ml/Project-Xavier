"""Tests for vision/scene_ai.py. No network: Gemini is replaced by fakes, and nothing here opens a camera."""

import json
import logging
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from vision import scene_ai
from vision.scene_ai import (
    SceneAdvice,
    SceneAdvisor,
    advice_valid,
    build_user_prompt,
    make_client,
    make_thumb,
    parse_scene_json,
    query_scene,
    scene_changed,
)

WAIT_S = 5.0  # generous upper bound for anything that happens on the advisor's thread, so a busy laptop does not flake
FRAME_W, FRAME_H = 200, 100


def point(x, y):
    return {"x": x, "y": y}


def box(label, left, top, right, bottom):
    return {"label": label, "left": left, "top": top, "right": right, "bottom": bottom}


def reply(floor=None, no_go=None, route=None) -> str:
    """A well-formed reply; each test overrides the part it wants to break."""
    return json.dumps({
        "floor": [[point(0, 1000), point(0, 500), point(1000, 500), point(1000, 1000)]] if floor is None else floor,
        "no_go": [box("table", 100, 600, 300, 800)] if no_go is None else no_go,
        "route": [point(500, 1000), point(500, 700)] if route is None else route,
    })


def textured_frame(seed: int = 0, width: int = 320, height: int = 240) -> np.ndarray:
    """A frame with large random blocks, so that moving the camera really changes the thumbnail."""
    blocks = np.random.default_rng(seed).integers(0, 256, (6, 8, 3), dtype=np.uint8)
    return np.kron(blocks, np.ones((height // 6, width // 8, 1), dtype=np.uint8))


def make_advice(frame: np.ndarray, frame_t: float = 0.0, model: str = "fake") -> SceneAdvice:
    return SceneAdvice(floor=(), no_go=(), route=np.empty((0, 2)), target_id=None, frame_t=frame_t,
                       thumb=make_thumb(frame), model=model, latency_s=0.0)


def wait_until(condition, timeout: float = WAIT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@pytest.fixture
def advisor_factory():
    """Builds advisors and always stops them, so a failing test never leaves a thread behind."""
    made = []

    def build(query, client="fake-client", min_interval_s=0.0):
        advisor = SceneAdvisor(client, query=query, min_interval_s=min_interval_s)
        made.append(advisor)
        advisor.start()
        return advisor

    yield build
    for advisor in made:
        advisor.stop()


# ---------------------------------------------------------------- parse_scene_json

def test_parse_scales_a_good_reply_from_0_1000_to_frame_pixels():
    # Arrange
    text = reply()

    # Act
    floor, no_go, route = parse_scene_json(text, FRAME_W, FRAME_H)

    # Assert: x is scaled by 200/1000 and y by 100/1000; the right and bottom edges clamp to the last pixel
    assert len(floor) == 1
    np.testing.assert_allclose(floor[0], [[0, 99], [0, 50], [199, 50], [199, 99]])
    assert [label for label, _ in no_go] == ["table"]
    np.testing.assert_allclose(no_go[0][1], [[20, 60], [60, 60], [60, 80], [20, 80]])  # 4 corners, clockwise
    np.testing.assert_allclose(route, [[100, 99], [100, 70]])


def test_parse_accepts_an_empty_route_and_keeps_its_shape():
    floor, no_go, route = parse_scene_json(reply(route=[]), FRAME_W, FRAME_H)

    assert route.shape == (0, 2)
    assert len(floor) == 1 and len(no_go) == 1


@pytest.mark.parametrize("text", ["not json", "", '{"floor": [', None, 42, b'{"floor": []}'])
def test_parse_raises_value_error_on_text_that_is_not_json(text):
    with pytest.raises(ValueError):
        parse_scene_json(text, FRAME_W, FRAME_H)


@pytest.mark.parametrize("text", [
    "[]",                                                  # top level is not an object
    '"floor"',
    json.dumps({"floor": [], "no_go": []}),                # route missing
    json.dumps({"floor": {}, "no_go": [], "route": []}),   # floor is not a list
    reply(floor=[point(1, 2)]),                            # a polygon must be a list of points
    reply(floor=[[[1, 2], [3, 4], [5, 6]]]),               # points must be {"x", "y"} objects
    reply(floor=[[point(1, 2), {"x": 3}, point(5, 6)]]),   # a point without y
    reply(no_go=["table"]),                                # a no-go entry must be an object
    reply(no_go=[{"label": "table", "left": 1, "top": 2, "right": 3}]),  # bottom missing
    reply(no_go=[box(7, 100, 600, 300, 800)]),             # label must be text
    reply(route="straight ahead"),
    reply(route=[point(1, 2), "end"]),
])
def test_parse_raises_value_error_on_the_wrong_shape(text):
    with pytest.raises(ValueError):
        parse_scene_json(text, FRAME_W, FRAME_H)


def test_parse_clamps_out_of_range_coordinates_to_the_frame():
    # Arrange: points far outside 0-1000 on every side
    text = reply(floor=[[point(-500, 2000), point(-1, -1), point(99999, 400), point(1500, 1e9)]],
                 no_go=[box("wall", -300, -300, 5000, 5000)], route=[point(-1, 1001)])

    # Act
    floor, no_go, route = parse_scene_json(text, FRAME_W, FRAME_H)

    # Assert: every coordinate lies inside the 200 x 100 frame
    for polygon in (floor[0], no_go[0][1], route):
        assert polygon[:, 0].min() >= 0 and polygon[:, 0].max() <= FRAME_W - 1
        assert polygon[:, 1].min() >= 0 and polygon[:, 1].max() <= FRAME_H - 1
    np.testing.assert_allclose(route, [[0, 99]])


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999", '"12"', "true", "null", "[1]", "1" + "0" * 400])
def test_parse_raises_value_error_on_non_finite_or_non_numeric_coordinates(bad):
    # Arrange: the same bad value once in each of the three parts of the reply
    as_floor = '{"floor": [[{"x": %s, "y": 1}, {"x": 2, "y": 3}, {"x": 9, "y": 9}]], "no_go": [], "route": []}' % bad
    as_no_go = '{"floor": [], "no_go": [{"label": "a", "left": 1, "top": %s, "right": 5, "bottom": 9}], "route": []}' % bad
    as_route = '{"floor": [], "no_go": [], "route": [{"x": 1, "y": %s}]}' % bad

    # Act / Assert
    for text in (as_floor, as_no_go, as_route):
        with pytest.raises(ValueError):
            parse_scene_json(text, FRAME_W, FRAME_H)


def test_parse_drops_degenerate_polygons_and_keeps_the_good_ones():
    # Arrange
    good = [point(0, 0), point(500, 0), point(500, 500)]
    text = reply(
        floor=[[], [point(1, 1), point(900, 900)],                  # fewer than 3 points
               [point(0, 0), point(400, 400), point(800, 800)],     # 3 points on one line: no area
               [point(10, 10), point(10, 10), point(10, 10)],       # the same point three times
               good],
        no_go=[box("flat", 100, 500, 900, 500),                     # zero height
               box("inside out", 900, 100, 100, 900),               # right edge left of the left edge
               box("ok", 100, 100, 900, 900)])

    # Act
    floor, no_go, _ = parse_scene_json(text, FRAME_W, FRAME_H)

    # Assert
    assert len(floor) == 1 and floor[0].shape == (3, 2)
    assert [label for label, _ in no_go] == ["ok"]


def test_parse_shortens_long_labels():
    _, no_go, _ = parse_scene_json(reply(no_go=[box("x" * 500, 100, 100, 900, 900)]), FRAME_W, FRAME_H)

    assert len(no_go[0][0]) == scene_ai.MAX_LABEL_CHARS


@pytest.mark.parametrize("width, height", [(0, 100), (200, -1), (200.5, 100), ("200", 100), (True, 100)])
def test_parse_raises_value_error_on_a_bad_frame_size(width, height):
    with pytest.raises(ValueError):
        parse_scene_json(reply(), width, height)


def test_parse_raises_value_error_on_an_oversized_reply():
    with pytest.raises(ValueError):
        parse_scene_json(reply() + " " * scene_ai.MAX_REPLY_CHARS, FRAME_W, FRAME_H)


# ---------------------------------------------------------------- scene_changed / advice_valid (C6)

def test_scene_is_unchanged_for_the_same_view_with_sensor_noise():
    # Arrange
    frame = textured_frame()
    noise = np.random.default_rng(1).normal(0, 6, frame.shape)
    noisy = np.clip(frame.astype(np.float64) + noise, 0, 255).astype(np.uint8)

    # Act / Assert
    assert scene_changed(make_thumb(frame), frame) is False
    assert scene_changed(make_thumb(frame), noisy) is False


def test_scene_is_changed_when_the_camera_looks_somewhere_else():
    frame = textured_frame(seed=0)

    assert scene_changed(make_thumb(frame), textured_frame(seed=1)) is True
    assert scene_changed(make_thumb(frame), np.roll(frame, frame.shape[1] // 8, axis=1)) is True  # panned by 1/8


@pytest.mark.parametrize("frame", [None, np.zeros((0, 0, 3), np.uint8), "frame", np.zeros(5, np.uint8)])
def test_scene_counts_as_changed_when_there_is_no_usable_frame(frame):
    assert scene_changed(make_thumb(textured_frame()), frame) is True


def test_make_thumb_is_small_grey_and_leaves_the_frame_untouched():
    # Arrange
    frame = textured_frame()
    before = frame.copy()

    # Act
    thumb = make_thumb(frame)

    # Assert
    assert thumb.shape == (scene_ai.THUMB_HEIGHT, scene_ai.THUMB_WIDTH) and thumb.dtype == np.uint8
    np.testing.assert_array_equal(frame, before)
    np.testing.assert_array_equal(make_thumb(frame[:, :, 0]), make_thumb(frame[:, :, 0]))  # grey frames work too


def test_advice_is_valid_when_fresh_and_the_scene_is_unchanged():
    frame = textured_frame()
    advice = make_advice(frame, frame_t=100.0)

    assert advice_valid(advice, frame, now=103.0) is True
    assert advice_valid(advice, frame, now=110.0) is True  # exactly 10 s old is still accepted


def test_advice_is_invalid_when_the_scene_changed():
    advice = make_advice(textured_frame(seed=0), frame_t=100.0)

    assert advice_valid(advice, textured_frame(seed=1), now=101.0) is False


def test_advice_is_invalid_when_older_than_the_maximum_age():
    frame = textured_frame()
    advice = make_advice(frame, frame_t=100.0)

    assert advice_valid(advice, frame, now=110.5) is False
    assert advice_valid(advice, frame, now=103.0, max_age_s=2.0) is False


def test_advice_is_invalid_when_missing_or_when_the_clock_makes_no_sense():
    frame = textured_frame()
    advice = make_advice(frame, frame_t=100.0)

    assert advice_valid(None, frame, now=100.0) is False
    assert advice_valid(advice, None, now=100.0) is False
    assert advice_valid(advice, frame, now=99.0) is False            # advice "from the future"
    assert advice_valid(advice, frame, now=float("nan")) is False


# ---------------------------------------------------------------- SceneAdvisor with a fake query

def test_advisor_delivers_the_answer_stamped_with_the_request():
    # Arrange
    frame = textured_frame()
    seen = []

    def query(client, got_frame, target_label, target_box):
        seen.append((client, target_label, target_box))
        return make_advice(got_frame, frame_t=-1.0)

    advisor = SceneAdvisor("fake-client", query=query, min_interval_s=0.0)
    advisor.start()
    try:
        # Act
        advisor.submit(frame, 12.5, 7, "armchair", (1.0, 2.0, 3.0, 4.0))
        arrived = wait_until(lambda: advisor.latest() is not None)

        # Assert
        assert arrived
        advice = advisor.latest()
        assert (advice.frame_t, advice.target_id) == (12.5, 7)  # taken from the request, not from the query
        assert seen == [("fake-client", "armchair", (1.0, 2.0, 3.0, 4.0))]
        assert advisor.status() == "ready"
        assert advice_valid(advice, frame, now=13.0)
    finally:
        advisor.stop()


def test_advisor_keeps_only_the_newest_request(advisor_factory):
    # Arrange: the first call blocks, so the next three requests pile up behind it
    release = threading.Event()
    labels = []

    def query(client, frame, target_label, target_box):
        labels.append(target_label)
        if target_label == "first":
            release.wait(WAIT_S)
        return make_advice(frame, model=target_label)

    advisor = advisor_factory(query)
    frame = textured_frame()
    advisor.submit(frame, 1.0, 1, "first", None)
    assert wait_until(lambda: labels == ["first"])

    # Act
    for index, label in enumerate(["second", "third", "newest"]):
        advisor.submit(frame, 2.0 + index, 2 + index, label, None)
    release.set()

    # Assert: "second" and "third" were never sent
    assert wait_until(lambda: advisor.latest() is not None and advisor.latest().model == "newest")
    assert labels == ["first", "newest"]
    assert advisor.latest().target_id == 4


def test_advisor_reports_failed_when_the_query_raises_and_then_keeps_working(advisor_factory, caplog):
    # Arrange
    def query(client, frame, target_label, target_box):
        if target_label == "bad":
            raise RuntimeError("boom api-key-SECRET-123")
        return make_advice(frame, model="recovered")

    advisor = advisor_factory(query)
    frame = textured_frame()

    # Act 1: a failing call
    with caplog.at_level(logging.DEBUG):
        advisor.submit(frame, 1.0, 1, "bad", None)  # must not raise into the caller (C7)
        failed = wait_until(lambda: advisor.status() == "failed")

    # Assert 1
    assert failed
    assert advisor.latest() is None
    assert "RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text  # C10: the error text may carry request details, so it is never logged

    # Act 2: the next request still gets answered
    advisor.submit(frame, 2.0, 2, "good", None)

    # Assert 2
    assert wait_until(lambda: advisor.status() == "ready")
    assert advisor.latest().model == "recovered"


def test_advisor_reports_failed_when_the_query_returns_something_that_is_not_advice(advisor_factory):
    advisor = advisor_factory(lambda client, frame, label, target_box: {"floor": []})

    advisor.submit(textured_frame(), 1.0, 1, "x", None)

    assert wait_until(lambda: advisor.status() == "failed")
    assert advisor.latest() is None


def test_advisor_keeps_the_last_good_answer_after_a_later_failure(advisor_factory):
    def query(client, frame, target_label, target_box):
        if target_label == "bad":
            raise OSError("network down")
        return make_advice(frame, model="good")

    advisor = advisor_factory(query)
    frame = textured_frame()
    advisor.submit(frame, 1.0, 1, "ok", None)
    assert wait_until(lambda: advisor.status() == "ready")

    advisor.submit(frame, 2.0, 2, "bad", None)

    assert wait_until(lambda: advisor.status() == "failed")
    assert advisor.latest().model == "good"  # still there; advice_valid() retires it by age (C6)


def test_advisor_makes_at_most_one_call_per_interval(advisor_factory):
    # Arrange
    interval_s = 0.25
    starts = []

    def query(client, frame, target_label, target_box):
        starts.append(time.monotonic())
        return make_advice(frame)

    advisor = advisor_factory(query, min_interval_s=interval_s)
    frame = textured_frame()

    # Act: ask far more often than the limit allows, for long enough to see several calls
    began = time.monotonic()
    while len(starts) < 4 and time.monotonic() - began < WAIT_S:
        advisor.submit(frame, time.monotonic(), 1, "x", None)
        time.sleep(0.01)
    elapsed = time.monotonic() - began

    # Assert: calls happened, but never closer together than the interval (C11)
    assert len(starts) >= 4
    gaps = np.diff(starts)
    # The limit is kept by the advisor's own clock just before each call; 50 ms of slack covers a busy scheduler.
    assert gaps.min() >= interval_s - 0.05
    assert len(starts) <= elapsed / interval_s + 1


def test_submit_returns_immediately_even_when_the_query_is_slow(advisor_factory):
    # Arrange: every call takes a full second
    slow_s = 1.0
    started = threading.Event()

    def query(client, frame, target_label, target_box):
        started.set()
        time.sleep(slow_s)
        return make_advice(frame)

    advisor = advisor_factory(query)
    frame = textured_frame()
    advisor.submit(frame, 0.0, 1, "x", None)
    assert started.wait(WAIT_S)  # the slow call is now in flight

    # Act: 50 more submits while the call is still running
    began = time.monotonic()
    for index in range(50):
        advisor.submit(frame, float(index), 1, "x", None)
    took = time.monotonic() - began

    # Assert: nowhere near the 1 s a blocked submit would cost
    assert took < slow_s / 2
    assert advisor.status() == "analysing"


def test_submit_copies_the_frame_so_later_changes_by_the_caller_do_not_reach_the_query(advisor_factory):
    # Arrange
    release = threading.Event()
    means = []

    def query(client, frame, target_label, target_box):
        release.wait(WAIT_S)
        means.append(float(frame.mean()))
        return make_advice(frame)

    advisor = advisor_factory(query)
    frame = np.full((40, 60, 3), 200, np.uint8)

    # Act: the caller reuses its buffer right after submitting
    advisor.submit(frame, 1.0, 1, "x", None)
    frame[:] = 0
    release.set()

    # Assert
    assert wait_until(lambda: len(means) == 1)
    assert means == [200.0]


def test_advisor_is_off_without_a_client_and_submit_is_harmless():
    # Arrange
    calls = []
    advisor = SceneAdvisor(None, query=lambda *args: calls.append(args))

    # Act
    advisor.start()
    advisor.submit(textured_frame(), 1.0, 1, "x", None)
    time.sleep(0.05)
    advisor.stop()

    # Assert
    assert advisor.status() == "off"
    assert advisor.latest() is None
    assert calls == []


def test_advisor_status_is_analysing_until_the_first_answer_and_off_after_stop():
    advisor = SceneAdvisor("fake-client", query=lambda client, frame, label, target_box: make_advice(frame),
                           min_interval_s=0.0)

    assert advisor.status() == "off"  # not started yet
    advisor.start()
    assert advisor.status() == "analysing"
    advisor.stop()
    assert advisor.status() == "off"


def test_stop_joins_the_thread_and_can_be_called_twice():
    # Arrange
    advisor = SceneAdvisor("fake-client", query=lambda client, frame, label, target_box: make_advice(frame),
                           min_interval_s=0.0)
    advisor.start()
    advisor.submit(textured_frame(), 1.0, 1, "x", None)
    assert wait_until(lambda: advisor.latest() is not None)
    workers = [t for t in threading.enumerate() if t.name == scene_ai.THREAD_NAME]
    assert len(workers) == 1 and workers[0].daemon

    # Act
    advisor.stop()
    advisor.stop()

    # Assert
    assert not workers[0].is_alive()
    advisor.submit(textured_frame(), 2.0, 1, "x", None)  # after stop: ignored, does not raise


def test_stop_before_start_does_not_raise():
    SceneAdvisor("fake-client", query=lambda *args: None).stop()


# ---------------------------------------------------------------- make_client / query_scene (fake client, no network)

def test_make_client_returns_none_when_there_is_no_key(monkeypatch):
    monkeypatch.setattr(scene_ai, "load_api_key", lambda: None)

    assert make_client() is None
    assert SceneAdvisor(make_client()).status() == "off"


class FakeModels:
    """Stands in for client.models: answers per model name, either with reply text or by raising."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        answer = self.answers[model]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=answer)


def test_query_scene_parses_the_reply_in_pixels_of_the_frame_that_was_given(monkeypatch):
    # Arrange: a frame wider than the upload size, so the reply must be scaled to the frame, not to the upload
    monkeypatch.setattr(scene_ai, "GEMINI_MODELS", ("model-a",))
    models = FakeModels({"model-a": reply()})
    frame = textured_frame(width=1280, height=720)
    before = frame.copy()

    # Act
    advice = query_scene(SimpleNamespace(models=models), frame, "armchair", (640.0, 360.0, 1280.0, 720.0))

    # Assert
    np.testing.assert_allclose(advice.floor[0], [[0, 719], [0, 360], [1279, 360], [1279, 719]])
    assert advice.model == "model-a" and advice.target_id is None and advice.latency_s >= 0.0
    assert not scene_changed(advice.thumb, frame)
    np.testing.assert_array_equal(frame, before)  # the input frame is not modified
    model, contents, config = models.calls[0]
    assert "armchair" in contents[1] and "left 500, top 500, right 1000, bottom 1000" in contents[1]
    assert config.response_mime_type == "application/json"


def test_query_scene_falls_back_to_the_next_model_and_never_logs_the_error_text(monkeypatch, caplog):
    # Arrange
    monkeypatch.setattr(scene_ai, "GEMINI_MODELS", ("model-a", "model-b"))
    models = FakeModels({"model-a": RuntimeError("503 overloaded key=SECRET-123"), "model-b": reply()})

    # Act
    with caplog.at_level(logging.DEBUG):
        advice = query_scene(SimpleNamespace(models=models), textured_frame(), None, None)

    # Assert
    assert advice.model == "model-b"
    assert [call[0] for call in models.calls] == ["model-a", "model-b"]
    assert "model-a" in caplog.text and "SECRET" not in caplog.text  # C10


def test_query_scene_raises_when_every_model_fails_or_replies_with_junk(monkeypatch):
    monkeypatch.setattr(scene_ai, "GEMINI_MODELS", ("model-a", "model-b"))
    models = FakeModels({"model-a": TimeoutError("slow"), "model-b": "not json"})

    with pytest.raises(RuntimeError):
        query_scene(SimpleNamespace(models=models), textured_frame(), "armchair", (0.0, 0.0, 10.0, 10.0))


def test_query_scene_does_not_try_another_model_after_a_slow_failure(monkeypatch):
    # Arrange: the first model burns the whole retry window before failing
    monkeypatch.setattr(scene_ai, "GEMINI_MODELS", ("model-a", "model-b"))
    monkeypatch.setattr(scene_ai, "RETRY_WINDOW_S", 0.05)

    class SlowModels(FakeModels):
        def generate_content(self, model, contents, config):
            time.sleep(0.1)
            return super().generate_content(model, contents, config)

    models = SlowModels({"model-a": TimeoutError("slow"), "model-b": reply()})

    # Act / Assert: an answer this late would be stale anyway, so model-b is not asked
    with pytest.raises(RuntimeError):
        query_scene(SimpleNamespace(models=models), textured_frame(), None, None)
    assert [call[0] for call in models.calls] == ["model-a"]


@pytest.mark.parametrize("frame", [None, np.zeros((0, 0, 3), np.uint8), "frame"])
def test_query_scene_rejects_a_missing_or_empty_frame(frame):
    with pytest.raises(ValueError):
        query_scene(SimpleNamespace(models=FakeModels({})), frame, None, None)


def test_user_prompt_gives_the_target_box_in_0_1000_units_and_cleans_the_label():
    # Act
    prompt = build_user_prompt("arm\nchair  " + "x" * 200, (100.0, 50.0, 200.0, 100.0), width=400, height=200)

    # Assert
    assert "left 250, top 250, right 500, bottom 500" in prompt
    assert "\n" not in prompt and len(prompt) < 200


def test_user_prompt_asks_for_no_route_when_there_is_no_target():
    assert "empty" in build_user_prompt(None, None, 400, 200)
    assert "empty" in build_user_prompt("armchair", None, 400, 200)
