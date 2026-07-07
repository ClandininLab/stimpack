#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys
from time import sleep
import posixpath
import warnings
import traceback
from typing import Optional

from PyQt6.QtWidgets import QApplication

from stimpack.rpc.launch import launch_server
from stimpack.rpc.transceiver import MySocketClient
from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.util import get_rgba
from stimpack.experiment.server import BaseServer
from stimpack.experiment.protocol import BaseProtocol
from stimpack.experiment.data import BaseData
from stimpack.experiment.util import config_tools
from stimpack.device import daq
from stimpack.device.locomotion.loco_managers.keytrac_managers import KeytracClosedLoopManager
from stimpack.util import ROOT_DIR

class BaseClient():
    def __init__(self, cfg:dict):
        """
        Parameters
        ----------
        cfg : dict
            Configuration dictionary.
        """
        self.stop:bool = False
        self.pause:bool = False
        self.cfg:dict = cfg

        # Messages pushed back from the server (drained in the run loop via manager.process_queue()).
        self.server_messages:list = []
        self.server_error:Optional[str] = None      # set when the server reports an error; aborts the run
        self.on_server_message = None               # optional callback(level, text), e.g. a GUI status hook

        # # # Load server options from config file and selections # # #
        self.server_options = config_tools.get_server_options(self.cfg)
        self.trigger_device = config_tools.load_trigger_device(self.cfg)

        # # # Start the stim manager and set the frame tracker square to black # # #
        # use a remote server
        if self.server_options.get('use_server', False) or self.server_options.get('use_remote_server', False): 
            # Assume the remote server is already running and listening on the specified host and port
            self.manager = MySocketClient(host=self.server_options['host'], port=self.server_options['port'])
        
        else: # use a local server, either the default or a specified one
            local_server_initialized = False

            # local server path is specified; start it in a separate process
            if 'local_server_path' in self.server_options:
                server_path: str = self.server_options['local_server_path']
                port = self.server_options.get('port', 60629)
                if not os.path.isabs(server_path):
                    server_path = os.path.join(config_tools.get_labpack_directory(), server_path)
                if os.path.exists(server_path):
                    # start the server in a separate process
                    self.manager, self.local_server_process = launch_server(server_path, host='127.0.0.1', port=port)
                    local_server_initialized = True
                else:
                    warnings.warn(f"Server path {server_path} does not exist. Using default local server.")
            
            # no local server path specified; start the default local server
            if not local_server_initialized:
                x_display = self.server_options.get('x_display', None)
                display_index: int = self.server_options.get('display_index', 0)

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
                                    visual_stim_kwargs=visual_stim_kwargs, 
                                    loco_class=loco_class, 
                                    loco_kwargs=loco_kwargs, 
                                    start_loop=True)
                self.manager = MySocketClient(host=server.host, port=server.port)

        # if the trigger device is on the server, set the manager for the trigger device
        if isinstance(self.trigger_device, daq.DAQonServer):
            self.trigger_device.set_manager(self.manager)

        # Let the server push warnings/errors back to us; delivered when we drain the queue (run loop).
        self.manager.register_function(self.report_server_message, name='report_server_message')

        self.manager.target('visual').corner_square_toggle_stop()
        self.manager.target('visual').corner_square_off()
        self.manager.target('visual').set_idle_background(0)

        # # # Import user-defined stimpack.visual_stim stimuli modules on server screens # # #
        visual_stim_modules_exist = config_tools.user_module_paths_exist(self.cfg, 'visual_stim')
        if config_tools.user_module_specified(self.cfg, 'visual_stim'):
            visual_stim_modules_exist = config_tools.user_module_paths_exist(self.cfg, 'visual_stim')
            visual_stim_modules_paths = config_tools.get_module_paths(self.cfg, 'visual_stim')
            for exists, path in zip(visual_stim_modules_exist, visual_stim_modules_paths):
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

    def report_server_message(self, level, text):
        """Handle a message pushed back from the server (run via manager.process_queue()).

        level: 'info' | 'warning' | 'error'. An 'error' marks the current run to be aborted.
        """
        self.server_messages.append((level, text))
        print(f"[server:{level}] {text}")
        if level == 'error':
            self.server_error = text
        if self.on_server_message is not None:
            try:
                self.on_server_message(level, text)
            except Exception:
                warnings.warn(f"on_server_message callback failed:\n{traceback.format_exc()}")

    def start_run(self, protocol_object:BaseProtocol, data:BaseData, save_metadata_flag:bool=True):
        """
        Required inputs: protocol_object, data
            protocol_object defines the protocol and associated parameters to be used
            data handles the metadata file
        """
        self.stop = False
        self.pause = False
        self.server_error = None
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
        # run_status is recorded on the series group at the end (data.end_epoch_run). The try/finally
        # guarantees a clean teardown + a recorded outcome even if the run aborts or raises.
        run_status, run_status_reason = 'completed', None
        try:
            self.manager.print_on_server("Starting run.")
            protocol_object.on_run_start(self.manager)
            while protocol_object.num_epochs_completed < protocol_object.run_parameters['num_epochs']:
                QApplication.processEvents()

                # Drain anything the server pushed back (e.g. an error) and act on it.
                self.manager.process_queue()
                if self.server_error is not None:
                    run_status, run_status_reason = 'error', self.server_error
                    warnings.warn(f"Aborting run: server reported an error: {self.server_error}")
                    break

                # Detect a dead server link — otherwise every send is a silent no-op and the run
                # would march to completion against a server that is not displaying/recording anything.
                if getattr(self.manager, 'connection_broken', False):
                    run_status, run_status_reason = 'aborted', 'server_connection_lost'
                    warnings.warn("Aborting run: connection to the stimulus server appears broken.")
                    break

                if self.stop is True:
                    self.stop = False
                    run_status = 'stopped'
                    break

                if self.pause is True:
                    pass # do nothing until resumed or stopped
                else: # start epoch and advance counter
                    self.start_epoch(protocol_object, data, save_metadata_flag=save_metadata_flag)
        except Exception as e:
            run_status, run_status_reason = 'error', f'{type(e).__name__}: {e}'
            warnings.warn(f"Run aborted by exception:\n{traceback.format_exc()}")
        finally:
            protocol_object.on_run_finish(self.manager)

            broken = getattr(self.manager, 'connection_broken', False)
            if not broken:
                # Set frame tracker to dark
                self.manager.target('visual').corner_square_toggle_stop()
                self.manager.target('visual').corner_square_off()

            # Stop locomotion device / software
            if protocol_object.loco_available and protocol_object.run_parameters['do_loco']:
                self.stop_loco()

            # Record the outcome of this run in the data file.
            if save_metadata_flag:
                data.end_epoch_run(protocol_object, status=run_status, reason=run_status_reason)

            if not broken:
                self.manager.print_on_server('Run ended.')

    def start_epoch(self, protocol_object:BaseProtocol, data:BaseData, save_metadata_flag:bool=True):
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
    def start_loco(self, data:BaseData, save_metadata_flag:bool=True):
        '''
        Set up locomotion data saving on the server and start locomotion device / software
        '''
        if save_metadata_flag:
            server_data_directory: Optional[str] = self.server_options.get('data_directory', None)
            if server_data_directory is not None:
                # set server-side directory in which to save animal positions from each screen.
                server_series_dir = posixpath.join(server_data_directory, data.experiment_file_name, str(data.series_count))
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
