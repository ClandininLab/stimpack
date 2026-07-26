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


# --- user modules are namespaced and keyed on their file (#21) -----------------------------------

def test_two_configs_naming_different_files_get_different_modules(tmp_path):
    """Registering under the bare config key made one config's module serve another's.

    'data', 'client', 'protocol' and 'daq' are ordinary words. Keyed on those, the second config to
    ask for 'data' was handed the first config's module -- reported only as "already loaded, using
    cached version", which reads as an optimization rather than as running someone else's code.
    """
    for owner in ('alice', 'bob'):
        (tmp_path / owner).mkdir()
        (tmp_path / owner / 'data.py').write_text(f"class Data:\n    owner = '{owner}'\n")

    loaded = {}
    for owner in ('alice', 'bob'):
        cfg = {'module_paths': {'data': f'{owner}/data.py'}}
        with config_tools.using_labpack_directory(str(tmp_path)):
            loaded[owner] = config_tools.load_user_module(cfg, 'data')[0]

    assert loaded['alice'].Data.owner == 'alice'
    assert loaded['bob'].Data.owner == 'bob'


def test_user_modules_do_not_squat_on_generic_names(tmp_path):
    """sys.modules['data'] would collide with any installed package of that name, both ways."""
    import sys

    (tmp_path / 'pack').mkdir()
    (tmp_path / 'pack' / 'data.py').write_text('class Data:\n    pass\n')
    cfg = {'module_paths': {'data': 'pack/data.py'}}

    with config_tools.using_labpack_directory(str(tmp_path)):
        config_tools.load_user_module(cfg, 'data')

    assert 'data' not in sys.modules
    assert any(key.startswith(f'{config_tools.USER_MODULE_NAMESPACE}.data.') for key in sys.modules)


def test_the_same_file_is_imported_once(tmp_path):
    """Several configs share a protocol file; re-executing it per config would make duplicate
    classes, and every one of them stays registered as a BaseProtocol subclass forever."""
    (tmp_path / 'pack').mkdir()
    (tmp_path / 'pack' / 'data.py').write_text('class Data:\n    pass\n')
    cfg = {'module_paths': {'data': 'pack/data.py'}}

    with config_tools.using_labpack_directory(str(tmp_path)):
        first = config_tools.load_user_module(cfg, 'data')[0]
        second = config_tools.load_user_module(cfg, 'data')[0]

    assert first is second
    assert first.Data is second.Data
