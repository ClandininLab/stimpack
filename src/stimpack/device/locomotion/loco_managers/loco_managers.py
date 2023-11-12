import os
import socket, select
import threading
import json
from math import degrees
from time import time

class LocoManager():
    def __init__(self, verbose=False) -> None:
        self.verbose = verbose
        pass
    
    def set_save_directory(self, save_dir):
        pass
    
    def start(self):
        pass
    
    def close(self):
        pass

    def handle_request_list(self, request_list):
        for request in request_list:
            if request['name'] in dir(self):
                # If the request is a method of this class, execute it.
                getattr(self, request['name'])(*request['args'], **request['kwargs'])
            else:
                if self.verbose: print(f"{self.__class__.__name__}: Requested method {request['name']} not found.")
    
class LocoSocketManager():
    def __init__(self, host, port, udp=True, verbose=False) -> None:
        self.host = host
        self.port = port
        self.udp = udp
        self.client_addr = None
        
        self.verbose = verbose

        self.sock = None
        self.sock_buffer = "\n"
        self.data_prev = []

    def handle_request_list(self, request_list):
        for request in request_list:
            if request['name'] in dir(self):
                # If the request is a method of this class, execute it.
                getattr(self, request['name'])(*request['args'], **request['kwargs'])
            else:
                if self.verbose: print(f"{self.__class__.__name__}: Requested method {request['name']} not found.")
    
    def connect(self):
        '''
        Open / connect to socket
        '''
        if self.udp:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.bind((self.host, self.port))
                print(f'LocoSocketManager: Bound socket to {self.host}:{self.port}')
                self.sock.setblocking(0)
            except :
                print("LocoSocketManager: Failed to bind socket.")
                self.close()
                return
        else: # TCP
            # TODO: Maybe need to listen for connection? This should be a server, receiving requests from locomotion source (e.g. Fictrac)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))

    def close(self):
        if self.sock is not None:
            # Clear out any remaining data
            _ = self.receive_message(wait_for=0)
            
            try:
                self.sock.close()
            except:
                print("LocoSocketManager: Failed to close socket.")
            
            self.sock = None
            self.client_addr = None

    def send_message(self, message):
        if self.sock is None:
            return
        
        try:
            if self.client_addr is None:
                print("LocoSocketManager: No client address. Cannot send message. Must wait until a message is received.")
                return
            if self.udp:
                self.sock.sendto(message.encode(), self.client_addr)
        except socket.error as e:
            print(e)
            print("LocoSocketManager: Failed to send message.")
            return

    def receive_message(self, wait_for=None):
        '''
        wait_for:
            None: wait until there is data to read
            0: return immediately if there is no data to read
            >0: wait for that many seconds for data to read
        '''
        if self.sock is None:
            return
        
        ready = []
        while not ready:
            if self.sock == -1:
                print('\nLocoSocketManager: Socket disconnected.')
                return None
            if wait_for is None:
                ready = select.select([self.sock], [], [])[0]
            else:
                ready = select.select([self.sock], [], [], wait_for)[0]

        # Check again in case we were stuck at select.select while socket was closed
        if self.sock is None:
            return None
        
        data, addr = self.sock.recvfrom(4096)
        self.client_addr = addr
        return data

    def get_line(self, wait_for=None, get_most_recent=True):
        '''
        Assumes that lines are separated by '\n'
        wait_for:
            None: wait until there is data to read
            0: return immediately if there is no data to read
            >0: wait for that many seconds for data to read
        '''
        
        new_data = self.receive_message(wait_for=wait_for)
        if new_data is None:
            return None
        ##

        if not new_data and not self.udp: # TCP and blank new_data...
            print('\nLocoSocketManager: Disconnected from TCP server.')
            return None

        # Decode received data
        self.sock_buffer += new_data.decode('UTF-8')

        # print(f'Input buffer: {self.sock_buffer}')
        if get_most_recent:
            ## Find the last frame of data

            endline = self.sock_buffer.rfind("\n")
            assert endline != 1, "LocoSocketManager: There must always be at least one linebreak in the buffer."
            
            # Find the end of the second to last frame. (\n is always left behind)
            prev_endline = self.sock_buffer[:endline-1].rfind("\n")
            if prev_endline == -1:
                return self.get_line(wait_for=wait_for, get_most_recent=get_most_recent)
            startline = prev_endline + 1
            
            line = self.sock_buffer[startline:endline]       # copy last frame
            self.sock_buffer = self.sock_buffer[endline:]     # delete through last frame, leaving behind the last \n
        else:
            ## Find the first frame of data

            # Find the start of the first frame
            # prev_endline = self.sock_buffer.find("\n")
            # assert prev_endline != 1, "There must always be at least one linebreak in the buffer."
            # if len(self.sock_buffer) <= prev_endline + 1: # nothing after the first \n
            #     return self.get_line(wait_for=wait_for, get_most_recent=get_most_recent)

            # Assume \n is the beginning of the buffer always
            if len(self.sock_buffer) <= 1: # nothing after the first \n
                return self.get_line(wait_for=wait_for, get_most_recent=get_most_recent)
            startline = 1

            # Find the end of the first frame
            endline = self.sock_buffer[startline:].find("\n")
            if endline == -1:
                return self.get_line(wait_for=wait_for, get_most_recent=get_most_recent)

            line = self.sock_buffer[startline:endline]       # copy first frame
            self.sock_buffer = self.sock_buffer[endline:]     # delete first frame, leaving behind the \n

        # print(f'Output buffer: {self.sock_buffer}')
        # print(f'Grabbed line: {line}')
        return line

