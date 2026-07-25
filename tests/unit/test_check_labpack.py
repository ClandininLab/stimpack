"""Unit tests for the labpack preflight (tiers 1-2).

These build small labpack directories on disk rather than mocking, because the whole point of the
check is whether paths named in a config resolve on a real filesystem.
"""
import pytest

pytest.importorskip("yaml")
pytest.importorskip("numpy")
pytest.importorskip("platformdirs")

import yaml  # noqa: E402

from stimpack.experiment.util import check_labpack  # noqa: E402

pytestmark = pytest.mark.unit


def make_labpack(root, cfg, cfg_name='test_config.yaml', package='pack'):
    """A minimal labpack on disk: a config, a package with the modules it names, and presets."""
    (root / 'configs').mkdir(exist_ok=True)
    (root / 'configs' / cfg_name).write_text(yaml.safe_dump(cfg, sort_keys=False))

    pkg = root / package
    (pkg / 'protocol').mkdir(parents=True, exist_ok=True)
    (pkg / 'device').mkdir(parents=True, exist_ok=True)
    (pkg / 'protocol' / 'my_protocol.py').write_text('')
    (pkg / 'data.py').write_text('')
    (pkg / 'client.py').write_text('')
    (pkg / 'device' / 'daq.py').write_text('')

    stim = pkg / 'visual_stim' / 'lab'
    stim.mkdir(parents=True, exist_ok=True)
    for submodule in ('stimuli', 'trajectory', 'distribution'):
        (stim / f'{submodule}.py').write_text('')

    (root / 'presets').mkdir(exist_ok=True)
    return root


def good_cfg(package='pack'):
    return {
        'experimenter': 'tester',
        'rig_config': {'rig_a': {'screen_center': [0, 0]}},
        'parameter_presets_dir': 'presets',
        'module_paths': {
            'protocol': [f'{package}/protocol/my_protocol.py'],
            'data': f'{package}/data.py',
            'client': f'{package}/client.py',
            'daq': f'{package}/device/daq.py',
            'visual_stim': [f'{package}/visual_stim/lab'],
        },
    }


def codes(findings, level=None):
    return sorted(f.code for f in findings if level is None or f.level == level)


def test_a_healthy_labpack_reports_nothing(tmp_path):
    make_labpack(tmp_path, good_cfg())
    findings, configs = check_labpack.check_labpack(str(tmp_path))
    assert findings == []
    assert configs == ['test_config.yaml']


# --- tier 1: keys stimpack no longer reads -------------------------------------------------------

def test_legacy_visual_stim_key_is_an_error(tmp_path):
    """The exact breakage this check exists for: stimuli silently never load.

    It must be an ERROR, not a warning -- a warning exits 0, so a CI gate would pass a labpack whose
    custom stimuli never load.
    """
    cfg = good_cfg()
    cfg['rig_config']['rig_a']['server_options'] = {'visual_stim_module_paths': ['pack/visual_stim/lab']}
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))

    assert 'legacy-config-key' in codes(findings, level='error')
    assert any('module_paths.visual_stim' in f.message for f in findings)


def test_a_legacy_key_with_visible_consequences_is_only_a_warning(tmp_path):
    """disp_server_id being ignored shows up as the wrong display, not as a silently wrong run."""
    cfg = good_cfg()
    cfg['rig_config']['rig_a']['disp_server_id'] = 2
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))

    assert codes(findings, level='error') == []
    assert 'legacy-config-key' in codes(findings, level='warning')


def test_legacy_keys_are_found_however_deeply_nested(tmp_path):
    cfg = good_cfg()
    cfg['rig_config']['rig_a'] = {'a': {'b': [{'c': {'visual_stim_module_paths': []}}]}}
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert 'legacy-config-key' in codes(findings, level='error')


# --- tier 2: does what the config names exist? ---------------------------------------------------

def test_a_missing_module_path_is_an_error(tmp_path):
    cfg = good_cfg()
    cfg['module_paths']['protocol'] = ['pack/protocol/nonexistent.py']
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))

    assert codes(findings, level='error') == ['missing-module-path']
    assert 'nonexistent.py' in findings[0].message


def test_a_missing_visual_stim_directory_is_an_error(tmp_path):
    cfg = good_cfg()
    cfg['module_paths']['visual_stim'] = ['pack/visual_stim/gone']
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert codes(findings, level='error') == ['missing-module-path']


