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


# --- tiers 3 and 5: import the protocols, then see where their calls go --------------------------

PROTOCOL_TEMPLATE = '''
from stimpack.experiment.protocol import BaseProtocol
from stimpack.rpc.multicall import MyMultiCall

class {name}(BaseProtocol):
    def get_run_parameter_defaults(self):
        return {{'num_trials': 2, 'idle_color': 0.5, 'do_loco': False}}

    def get_protocol_parameter_defaults(self):
        return {{'pre_time': 0.0, 'stim_time': 0.0, 'tail_time': 0.0}}

    def get_trial_parameters(self):
        super().get_trial_parameters()
        self.trial_stim_parameters = {{'name': 'MovingSpot'}}

    def load_stimuli(self, manager, multicall=None):
        multicall = multicall or MyMultiCall(manager)
{body}
        multicall()
'''


def labpack_with_protocol(root, body, name='Demo'):
    cfg = good_cfg()
    make_labpack(root, cfg)
    (root / 'pack' / 'protocol' / 'my_protocol.py').write_text(
        PROTOCOL_TEMPLATE.format(name=name, body=body))
    return cfg


def deep_findings(root):
    from stimpack.experiment.util import config_tools
    cfg = check_labpack.config_tools.get_configuration_file('test_config.yaml', str(root))
    with config_tools.using_labpack_directory(str(root)):
        return check_labpack.check_protocols(cfg, 'test_config.yaml', str(root))


def test_an_untargeted_call_is_reported(tmp_path):
    """The opto bug: an untargeted call goes to root, is not defined there, and is dropped.

    Nothing at run time says so -- the call is accepted and silently discarded -- which is why this
    has to be caught before the experiment rather than during it.
    """
    labpack_with_protocol(tmp_path, "        multicall.daq_setup_pulse_wave_stream_out(freq=1)")

    findings = deep_findings(tmp_path)

    assert codes(findings, level='error') == ['call-lands-nowhere']
    assert 'daq_setup_pulse_wave_stream_out' in findings[0].message
    assert "target('voltage_out')" in findings[0].message      # suggests the right module


def test_an_untargeted_screen_call_suggests_the_visual_module(tmp_path):
    labpack_with_protocol(tmp_path, "        multicall.load_stim(name='MovingSpot')")

    findings = deep_findings(tmp_path)
    assert codes(findings, level='error') == ['call-lands-nowhere']
    assert "target('visual')" in findings[0].message


def test_untargeted_calls_through_the_manager_are_reported_too(tmp_path):
    """Not every call goes through a multicall."""
    labpack_with_protocol(tmp_path, "        manager.daq_output_step(value=1)")

    findings = deep_findings(tmp_path)
    assert codes(findings, level='error') == ['call-lands-nowhere']


def test_a_properly_targeted_call_is_not_reported(tmp_path):
    labpack_with_protocol(tmp_path, "        multicall.target('voltage_out').output_step(value=1)")
    assert deep_findings(tmp_path) == []


def test_a_real_root_function_is_not_reported(tmp_path):
    """print_on_server IS defined on root, so calling it untargeted is correct."""
    labpack_with_protocol(tmp_path, "        multicall.print_on_server('hello')")
    assert deep_findings(tmp_path) == []


def test_an_unknown_target_is_a_warning_not_an_error(tmp_path):
    """A rig server may define modules stimpack does not know about."""
    labpack_with_protocol(tmp_path, "        multicall.target('olfactometer').puff()")

    findings = deep_findings(tmp_path)
    assert codes(findings, level='error') == []
    assert codes(findings, level='warning') == ['unknown-target']


def test_a_protocol_that_will_not_import_is_an_error(tmp_path):
    make_labpack(tmp_path, good_cfg())
    (tmp_path / 'pack' / 'protocol' / 'my_protocol.py').write_text('import definitely_not_a_module\n')

    findings = deep_findings(tmp_path)
    assert codes(findings) == ['missing-third-party-module']       # not the labpack's fault
    assert findings[0].level == 'warning'


