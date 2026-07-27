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


# --- how a missing root function is reported ------------------------------------------------------

def _base_server_stub():
    """A BaseServer with just enough state to route requests, and no sockets."""
    from stimpack.experiment.server import BaseServer

    server = BaseServer.__new__(BaseServer)
    server.modules = {}
    server.functions_on_root = {'print_on_server': lambda x: None}
    server._warned_module_aliases = set()
    server.reported = []
    server.report_to_client = lambda level, text: server.reported.append((level, text))
    return server


def test_an_untargeted_call_that_lands_nowhere_is_an_error():
    """Untargeted calls default to root. One that finds nothing there was meant for something and
    reached nothing -- how mis-migrated daq_* calls silently stopped firing."""
    server = _base_server_stub()

    with pytest.warns(UserWarning):
        server.handle_request_list([{'name': 'daq_output_step', 'args': [], 'kwargs': {}}])

    assert server.reported and server.reported[0][0] == 'error'
    assert 'daq_output_step' in server.reported[0][1]
    assert "target('all')" in server.reported[0][1]      # says what to do instead


def test_an_explicit_root_call_this_rig_lacks_is_only_a_warning():
    """Labs register rig-specific functions on root -- a projector's LED current, a shutter. A
    protocol written for one rig must degrade on another rather than refuse to run, exactly as a
    request for a module this server lacks does."""
    server = _base_server_stub()

    with pytest.warns(UserWarning):
        server.handle_request_list([{'name': 'set_dlpc_current', 'target': 'root',
                                     'args': [10, 10, 10], 'kwargs': {}}])

    assert server.reported and server.reported[0][0] == 'warning'
    assert 'set_dlpc_current' in server.reported[0][1]
    assert 'print_on_server' in server.reported[0][1]    # lists what IS registered


def test_a_missing_module_and_a_missing_root_function_agree_on_severity():
    """Both mean 'this rig does not have that capability', so both are warnings; only a call that
    landed nowhere by accident is an error."""
    server = _base_server_stub()

    with pytest.warns(UserWarning):
        server.handle_request_list([{'name': 'output_step', 'target': 'voltage_out',
                                     'args': [], 'kwargs': {}}])
    missing_module = [level for level, _ in server.reported]

    server.reported.clear()
    with pytest.warns(UserWarning):
        server.handle_request_list([{'name': 'set_dlpc_current', 'target': 'root',
                                     'args': [], 'kwargs': {}}])
    missing_function = [level for level, _ in server.reported]

    assert missing_module == missing_function == ['warning']


def test_a_registered_root_function_still_runs():
    server = _base_server_stub()
    called = []
    server.functions_on_root['set_dlpc_current'] = lambda *a: called.append(a)

    server.handle_request_list([{'name': 'set_dlpc_current', 'target': 'root',
                                 'args': [10, 20, 30], 'kwargs': {}}])

    assert called == [(10, 20, 30)]
    assert server.reported == []
