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

def launch_server(module_or_filename, new_env_vars=None, server_poll_timeout=10, server_poll_interval=0.1, **kwargs):
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

    # wait for this process to terminate upon exit
    atexit.register(proc.wait)

    # try to establish connecting to client
    server_poll_start = time()
    while (time() - server_poll_start) < server_poll_timeout:
        try:
            return MySocketClient(host=kwargs['host'], port=kwargs['port'])
        except ConnectionRefusedError:
            sleep(server_poll_interval)
    else:
        raise Exception('Could not connect to server.')
