"""End-to-end tests against a LIVE server with real screen subprocesses.

Nothing is mocked: commands cross a real socket, a real screen subprocess renders with a real GL
context, and a full experiment series is run and written to HDF5. This is the closest automated
equivalent of sitting at the rig and clicking Record.
"""
import time

import h5py
import pytest

from helpers import wait_until          # tests/helpers.py (tests/ is on pytest's pythonpath)
from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.e2e


class LiveProtocol(BaseProtocol):
    """A real 2-epoch protocol using a real built-in stimulus, with short timings."""
    stim_name = 'MovingSpot'
    on_trial = None

    def get_run_parameter_defaults(self):
        return {'num_trials': 2, 'idle_color': 0.5, 'do_loco': False}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.05, 'stim_time': 0.15, 'tail_time': 0.05, 'radius': [10.0, 20.0]}

    def get_trial_parameters(self):
        super().get_trial_parameters()
        self.trial_stim_parameters = {'name': self.stim_name,
                                      'radius': self.trial_protocol_parameters['radius'],
                                      'sphere_radius': 1, 'color': [1, 1, 1, 1],
                                      'theta': 0, 'phi': 0}

    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
        if self.on_trial is not None:
            self.on_trial(self)
        super().start_stimuli(manager, append_stim_frames=append_stim_frames,
                              print_profile=print_profile, multicall=multicall)


# --- the rendering stack ------------------------------------------------------------------------

def frame_count(live_client, live_manager, timeout=15):
    """Ask the screen how many frames it has rendered, and wait for the answer to come back."""
    before = len(live_client.server_messages)
    live_manager.target('visual').report_frame_count()

    def answered():
        live_manager.process_queue()
        return any('frame_count=' in text for _, text in live_client.server_messages[before:])

    assert wait_until(answered, timeout=timeout), 'the screen never reported a frame count'
    reported = [text for _, text in live_client.server_messages[before:] if 'frame_count=' in text]
    return int(reported[-1].split('frame_count=')[1].split()[0])


def test_live_server_loads_and_runs_a_stimulus(live_client, live_manager):
    """Drive the screen subprocess directly over the real socket, and check it really rendered.

    Asserting only that the link survived is not enough: paintGL is what drains the RPC queue, so a
    screen whose render loop never starts accepts every command and silently does nothing -- and
    this test passed against exactly that when the GL context failed to come up under PRIME
    offload. The frame count is what distinguishes "ran the stimulus" from "accepted the commands".
    """
    frames_before = frame_count(live_client, live_manager)

    live_manager.target('visual').set_idle_background(0.5)
    live_manager.target('visual').load_stim(name='MovingSpot', radius=15, sphere_radius=1,
                                            color=[1, 1, 1, 1], theta=0, phi=0)
    live_manager.target('visual').start_stim()
    time.sleep(0.3)                                  # let it render some frames
    live_manager.target('visual').stop_stim()
    time.sleep(0.1)

    frames_after = frame_count(live_client, live_manager)
    assert frames_after > frames_before, \
        f'the screen drew no frames while the stimulus ran ({frames_before} -> {frames_after})'

    # The link is still healthy: the screen subprocess did not crash on any of that.
    assert live_manager.connection_broken is False
    assert live_client.server_error is None


def test_live_server_survives_a_bad_stimulus_and_reports_it(live_client, live_manager):
    """A nonexistent stim class must not kill the screen subprocess, and the error must come back.

    This is the whole Tier-2 chain for real: screen subprocess -> VisualStimServer -> BaseServer ->
    client, over real sockets and OS processes.
    """
    live_manager.target('visual').load_stim(name='NoSuchStimulus_E2E')

    def error_arrived():
        live_manager.process_queue()          # BaseClient does this each run-loop iteration
        return live_client.server_error is not None

    assert wait_until(error_arrived, timeout=15), \
        "the server never reported the bad-stimulus error back to the client"
    assert 'NoSuchStimulus_E2E' in live_client.server_error
    assert '[screen]' in live_client.server_error   # bubbled up from the screen subprocess

    # ...and the server is still alive and usable afterwards (the error was isolated)
    live_manager.target('visual').load_stim(name='MovingSpot', radius=10, sphere_radius=1,
                                            color=[1, 1, 1, 1], theta=0, phi=0)
    live_manager.target('visual').start_stim()
    time.sleep(0.2)
    live_manager.target('visual').stop_stim()
    assert live_manager.connection_broken is False


# --- a full experiment series -------------------------------------------------------------------

