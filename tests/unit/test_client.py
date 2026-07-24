"""Unit tests for BaseClient's server-message handling (no server/hardware).

BaseClient.__init__ connects to a server, so these bypass it (__new__) to test the handler in
isolation. Importing client.py needs PyQt6 (it uses QApplication in the run loop), so these skip
where PyQt6 is unavailable and run in CI.
"""
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