def test_a_visual_stim_directory_with_no_stim_files_is_an_error(tmp_path):
    """The path resolves, so a plain existence check passes -- but it contributes no stimuli."""
    cfg = good_cfg()
    make_labpack(tmp_path, cfg)
    empty = tmp_path / 'pack' / 'visual_stim' / 'empty'
    empty.mkdir(parents=True)
    cfg['module_paths']['visual_stim'] = ['pack/visual_stim/empty']
    (tmp_path / 'configs' / 'test_config.yaml').write_text(yaml.safe_dump(cfg))

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert codes(findings, level='error') == ['empty-visual-stim-dir']


def test_a_partial_visual_stim_directory_is_only_a_warning(tmp_path):
    """Defining stimuli but no custom trajectories is normal."""
    cfg = good_cfg()
    make_labpack(tmp_path, cfg)
    (tmp_path / 'pack' / 'visual_stim' / 'lab' / 'trajectory.py').unlink()

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert codes(findings, level='error') == []
    assert codes(findings, level='warning') == ['partial-visual-stim-dir']


def test_a_single_file_module_pointing_at_a_directory_is_an_error(tmp_path):
    cfg = good_cfg()
    cfg['module_paths']['data'] = 'pack/protocol'
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert codes(findings, level='error') == ['module-path-is-a-directory']
    assert "'Data'" in findings[0].message          # says which class was expected


def test_a_config_with_no_visual_stim_entry_is_fine(tmp_path):
    """A protocol using only stimpack's built-in stimuli needs no visual_stim path."""
    cfg = good_cfg()
    del cfg['module_paths']['visual_stim']
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert findings == []


def test_absolute_module_paths_are_not_resolved_against_the_labpack(tmp_path):
    cfg = good_cfg()
    cfg['module_paths']['data'] = '/nonexistent/absolute/data.py'
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert codes(findings, level='error') == ['missing-module-path']
    assert '/nonexistent/absolute/data.py' in findings[0].message


# --- presets and whole-labpack conditions --------------------------------------------------------

def test_a_missing_presets_directory_is_only_a_warning(tmp_path):
    """Stimpack creates it on first save, so its absence is not a broken run."""
    cfg = good_cfg()
    cfg['parameter_presets_dir'] = 'presets/nobody'
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert codes(findings, level='error') == []
    assert codes(findings, level='warning') == ['missing-presets-dir']


def test_a_labpack_directory_that_does_not_exist_is_an_error(tmp_path):
    findings, configs = check_labpack.check_labpack(str(tmp_path / 'nope'))
    assert codes(findings) == ['no-labpack']
    assert configs == []


def test_a_labpack_with_no_configs_is_an_error(tmp_path):
    (tmp_path / 'configs').mkdir()
    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert codes(findings) == ['no-configs']


def test_an_unreadable_config_does_not_stop_the_other_configs(tmp_path):
    make_labpack(tmp_path, good_cfg(), cfg_name='fine.yaml')
    (tmp_path / 'configs' / 'broken.yaml').write_text('key: [unclosed\n')

    findings, configs = check_labpack.check_labpack(str(tmp_path))

    assert codes(findings) == ['unreadable-config']
    assert sorted(configs) == ['broken.yaml', 'fine.yaml']      # the good one was still checked


def test_configs_can_use_python_tuple_tags(tmp_path):
    """Presets and configs use !!python/tuple; plain safe_load would raise on them."""
    make_labpack(tmp_path, good_cfg())
    path = tmp_path / 'configs' / 'test_config.yaml'
    path.write_text(path.read_text() + "\nsome_tuple: !!python/tuple [1, 2]\n")

    findings, _ = check_labpack.check_labpack(str(tmp_path))
    assert findings == []                                        # parsed, not reported as unreadable


# --- the report ----------------------------------------------------------------------------------

def test_report_lists_errors_before_warnings(tmp_path):
    cfg = good_cfg()
    cfg['parameter_presets_dir'] = 'presets/nobody'               # warning
    cfg['module_paths']['data'] = 'pack/gone.py'                  # error
    make_labpack(tmp_path, cfg)

    findings, configs = check_labpack.check_labpack(str(tmp_path))
    report = check_labpack.format_report(findings, configs, str(tmp_path))

    assert report.index('ERROR') < report.index('WARNING')
    assert '1 error(s), 1 warning(s).' in report


def test_report_says_so_when_nothing_is_wrong(tmp_path):
    make_labpack(tmp_path, good_cfg())
    findings, configs = check_labpack.check_labpack(str(tmp_path))
    assert 'No problems found.' in check_labpack.format_report(findings, configs, str(tmp_path))
