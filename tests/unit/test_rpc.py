"""Unit tests for stimpack.rpc — the JSON-over-socket RPC layer.

Pure standard library: no numpy, PyQt, GL, sockets, or hardware. Several of these also serve as
regression tests for recent fixes (exception isolation, disconnect detection, multicall clearing).
"""
import time

import pytest

import socket

from stimpack.rpc.util import JSONCoderWithTuple, get_from_dict
from stimpack.rpc.transceiver import MyTransceiver, MySocketServer, MySocketClient, _disable_nagle
from stimpack.rpc.multicall import MyMultiCall


def _wait_until(predicate, timeout=5.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False

pytestmark = pytest.mark.unit


class FakeOutfile:
    """Minimal binary-mode stream that records writes (and can simulate a disconnect)."""
    def __init__(self, mode="wb", raise_exc=None):
        self.mode = mode
        self.raise_exc = raise_exc
        self.written = []

    def write(self, data):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.written.append(data)

    def flush(self):
        pass


class RecordingTransceiver:
    """Captures the request lists passed to write_request_list."""
    def __init__(self):
        self.sent = []

    def write_request_list(self, request_list):
        self.sent.append(list(request_list))


# --- wire codec ------------------------------------------------------------

def test_codec_preserves_tuples_and_lists():
    obj = {"a": (1, 2), "b": [(3, 4), 5], "c": [1, 2]}
    out = JSONCoderWithTuple.decode(JSONCoderWithTuple.encode(obj))
    assert out["a"] == (1, 2) and isinstance(out["a"], tuple)
    assert out["b"][0] == (3, 4) and isinstance(out["b"][0], tuple)
    assert out["c"] == [1, 2] and isinstance(out["c"], list)  # plain lists stay lists


def test_get_from_dict_single_multi_and_remove():
    d = {"a": 1, "b": 2}
    assert get_from_dict(d, "a") == 1
    assert get_from_dict(d, ["a", "b"]) == [1, 2]
    assert get_from_dict(d, "missing", default=9) == 9
    get_from_dict(d, "a", remove=True)
    assert "a" not in d


# --- MyTransceiver dispatch ------------------------------------------------

def test_dispatch_calls_registered_function():
    t = MyTransceiver()
    calls = []
    t.register_function(lambda *a, **k: calls.append((a, k)), name="rec")
    t.handle_request_list([{"name": "rec", "args": [1], "kwargs": {"x": 2}}])
    assert calls == [((1,), {"x": 2})]


def test_dispatch_isolates_handler_exceptions():
    # Regression (#1): a raising handler must not stop later requests in the same list.
    t = MyTransceiver()
    ran = []
    t.register_function(lambda: (_ for _ in ()).throw(ValueError("boom")), name="boom")
    t.register_function(lambda: ran.append(True), name="ok")
    t.handle_request_list([{"name": "boom"}, {"name": "ok"}])  # must not raise
    assert ran == [True]


def test_unknown_function_warns_without_raising():
    t = MyTransceiver()
    with pytest.warns(UserWarning):
        t.handle_request_list([{"name": "does_not_exist"}])


def test_error_reporter_called_on_handler_exception():
    # Tier-2 bubbling: a handler error is forwarded via error_reporter (used to reach the client).
    t = MyTransceiver()
    reported = []
    t.error_reporter = lambda level, text: reported.append((level, text))
    t.register_function(lambda: (_ for _ in ()).throw(ValueError("kaboom")), name="boom")
    with pytest.warns(UserWarning):
        t.handle_request_list([{"name": "boom"}])
    assert reported and reported[0][0] == "error"
    assert "kaboom" in reported[0][1]


def test_unknown_function_is_reported_to_the_caller():
    # The silent-no-op failure mode: the attribute access succeeds, the request is sent, and it lands
    # nowhere. An explicitly-targeted unknown name must be reported back.
    t = MyTransceiver()
    reported = []
    t.error_reporter = lambda level, text: reported.append((level, text))
    with pytest.warns(UserWarning):
        t.handle_request_list([{"name": "daq_setup_pulse_wave_stream_out", "target": "daq"}])
    assert reported and "no such function" in reported[0][1]
    assert "daq_setup_pulse_wave_stream_out" in reported[0][1]


def test_broadcast_to_a_module_without_the_method_is_not_reported():
    # target('all') is a broadcast: each module takes only the calls it knows (start_stim is for the
    # screens; daq/locomotion ignoring it is normal). Reporting these would fire on every run.
    t = MyTransceiver()
    reported = []
    t.error_reporter = lambda level, text: reported.append((level, text))
    t.handle_request_list([{"name": "start_stim", "target": "all"}])
    assert reported == []


@pytest.mark.parametrize("name", ["_private", "__deepcopy__", "__getstate__", "_repr_html_"])
def test_private_attributes_raise_instead_of_becoming_rpc_calls(name):
    # Without this guard, copy/pickle/IPython introspection silently becomes network traffic, and
    # getattr(manager, 'x', default) returns an RPC stub instead of falling back to the default.
    from stimpack.rpc.transceiver import reject_private_attribute
    with pytest.raises(AttributeError):
        reject_private_attribute(name)


def test_getattr_default_now_falls_back(monkeypatch):
    # Regression for the trap that bit the e2e fixtures: getattr(obj, 'missing', default).
    rt = RecordingTransceiver()
    mc = MyMultiCall(rt)
    assert getattr(mc, '_not_a_remote_call', 'fallback') == 'fallback'
    # ...while ordinary remote calls still work
    mc.load_stim(name='X')
    mc()
    assert rt.sent[0][0]['name'] == 'load_stim'


def test_error_reporter_default_none_does_not_crash():
    t = MyTransceiver()
    assert t.error_reporter is None
    t.register_function(lambda: (_ for _ in ()).throw(ValueError("x")), name="boom")
    with pytest.warns(UserWarning):
        t.handle_request_list([{"name": "boom"}])  # must not raise with no reporter set


def test_launch_server_detects_dead_child(tmp_path):
    # Regression (#15): a server script that exits immediately must raise promptly with its exit code,
    # not burn the full poll timeout and report a generic failure.
    from stimpack.rpc.launch import launch_server

    script = tmp_path / "dies_immediately.py"
    script.write_text("import sys; sys.exit(3)\n")

    t0 = time.monotonic()
    with pytest.raises(RuntimeError) as exc:
        launch_server(str(script), server_poll_timeout=10, server_poll_interval=0.05)
    elapsed = time.monotonic() - t0

    assert "code 3" in str(exc.value)
    assert elapsed < 5  # detected promptly, well before the 10s timeout


# --- MyTransceiver outbound ------------------------------------------------

def test_write_request_list_round_trips_on_the_wire():
    t = MyTransceiver()
    t.outfile = FakeOutfile()
    req = [{"name": "foo", "args": [1], "kwargs": {}}]
    t.write_request_list(req)
    line = t.outfile.written[0].decode("utf-8")
    assert JSONCoderWithTuple.decode(line) == req


def test_write_sets_connection_broken_on_disconnect():
    # Regression (#2): a peer reset must set the flag + warn, not raise or silently no-op.
    t = MyTransceiver()
    assert t.connection_broken is False
    t.outfile = FakeOutfile(raise_exc=ConnectionResetError())
    with pytest.warns(UserWarning):
        t.write_request_list([{"name": "foo", "args": [], "kwargs": {}}])
    assert t.connection_broken is True


# --- MyMultiCall -----------------------------------------------------------

def test_multicall_batches_and_targets():
    rt = RecordingTransceiver()
    mc = MyMultiCall(rt)
    mc.foo(1, x=2)
    mc.target("visual").bar()
    mc()
    assert rt.sent == [[
        {"name": "foo", "args": (1,), "kwargs": {"x": 2}},
        {"target": "visual", "name": "bar", "args": (), "kwargs": {}},
    ]]


def test_multicall_clears_after_flush():
    # Regression (#28): re-invoking must not re-send the previous batch.
    rt = RecordingTransceiver()
    mc = MyMultiCall(rt)
    mc.foo()
    mc()
    mc()
    assert rt.sent[0] == [{"name": "foo", "args": (), "kwargs": {}}]
    assert rt.sent[1] == []


# --- reverse channel: server -> client push (server error reporting) -----------------------------

def test_disable_nagle_sets_tcp_nodelay():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 0  # default: Nagle on
        _disable_nagle(s)
        assert s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 1  # now off
    finally:
        s.close()


def test_disable_nagle_is_best_effort_on_bad_socket():
    # A socket that doesn't support TCP_NODELAY (e.g. UDP) must not raise.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _disable_nagle(s)  # must not raise
    finally:
        s.close()


def test_client_flags_connection_broken_when_reader_sees_disconnect():
    # Regression (#2, read side): the reader thread must flag connection_broken when the server drops,
    # even if the client isn't sending — so a dead server is detected during a quiet stretch.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    client = MySocketClient(host="127.0.0.1", port=port)  # kernel accepts into the backlog
    assert client.connection_broken is False

    conn, _ = srv.accept()
    conn.close()  # drop the connection -> the client's reader hits EOF
    srv.close()

    assert _wait_until(lambda: client.connection_broken is True), "reader thread did not flag the disconnect"


def test_server_can_push_message_to_client_over_socket():
    # A server pushes a request back to the connected client; the client's reader thread queues it and
    # process_queue() executes it. This is the channel BaseServer.report_to_client uses to surface
    # server-side errors in the client/GUI.
    server = MySocketServer(host="127.0.0.1", port=0, threaded=True, auto_stop=False)
    port = server.listener.getsockname()[1]
    client = MySocketClient(host="127.0.0.1", port=port)

    received = []
    client.register_function(lambda level, text: received.append((level, text)),
                             name="report_server_message")

    # The server sets its outfile when it accepts the client connection.
    assert _wait_until(lambda: server.outfile is not None), "server never accepted the client"

    server.write_request_list([{"name": "report_server_message", "args": ["error", "boom"], "kwargs": {}}])

    assert _wait_until(lambda: not client.queue.empty()), "client never received the pushed message"
    client.process_queue()
    assert received == [("error", "boom")]

    server.shutdown_flag.set()


# --- MySocketClient.close() ---------------------------------------------------------------------
#
# Without a real close(), the reader thread is unstoppable: it parks in `for line in self.infile`
# and only exits if the peer happens to drop the connection. That left live threads bound to the
# process's QApplication across test tiers, and left the GUI unable to shut a client down.

def _client_server_pair():
    """A MySocketClient connected to a throwaway listening socket."""
    import socket as _socket
    from stimpack.rpc.transceiver import MySocketClient

    listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]

    client = MySocketClient(host='127.0.0.1', port=port)
    conn, _ = listener.accept()
    return client, conn, listener