class LocoClosedLoopManager(LocoManager):
    def __init__(self, stim_server, host, port, save_directory=None, start_at_init=False, udp=True, verbose=False) -> None:
        super().__init__(verbose=verbose)
        self.stim_server = stim_server
        self.socket_manager = LocoSocketManager(host=host, port=port, udp=udp, verbose=verbose)
        
        self.save_directory = save_directory
        self.log_file = None

        self.data_prev = []
        self.pos_0 = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0} # meters and degrees
        self.pos   = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0} # meters and degrees

        self.loop_attrs = {
            'thread': None,
            'looping': False,
            'closed_loop': False,
            'update_x': True,
            'update_y': True,
            'update_z': True,
            'update_theta': True,
            'update_phi': False,
            'update_roll': False
        }

        self.loop_custom_fxn = None

        if start_at_init:
            self.start()

    def handle_request_list(self, request_list):
        for request in request_list:
            if request['name'] in dir(self):
                # If the request is a method of this class, execute it.
                getattr(self, request['name'])(*request['args'], **request['kwargs'])
            else:
                if self.verbose: print(f"{self.__class__.__name__}: Requested method {request['name']} not found.")
        
    def set_save_directory(self, save_directory):
        self.save_directory = save_directory
        
    def start(self):
        self.socket_manager.connect()
        
        if self.save_directory is not None:
            os.makedirs(self.save_directory, exist_ok=True)
            log_path = os.path.join(self.save_directory, 'log.txt')
            self.log_file = open(log_path, "a")

        self.started = True

    def close(self):
        if self.is_looping():
            self.loop_stop()

        self.socket_manager.close()
        
        if self.log_file is not None:
            self.log_file.flush()
            self.log_file.close()
            self.log_file = None
            
        self.started = False

    def get_data(self, wait_for=None, get_most_recent=True):
        line = self.socket_manager.get_line(wait_for=wait_for, get_most_recent=get_most_recent)
        if line is None:
            return None

        data = self._parse_line(line)
        self.data_prev = data

        return data
    
    def _parse_line(self, line):
        # TODO: Check line and parse line

        toks = line.split(", ")
        
        print(f"{self.__class__.__name__}: Please implement __parse_line in the inheriting class!")

        x = 0
        y = 0
        z = 0
        theta = 0
        phi = 0
        roll = 0
        frame_num = 0
        ts = 0
        
        return {'x': x, 'y': y, 'z': z, 'theta': theta, 'phi': phi, 'roll': roll, 'frame_num': frame_num, 'ts': ts}
  
    def set_pos_0(self, loco_pos = {'x': None, 'y': None, 'z': None, 'theta': None, 'phi': None, 'roll': None}, 
                  use_data_prev=True, get_most_recent=True, write_log=False):
        '''
        Maps the specified locomotion device's output to the stimpack.experiment.server's position 0.
        
        loco_pos: 
            dictionary of position variables to map to 0.
            keys: position variables to map to 0
            values: locomotion device position
                    if None, the current value is acquired from socket.
        
        get_most_recent:
            Only relevant if getting data for the first time or use_data_prev = False
            if True, grabs line that is most recent
            if False, grabs line that is the oldest
        '''
        
        loco_state_pos_pairs = {k: (loco_pos[k], 0) for k in loco_pos.keys()}
        
        self.map_loco_to_server_pos(loco_state_pos_pairs=loco_state_pos_pairs, 
                                    use_data_prev=use_data_prev, 
                                    get_most_recent=get_most_recent, 
                                    write_log=write_log)

    def map_loco_to_server_pos(self, 
                loco_state_pos_pairs = {'x': (None, 0), 'y': (None, 0), 'z': (None, 0), 'theta': (None, 0), 'phi': (None, 0), 'roll': (None, 0)}, 
                use_data_prev=True, get_most_recent=True, write_log=False):
        '''
        Sets mapping between locomotion device's output and stimpack.experiment.server's position.
        
        loco_state_pos_pairs: 
            dictionary of position variables to map from locomotion device to stimpack.experiment.server.
            keys: position variables to map to stimpack.experiment.server
            values: tuple of (locomotion device position, stimpack.experiment.server position)
            If locomotion device position is None, the current value is acquired from socket.
        
        get_most_recent:
            Only relevant if getting data for the first time or use_data_prev = False
            if True, grabs line that is most recent
            if False, grabs line that is the oldest
        '''
        
        assert isinstance(loco_state_pos_pairs, dict), "loco_state_pos_pairs must be a dictionary."
        assert all([k in ['x', 'y', 'z', 'theta', 'phi', 'roll'] for k in loco_state_pos_pairs.keys()]), "loco_state_pos_pairs must only contain keys in ['x', 'y', 'z', 'theta', 'phi', 'roll']"
        
        loco_pos   = {k:v[0] for k,v in loco_state_pos_pairs.items()}
        server_pos = {k:v[1] for k,v in loco_state_pos_pairs.items()}
        
        self.stim_server.set_subject_state(server_pos)

        if None in loco_pos.values():
            if use_data_prev and len(self.data_prev)!=0:
                data = self.data_prev
            else:
                data = self.get_data(get_most_recent=get_most_recent)

            for k,v in loco_pos.items():
                if v is None: loco_pos[k] = float(data.get(k, 0))
        
            frame_num = int(data['frame_num'])
            ts = float(data['ts'])
        else:
            frame_num = -1
            ts = None
        
        for k in loco_state_pos_pairs.keys():
            loco_state_pos_pairs[k] = (loco_pos[k], server_pos[k])
            self.pos_0[k] = loco_pos[k] - server_pos[k] # the scalar offset to apply to the locomotion device's position to get the stimpack.experiment.server's position
            self.pos[k]   = server_pos[k]
        
        if write_log and self.log_file is not None:
            if ts is None:
                ts = time()
            log_line = json.dumps({'set_pos': {'frame_num': frame_num} | loco_state_pos_pairs, 'ts': ts})
            self.write_to_log(log_line)
    
    def write_to_log(self, string):
        if self.log_file is not None:
            self.log_file.write(str(string) + "\n")

    def update_pos(self, update_x=True, update_y=True, update_z=True, update_theta=True, update_phi=False, update_roll=False, return_pos=False):
        data = self.get_data()
        
        self.pos['x']     = float(data.get('x',     0)) - self.pos_0['x']
        self.pos['y']     = float(data.get('y',     0)) - self.pos_0['y']
        self.pos['z']     = float(data.get('z',     0)) - self.pos_0['z']
        self.pos['theta'] = float(data.get('theta', 0)) - self.pos_0['theta'] # degrees
        self.pos['phi']   = float(data.get('phi',   0)) - self.pos_0['phi']   # degrees
        self.pos['roll']  = float(data.get('roll',  0)) - self.pos_0['roll']  # degrees
        
        update_dict = {}
        if update_x:     update_dict['x']     = self.pos['x']
        if update_y:     update_dict['y']     = self.pos['y']
        if update_z:     update_dict['z']     = self.pos['z']
        if update_theta: update_dict['theta'] = self.pos['theta']
        if update_phi:   update_dict['phi']   = self.pos['phi']
        if update_roll:  update_dict['roll']  = self.pos['roll']
        if len(update_dict) > 0:
            self.stim_server.set_subject_state(update_dict)
        
        if return_pos:
            return self.pos.copy()
        else:
            return

    def is_looping(self):
        return self.loop_attrs['looping']

    def loop_start(self):
        def loop_helper():
            self.loop_attrs['looping'] = True
            while self.loop_attrs['looping']:
                if self.loop_attrs['closed_loop']:
                    self.update_pos(update_x     = self.loop_attrs['update_x'], 
                                    update_y     = self.loop_attrs['update_y'],
                                    update_z     = self.loop_attrs['update_z'],
                                    update_theta = self.loop_attrs['update_theta'], 
                                    update_phi   = self.loop_attrs['update_phi'],
                                    update_roll  = self.loop_attrs['update_roll'])
                else:
                    self.update_pos(update_x     = False, 
                                    update_y     = False,
                                    update_z     = False,
                                    update_theta = False,
                                    update_phi   = False,
                                    update_roll  = False)
                    
                if self.loop_custom_fxn is not None:
                    self.loop_custom_fxn(self.pos)

        if self.loop_attrs['looping']:
            if self.verbose: print(f"{self.__class__.__name__}: Already looping")
        else:
            self.loop_attrs['thread'] = threading.Thread(target=loop_helper, daemon=True)
            self.loop_attrs['thread'].start()

    def loop_stop(self):
        self.loop_attrs['looping'] = False
        self.loop_attrs['closed_loop'] = False
        if self.loop_attrs['thread'] is not None:
            self.loop_attrs['thread'].join(timeout=5)
            self.loop_attrs['thread'] = None

    def loop_start_closed_loop(self):
        self.loop_attrs['closed_loop'] = True

    def loop_stop_closed_loop(self):
        self.loop_attrs['closed_loop'] = False

    def loop_update_closed_loop_vars(self, update_x=False, update_y=False, update_z=False, update_theta=True, update_phi=False, update_roll=False):
        self.loop_attrs['update_x']     = update_x
        self.loop_attrs['update_y']     = update_y
        self.loop_attrs['update_z']     = update_z
        self.loop_attrs['update_theta'] = update_theta
        self.loop_attrs['update_phi']   = update_phi
        self.loop_attrs['update_roll']  = update_roll
    