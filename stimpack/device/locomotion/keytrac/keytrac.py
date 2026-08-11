"""Deprecated location: forwards to stimpack/locomotion/keytrac/keytrac.py.

This file exists because labpack server scripts build the KeyTrac app's path from stimpack's
install directory (``os.path.join(ROOT_DIR, 'device/locomotion/keytrac/keytrac.py')``) and hand
it to KeytracManager, which launches it with ``python <path> <host> <port> <relative>``. Moving
the app without this forwarder would turn that launch into a FileNotFoundError on any labpack
that has not updated its path yet. Removed with the rest of stimpack.device in 2.0.
"""
import runpy
import warnings

if __name__ == '__main__':
    warnings.warn('stimpack/device/locomotion/keytrac/keytrac.py is deprecated; launch '
                  'stimpack/locomotion/keytrac/keytrac.py instead (same arguments).',
                  DeprecationWarning, stacklevel=2)
    # sys.argv passes through untouched: the app reads host/port/relative from argv[1:].
    runpy.run_module('stimpack.locomotion.keytrac.keytrac', run_name='__main__')
