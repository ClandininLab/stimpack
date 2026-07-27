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


def test_frame_times_are_only_profiled_while_the_stimulus_runs():
    """#43: paintGL appended a timestamp whenever a stim was loaded, started or not, so pre-time
    frames landed in the statistics print_profile reports -- and a stimulus loaded but never
    started grew the list for as long as it sat there."""
    import inspect
    import re
    from stimpack.visual_stim import framework

    body = inspect.getsource(framework.StimDisplay.paintGL)
    guard = re.search(r'if self\.stim_started:\s*\n\s*self\.profile_frame_times\.append', body)
    assert guard, "profile_frame_times is appended without a stim_started guard"


# --- error reporting and the removed launch-time kwarg -------------------------------------------

def test_visual_stim_server_reports_to_its_client_by_default():
    """A screen bubbles its errors up to the VisualStimServer, which forwards them via
    error_reporter. That was left as None unless a BaseServer wired it, so a script driving
    launch_stim_server directly -- what every example does -- had screen-side errors silently
    dropped: a failing stimulus did nothing and said nothing."""
    from stimpack.visual_stim.stim_server import VisualStimServer

    server = VisualStimServer.__new__(VisualStimServer)
    sent = []
    server.write_request_list = sent.append
    server.error_reporter = server.report_to_client

    server.error_reporter('error', 'something broke')

    assert sent == [[{'name': 'report_server_message',
                      'args': ['error', 'something broke'], 'kwargs': {}}]]


def test_a_base_server_takes_over_the_reporting():
    """Nested in a BaseServer, messages must reach the experiment client rather than stopping at
    the visual module."""
    import inspect
    from stimpack.experiment.server import BaseServer

    source = inspect.getsource(BaseServer.__init__)
    assert 'module.error_reporter = self.report_to_client' in source


def test_forwarding_a_screen_message_prefixes_its_origin():
    from stimpack.visual_stim.stim_server import VisualStimServer

    server = VisualStimServer.__new__(VisualStimServer)
    got = []
    server.error_reporter = lambda level, text: got.append((level, text))

    server._forward_screen_message('error', 'load_stim blew up')

    assert got == [('error', '[screen] load_stim blew up')]


def test_the_removed_launch_time_kwarg_is_an_explicit_error():
    """Removed in 0.3.0. **kwargs would otherwise swallow it, and the stimuli it named would
    quietly never load -- the same silent failure the keyword itself caused."""
    from stimpack.visual_stim.stim_server import VisualStimServer

    with pytest.raises(TypeError, match='other_stim_module_paths was removed'):
        VisualStimServer(screens=[], other_stim_module_paths=['/some/path'])
