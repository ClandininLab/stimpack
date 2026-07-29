#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The client side of an experiment: runs the protocol and writes the data file.

:class:`BaseClient` owns the run loop. For each trial it asks the protocol what to present, sends
the stimulus to the server, waits out the trial, and records what happened. It also decides how a
run ends -- completed, stopped by the user, aborted on a dropped link or a server-reported error,
or failed with an exception -- and stores that outcome alongside the data.

Calls to the server are one-way, so the client cannot tell from a send whether anything happened.
It detects trouble two ways: the server pushes messages back over the same socket
(``report_server_message``), and a broken connection is noticed directly.
"""

import os, sys
import subprocess
import time
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
from stimpack.experiment.deprecated_names import add_deprecated_aliases, _warn_once

# How often the run loop looks up while paused. Nothing is being presented or recorded in that
# state and it is waiting on somebody to press Resume, so this only has to beat human reaction
# time; it is not trial timing (see protocol.SLEEP_POLL_INTERVAL for that, which is 5x tighter
# because it gates stimulus durations).
PAUSE_POLL_INTERVAL = 0.01


class BaseClient():
    def __init__(self, cfg:dict):
        """
        Parameters
        ----------
        cfg : dict
            Configuration dictionary.
        """
        self.stop:bool = False
        # The protocol currently running, so stop_run can cut its trial short rather than let the
        # run finish the one in progress. None between runs.
        self.protocol_object = None
        # Which trial is running, and why the last one ended early (None if it ran its full
        # length). Both are per-trial, reset as each begins.
        self.current_trial_index = None
        self.trial_end_reason = None
        # Pause has two states, and they are not the same thing. `pause` is what the user asked
        # for, set the instant the button is pressed; `paused_since` is when the run loop actually
        # went idle, which cannot happen until the trial in progress finishes. Between the two the
        # run is still stimulating and recording, so a GUI that reports "Paused" straight away is
        # lying about what the rig is doing. See pause_state.
        self.pause:bool = False
        self.paused_since:Optional[float] = None    # monotonic clock, or None if not idle
        self.paused_duration:float = 0.0            # seconds idled so far this run, closed pauses only
        self.cfg:dict = cfg

        # Messages pushed back from the server (drained in the run loop via manager.process_queue()).
        self.server_messages:list = []
        self.server_error:Optional[str] = None      # set when the server reports an error; aborts the run
        self.on_server_message = None               # optional callback(level, text), e.g. a GUI status hook
        self.on_data_error = None                   # optional callback(text) for a failed data write
        self._message_counts:dict = {}              # (level, text) -> times seen; used to deduplicate

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

                # Keep a handle on the server: it lives in THIS process, so nothing else will ever
                # shut it down. Without this it was a local variable, and closing the GUI left its
                # screen subprocesses -- and KeyTrac, which is spawned detached (start_new_session)
                # and so survives even our process group -- running.
                self.local_server = BaseServer(host='127.0.0.1',
                                    port=None,
                                    visual_stim_kwargs=visual_stim_kwargs,
                                    loco_class=loco_class,
                                    loco_kwargs=loco_kwargs,
                                    start_loop=True)
                self.manager = MySocketClient(host=self.local_server.host, port=self.local_server.port)

        # if the trigger device is on the server, set the manager for the trigger device
        if isinstance(self.trigger_device, daq.DAQonServer):
            self.trigger_device.set_manager(self.manager)

        # Let the server push warnings/errors back to us; delivered when we drain the queue (run loop).
        self.manager.register_function(self.report_server_message, name='report_server_message')
        # Lets the server end an trial early -- see BaseServer.end_trial. Registered here rather
        # than on BaseServer's side of the link because the server can only ask; the client is
        # what actually runs the trial.
        self.manager.register_function(self.stop_trial, name='stop_trial')
        # Under its old name too: these are wire names, so a server from before 0.3 -- or a
        # labpack device calling manager.stop_epoch(...) -- still reaches the right method.
        self.manager.register_function(self.stop_trial, name='stop_epoch')

        # The server advertises its modules as soon as it accepts the connection, but that message
        # only takes effect once we drain the queue. Wait briefly for it here so protocols can rely
        # on has_module() everywhere -- including precompute, which runs before the run loop starts
        # draining. Normally this returns on the first pass; the cap only matters against a server
        # that never advertises (an older stimpack), where available_modules stays None and
        # has_module() answers True, i.e. exactly the previous behavior.
        deadline = time.time() + 1.0
        while self.manager.available_modules is None and time.time() < deadline:
            self.manager.process_queue()
            sleep(0.01)

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

    def stop_trial(self, trial_index=None, reason=None, epoch_index=None):
        """
        End the current trial's remaining wait, without stopping the run.

        The protocol's pre / stimulus / tail intervals are interruptible sleeps (see
        BaseProtocol.sleep); this is what interrupts them. Called locally by stop_run, and
        remotely by the server for a trial whose length depends on the animal's behaviour
        (BaseServer.end_trial).

        :param epoch_index: the pre-0.3 name for trial_index. This is a wire signature -- a
            server from before 0.3 stamps its request with epoch_index -- so it is accepted here
            rather than only as a method alias.
        :param trial_index: the trial this was meant for. A request is ignored if that trial has
            already ended -- without this, one sent as an trial was finishing would arrive during
            the next and cut it short, which is close to invisible in the data. None (the local
            Stop button) always applies to whatever is running now.
        :param reason: why it ended early, recorded with the trial.
        """
        # getattr: report_server_message reaches here, and a client may be constructed without
        # going through __init__.
        protocol_object = getattr(self, 'protocol_object', None)
        if protocol_object is None:
            return

        if epoch_index is not None and trial_index is None:
            _warn_once('epoch_index', 'trial_index', 'Argument')
            trial_index = epoch_index

        if trial_index is not None and trial_index != getattr(self, 'current_trial_index', None):
            return          # meant for an trial that has already ended

        self.trial_end_reason = reason
        protocol_object.stop_trial()

    def stop_run(self):
        self.stop = True
        # Cut the trial in progress short as well. Without this, Stop is not acted on until the
        # trial ends -- so stopping a run with long trials meant watching the current one finish,
        # which is no use when the reason for stopping is what is on the screen.
        self.stop_trial()
        QApplication.processEvents()

    def pause_run(self):
        """Ask the run to pause. Takes effect when the trial in progress ends, not immediately."""
        self.pause = True
        QApplication.processEvents()

    def resume_run(self):
        self.pause = False
        QApplication.processEvents()

    @property
    def pause_state(self):
        """'running' | 'pending' | 'paused' -- what to tell the user right now.

        'pending' is the interval between pressing Pause and the run loop reaching the end of the
        trial it was in. Stimuli are still being presented and recorded during it.
        """
        if not self.pause:
            return 'running'
        return 'paused' if self.paused_since is not None else 'pending'

    @property
    def paused_seconds(self):
        """Seconds this run has spent idle, including a pause still in progress.

        Excluded from elapsed time in the GUI: est_run_time is a sum of stimulus durations, so a
        wall-clock elapsed figure stops being comparable to it the moment anyone pauses.
        """
        total = self.paused_duration
        if self.paused_since is not None:
            total += time.monotonic() - self.paused_since
        return total

    def _close_out_pause(self):
        """Fold a pause in progress into the total. Idempotent."""
        if self.paused_since is not None:
            self.paused_duration += time.monotonic() - self.paused_since
            self.paused_since = None

    @property
    def available_modules(self):
        """Modules the server advertised ('visual', 'locomotion', 'voltage_out', ...), or None if it
        never told us (an older server). See BaseProtocol.has_module."""
        return self.manager.available_modules

    def report_server_message(self, level, text):
        """Handle a message pushed back from the server (run via manager.process_queue()).

        level: 'info' | 'warning' | 'error'. An 'error' marks the current run to be aborted.

        Repeats are counted but surfaced only once per run: a per-trial condition would otherwise
        emit the same line hundreds of times, burying anything that matters (and growing
        server_messages without bound).
        """
        if level == 'error':
            self.server_error = text        # always, even on a repeat: this aborts the run
            # End the trial's wait too: the run loop checks server_error between trials, so
            # without this an error reported mid-trial is not acted on until that trial finishes.
            self.stop_trial()

        key = (level, text)
        self._message_counts[key] = self._message_counts.get(key, 0) + 1
        if self._message_counts[key] > 1:
            return                          # already surfaced this exact message during this run

        self.server_messages.append((level, text))
        print(f"[server:{level}] {text}")
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
        self.paused_since = None
        self.paused_duration = 0.0      # pause totals are per run, like the message dedupe below
        self.server_error = None
        self._message_counts = {}       # dedupe is per run, so a recurring issue is reported again
        self.protocol_object = protocol_object
        protocol_object.save_metadata_flag = save_metadata_flag

        # Check run parameters, compute persistent parameters, and precompute trial parameters
        # Do not recompute trial parameters if they have been computed already
        protocol_object.prepare_run(manager=self.manager, recompute_epoch_parameters=False)

        # Set background to idle_color
        self.manager.target('visual').set_idle_background(get_rgba(protocol_object.run_parameters.get('idle_color', 0)))

        if save_metadata_flag:
            data.create_series(protocol_object)
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

        # # # Series loop # # #
        # run_status is recorded on the series group at the end (data.end_series). The try/finally
        # guarantees a clean teardown + a recorded outcome even if the run aborts or raises.
        run_status, run_status_reason = 'completed', None
        try:
            # Drain before on_run_start, not after. prepare_run has already run, so anything it
            # provoked -- a missing root function, a bad stimulus -- is sitting in the queue
            # already. on_run_start actuates hardware (shutters, opto steps, triggers), and a run
            # that is going to abort must not get that far. The loop below re-checks and stops it.
            self.manager.process_queue()
            if self.server_error is None:
                self.manager.print_on_server("Starting run.")
                protocol_object.on_run_start(self.manager)
            while protocol_object.num_trials_completed < protocol_object.run_parameters['num_trials']:
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
                    if self.paused_since is None:
                        # The pause takes effect here, at an trial boundary -- not when the button
                        # was pressed. Record when, so paused_seconds can be excluded from elapsed
                        # time and reported in the data file.
                        self.paused_since = time.monotonic()
                        self.manager.print_on_server('Paused.')
                    # Wait, rather than spin. This branch used to be a bare `pass`, so a paused run
                    # busy-looped at ~2.2 million iterations a second and held a core at 100% for
                    # as long as the pause lasted -- next to the timing-sensitive screen subprocess,
                    # and for exactly the minutes somebody has stepped away from the rig. A pause
                    # waits on a human, so polling at 100 Hz is imperceptibly responsive.
                    sleep(PAUSE_POLL_INTERVAL)
                else: # start trial and advance counter
                    if self.paused_since is not None:
                        self._close_out_pause()
                        self.manager.print_on_server('Resumed.')
                    self.start_trial(protocol_object, data, save_metadata_flag=save_metadata_flag)
        except Exception as e:
            run_status, run_status_reason = 'error', f'{type(e).__name__}: {e}'
            warnings.warn(f"Run aborted by exception:\n{traceback.format_exc()}")
        finally:
            # A run can end while paused -- Stop is checked before the pause branch -- and the
            # elapsed-time display keeps reading paused_seconds after the loop exits.
            self._close_out_pause()

            protocol_object.on_run_finish(self.manager)

            broken = getattr(self.manager, 'connection_broken', False)
            if not broken:
                # Set frame tracker to dark
                self.manager.target('visual').corner_square_toggle_stop()
                self.manager.target('visual').corner_square_off()

            # Stop locomotion device / software
            if protocol_object.loco_available and protocol_object.run_parameters['do_loco']:
                self.stop_loco()

            # Note how often each deduplicated server message actually occurred.
            for (level, text), count in self._message_counts.items():
                if count > 1:
                    print(f"[server:{level}] (occurred {count}x this run) {text}")

            # Record the outcome of this run in the data file.
            #
            # Isolated because this is a finally block: an exception raised here replaces whatever
            # actually went wrong with a failure from the cleanup, and -- since start_run is called
            # on a QThread, where an exception out of run() aborts the process -- takes the GUI
            # down with it. That is exactly what happened when a bad trial write left an NWB file
            # that end_series could not then read: the real error was reported, and then the
            # application core-dumped while trying to record that it had failed.
            if save_metadata_flag:
                try:
                    data.end_series(protocol_object, status=run_status, reason=run_status_reason,
                                       paused_seconds=self.paused_seconds)
                except Exception:
                    # Loudly. Whatever stopped the outcome being written stopped it part-way, so
                    # the file is not what it should be -- and for NWB it may not open at all.
                    # A warning alone leaves that to be discovered at analysis time; the run has
                    # already ended, so nothing else is going to raise about it.
                    message = (f"The run ended '{run_status}', but recording that in the "
                               f"{type(data).__name__} file failed. The file for this series may "
                               f"be incomplete, and may not open.\n\n{traceback.format_exc()}")
                    warnings.warn(message)
                    self.report_data_error(message)

            if not broken:
                self.manager.print_on_server('Run ended.')

            self.protocol_object = None

    def report_data_error(self, text):
        """Surface a failure to write the data file to whoever is driving, not just to the log.

        Separate from report_server_message on purpose: this did not come from the server, and
        reporting it as a server error sends somebody to look at the rig for a problem that is in
        the file. Best-effort, and never raises -- it is called from a finally block.
        """
        if self.on_data_error is None:
            return
        try:
            self.on_data_error(text)
        except Exception:
            warnings.warn(f"on_data_error callback failed:\n{traceback.format_exc()}")

    def start_trial(self, protocol_object:BaseProtocol, data:BaseData, save_metadata_flag:bool=True):
        #  get stimulus parameters for this trial
        if protocol_object.use_precomputed_trial_parameters:
            protocol_object.load_precomputed_trial_parameters()
        else:
            protocol_object.get_trial_parameters()
        
        # Check that all required trial protocol parameters are set
        protocol_object.check_required_trial_protocol_parameters()

        # Tell the server which trial this is, so it can stamp an end_trial request and we can
        # tell a late one from a current one.
        self.current_trial_index = protocol_object.num_trials_completed
        self.trial_end_reason = None
        self.manager.set_current_trial(self.current_trial_index)

        if save_metadata_flag:
            data.create_trial(protocol_object)

        # Send triggering TTL through the DAQ device (if device is set)
        if protocol_object.trigger_on_epoch is True:
            if self.trigger_device is not None:
                print("Triggering acquisition devices.")
                self.trigger_device.send_trigger()

        self.manager.print_on_server(f'Trial {protocol_object.num_trials_completed}')

        # Use the protocol object to send the stimulus to stimpack.visual_stim
        protocol_object.load_stimuli(self.manager)

        protocol_object.start_stimuli(self.manager)

        self.manager.print_on_server('Trial completed.')

        # Nothing is running now, so a late end_trial has nothing to cut short.
        self.current_trial_index = None
        self.manager.set_current_trial(None)

        if save_metadata_flag:
            data.end_trial(protocol_object, reason=self.trial_end_reason)
        
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
        '''
        Shut down whatever server this client started. Called from the GUI's closeEvent.

        Both local-server paths spawn OS subprocesses of their own (one per screen, plus KeyTrac),
        and those do not reliably die with us: KeyTrac is started with start_new_session=True, so it
        is detached from our process group. Closing here is what actually reaps them.
        '''
        # We had started a local server in a separate process; terminate it.
        if 'local_server_process' in self.__dict__:
            print("Closing local server process.")
            self.local_server_process.terminate()
            try:
                self.local_server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                warnings.warn("Local server process did not exit; killing it.")
                self.local_server_process.kill()

        # We had started a local server in THIS process; close it so its modules shut down their own
        # subprocesses. Best-effort: a failure here must not stop the GUI from closing.
        if 'local_server' in self.__dict__:
            print("Closing local server.")
            try:
                self.local_server.close()
            except Exception as e:
                warnings.warn(f"Error closing local server: {type(e).__name__}: {e}")


add_deprecated_aliases(
    BaseClient,
    methods=[('start_epoch', 'start_trial'), ('stop_epoch', 'stop_trial')],
    attributes=[('current_epoch_index', 'current_trial_index'),
                ('epoch_end_reason', 'trial_end_reason')],
)
