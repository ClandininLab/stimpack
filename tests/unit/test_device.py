"""Unit tests for the device layer's error reporting (no hardware).

stimpack.device.daq imports only the RPC layer (stdlib), so this runs everywhere.
"""
import pytest

from stimpack.device.daq import DAQ

pytestmark = pytest.mark.unit


def test_daq_reports_handler_error_via_error_reporter():
    # Tier-2 bubbling: a DAQ handler error is forwarded via error_reporter (BaseServer wires this to
    # reach the client).
    class _BoomDAQ(DAQ):
        def boom(self):
            raise ValueError("kaboom")

    d = _BoomDAQ()
    reported = []
    d.error_reporter = lambda level, text: reported.append((level, text))
    with pytest.warns(UserWarning):
        d.handle_request_list([{"name": "boom", "args": [], "kwargs": {}}])

    assert reported and reported[0][0] == "error"
    assert "kaboom" in reported[0][1]


def test_daq_error_isolated_without_reporter():
    class _BoomDAQ(DAQ):
        def boom(self):
            raise ValueError("x")

    d = _BoomDAQ()  # no error_reporter set
    with pytest.warns(UserWarning):
        d.handle_request_list([{"name": "boom", "args": [], "kwargs": {}}])  # must not raise