def test_a_protocol_broken_in_its_own_code_is_an_error(tmp_path):
    make_labpack(tmp_path, good_cfg())
    (tmp_path / 'pack' / 'protocol' / 'my_protocol.py').write_text('raise ValueError("typo")\n')

    findings = deep_findings(tmp_path)
    assert codes(findings) == ['protocol-will-not-import']
    assert findings[0].level == 'error'


def test_protocols_that_cannot_be_exercised_are_counted_not_hidden(tmp_path):
    """Silently skipping would read as 'all clear' -- the very silence this module exists to remove."""
    make_labpack(tmp_path, good_cfg())
    # idle_color is a required run parameter; unlike do_loco the checker does not supply it, so
    # prepare_run raises and the protocol cannot be exercised.
    (tmp_path / 'pack' / 'protocol' / 'my_protocol.py').write_text(
        PROTOCOL_TEMPLATE.format(name='Demo', body="        pass").replace(
            "'idle_color': 0.5, ", ""))

    findings = deep_findings(tmp_path)
    assert codes(findings) == ['protocols-not-exercised']
    assert '1 of 1 protocols' in findings[0].message


def test_the_deep_check_does_not_sleep_through_the_stimulus(tmp_path):
    """start_stimuli sleeps for the real stimulus duration; checking must not take that long."""
    import time
    labpack_with_protocol(tmp_path, "        pass")   # builds the labpack; the cfg is not needed here
    path = tmp_path / 'pack' / 'protocol' / 'my_protocol.py'
    path.write_text(path.read_text().replace("'pre_time': 0.0", "'pre_time': 30.0"))

    started = time.monotonic()
    deep_findings(tmp_path)
    assert time.monotonic() - started < 10, "sleep() was not neutralized"


# --- tier 4: do the stimulus names a protocol asks for resolve? ----------------------------------

CUSTOM_STIMULUS = '''
from stimpack.visual_stim.base import BaseProgram

class LabSpecialStimulus(BaseProgram):
    pass
'''


def test_an_unknown_stimulus_name_is_an_error(tmp_path):
    """This is the '0 stimulus candidates found' failure, caught before the animal is on the rig."""
    labpack_with_protocol(tmp_path, "        pass")
    path = tmp_path / 'pack' / 'protocol' / 'my_protocol.py'
    path.write_text(path.read_text().replace("'name': 'MovingSpot'", "'name': 'NoSuchStimulus'"))

    findings = deep_findings(tmp_path)

    assert codes(findings, level='error') == ['unknown-stimulus']
    assert 'NoSuchStimulus' in findings[0].message


def test_a_builtin_stimulus_name_resolves(tmp_path):
    labpack_with_protocol(tmp_path, "        pass")          # names MovingSpot, a stimpack stimulus
    assert deep_findings(tmp_path) == []


def test_a_stimulus_from_the_configs_own_visual_stim_directory_resolves(tmp_path):
    labpack_with_protocol(tmp_path, "        pass")
    (tmp_path / 'pack' / 'visual_stim' / 'lab' / 'stimuli.py').write_text(CUSTOM_STIMULUS)
    path = tmp_path / 'pack' / 'protocol' / 'my_protocol.py'
    path.write_text(path.read_text().replace("'name': 'MovingSpot'", "'name': 'LabSpecialStimulus'"))

    assert deep_findings(tmp_path) == []


def test_a_stimulus_is_not_vouched_for_by_another_configs_modules(tmp_path):
    """The BaseProgram subclass registry is global and never shrinks.

    Without per-config scoping, checking a labpack where one config loads a stimulus would let that
    stimulus satisfy every other config too -- so the missing-stimulus case, the one that actually
    happens, would quietly pass.
    """
    lender = tmp_path / 'lender'
    lender.mkdir()
    labpack_with_protocol(lender, "        pass")
    (lender / 'pack' / 'visual_stim' / 'lab' / 'stimuli.py').write_text(CUSTOM_STIMULUS)
    deep_findings(lender)                                # loads LabSpecialStimulus into this process

    borrower = tmp_path / 'borrower'
    borrower.mkdir()
    cfg = labpack_with_protocol(borrower, "        pass")
    del cfg['module_paths']['visual_stim']               # this config loads no custom stimuli
    (borrower / 'configs' / 'test_config.yaml').write_text(yaml.safe_dump(cfg))
    path = borrower / 'pack' / 'protocol' / 'my_protocol.py'
    path.write_text(path.read_text().replace("'name': 'MovingSpot'", "'name': 'LabSpecialStimulus'"))

    assert codes(deep_findings(borrower), level='error') == ['unknown-stimulus']


