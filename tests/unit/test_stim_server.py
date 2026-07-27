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
    started grew the list for as long as it sat there.

    Checked structurally rather than by grepping one method's source: which method does the
    appending is an implementation detail (subframe multiplexing moved it into paint_subframe),
    but every append must sit under `if self.stim_started`.
    """
    import ast
    import inspect
    import textwrap
    from stimpack.visual_stim import framework

    tree = ast.parse(textwrap.dedent(inspect.getsource(framework.StimDisplay)))

    def guards_stim_started(node):
        test = node.test
        return (isinstance(test, ast.Attribute) and test.attr == 'stim_started'
                and getattr(test.value, 'id', None) == 'self')

    def appends_frame_time(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'append'
                and getattr(node.func.value, 'attr', None) == 'profile_frame_times')

    guarded, total = 0, 0
    for node in ast.walk(tree):
        if appends_frame_time(node):
            total += 1
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and guards_stim_started(node):
            guarded += sum(1 for sub in ast.walk(node) if appends_frame_time(sub))

    assert total > 0, 'no frame-time profiling found at all'
    assert guarded == total, (
        f'{total - guarded} of {total} profile_frame_times.append calls are not under '
        f'`if self.stim_started`')


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


# --- advertising which functions a rig has --------------------------------------------------------

def test_a_module_that_dispatches_by_attribute_can_enumerate_itself():
    """DAQ and LocoManager both dispatch with `request['name'] in dir(self)`, so their callable
    surface is exactly their public attributes and the server can advertise it."""
    from stimpack.device.daq import DAQ

    class LabDAQ(DAQ):
        def __init__(self):
            pass
        def open_shutter(self):
            pass
        def _internal(self):
            pass

    names = LabDAQ().get_callable_names()
    assert 'open_shutter' in names          # the lab's own method
    assert 'send_trigger' in names          # inherited from DAQ
    assert '_internal' not in names         # private


def test_every_advertised_screen_function_is_a_real_method():
    """The screen's surface is fixed in stimpack's own source rather than discovered at runtime,
    so it can rot silently. main() registers from this same tuple, so a name that is not a real
    StimDisplay method would fail at screen launch -- in a subprocess, where it is awkward to see.
    Catch it here instead."""
    from stimpack.visual_stim.framework import SCREEN_FUNCTION_NAMES, StimDisplay

    missing = [name for name in SCREEN_FUNCTION_NAMES
               if not callable(getattr(StimDisplay, name, None))]
    assert missing == []
    assert len(set(SCREEN_FUNCTION_NAMES)) == len(SCREEN_FUNCTION_NAMES)   # no duplicates


def test_the_visual_module_advertises_screens_and_its_own_functions():
    """target('visual') reaches either the screens or this server's own root functions, so both
    belong in what it advertises."""
    from stimpack.visual_stim.framework import SCREEN_FUNCTION_NAMES
    from stimpack.visual_stim.stim_server import VisualStimServer

    server = VisualStimServer.__new__(VisualStimServer)
    server.functions_on_root = {'close': None, 'load_shared_pixmap_stim': None}

    names = server.get_callable_names()

    assert 'load_stim' in names                  # handled by a screen
    assert 'close' in names                      # handled here
    assert set(SCREEN_FUNCTION_NAMES).issubset(names)
    assert 'set_dlpc_current' not in names       # a root registration, not a visual one


def test_on_connection_open_advertises_root_and_enumerable_modules():
    from stimpack.experiment.server import BaseServer

    class Enumerable:
        def get_callable_names(self):
            return ['set_value', 'send_trigger']

    sent_over_the_wire = []

    class Opaque:
        '''A module that cannot enumerate itself AND is a transceiver, so every missing attribute
        becomes an RPC stub rather than raising. Asking the INSTANCE whether it can enumerate
        therefore always says yes, and calling that stub sends the question down the wire.'''
        def __getattr__(self, name):
            def stub(*args, **kwargs):
                sent_over_the_wire.append(name)
                return ['nonsense', 'from', 'a', 'stub']
            return stub

    server = BaseServer.__new__(BaseServer)
    server.modules = {'voltage_out': Enumerable(), 'visual': Opaque()}
    server.functions_on_root = {'print_on_server': None, 'set_dlpc_current': None}
    sent = []
    server.write_request_list = sent.append

    server.on_connection_open()

    advertised = {r['name']: r['args'][0] for r in sent[0]}
    assert advertised['report_server_modules'] == ['visual', 'voltage_out']
    functions = advertised['report_server_functions']
    assert functions['root'] == ['print_on_server', 'set_dlpc_current']
    assert functions['voltage_out'] == ['send_trigger', 'set_value']
    assert 'visual' not in functions         # not guessed at
    assert sent_over_the_wire == [], (
        'the server asked a transceiver module whether it can enumerate, which is not a question '
        'but an RPC call: it went down the wire to a screen that has no such function')


def test_a_module_that_raises_while_enumerating_is_skipped_not_fatal():
    from stimpack.experiment.server import BaseServer

    class Broken:
        def get_callable_names(self):
            raise RuntimeError('nope')

    server = BaseServer.__new__(BaseServer)
    server.modules = {'voltage_out': Broken()}
    server.functions_on_root = {}
    sent = []
    server.write_request_list = sent.append

    server.on_connection_open()              # must not raise

    functions = {r['name']: r['args'][0] for r in sent[0]}['report_server_functions']
    assert 'voltage_out' not in functions
