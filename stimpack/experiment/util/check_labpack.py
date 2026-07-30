"""Static checks on a labpack, run before an experiment rather than during one.

The failure mode this exists for is silence. A labpack that names something stimpack can no longer
find does not crash: the GUI opens, the protocol list populates, Record works, and the experiment is
simply wrong -- custom stimuli never loaded, or an opto call routed nowhere. Every such failure seen
so far reduces to *a name that no longer resolves*, and nothing checks names until the moment they
are used, which is when an animal is already on the rig.

Two groups of checks, split by what they cost.

The cheap ones import nothing, which is what lets them run on every GUI launch:

  tier 1  config keys stimpack no longer reads
  tier 2  every module_paths entry resolves on disk, and visual_stim directories look loadable

The rest import lab code and run each protocol, so they are opt-in (--deep) and never part of
startup -- executing arbitrary lab code on the launch path is not something a startup check should
do:

  tier 3  each protocol module imports, and each protocol constructs and produces an epoch
  tier 4  every stimulus name an epoch asks for resolves, as load_stim would resolve it
  tier 5  every call a protocol makes is addressed somewhere that exists

Tiers 4 and 5 run the protocol rather than reading it. Stimulus names and call sites are often
computed (`'Grating' if rotating else 'RotatingGrating'`), spread across load_stimuli, start_stimuli
and helpers, and the 'name' key is overloaded -- stimuli, trajectories, distributions and DAQ
channels all use it. Parsing gets that wrong; running it does not.

Two severities, and the distinction is about what happens next:

  error    stimpack will not find this, so the run will silently do the wrong thing
  warning  something is absent or ignored, which may well be deliberate for this rig
"""
import contextlib
import inspect
import os
import re
import sys
import tempfile
import warnings
from dataclasses import dataclass

from stimpack.experiment.util import config_tools
from stimpack.visual_stim.util import STIM_SUBMODULES

# module_paths entries that name a single file, and the class each is required to define. A
# directory is expected for visual_stim instead, so it is handled separately.
SINGLE_FILE_MODULES = {
    'protocol': 'BaseProtocol',
    'data': 'Data',
    'client': 'Client',
    'daq': None,
}


@dataclass(frozen=True)
class Finding:
    """One problem found in a labpack."""
    level: str      # 'error' or 'warning'
    code: str       # stable slug, e.g. 'missing-module-path'
    config: str     # the config file this came from ('' for labpack-wide findings)
    message: str

    def __str__(self):
        where = f'[{self.config}] ' if self.config else ''
        return f'{self.level.upper():7s} {where}{self.message}'


