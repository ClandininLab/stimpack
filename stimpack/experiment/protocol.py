#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocol parent class. Override any methods in here in the user protocol subclass

A user-defined protocol class needs to overwrite the following methods, at minimum:
-get_epoch_parameters()
-get_protocol_parameter_defaults()

And probably also:
-get_run_parameter_defaults()

You can also overwrite the following methods if you want to change the default behavior:
-prepare_run()
-process_input_parameters()
-load_stimuli()
-start_stimuli()
You may want to run the parent method first, then add your own code.
e.g. super().prepare_run()

see the simple example protocol classes at the bottom of this module.

-protocol_parameters: user-defined params that are mapped to stimpack.visual_stim epoch params
                     *saved as attributes at the epoch run level
-epoch_protocol_parameters: epoch-specific user-defined params that are mapped to stimpack.visual_stim epoch params
                     *saved as attributes at the individual epoch level
-epoch_stim_parameters: parameter set used to define stimpack.visual_stim stimulus
                     *saved as attributes at the individual epoch level
"""
import sys
import numpy as np
from time import sleep
import os.path
import os
import math
import yaml
import itertools
import warnings
import stimpack.rpc.multicall
from stimpack.visual_stim.util import get_rgba
from stimpack.experiment.util import config_tools
from stimpack.util import ROOT_DIR


class BaseProtocol():
    def __init__(self, cfg):
        self.cfg = cfg

        self.parameter_preset_directory = os.path.curdir
        self.trigger_on_epoch_run = True  # Used in control.EpochRun.start_run(), sends a TTL trigger to start acquisition devices
        self.trigger_on_epoch = False  # Used in control.EpochRun.start_epoch(), sends a TTL trigger to start acquisition devices
        self.save_metadata_flag = False  # Bool, whether or not to save this series. Set to True by GUI on 'record' but not 'view'.
        self.use_precomputed_epoch_parameters = True  # Bool, whether or not to precompute epoch parameters

        self.use_server_side_state_dependent_control = False  # Bool, whether or not to use custom closed-loop control
        
        self.num_epochs_completed = 0
        self.persistent_parameters = {}
        self.precomputed_epoch_parameters = {}

        # epoch_protocol_parameters used to store protocol parameters that will be saved out in an easily accessible place in the data file
        # Fill this in with desired parameters in get_epoch_parameters(). Can also be used to control other features of the stimulus and used in load_stimuli()
        self.epoch_protocol_parameters = {}

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()
        self.load_parameter_presets()
        
        self.parameter_preset_directory = config_tools.get_parameter_preset_directory(self.cfg)
        if self.parameter_preset_directory is not None:
            os.makedirs(self.parameter_preset_directory, exist_ok=True)

        # Rig-specific screen center
        self.screen_center = config_tools.get_screen_center(self.cfg)
        
        # Rig-specific loco_available
        self.loco_available = config_tools.get_loco_available(self.cfg)

    def adjust_center(self, relative_center):
        absolute_center = [sum(x) for x in zip(relative_center, self.screen_center)]
        return absolute_center

    def get_epoch_parameters(self):
        """ Inherit / overwrite me in the child subclass"""
        self.epoch_protocol_parameters = None
        self.epoch_stim_parameters = None

        # Get protocol parameters for this epoch
        self.epoch_protocol_parameters = self.select_epoch_protocol_parameters(
                                                all_combinations=self.run_parameters.get('all_combinations', True), 
                                                randomize_order =self.run_parameters.get('randomize_order', False))

    def get_run_parameter_defaults(self):
        """ Overwrite me in the child subclass"""
        return {}

    def get_protocol_parameter_defaults(self):
        """ Overwrite me in the child subclass"""
        return {}

    def load_parameter_presets(self):
        fname = os.path.join(self.parameter_preset_directory, self.__class__.__name__) + '.yaml'
        if os.path.isfile(fname):
            with open(fname, 'r') as ymlfile:
                self.parameter_presets = yaml.load(ymlfile, Loader=yaml.Loader)
        else:
            self.parameter_presets = {}

    def update_parameter_presets(self, name):
        self.load_parameter_presets()
        new_preset = {'run_parameters': self.run_parameters,
                      'protocol_parameters': self.protocol_parameters}
        self.parameter_presets[name] = new_preset
        with open(os.path.join(self.parameter_preset_directory, self.__class__.__name__ + '.yaml'), 'w+') as ymlfile:
            yaml.dump(self.parameter_presets, ymlfile, default_flow_style=False, sort_keys=False)

    def select_protocol_preset(self, name='Default'):
        '''
        Parameters that are not present in the preset will use the current protocol's default values.
        '''

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

        # If loco is available, add/set "do_loco" boolean to run parameters
        if self.loco_available:
            self.run_parameters['do_loco'] = False

        # If name is 'Default' or is not in parameter_presets, just use the current protocol's defaults
        if name == 'Default':
            return
        elif name not in self.parameter_presets:
            warnings.warn(f'Warning: Preset {name} not found.', RuntimeWarning)
            return
        
        # Warn about any param that is not in the preset
        for k in self.run_parameters.keys():
            if k not in self.parameter_presets[name]['run_parameters'].keys():
                warnings.warn(f'Warning: run parameter {k} not found in preset {name}; using default.', RuntimeWarning)
        for k in self.protocol_parameters.keys():
            if k not in self.parameter_presets[name]['protocol_parameters'].keys():
                warnings.warn(f'Warning: protocol parameter {k} not found in preset {name}; using default.', RuntimeWarning)

        # Update the protocol parameters
        # Warn about any preset param that is not in the current protocol
        for k, v in self.parameter_presets[name]['run_parameters'].items():
            if k in self.run_parameters.keys():
                self.run_parameters[k] = v
            else:
                warnings.warn(f'Warning: run parameter {k} not found in current protocol. Skipping preset parameter.', RuntimeWarning)
        for k, v in self.parameter_presets[name]['protocol_parameters'].items():
            if k in self.protocol_parameters.keys():
                self.protocol_parameters[k] = v
            else:
                warnings.warn(f'Warning: protocol parameter {k} not found in current protocol. Skipping preset parameter.', RuntimeWarning)            

    def advance_epoch_counter(self):
        self.num_epochs_completed += 1
        
    def precompute_epoch_parameters(self, refresh=False):
        """
        Precompute epoch parameters for all epochs in advance
        Can prevent slowdowns during epoch run loop and assists with estimating run time
        """
        if refresh:
            self.precomputed_epoch_parameters = {}

        if len(self.precomputed_epoch_parameters) == 0:
            precomputed_epoch_stim_parameters = []
            precomputed_epoch_protocol_parameters = []
            for e in range(int(self.run_parameters['num_epochs'])):
                self.num_epochs_completed = e
                self.get_epoch_parameters()
                self.check_required_epoch_protocol_parameters()
                precomputed_epoch_stim_parameters.append(self.epoch_stim_parameters)
                precomputed_epoch_protocol_parameters.append(self.epoch_protocol_parameters)
            self.precomputed_epoch_parameters = {'stim': precomputed_epoch_stim_parameters,
                                                'protocol': precomputed_epoch_protocol_parameters}
            self.num_epochs_completed = 0

    def load_precomputed_epoch_parameters(self):
        self.epoch_stim_parameters = self.precomputed_epoch_parameters['stim'][self.num_epochs_completed]
        self.epoch_protocol_parameters = self.precomputed_epoch_parameters['protocol'][self.num_epochs_completed]

    def __estimate_run_time(self):
        '''
        If pre_time, stim_time, and tail_time are specified in the protocol parameters, this method will estimate the total run time.
        '''
        epoch_protocol_params = self.precomputed_epoch_parameters['protocol']
        self.est_run_time = np.sum([p.get('pre_time', 0) + p.get('stim_time', 0) + p.get('tail_time', 0) for p in epoch_protocol_params])

    def process_input_parameters(self):
        """
        Process input parameters and set persistent parameters prior to epoch run loop
        Overwrite me in the child subclass as needed
        """
        self.persistent_parameters['variable_protocol_parameter_names'] = [k for k,v in self.protocol_parameters.items() if isinstance(v, list) and len(v) > 1]

    def check_required_run_parameters(self):
        """
        required_run_parameters: list of tuples (parameter_name, parameter_dtype)
            parameter is cast to parameter_dtype; if no cast is needed, use None
        """
        required_run_parameters = [('num_epochs', int), ('idle_color', None)]
        if self.loco_available:
            required_run_parameters.append(('do_loco', bool))
        
        for p, dtype in required_run_parameters:
            if p not in self.run_parameters:
                raise ValueError(f'Run parameter {p} is required but not found in {self.run_parameters}')
            else:
                if dtype is not None:
                    if not isinstance(dtype, list):
                        dtype = [dtype]

                    value_error = False
                    for d in dtype:
                        try:
                            self.run_parameters[p] = d(self.run_parameters[p])
                            value_error = False
                            break
                        except:
                            value_error = True
                    if value_error:
                        raise ValueError(f'Run parameter {p} could not be cast to {dtype}.')
    
    def check_required_epoch_protocol_parameters(self):
        """
        required_run_parameters: list of tuples (parameter_name, parameter_dtype)
            parameter is cast to parameter_dtype; if no cast is needed, use None
        """
        required_protocol_parameters = [('pre_time', float), ('stim_time', float), ('tail_time', float)]
        
        for p, dtype in required_protocol_parameters:
            if p not in self.epoch_protocol_parameters:
                raise ValueError(f'Epoch protocol parameter {p} is required but not found in {self.epoch_protocol_parameters}')
            else:
                if dtype is not None:
                    try:
                        self.epoch_protocol_parameters[p] = dtype(self.epoch_protocol_parameters[p])
                    except:
                        raise ValueError(f'Epoch protocol parameter {p} could not be cast to {dtype}')

    def prepare_run(self, manager=None, recompute_epoch_parameters=True):
        """
        recompute_epoch_parameters: bool
            If True, precompute epoch parameters even if they have been computed already
            If False, do not recompute epoch parameters if they have been computed already
        """
        self.num_epochs_completed = 0
        self.persistent_parameters = {}
        self.epoch_protocol_parameters = {}

        # Process input parameters and set persistent parameters prior to epoch run loop
        self.process_input_parameters()

        # Check that all required run parameters are set
        self.check_required_run_parameters()
        
        # Precompute epoch parameters
        self.precompute_epoch_parameters(refresh=recompute_epoch_parameters)

        # Estimate run time
        self.__estimate_run_time()

        # If manager exists, set visual_stim background to idle_color
        if manager is not None:
            manager.target('visual').set_idle_background(get_rgba(self.run_parameters.get('idle_color', 0)))

    def on_run_start(self, manager):
        """
        Method that is called at the beginning of each run. Does not itself start the run.
        Can be overwritten in the child subclass with super().on_run_start(manager) to add additional functionality.
        """
        # If self.use_server_side_state_dependent_control is True, signal to the server that custom closed-loop control is being used
        # We currently assume that the protocol module is in the labpack and that its path is specified in the config file as relative to the labpack
        if self.use_server_side_state_dependent_control:
            protocol_path = os.path.abspath(sys.modules[self.__module__].__file__)
            if protocol_path.startswith(config_tools.get_labpack_directory()):
                protocol_path = os.path.relpath(protocol_path, config_tools.get_labpack_directory())
            elif protocol_path.startswith(ROOT_DIR):
                protocol_path = None # Stimpack example protocol
            else:
                raise ValueError(f'Protocol path {protocol_path} is not in the labpack directory or the stimpack directory.')
            
            manager.target('root').load_server_side_state_dependent_control(
                protocol_module_path = protocol_path,
                protocol_name = self.__class__.__name__
            )
        self.num_epochs_completed = 0

    def load_stimuli(self, manager, multicall=None):
        if multicall is None:
            multicall = stimpack.rpc.multicall.MyMultiCall(manager)

        bg = get_rgba(self.run_parameters.get('idle_color', 0))
        multicall.target('visual').set_idle_background(bg)
        multicall.target('visual').load_stim('ConstantBackground', color=bg, hold=True)

        if isinstance(self.epoch_stim_parameters, list):
            for ep in self.epoch_stim_parameters:
                if ep is not None:
                    multicall.target('visual').load_stim(**ep.copy(), hold=True)
        else:
            if self.epoch_stim_parameters is not None:
                multicall.target('visual').load_stim(**self.epoch_stim_parameters.copy(), hold=True)

        multicall()

    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
        
        # locomotion setting variables
        do_loco = self.run_parameters.get('do_loco', False)
        do_loco_closed_loop = do_loco and self.epoch_protocol_parameters.get('loco_pos_closed_loop', False)
        save_pos_history = do_loco_closed_loop and self.save_metadata_flag
        
        ### pre time
        sleep(self.epoch_protocol_parameters['pre_time'])
        
        if multicall is None:
            multicall = stimpack.rpc.multicall.MyMultiCall(manager)

        ### stim time
        # locomotion / closed loop
        if do_loco:
            multicall.target('locomotion').set_pos_0(loco_pos = {'x': None, 'y': None, 'z': None, 'theta': None, 'phi': None, 'roll': None}, 
                                                                  use_data_prev=True, write_log=self.save_metadata_flag)
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_update_closed_loop_vars(update_theta=True, update_x=True, update_y=True)
            multicall.target('locomotion').loop_start_closed_loop()
        
        multicall.target('all').set_save_pos_history_flag(save_pos_history)
        multicall.target('all').start_stim(append_stim_frames=append_stim_frames)
        multicall.target('visual').corner_square_toggle_start()
        multicall()
        sleep(self.epoch_protocol_parameters['stim_time'])

        ### tail time
        multicall = stimpack.rpc.multicall.MyMultiCall(manager)
        multicall.target('all').stop_stim(print_profile=print_profile)
        multicall.target('visual').corner_square_toggle_stop()
        multicall.target('visual').corner_square_off()

        # locomotion / closed loop
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_stop_closed_loop()
        if save_pos_history:
            multicall.target('all').save_pos_history_to_file(epoch_id=f'{self.num_epochs_completed:03d}')

        multicall()

        sleep(self.epoch_protocol_parameters['tail_time'])
        
    def on_run_finish(self, manager, multicall=None):
        """
        Method that is called at the end of each run, either when the run is completed or when the run is stopped.
        Fill in if you want to do something at the end of each run.
        Overwrite me in the child subclass.
        """
        # If self.use_server_side_state_dependent_control is True, signal to the server that custom closed-loop control is no longer being used
        if self.use_server_side_state_dependent_control:
            manager.target('root').unload_server_side_state_dependent_control()
        
    def get_parameter_sequence(self, parameter_list, all_combinations=True, randomize_order=False):
        """
        inputs
        parameter_list can be:
            -list/array of parameters
            -single value (int, float etc)
            -tuple of lists, where each list contains values for a single parameter
                    in this case, all_combinations = True will return all possible combinations of parameters, taking
                    one from each parameter list. If all_combinations = False, keeps params associated across lists
        randomize_order will randomize sequence or sequences at the beginning of each new sequence
        """

        # parameter_list is a tuple of lists or a single list
        if type(parameter_list) is list: # single protocol parameter list, choose one from this list
            parameter_sequence = parameter_list

        elif type(parameter_list) is tuple: # multiple lists of protocol parameters
            if all_combinations:
                parameter_list_new = []

                # check for non-list elements of the tuple (int or float user entry)
                for param in list(parameter_list):
                    if type(param) is not list:
                        parameter_list_new.append([param])
                    else:
                        parameter_list_new.append(param)
                parameter_list = tuple(parameter_list_new)

                # parameter_sequence is num_combinations by num params
                parameter_sequence = list(itertools.product(*parameter_list))
            else:
                parameter_list_new = []

                # sequence length is determined by the length of the longest list
                # for non-list elements or lists with shorter lengths, repeat to fill out the max length                
                sequence_length = max([(len(param) if type(param) is list else 1) for param in parameter_list])
                
                for param in list(parameter_list):
                    if type(param) is not list:
                        parameter_list_new.append([param] * sequence_length)
                    else:
                        n_repeats = sequence_length // len(param)
                        n_remainder = sequence_length % len(param)
                        parameter_list_new.append(param * n_repeats + param[:n_remainder])
                
                # keep params in lists associated with one another
                # requires param lists of equal length
                parameter_sequence = np.vstack(np.array(parameter_list_new, dtype=object)).T

        else: # user probably entered a single value (int or float), convert to list
            parameter_sequence = [parameter_list]

        # Get sequence order
        num_epochs_in_sequence = len(parameter_sequence)
        num_epoch_sequences = math.ceil(self.run_parameters['num_epochs'] / num_epochs_in_sequence)
        
        # index in parameter_sequence for each epoch
        if randomize_order:
            parameter_sequence_epoch_inds = np.concatenate([np.random.permutation(num_epochs_in_sequence) for _ in range(num_epoch_sequences)])[:self.run_parameters['num_epochs']]
        else:
            parameter_sequence_epoch_inds = np.arange(self.run_parameters['num_epochs']) % num_epochs_in_sequence

        self.persistent_parameters['protocol_parameter_sequence'] = parameter_sequence
        self.persistent_parameters['protocol_parameter_sequence_epoch_inds'] = parameter_sequence_epoch_inds
    
    def select_epoch_protocol_parameters(self, all_combinations=True, randomize_order=False):
        """
        inputs
        all_combinations:
            True will return all possible combinations of parameters, taking one from each parameter list. 
            False keeps params associated across lists
        randomize_order will randomize sequence or sequences at the beginning of each new sequence

        returns
        epoch_protocol_parameters:
            dictionary of protocol parameter names and values specific to this epoch.
        """

        # new run: initialize parameter sequences if not already done
        if self.num_epochs_completed == 0 and 'protocol_parameter_sequence' not in self.persistent_parameters:
            self.get_parameter_sequence(tuple(self.protocol_parameters.values()), all_combinations=all_combinations, randomize_order=randomize_order)

        # get current epoch parameters
        parameter_sequence = self.persistent_parameters['protocol_parameter_sequence']
        parameter_sequence_epoch_inds = self.persistent_parameters['protocol_parameter_sequence_epoch_inds']

        epoch_protocol_parameter_values = parameter_sequence[parameter_sequence_epoch_inds[self.num_epochs_completed]]
        epoch_protocol_parameters = {parameter_name: epoch_protocol_parameter_values[i] for i, parameter_name in enumerate(self.protocol_parameters.keys())}

        return epoch_protocol_parameters
    


#%%

class SharedPixMapProtocol(BaseProtocol):
    def __init__(self, cfg):
        super().__init__(cfg)

        self.use_precomputed_epoch_parameters = True  # Bool, whether or not to precompute epoch parameters

        # Shared pixmap stim parameters
        self.epoch_shared_pixmap_stim_parameters = None

    def precompute_epoch_parameters(self, refresh=False):
        if refresh:
            self.precomputed_epoch_parameters = {}

        if len(self.precomputed_epoch_parameters) == 0:
            precomputed_epoch_stim_parameters = []
            precomputed_epoch_shared_pixmap_stim_parameters = []
            precomputed_epoch_protocol_parameters = []
            for e in range(int(self.run_parameters['num_epochs'])):
                self.num_epochs_completed = e
                self.get_epoch_parameters()
                self.check_required_epoch_protocol_parameters()
                precomputed_epoch_stim_parameters.append(self.epoch_stim_parameters)
                precomputed_epoch_protocol_parameters.append(self.epoch_protocol_parameters)
                precomputed_epoch_shared_pixmap_stim_parameters.append(self.epoch_shared_pixmap_stim_parameters)
            self.precomputed_epoch_parameters = {'stim': precomputed_epoch_stim_parameters,
                                                'protocol': precomputed_epoch_protocol_parameters,
                                                'pixmap': precomputed_epoch_shared_pixmap_stim_parameters}
            self.num_epochs_completed = 0

    def load_precomputed_epoch_parameters(self):
        self.epoch_stim_parameters = self.precomputed_epoch_parameters['stim'][self.num_epochs_completed]
        self.epoch_shared_pixmap_stim_parameters = self.precomputed_epoch_parameters['pixmap'][self.num_epochs_completed]
        self.epoch_protocol_parameters = self.precomputed_epoch_parameters['protocol'][self.num_epochs_completed]

    def load_stimuli(self, manager, multicall=None):
        if multicall is None:
            multicall = stimpack.rpc.multicall.MyMultiCall(manager)

        # Load shared pixmap stimuli if defined # TODO This shouldn't really be a list
        if self.epoch_shared_pixmap_stim_parameters is not None:
            if not isinstance(self.epoch_shared_pixmap_stim_parameters, list):
                self.epoch_shared_pixmap_stim_parameters = [self.epoch_shared_pixmap_stim_parameters]
            for ep in self.epoch_shared_pixmap_stim_parameters:
                multicall.target('visual').load_shared_pixmap_stim(**ep.copy())

        bg = self.run_parameters.get('idle_color')
        multicall.target('visual').load_stim('ConstantBackground', color=get_rgba(bg), hold=True)

        if isinstance(self.epoch_stim_parameters, list):
            for ep in self.epoch_stim_parameters:
                multicall.target('visual').load_stim(**ep.copy(), hold=True)
        else:
            multicall.target('visual').load_stim(**self.epoch_stim_parameters.copy(), hold=True)

        multicall()

    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
        
        # locomotion setting variables
        do_loco = self.run_parameters.get('do_loco', False)
        do_loco_closed_loop = do_loco and self.epoch_protocol_parameters.get('loco_pos_closed_loop', False)
        save_pos_history = do_loco_closed_loop and self.save_metadata_flag
        
        ### pre time
        sleep(self.epoch_protocol_parameters['pre_time'])
        
        if multicall is None:
            multicall = stimpack.rpc.multicall.MyMultiCall(manager)

        ### stim time
        # locomotion / closed loop
        if do_loco:
            multicall.target('locomotion').set_pos_0(loco_pos = {'x': None, 'y': None, 'z': None, 'theta': None, 'phi': None, 'roll': None}, 
                                                                  use_data_prev=True, write_log=self.save_metadata_flag)
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_update_closed_loop_vars(update_theta=True, update_x=False, update_y=False)
            multicall.target('locomotion').loop_start_closed_loop()
        
        # Shared pixmap stimuli
        if self.epoch_shared_pixmap_stim_parameters is not None:
            multicall.target('visual').start_shared_pixmap_stim()
        
        multicall.target('all').start_stim()
        multicall.target('visual').corner_square_toggle_start()
        multicall()
        sleep(self.epoch_protocol_parameters['stim_time'])

        ### tail time
        multicall = stimpack.rpc.multicall.MyMultiCall(manager)
        multicall.target('all').stop_stim(print_profile=print_profile)
        multicall.target('visual').corner_square_toggle_stop()
        multicall.target('visual').corner_square_off()

        # locomotion / closed loop
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_stop_closed_loop()
        if save_pos_history:
            multicall.target('all').save_pos_history_to_file(epoch_id=f'{self.num_epochs_completed:03d}')

        # shared pixmap clear
        if self.epoch_shared_pixmap_stim_parameters is not None:
            multicall.target('visual').clear_shared_pixmap_stim()

        multicall()

        sleep(self.epoch_protocol_parameters['tail_time'])

    def on_run_finish(self, manager, multicall=None):
        """
        Method that is called at the end of each run, either when the run is completed or when the run is stopped.
        Fill in if you want to do something at the end of each run.
        Overwrite me in the child subclass.
        """
        pass
