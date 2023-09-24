import os
import socket, select
import threading
import json
from math import degrees
from time import time

class LocoManager():
    def __init__(self) -> None:
        pass
    
    def set_save_directory(self, save_dir):
        pass
    
    def start(self):
        pass
    
    def close(self):
        pass

class LocoSocketManager():
    def __init__(self, host, port, udp=True) -> None:
        self.host = host
        self.port = port
        self.udp = udp
        self.client_addr = None

        self.sock = None
        self.sock_buffer = "\n"
        self.data_prev = []

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
    def __init__(self, fs_manager, host, port, save_directory=None, start_at_init=False, udp=True) -> None:
        super().__init__()
        self.fs_manager = fs_manager
        self.socket_manager = LocoSocketManager(host=host, port=port, udp=udp)
        
        self.save_directory = save_directory
        self.log_file = None

        self.data_prev = []
        self.pos_0 = {'theta': 0, 'x': 0, 'y': 0, 'z': 0}
        self.pos   = {'theta': 0, 'x': 0, 'y': 0, 'z': 0}

        self.loop_attrs = {
            'thread': None,
            'looping': False,
            'closed_loop': False,
            'update_theta': True,
            'update_x': False,
            'update_y': False,
            'update_z': False
        }

        self.loop_custom_fxn = None

        if start_at_init:
            self.start()
        
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
        
        print("Please implement __parse_line in the inheriting class!")

        theta = 0
        x = 0
        y = 0
        z = 0
        frame_num = 0
        ts = 0
        
        return {'theta': theta, 'x': x, 'y': y, 'z': z, 'frame_num': frame_num, 'ts': ts}
  
    def set_pos_0(self, theta_0=None, x_0=0, y_0=0, z_0=0, use_data_prev=True, get_most_recent=True, write_log=False):
        '''
        Sets position 0 for stimpack.visual_stim manager.
        
        theta_0, x_0, y_0, z_0: 
            if None, the current value is acquired from socket.
        
        get_most_recent:
            Only relevant if getting data for the first time or use_data_prev = False
            if True, grabs line that is most recent
            if False, grabs line that is the oldest
        '''
        self.fs_manager.set_global_theta_offset(0) #radians
        self.fs_manager.set_global_subject_pos(0, 0, 0)

        if None in [theta_0, x_0, y_0, z_0]:
            if use_data_prev and len(self.data_prev)!=0:
                data = self.data_prev
            else:
                data = self.get_data(get_most_recent=get_most_recent)

            if theta_0 is None: theta_0 = float(data['theta'])
            if     x_0 is None:     x_0 = float(data['x'])
            if     y_0 is None:     y_0 = float(data['y'])
            if     z_0 is None:     z_0 = float(data['z'])
        
            frame_num = int(data['frame_num'])
            ts = float(data['ts'])
        else:
            frame_num = -1
            ts = None

        self.pos_0['theta'] = theta_0
        self.pos_0['x']     = x_0
        self.pos_0['y']     = y_0
        self.pos_0['z']     = z_0
        self.pos['theta']   = theta_0
        self.pos['x']       = x_0
        self.pos['y']       = y_0
        self.pos['z']       = z_0
        
        if write_log and self.log_file is not None:
            if ts is None:
                ts = time()
            log_line = json.dumps({'set_pos_0': {'frame_num': frame_num, 'theta': theta_0, 'x': x_0, 'y': y_0, 'z': z_0}, 'ts': ts})
            self.write_to_log(log_line)
    
    def write_to_log(self, string):
        if self.log_file is not None:
            self.log_file.write(str(string) + "\n")

    def update_pos(self, update_theta=True, update_x=False, update_y=False, update_z=False, return_pos=False):
        data = self.get_data()
        
        self.pos['theta'] = float(data['theta']) - self.pos_0['theta'] #radians
        self.pos['x'] = float(data['x']) - self.pos_0['x']
        self.pos['y'] = float(data['y']) - self.pos_0['y']
        self.pos['z'] = float(data['z']) - self.pos_0['z']

        if update_theta: self.fs_manager.set_global_theta_offset(degrees(self.pos['theta']))
        if update_x:     self.fs_manager.set_global_subject_x(self.pos['x'])
        if update_y:     self.fs_manager.set_global_subject_y(self.pos['y'])
        if update_z:     self.fs_manager.set_global_subject_z(self.pos['z'])

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
                    self.update_pos(update_theta = self.loop_attrs['update_theta'], 
                                    update_x     = self.loop_attrs['update_x'], 
                                    update_y     = self.loop_attrs['update_y'],
                                    update_z     = self.loop_attrs['update_z'])
                else:
                    self.update_pos(update_theta = False,
                                    update_x     = False, 
                                    update_y     = False,
                                    update_z     = False)
                    
                if self.loop_custom_fxn is not None:
                    self.loop_custom_fxn(self.pos)

        if self.loop_attrs['looping']:
            print("Already looping")
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

    def loop_update_closed_loop_vars(self, update_theta=True, update_x=False, update_y=False, update_z=False):
        self.loop_attrs['update_theta'] = update_theta
        self.loop_attrs['update_x']     = update_x
        self.loop_attrs['update_y']     = update_y
        self.loop_attrs['update_z']     = update_z
    
    def loop_update_custom_fxn(self, custom_fxn):
        if isinstance(custom_fxn, function):
            self.loop_custom_fxn = custom_fxn
        else:
            pass