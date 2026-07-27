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


def test_the_module_name_says_which_file_it_came_from(tmp_path):
    """A bare hash is unique but meaningless in a traceback; lead with the filename."""
    (tmp_path / 'pack').mkdir()
    (tmp_path / 'pack' / 'mc_protocol.py').write_text('')

    name = config_tools.user_module_sys_name('protocol', str(tmp_path / 'pack' / 'mc_protocol.py'))

    assert name.startswith(f'{config_tools.USER_MODULE_NAMESPACE}.protocol.mc_protocol_')


def test_same_filename_in_two_labpacks_still_gets_distinct_names(tmp_path):
    """The stem is for humans; the path hash is what keeps them apart."""
    names = set()
    for lab in ('lab_a', 'lab_b'):
        (tmp_path / lab).mkdir()
        (tmp_path / lab / 'mc_protocol.py').write_text('')
        names.add(config_tools.user_module_sys_name('protocol', str(tmp_path / lab / 'mc_protocol.py')))

    assert len(names) == 2


def test_module_names_are_valid_python_identifiers(tmp_path):
    """Filenames can contain characters a module name cannot."""
    (tmp_path / '2 weird-name!.py').write_text('')

    name = config_tools.user_module_sys_name('data', str(tmp_path / '2 weird-name!.py'))

    assert all(part.isidentifier() for part in name.split('.')), name


# --- lab-wide config -----------------------------------------------------------------------------

def _labpack(tmp_path, configs):
    """A labpack directory holding the given {filename: yaml text} configs."""
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    for name, text in configs.items():
        (tmp_path / 'configs' / name).write_text(text)
    return str(tmp_path)


def test_lab_config_supplies_defaults_under_each_config(tmp_path):
    """Settings shared by everyone in the lab live in one file instead of being copied into every
    rig's config, where they drift."""
    labpack = _labpack(tmp_path, {
        'lab_config.yaml': 'lab: Clandinin\ninstitution: Stanford\nexperimenter: nobody\n',
        'rig_a.yaml': 'experimenter: alice\n',
    })

    cfg = config_tools.get_configuration_file('rig_a.yaml', labpack)

    assert cfg['lab'] == 'Clandinin'          # inherited
    assert cfg['institution'] == 'Stanford'   # inherited
    assert cfg['experimenter'] == 'alice'     # the rig's own value wins


def test_lab_config_merges_nested_dicts_rather_than_replacing_them(tmp_path):
    labpack = _labpack(tmp_path, {
        'lab_config.yaml': 'subject_metadata:\n  genotype: [wt, mutant]\n  sex: [F, M]\n',
        'rig_a.yaml': 'subject_metadata:\n  sex: [F]\n  prep: [in vivo]\n',
    })

    cfg = config_tools.get_configuration_file('rig_a.yaml', labpack)

    assert cfg['subject_metadata']['genotype'] == ['wt', 'mutant']   # kept from the lab config
    assert cfg['subject_metadata']['prep'] == ['in vivo']            # added by the rig
    assert cfg['subject_metadata']['sex'] == ['F', 'M']              # lists union, rig's first


def test_merge_configs_leaves_its_inputs_alone():
    """deepmerge writes into its first argument. get_configuration_file re-reads the lab config
    each time so it would not notice, but any caller holding a config across two merges would get
    the first merge's result folded into the second."""
    base = {'rig_config': {'shared': {'screen_center': [0, 0]}}, 'lab': 'X'}
    merged_a = config_tools.merge_configs(base, {'rig_config': {'a': {'screen_center': [1, 1]}}})
    merged_b = config_tools.merge_configs(base, {'rig_config': {'b': {'screen_center': [2, 2]}}})

    assert set(base['rig_config']) == {'shared'}          # the base was not written into
    assert set(merged_a['rig_config']) == {'shared', 'a'}
    assert set(merged_b['rig_config']) == {'shared', 'b'}  # not {'shared', 'a', 'b'}


def test_lab_config_does_not_leak_between_configs(tmp_path):
    """The same guarantee end to end, through the loader."""
    labpack = _labpack(tmp_path, {
        'lab_config.yaml': 'rig_config:\n  shared: {screen_center: [0, 0]}\n',
        'rig_a.yaml': 'rig_config:\n  a: {screen_center: [1, 1]}\n',
        'rig_b.yaml': 'rig_config:\n  b: {screen_center: [2, 2]}\n',
    })

    config_tools.get_configuration_file('rig_a.yaml', labpack)
    cfg_b = config_tools.get_configuration_file('rig_b.yaml', labpack)

    assert set(cfg_b['rig_config']) == {'shared', 'b'}      # not 'a'


def test_lab_config_is_not_offered_as_a_config_to_choose(tmp_path):
    labpack = _labpack(tmp_path, {'lab_config.yaml': 'lab: X\n', 'rig_a.yaml': 'experimenter: a\n'})
    assert config_tools.get_available_config_files(labpack) == ['rig_a.yaml']


def test_a_labpack_without_a_lab_config_is_unaffected(tmp_path):
    labpack = _labpack(tmp_path, {'rig_a.yaml': 'experimenter: alice\n'})
    assert config_tools.get_lab_config(labpack) is None
    assert config_tools.get_configuration_file('rig_a.yaml', labpack)['experimenter'] == 'alice'


def test_merging_can_be_turned_off(tmp_path):
    labpack = _labpack(tmp_path, {'lab_config.yaml': 'lab: X\n', 'rig_a.yaml': 'experimenter: a\n'})
    cfg = config_tools.get_configuration_file('rig_a.yaml', labpack, merge_lab_config=False)
    assert 'lab' not in cfg


# --- choosing a built-in data backend --------------------------------------------------------------

def test_data_format_defaults_to_hdf5():
    assert config_tools.get_data_format({}) == 'hdf5'
    assert config_tools.get_builtin_data_class({}).__name__ == 'BaseData'


def test_data_format_is_case_insensitive():
    assert config_tools.get_data_format({'data_format': 'NWB'}) == 'nwb'


def test_unknown_data_format_warns_and_falls_back():
    with pytest.warns(UserWarning, match='Unknown data_format'):
        assert config_tools.get_data_format({'data_format': 'parquet'}) == 'hdf5'


def test_nwb_data_class_is_resolved_on_demand():
    pytest.importorskip('pynwb')
    cls = config_tools.get_builtin_data_class({'data_format': 'nwb'})
    assert cls.__name__ == 'NWBData'
    assert cls.output_is_directory is True
