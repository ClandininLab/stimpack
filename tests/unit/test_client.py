"""Unit tests for BaseClient's server-message handling (no server/hardware).

BaseClient.__init__ connects to a server, so these bypass it (__new__) to test the handler in
isolation. Importing client.py needs PyQt6 (it uses QApplication in the run loop), so these skip
where PyQt6 is unavailable and run in CI.
"""
import subprocess

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("numpy")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

from stimpack.experiment.client import BaseClient

pytestmark = pytest.mark.unit


def _bare_client():
    c = BaseClient.__new__(BaseClient)
    c.server_messages = []
    c.server_error = None
    c.on_server_message = None
    c._message_counts = {}
    return c


def test_report_server_message_records_and_flags_error():
    c = _bare_client()
    c.report_server_message("warning", "heads up")
    assert c.server_error is None
    assert ("warning", "heads up") in c.server_messages

    c.report_server_message("error", "boom")
    assert c.server_error == "boom"           # an error marks the run for abort
    assert ("error", "boom") in c.server_messages


def test_on_server_message_callback_is_invoked():
    c = _bare_client()
    seen = []
    c.on_server_message = lambda level, text: seen.append((level, text))
    c.report_server_message("info", "hello")
    assert seen == [("info", "hello")]


def test_on_server_message_callback_failure_is_isolated():
    c = _bare_client()
    c.on_server_message = lambda level, text: 1 / 0  # a broken GUI hook must not break reporting
    c.report_server_message("error", "boom")  # must not raise
    assert c.server_error == "boom"


# --- close() ------------------------------------------------------------------------------------
#
# The two local-server paths each spawn OS subprocesses of their own (one per screen, plus KeyTrac,
# which is detached via start_new_session and so outlives our process group). close() is the only
# thing that reaps them, and it is called from the GUI's closeEvent.

class _FakeServer:
    def __init__(self, raises=False):
        self.closed = False
        self.raises = raises

    def close(self):
        self.closed = True
        if self.raises:
            raise RuntimeError("module failed to close")


class _FakeProcess:
    def __init__(self, hangs=False):
        self.terminated = False
        self.killed = False
        self.hangs = hangs

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if self.hangs:
            raise subprocess.TimeoutExpired(cmd="server", timeout=timeout)

    def kill(self):
        self.killed = True


def test_close_shuts_down_the_in_process_server():
    """The default local server lives in this process; nothing else will ever close it."""
    c = _bare_client()
    c.local_server = _FakeServer()
    c.close()
    assert c.local_server.closed


def test_close_survives_a_server_that_fails_to_close():
    """A failure while closing must not stop the GUI from closing."""
    c = _bare_client()
    c.local_server = _FakeServer(raises=True)
    with pytest.warns(UserWarning):
        c.close()                              # must not raise


def test_close_terminates_a_launched_server_process():
    c = _bare_client()
    c.local_server_process = _FakeProcess()
    c.close()
    assert c.local_server_process.terminated
    assert not c.local_server_process.killed


def test_close_kills_a_launched_server_process_that_will_not_exit():
    """Bounded wait: a server that ignores terminate must not hang GUI shutdown forever."""
    c = _bare_client()
    c.local_server_process = _FakeProcess(hangs=True)
    with pytest.warns(UserWarning):
        c.close()
    assert c.local_server_process.killed


def test_close_is_a_no_op_when_no_local_server_was_started():
    """Connecting to a remote rig server: there is nothing of ours to shut down."""
    _bare_client().close()                     # must not raise