def test_a_visual_stim_module_that_will_not_load_is_an_error(tmp_path):
    labpack_with_protocol(tmp_path, "        pass")
    (tmp_path / 'pack' / 'visual_stim' / 'lab' / 'stimuli.py').write_text('raise ValueError("boom")\n')

    findings = deep_findings(tmp_path)
    assert 'visual-stim-will-not-load' in codes(findings, level='error')


def test_every_stimulus_in_a_multi_stimulus_trial_is_checked(tmp_path):
    """trial_stim_parameters may be a list; a bad name later in it must not be missed."""
    labpack_with_protocol(tmp_path, "        pass")
    path = tmp_path / 'pack' / 'protocol' / 'my_protocol.py'
    path.write_text(path.read_text().replace(
        "self.trial_stim_parameters = {'name': 'MovingSpot'}",
        "self.trial_stim_parameters = [{'name': 'MovingSpot'}, {'name': 'AlsoNotReal'}]"))

    findings = deep_findings(tmp_path)
    assert codes(findings, level='error') == ['unknown-stimulus']
    assert 'AlsoNotReal' in findings[0].message


# --- data backend availability --------------------------------------------------------------------

def test_unknown_data_format_is_an_error():
    findings = check_labpack.check_config({'data_format': 'parquet', 'module_paths': {}}, 'c.yaml')
    codes = [f.code for f in findings]
    assert 'unknown-data-format' in codes
    assert any(f.level == 'error' for f in findings if f.code == 'unknown-data-format')


def test_default_data_format_is_fine():
    findings = check_labpack.check_config({'module_paths': {}}, 'c.yaml')
    assert [f for f in findings if 'data' in f.code and 'format' in f.code] == []


def test_nwb_without_pynwb_is_reported_not_discovered_at_the_rig(monkeypatch):
    """A config asking for NWB on a machine without pynwb looks fine and then kills the GUI on
    launch. The checker exists to move that discovery off the rig."""
    def no_pynwb(cfg):
        raise ImportError('The NWB data backend requires pynwb.')

    monkeypatch.setattr(check_labpack.config_tools, 'get_builtin_data_class', no_pynwb)

    findings = check_labpack.check_config({'data_format': 'nwb', 'module_paths': {}}, 'c.yaml')
    matching = [f for f in findings if f.code == 'data-backend-unavailable']
    assert matching and matching[0].level == 'error'
    assert 'pynwb' in matching[0].message


def test_nwb_with_pynwb_installed_passes():
    pytest.importorskip('pynwb')
    findings = check_labpack.check_config({'data_format': 'nwb', 'module_paths': {}}, 'c.yaml')
    assert [f for f in findings if f.code == 'data-backend-unavailable'] == []


def test_a_data_module_mapped_per_format_checks_out(tmp_path):
    """module_paths.data may map a class per format. That reached os.path as a dict, so the
    checker raised TypeError on exactly the configs it exists to check."""
    cfg = good_cfg()
    cfg['data_format'] = 'nwb'
    cfg['module_paths']['data'] = {'hdf5': 'pack/data.py', 'nwb': 'pack/data_nwb.py'}
    root = make_labpack(tmp_path, cfg)
    (root / 'pack' / 'data_nwb.py').write_text('')

    findings, configs = check_labpack.check_labpack(str(tmp_path))

    assert findings == []
    assert configs == ['test_config.yaml']


def test_a_missing_module_is_still_found_inside_a_mapping(tmp_path):
    """Flattening the mapping must not cost the existence check that the flat form gets."""
    cfg = good_cfg()
    cfg['data_format'] = 'hdf5'
    cfg['module_paths']['data'] = {'hdf5': 'pack/data.py', 'nwb': 'pack/nonexistent.py'}
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))

    assert codes(findings, level='error') == ['missing-module-path']
    assert 'nonexistent.py' in findings[0].message


