"""The rider app must never create synthetic perception (no devices are opened here)."""

import pytest

from interface.web.server import make_perception
from interface.web.session import ActionError


@pytest.mark.parametrize("mode", ["mock", "synthetic", "", None])
def test_product_factory_rejects_generated_input(mode):
    with pytest.raises(ActionError, match="Real cameras required"):
        make_perception(mode, {})


def test_live_input_requires_both_cameras():
    with pytest.raises(ActionError, match="Choose the eye camera"):
        make_perception("live", {"forward_camera": 0})


def test_live_input_requires_distinct_cameras():
    with pytest.raises(ActionError, match="Choose different cameras"):
        make_perception("live", {"forward_camera": 0, "eye_camera": 0})
