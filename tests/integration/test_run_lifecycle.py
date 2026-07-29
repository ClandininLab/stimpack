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

    on_trial(protocol) is invoked at the start of each epoch's start_stimuli, letting a test inject
    an event (stop the run, break the link, push a server error, raise) at a chosen epoch.
    """
    on_trial = None

    def get_run_parameter_defaults(self):
        return {'num_trials': 3, 'idle_color': 0.5, 'do_loco': False}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.0, 'stim_time': 0.0, 'tail_time': 0.0}

    def get_trial_parameters(self):
        super().get_trial_parameters()
        self.trial_stim_parameters = {'name': 'FakeStim'}

    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
        if self.on_trial is not None:
            self.on_trial(self)
        super().start_stimuli(manager, append_stim_frames=append_stim_frames,
                              print_profile=print_profile, multicall=multicall)


def series_attrs(data):
    path = data.series_path()
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        return dict(f[path].attrs), list(f[path][data.TRIALS_GROUP].keys())


# --- normal completion ------------------------------------------------------------------------

def test_run_completes_and_records_status(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 3
    attrs, epochs = series_attrs(data)
    assert attrs['run_status'] == 'completed'
    assert attrs['num_trials_completed'] == 3
    assert 'abort_reason' not in attrs
    assert 'run_end_unix_time' in attrs
    assert len(epochs) == 3                       # every epoch was written to the file

    # the stimulus was actually driven over the (fake) link, and the frame tracker was reset at the end
    assert 'corner_square_off' in fake_manager.call_names(target='visual')


def test_run_without_metadata_writes_nothing(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, data, save_metadata_flag=False)

    assert protocol.num_trials_completed == 3
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        assert list(f[data.subject_series_path()].keys()) == []   # view mode: no series group


# --- user stop / pause ------------------------------------------------------------------------

def test_user_stop_halts_run_and_records_stopped(client, data):
    protocol = TinyProtocol(cfg={})
    protocol.on_trial = lambda p: client.stop_run() if p.num_trials_completed == 0 else None

    client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 1     # first epoch finished, then the run stopped
    attrs, epochs = series_attrs(data)
    assert attrs['run_status'] == 'stopped'
    assert attrs['num_trials_completed'] == 1
    assert len(epochs) == 1


def test_pause_then_resume_still_completes(client, data):
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            client.pause_run()
            client.resume_run()                    # a paused loop spins until resumed
    protocol.on_trial = hook

    client.start_run(protocol, data, save_metadata_flag=True)
    assert protocol.num_trials_completed == 3
    assert series_attrs(data)[0]['run_status'] == 'completed'


# --- abort paths ------------------------------------------------------------------------------

def test_dead_server_link_aborts_run(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            fake_manager.connection_broken = True  # the server died
    protocol.on_trial = hook

    with pytest.warns(UserWarning, match='connection'):
        client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 1      # stopped instead of running all 3 epochs
    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'aborted'
    assert attrs['abort_reason'] == 'server_connection_lost'


def test_server_reported_error_aborts_run(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    # BaseClient registers report_server_message on the manager in __init__; do it here since the
    # fixture bypasses __init__.
    fake_manager.register_function(client.report_server_message, name='report_server_message')

    def hook(p):
        if p.num_trials_completed == 0:
            fake_manager.push_server_message('error', 'load_stim blew up')
    protocol.on_trial = hook

    with pytest.warns(UserWarning, match='server reported an error'):
        client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 1
    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'error'
    assert 'load_stim blew up' in attrs['abort_reason']


def test_exception_during_run_is_contained_and_recorded(client, data):
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 1:
            raise RuntimeError('epoch exploded')
    protocol.on_trial = hook

    with pytest.warns(UserWarning, match='aborted by exception'):
        client.start_run(protocol, data, save_metadata_flag=True)   # must not propagate

    attrs, _ = series_attrs(data)
    assert attrs['run_status'] == 'error'
    assert 'epoch exploded' in attrs['abort_reason']


def test_server_warning_does_not_abort_run(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    fake_manager.register_function(client.report_server_message, name='report_server_message')
    protocol.on_trial = lambda p: (fake_manager.push_server_message('warning', 'just a heads up')
                                   if p.num_trials_completed == 0 else None)

    client.start_run(protocol, data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 3      # a warning is surfaced but does not stop the run
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
    assert protocol.num_trials_completed == 0
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
    assert protocol.num_trials_completed == 3
    assert series_attrs(data)[0]['run_status'] == 'completed'


# --- the same lifecycle, writing NWB ------------------------------------------------------------
#
# The client does not know which backend it has; it calls end_series(status=..., reason=...)
# either way. These assert the NWB backend actually honours that contract under the real run loop,
# which is where the old data_nwb.end_series(protocol_object) signature would have raised.

def nwb_epoch_row(data):
    from pynwb import NWBHDF5IO
    with NWBHDF5IO(data.get_nwb_file_path(), 'r') as io:
        nwbfile = io.read()
        return nwbfile.epochs.to_dataframe().iloc[0], len(nwbfile.trials or [])


def test_nwb_run_completes_and_records_status(client, nwb_data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, nwb_data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 3
    row, n_trials = nwb_epoch_row(nwb_data)
    assert row['run_status'] == 'completed'
    assert row['run_status_reason'] == ''
    assert n_trials == 3                          # every epoch was written as a trial


def test_nwb_run_records_a_user_stop(client, nwb_data, fake_manager):
    protocol = TinyProtocol(cfg={})
    protocol.on_trial = lambda p: client.stop_run() if p.num_trials_completed == 1 else None
    client.start_run(protocol, nwb_data, save_metadata_flag=True)

    row, _ = nwb_epoch_row(nwb_data)
    assert row['run_status'] == 'stopped'


def test_nwb_run_records_an_exception(client, nwb_data, fake_manager):
    def boom(p):
        raise RuntimeError('stimulus blew up')

    protocol = TinyProtocol(cfg={})
    protocol.on_trial = boom
    with pytest.warns(UserWarning):
        client.start_run(protocol, nwb_data, save_metadata_flag=True)

    row, _ = nwb_epoch_row(nwb_data)
    assert row['run_status'] == 'error'
    assert 'stimulus blew up' in row['run_status_reason']


def test_nwb_run_that_fails_before_its_file_exists_does_not_mask_the_cause(client, nwb_data,
                                                                          fake_manager, tmp_path):
    """end_series runs from the client's finally block. If the series file was never written,
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