def test_full_experiment_series_end_to_end(live_client, live_data):
    """A complete Record run: real client -> real socket -> real server -> real screen; real HDF5."""
    protocol = LiveProtocol(cfg={})
    live_client.start_run(protocol, live_data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 2

    path = f'{live_data.data_directory}/{live_data.experiment_file_name}.hdf5'
    with h5py.File(path, 'r') as f:
        series = f['/Subjects/subj_e2e/epoch_runs/series_001']
        assert series.attrs['run_status'] == 'completed'
        assert series.attrs['num_trials_completed'] == 2
        assert series.attrs['protocol_ID'] == 'LiveProtocol'
        epochs = list(series['epochs'].keys())
        assert len(epochs) == 2
        # the per-epoch stimulus parameters really made it into the file
        assert series['epochs'][epochs[0]].attrs['name'] == 'MovingSpot'

    assert live_client.server_error is None          # no server-side errors during the run


def test_stopping_a_live_run_halts_it(live_client, live_data):
    """Stop mid-series against the live server, exactly as the GUI's Stop button does."""
    protocol = LiveProtocol(cfg={})
    protocol.on_trial = lambda p: live_client.stop_run() if p.num_trials_completed == 0 else None

    live_client.start_run(protocol, live_data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 1
    path = f'{live_data.data_directory}/{live_data.experiment_file_name}.hdf5'
    with h5py.File(path, 'r') as f:
        series = f['/Subjects/subj_e2e/epoch_runs/series_001']
        assert series.attrs['run_status'] == 'stopped'


def test_live_run_aborts_when_the_protocol_asks_for_a_bad_stimulus(live_client, live_data):
    """A protocol naming a nonexistent stimulus (the ServerErrorDemo scenario) aborts the run."""
    protocol = LiveProtocol(cfg={})
    protocol.stim_name = 'NoSuchStimulus_E2E_Run'
    # More epochs = more between-epoch checkpoints at which the error can be noticed. The run aborts
    # at the first one, so this doesn't slow the passing case; it only removes the race.
    protocol.run_parameters['num_trials'] = 4
    # The error has to cross three processes (screen -> VisualStimServer -> BaseServer -> client)
    # before the client's next between-epoch check. Give epoch 0 a comfortably longer duration than
    # that propagation takes, so the assertion isn't racing it.
    protocol.protocol_parameters = {'pre_time': 1.0, 'stim_time': 1.0, 'tail_time': 0.1,
                                    'radius': [10.0, 20.0]}

    # Assert on the recorded outcome rather than on warning emission: Python's per-location warning
    # registry makes "was a warning raised" flaky across a shared process, while run_status is the
    # behavior actually under test.
    live_client.start_run(protocol, live_data, save_metadata_flag=True)

    path = f'{live_data.data_directory}/{live_data.experiment_file_name}.hdf5'
    with h5py.File(path, 'r') as f:
        series = f['/Subjects/subj_e2e/epoch_runs/series_001']
        assert series.attrs['run_status'] == 'error'
        assert 'abort_reason' in series.attrs
    assert protocol.num_trials_completed < 2         # did not run the whole series


def test_root_function_names_match_a_live_server(live_server):
    """ROOT_FUNCTION_NAMES is what the labpack checker uses to tell a real untargeted call from one
    that lands nowhere. If it drifts from what the server actually registers, the check either
    misses a genuine bug or invents one. Assert against a real server rather than trusting a list.
    """
    from stimpack.experiment.server import ROOT_FUNCTION_NAMES

    assert set(live_server.functions_on_root) == set(ROOT_FUNCTION_NAMES)






def test_a_live_server_can_end_an_epoch_early(live_server, live_manager, live_client):
    """The whole path for real: a state update reaches the server, the labpack's closed-loop
    function decides the trial is over, and the client's epoch wait returns early.

    Everything here is the real object over a real socket -- only the tracker is stood in for, by
    calling set_subject_state directly as a locomotion manager would.
    """
    ended = []

    def control(server, subject_state, state_update):
        # state_update is what just arrived; subject_state is what it was before. Testing the
        # latter alone would fire one update late -- or never, on a single update.
        if state_update.get('x', subject_state.get('x', 0)) > 0.5:
            server.end_trial(reason='reached_goal')
            ended.append(True)
        return state_update

    live_server.loaded_custom_state_dependent_control = control
    live_manager.register_function(live_client.stop_trial, name='stop_trial')

    class GoalProtocol(BaseProtocol):
        def get_run_parameter_defaults(self):
            return {'num_trials': 1, 'idle_color': 0.5, 'do_loco': False}
        def get_protocol_parameter_defaults(self):
            return {'pre_time': 0.0, 'stim_time': 30.0, 'tail_time': 0.0}
        def get_trial_parameters(self):
            super().get_trial_parameters()
            self.trial_stim_parameters = {'name': 'MovingSpot', 'radius': 10, 'sphere_radius': 1,
                                          'color': [1, 1, 1, 1], 'theta': 0, 'phi': 0}
        def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
            # the "animal" reaches the goal 0.3 s in
            threading.Timer(0.3, lambda: live_server.set_subject_state({'x': 1.0})).start()
            super().start_stimuli(manager, append_stim_frames=append_stim_frames,
                                  print_profile=print_profile, multicall=multicall)

    import threading
    protocol = GoalProtocol(cfg={})

    started = time.monotonic()
    live_client.start_run(protocol, _NullData(), save_metadata_flag=False)
    elapsed = time.monotonic() - started

    assert ended, 'the closed-loop function never saw the state update'
    assert elapsed < 10, f'{elapsed:.1f}s: the 30 s epoch was not cut short'
    assert protocol.num_trials_completed == 1


class _NullData:
    """Enough of a data object for a run that saves nothing."""
    def __getattr__(self, name):
        return lambda *args, **kwargs: None
