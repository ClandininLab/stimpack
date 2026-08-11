"""Unit tests for BaseProtocol's parameter-sequencing engine (no GL/GUI/hardware).

Importable without PyQt6 now that stimpack.util defers its Qt import; needs numpy + yaml.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.unit


def make_protocol(num_trials):
    p = BaseProtocol(cfg={})
    p.run_parameters = {"num_trials": num_trials}
    return p


def test_all_combinations_is_cartesian_product():
    p = make_protocol(num_trials=6)
    p.get_parameter_sequence(([0, 1, 2], [10, 20]), all_combinations=True, randomize_order=False)
    seq = p.persistent_parameters["protocol_parameter_sequence"]
    assert set(seq) == {(0, 10), (0, 20), (1, 10), (1, 20), (2, 10), (2, 20)}
    assert len(seq) == 6


def test_associated_lists_when_not_all_combinations():
    p = make_protocol(num_trials=3)
    p.get_parameter_sequence(([0, 1, 2], [10, 20, 30]), all_combinations=False, randomize_order=False)
    seq = p.persistent_parameters["protocol_parameter_sequence"]
    assert [tuple(row) for row in seq] == [(0, 10), (1, 20), (2, 30)]


def test_single_list_is_used_directly():
    p = make_protocol(num_trials=4)
    p.get_parameter_sequence([0, 90, 180, 270], all_combinations=True, randomize_order=False)
    seq = p.persistent_parameters["protocol_parameter_sequence"]
    assert seq == [0, 90, 180, 270]


def test_sequence_repeats_to_fill_num_trials():
    p = make_protocol(num_trials=5)
    p.get_parameter_sequence([0, 1], all_combinations=True, randomize_order=False)
    inds = p.persistent_parameters["protocol_parameter_sequence_epoch_inds"]
    assert list(inds) == [0, 1, 0, 1, 0]  # arange(5) % 2


def test_server_error_demo_requests_a_nonexistent_stim():
    # The demo protocol must ask for a stim class that does not exist, so load_stim raises on the
    # server (demonstrating server -> client error reporting).
    from stimpack.experiment.diagnostics_protocol import ServerErrorDemo
    p = ServerErrorDemo(cfg={})
    p.get_trial_parameters()
    assert p.trial_stim_parameters == {"name": "NoSuchStimulus_ServerErrorDemo"}


def test_run_time_estimate_can_be_overridden_by_a_subclass():
    """Name mangling made _BaseProtocol__estimate_run_time unreachable from a subclass, so a
    labpack with variable-length epochs could not correct the estimate."""
    from stimpack.experiment.protocol import BaseProtocol

    class MyProtocol(BaseProtocol):
        def _estimate_run_time(self):
            self.est_run_time = 42.0

    assert MyProtocol._estimate_run_time is not BaseProtocol._estimate_run_time
    assert not hasattr(BaseProtocol, '_BaseProtocol__estimate_run_time')


# --- asking what the rig can do -------------------------------------------------------------------

def _protocol(functions=None, modules=None):
    from stimpack.experiment.protocol import BaseProtocol
    p = BaseProtocol(cfg={})
    p.available_modules = modules
    p.available_server_functions = functions
    return p


def test_has_server_function_finds_a_lab_registered_root_function():
    p = _protocol({'root': {'print_on_server', 'set_dlpc_current'}})
    assert p.has_server_function('set_dlpc_current') is True
    assert p.has_server_function('set_shutter') is False


def test_has_server_function_defaults_to_the_root_target():
    """Matching an untargeted call, which also goes to root."""
    p = _protocol({'root': {'set_dlpc_current'}, 'voltage_out': {'set_value'}})
    assert p.has_server_function('set_dlpc_current') is True
    assert p.has_server_function('set_value') is False           # that one is on a module
    assert p.has_server_function('set_value', target='voltage_out') is True


def test_has_server_function_is_true_when_the_server_advertised_nothing():
    """An older stimpack. Adopting this must not change behavior until there is something real
    to report -- the same contract as has_module."""
    assert _protocol(None).has_server_function('anything') is True


def test_has_server_function_is_true_for_a_target_that_cannot_enumerate():
    """The visual module forwards to screen subprocesses, so it is absent from the map. Absent
    means unknown, not empty -- answering False would be a wrong answer rather than no answer."""
    p = _protocol({'root': {'print_on_server'}})
    assert p.has_server_function('load_stim', target='visual') is True


# --- the chase: server-side pursuit against a client-defined path --------------------------------

class _FakeServer:
    def __init__(self):
        self.ended = []

    def end_trial(self, reason=None):
        self.ended.append(reason)


def test_the_server_regenerates_the_exact_path_the_client_shows():
    """ChaseTheTower's whole premise: no tower position is ever sent. The client builds the
    stimulus trajectories and the server rebuilds them from the seed, through the same function --
    so the two must be identical, not merely similar."""
    import numpy as np
    import stimpack.experiment.example_protocol as ep

    p = ep.ChaseTheTower(cfg={})
    p.select_protocol_preset()
    p.protocol_parameters['seed'] = 11
    p.run_parameters['randomize_order'] = False
    p.precompute_trial_parameters(refresh=True)
    p.load_precomputed_trial_parameters()
    p.get_trial_parameters()

    n = int(p.trial_protocol_parameters['stim_time'] / ep.ChaseTheTower.DT) + 1
    box = next(d for d in p.trial_stim_parameters if d['name'] == 'MovingBox')
    xs, ys = ep._tower_path(11, n)

    assert np.allclose([v for _, v in box['x']['tv_pairs']], xs)
    assert np.allclose([v for _, v in box['y']['tv_pairs']], ys)


def test_the_chase_arms_stamps_catches_and_disarms(monkeypatch):
    import stimpack.experiment.example_protocol as ep

    now = [1000.0]
    monkeypatch.setattr(ep.time, 'time', lambda: now[0])
    fn = ep.ChaseTheTower.server_side_state_dependent_control
    n = int(30.0 / ep.ChaseTheTower.DT) + 1
    xs, ys = ep._tower_path(5, n)
    server, state = _FakeServer(), {}

    def step(update):
        out = fn(server, state, dict(update))
        state.update(out)
        return out

    # Not armed: untouched, exactly as for every protocol that never heard of the chase.
    assert step({'y': 0.25}) == {'y': 0.25} and server.ended == []

    step({'chase_armed': 1, 'chase_t0': 0.0, 'chase_seed': 5, 'chase_n': n})
    assert state['chase_t0'] == 1000.0, 'first armed update stamps the trial clock'

    now[0] = 1003.0
    i = min(int(3.0 / ep.ChaseTheTower.DT), n - 1)
    step({'x': 0.0, 'y': 0.0})
    assert server.ended == [], 'at the start line, the tower is out of reach'

    step({'x': xs[i] + 0.01, 'y': ys[i]})
    assert server.ended == ['caught'], 'within the catch radius: caught'
    assert state['chase_armed'] == 0, 'one catch per arming'

    step({'x': xs[i], 'y': ys[i]})
    assert server.ended == ['caught'], 'disarmed: standing on the tower must not end anything'


def test_the_tower_never_wanders_into_the_catch_zone_unaided():
    """A stationary subject must not be handed a catch: over many seeds, the tower's closest
    approach to the start line stays outside CATCH_RADIUS. Guaranteed by construction
    (TOWER_START minus WANDER_BOUND), and measured anyway."""
    import numpy as np
    import stimpack.experiment.example_protocol as ep

    n = int(30.0 / ep.ChaseTheTower.DT) + 1
    closest = min(
        float(np.min(np.hypot(np.array(xs), np.array(ys))))
        for xs, ys in (ep._tower_path(seed, n) for seed in range(10)))

    assert closest >= ep.ChaseTheTower.TOWER_START[1] - ep.ChaseTheTower.WANDER_BOUND - 1e-9
    assert closest > ep.ChaseTheTower.CATCH_RADIUS


# --- do_loco defaults: pre-checked where the protocol is closed-loop by nature --------------------

def test_a_closed_loop_protocol_arrives_with_tracking_on():
    """ReachTheGoal without do_loco is thirty seconds of nothing; a demo that sits inert until
    the user finds a checkbox is a broken demo. The protocol declares it, and
    select_protocol_preset must respect the declaration rather than overwrite it."""
    import stimpack.experiment.example_protocol as ep

    for cls in (ep.ReachTheGoal, ep.ChaseTheTower, ep.LinearTrackWithTowers):
        p = cls(cfg={})
        p.select_protocol_preset()
        assert p.run_parameters['do_loco'] is True, cls.__name__

    p = ep.WanderingSpot(cfg={})        # open loop by nature: stays opt-in
    p.select_protocol_preset()
    assert p.run_parameters['do_loco'] is False


def test_do_loco_is_removed_on_a_rig_without_a_tracker():
    """Even when the protocol declares it: the checkbox would offer a thing that cannot work, and
    a run with it set would send locomotion calls to a module that does not exist."""
    import stimpack.experiment.example_protocol as ep

    cfg = {'current_rig_name': 'norig',
           'rig_config': {'norig': {'loco_available': False}}}
    p = ep.ReachTheGoal(cfg=cfg)
    p.select_protocol_preset()
    assert 'do_loco' not in p.run_parameters


def test_the_tower_base_is_never_coplanar_with_the_floor():
    """Coplanar surfaces z-fight, and which wins varies per pixel and per driver: on rig hardware
    the translucent tower shimmered with blinking lines along its base as it moved. The base must
    sit strictly below the floor plane, by enough to clear depth-precision noise."""
    import stimpack.experiment.example_protocol as ep

    c = ep.ChaseTheTower
    base = (c.FLOOR_Z + c.TOWER_HEIGHT / 2 - c.TOWER_SINK) - c.TOWER_HEIGHT / 2
    top = base + c.TOWER_HEIGHT

    assert base <= c.FLOOR_Z - 0.001, 'tower base is on (or above) the floor plane: z-fighting'
    assert top > c.FLOOR_Z + 0.02, 'tower barely rises above the floor'
