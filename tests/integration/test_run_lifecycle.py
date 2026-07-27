"""Integration tests for the epoch-run lifecycle.

Drives the real BaseClient.start_run loop with a real BaseProtocol and a real BaseData (HDF5), using
only a fake RPC link. Covers: normal completion, user stop, pause/resume, abort on a dead server
link, abort on a server-reported error, and abort on an exception — asserting both the control flow
and the run outcome recorded in the data file.
"""
import h5py
import pytest

from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.integration


class TinyProtocol(BaseProtocol):
    """A minimal real protocol: 3 epochs, zero-duration timing so runs are instant.

    on_epoch(protocol) is invoked at the start of each epoch's start_stimuli, letting a test inject
    an event (stop the run, break the link, push a server error, raise) at a chosen epoch.
    """
    on_epoch = None

    def get_run_parameter_defaults(self):
        return {'num_epochs': 3, 'idle_color': 0.5, 'do_loco': False}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.0, 'stim_time': 0.0, 'tail_time': 0.0}

    def get_epoch_parameters(self):
        super().get_epoch_parameters()
        self.epoch_stim_parameters = {'name': 'FakeStim'}

    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
        if self.on_epoch is not None:
            self.on_epoch(self)
        super().start_stimuli(manager, append_stim_frames=append_stim_frames,
                              print_profile=print_profile, multicall=multicall)


def series_attrs(data):
    path = '/Subjects/{}/epoch_runs/series_{}'.format(data.current_subject, str(data.series_count).zfill(3))
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        return dict(f[path].attrs), list(f[path]['epochs'].keys())


# --- normal completion ------------------------------------------------------------------------

