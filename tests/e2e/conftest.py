"""Fixtures for end-to-end tests: a LIVE server with real screen subprocesses.

Unlike the integration tier (which fakes the socket), these launch the real thing:
  BaseServer (real RPC socket) -> VisualStimServer -> one screen subprocess per Screen,
each running Qt + moderngl with a real GL context. Nothing is mocked; commands travel over a real
socket and stimuli are really rendered.

Requires a working headless GL stack (software Mesa is fine); tests skip if one isn't available.
"""
import pytest

from helpers import wait_until

pytest.importorskip("numpy")
pytest.importorskip("h5py")
pytest.importorskip("moderngl")
pytest.importorskip("PyQt6")

SERVER_BOOT_TIMEOUT = 60



@pytest.fixture(scope="module")
def live_server():
    """A real BaseServer whose 'visual' module has launched a real screen subprocess."""
    from stimpack.experiment.server import BaseServer
    from stimpack.visual_stim.screen import Screen

    screen = Screen(fullscreen=False, vsync=False, display_index=0,
                    pa=(-0.15, 0.15, -0.15), pb=(0.15, 0.15, -0.15), pc=(-0.15, 0.15, 0.15))
    try:
        server = BaseServer(host='127.0.0.1', port=None,
                            visual_stim_kwargs={'screens': [screen]},
                            start_loop=True)
    except Exception as e:                       # no GL / no display / subprocess failed to boot
        pytest.skip(f"Could not launch a live stim server here: {type(e).__name__}: {e}")

    yield server

    try:
        server.close()
    except Exception:
        pass


@pytest.fixture(scope="module")
def live_manager(live_server):
    """A real MySocketClient connected to the live server over a real socket.

    Module-scoped on purpose: MySocketServer serves ONE connection at a time, so a fresh client per
    test would queue in the backlog behind the previous (never-closed) one and never be served.
    """
    from stimpack.rpc.transceiver import MySocketClient

    manager = MySocketClient(host=live_server.host, port=live_server.port)
    yield manager

    # Close it, rather than leaving a live reader thread bound to this process's QApplication. A
    # later tier that pumps the Qt event loop would otherwise dispatch this manager's queued events
    # into torn-down receivers and segfault (see tests/conftest.py).
    manager.close()


@pytest.fixture(scope="module")
def live_client(live_manager):
    """A real BaseClient driving the live server (bypassing the config-driven __init__)."""
    from PyQt6.QtWidgets import QApplication
    from stimpack.experiment.client import BaseClient

    QApplication.instance() or QApplication([])   # start_run pumps processEvents()

    # Mirror what BaseClient.__init__ sets up (it is bypassed here because it would build its own
    # server from a config).
    c = BaseClient.__new__(BaseClient)
    c.cfg = {}
    c.stop = False
    c.pause = False
    c.server_messages = []
    c.server_error = None
    c.on_server_message = None
    c._message_counts = {}
    c.manager = live_manager
    c.trigger_device = None
    c.server_options = {}
    # BaseClient.__init__ normally registers this so the server can push messages back
    live_manager.register_function(c.report_server_message, name='report_server_message')

    # Readiness gate: wait until the screen subprocess's render loop is actually dispatching
    # requests. paintGL is what drains the RPC queue, so until the first frame runs, requests just
    # sit there -- and a timing-sensitive test would race a slow screen boot. Deliberately ask for a
    # nonexistent stimulus: the error coming back proves the whole chain is live.
    live_manager.target('visual').load_stim(name='__readiness_probe__')

    def chain_is_live():
        live_manager.process_queue()
        return c.server_error is not None

    if not wait_until(chain_is_live, timeout=30):
        pytest.skip('the live screen subprocess never started dispatching requests')

    c.server_error = None                 # the probe's error is expected; don't leak it into tests
    c.server_messages = []
    c._message_counts = {}
    return c


@pytest.fixture(autouse=True)
def _reset_live_state(request):
    """Clear per-run state on the shared client/manager before each test.

    Note: attributes are set explicitly rather than probed with getattr/hasattr — MySocketClient's
    __getattr__ turns ANY missing attribute into an RPC stub, so those probes never fall back.
    """
    if 'live_client' in request.fixturenames:
        client = request.getfixturevalue('live_client')
        client.stop = False
        client.pause = False
        client.server_error = None
        client.server_messages = []
        client._message_counts = {}
    if 'live_manager' in request.fixturenames:
        manager = request.getfixturevalue('live_manager')
        manager.connection_broken = False
        manager.process_queue()          # drop anything left over from a previous test
    yield


@pytest.fixture
def live_data(tmp_path):
    from stimpack.experiment.data import BaseData

    d = BaseData(cfg={})
    d.data_directory = str(tmp_path)
    d.experiment_file_name = "e2e_test"
    d.initialize_experiment_file()
    d.create_subject({"subject_id": "subj_e2e"})
    return d
