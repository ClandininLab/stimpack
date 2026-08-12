"""The subject-state history: collected on the server, shipped once at run end, saved with the series.

The server is the single funnel every state source passes through (trackers, KeyTrac, a protocol's
own keys), so its history is the modality-neutral record the per-module logs are projections of.
Shipping happens at run END on purpose -- serializing a run's history must never delay the gap
between trials -- and the tests pin that contract at each hop: accumulate, ship, receive, write.
"""
import json

import pytest

pytest.importorskip("numpy")
pytest.importorskip("h5py")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

import h5py
import numpy as np

pytestmark = pytest.mark.unit


# # # The server side: accumulate between the client's marks, ship once # # #

def server(tmp_path=None):
    from stimpack.experiment.server import BaseServer
    s = BaseServer(host='127.0.0.1', port=None, visual_stim_kwargs=None, start_loop=False)
    s._shipped = []
    s.write_request_list = s._shipped.extend
    return s


def test_not_collecting_outside_a_run():
    s = server()
    s.set_subject_state({'x': 1.0})
    assert s._subject_state_history is None


def test_snapshots_accumulate_between_start_and_send():
    s = server()
    s.start_subject_state_history()
    s.set_subject_state({'x': 1.0})
    s.set_subject_state({'y': 2.0, 'lab_key': 7})

    assert len(s._subject_state_history) == 2
    t0, state0 = s._subject_state_history[0]
    t1, state1 = s._subject_state_history[1]
    assert t1 >= t0
    assert state0['x'] == 1.0 and 'lab_key' not in state0
    # full accumulated state, not the sparse update: the second row still knows x
    assert state1['x'] == 1.0 and state1['y'] == 2.0 and state1['lab_key'] == 7


def test_send_ships_one_message_and_stops_collecting():
    s = server()
    s.start_subject_state_history()
    s.set_subject_state({'x': 1.0})
    s.send_subject_state_history()

    assert [r['name'] for r in s._shipped] == ['receive_subject_state_history']
    history = s._shipped[0]['args'][0]
    assert len(history) == 1 and history[0][1]['x'] == 1.0
    # collection is run-scoped: a state update after the run leaves no trace
    s.set_subject_state({'x': 2.0})
    assert s._subject_state_history is None


def test_send_with_nothing_collected_ships_an_empty_history():
    """An older client never calls start; a symmetric server still answers, with []."""
    s = server()
    s.send_subject_state_history()
    assert s._shipped[0]['args'][0] == []


def test_the_belt_log_flushes_at_trial_boundaries_not_per_update(tmp_path):
    """Updates arrive on the request loop at tracker rate, where a stalling disk (an NFS mount)
    would stall the routing of everything else -- so lines buffer in memory and reach disk when
    the client marks a trial edge. A crash loses at most the trial in progress, which is the
    trial the crash already ruined."""
    s = server()
    s.start_subject_state_history(log_dir=str(tmp_path / 'state'))
    s.set_subject_state({'x': 1.0})
    assert not (tmp_path / 'state' / 'subject_state.jsonl').exists(), 'buffered, not yet on disk'

    s.set_current_trial(None)                                        # the client ends a trial
    lines = (tmp_path / 'state' / 'subject_state.jsonl').read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row['state']['x'] == 1.0 and 'ts' in row

    s.set_subject_state({'x': 2.0})
    s.send_subject_state_history()                                   # run end also flushes
    assert len((tmp_path / 'state' / 'subject_state.jsonl').read_text().splitlines()) == 2
    assert s._subject_state_log_file is None


def test_a_stateless_run_leaves_no_belt_file_behind(tmp_path):
    """A protocol that never touches subject state costs the history nothing: an empty ship, no
    file, not even the directory -- the belt opens lazily, on the first flush with lines."""
    s = server()
    s.start_subject_state_history(log_dir=str(tmp_path / 'state'))
    s.set_current_trial(0)
    s.set_current_trial(None)
    s.send_subject_state_history()

    assert s._shipped[0]['args'][0] == []
    assert not (tmp_path / 'state').exists()


# # # The client side: ask at run end, wait for the answer, hand it to data # # #

class _Manager:
    """Delivery is asynchronous over the real link; here process_queue plays the postman."""
    def __init__(self, shim, history):
        self._shim, self._history, self.requested = shim, history, []
        self.available_server_functions = {'root': {'send_subject_state_history'}}

    def target(self, name):
        outer = self

        class _Proxy:
            def __getattr__(self, method):
                return lambda *a, **k: outer.requested.append((name, method))
        return _Proxy()

    def process_queue(self):
        if self._history is not None:
            self._shim._subject_state_history = self._history


