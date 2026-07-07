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
