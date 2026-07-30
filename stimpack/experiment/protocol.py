#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocol parent class. Override any methods in here in the user protocol subclass

A user-defined protocol class needs to overwrite the following methods, at minimum:
-get_trial_parameters()
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

The three parameter sets a protocol works with::

    protocol_parameters        user-defined params mapped to stimpack.visual_stim trial params,
                               saved as attributes at the series level
    trial_protocol_parameters  trial-specific user-defined params mapped to stimpack.visual_stim
                               trial params, saved as attributes at the individual trial level
    trial_stim_parameters      the parameter set defining the stimpack.visual_stim stimulus,
                               saved as attributes at the individual trial level
"""
import sys
import numpy as np
import time
from time import sleep
import os.path
import os
import math
import itertools
import warnings

from stimpack.rpc.transceiver import MySocketClient
from stimpack.rpc.multicall import MyMultiCall
from stimpack.experiment.deprecated_names import (add_deprecated_aliases, calls_legacy_override,
                                                  normalize_run_parameters)
from stimpack.visual_stim.util import get_rgba
from stimpack.experiment.util import config_tools
from stimpack.util import ROOT_DIR


# How often an interruptible sleep() looks for a reason to stop, in seconds. Small enough that
# Stop responds within a frame, large enough that waiting costs no measurable CPU.
SLEEP_POLL_INTERVAL = 0.002

# The dropdown entry standing for "the protocol's own values", rather than a saved preset. Not a
# key in parameter_presets, which is why saving one under this name produced two identical-looking
# entries with no way to tell them apart.
DEFAULT_PRESET_NAME = 'Default'


class BaseProtocol():
    def __init__(self, cfg):
        self.cfg = cfg

        self.parameter_preset_directory = os.path.curdir
        self.trigger_on_epoch_run = True  # Used in control.EpochRun.start_run(), sends a TTL trigger to start acquisition devices
        self.trigger_on_epoch = False  # Used in control.EpochRun.start_trial(), sends a TTL trigger to start acquisition devices
        self.save_metadata_flag = False  # Bool, whether or not to save this series. Set to True by GUI on 'record' but not 'view'.
        self.use_precomputed_trial_parameters = True  # Bool, whether or not to precompute trial parameters
        self.stop_sleep_flag = False  # set by stop_trial() to cut a sleep() short
        # The client this protocol is running against, set in prepare_run. None when the protocol
        # is driven without one -- the labpack checker does that -- in which case waits are plain
        # and uninterruptible.
        self.manager = None
        self._warned_uninterruptible_sleep = False
        self.save_stringified_params = False  # Bool, whether to stringify trial stim params for nwb saving. Helpful for protocols with different param keys across trials. Need to supply all_trial_stim_parameter_keys

        self.use_server_side_state_dependent_control = False  # Bool, whether or not to use custom closed-loop control
        
        self.num_trials_completed = 0
        self.persistent_parameters = {}
        self.precomputed_trial_parameters = {}

        # trial_protocol_parameters used to store protocol parameters that will be saved out in an easily accessible place in the data file
        # Fill this in with desired parameters in get_trial_parameters(). Can also be used to control other features of the stimulus and used in load_stimuli()
        self.trial_protocol_parameters = {}

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

        # Modules the server advertised, filled in by prepare_run. None until then / for a server
        # that doesn't advertise. See has_module().
        self.available_modules = None
        self.available_server_functions = None


    def has_module(self, module_name):
        """Whether the connected server has this module ('visual', 'locomotion', 'voltage_out', ...).

        Lets one protocol run on rigs with different hardware instead of keeping a copy per rig:

            if self.has_module('voltage_out') and self.trial_protocol_parameters['opto_amp'] > 0:
                multicall.target('voltage_out').setup_pulse_wave_stream_out(...)

        Answers True when the server didn't advertise its modules (an older stimpack), so this is
        safe to adopt: behavior is unchanged until the server actually reports.

        Note this says the rig can output voltage -- not what is wired to it. Whether an LED, odor
        valve or reward pump is attached, and on which channel, is lab-specific: put that in your
        own rig_config keys and read it in your labpack protocol.
        """
        if self.available_modules is None:
            return True
        return module_name in self.available_modules

    def has_server_function(self, function_name, target='root'):
        """Whether the connected server will answer to this function name.

        The companion to :meth:`has_module`, for the functions a lab registers on its own rig
        servers -- a projector's LED current, a shutter, a valve -- which exist on one rig and not
        another::

            if self.has_server_function('set_dlpc_current'):
                manager.target('root').set_dlpc_current(*self.run_parameters['dlpc_current_start'])

        :param function_name: the name a request would carry
        :param target: where it would be sent -- ``'root'`` (the default, matching an untargeted
            call), or a module name such as ``'voltage_out'``

        Answers ``True`` when the answer is not known -- an older stimpack that advertises
        nothing, or a target that cannot enumerate itself -- so adopting this is safe: behaviour is
        unchanged until there is something real to report. All three built-in targets do enumerate,
        so in practice the answer is real.

        Calling a function the rig does not have is not fatal -- it is reported as a warning and
        the run continues -- so this is for protocols that want to skip the call rather than let it
        be dropped.
        """
        if self.available_server_functions is None:
            return True
        names = self.available_server_functions.get(target)
        if names is None:
            return True
        return function_name in names

    def adjust_center(self, relative_center):
        """
        Convert a center given relative to the screen center into absolute coordinates.

        Protocols are usually written in relative terms so the same protocol works on rigs whose
        screens are centered differently; ``screen_center`` comes from the rig config.
        """
        absolute_center = [sum(x) for x in zip(relative_center, self.screen_center)]
        return absolute_center

    @property
    def run_parameters(self):
        """The run's parameters, with any pre-0.3 keys renamed.

        A property rather than a plain attribute so that the rename catches every assignment. The
        usual labpack protocol sets this itself::

            def __init__(self, cfg):
                super().__init__(cfg)
                self.run_parameters = self.get_run_parameter_defaults()

        -- which never passes through stimpack's own code, so normalising there would have missed
        a protocol declaring num_epochs in 75 protocols of one labpack alone.
        """
        try:
            return self._run_parameters
        except AttributeError:
            self._run_parameters = {}
            return self._run_parameters

    @run_parameters.setter
    def run_parameters(self, value):
        self._run_parameters = normalize_run_parameters(value)

    @calls_legacy_override('get_epoch_parameters')
    def get_trial_parameters(self):
        """ Inherit / overwrite me in the child subclass"""
        self.trial_protocol_parameters = {}
        self.trial_stim_parameters = {}

        # Get protocol parameters for this trial
        self.trial_protocol_parameters = self.select_trial_protocol_parameters(
                                                all_combinations=self.run_parameters.get('all_combinations', True), 
                                                randomize_order =self.run_parameters.get('randomize_order', False))

    def get_run_parameter_defaults(self):
        """ Overwrite me in the child subclass"""
        return {}

    def get_protocol_parameter_defaults(self):
        """ Overwrite me in the child subclass"""
        return {}

    def load_parameter_presets(self):
        """
        Load this protocol's saved parameter presets from the labpack's preset directory.

        Presets live in ``<parameter_presets_dir>/<ProtocolName>.yaml``. A protocol with no
        preset file simply has none.
        """
        fname = os.path.join(self.parameter_preset_directory, self.__class__.__name__) + '.yaml'
        if os.path.isfile(fname):
            with open(fname, 'r') as ymlfile:
                # Refuse arbitrary-code YAML while still reconstructing the !!python/tuple values presets use.
                self.parameter_presets = config_tools.safe_load_yaml_with_tuples(ymlfile)
        else:
            self.parameter_presets = {}

    def update_parameter_presets(self, name):
        """
        Save the current run and protocol parameters as a named preset, and write it to disk.

        Re-saving under an existing name replaces it.
        """
        self.load_parameter_presets()
        new_preset = {'run_parameters': self.run_parameters,
                      'protocol_parameters': self.protocol_parameters}
        self.parameter_presets[name] = new_preset
        with open(os.path.join(self.parameter_preset_directory, self.__class__.__name__ + '.yaml'), 'w+') as ymlfile:
            # The dumper that matches load_parameter_presets' loader: plain YAML plus
            # !!python/tuple, and an error on anything else rather than a file we cannot read back.
            config_tools.safe_dump_yaml_with_tuples(
                self.parameter_presets, ymlfile, default_flow_style=False, sort_keys=False)

    def select_protocol_preset(self, name=DEFAULT_PRESET_NAME):
        '''
        Parameters that are not present in the preset will use the current protocol's default values.
        '''

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

        # If loco is available, add/set "do_loco" boolean to run parameters
        if self.loco_available:
            self.run_parameters['do_loco'] = False

        # If name is the default entry or is not in parameter_presets, just use the current
        # protocol's defaults
        if name == DEFAULT_PRESET_NAME:
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
        """Record that an trial finished. Drives which precomputed parameters are used next."""
        self.num_trials_completed += 1
        
    def precompute_trial_parameters(self, refresh=False):
        """
        Precompute trial parameters for all trials in advance
        Can prevent slowdowns during series loop and assists with estimating run time
        """
        if refresh:
            self.precomputed_trial_parameters = {}

        if len(self.precomputed_trial_parameters) == 0:
            precomputed_epoch_stim_parameters = []
            precomputed_epoch_protocol_parameters = []
            for e in range(int(self.run_parameters['num_trials'])):
                self.num_trials_completed = e
                self.get_trial_parameters()
                self.check_required_trial_protocol_parameters()
                precomputed_epoch_stim_parameters.append(self.trial_stim_parameters)
                precomputed_epoch_protocol_parameters.append(self.trial_protocol_parameters)
            self.precomputed_trial_parameters = {'stim': precomputed_epoch_stim_parameters,
                                                'protocol': precomputed_epoch_protocol_parameters}
            self.num_trials_completed = 0

    def load_precomputed_trial_parameters(self):
        """Take this trial's parameters from the set computed by :meth:`precompute_trial_parameters`."""
        self.trial_stim_parameters = self.precomputed_trial_parameters['stim'][self.num_trials_completed]
        self.trial_protocol_parameters = self.precomputed_trial_parameters['protocol'][self.num_trials_completed]

    def _estimate_run_time(self):
        '''
        If pre_time, stim_time, and tail_time are specified in the protocol parameters, this method will estimate the total run time.
        '''
        epoch_protocol_params = self.precomputed_trial_parameters['protocol']
        self.est_run_time = np.sum([p.get('pre_time', 0) + p.get('stim_time', 0) + p.get('tail_time', 0) for p in epoch_protocol_params]) + \
                            self.run_parameters.get('pre_run_time', 0) + self.run_parameters.get('post_run_time', 0)

    def process_input_parameters(self):
        """
        Process input parameters and set persistent parameters prior to series loop
        Overwrite me in the child subclass as needed
        """
        self.persistent_parameters['variable_protocol_parameter_names'] = [k for k,v in self.protocol_parameters.items() if isinstance(v, list) and len(v) > 1]

    def check_required_run_parameters(self):
        """
        required_run_parameters: list of tuples (parameter_name, parameter_dtype)
            parameter is cast to parameter_dtype; if no cast is needed, use None
        """
        required_run_parameters = [('num_trials', int), ('idle_color', None)]
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
    
    def check_required_trial_protocol_parameters(self):
        """
        required_run_parameters: list of tuples (parameter_name, parameter_dtype)
            parameter is cast to parameter_dtype; if no cast is needed, use None
        """
        required_protocol_parameters = [('pre_time', float), ('stim_time', float), ('tail_time', float)]
        
        for p, dtype in required_protocol_parameters:
            if p not in self.trial_protocol_parameters:
                raise ValueError(f'Trial protocol parameter {p} is required but not found in {self.trial_protocol_parameters}')
            else:
                if dtype is not None:
                    try:
                        self.trial_protocol_parameters[p] = dtype(self.trial_protocol_parameters[p])
                    except:
                        raise ValueError(f'Trial protocol parameter {p} could not be cast to {dtype}')

    def prepare_run(self, manager:MySocketClient, recompute_epoch_parameters=True):
        """
        recompute_epoch_parameters: bool
            If True, precompute trial parameters even if they have been computed already
            If False, do not recompute trial parameters if they have been computed already
        """
        self.manager = manager      # so sleep() can drain the queue and be interrupted
        self.num_trials_completed = 0
        self.persistent_parameters = {}
        self.trial_protocol_parameters = {}

        # Pick up what the server said it can do, so has_module() is usable from here on -- including
        # inside precompute_trial_parameters below. Read through __dict__: only a client tracks this,
        # and a plain attribute access on another transceiver would return an RPC stub via
        # __getattr__ rather than falling back.
        if manager is not None:
            self.available_modules = vars(manager).get('available_modules')
            self.available_server_functions = vars(manager).get('available_server_functions')

        # Process input parameters and set persistent parameters prior to series loop
        self.process_input_parameters()

        # Check that all required run parameters are set
        self.check_required_run_parameters()
        
        # Precompute trial parameters
        self.precompute_trial_parameters(refresh=recompute_epoch_parameters)

        # Estimate run time
        self._estimate_run_time()

        # If manager exists, set visual_stim background to idle_color
        if manager is not None:
            manager.target('visual').set_idle_background(get_rgba(self.run_parameters.get('idle_color', 0)))

    def on_run_start(self, manager:MySocketClient, multicall:MyMultiCall|None=None):
        """
        Method that is called at the beginning of each run. Does not itself start the run.
        Can be overwritten in the child subclass with super().on_run_start(manager) to add additional functionality.
        """
        if multicall is None:
            multicall = MyMultiCall(manager)

        # If self.use_server_side_state_dependent_control is True, signal to the server that custom closed-loop control is being used
        # We currently assume that the protocol module is in the labpack and that its path is specified in the config file as relative to the labpack
        if self.use_server_side_state_dependent_control:
            protocol_module_file = sys.modules[self.__module__].__file__
            if protocol_module_file is None:
                raise ValueError(f'Protocol module {self.__module__} has no __file__ attribute. Cannot determine protocol path.')
            protocol_path = os.path.abspath(protocol_module_file)
            if protocol_path.startswith(config_tools.get_labpack_directory()):
                protocol_path = os.path.relpath(protocol_path, config_tools.get_labpack_directory())
            elif protocol_path.startswith(ROOT_DIR):
                protocol_path = None # Stimpack example protocol
            else:
                raise ValueError(f'Protocol path {protocol_path} is not in the labpack directory or the stimpack directory.')
            
            multicall.target('root').load_server_side_state_dependent_control(
                protocol_module_path = protocol_path,
                protocol_name = self.__class__.__name__
            )
        
        multicall()

        # If run_parameters['pre_run_time'] exists, sleep for that time
        if 'pre_run_time' in self.run_parameters:
            pre_run_time = self.run_parameters['pre_run_time']
            if isinstance(pre_run_time, (int, float)):
                if pre_run_time > 0:
                    sleep(pre_run_time)
            else:
                raise ValueError(f'Run parameter pre_run_time must be an int or float, not {type(pre_run_time)}.')

        # Reset the number of trials completed
        self.num_trials_completed = 0

    def load_stimuli(self, manager:MySocketClient, multicall:MyMultiCall|None=None):
        """
        Send this trial's stimuli to the server, ready to start.

        Loads the background first, then each stimulus in ``trial_stim_parameters``. Batched
        through a :class:`~stimpack.rpc.multicall.MyMultiCall` so they arrive together; pass your
        own to add further calls to the same batch.
        """
        if multicall is None:
            multicall = MyMultiCall(manager)

        bg = get_rgba(self.run_parameters.get('idle_color', 0))
        multicall.target('visual').set_idle_background(bg)
        multicall.target('visual').load_stim('ConstantBackground', color=bg, hold=True)

        if isinstance(self.trial_stim_parameters, list):
            for ep in self.trial_stim_parameters:
                if ep is not None:
                    multicall.target('visual').load_stim(**ep.copy(), hold=True)
        else:
            if self.trial_stim_parameters is not None:
                multicall.target('visual').load_stim(**self.trial_stim_parameters.copy(), hold=True)

        multicall()

    def start_stimuli(self, manager:MySocketClient, append_stim_frames=False, print_profile=True, multicall:MyMultiCall|None=None):
        """
        Run one trial: start the stimulus, wait out its timing, then stop it.

        Handles the pre / stimulus / tail structure, closed-loop locomotion if the protocol asks
        for it, and the corner square used for photodiode timing.

        :param append_stim_frames: keep rendered frames on the server for later retrieval
        :param print_profile: print the trial's frame-time distribution when it ends
        :param multicall: batch to add the start calls to, rather than sending them alone
        """
        # locomotion setting variables
        do_loco = self.run_parameters.get('do_loco', False)
        do_loco_closed_loop = do_loco and self.trial_protocol_parameters.get('loco_pos_closed_loop', False)
        save_pos_history = do_loco_closed_loop and self.save_metadata_flag
        
        ### pre time
        self.sleep(self.trial_protocol_parameters['pre_time'])
        
        if multicall is None:
            multicall = MyMultiCall(manager)

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
        self.sleep(self.trial_protocol_parameters['stim_time'])

        ### tail time
        multicall = MyMultiCall(manager)
        multicall.target('all').stop_stim(print_profile=print_profile)
        multicall.target('visual').corner_square_toggle_stop()
        multicall.target('visual').corner_square_off()

        # locomotion / closed loop
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_stop_closed_loop()
        if save_pos_history:
            multicall.target('all').save_pos_history_to_file(epoch_id=f'{self.num_trials_completed:03d}')

        multicall()

        self.sleep(self.trial_protocol_parameters['tail_time'])

    def on_run_finish(self, manager:MySocketClient, multicall:MyMultiCall|None=None):
        """
        Method that is called at the end of each run, either when the run is completed or when the run is stopped.
        Fill in if you want to do something at the end of each run.
        Overwrite me in the child subclass.
        """

        # If run_parameters['post_run_time'] exists, sleep for that time
        if 'post_run_time' in self.run_parameters:
            post_run_time = self.run_parameters['post_run_time']
            if isinstance(post_run_time, (int, float)):
                if post_run_time > 0:
                    sleep(post_run_time)
            else:
                raise ValueError(f'Run parameter post_run_time must be an int or float, not {type(post_run_time)}.')

        if multicall is None:
            multicall = MyMultiCall(manager)

        # If self.use_server_side_state_dependent_control is True, signal to the server that custom closed-loop control is no longer being used
        if self.use_server_side_state_dependent_control:
            multicall.target('root').unload_server_side_state_dependent_control()
        
        multicall()
        
    def sleep(self, duration, process_server_requests=True):
        """
        Wait, while staying responsive to the client.

        Used for an trial's pre / stimulus / tail intervals in place of ``time.sleep``, which
        cannot be interrupted: with a bare sleep, pressing Stop is not noticed until the trial
        ends, so stopping a 240-second run means watching it finish. The same delay applies to an
        error the server reports mid-trial.

        This drains the client's queue as it waits and returns early when
        :meth:`stop_trial` is called -- by the Stop button, or by the client when the server
        reports an error.

        :param duration: seconds to wait
        :param process_server_requests: set False for a plain, uninterruptible sleep -- for a
            protocol with no manager, or a wait that must not be cut short
        """
        if not process_server_requests or self.manager is None:
            # Once per protocol, not once per wait: a protocol driven without a client -- the
            # labpack checker does this -- would otherwise say it three times an trial.
            if process_server_requests and not self._warned_uninterruptible_sleep:
                self._warned_uninterruptible_sleep = True
                warnings.warn('Protocol: no manager to process the queue during sleep, so waits '
                              'in this run cannot be interrupted.', RuntimeWarning)
            time.sleep(duration)
            return

        self.stop_sleep_flag = False
        end_time = time.time() + duration
        while time.time() < end_time:
            self.manager.process_queue()
            if self.stop_sleep_flag:
                self.stop_sleep_flag = False
                return
            # Yield rather than spin. Without this the wait pegs a core for the whole trial, on a
            # client that may also be running the closed-loop locomotion updates. A step this
            # small keeps the response to Stop well inside one frame at 120 Hz.
            time.sleep(min(SLEEP_POLL_INTERVAL, max(0.0, end_time - time.time())))

    def stop_trial(self):
        """
        Cut the current :meth:`sleep` short, ending the trial's remaining wait.

        The run itself continues unless the caller also asks for it to stop -- see
        BaseClient.stop_run, which does both.
        """
        self.stop_sleep_flag = True

    def get_parameter_sequence(self, parameter_list, all_combinations=True, randomize_order=False):
        """
        Expand a protocol parameter into the sequence of values presented across a run.

        :param parameter_list: one of

            * a list or array of values -- used as the sequence directly
            * a single value (int, float, ...) -- a sequence of length one
            * a tuple of lists, one list per parameter, combined according to ``all_combinations``

        :param all_combinations: for a tuple of lists, ``True`` takes every combination of one
            value from each list; ``False`` keeps the lists associated element by element, so
            ``([1, 2], ['a', 'b'])`` yields ``(1, 'a')`` and ``(2, 'b')`` rather than all four.
        :param randomize_order: shuffle the sequence at the start of each pass through it, so
            every value is still presented equally often.
        :return: the sequence of parameter values for one pass.
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
                parameter_sequence = np.array(parameter_list_new, dtype=object).T

        else: # user probably entered a single value (int or float), convert to list
            parameter_sequence = [parameter_list]

        # Get sequence order
        num_epochs_in_sequence = len(parameter_sequence)
        num_epoch_sequences = math.ceil(self.run_parameters['num_trials'] / num_epochs_in_sequence)
        
        # index in parameter_sequence for each trial
        if randomize_order:
            parameter_sequence_epoch_inds = np.concatenate([np.random.permutation(num_epochs_in_sequence) for _ in range(num_epoch_sequences)])[:self.run_parameters['num_trials']]
        else:
            parameter_sequence_epoch_inds = np.arange(self.run_parameters['num_trials']) % num_epochs_in_sequence

        self.persistent_parameters['protocol_parameter_sequence'] = parameter_sequence
        self.persistent_parameters['protocol_parameter_sequence_epoch_inds'] = parameter_sequence_epoch_inds
    
    def select_trial_protocol_parameters(self, all_combinations=True, randomize_order=False):
        """
        Pick this trial's value for every protocol parameter.

        Called once per trial. Sequences are built on the first trial of a run and stored in
        ``persistent_parameters``, so the order is consistent across the run rather than
        re-drawn each time.

        :param all_combinations: ``True`` takes every combination of one value from each
            parameter list; ``False`` keeps the lists associated element by element.
        :param randomize_order: shuffle each sequence at the start of every pass through it.
        :return: dictionary of protocol parameter names to the value chosen for this trial.
        """

        # new run: initialize parameter sequences if not already done
        if self.num_trials_completed == 0 and 'protocol_parameter_sequence' not in self.persistent_parameters:
            self.get_parameter_sequence(tuple(self.protocol_parameters.values()), all_combinations=all_combinations, randomize_order=randomize_order)

        # get current trial parameters
        parameter_sequence = self.persistent_parameters['protocol_parameter_sequence']
        parameter_sequence_epoch_inds = self.persistent_parameters['protocol_parameter_sequence_epoch_inds']

        epoch_protocol_parameter_values = parameter_sequence[parameter_sequence_epoch_inds[self.num_trials_completed]]
        trial_protocol_parameters = {parameter_name: epoch_protocol_parameter_values[i] for i, parameter_name in enumerate(self.protocol_parameters.keys())}

        return trial_protocol_parameters
    


#%%

# The pre-0.3 spelling, kept working: an trial is now a trial and an series a series.
# See stimpack.experiment.deprecated_names.
add_deprecated_aliases(
    BaseProtocol,
    methods=[
        ('get_epoch_parameters', 'get_trial_parameters'),
        ('precompute_epoch_parameters', 'precompute_trial_parameters'),
        ('load_precomputed_epoch_parameters', 'load_precomputed_trial_parameters'),
        ('select_epoch_protocol_parameters', 'select_trial_protocol_parameters'),
        ('check_required_epoch_protocol_parameters', 'check_required_trial_protocol_parameters'),
        ('stop_epoch', 'stop_trial'),
    ],
    attributes=[
        ('epoch_protocol_parameters', 'trial_protocol_parameters'),
        ('epoch_stim_parameters', 'trial_stim_parameters'),
        ('num_epochs_completed', 'num_trials_completed'),
        ('precomputed_epoch_parameters', 'precomputed_trial_parameters'),
        ('use_precomputed_epoch_parameters', 'use_precomputed_trial_parameters'),
        ('all_epoch_stim_parameter_keys', 'all_trial_stim_parameter_keys'),
        ('required_epoch_protocol_parameters', 'required_trial_protocol_parameters'),
    ],
)

class SharedPixMapProtocol(BaseProtocol):
    def __init__(self, cfg):
        super().__init__(cfg)

        self.use_precomputed_trial_parameters = True  # Bool, whether or not to precompute trial parameters

        # Shared pixmap stim parameters
        self.epoch_shared_pixmap_stim_parameters = None

    def precompute_trial_parameters(self, refresh=False):
        if refresh:
            self.precomputed_trial_parameters = {}

        if len(self.precomputed_trial_parameters) == 0:
            precomputed_epoch_stim_parameters = []
            precomputed_epoch_shared_pixmap_stim_parameters = []
            precomputed_epoch_protocol_parameters = []
            for e in range(int(self.run_parameters['num_trials'])):
                self.num_trials_completed = e
                self.get_trial_parameters()
                self.check_required_trial_protocol_parameters()
                precomputed_epoch_stim_parameters.append(self.trial_stim_parameters)
                precomputed_epoch_protocol_parameters.append(self.trial_protocol_parameters)
                precomputed_epoch_shared_pixmap_stim_parameters.append(self.epoch_shared_pixmap_stim_parameters)
            self.precomputed_trial_parameters = {'stim': precomputed_epoch_stim_parameters,
                                                'protocol': precomputed_epoch_protocol_parameters,
                                                'pixmap': precomputed_epoch_shared_pixmap_stim_parameters}
            self.num_trials_completed = 0

    def load_precomputed_trial_parameters(self):
        self.trial_stim_parameters = self.precomputed_trial_parameters['stim'][self.num_trials_completed]
        self.epoch_shared_pixmap_stim_parameters = self.precomputed_trial_parameters['pixmap'][self.num_trials_completed]
        self.trial_protocol_parameters = self.precomputed_trial_parameters['protocol'][self.num_trials_completed]

    def load_stimuli(self, manager:MySocketClient, multicall:MyMultiCall|None=None):
        if multicall is None:
            multicall = MyMultiCall(manager)

        # Load shared pixmap stimuli if defined # TODO This shouldn't really be a list
        if self.epoch_shared_pixmap_stim_parameters is not None:
            if not isinstance(self.epoch_shared_pixmap_stim_parameters, list):
                self.epoch_shared_pixmap_stim_parameters = [self.epoch_shared_pixmap_stim_parameters]
            for ep in self.epoch_shared_pixmap_stim_parameters:
                multicall.target('visual').load_shared_pixmap_stim(**ep.copy())

        bg = self.run_parameters.get('idle_color')
        multicall.target('visual').load_stim('ConstantBackground', color=get_rgba(bg), hold=True)

        if isinstance(self.trial_stim_parameters, list):
            for ep in self.trial_stim_parameters:
                multicall.target('visual').load_stim(**ep.copy(), hold=True)
        else:
            multicall.target('visual').load_stim(**self.trial_stim_parameters.copy(), hold=True)

        multicall()

    def start_stimuli(self, manager:MySocketClient, append_stim_frames=False, print_profile=True, multicall:MyMultiCall|None=None):

        # locomotion setting variables
        do_loco = self.run_parameters.get('do_loco', False)
        do_loco_closed_loop = do_loco and self.trial_protocol_parameters.get('loco_pos_closed_loop', False)
        save_pos_history = do_loco_closed_loop and self.save_metadata_flag
        
        ### pre time
        self.sleep(self.trial_protocol_parameters['pre_time'])
        
        if multicall is None:
            multicall = MyMultiCall(manager)

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
        self.sleep(self.trial_protocol_parameters['stim_time'])

        ### tail time
        multicall = MyMultiCall(manager)
        multicall.target('all').stop_stim(print_profile=print_profile)
        multicall.target('visual').corner_square_toggle_stop()
        multicall.target('visual').corner_square_off()

        # locomotion / closed loop
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_stop_closed_loop()
        if save_pos_history:
            multicall.target('all').save_pos_history_to_file(epoch_id=f'{self.num_trials_completed:03d}')

        # shared pixmap clear
        if self.epoch_shared_pixmap_stim_parameters is not None:
            multicall.target('visual').clear_shared_pixmap_stim()

        multicall()

        self.sleep(self.trial_protocol_parameters['tail_time'])

    def on_run_finish(self, manager:MySocketClient, multicall:MyMultiCall|None=None):
        """
        Method that is called at the end of each run, either when the run is completed or when the run is stopped.
        Fill in if you want to do something at the end of each run.
        Overwrite me in the child subclass.
        """
        pass