def test_stop_ends_the_trial_in_progress(client, data, fake_manager, qapp):
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


def test_a_server_error_mid_trial_aborts_without_waiting(client, data, fake_manager):
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


def test_an_uninterrupted_trial_still_lasts_its_full_duration(client, data, fake_manager):
    """The interruptible wait must still wait: an epoch nobody stops has to take its stim_time."""
    import time

    class BriefProtocol(TinyProtocol):
        def get_run_parameter_defaults(self):
            return {'num_trials': 1, 'idle_color': 0.5, 'do_loco': False}
        def get_protocol_parameter_defaults(self):
            return {'pre_time': 0.0, 'stim_time': 0.4, 'tail_time': 0.0}

    protocol = BriefProtocol(cfg={})
    started = time.monotonic()
    client.start_run(protocol, data, save_metadata_flag=True)
    elapsed = time.monotonic() - started

    assert 0.4 <= elapsed < 2.0, f'a 0.4s epoch took {elapsed:.2f}s'
    assert protocol.num_trials_completed == 1


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

def test_the_server_can_end_an_trial_early(client, data, fake_manager):
    """The point of the whole mechanism: a trial that lasts until the animal does something.

    The condition can only be evaluated on the server -- the client never receives subject state,
    and could not ask for it, since requests carry no reply.
    """
    import time

    protocol = SlowProtocol(cfg={})          # 30 s stimulus
    fake_manager.register_function(client.report_server_message, name='report_server_message')
    fake_manager.register_function(client.stop_trial, name='stop_trial')

    # the "tracker" reaches the criterion 0.3 s into each epoch
    import threading

    def on_trial(p):
        threading.Timer(0.3, lambda: fake_manager.push_server_request(
            'stop_trial', trial_index=client.current_trial_index, reason='reached_goal')).start()
    protocol.on_trial = on_trial

    started = time.monotonic()
    client.start_run(protocol, data, save_metadata_flag=True)
    elapsed = time.monotonic() - started

    assert protocol.num_trials_completed == 3, 'the run should continue, not stop'
    assert elapsed < 10, f'{elapsed:.1f}s: epochs were not cut short'


