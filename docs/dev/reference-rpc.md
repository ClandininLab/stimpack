# Reference: `stimpack.rpc`

The dependency‑free bottom layer. Provides JSON‑over‑TCP, fire‑and‑forget RPC
that connects the client, the server, per‑screen subprocesses, and device
managers. Imports only the Python standard library.

> Conceptual overview and routing are in [`ARCHITECTURE.md`](ARCHITECTURE.md)
> §1–4. This file is the class/function reference.

Files: `transceiver.py`, `launch.py`, `multicall.py`, `util.py`,
`echo_server.py`, `__init__.py` (empty).

---

## Wire protocol

* One message = one line of newline‑terminated JSON.
* Each line decodes to a **request list**: a JSON array of request dicts
  `{"name": <fn>, "args": [...], "kwargs": {...}, "target": <module>?}`.
* **No responses.** No return values, IDs, or error channel.
* Tuples survive JSON via `JSONCoderWithTuple`: a tuple is encoded as
  `{"__tuple__": true, "items": [...]}` and rebuilt on decode with an
  `object_hook`. (This is how positional `*args` tuples round‑trip.)

---

## `transceiver.py`

### `MyTransceiver`
Base class holding the function registry, the outbound stream (`self.outfile`),
the inbound `queue.Queue`, and a `shutdown_flag` (`threading.Event`). Auto‑
registers a `shutdown` function so any peer can remotely set the flag.

| Method | Purpose |
|---|---|
| `register_function(fn, name=None)` | Expose a callable to remote peers. Asserts on duplicate names. |
| `write_request_list(list)` | JSON‑encode one line, utf‑8‑encode for binary streams, `write`+`flush`. No‑ops if `outfile is None`; swallows `BrokenPipeError`. |
| `handle_request_list(list)` | Dispatch each request to `self.functions[name](*args, **kwargs)`, synchronously. `warnings.warn` on unknown/invalid. **Ignores the `target` key** (subclasses implement routing). |
| `process_queue()` | Drain `self.queue` with `get_nowait`; the application must call this from its own loop. |
| `parse_line(line)` | Decode one wire line to a request list. |

### `MySocketClient(host='127.0.0.1', port=…)`
TCP client proxy. `create_connection`, registers an `atexit` socket‑close, wraps
the socket as a text `infile` and binary `outfile`, and starts a **daemon reader
thread** (`loop`).

* `__getattr__(name)` → returns a closure that serializes `{name, args, kwargs}`
  and sends it as a 1‑element request list. **This is the "remote call looks
  local" magic.** Any missing attribute becomes a send — including typos.
* `target(target_name)` → a proxy whose `__getattr__` adds the `target` key.
* `loop()` (reader thread) → parses inbound lines (silently skips
  `JSONDecodeError`) and `queue.put`s them. Nothing drains this queue by default.

### `MySocketServer(host='127.0.0.1', port=0, threaded=True, auto_stop=True, accept_timeout=…, name=…)`
TCP listener. `port=0` ⇒ OS‑assigned. Prints `name hostname/port` to stdout
(informational — never parsed by the launcher). `accept_timeout` defaults to 10 s
when `auto_stop`.

* `loop()` → **serial** accept loop (one connection at a time). Per connection it
  sets `self.outfile` (enabling server→client pushes) and reads lines: if
  `threaded`, `queue.put`; else `handle_request_list` inline. On disconnect calls
  `on_connection_close()` and, if `auto_stop`, sets `shutdown_flag`.
* `__getattr__(name)` → like the client but **executes locally** via
  `handle_request_list` (same syntax, opposite semantics).
* `target(target_name)` → local‑dispatch variant.
* `on_connection_close()` → subclass hook (overridden by `BaseServer` /
  `VisualStimServer`).

`threaded`/`auto_stop`/`name`/`accept_timeout` are the knobs subclasses tune:
`VisualStimServer` and `BaseServer` use `threaded=False`; screen `framework.py`
servers use `threaded=True, auto_stop=True`.

---

## `launch.py` — `launch_server(module_or_filename, new_env_vars=None, server_poll_timeout=10, server_poll_interval=0.1, **kwargs) → (MySocketClient, subprocess.Popen)`

Spawns a server script as a subprocess and returns a connected client.

1. `cmd = [sys.executable, <file>, json.dumps(kwargs)]` (accepts a filename or a
   `ModuleType`, using its `__file__`).
2. Defaults `host='127.0.0.1'`; if no `port`, `find_free_port()` (parent chooses).
3. `Popen`, `atexit.register(proc.wait)`.
4. Poll‑connect a `MySocketClient` until success or the 10 s timeout (retrying
   only on `ConnectionRefusedError`); raise `Exception('Could not connect to
   server.')` on timeout.

> The child is **not** watched for early death, so a crash in the child surfaces
> only as the generic 10 s timeout (see [`IMPROVEMENTS.md`](IMPROVEMENTS.md) #15).

---

## `multicall.py` — `MyMultiCall(transceiver)`

Accumulates calls and flushes them as **one** wire line so they execute
near‑coincidently.

* `mc.any_name(*a, **k)` → queue a request.
* `mc.target('visual').fn(...)` → queue a targeted request.
* `mc()` → send the accumulated list (via `transceiver.write_request_list`).

> `__call__` does **not** clear `self.request_list`; call it once per instance
> (see [`IMPROVEMENTS.md`](IMPROVEMENTS.md) #28).

---

## `util.py`

| Symbol | Purpose |
|---|---|
| `start_daemon_thread(target)` | Fire‑and‑forget daemon `Thread` (never joined). |
| `stream_is_binary(stream)` | `'b' in stream.mode`. |
| `find_free_port(host='')` | Bind‑to‑0 probe then close (a TOCTOU race — the port can be taken before reuse). |
| `get_kwargs()` | In a launched child, decode `sys.argv[1]` (JSON) → `defaultdict(lambda: None)`. Bare `except:` falls back to `{}`. |
| `get_from_dict(dict, keys, default=None, remove=False)` | Multi‑key getter with optional `pop`; returns a scalar for a single key. |
| `JSONCoderWithTuple` | `encode`/`decode` static methods implementing the tuple‑hinting codec. |

---

## `echo_server.py`

The minimal reference child process: `get_kwargs()` → `MySocketServer(name=
'EchoServer', threaded=False)` → `register_function(echo)` → `loop()`. It is the
template every launchable server (including `visual_stim/framework.py` and the
labpack rig servers) follows, and it backs `examples/rpc/client.py`.

---

## Extending the RPC layer

* `register_function(fn, name=None)` on any transceiver to expose a callable.
* Subclass `MySocketServer` and override `handle_request_list` for custom
  routing (this is exactly what `BaseServer` and `VisualStimServer` do).
* Add a new server module: `self.modules['mymodule'] = MyModule(...)` in a
  `BaseServer` subclass; clients then call `manager.target('mymodule').fn(...)`
  with zero RPC‑layer changes.
* `launch_server(script, new_env_vars=…, **server_kwargs)` works with any script
  following the `get_kwargs()` + `MySocketServer` + `loop()` template.
