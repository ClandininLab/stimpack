import subprocess
import signal
import numpy as np

from stimpack.device.locomotion.loco_managers import LocoManager, LocoClosedLoopManager

KEYTRAC_HOST = '127.0.0.1'  # The server's hostname or IP address
KEYTRAC_PORT = 33335         # The port used by the server
PYTHON_BIN =   'python'
KEYTRAC_PY =   'keytrac.py'

class KeytracManager(LocoManager):
    def __init__(self, python_bin=PYTHON_BIN, kt_py_fn=KEYTRAC_PY, relative_control=True, start_at_init=True, verbose=False):
        super().__init__(verbose=verbose)
        
        self.python_bin = python_bin
        self.kt_py_fn = kt_py_fn
        self.relative_control = relative_control
        self.keytrac_host = KEYTRAC_HOST
        self.keytrac_port = KEYTRAC_PORT

        self.started = False
        self.p = None

        if start_at_init:
            self.start()

    def start(self):
        if self.started:
            if self.verbose: print("KeytracManager: Keytrac is already running.")
        else:
            self.p = subprocess.Popen([self.python_bin, self.kt_py_fn, self.keytrac_host, str(self.keytrac_port), self.relative_control], start_new_session=True)
            self.started = True

    def close(self, timeout=5):
        if self.started:
            self.p.send_signal(signal.SIGINT)
            
            try:
                self.p.wait(timeout=timeout)
            except:
                print("KeytracManager: Timeout expired for closing Keytrac. Killing process...")
                self.p.kill()
                self.p.terminate()

            self.p = None
            self.started = False
        else:
            if self.verbose: print("KeytracManager: Keytrac hasn't been started yet. Cannot be closed.")

class KeytracClosedLoopManager(LocoClosedLoopManager):
    def __init__(self, stim_server, host=KEYTRAC_HOST, port=KEYTRAC_PORT, 
                       python_bin=PYTHON_BIN, kt_py_fn=KEYTRAC_PY, 
                       relative_control=True, start_at_init=False, udp=True):
        super().__init__(stim_server=stim_server, host=host, port=port, save_directory=None, start_at_init=False, udp=udp)
        self.kt_manager = KeytracManager(python_bin=python_bin, kt_py_fn=kt_py_fn, relative_control=relative_control, start_at_init=False)

        if start_at_init:    self.start()

    def start(self):
        super().start()
        self.kt_manager.start()

    def close(self):
        super().close()
        self.kt_manager.close()

    def _parse_line(self, line):
        toks = line.split(", ")

        # Keytrac lines always starts with KT
        if toks.pop(0) != "KT":
            print(line)
            print('Bad read')
            return None
        
        key_count = int(toks[0])
        key_pressed = toks[1]
        x = float(toks[2])
        y = float(toks[3])
        z = float(toks[4])
        theta = np.rad2deg(float(toks[5]))
        phi = np.rad2deg(float(toks[6]))
        roll = np.rad2deg(float(toks[7]))
        ts = float(toks[8])

        return {'x': x, 'y': y, 'z':z, 'theta': theta, 'phi': phi, 'roll': roll, 'frame_num': key_count, 'ts': ts}

    def set_pos_0(self, loco_pos = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}, use_data_prev=True, get_most_recent=True, write_log=False):
        self.socket_manager.send_message("reset_pos")
        super().set_pos_0(loco_pos = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}, 
                          use_data_prev=use_data_prev, 
                          get_most_recent=get_most_recent, 
                          write_log=write_log)
        