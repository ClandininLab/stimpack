#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys
from time import sleep
import posixpath
import warnings
from PyQt6.QtWidgets import QApplication

from stimpack.rpc.launch import launch_server
from stimpack.rpc.transceiver import MySocketClient
from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.util import get_rgba
from stimpack.experiment.server import BaseServer
from stimpack.experiment.util import config_tools
from stimpack.device import daq
from stimpack.device.locomotion.loco_managers.keytrac_managers import KeytracClosedLoopManager
from stimpack.util import ROOT_DIR

class BaseClient():
    def __init__(self, cfg):
        self.stop = False
        self.pause = False
        self.manager = None
        self.cfg = cfg
        
        # # # Load server options from config file and selections # # #
        self.server_options = config_tools.get_server_options(self.cfg)
        self.trigger_device = config_tools.load_trigger_device(self.cfg)

        # # # Start the stim manager and set the frame tracker square to black # # #
        # use a remote server
        if self.server_options.get('use_server', False) or self.server_options.get('use_remote_server', False): 
            # Assume the remote server is already running and listening on the specified host and port
            self.manager = MySocketClient(host=self.server_options['host'], port=self.server_options['port'])
        
        else: # use a local server, either the default or a specified one
            # local server path is specified; start it in a separate process
            if 'local_server_path' in self.server_options:
                server_path = self.server_options['local_server_path']
                port = self.server_options.get('port', 60629)
                if not os.path.isabs(server_path):
                    server_path = os.path.join(config_tools.get_labpack_directory(), server_path)
                if os.path.exists(server_path):
                    # start the server in a separate process
                    self.manager, self.local_server_process = launch_server(server_path, host='', port=port, return_process_handle=True)
                else:
                    warnings.warn(f"Server path {server_path} does not exist. Using default local server.")
            
            # no local server path specified; start the default local server
            if self.manager is None:
                x_display = self.server_options.get('x_display', None)
                display_index = self.server_options.get('display_index', 0)

                visual_stim_kwargs = {
                    'screens': [Screen(x_display=x_display, display_index=display_index, fullscreen=False, vsync=True, square_size=(0.1, 0.1),
                                       pa=(-0.15, 0.15, -0.15), pb=(+0.15, 0.15, -0.15), pc=(-0.15, 0.15, +0.15))] # -45 to 45 deg in both theta and phi
                }

                loco_class = KeytracClosedLoopManager
                loco_kwargs = {
                    'host':          '127.0.0.1',
                    'port':           33335,
                    'python_bin':    sys.executable,
                    'kt_py_fn':      os.path.join(ROOT_DIR, "device/locomotion/keytrac/keytrac.py"),
                    'relative_control': 'True',
                }

                server = BaseServer(host='127.0.0.1',
                                    port=None, 
                                    start_loop=True, 
                                    visual_stim_kwargs=visual_stim_kwargs, 
                                    loco_class=loco_class, 
                                    loco_kwargs=loco_kwargs)
                self.manager = MySocketClient(host=server.host, port=server.port)

        # if the trigger device is on the server, set the manager for the trigger device
        if isinstance(self.trigger_device, daq.DAQonServer):
            self.trigger_device.set_manager(self.manager)

        self.manager.target('visual').corner_square_toggle_stop()
        self.manager.target('visual').corner_square_off()
        self.manager.target('visual').set_idle_background(0)

        # # # Import user-defined stimpack.visual_stim stimuli modules on server screens # # #
        visual_stim_modules_exist = config_tools.user_module_exists(self.cfg, 'visual_stim', single_item_in_list=True)
        if visual_stim_modules_exist is not False: # 'visual_stim' is specified under module_paths in the cfg file
            visual_stim_module_paths = config_tools.get_full_paths_to_module(self.cfg, 'visual_stim', single_item_in_list=True)
            for exists, path in zip(visual_stim_modules_exist, visual_stim_module_paths):
                if not exists:
                    warnings.warn(f"Visual stim module {path} does not exist.")
                else:
                    self.manager.target('visual').import_stim_module(path)

    def stop_run(self):
        self.stop = True
        QApplication.processEvents()

    def pause_run(self):
        self.pause = True
        QApplication.processEvents()

    def resume_run(self):
        self.pause = False
        QApplication.processEvents()

    def start_run(self, protocol_object, data, save_metadata_flag=True):
        """
        Required inputs: protocol_object, data
            protocol_object defines the protocol and associated parameters to be used
            data handles the metadata file
        """
        self.stop = False
        self.pause = False
        protocol_object.save_metadata_flag = save_metadata_flag

        # Check run parameters, compute persistent parameters, and precompute epoch parameters
        # Do not recompute epoch parameters if they have been computed already
        protocol_object.prepare_run(manager=self.manager, recompute_epoch_parameters=False)

        # Set background to idle_color
        self.manager.target('visual').set_idle_background(get_rgba(protocol_object.run_parameters.get('idle_color', 0)))

        if save_metadata_flag:
            data.create_epoch_run(protocol_object)
        else:
            print('Warning - you are not saving your metadata!')

        # Set up locomotion data saving on the server and start locomotion device / software
        if protocol_object.loco_available and protocol_object.run_parameters['do_loco']:
            self.start_loco(data, save_metadata_flag=save_metadata_flag)
            
        # Trigger acquisition of scope and cameras by send triggering TTL through the DAQ device (if device is set)
        if protocol_object.trigger_on_epoch_run is True:
            if self.trigger_device is not None:
                print("Triggering acquisition devices.")
                self.trigger_device.send_trigger()

        # Start locomotion loop on the server only if closed_loop is an option for the protocol.
        if protocol_object.loco_available and protocol_object.run_parameters['do_loco'] and 'loco_pos_closed_loop' in protocol_object.protocol_parameters:
            self.start_loco_loop()

        # # # Epoch run loop # # #
        self.manager.print_on_server("Starting run.")
        protocol_object.on_run_start(self.manager)
        while protocol_object.num_epochs_completed < protocol_object.run_parameters['num_epochs']:
            QApplication.processEvents()
            if self.stop is True:
                self.stop = False
                protocol_object.on_run_finish(self.manager)
                break # break out of epoch run loop

            if self.pause is True:
                pass # do nothing until resumed or stopped
            else: # start epoch and advance counter
                self.start_epoch(protocol_object, data, save_metadata_flag=save_metadata_flag)

        protocol_object.on_run_finish(self.manager)

        # Set frame tracker to dark
        self.manager.target('visual').corner_square_toggle_stop()
        self.manager.target('visual').corner_square_off()

        # Stop locomotion device / software
        if protocol_object.loco_available and protocol_object.run_parameters['do_loco']:
            self.stop_loco()

        if save_metadata_flag:
            data.end_epoch_run(protocol_object)
        self.manager.print_on_server('Run ended.')

    def start_epoch(self, protocol_object, data, save_metadata_flag=True):
        #  get stimulus parameters for this epoch
        if protocol_object.use_precomputed_epoch_parameters:
            protocol_object.load_precomputed_epoch_parameters()
        else:
            protocol_object.get_epoch_parameters()
        
        # Check that all required epoch protocol parameters are set
        protocol_object.check_required_epoch_protocol_parameters()

        if save_metadata_flag:
            data.create_epoch(protocol_object)

        # Send triggering TTL through the DAQ device (if device is set)
        if protocol_object.trigger_on_epoch is True:
            if self.trigger_device is not None:
                print("Triggering acquisition devices.")
                self.trigger_device.send_trigger()

        self.manager.print_on_server(f'Epoch {protocol_object.num_epochs_completed}')

        # Use the protocol object to send the stimulus to stimpack.visual_stim
        protocol_object.load_stimuli(self.manager)

        protocol_object.start_stimuli(self.manager)

        self.manager.print_on_server('Epoch completed.')

        if save_metadata_flag:
            data.end_epoch(protocol_object)
        
        protocol_object.advance_epoch_counter()

    #%% Locomotion methods
    def start_loco(self, data, save_metadata_flag=True):
        '''
        Set up locomotion data saving on the server and start locomotion device / software
        '''
        if save_metadata_flag:
            server_data_directory = self.server_options.get('data_directory', None)
            if server_data_directory is not None:
                # set server-side directory in which to save animal positions from each screen.
                server_series_dir = posixpath.join(server_data_directory, data.get_server_subdir(), str(data.series_count))
                server_pos_history_dir = posixpath.join(server_series_dir, 'visual_stim_pos')
                self.manager.target('all').set_save_pos_history_dir(server_pos_history_dir)

                # set server-side directory in which to save locomotion data
                server_loco_dir = posixpath.join(server_series_dir, 'loco')
                self.manager.target('locomotion').set_save_directory(server_loco_dir)
            else:
                print("Warning: Locomotion data won't be saved without server's data_directory specified in config file.")
        self.manager.target('locomotion').start()
        sleep(3) # Give locomotion device / software time to load
    
    def start_loco_loop(self):
        '''
        Start locomotion loop on the server for closed-loop updating
        '''
        sleep(2) # Give loco time to start acquiring
        self.manager.target('locomotion').loop_start() # start loop, which is superfluous if closed loop is not needed for the exp.
        
    def stop_loco(self):
        self.manager.target('locomotion').close()
        self.manager.target('locomotion').set_save_directory(None)
    
    def close(self):
        # We had started a local server in a separate process; terminate it.
        if 'local_server_process' in self.__dict__:
            print("Closing local server.")
            self.local_server_process.terminate()
