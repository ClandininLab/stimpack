"""Unit tests for stimpack.experiment.util.config_tools — safe YAML loading + config navigation."""
import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

from stimpack.experiment.util import config_tools

pytestmark = pytest.mark.unit


def test_tuple_safe_loader_preserves_tuples():
    text = "center: !!python/tuple\n- 0\n- 0\nwh:\n- !!python/tuple\n  - 10\n  - 7.14\n"
    data = config_tools.safe_load_yaml_with_tuples(text)
    assert data["center"] == (0, 0)
    assert data["wh"] == [(10, 7.14)]


def test_tuple_safe_loader_blocks_arbitrary_code():
    # Regression (#11): the loader must refuse !!python/object/apply (arbitrary code execution).
    with pytest.raises(yaml.YAMLError):
        config_tools.safe_load_yaml_with_tuples("!!python/object/apply:os.system ['echo pwned']")


def test_rig_getters_tolerate_missing_rig_config():
    # Regression (#20): a config without rig_config must fall back, not raise AttributeError.
    cfg = {"current_rig_name": "nope"}
    assert config_tools.get_screen_center(cfg) == [0, 0]
    assert config_tools.get_loco_available(cfg) is True
    assert config_tools.get_available_rig_configs({}) == []


def test_legacy_config_key_is_reported():
    # A config still listing custom stimuli under server_options.visual_stim_module_paths parses and
    # runs fine, but stimpack never reads that key — so the stimuli are silently never loaded.
    cfg = {'rig_config': {'r1': {'server_options': {
        'use_remote_server': True,
        'visual_stim_module_paths': ['/some/path/visual_stim/mylab']}}}}

    with pytest.warns(UserWarning, match='module_paths.visual_stim'):
        found = config_tools.warn_about_legacy_config_keys(cfg, 'mylab_config.yaml')

    assert found == ['visual_stim_module_paths']


def test_current_config_produces_no_legacy_warning():
    cfg = {'module_paths': {'visual_stim': ['labpack/visual_stim/example']},
           'rig_config': {'r1': {'server_options': {'use_remote_server': False}}}}
    assert config_tools.warn_about_legacy_config_keys(cfg) == []


def test_rig_getters_read_present_values():
    cfg = {"current_rig_name": "rig1",
           "rig_config": {"rig1": {"screen_center": [5, -5], "loco_available": False}}}
    assert config_tools.get_screen_center(cfg) == [5, -5]
    assert config_tools.get_loco_available(cfg) is False
    assert config_tools.get_available_rig_configs(cfg) == ["rig1"]
