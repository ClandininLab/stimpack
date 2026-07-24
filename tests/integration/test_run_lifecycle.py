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
