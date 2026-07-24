"""Integration tests for the locomotion / closed-loop engine.

Drives a real KeytracClosedLoopManager over a real UDP socket using synthetic datagrams in KeyTrac's
actual wire format, so positions are deterministic. No KeyTrac subprocess (see tests/e2e for that)
and no rig. Covers parsing, the pos_0 offset, per-axis gating, and the closed-loop thread.
"""
import socket
import time

import numpy as np
import pytest

pytestmark = pytest.mark.integration


class RecordingStimServer:
    """Stands in for BaseServer: records the subject-state updates the loco manager pushes."""

    def __init__(self):
        self.states = []

    def set_subject_state(self, state_update):
        self.states.append(dict(state_update))


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def kt_line(key_count=1, x=0.0, y=0.0, z=0.0, theta=0.0, phi=0.0, roll=0.0, ts=None):
    """One KeyTrac state message. Angles are RADIANS on the wire (the manager converts to degrees)."""
    ts = time.time() if ts is None else ts
    return f"KT, {key_count}, No key pressed, {x}, {y}, {z}, {theta}, {phi}, {roll}, {ts}\n"


@pytest.fixture
def loco():
    """A real KeytracClosedLoopManager with its socket bound, but no KeyTrac subprocess launched."""
    from stimpack.device.locomotion.loco_managers.keytrac_managers import KeytracClosedLoopManager

    server = RecordingStimServer()
    port = free_udp_port()
    manager = KeytracClosedLoopManager(stim_server=server, host='127.0.0.1', port=port,
                                       start_at_init=False)
    manager.socket_manager.connect()          # bind the UDP socket without spawning KeyTrac

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(**kwargs):
        sender.sendto(kt_line(**kwargs).encode(), ('127.0.0.1', port))

    manager._test_send = send
    manager._test_sender = sender
    manager._test_server = server
    yield manager

    try:
        if manager.is_looping():
            manager.loop_stop()
        manager.socket_manager.close()
    except Exception:
        pass
    sender.close()


# --- parsing ------------------------------------------------------------------------------------

def test_parse_line_maps_fields_and_converts_angles(loco):
    data = loco._parse_line(kt_line(key_count=7, x=1.5, y=-2.0, z=0.25,
                                    theta=np.pi, phi=np.pi / 2, roll=0.0, ts=123.5))
    assert data['x'] == 1.5 and data['y'] == -2.0 and data['z'] == 0.25
    assert data['theta'] == pytest.approx(180.0)     # radians on the wire -> degrees
    assert data['phi'] == pytest.approx(90.0)
    assert data['frame_num'] == 7
    assert data['ts'] == 123.5


def test_parse_line_rejects_a_non_keytrac_line(loco):
    assert loco._parse_line("FT, 1, 2, 3\n") == {}   # wrong prefix -> empty, not a crash


def test_get_data_reads_a_real_datagram(loco):
    loco._test_send(key_count=3, x=0.4, y=0.8, theta=0.0)
    data = loco.get_data(wait_for=5)
    assert data['x'] == pytest.approx(0.4)
    assert data['y'] == pytest.approx(0.8)
    assert data['frame_num'] == 3


# --- offsets ------------------------------------------------------------------------------------

def test_keytrac_set_pos_0_commands_keytrac_to_reset(loco):
    """KeyTrac can zero itself, so its set_pos_0 sends 'reset_pos' and zeroes both sides
    (unlike the generic offset-capture path below, used by trackers that can't be reset)."""
    loco._test_send(x=5.0, y=5.0)
    loco.get_data(wait_for=5)                        # gives the socket a client address to reply to

    loco.set_pos_0(use_data_prev=True)

    loco._test_sender.settimeout(5)
    assert loco._test_sender.recv(1024).decode() == 'reset_pos'   # KeyTrac was told to reset
    assert loco.pos_0['x'] == pytest.approx(0.0)     # ...so stimpack's offset is zero too
    assert loco.pos['x'] == pytest.approx(0.0)


def test_generic_offset_capture_makes_positions_relative(loco):
    """The base mapping (loco value = None -> read it from the socket) captures the current reading
    as the origin, so later positions are reported relative to it."""
    loco._test_send(x=5.0, y=5.0)
    loco.get_data(wait_for=5)

    # the generic path protocols use for trackers that cannot self-zero
    loco.map_loco_to_server_pos(loco_state_pos_pairs={'x': (None, 0), 'y': (None, 0)},
                                use_data_prev=True)

    assert loco.pos_0['x'] == pytest.approx(5.0)     # offset captured from the live reading
    assert loco.pos['x'] == pytest.approx(0.0)       # server-side position starts at zero

    # a later reading is reported relative to that origin
    loco._test_send(x=7.0, y=5.0)
    loco.update_pos()
    assert loco.pos['x'] == pytest.approx(2.0)
    assert loco.pos['y'] == pytest.approx(0.0)


def test_update_pos_ignores_a_missing_reading(loco):
    """A timed-out read must leave the position alone.

    Regression: the data.get(..., 0) defaults used to fabricate a position of -pos_0 and push it,
    which would teleport the subject mid-experiment if the tracker hiccuped.
    """
    loco._test_send(x=4.0, y=1.0)
    loco.update_pos(wait_for=5)
    before = dict(loco.pos)
    pushes_before = len(loco._test_server.states)

    loco.update_pos(wait_for=0.1)                    # no datagram waiting

    assert loco.pos == before                        # unchanged, not -pos_0
    assert len(loco._test_server.states) == pushes_before   # nothing forwarded


def test_update_pos_pushes_only_the_enabled_axes(loco):
    loco._test_send(x=1.0, y=2.0, z=3.0, theta=np.pi)
    loco.update_pos(update_x=True, update_y=False, update_z=False,
                    update_theta=True, update_phi=False, update_roll=False)

    pushed = loco._test_server.states[-1]
    assert set(pushed.keys()) == {'x', 'theta'}      # y/z/phi/roll were not forwarded
    assert pushed['x'] == pytest.approx(1.0)
    assert pushed['theta'] == pytest.approx(180.0)


# --- the closed-loop thread -----------------------------------------------------------------------

def test_closed_loop_forwards_position_only_when_enabled(loco):
    server = loco._test_server
    loco.loop_update_closed_loop_vars(update_x=True, update_y=True, update_theta=True)
    loco.loop_start()
    assert loco.is_looping()

    # open loop: the socket is drained but nothing is forwarded to the stimulus server
    for _ in range(5):
        loco._test_send(x=1.0, y=1.0)
        time.sleep(0.02)
    time.sleep(0.2)
    open_loop_updates = [s for s in server.states if s]
    assert all(len(s) == 0 for s in open_loop_updates) or open_loop_updates == []

    # closed loop: positions now reach the stimulus server
    loco.loop_start_closed_loop()
    for _ in range(5):
        loco._test_send(x=2.0, y=3.0)
        time.sleep(0.02)

    deadline = time.time() + 5
    while time.time() < deadline and not any(s.get('x') == pytest.approx(2.0) for s in server.states):
        loco._test_send(x=2.0, y=3.0)
        time.sleep(0.05)

    assert any(s.get('x') == pytest.approx(2.0) and s.get('y') == pytest.approx(3.0)
               for s in server.states), "closed-loop position never reached the stimulus server"

    loco.loop_stop()
    assert not loco.is_looping()


def test_loop_start_is_idempotent(loco):
    loco.loop_start()
    loco.loop_start()                                 # must not start a second reader on one socket
    assert loco.is_looping()
    loco.loop_stop()
    assert not loco.is_looping()
