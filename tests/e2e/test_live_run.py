"""End-to-end tests against a LIVE server with real screen subprocesses.

Nothing is mocked: commands cross a real socket, a real screen subprocess renders with a real GL
context, and a full experiment series is run and written to HDF5. This is the closest automated
equivalent of sitting at the rig and clicking Record.
"""
import time

import h5py
import pytest

from conftest import wait_until          # tests/e2e/conftest.py (pytest pythonpath)
from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.e2e


class LiveProtocol(BaseProtocol):
    """A real 2-epoch protocol using a real built-in stimulus, with short timings."""
    stim_name = 'MovingSpot'
    on_epoch = None

    def get_run_parameter_defaults(self):
        return {'num_epochs': 2, 'idle_color': 0.5, 'do_loco': False}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.05, 'stim_time': 0.15, 'tail_time': 0.05, 'radius': [10.0, 20.0]}

    def get_epoch_parameters(self):
        super().get_epoch_parameters()
        self.epoch_stim_parameters = {'name': self.stim_name,
                                      'radius': self.epoch_protocol_parameters['radius'],
                                      'sphere_radius': 1, 'color': [1, 1, 1, 1],
                                      'theta': 0, 'phi': 0}

    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
        if self.on_epoch is not None:
            self.on_epoch(self)
        super().start_stimuli(manager, append_stim_frames=append_stim_frames,
                              print_profile=print_profile, multicall=multicall)


# --- the rendering stack ------------------------------------------------------------------------

def test_live_server_loads_and_runs_a_stimulus(live_manager):
    """Drive the screen subprocess directly over the real socket."""
    live_manager.target('visual').set_idle_background(0.5)
    live_manager.target('visual').load_stim(name='MovingSpot', radius=15, sphere_radius=1,
                                            color=[1, 1, 1, 1], theta=0, phi=0)
    live_manager.target('visual').start_stim()
    time.sleep(0.3)                                  # let it render some frames
    live_manager.target('visual').stop_stim()
    time.sleep(0.1)

    # The link is still healthy: the screen subprocess did not crash on any of that.
    assert live_manager.connection_broken is False


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

    assert protocol.num_epochs_completed == 2

    path = f'{live_data.data_directory}/{live_data.experiment_file_name}.hdf5'
    with h5py.File(path, 'r') as f:
        series = f['/Subjects/subj_e2e/epoch_runs/series_001']
        assert series.attrs['run_status'] == 'completed'
        assert series.attrs['num_epochs_completed'] == 2
        assert series.attrs['protocol_ID'] == 'LiveProtocol'
        epochs = list(series['epochs'].keys())
        assert len(epochs) == 2
        # the per-epoch stimulus parameters really made it into the file
        assert series['epochs'][epochs[0]].attrs['name'] == 'MovingSpot'

    assert live_client.server_error is None          # no server-side errors during the run


def test_stopping_a_live_run_halts_it(live_client, live_data):
    """Stop mid-series against the live server, exactly as the GUI's Stop button does."""
    protocol = LiveProtocol(cfg={})
    protocol.on_epoch = lambda p: live_client.stop_run() if p.num_epochs_completed == 0 else None

    live_client.start_run(protocol, live_data, save_metadata_flag=True)

    assert protocol.num_epochs_completed == 1
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
    protocol.run_parameters['num_epochs'] = 4
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
    assert protocol.num_epochs_completed < 2         # did not run the whole series
