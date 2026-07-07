"""Unit tests for the GUI's server-message wiring (no live window).

Importing gui.py needs PyQt6 and the full client/render import chain, so these skip where those are
unavailable and run in CI. The cross-thread signal marshalling itself is Qt's job; here we check the
signal is declared and the slot updates the status label.
"""
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("numpy")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

from stimpack.experiment.gui import ExperimentGUI

pytestmark = pytest.mark.unit


def test_server_message_signal_is_declared():
    # Needed so report_server_message (run thread) can marshal onto the GUI thread.
    assert 'server_message_signal' in ExperimentGUI.__dict__


def test_on_server_message_received_updates_status_label():
    # Call the slot with a duck-typed self so we don't need a live QWidget / QApplication.
    class _Label:
        text = None
        def setText(self, t):
            self.text = t

    class _Fake:
        status_label = _Label()

    fake = _Fake()
    ExperimentGUI.on_server_message_received(fake, "error", "boom")
    assert fake.status_label.text == "[server error] boom"