class _Data:
    def __init__(self):
        self.saved = []

    def save_subject_state_history(self, history):
        self.saved.append(history)


def _collect(history, timeout=0.2):
    from stimpack.experiment.client import BaseClient

    class _Shim:
        _server_collects_subject_state = BaseClient._server_collects_subject_state
    shim = _Shim()
    shim.manager = _Manager(shim, history)
    data = _Data()
    BaseClient.collect_subject_state_history(shim, data, timeout=timeout)
    return shim.manager, data


def test_the_history_is_requested_received_and_saved():
    manager, data = _collect(history=[[1.0, {'x': 0.5}]])
    assert ('root', 'send_subject_state_history') in manager.requested
    assert data.saved == [[[1.0, {'x': 0.5}]]]


def test_an_empty_history_is_not_written():
    _, data = _collect(history=[])
    assert data.saved == []


def test_a_server_that_never_answers_times_out_without_raising():
    """A server that advertised the capability but died mid-run never answers. The run must
    still end cleanly, with the history simply absent."""
    _, data = _collect(history=None, timeout=0.05)
    assert data.saved == []


def test_a_server_that_never_advertised_is_not_asked():
    """The costed asymmetry: a fire-and-forget call to an older server is free, but waiting out
    the timeout at the end of every run is not -- so no advertisement, no round trip."""
    from stimpack.experiment.client import BaseClient

    class _Shim:
        _server_collects_subject_state = BaseClient._server_collects_subject_state
    shim = _Shim()
    shim.manager = _Manager(shim, history=[[1.0, {'x': 0.5}]])
    shim.manager.available_server_functions = None
    data = _Data()
    BaseClient.collect_subject_state_history(shim, data, timeout=60.0)   # must not wait at all
    assert shim.manager.requested == []
    assert data.saved == []


# # # The HDF5 writer # # #

def _hdf5_data(tmp_path):
    from stimpack.experiment.data import BaseData
    data = BaseData(cfg={})
    data.data_directory = str(tmp_path)
    data.experiment_file_name = 'test_experiment'
    data.initialize_experiment_file()
    data.create_subject({'subject_id': 's1'})
    return data


class _Protocol:
    def __init__(self):
        self.run_parameters = {'num_trials': 1, 'idle_color': 0.0}
        self.protocol_parameters = {}
        self.trial_stim_parameters = {'name': 'StimA'}
        self.trial_protocol_parameters = {}
        self.num_trials_completed = 0


def test_hdf5_history_lands_under_the_series(tmp_path):
    data = _hdf5_data(tmp_path)
    data.create_series(_Protocol())
    data.save_subject_state_history([
        [100.0, {'x': 0.0, 'theta': 0.0}],
        [100.1, {'x': 0.5, 'theta': 90.0, 'chase_armed': 1}],
    ])

    with h5py.File(tmp_path / 'test_experiment.hdf5', 'r') as f:
        group = f[data.series_path() + '/subject_state_history']
        assert np.allclose(group['time'][()], [100.0, 100.1])
        assert np.allclose(group['x'][()], [0.0, 0.5])
        # a key introduced mid-run is NaN before it exists, not zero
        assert np.isnan(group['chase_armed'][0]) and group['chase_armed'][1] == 1.0
        assert group.attrs['time_basis'].startswith('unix')


def test_hdf5_non_numeric_keys_are_named_not_dropped(tmp_path):
    data = _hdf5_data(tmp_path)
    data.create_series(_Protocol())
    data.save_subject_state_history([[100.0, {'x': 0.0, 'phase': 'chasing'}]])

    with h5py.File(tmp_path / 'test_experiment.hdf5', 'r') as f:
        group = f[data.series_path() + '/subject_state_history']
        assert list(group.attrs['non_numeric_keys']) == ['phase']
        assert 'phase' not in group


# # # The per-screen record is opt-in, now that this history exists # # #

def test_screen_pos_history_is_off_by_default():
    """The server history is the analysis record; each screen's frame-time copy is a verification
    record that earns its disk only when someone asks for it. Pre-1.0 it rode along with every
    recorded closed-loop trial automatically."""
    from stimpack.experiment.protocol import BaseProtocol
    assert BaseProtocol(cfg={}).save_screen_pos_history is False
