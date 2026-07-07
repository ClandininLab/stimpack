"""Unit tests for VisualStimServer's screen->client error forwarding (no screens launched)."""
import pytest

pytest.importorskip("moderngl")   # importing stim_server pulls in the framework/GL import chain
pytest.importorskip("PyQt6")
pytest.importorskip("numpy")

from stimpack.visual_stim.stim_server import VisualStimServer

pytestmark = pytest.mark.unit


def test_forward_screen_message_tags_and_forwards():
    # A message a screen subprocess pushes back is forwarded (tagged) via error_reporter toward the client.
    vss = VisualStimServer.__new__(VisualStimServer)  # bypass __init__ (which launches screen subprocesses)
    forwarded = []
    vss.error_reporter = lambda level, text: forwarded.append((level, text))
    vss._forward_screen_message("error", "bad stim param")
    assert forwarded == [("error", "[screen] bad stim param")]


def test_forward_screen_message_no_reporter_is_safe():
    vss = VisualStimServer.__new__(VisualStimServer)
    vss.error_reporter = None
    vss._forward_screen_message("error", "x")  # must not raise