def test_a_mapping_with_no_data_format_is_a_warning(tmp_path):
    """The lab supplied classes; which one runs is then decided by a default rather than by them.
    Unambiguous when they mapped one format, a coin toss when they mapped several."""
    cfg = good_cfg()
    cfg.pop('data_format', None)
    cfg['module_paths']['data'] = {'hdf5': 'pack/data.py', 'nwb': 'pack/data_nwb.py'}
    root = make_labpack(tmp_path, cfg)
    (root / 'pack' / 'data_nwb.py').write_text('')

    findings, _ = check_labpack.check_labpack(str(tmp_path))

    assert codes(findings, level='warning') == ['no-data-format-with-mapping']


def test_a_data_format_outside_the_mapping_is_a_warning(tmp_path):
    """Legitimate -- custom HDF5 and stock NWB is a reasonable thing to want -- but it means every
    launch bypasses the labpack's classes, which is worth knowing on purpose rather than at 2am."""
    cfg = good_cfg()
    cfg['data_format'] = 'nwb'
    cfg['module_paths']['data'] = {'hdf5': 'pack/data.py'}
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))

    assert codes(findings, level='warning') == ['data-format-outside-mapping']
    assert "built-in" in findings[0].message


def test_a_labpack_defined_format_is_not_an_unknown_one(tmp_path):
    """A mapping may name a format stimpack has never heard of -- the class is loaded by path and
    only ever duck-typed. Validating against the built-ins alone rejected it."""
    cfg = good_cfg()
    cfg['data_format'] = 'parquet'
    cfg['module_paths']['data'] = {'parquet': 'pack/data.py'}
    make_labpack(tmp_path, cfg)

    findings, _ = check_labpack.check_labpack(str(tmp_path))

    assert findings == []


def test_a_bare_sleep_in_start_stimuli_is_reported(tmp_path):
    """BaseProtocol.sleep drains the client's queue and returns early when the run is stopped;
    time.sleep cannot be interrupted, so Stop is not noticed until the trial ends. A protocol
    overriding start_stimuli has to remember self.sleep, and stimpack's own example did not --
    which is what one lab's ten protocols were copied from."""
    cfg = good_cfg()
    root = make_labpack(tmp_path, cfg)
    (root / 'pack' / 'protocol' / 'my_protocol.py').write_text(
        'from time import sleep\n'
        'from stimpack.experiment.protocol import BaseProtocol\n\n'
        'class Sleepy(BaseProtocol):\n'
        '    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True,\n'
        '                      multicall=None):\n'
        '        sleep(1)\n'
        '        sleep(2)\n')

    findings, _ = check_labpack.check_labpack(str(tmp_path), deep=True)

    sleepy = [f for f in findings if f.code == 'uninterruptible-sleep']
    assert len(sleepy) == 1
    assert 'Sleepy' in sleepy[0].message and '2 time(s)' in sleepy[0].message


def test_self_sleep_is_not_reported(tmp_path):
    """The fix must not still look like the fault -- 'self.sleep(' contains 'sleep('."""
    cfg = good_cfg()
    root = make_labpack(tmp_path, cfg)
    (root / 'pack' / 'protocol' / 'my_protocol.py').write_text(
        'from stimpack.experiment.protocol import BaseProtocol\n\n'
        'class Awake(BaseProtocol):\n'
        '    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True,\n'
        '                      multicall=None):\n'
        '        self.sleep(1)\n')

    findings, _ = check_labpack.check_labpack(str(tmp_path), deep=True)

    assert [f for f in findings if f.code == 'uninterruptible-sleep'] == []


def test_a_protocol_that_does_not_override_start_stimuli_is_not_reported(tmp_path):
    """BaseProtocol's own start_stimuli already uses self.sleep, and every protocol inherits it."""
    make_labpack(tmp_path, good_cfg())
    (tmp_path / 'pack' / 'protocol' / 'my_protocol.py').write_text(
        'from stimpack.experiment.protocol import BaseProtocol\n\n'
        'class Plain(BaseProtocol):\n'
        '    pass\n')

    findings, _ = check_labpack.check_labpack(str(tmp_path), deep=True)

    assert [f for f in findings if f.code == 'uninterruptible-sleep'] == []