def check_config(cfg, cfg_name='', labpack_dir=None):
    """Run tiers 1-2 against one already-loaded config. Returns a list of Findings."""
    findings = []
    if labpack_dir is None:
        labpack_dir = config_tools.get_labpack_directory()

    def add(level, code, message):
        findings.append(Finding(level, code, cfg_name, message))

    # --- tier 1: keys stimpack no longer reads --------------------------------------------------
    for key in dict.fromkeys(_legacy_keys(cfg)):
        level, explanation = config_tools.LEGACY_CONFIG_KEYS[key]
        add(level, 'legacy-config-key', f"'{key}' is no longer read by stimpack: {explanation}")

    # --- data backend: is the requested one actually usable here? -------------------------------
    # data_format picks a built-in backend, and the NWB one needs pynwb, which is an optional
    # dependency. Without this the config looks fine and the GUI dies on import at start-up --
    # at the rig, with an animal on it.
    mapped = config_tools.get_data_module_paths_by_format(cfg)
    available = config_tools.get_available_data_formats(cfg)
    default_format = config_tools.get_default_data_format(cfg)
    declared = cfg.get('data_format')

    if declared is not None and str(declared).lower() not in available:
        add('error', 'unknown-data-format',
            f"data_format '{str(declared).lower()}' is not one of {available}; stimpack will fall "
            f"back to {default_format}")
    elif declared is None and mapped:
        # The lab supplied classes; which one runs is then decided by a default rather than by
        # them. Unambiguous when they mapped one format, a coin toss when they mapped several.
        add('warning', 'no-data-format-with-mapping',
            f"module_paths.data maps {sorted(mapped)} but no data_format is set, so "
            f"'{default_format}' is used by default. Set data_format to say which you mean.")
    elif mapped and str(declared).lower() not in mapped:
        # Legitimate -- custom HDF5 and stock NWB is a reasonable thing to want -- but it means
        # every launch bypasses the labpack's classes, which is worth knowing on purpose.
        add('warning', 'data-format-outside-mapping',
            f"data_format is '{str(declared).lower()}' but module_paths.data supplies classes "
            f"only for {sorted(mapped)}, so stimpack's built-in class is used")

    data_format = config_tools.get_data_format(cfg)
    if data_format in config_tools.BUILTIN_DATA_FORMATS:
        try:
            config_tools.get_builtin_data_class(cfg)
        except ImportError as e:
            add('error', 'data-backend-unavailable',
                f"data_format is '{data_format}' but its backend cannot be imported: {e}")

    # --- tier 2: does everything module_paths names actually exist? -----------------------------
    module_paths = cfg.get('module_paths') or {}
    if not module_paths:
        add('warning', 'no-module-paths',
            "no module_paths section, so this config contributes no protocols, data class, client "
            "or custom stimuli")
        return findings

    for module_name, required_class in SINGLE_FILE_MODULES.items():
        for path in config_tools.get_module_paths(cfg, module_name) if module_name in module_paths else []:
            full = _resolve(path, labpack_dir)
            if not os.path.exists(full):
                add('error', 'missing-module-path',
                    f"module_paths.{module_name} -> {path} does not exist (looked in {full})")
            elif os.path.isdir(full):
                add('error', 'module-path-is-a-directory',
                    f"module_paths.{module_name} -> {path} is a directory; a .py file is expected"
                    + (f" defining a class named '{required_class}'" if required_class else ""))

    for path in config_tools.get_module_paths(cfg, 'visual_stim') if 'visual_stim' in module_paths else []:
        findings.extend(_check_visual_stim_dir(path, labpack_dir, cfg_name))

    # --- presets ---------------------------------------------------------------------------------
    presets_dir = cfg.get('parameter_presets_dir')
    if presets_dir is None:
        add('warning', 'no-presets-dir',
            "no parameter_presets_dir, so saved parameter presets have nowhere to load from")
    elif not os.path.isdir(_resolve(presets_dir, labpack_dir)):
        add('warning', 'missing-presets-dir',
            f"parameter_presets_dir -> {presets_dir} does not exist; presets will not be found "
            f"(stimpack creates it on first save)")

    return findings


def check_labpack(labpack_dir=None, cfg_names=None, deep=False):
    """Check a labpack's configs. Returns (findings, configs_checked).

    deep=False runs tiers 1-2 (cheap, imports nothing). deep=True additionally imports the protocol
    modules and runs each protocol against a recording manager (tiers 3 and 5).
    """
    if labpack_dir is None:
        labpack_dir = config_tools.get_labpack_directory()

    if not labpack_dir or not os.path.isdir(labpack_dir):
        return [Finding('error', 'no-labpack', '',
                        f"no labpack directory set (got {labpack_dir!r}). Point stimpack at one "
                        f"with 'Labpack Dir' in the startup dialog.")], []

    if cfg_names is None:
        cfg_names = config_tools.get_available_config_files(labpack_dir)

    if not cfg_names:
        return [Finding('error', 'no-configs', '',
                        f"no configs found in {os.path.join(labpack_dir, 'configs')}")], []

    findings = []
    for cfg_name in sorted(cfg_names):
        try:
            # get_configuration_file warns about legacy keys itself. Silence that here: this check
            # reports the same keys as findings, and printing both would double every line.
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                cfg = config_tools.get_configuration_file(cfg_name, labpack_dir)
        except Exception as e:
            # A config that will not parse is a hard stop for that config, not for the check.
            findings.append(Finding('error', 'unreadable-config', cfg_name,
                                    f"could not be read: {type(e).__name__}: {e}"))
            continue
        findings.extend(check_config(cfg, cfg_name, labpack_dir))
        if deep:
            try:
                # Module paths resolve through config_tools.get_labpack_directory(), so without
                # this the check would read this labpack's configs and then load the *configured*
                # labpack's protocols -- silently checking the wrong code.
                with config_tools.using_labpack_directory(labpack_dir):
                    findings.extend(check_protocols(cfg, cfg_name, labpack_dir))
            except Exception as e:
                # The deep tiers run arbitrary lab code; a crash in one config must not lose the
                # findings from the others.
                findings.append(Finding('warning', 'deep-check-failed', cfg_name,
                                        f'could not be checked deeply: {type(e).__name__}: {e}'))

    return findings, sorted(cfg_names)


