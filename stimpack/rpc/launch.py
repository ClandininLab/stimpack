"""Launching a server in a subprocess and returning a connected client."""
import sys, subprocess, os.path, json, atexit

from time import sleep, time
from types import ModuleType

from stimpack.rpc.transceiver import MySocketClient
from stimpack.rpc.util import find_free_port

def fullpath(file):
    """
    Instead of undoing the symlinks and getting to the "real path",
    maintain symlinks. This avoids the problem caused when using
    virtual environments with symlinks to the python executable.
    """
    return os.path.expanduser(file)

def launch_server(module_or_filename: str | ModuleType, 
                  new_env_vars: dict | None = None, 
                  server_poll_timeout: float = 10, 
                  server_poll_interval: float = 0.1, 
                  **kwargs) -> tuple[MySocketClient, subprocess.Popen]:
    # create list to hold command
    cmd = []

    # add python interpreter
    cmd += [fullpath(sys.executable)]

    # add path to server file
    if isinstance(module_or_filename, str):
        filename = module_or_filename
    elif isinstance(module_or_filename, ModuleType):
        filename = module_or_filename.__file__
    else:
        raise ValueError('Unknown type: {}'.format(type(module_or_filename)))

    cmd += [fullpath(filename)]

    # define host if necessary
    if 'host' not in kwargs:
        kwargs['host'] = '127.0.0.1'

    # define port if necessary
    if 'port' not in kwargs:
        kwargs['port'] = find_free_port(kwargs['host'])

    # write options to process
    cmd += [json.dumps(kwargs)]

    # set the environment variables
    if new_env_vars is None:
        new_env_vars = {}
    env = os.environ.copy()
    env.update(new_env_vars)

    # launch process
    proc = subprocess.Popen(args=cmd, env=env)

    # Reap the child on exit, but with a bound (then force it) so a server that does not auto-stop
    # can't hang interpreter exit forever.
    def _reap():
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    atexit.register(_reap)

    # try to establish a connection to the server
    server_poll_start = time()
    while (time() - server_poll_start) < server_poll_timeout:
        # If the child died before accepting a connection (ImportError in a server script, missing
        # display, bad kwargs, ...), surface its exit code immediately instead of burning the whole
        # timeout and reporting a generic failure.
        returncode = proc.poll()
        if returncode is not None:
            raise RuntimeError(
                f'Server process exited with code {returncode} before accepting a connection.\n'
                f'  command: {cmd}')
        try:
            client = MySocketClient(host=kwargs['host'], port=kwargs['port'])
            return client, proc
        except ConnectionRefusedError:
            sleep(server_poll_interval)

    raise TimeoutError(
        f"Could not connect to server at {kwargs['host']}:{kwargs['port']} within {server_poll_timeout}s.\n"
        f'  command: {cmd}')