def test_an_trial_ended_early_records_why_and_how_long(client, data, fake_manager):
    import threading

    protocol = SlowProtocol(cfg={})
    protocol.run_parameters['num_trials'] = 1
    fake_manager.register_function(client.stop_trial, name='stop_trial')
    protocol.on_trial = lambda p: threading.Timer(0.3, lambda: fake_manager.push_server_request(
        'stop_trial', trial_index=client.current_trial_index, reason='reached_goal')).start()

    client.start_run(protocol, data, save_metadata_flag=True)

    import h5py
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        epoch = f[data.trials_path() + '/trial_001']
        assert epoch.attrs['ended_early']
        assert epoch.attrs['trial_end_reason'] == 'reached_goal'
        assert 0 < epoch.attrs['trial_duration'] < 5      # not the 30 s the protocol asked for


def test_an_trial_that_runs_its_course_is_not_marked_early(client, data, fake_manager):
    protocol = TinyProtocol(cfg={})
    client.start_run(protocol, data, save_metadata_flag=True)

    import h5py
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        epoch = f[data.trials_path() + '/trial_001']
        assert not epoch.attrs['ended_early']
        assert 'trial_end_reason' not in epoch.attrs


def test_a_late_request_does_not_cut_short_the_following_trial(client, data, fake_manager):
    """A criterion met just as an epoch ends would otherwise arrive during the next one and end
    it too -- a truncated trial with no visible cause."""
    protocol = TinyProtocol(cfg={})
    fake_manager.register_function(client.stop_trial, name='stop_trial')

    client.current_trial_index = 0
    client.protocol_object = protocol
    protocol.manager = fake_manager

    client.stop_trial(trial_index=0, reason='in time')          # for the epoch running now
    assert protocol.stop_sleep_flag is True
    assert client.trial_end_reason == 'in time'

    protocol.stop_sleep_flag = False
    client.current_trial_index = 1                              # the next epoch has begun
    client.stop_trial(trial_index=0, reason='too late')         # a straggler for the old one
    assert protocol.stop_sleep_flag is False, 'a late request ended the wrong epoch'
    assert client.trial_end_reason == 'in time', 'a late request overwrote the reason'


def test_the_server_does_nothing_between_trials(fake_manager):
    """end_trial outside an epoch would otherwise end whichever one starts next."""
    from stimpack.experiment.server import BaseServer

    server = BaseServer.__new__(BaseServer)
    sent = []
    server.write_request_list = sent.append
    server.current_trial_index = None

    server.end_trial(reason='reached_goal')
    assert sent == []

    server.set_current_trial(4)
    server.end_trial(reason='reached_goal')
    assert sent and sent[0][0]['kwargs'] == {'trial_index': 4, 'reason': 'reached_goal'}


# --- pause: waiting, not spinning, and knowing which of the two states it is in ------------------

def _resume_after(client, seconds, record=None):
    """Resume the run from another thread, sampling the client's state just before doing so."""
    import threading
    import time as _time

    def worker():
        _time.sleep(seconds)
        if record is not None:
            record['state_while_paused'] = client.pause_state
            record['paused_seconds'] = client.paused_seconds
        client.resume_run()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def test_a_paused_run_waits_instead_of_spinning(client, data, fake_manager):
    """#pause: the paused branch was a bare `pass`, so the loop ran flat out for the whole pause.

    Measured at ~2.2 million iterations a second, holding a core at 100% -- alongside the
    timing-sensitive screen subprocess, and for exactly the minutes somebody has stepped away from
    the rig. process_queue() runs once per iteration, so counting it counts the loop.
    """
    import time as _time

    iterations = []
    real_process_queue = fake_manager.process_queue

    def counting_process_queue():
        iterations.append(1)
        real_process_queue()
    fake_manager.process_queue = counting_process_queue

    pause_seconds = 0.4
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            client.pause_run()
            _resume_after(client, pause_seconds)
    protocol.on_trial = hook

    t0 = _time.monotonic()
    client.start_run(protocol, data, save_metadata_flag=False)
    assert _time.monotonic() - t0 >= pause_seconds, 'the run did not actually wait'

    # 100 Hz polling gives ~40 for this pause; the old spin gave ~900,000. Any threshold in between
    # separates them, so this is not sensitive to how fast the machine is.
    assert len(iterations) < 5000, f'the paused loop spun: {len(iterations)} iterations'
    assert protocol.num_trials_completed == 3, 'the run did not resume'