def format_report(findings, configs_checked, labpack_dir=None):
    """A human-readable report. Returns the text; the caller decides where it goes."""
    if labpack_dir is None:
        labpack_dir = config_tools.get_labpack_directory()

    errors = [f for f in findings if f.level == 'error']
    warnings_ = [f for f in findings if f.level == 'warning']

    lines = [f'Checking labpack: {labpack_dir}',
             f'Configs checked : {len(configs_checked)}'
             + (f" ({', '.join(configs_checked)})" if configs_checked else ''),
             '']

    if not findings:
        lines.append('No problems found.')
        return '\n'.join(lines)

    for finding in sorted(findings, key=lambda f: (f.level != 'error', f.config, f.code)):
        lines.append(str(finding))

    lines += ['', f'{len(errors)} error(s), {len(warnings_)} warning(s).']
    if errors:
        lines.append('Errors mean stimpack will not find what the config names, so a run using it '
                     'will silently do the wrong thing.')
    return '\n'.join(lines)


# --- internals ----------------------------------------------------------------------------------

def _resolve(path, labpack_dir):
    """Config paths are relative to the labpack directory unless absolute."""
    return path if os.path.isabs(path) else os.path.join(labpack_dir, path)


def _legacy_keys(cfg):
    """Legacy keys present anywhere in the config, in document order. Does not warn."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in config_tools.LEGACY_CONFIG_KEYS:
                    found.append(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(cfg)
    return found


def _check_visual_stim_dir(path, labpack_dir, cfg_name):
    """A visual_stim entry is a directory the server exec's stimuli/trajectory/distribution from.

    Worth its own check because this is the entry that fails most quietly: the server loads what it
    finds and warns about the rest into its own log, so from the client everything looks fine right
    up until a stimulus name does not resolve.
    """
    full = _resolve(path, labpack_dir)

    if not os.path.exists(full):
        return [Finding('error', 'missing-module-path', cfg_name,
                        f"module_paths.visual_stim -> {path} does not exist (looked in {full}); "
                        f"custom stimuli will never load")]
    if not os.path.isdir(full):
        return [Finding('error', 'visual-stim-not-a-directory', cfg_name,
                        f"module_paths.visual_stim -> {path} is a file; a directory containing "
                        f"{', '.join(s + '.py' for s in STIM_SUBMODULES)} is expected")]

    present = [s for s in STIM_SUBMODULES if os.path.exists(os.path.join(full, f'{s}.py'))]
    if not present:
        return [Finding('error', 'empty-visual-stim-dir', cfg_name,
                        f"module_paths.visual_stim -> {path} contains none of "
                        f"{', '.join(s + '.py' for s in STIM_SUBMODULES)}, so it contributes no "
                        f"stimuli")]

    missing = [s for s in STIM_SUBMODULES if s not in present]
    if missing:
        return [Finding('warning', 'partial-visual-stim-dir', cfg_name,
                        f"module_paths.visual_stim -> {path} has no "
                        f"{', '.join(s + '.py' for s in missing)}; fine if you define none, but "
                        f"referencing one by name will fail")]
    return []


# =================================================================================================
# Tiers 3 and 5: import the protocols, then see where their calls would actually go.
#
# These import and run lab code, so they are opt-in (--deep) and never part of GUI startup.
#
# Tier 5 is the reason this exists. Stimpack's RPC is fire-and-forget with no return channel: a call
# addressed to a name the server does not have is accepted, sent, and dropped. That is how
# untargeted daq_* calls silently stopped firing -- an untargeted request defaults to 'root', where
# those names are not registered, so opto did nothing for months while everything looked fine.
#
# Rather than parse the protocols (call sites are spread across load_stimuli, start_stimuli and
# helpers, and names are often computed), the check runs them against a manager that records where
# each call is addressed instead of sending it.
# =================================================================================================

class RecordingManager:
    """Stands in for MySocketClient, recording where each call is addressed instead of sending it.

    Records (target, name), where target is None for an untargeted call -- which the server routes
    to its root node.
    """

    def __init__(self, available_modules=None):
        # Real attributes, so __getattr__ cannot turn them into recorded calls.
        self.calls = []
        self.connection_broken = False
        self.available_modules = available_modules
        self.functions = {}

    def write_request_list(self, request_list):
        """MyMultiCall flushes a whole batch through here.

        Expanding it matters: protocols build most of their calls through a multicall, so recording
        this as a single 'write_request_list' call would hide every one of them -- including the
        untargeted opto calls this check exists to find.
        """
        for request in request_list:
            if isinstance(request, dict) and 'name' in request:
                self.calls.append((request.get('target'), request['name']))

    def register_function(self, function, name=None):
        self.functions[name or function.__name__] = function

    def process_queue(self):
        pass

    def close(self):
        pass

    def target(self, target_name):
        recorder = self

        class _Target:
            def __getattr__(self, name):
                if name.startswith('_'):
                    raise AttributeError(name)
                return lambda *args, **kwargs: recorder.calls.append((target_name, name))

        return _Target()

    def __getattr__(self, name):
        # Anything else is an untargeted call, which the server routes to 'root'.
        if name.startswith('_'):
            raise AttributeError(name)
        return lambda *args, **kwargs: self.calls.append((None, name))


def check_protocols(cfg, cfg_name='', labpack_dir=None, max_epochs=2):
    """Tiers 3 and 5 for one config. Returns a list of Findings."""
    from stimpack.experiment.protocol import BaseProtocol
    from stimpack.experiment.server import KNOWN_TARGETS, ROOT_FUNCTION_NAMES

    if labpack_dir is None:
        labpack_dir = config_tools.get_labpack_directory()

    findings = []

    def add(level, code, message):
        findings.append(Finding(level, code, cfg_name, message))

    # --- tier 3: does the protocol module import? -----------------------------------------------
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            modules = config_tools.load_user_module(cfg, 'protocol', allow_multiple=True)
    except Exception as e:
        add(*_classify_import_error(e, 'module_paths.protocol'))
        return findings

    if not modules:
        return findings

    # Take the classes out of the loaded module objects rather than asking get_all_subclasses,
    # which is global: every subclass ever imported stays registered, so checking several configs in
    # one process would test each one against every other user's protocols. Loading the same file
    # twice also produces two module objects sharing a __name__, so filtering by module name does
    # not scope it either -- only the module object itself does.
    protocols = list(dict.fromkeys(
        obj
        for module in modules
        for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, BaseProtocol)
        and obj.__name__ not in ('BaseProtocol', 'SharedPixMapProtocol')))
    if not protocols:
        add('warning', 'no-protocols',
            "the protocol module imported but defines no BaseProtocol subclasses, so the GUI's "
            "protocol list will be empty")
        return findings

    check_cfg = _cfg_for_checking(cfg, labpack_dir)
    stimulus_names, stim_findings = _available_stimulus_names(cfg, labpack_dir, cfg_name)
    findings.extend(stim_findings)

    skipped = []
    for rig, label in _rigs_worth_checking(check_cfg):
        rig_cfg = dict(check_cfg, current_rig_name=rig)
        for protocol_class in sorted(protocols, key=lambda p: p.__name__):
            protocol_findings, why_skipped = _check_one_protocol(
                protocol_class, rig_cfg, cfg_name, label, max_epochs,
                KNOWN_TARGETS, ROOT_FUNCTION_NAMES, stimulus_names)
            findings.extend(protocol_findings)
            if why_skipped is not None:
                skipped.append(why_skipped)

    # Say what was not covered. A check that quietly skips things reads as "all clear" when it is
    # not -- the same silence this whole module exists to remove.
    if skipped:
        unique = list(dict.fromkeys(skipped))
        findings.append(Finding(
            'warning', 'protocols-not-exercised', cfg_name,
            f"{len(unique)} of {len(protocols)} protocols could not be run with their default "
            f"parameters, so where their calls go was not checked. This is usually because a "
            f"preset supplies a run parameter the class does not default (commonly do_loco). "
            f"First: {unique[0]}"))

    # The same problem surfaces once per epoch and once per protocol sharing a base class; report
    # each distinct one once. Findings are frozen dataclasses, so they de-duplicate by value.
    return list(dict.fromkeys(findings))


def _check_one_protocol(protocol_class, cfg, cfg_name, rig_label, max_epochs,
                        known_targets, root_function_names, stimulus_names):
    name = protocol_class.__name__
    findings = []

    def add(level, code, message, rig_specific=False):
        where = f' [{rig_label}]' if rig_specific and rig_label else ''
        findings.append(Finding(level, code, cfg_name, f'{name}{where}: {message}'))

    skipped = None                    # set when the protocol could not be exercised at all

    # --- an uninterruptible wait in start_stimuli -----------------------------------------------
    # BaseProtocol.sleep drains the client's queue and returns early when the run is stopped;
    # time.sleep cannot be interrupted, so Stop is not noticed until the trial ends -- on a long
    # trial that is a long wait, and the same delay applies to an error the server reports
    # mid-trial. A protocol overriding start_stimuli has to remember to use self.sleep, and
    # stimpack's own example did not, which is what these were copied from.
    if 'start_stimuli' in protocol_class.__dict__:
        try:
            source = inspect.getsource(protocol_class.start_stimuli)
        except (OSError, TypeError):
            source = ''
        # A bare call, not self.sleep(...) or manager.sleep(...).
        bare_sleeps = len(re.findall(r'(?<![.\w])sleep\s*\(', source))
        if bare_sleeps:
            add('warning', 'uninterruptible-sleep',
                f'start_stimuli calls time.sleep {bare_sleeps} time(s); use self.sleep so Stop '
                f'takes effect during a trial rather than at the end of it')

    # --- tier 3: does it construct, and can it produce an epoch? --------------------------------
    try:
        protocol = protocol_class(cfg=cfg)
    except Exception as e:
        add('error', 'protocol-will-not-construct', f'{type(e).__name__}: {e}')
        return findings, skipped

    recorder = RecordingManager()
    protocol.save_metadata_flag = False

    # Follow the same sequence BaseClient.start_run uses. prepare_run is not optional scaffolding:
    # it is what fills in persistent_parameters (variable_protocol_parameter_names) and est_run_time,
    # and it precomputes each epoch's parameters. Skipping it makes every protocol look broken.
    #
    # Shorten the run first: precompute calls get_trial_parameters once per epoch, and a protocol
    # with hundreds of epochs would otherwise take real time to check. This is why the check covers
    # the first few epochs rather than the whole series.
    epochs = min(int(protocol.run_parameters.get('num_trials', 1) or 1), max_epochs)
    protocol.run_parameters['num_trials'] = epochs

    # Supply the run parameters a preset would. On a rig with locomotion, do_loco is required but
    # most protocol classes do not default it -- they expect the preset to. Without this, nearly
    # every protocol is skipped and tier 5 checks nothing. Setting it to match the rig also
    # exercises the locomotion branch of start_stimuli, which is where those calls live.
    if protocol.loco_available:
        protocol.run_parameters.setdefault('do_loco', True)

    with _sleep_disabled(protocol_class):
        try:
            protocol.prepare_run(manager=recorder, recompute_epoch_parameters=True)
        except Exception as e:
            # Not reported as a finding. Protocols are normally run from a saved preset, and a
            # preset supplies run parameters the class defaults omit (do_loco is the usual one), so
            # "fails with defaults" mostly is not a defect -- and when it is, it raises the moment
            # someone presses Record rather than staying quiet. Silently dropping it would be worse
            # though: the caller counts these and says how many went unchecked.
            return findings, f'{name}: {type(e).__name__}: {e}'

        for epoch in range(epochs):
            protocol.num_trials_completed = epoch
            try:
                if protocol.use_precomputed_trial_parameters:
                    protocol.load_precomputed_trial_parameters()
                else:
                    protocol.get_trial_parameters()
            except Exception as e:
                add('error', 'get-epoch-parameters-failed', f'{type(e).__name__}: {e}')
                return findings, skipped

            # --- tier 4: would load_stim resolve the names this epoch asks for? -----------------
            for stimulus in _stimulus_names_in(protocol.trial_stim_parameters):
                if stimulus not in stimulus_names:
                    add('error', 'unknown-stimulus',
                        f"loads a stimulus named '{stimulus}', which is not among the stimuli this "
                        f"config makes available. load_stim raises '0 stimulus candidates found' "
                        f"when it reaches this epoch. Check the spelling, or add the module that "
                        f"defines it to module_paths.visual_stim")

            # --- tier 5: where would this epoch's calls actually go? ----------------------------
            for method in ('load_stimuli', 'start_stimuli'):
                try:
                    getattr(protocol, method)(recorder)
                except Exception as e:
                    # Not necessarily a defect: these normally run against a live server, and a
                    # protocol may reach for something a recorder does not provide. Say so rather
                    # than claiming the protocol is broken.
                    add('warning', 'could-not-exercise',
                        f'{method}() could not be run without a server '
                        f'({type(e).__name__}: {e}), so its calls were not checked')

    # --- tier 5: judge the recorded calls --------------------------------------------------------
    for target, call in dict.fromkeys(recorder.calls):        # de-duplicated, order preserved
        if target is None:
            if call not in root_function_names:
                add('error', 'call-lands-nowhere',
                    f"{call}(...) is sent untargeted, so it is routed to the server's root node, "
                    f"where it is not defined -- the call is accepted and then dropped. "
                    f"Address it with target('{_likely_target(call)}').{call.removeprefix('daq_')}(...)")
        elif target not in known_targets:
            add('warning', 'unknown-target',
                f"target('{target}').{call}(...) names a module stimpack does not define "
                f"(known: {', '.join(sorted(known_targets))}). Fine if your rig server adds it; "
                f"otherwise the call goes nowhere")

    return findings, skipped


# --- internals for the deep tiers ----------------------------------------------------------------

def _available_stimulus_names(cfg, labpack_dir, cfg_name):
    """The stimulus class names a server running this config would resolve, and any load failures.

    load_stim resolves a name against every BaseProgram subclass loaded in the server process, so
    the set is stimpack's own stimuli plus whatever this config's module_paths.visual_stim
    directories define.

    Scoped per config on purpose. The subclass registry is global and never shrinks, so checking
    several configs in one process would let one user's stimuli vouch for another user's protocol --
    a missing stimulus would quietly pass. Core names are taken by module prefix and labpack names
    from the module objects just loaded, so neither depends on what a previous config loaded.
    """
    from stimpack.util import get_all_subclasses
    from stimpack.visual_stim.base import BaseProgram
    from stimpack.visual_stim.util import load_stim_module_from_path

    names = {klass.__name__ for klass in get_all_subclasses(BaseProgram)
             if getattr(klass, '__module__', '').startswith('stimpack.')}
    findings = []

    for index, path in enumerate(config_tools.get_module_paths(cfg, 'visual_stim')
                                 if 'visual_stim' in (cfg.get('module_paths') or {}) else []):
        # A name unique to this config, so loading does not overwrite another config's modules.
        module_name = f'_check_{abs(hash((cfg_name, index))):x}'
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                load_stim_module_from_path(_resolve(path, labpack_dir), module_name=module_name)
        except Exception as e:
            findings.append(Finding(
                'error', 'visual-stim-will-not-load', cfg_name,
                f"module_paths.visual_stim -> {path} failed to load ({type(e).__name__}: {e}), so "
                f"none of its stimuli are available"))
            continue

        for loaded in [m for key, m in sys.modules.items() if key.startswith(f'{module_name}.')]:
            names.update(obj.__name__ for obj in vars(loaded).values()
                         if isinstance(obj, type) and issubclass(obj, BaseProgram))

    return names, findings


def _stimulus_names_in(trial_stim_parameters):
    """The stimulus names one epoch would load. May be a single dict, a list of them, or None."""
    entries = (trial_stim_parameters if isinstance(trial_stim_parameters, list)
               else [trial_stim_parameters])
    return [entry['name'] for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get('name'), str)]


def _likely_target(call):
    """Best guess at the module an untargeted call meant, for the suggestion in the message.

    A daq_ prefix is the signature of the pre-target() style, where the module was part of the
    function name. Everything else is far more often a screen call.
    """
    return 'voltage_out' if call.startswith('daq_') else 'visual'


def _rigs_worth_checking(cfg):
    """One representative rig per distinct locomotion setting, as (rig_name, label).

    Checking every rig would multiply the work and mostly repeat itself: of everything a rig config
    carries, only loco_available changes whether a protocol validates (it decides whether do_loco is
    a required run parameter). Screen centre, server options and data directory do not. So check one
    rig with locomotion and one without, when the labpack has both.
    """
    rigs = list((cfg.get('rig_config') or {}).keys())
    if not rigs:
        return [(None, '')]

    representatives = {}
    for rig in rigs:
        loco = config_tools.get_loco_available(dict(cfg, current_rig_name=rig))
        representatives.setdefault(bool(loco), rig)

    label = {True: 'rigs with locomotion', False: 'rigs without locomotion'}
    return [(rig, label[loco] if len(representatives) > 1 else '')
            for loco, rig in sorted(representatives.items(), reverse=True)]


def _cfg_for_checking(cfg, labpack_dir):
    """A cfg safe to construct protocols with.

    BaseProtocol.__init__ ends with os.makedirs(parameter_preset_directory), so constructing one
    *writes to disk*. Point it at the real preset directory when that already exists -- reading real
    presets is better coverage -- and at a temporary one otherwise, so a check never creates
    directories in someone's labpack.
    """
    check_cfg = dict(cfg)
    presets_dir = cfg.get('parameter_presets_dir')
    real = os.path.join(labpack_dir, presets_dir) if presets_dir else None
    if not (real and os.path.isdir(real)):
        check_cfg['parameter_presets_dir'] = tempfile.mkdtemp(prefix='stimpack-check-')
    return check_cfg


@contextlib.contextmanager
def _sleep_disabled(protocol_class):
    """Neutralize sleep() while running a protocol.

    start_stimuli sleeps for pre_time, stim_time and tail_time, so checking a protocol would
    otherwise take exactly as long as running it for real.

    Patch the globals of the class's own methods rather than module objects. Modules hold their own
    binding (`from time import sleep`), so patching time.sleep does not reach them -- and patching
    by module *name* is not enough either: loading the same protocol file for several configs
    creates several module objects that share a name, and get_all_subclasses hands back classes
    belonging to any of them. A method's __globals__ is by definition the namespace that method's
    sleep() resolves in, so this cannot miss.
    """
    namespaces, patched = [], []
    for klass in protocol_class.__mro__:
        for attribute in vars(klass).values():
            namespace = getattr(attribute, '__globals__', None)
            if namespace is not None and 'sleep' in namespace and not any(
                    namespace is seen for seen in namespaces):
                namespaces.append(namespace)

    for namespace in namespaces:
        patched.append((namespace, namespace['sleep']))
        namespace['sleep'] = lambda *args, **kwargs: None

    # Also the method. BaseProtocol.sleep is an interruptible wait that polls the client rather
    # than calling the module-level sleep, so patching the name above does not reach it -- it
    # would poll for the full stimulus duration and the check would take as long as the run.
    had_own_sleep = 'sleep' in vars(protocol_class)
    original_method = vars(protocol_class).get('sleep')
    protocol_class.sleep = lambda self, *args, **kwargs: None
    try:
        yield
    finally:
        if had_own_sleep:
            protocol_class.sleep = original_method
        else:
            del protocol_class.sleep
        for namespace, original in patched:
            namespace['sleep'] = original


def _classify_import_error(exc, what):
    """Distinguish 'this labpack is broken' from 'this machine is not the rig'.

    A missing hardware driver is the single most likely false positive here: labpack device modules
    import nidaqmx / labjack at module level, and a client machine has neither. Reporting that as an
    error would teach people to ignore the checker.
    """
    if isinstance(exc, ImportError):
        missing = getattr(exc, 'name', None) or ''
        if missing and not missing.startswith(('stimpack', 'labpack')):
            return ('warning', 'missing-third-party-module',
                    f"{what} needs '{missing}', which is not installed here. Expected if this "
                    f"machine is not the rig; otherwise install it.")
    return ('error', 'protocol-will-not-import', f'{what}: {type(exc).__name__}: {exc}')
