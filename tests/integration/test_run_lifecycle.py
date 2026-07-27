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


# --- stopping without waiting out the epoch --------------------------------------------------------

class SlowProtocol(TinyProtocol):
    """Epochs long enough that waiting one out would be obvious."""
    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.0, 'stim_time': 30.0, 'tail_time': 0.0}


def test_stop_ends_the_epoch_in_progress(client, data, fake_manager, qapp):
    """Stop used to be noticed only at the top of the next epoch, so stopping a run with long
    epochs meant watching the current one finish -- no use when the reason for stopping is what is
    on the screen right now."""
    import threading
    import time

    protocol = SlowProtocol(cfg={})
    fake_manager.register_function(client.report_server_message, name='report_server_message')

    # press Stop shortly after the first epoch's 30-second stimulus starts
    threading.Timer(0.3, client.stop_run).start()

    started = time.monotonic()
    client.start_run(protocol, data, save_metadata_flag=True)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f'the run took {elapsed:.1f}s; it waited out the 30s epoch'
    assert series_attrs(data)[0]['run_status'] == 'stopped'


def test_a_server_error_mid_epoch_aborts_without_waiting(client, data, fake_manager):
    """Same latency problem for an error the server reports during an epoch."""
    import threading
    import time

    protocol = SlowProtocol(cfg={})
    fake_manager.register_function(client.report_server_message, name='report_server_message')
    threading.Timer(0.3, lambda: fake_manager.push_server_message('error', 'screen died')).start()

    started = time.monotonic()
    with pytest.warns(UserWarning):
        client.start_run(protocol, data, save_metadata_flag=True)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f'the run took {elapsed:.1f}s; it waited out the 30s epoch'
    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'error'
    assert 'screen died' in attrs['abort_reason']


def test_an_uninterrupted_epoch_still_lasts_its_full_duration(client, data, fake_manager):
    """The interruptible wait must still wait: an epoch nobody stops has to take its stim_time."""
    import time

    class BriefProtocol(TinyProtocol):
        def get_run_parameter_defaults(self):
            return {'num_epochs': 1, 'idle_color': 0.5, 'do_loco': False}
        def get_protocol_parameter_defaults(self):
            return {'pre_time': 0.0, 'stim_time': 0.4, 'tail_time': 0.0}

    protocol = BriefProtocol(cfg={})
    started = time.monotonic()
    client.start_run(protocol, data, save_metadata_flag=True)
    elapsed = time.monotonic() - started

    assert 0.4 <= elapsed < 2.0, f'a 0.4s epoch took {elapsed:.2f}s'
    assert protocol.num_epochs_completed == 1


def test_waiting_does_not_spin_the_cpu(client, data, fake_manager):
    """The wait polls the client, so it must yield between passes -- otherwise it pegs a core for
    every epoch, on a client that may also be running the closed-loop locomotion updates."""
    import time

    protocol = TinyProtocol(cfg={})
    protocol.manager = fake_manager

    cpu_before = time.process_time()
    protocol.sleep(0.5)
    cpu_used = time.process_time() - cpu_before

    assert cpu_used < 0.1, f'used {cpu_used:.2f}s of CPU waiting 0.5s; it is spinning'


# --- trials the animal ends ------------------------------------------------------------------------

def test_the_server_can_end_an_epoch_early(client, data, fake_manager):
    """The point of the whole mechanism: a trial that lasts until the animal does something.

    The condition can only be evaluated on the server -- the client never receives subject state,
    and could not ask for it, since requests carry no reply.
    """
    import time

    protocol = SlowProtocol(cfg={})          # 30 s stimulus
    fake_manager.register_function(client.report_server_message, name='report_server_message')
    fake_manager.register_function(client.stop_epoch, name='stop_epoch')

    # the "tracker" reaches the criterion 0.3 s into each epoch
    import threading

    def on_epoch(p):
        threading.Timer(0.3, lambda: fake_manager.push_server_request(
            'stop_epoch', epoch_index=client.current_epoch_index, reason='reached_goal')).start()
    protocol.on_epoch = on_epoch

    started = time.monotonic()
    client.start_run(protocol, data, save_metadata_flag=True)
    elapsed = time.monotonic() - started

    assert protocol.num_epochs_completed == 3, 'the run should continue, not stop'
    assert elapsed < 10, f'{elapsed:.1f}s: epochs were not cut short'


def test_an_epoch_ended_early_records_why_and_how_long(client, data, fake_manager):
    import threading

    protocol = SlowProtocol(cfg={})
    protocol.run_parameters['num_epochs'] = 1
    fake_manager.register_function(client.stop_epoch, name='stop_epoch')
    protocol.on_epoch = lambda p: threading.Timer(0.3, lambda: fake_manager.push_server_request(
        'stop_epoch', epoch_index=client.current_epoch_index, reason='reached_goal')).start()

    client.start_run(protocol, data, save_metadata_flag=True)

    import h5py
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        epoch = f[f'/Subjects/{data.current_subject}/epoch_runs/series_001/epochs/epoch_001']
        assert epoch.attrs['ended_early']
        assert epoch.attrs['epoch_end_reason'] == 'reached_goal'
        assert 0 < epoch.attrs['epoch_duration'] < 5      # not the 30 s the protocol asked for


def test_an_epoch_that_runs_its_course_is_not_marked_early(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, data, save_metadata_flag=True)

    import h5py
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        epoch = f[f'/Subjects/{data.current_subject}/epoch_runs/series_001/epochs/epoch_001']
        assert not epoch.attrs['ended_early']
        assert 'epoch_end_reason' not in epoch.attrs


def test_a_late_request_does_not_cut_short_the_following_epoch(client, data, fake_manager):
    """A criterion met just as an epoch ends would otherwise arrive during the next one and end
    it too -- a truncated trial with no visible cause."""
    protocol = TinyProtocol(cfg={})
    fake_manager.register_function(client.stop_epoch, name='stop_epoch')

    client.current_epoch_index = 0
    client.protocol_object = protocol
    protocol.manager = fake_manager

    client.stop_epoch(epoch_index=0, reason='in time')          # for the epoch running now
    assert protocol.stop_sleep_flag is True
    assert client.epoch_end_reason == 'in time'

    protocol.stop_sleep_flag = False
    client.current_epoch_index = 1                              # the next epoch has begun
    client.stop_epoch(epoch_index=0, reason='too late')         # a straggler for the old one
    assert protocol.stop_sleep_flag is False, 'a late request ended the wrong epoch'
    assert client.epoch_end_reason == 'in time', 'a late request overwrote the reason'


def test_the_server_does_nothing_between_epochs(fake_manager):
    """end_epoch outside an epoch would otherwise end whichever one starts next."""
    from stimpack.experiment.server import BaseServer

    server = BaseServer.__new__(BaseServer)
    sent = []
    server.write_request_list = sent.append
    server.current_epoch_index = None

    server.end_epoch(reason='reached_goal')
    assert sent == []

    server.set_current_epoch(4)
    server.end_epoch(reason='reached_goal')
    assert sent and sent[0][0]['kwargs'] == {'epoch_index': 4, 'reason': 'reached_goal'}