def test_run_completes_and_records_status(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_epochs_completed == 3
    attrs, epochs = series_attrs(data)
    assert attrs['run_status'] == 'completed'
    assert attrs['num_epochs_completed'] == 3
    assert 'abort_reason' not in attrs
    assert 'run_end_unix_time' in attrs
    assert len(epochs) == 3                       # every epoch was written to the file

    # the stimulus was actually driven over the (fake) link, and the frame tracker was reset at the end
    assert 'corner_square_off' in fake_manager.call_names(target='visual')


def test_run_without_metadata_writes_nothing(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, data, save_metadata_flag=False)

    assert protocol.num_epochs_completed == 3
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        assert list(f['/Subjects/subj1/epoch_runs'].keys()) == []   # view mode: no series group


# --- user stop / pause ------------------------------------------------------------------------

def test_user_stop_halts_run_and_records_stopped(client, data):
    protocol = TinyProtocol(cfg={})
    protocol.on_epoch = lambda p: client.stop_run() if p.num_epochs_completed == 0 else None

    client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_epochs_completed == 1     # first epoch finished, then the run stopped
    attrs, epochs = series_attrs(data)
    assert attrs['run_status'] == 'stopped'
    assert attrs['num_epochs_completed'] == 1
    assert len(epochs) == 1


def test_pause_then_resume_still_completes(client, data):
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_epochs_completed == 0:
            client.pause_run()
            client.resume_run()                    # a paused loop spins until resumed
    protocol.on_epoch = hook

    client.start_run(protocol, data, save_metadata_flag=True)
    assert protocol.num_epochs_completed == 3
    assert series_attrs(data)[0]['run_status'] == 'completed'


# --- abort paths ------------------------------------------------------------------------------

def test_dead_server_link_aborts_run(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_epochs_completed == 0:
            fake_manager.connection_broken = True  # the server died
    protocol.on_epoch = hook

    with pytest.warns(UserWarning, match='connection'):
        client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_epochs_completed == 1      # stopped instead of running all 3 epochs
    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'aborted'
    assert attrs['abort_reason'] == 'server_connection_lost'


def test_server_reported_error_aborts_run(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    # BaseClient registers report_server_message on the manager in __init__; do it here since the
    # fixture bypasses __init__.
    fake_manager.register_function(client.report_server_message, name='report_server_message')

    def hook(p):
        if p.num_epochs_completed == 0:
            fake_manager.push_server_message('error', 'load_stim blew up')
    protocol.on_epoch = hook

    with pytest.warns(UserWarning, match='server reported an error'):
        client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_epochs_completed == 1
    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'error'
    assert 'load_stim blew up' in attrs['abort_reason']


def test_exception_during_run_is_contained_and_recorded(client, data):
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_epochs_completed == 1:
            raise RuntimeError('epoch exploded')
    protocol.on_epoch = hook

    with pytest.warns(UserWarning, match='aborted by exception'):
        client.start_run(protocol, data, save_metadata_flag=True)   # must not propagate

    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'error'
    assert 'epoch exploded' in attrs['abort_reason']


def test_server_warning_does_not_abort_run(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    fake_manager.register_function(client.report_server_message, name='report_server_message')
    protocol.on_epoch = lambda p: (fake_manager.push_server_message('warning', 'just a heads up')
                                   if p.num_epochs_completed == 0 else None)

    client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_epochs_completed == 3      # a warning is surfaced but does not stop the run
    assert series_attrs(data)[0]['run_status'] == 'completed'
    assert ('warning', 'just a heads up') in client.server_messages


def test_an_error_from_prepare_run_stops_the_run_before_on_run_start(client, data, fake_manager):
    """on_run_start actuates hardware -- PMT shutters, opto steps, acquisition triggers -- so a run
    that is already going to abort must not reach it.

    The queue used to be drained only inside the epoch loop, which runs after on_run_start. An
    error provoked by prepare_run therefore sat unread while the rig was told to close shutters and
    step opto for a run that then immediately aborted. Seen on a real rig: a protocol calling
    target('root').set_dlpc_current on a machine without that function.
    """
    started = []

    class Protocol(TinyProtocol):
        def prepare_run(self, manager, recompute_epoch_parameters=True):
            super().prepare_run(manager, recompute_epoch_parameters)
            fake_manager.push_server_message('error', 'no such function on the server root node')

        def on_run_start(self, manager, multicall=None):
            started.append(True)                 # the hardware actuation, in real protocols

    protocol = Protocol(cfg={})
    fake_manager.register_function(client.report_server_message, name='report_server_message')

    with pytest.warns(UserWarning):
        client.start_run(protocol, data, save_metadata_flag=True)

    assert started == [], 'on_run_start ran for a run that was already aborting'
    assert protocol.num_epochs_completed == 0
    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'error'
    assert 'root node' in attrs['abort_reason']


def test_on_run_start_still_runs_for_a_healthy_run(client, data, fake_manager):
    """The guard must not cost a normal run its start-up."""
    started = []

    class Protocol(TinyProtocol):
        def on_run_start(self, manager, multicall=None):
            started.append(True)

    protocol = Protocol(cfg={})
    fake_manager.register_function(client.report_server_message, name='report_server_message')

    client.start_run(protocol, data, save_metadata_flag=True)

    assert started == [True]
    assert protocol.num_epochs_completed == 3
    assert series_attrs(data)[0]['run_status'] == 'completed'


# --- the same lifecycle, writing NWB ------------------------------------------------------------
#
# The client does not know which backend it has; it calls end_epoch_run(status=..., reason=...)
# either way. These assert the NWB backend actually honours that contract under the real run loop,
# which is where the old data_nwb.end_epoch_run(protocol_object) signature would have raised.

def nwb_epoch_row(data):
    from pynwb import NWBHDF5IO
    with NWBHDF5IO(data.get_nwb_file_path(), 'r') as io:
        nwbfile = io.read()
        return nwbfile.epochs.to_dataframe().iloc[0], len(nwbfile.trials or [])


def test_nwb_run_completes_and_records_status(client, nwb_data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, nwb_data, save_metadata_flag=True)

    assert protocol.num_epochs_completed == 3
    row, n_trials = nwb_epoch_row(nwb_data)
    assert row['run_status'] == 'completed'
    assert row['run_status_reason'] == ''
    assert n_trials == 3                          # every epoch was written as a trial


def test_nwb_run_records_a_user_stop(client, nwb_data, fake_manager):
    protocol = TinyProtocol(cfg={})
    protocol.on_epoch = lambda p: client.stop_run() if p.num_epochs_completed == 1 else None
    client.start_run(protocol, nwb_data, save_metadata_flag=True)

    row, _ = nwb_epoch_row(nwb_data)
    assert row['run_status'] == 'stopped'


def test_nwb_run_records_an_exception(client, nwb_data, fake_manager):
    def boom(p):
        raise RuntimeError('stimulus blew up')

    protocol = TinyProtocol(cfg={})
    protocol.on_epoch = boom
    with pytest.warns(UserWarning):
        client.start_run(protocol, nwb_data, save_metadata_flag=True)

    row, _ = nwb_epoch_row(nwb_data)
    assert row['run_status'] == 'error'
    assert 'stimulus blew up' in row['run_status_reason']


def test_nwb_run_that_fails_before_its_file_exists_does_not_mask_the_cause(client, nwb_data,
                                                                          fake_manager, tmp_path):
    """end_epoch_run runs from the client's finally block. If the series file was never written,
    it must say so rather than raising FileNotFoundError over the real failure."""
    nwb_data.series_count = 99                    # a series prepare_series never created
    protocol = TinyProtocol(cfg={})
    with pytest.warns(UserWarning, match='No NWB file at'):
        client.start_run(protocol, nwb_data, save_metadata_flag=True)


def test_nwb_server_subdir_is_experiment_then_subject(client, nwb_data):
    assert nwb_data.get_server_subdir() == 'integration_test/subj1'
