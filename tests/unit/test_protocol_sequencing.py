"""Unit tests for BaseProtocol's parameter-sequencing engine (no GL/GUI/hardware).

Importable without PyQt6 now that stimpack.util defers its Qt import; needs numpy + yaml.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.unit


def make_protocol(num_epochs):
    p = BaseProtocol(cfg={})
    p.run_parameters = {"num_epochs": num_epochs}
    return p


def test_all_combinations_is_cartesian_product():
    p = make_protocol(num_epochs=6)
    p.get_parameter_sequence(([0, 1, 2], [10, 20]), all_combinations=True, randomize_order=False)
    seq = p.persistent_parameters["protocol_parameter_sequence"]
    assert set(seq) == {(0, 10), (0, 20), (1, 10), (1, 20), (2, 10), (2, 20)}
    assert len(seq) == 6


def test_associated_lists_when_not_all_combinations():
    p = make_protocol(num_epochs=3)
    p.get_parameter_sequence(([0, 1, 2], [10, 20, 30]), all_combinations=False, randomize_order=False)
    seq = p.persistent_parameters["protocol_parameter_sequence"]
    assert [tuple(row) for row in seq] == [(0, 10), (1, 20), (2, 30)]


def test_single_list_is_used_directly():
    p = make_protocol(num_epochs=4)
    p.get_parameter_sequence([0, 90, 180, 270], all_combinations=True, randomize_order=False)
    seq = p.persistent_parameters["protocol_parameter_sequence"]
    assert seq == [0, 90, 180, 270]


def test_sequence_repeats_to_fill_num_epochs():
    p = make_protocol(num_epochs=5)
    p.get_parameter_sequence([0, 1], all_combinations=True, randomize_order=False)
    inds = p.persistent_parameters["protocol_parameter_sequence_epoch_inds"]
    assert list(inds) == [0, 1, 0, 1, 0]  # arange(5) % 2


def test_server_error_demo_requests_a_nonexistent_stim():
    # The demo protocol must ask for a stim class that does not exist, so load_stim raises on the
    # server (demonstrating server -> client error reporting).
    from stimpack.experiment.example_protocol import ServerErrorDemo
    p = ServerErrorDemo(cfg={})
    p.get_epoch_parameters()
    assert p.epoch_stim_parameters == {"name": "NoSuchStimulus_ServerErrorDemo"}


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
    """An older stimpack. Adopting this must not change behaviour until there is something real
    to report -- the same contract as has_module."""
    assert _protocol(None).has_server_function('anything') is True


def test_has_server_function_is_true_for_a_target_that_cannot_enumerate():
    """The visual module forwards to screen subprocesses, so it is absent from the map. Absent
    means unknown, not empty -- answering False would be a wrong answer rather than no answer."""
    p = _protocol({'root': {'print_on_server'}})
    assert p.has_server_function('load_stim', target='visual') is True
