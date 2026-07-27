"""Shared test doubles: stand in for the RPC link and the client, so real stimpack objects can be
driven with no server, screens, GL, or hardware."""


class FakeManager:
    """Stands in for MySocketClient: records calls instead of sending them over a socket.

    Mirrors the surface BaseClient/BaseProtocol use: target(...) proxies, register_function,
    process_queue, arbitrary fire-and-forget attribute calls, and the connection_broken health flag.
    """

    def __init__(self):
        self.calls = []                # (target, name, args, kwargs) in order
        self.connection_broken = False
        self.functions = {}
        self.inbox = []                # messages the "server" will push on the next process_queue()

    # --- surface used by BaseClient / BaseProtocol ---
    def register_function(self, function, name=None):
        self.functions[name or function.__name__] = function

    def process_queue(self):
        while self.inbox:
            name, args, kwargs = self.inbox.pop(0)
            if name in self.functions:
                self.functions[name](*args, **kwargs)

    def target(self, target_name):
        manager = self

        class _Target:
            def __getattr__(self, name):
                def f(*args, **kwargs):
                    manager.calls.append((target_name, name, args, kwargs))
                return f
        return _Target()

    def __getattr__(self, name):
        # Any other attribute access is an untargeted ("root") fire-and-forget call.
        def f(*args, **kwargs):
            self.calls.append((None, name, args, kwargs))
        return f

    # --- helpers for assertions ---
    def call_names(self, target=None):
        return [c[1] for c in self.calls if target is None or c[0] == target]

    def push_server_message(self, level, text):
        """Queue a message as if the server pushed it back; delivered on the next process_queue()."""
        self.push_server_request("report_server_message", level, text)

    def push_server_request(self, name, *args, **kwargs):
        """Queue any request as if the server had sent it -- the server calls functions on the
        client too, not only report_server_message (see BaseServer.end_epoch)."""
        self.inbox.append((name, args, kwargs))


class FakeClient:
    """Stands in for BaseClient in GUI tests: records runs instead of driving a real server."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.manager = FakeManager()
        self.on_server_message = None
        self.runs = []                 # (protocol class name, save_metadata_flag) per start_run
        self.stop = False
        self.pause = False

    def start_run(self, protocol_object, data, save_metadata_flag=True):
        self.runs.append((protocol_object.__class__.__name__, save_metadata_flag))

    def stop_run(self):
        self.stop = True

    def pause_run(self):
        self.pause = True

    def resume_run(self):
        self.pause = False

    def close(self):
        pass