def test_pause_state_distinguishes_requested_from_in_effect(client, data):
    """Pressing Pause does not pause the rig: the epoch in progress keeps presenting and recording.

    Reporting "Paused" during that interval tells the experimenter the subject is idle when it is
    still being stimulated, so the two states are kept apart.
    """
    seen = {}
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            assert client.pause_state == 'running'
            client.pause_run()
            # still inside the epoch: requested, but the run loop has not reached the boundary
            seen['just_after_press'] = client.pause_state
            _resume_after(client, 0.3, record=seen)
    protocol.on_trial = hook

    client.start_run(protocol, data, save_metadata_flag=False)

    assert seen['just_after_press'] == 'pending'
    assert seen['state_while_paused'] == 'paused'
    assert client.pause_state == 'running'          # resumed and ran to completion


def test_paused_time_is_measured_and_excluded_from_the_run(client, data):
    """paused_seconds is what lets the GUI keep elapsed time comparable to est_run_time."""
    pause_seconds = 0.4
    seen = {}
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            client.pause_run()
            _resume_after(client, pause_seconds, record=seen)
    protocol.on_trial = hook

    client.start_run(protocol, data, save_metadata_flag=False)

    assert seen['paused_seconds'] >= pause_seconds * 0.5   # a pause in progress is counted
    assert client.paused_seconds >= pause_seconds * 0.5    # and survives the end of the run
    # TinyProtocol's epochs are zero-length, so essentially all of the run was the pause.
    assert client.paused_seconds < pause_seconds + 2


def test_a_run_stopped_while_paused_stops_accumulating(client, data):
    """The elapsed-time display keeps reading paused_seconds after the loop exits."""
    import time as _time

    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            client.pause_run()
            _resume_after(client, 0.2)                 # resume, then stop on the next epoch
        elif p.num_trials_completed == 1:
            client.stop_run()
    protocol.on_trial = hook

    client.start_run(protocol, data, save_metadata_flag=False)

    settled = client.paused_seconds
    _time.sleep(0.3)
    assert client.paused_seconds == settled, 'paused time kept growing after the run ended'


def test_a_pause_is_recorded_in_the_data_file(client, data):
    """A pause is an unexplained gap in the timeline otherwise: the subject sat in the rig between
    two epochs with nothing being presented, and nothing in the file said so."""
    pause_seconds = 0.4
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            client.pause_run()
            _resume_after(client, pause_seconds)
    protocol.on_trial = hook

    client.start_run(protocol, data, save_metadata_flag=True)

    attrs, _ = series_attrs(data)
    assert attrs['paused_duration'] >= pause_seconds * 0.5
    assert attrs['run_status'] == 'completed'


def test_a_run_with_no_pause_records_zero_rather_than_nothing(client, data):
    """An absent attribute would be ambiguous between 'not paused' and 'written by an older
    stimpack that did not record it'."""
    client.start_run(TinyProtocol(cfg={}), data, save_metadata_flag=True)

    attrs, _ = series_attrs(data)
    assert attrs['paused_duration'] == 0.0


def test_nwb_records_a_pause_too(client, nwb_data):
    pause_seconds = 0.4
    protocol = TinyProtocol(cfg={})

    def hook(p):
        if p.num_trials_completed == 0:
            client.pause_run()
            _resume_after(client, pause_seconds)
    protocol.on_trial = hook

    client.start_run(protocol, nwb_data, save_metadata_flag=True)

    row, _ = nwb_epoch_row(nwb_data)
    assert row['paused_duration'] >= pause_seconds * 0.5


# --- overwriting a series -------------------------------------------------------------------------

