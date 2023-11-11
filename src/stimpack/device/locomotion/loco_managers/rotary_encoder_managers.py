import subprocess
import signal
import numpy as np

from stimpack.device.locomotion.loco_managers import LocoManager, LocoClosedLoopManager

ROTENC_HOST = '127.0.0.1'  # The server's hostname or IP address
ROTENC_PORT = 33336         # The port used by the server
PYTHON_BIN =   'python'
ROTENC_PY =   'rotenc.py'

class RotaryEncoderManager(LocoManager):
    def __init__(self, python_bin=PYTHON_BIN, rotenc_py_fn=ROTENC_PY, start_at_init=True, verbose=False):
        super().__init__(verbose=verbose)
        
        self.python_bin = python_bin
        self.rotenc_py_fn = rotenc_py_fn
        self.rotenc_host = ROTENC_HOST
        self.rotenc_port = ROTENC_PORT

        self.started = False
        self.p = None

        if start_at_init:
            self.start()

    def start(self):
        if self.started:
            if self.verbose: print("RotaryEncoderManager: RotaryEncoder is already running.")
        else:
            self.p = subprocess.Popen([self.python_bin, self.rotenc_py_fn, self.rotenc_host, str(self.rotenc_port)], start_new_session=True)
            self.started = True

    def close(self, timeout=5):
        if self.started:
            self.p.send_signal(signal.SIGINT)
            
            try:
                self.p.wait(timeout=timeout)
            except:
                print("RotaryEncoderManager: Timeout expired for closing RotaryEncoder. Killing process...")
                self.p.kill()
                self.p.terminate()

            self.p = None
            self.started = False
        else:
            if self.verbose: print("RotaryEncoderManager: RotaryEncoder hasn't been started yet. Cannot be closed.")

class RotaryEncoderClosedLoopManager(LocoClosedLoopManager):
    def __init__(self, stim_server, host=ROTENC_HOST, port=ROTENC_PORT, 
                       start_at_init=False, udp=True,
                       wheel_radius=0.1, n_pulses_per_rev=1024, pulse_polarity=1):
        super().__init__(stim_server=stim_server, host=host, port=port, save_directory=None, start_at_init=start_at_init, udp=udp)
                
        self.wheel_radius = wheel_radius
        self.n_pulses_per_rev = n_pulses_per_rev
        self.dist_per_pulse = 2*np.pi*self.wheel_radius/self.n_pulses_per_rev
        self.pulse_polarity = pulse_polarity
        
        self.y = 0

        if start_at_init:    self.start()

    def start(self):
        super().start()

    def close(self):
        super().close()

    def _parse_line(self, line):
        toks = line.split(", ")

        # RotaryEncoder lines always starts with RE
        if toks.pop(0) != "RE":
            print(f'RotaryEncoderClosedLoopManager: Bad line: {line}')
            return None
        
        frame_count = int(toks[0])
        net_pulses_in_frame = int(toks[1])
        ts = float(toks[2])
        # y = float(toks[3])
        self.y += self.pulse_polarity * net_pulses_in_frame * self.dist_per_pulse

        return {'y': self.y, 'frame_num': frame_count, 'ts': ts}

    def set_pos_0(self, x_0=0, y_0=None, z_0=0, theta_0=0, phi_0=0, roll_0=0, use_data_prev=True, get_most_recent=True, write_log=False):
        super().set_pos_0(x_0=0, y_0=y_0, z_0=0, theta_0=0, phi_0=0, roll_0=0, 
                          use_data_prev=use_data_prev, 
                          get_most_recent=get_most_recent, 
                          write_log=write_log)