def test_close_stops_the_reader_thread():
    client, conn, listener = _client_server_pair()
    thread = client._reader_thread
    assert thread.is_alive()

    client.close()

    assert not thread.is_alive(), "close() must unblock and join the reader thread"
    conn.close()
    listener.close()


def test_close_is_idempotent():
    client, conn, listener = _client_server_pair()
    client.close()
    client.close()                     # must not raise
    conn.close()
    listener.close()


def test_sending_after_close_is_a_silent_no_op():
    """write_request_list treats a dropped link as None; a closed file would raise ValueError."""
    client, conn, listener = _client_server_pair()
    client.close()

    client.some_remote_call(1, 2)      # must not raise

    conn.close()
    listener.close()


# --- an undecodable line is reported, not dropped (#27) ------------------------------------------

def test_an_undecodable_line_is_reported():
    """A line only fails to decode if something is wrong -- a truncated write, two writers
    interleaving, a non-stimpack client. Dropping it silently is the same invisible failure as an
    unknown function name: the caller's request just never happens."""
    from stimpack.rpc.transceiver import _warn_undecodable_line
    from json.decoder import JSONDecodeError

    with pytest.warns(UserWarning, match='could not be decoded'):
        _warn_undecodable_line(b'{"name": "load_stim"', JSONDecodeError('x', '{', 0))


def test_a_huge_undecodable_line_is_truncated_in_the_warning():
    from stimpack.rpc.transceiver import _warn_undecodable_line
    from json.decoder import JSONDecodeError

    with pytest.warns(UserWarning) as record:
        _warn_undecodable_line('x' * 5000, JSONDecodeError('x', '{', 0))

    assert len(str(record[0].message)) < 500
    assert '5000 chars' in str(record[0].message)
