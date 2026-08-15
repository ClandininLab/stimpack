#!/usr/bin/env python3
"""Demo: server-side errors are reported back to the client (the "client reporter").

Stands up a real MySocketServer + MySocketClient over a loopback socket, wires error reporting the
same way BaseServer.report_to_client / BaseClient.report_server_message do, and drives a failing
remote call so you can watch the client receive the error. No GUI, GL, or hardware needed.

Run:  python examples/rpc/error_reporting.py
"""
import time

from stimpack.rpc.transceiver import MySocketServer, MySocketClient


def wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def main():
    # --- Server: expose a function that can fail, and report handler errors to the client. ---
    server = MySocketServer(host="127.0.0.1", port=0, threaded=True, auto_stop=False)
    port = server.listener.getsockname()[1]

    def load_stim(width=10):
        if width <= 0:
            raise ValueError(f"width must be > 0 (got {width})")
        print(f"  SERVER: loaded stim with width={width}")

    server.register_function(load_stim)
    # This is what BaseServer.report_to_client does under the hood:
    server.error_reporter = lambda level, text: server.write_request_list(
        [{"name": "report_server_message", "args": [level, text], "kwargs": {}}])

    # --- Client: register the same handler BaseClient uses, and drain its queue to receive pushes. ---
    client = MySocketClient(host="127.0.0.1", port=port)
    server_errors = []

    def report_server_message(level, text):
        print(f"  CLIENT: received  ->  [server:{level}] {text}")
        if level == "error":
            server_errors.append(text)

    client.register_function(report_server_message, name="report_server_message")
    wait_until(lambda: server.outfile is not None)  # server has accepted the client connection

    # 1) A good call: nothing is reported back.
    print("\n[1] client calls load_stim(width=10)  -- valid")
    client.load_stim(width=10)
    wait_until(lambda: not server.queue.empty())
    server.process_queue()          # server executes queued requests (BaseServer does this in its loop)
    time.sleep(0.1)
    client.process_queue()          # client drains anything pushed back (BaseClient does this each run-loop iteration)
    print(f"    client-side server_errors: {server_errors}")

    # 2) A bad call: the handler raises -> the server isolates + reports it -> the client receives it.
    print("\n[2] client calls load_stim(width=-5)  -- fails on the server")
    client.load_stim(width=-5)
    wait_until(lambda: not server.queue.empty())
    server.process_queue()          # load_stim raises; the error is isolated and reported to the client
    wait_until(lambda: not client.queue.empty())
    client.process_queue()          # client receives the pushed error
    print(f"    client-side server_errors: {server_errors}")

    print("\n(The server also logs the full traceback locally via warnings.warn — shown above.)")
    server.shutdown_flag.set()


if __name__ == "__main__":
    main()
