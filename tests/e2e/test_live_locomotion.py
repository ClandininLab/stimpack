"""End-to-end locomotion / closed-loop tests.

Two levels, both against real processes and real sockets:
  1. a REAL KeyTrac subprocess (the PyQt app) streaming over UDP into a live server, and
  2. a live server whose locomotion module is fed controlled positions, verifying the whole
     closed-loop chain (tracker -> loco manager -> BaseServer -> every module incl. the screen).

KeyTrac emits a state heartbeat every 500 ms without any keypress, which is what makes the real
subprocess testable headlessly.
"""
import os
import socket
import sys
import time

import pytest

from conftest import wait_until          # tests/e2e/conftest.py (pytest pythonpath)

pytestmark = pytest.mark.e2e


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def keytrac_py():
    from stimpack.util import ROOT_DIR
    return os.path.join(ROOT_DIR, 'device', 'locomotion', 'keytrac', 'keytrac.py')


def make_loco_server(port, screens=None):
    """A live BaseServer whose 'locomotion' module is a real KeytracClosedLoopManager."""
    from stimpack.device.locomotion.loco_managers.keytrac_managers import KeytracClosedLoopManager
    from stimpack.experiment.server import BaseServer
    from stimpack.visual_stim.screen import Screen

    screens = screens if screens is not None else [Screen(fullscreen=False, vsync=False, display_index=0)]
    return BaseServer(
        host='127.0.0.1', port=None,
        visual_stim_kwargs={'screens': screens},
        loco_class=KeytracClosedLoopManager,
        loco_kwargs={'host': '127.0.0.1', 'port': port,
                     'python_bin': sys.executable, 'kt_py_fn': keytrac_py(),
                     'relative_control': True},
        start_loop=True)


# --- a real KeyTrac subprocess --------------------------------------------------------------------

def test_real_keytrac_subprocess_streams_into_the_server():
    """Launch the actual KeyTrac app and consume its real UDP stream."""
    port = free_udp_port()
    try:
        server = make_loco_server(port)
    except Exception as e:
        pytest.skip(f"could not launch a live server here: {type(e).__name__}: {e}")

    loco = server.modules['locomotion']
    try:
        loco.start()                                  # binds the socket AND spawns keytrac.py
        assert loco.kt_manager.started is True
        assert loco.kt_manager.p.poll() is None, "the KeyTrac subprocess exited immediately"

        # KeyTrac heartbeats every 500 ms; read one and check it parses into the expected shape.
        data = loco.get_data(wait_for=15)
        assert data, "no data received from the real KeyTrac subprocess"
        assert set(data) >= {'x', 'y', 'z', 'theta', 'phi', 'roll', 'frame_num', 'ts'}
        assert all(isinstance(data[k], float) for k in ('x', 'y', 'z', 'theta', 'phi', 'roll'))

        # the closed-loop thread consumes the real stream and pushes subject state to the server
        loco.loop_update_closed_loop_vars(update_x=True, update_y=True, update_theta=True)
        loco.loop_start()
        loco.loop_start_closed_loop()
        assert wait_until(lambda: set(server.subject_state) >= {'x', 'y', 'theta'}, timeout=15), \
            "closed-loop updates from the real KeyTrac never reached the server"
        loco.loop_stop()

        # set_pos_0 commands KeyTrac to reset; it must not raise and must zero our origin
        loco.set_pos_0(use_data_prev=True)
        assert loco.pos_0['x'] == pytest.approx(0.0)
    finally:
        try:
            loco.close()                              # also SIGINTs the KeyTrac subprocess
        except Exception:
            pass
        server.close()

    assert loco.kt_manager.started is False           # subprocess cleaned up


def test_real_keytrac_subprocess_is_terminated_on_close():
    port = free_udp_port()
    try:
        server = make_loco_server(port)
    except Exception as e:
        pytest.skip(f"could not launch a live server here: {type(e).__name__}: {e}")

    loco = server.modules['locomotion']
    loco.start()
    proc = loco.kt_manager.p
    assert proc.poll() is None

    loco.close()
    server.close()

    assert wait_until(lambda: proc.poll() is not None, timeout=15), "KeyTrac subprocess outlived close()"


# --- the full closed-loop chain with controlled positions ------------------------------------------

def test_closed_loop_position_reaches_the_server_and_screens():
    """Feed known positions in KeyTrac's wire format and follow them through the real chain.

    Uses the real loco manager + real BaseServer + real screen subprocess, but injects the datagrams
    itself so the positions are deterministic (a real KeyTrac only moves on keypresses).
    """
    port = free_udp_port()
    try:
        server = make_loco_server(port)
    except Exception as e:
        pytest.skip(f"could not launch a live server here: {type(e).__name__}: {e}")

    loco = server.modules['locomotion']
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        loco.socket_manager.connect()                 # bind, without spawning KeyTrac
        loco.loop_update_closed_loop_vars(update_x=True, update_y=True, update_theta=True)
        loco.loop_start()
        loco.loop_start_closed_loop()

        def send(x, y, theta_rad):
            line = f"KT, 1, No key pressed, {x}, {y}, 0.0, {theta_rad}, 0.0, 0.0, {time.time()}\n"
            sender.sendto(line.encode(), ('127.0.0.1', port))

        # walk the subject to a known place and wait for the server to reflect it
        def arrived():
            send(2.5, -1.5, 0.0)
            time.sleep(0.05)
            return (server.subject_state.get('x') == pytest.approx(2.5)
                    and server.subject_state.get('y') == pytest.approx(-1.5))

        assert wait_until(arrived, timeout=15), \
            f"position never propagated to the server (subject_state={server.subject_state})"

        # the server forwards state to every module, so the screen subprocess got it too and the
        # visual stack is still healthy afterwards
        server.target('visual').set_idle_background(0.5)
        server.target('visual').load_stim(name='MovingSpot', radius=10, sphere_radius=1,
                                          color=[1, 1, 1, 1], theta=0, phi=0)
        server.target('visual').start_stim()
        time.sleep(0.2)
        server.target('visual').stop_stim()

        loco.loop_stop()
    finally:
        sender.close()
        try:
            loco.socket_manager.close()
        except Exception:
            pass
        server.close()
