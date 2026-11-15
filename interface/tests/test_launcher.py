"""Launcher logic tests: no window is opened; only the pure pieces (focus, confirmation, summaries, drawing)."""

from dataclasses import replace

import numpy as np

from interface import launcher as la
from interface import launcher_view as view
from interface.launcher_modes import LIVE, PRACTICE


def _middle(rect):
    return (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2


def test_live_modes_ask_for_confirmation_and_practice_modes_start_at_once():
    # Arrange
    state = view.HomeState()
    live_index = len(PRACTICE)

    # Act
    after_practice, practice_mode = la.choose(state, 0, now=1.0)
    after_live, live_mode = la.choose(state, live_index, now=1.0)

    # Assert
    assert practice_mode == PRACTICE[0] and after_practice.sheet is None
    assert live_mode is None and after_live.sheet == LIVE[0] and after_live.sheet_focus == 0  # Cancel focused


def test_confirmation_sheet_starts_only_on_the_start_button():
    # Arrange
    state = replace(view.HomeState(), sheet=LIVE[0], sheet_focus=0)
    cancel, start = view.sheet_buttons()

    # Act / Assert
    assert la.handle_sheet(state, la.ENTER, [])[1] is None             # Enter on Cancel: nothing starts
    assert la.handle_sheet(state, la.ESC, [])[1] is None
    assert la.handle_sheet(state, -1, [_middle(cancel)])[1] is None
    assert la.handle_sheet(state, -1, [_middle(start)])[1] == LIVE[0]
    focused_start = la.handle_sheet(state, la.RIGHT, [])[0]
    assert la.handle_sheet(focused_start, la.ENTER, [])[1] == LIVE[0]


def test_arrow_keys_move_focus_to_the_neighbouring_card():
    # Arrange: practice row 1 = cards 0-3, row 2 = 4-6; live row = 7-10
    first_live = len(PRACTICE)

    # Act / Assert
    assert la.neighbour(0, la.RIGHT) == 1
    assert la.neighbour(1, la.LEFT) == 0
    assert la.neighbour(0, la.DOWN) == 4
    assert la.neighbour(4, la.DOWN) == first_live
    assert la.neighbour(0, la.UP) == 0          # nothing above: focus stays


def test_clicking_a_card_chooses_it():
    # Arrange
    rect = view.card_rects()[3]

    # Act
    state, chosen, quit_now = la.handle_home(view.HomeState(), -1, [_middle(rect)], now=1.0)

    # Assert
    assert chosen == PRACTICE[3] and state.focus == 3 and not quit_now


def test_summary_picks_the_last_error_line_without_log_prefixes():
    # Arrange: what demo.sh prints when the headset Wi-Fi is missing, after some normal output
    text = ("2026-11-15 02:10:00,123 INFO vision.object_select: session log: x.log\n"
            "The laptop is not on the headset's Wi-Fi, so the jaw clench cannot be read.\n"
            "Fix: quit the OpenBCI GUI (Cmd+Q), then join the 'OpenBCI-xxxx' Wi-Fi network and run this again.\n")

    # Act
    line = la.summary_line(text)

    # Assert
    assert line == "The laptop is not on the headset's Wi-Fi, so the jaw clench cannot be read."


def test_summary_of_an_empty_log_is_none():
    assert la.summary_line("") is None


def test_hover_glow_eases_toward_the_hovered_card_and_fades_elsewhere():
    # Act
    rising = la.ease_hover({}, 2, dt=0.05)
    falling = la.ease_hover({2: 1.0}, None, dt=0.05)

    # Assert
    assert 0 < rising[2] < 1 and 0 < falling.get(2, 0) < 1


def test_home_and_sheet_render_at_canvas_size():
    # Act
    home = view.render_home(view.HomeState(readiness={"headset": True}, clock=10.0))
    sheet = view.render_home(view.HomeState(sheet=LIVE[0], clock=10.0, sheet_open_s=9.0))

    # Assert
    assert home.shape == sheet.shape == (view.H, view.W, 3) and home.dtype == np.uint8
    assert (home != sheet).any()
