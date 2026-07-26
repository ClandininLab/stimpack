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


# --- the timestamp must not leak to other modules (#29) ------------------------------------------

def test_timestamping_screen_requests_does_not_mutate_the_shared_request():
    """Under target='all' the server hands the SAME dict objects to every module.

    VisualStimServer runs first and stamps 't' onto the screen-bound requests. Editing in place put
    that 't' into the dicts locomotion and voltage_out then receive -- invisible only because
    neither implements any of time_stamp_commands. The first module that does would get a TypeError
    on a signature that looks correct.
    """
    from stimpack.visual_stim.stim_server import VisualStimServer

    server = VisualStimServer.__new__(VisualStimServer)
    server.functions_on_root = {}
    server.screen_managers = []
    server.time_stamp_commands = ['start_stim']

    shared = {'target': 'all', 'name': 'start_stim', 'args': [], 'kwargs': {'append_stim_frames': False}}
    server.handle_request_list([shared])

    assert shared['kwargs'] == {'append_stim_frames': False}, \
        "the request another module will receive was mutated"