def test_a_series_can_be_deleted_and_recorded_again(client, data):
    """The GUI offers this after asking, so a false start can be redone under the same number
    rather than renumbered around."""
    client.start_run(TinyProtocol(cfg={}), data, save_metadata_flag=True)
    assert data.get_series_count() in data.get_existing_series()
    first_attrs, first_epochs = series_attrs(data)
    assert len(first_epochs) == 3

    assert data.delete_series() is True
    assert data.get_series_count() not in data.get_existing_series()

    protocol = TinyProtocol(cfg={})
    protocol.run_parameters['num_trials'] = 2          # a visibly different second attempt
    client.start_run(protocol, data, save_metadata_flag=True)

    attrs, epochs = series_attrs(data)
    assert len(epochs) == 2, 'the replacement series kept the old epochs'
    assert attrs['run_status'] == 'completed'
    assert attrs['run_start_unix_time'] >= first_attrs['run_start_unix_time']


def test_deleting_a_series_that_is_not_there_says_so(data):
    assert data.delete_series(series_number=99) is False


def test_nwb_deletes_the_series_file(client, nwb_data):
    client.start_run(TinyProtocol(cfg={}), nwb_data, save_metadata_flag=True)
    path = nwb_data.get_nwb_file_path()
    assert path.is_file()

    assert nwb_data.delete_series() is True
    assert not path.is_file(), 'the series file is still there'

    # and prepare_series, which refuses to overwrite, is happy to write it again
    nwb_data.prepare_series()
    assert path.is_file()


# --- NWB: parameters that are not scalars --------------------------------------------------------

class VectorParamProtocol(TinyProtocol):
    """A protocol whose epoch parameters include a multi-element value.

    Utterly ordinary -- MovingPatch and MovingEllipse both have width_height, and centre is a
    coordinate pair -- which is what makes it worth a test.
    """
    def get_run_parameter_defaults(self):
        return {'num_trials': 2, 'idle_color': 0.5, 'do_loco': False}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.0, 'stim_time': 0.0, 'tail_time': 0.0,
                'width_height': [[10, 30]], 'center': [[0, 0]]}


def test_nwb_records_trials_whose_parameters_are_pairs(client, nwb_data):
    """#nwb: the trials table wrote a 2-element value as a (1, 2) dataset while declaring a
    rank-1 maxshape, so h5py refused it and the run aborted on the first epoch."""
    protocol = VectorParamProtocol(cfg={})

    client.start_run(protocol, nwb_data, save_metadata_flag=True)

    assert protocol.num_trials_completed == 2, 'the run did not survive its first epoch'

    from pynwb import NWBHDF5IO
    with NWBHDF5IO(nwb_data.get_nwb_file_path(), 'r') as io:
        trials = io.read().trials.to_dataframe()

    assert len(trials) == 2
    assert list(trials['width_height'].iloc[0]) == [10, 30], 'the pair was not recorded'


def test_a_failure_to_record_the_outcome_does_not_take_the_process_down(client, data, monkeypatch):
    """start_run is called on a QThread, where an exception out of run() aborts the process. This
    one is raised from a finally block, so it also replaced the real error with the cleanup's --
    which is how a bad NWB epoch write ended with the GUI core-dumping while trying to record that
    the run had failed, reporting a read error instead of the write that caused it."""
    protocol = TinyProtocol(cfg={})

    def explode(*args, **kwargs):
        raise ValueError('No data_type found for builder root/intervals/trials')
    monkeypatch.setattr(data, 'end_series', explode)

    with pytest.warns(UserWarning, match='recording that in the .* file failed'):
        client.start_run(protocol, data, save_metadata_flag=True)   # must not raise

    assert protocol.num_trials_completed == 3, 'the run itself should have finished normally'


def test_the_original_error_survives_a_failing_cleanup(client, data, monkeypatch):
    """The run's own failure is what the experimenter needs to see, not the cleanup's."""
    protocol = TinyProtocol(cfg={})
    protocol.on_trial = lambda p: (_ for _ in ()).throw(RuntimeError('the screen fell over'))
    monkeypatch.setattr(data, 'end_series',
                        lambda *a, **k: (_ for _ in ()).throw(ValueError('cleanup also failed')))

    with pytest.warns(UserWarning) as warnings_raised:
        client.start_run(protocol, data, save_metadata_flag=True)

    messages = [str(w.message) for w in warnings_raised]
    assert any('the screen fell over' in m for m in messages), 'the real error was lost'
    assert any('recording that in the' in m for m in messages)


