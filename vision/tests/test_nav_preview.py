import pytest

from vision.nav_preview import direction_label


@pytest.mark.parametrize("left, right, label", [
    (0, 0, "STOP"),
    (100, 100, "FORWARD"),
    (100, 70, "FORWARD + RIGHT"),
    (70, 100, "FORWARD + LEFT"),
    (60, -60, "SPIN RIGHT"),
    (-60, 60, "SPIN LEFT"),
    (3, -2, "STOP"),  # tiny speeds below the board's dead zone count as stopped
])
def test_direction_label(left, right, label):
    assert direction_label(left, right) == label
