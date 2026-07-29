"""
End-to-end tests that stand up their own server.

Separate from test_live_run.py deliberately. Those tests share one module-scoped live_server for
the whole file; these need servers of their own, and if they lived in the same module they would
run while that shared one was still alive -- three GL contexts competing under a software
renderer, on a tier whose assertions are all "did this message arrive in time".
"""
import time

import pytest

from helpers import unobtrusive_screen, wait_until

pytestmark = pytest.mark.e2e


# --- custom stimulus modules across client sessions ----------------------------------------------


def test_a_standalone_stim_server_reports_screen_errors_to_its_client():
    """launch_stim_server without a BaseServer -- what the examples and any plain script do.

    The screen bubbles its errors up to the VisualStimServer, which forwarded them via
    error_reporter; that was None here, so they were dropped. A failing stimulus did nothing and
    reported nothing, which is the hardest kind of failure to debug from a script.
    """
    from stimpack.visual_stim.stim_server import launch_stim_server

    try:
        manager = launch_stim_server(unobtrusive_screen())
    except Exception as e:
        pytest.skip(f"Could not launch a stim server here: {type(e).__name__}: {e}")

    reported = []
    manager.register_function(lambda level, text: reported.append((level, text)),
                              name='report_server_message')
    try:
        time.sleep(2)
        manager.load_stim(name='NoSuchStimulus_Standalone')

        def arrived():
            manager.process_queue()
            return bool(reported)

        if not wait_until(arrived, timeout=15):
            # Distinguish "the report did not come back" -- the bug this test exists for -- from
            # "there is no usable GL here", which is the rest of this tier's skip condition. A
            # screen that cannot create a context dies, and the socket to it breaks.
            if getattr(manager, 'connection_broken', False):
                pytest.skip('the screen subprocess died before it could report anything '
                            '(no usable GL on this machine)')
            pytest.fail('a standalone stim server never reported the screen-side error to its client')
        level, text = reported[0]
        assert level == 'error'
        assert 'NoSuchStimulus_Standalone' in text
        assert '[screen]' in text                 # bubbled up from the screen subprocess
    finally:
        try:
            manager.close()
        except Exception:
            pass


def test_a_custom_stim_module_survives_successive_client_sessions(tmp_path):
    """Regression: each client imports its labpack's stimuli when it connects, and the server
    unloads them when it disconnects. Because a loaded stimulus instance keeps its class alive, the
    unload did not actually remove it, so the second session's import produced two classes of the
    same name and load_stim failed with '2 stimulus candidates found'.

    A rig server outlives the GUI, so this was hit by closing and reopening the GUI -- while a
    local server, which dies with the GUI, hid it entirely.

    Uses a BaseServer rather than a bare VisualStimServer: only BaseServer wires the screens'
    error_reporter, and without it a failing load_stim is swallowed and this test would pass
    against the bug it exists to catch.
    """
    from stimpack.experiment.server import BaseServer
    from stimpack.rpc.transceiver import MySocketClient

    module_dir = tmp_path / 'custom_stim'
    module_dir.mkdir()
    (module_dir / 'stimuli.py').write_text(
        'from stimpack.visual_stim.base import BaseProgram\n'
        'from stimpack.visual_stim import shapes\n\n\n'
        'class SessionTestStim(BaseProgram):\n'
        '    def configure(self, color=(1, 1, 1, 1)):\n'
        '        self.color = color\n\n'
        '    def eval_at(self, t, subject_position=None):\n'
        '        self.stim_object = shapes.GlSphericalRect(width=10, height=10, color=self.color)\n')

    screen = unobtrusive_screen(display_index=0,
                                pa=(-0.15, 0.15, -0.15), pb=(0.15, 0.15, -0.15), pc=(-0.15, 0.15, 0.15))
    try:
        server = BaseServer(host='127.0.0.1', port=None,
                            visual_stim_kwargs={'screens': [screen]}, start_loop=True)
    except Exception as e:
        pytest.skip(f"Could not launch a live stim server here: {type(e).__name__}: {e}")

    reported = []
    try:
        for session in (1, 2):
            manager = MySocketClient(host=server.host, port=server.port)
            manager.register_function(
                lambda level, text, s=session: reported.append((s, level, text)),
                name='report_server_message')
            time.sleep(0.5)

            manager.target('visual').import_stim_module(str(module_dir))   # BaseClient does this
            time.sleep(1.5)
            manager.target('visual').load_stim(name='SessionTestStim')

            def settled():
                manager.process_queue()
                return bool(reported)
            wait_until(settled, timeout=5)      # give an error time to arrive, if there is one

            manager.close()
            time.sleep(1.5)
    finally:
        try:
            server.close()
        except Exception:
            pass

    errors = [r for r in reported if r[1] == 'error']
    assert errors == [], f'the server reported an error: {errors}'