def test_nwb_trials_columns_can_grow_without_limit(client, nwb_data):
    """The trials table declared maxshape=1000, a hard ceiling that would have failed on epoch
    1001 and not before. Checked by reading the declared shape rather than by writing 1001 rows."""
    import h5py

    client.start_run(VectorParamProtocol(cfg={}), nwb_data, save_metadata_flag=True)

    with h5py.File(nwb_data.get_nwb_file_path(), 'r') as f:
        trials = f['/intervals/trials']
        assert trials['start_time'].maxshape == (None,)
        # a pair keeps its width and grows only in rows
        assert trials['width_height'].maxshape == (None, 2)


def test_a_failure_to_record_the_outcome_is_reported_not_just_logged(client, data, monkeypatch):
    """Whatever stopped the outcome being written stopped it part-way, so the file is not what it
    should be -- and for NWB it may not open at all. The run has already ended by then, so nothing
    else will raise about it: a warning alone leaves it to be found at analysis time."""
    reported = []
    client.on_data_error = reported.append
    monkeypatch.setattr(data, 'end_series',
                        lambda *a, **k: (_ for _ in ()).throw(ValueError('no data_type found')))

    with pytest.warns(UserWarning):
        client.start_run(TinyProtocol(cfg={}), data, save_metadata_flag=True)

    assert len(reported) == 1, 'the failure was not surfaced'
    assert 'may not open' in reported[0]
    assert 'no data_type found' in reported[0], 'the underlying error was not included'


def test_a_broken_data_error_callback_cannot_take_the_run_with_it(client, data, monkeypatch):
    """It is called from a finally block on a QThread; raising there aborts the process."""
    client.on_data_error = lambda text: (_ for _ in ()).throw(RuntimeError('callback is broken'))
    monkeypatch.setattr(data, 'end_series',
                        lambda *a, **k: (_ for _ in ()).throw(ValueError('write failed')))

    with pytest.warns(UserWarning, match='on_data_error callback failed'):
        client.start_run(TinyProtocol(cfg={}), data, save_metadata_flag=True)   # must not raise


class NestedParamProtocol(TinyProtocol):
    """A parameter whose per-epoch value is itself a list of pairs -- N positions, say, or a
    colour per element. MHT builds cylinder_locations this way."""
    def get_run_parameter_defaults(self):
        return {'num_trials': 2, 'idle_color': 0.5, 'do_loco': False}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.0, 'stim_time': 0.0, 'tail_time': 0.0,
                'locations': [[[1, 2], [3, 4]]],
                'width_height': [[10, 30], [20, 40]]}


def test_nwb_handles_a_parameter_nested_two_deep(client, nwb_data):
    """The epochs table holds the parameters as entered, so a per-epoch value that is a list of
    pairs is three deep there. Declaring a rank-1 maxshape over what was left after one flatten
    wrote an epochs group with no neurodata_type -- and pynwb could then not open the file at all,
    including the correctly-written trials data underneath it."""
    import numpy as np
    from pynwb import NWBHDF5IO

    client.start_run(NestedParamProtocol(cfg={}), nwb_data, save_metadata_flag=True)

    with NWBHDF5IO(nwb_data.get_nwb_file_path(), 'r') as io:   # must open at all
        f = io.read()
        epochs = f.epochs.to_dataframe()
        trials = f.trials.to_dataframe()

    # the run-level row keeps the parameters as they were entered
    assert np.asarray(epochs['locations'].iloc[0]).tolist() == [[[1, 2], [3, 4]]]
    assert np.asarray(epochs['width_height'].iloc[0]).tolist() == [[10, 30], [20, 40]]

    # and each epoch keeps the value it actually used
    assert np.asarray(trials['locations'].iloc[0]).tolist() == [[1, 2], [3, 4]]
    assert sorted(np.asarray(trials['width_height'].iloc[i]).tolist() for i in range(2)) \
        == [[10, 30], [20, 40]]
