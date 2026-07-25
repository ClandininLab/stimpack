"""Static checks on a labpack, run before an experiment rather than during one.

The failure mode this exists for is silence. A labpack that names something stimpack can no longer
find does not crash: the GUI opens, the protocol list populates, Record works, and the experiment is
simply wrong -- custom stimuli never loaded, or an opto call routed nowhere. Every such failure seen
so far reduces to *a name that no longer resolves*, and nothing checks names until the moment they
are used, which is when an animal is already on the rig.

These checks are deliberately cheap and import nothing:

  tier 1  config keys stimpack no longer reads
  tier 2  every module_paths entry resolves on disk, and visual_stim directories look loadable

That restraint is what lets them run on every GUI launch. Checks that must import user code (do the
protocols import? do the stimulus names they reference exist?) are a separate, opt-in tier -- running
arbitrary lab code on the launch path is not something a startup check should do.

Two severities, and the distinction is about what happens next:

  error    stimpack will not find this, so the run will silently do the wrong thing
  warning  something is absent or ignored, which may well be deliberate for this rig
"""
import os
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


def check_labpack(labpack_dir=None, cfg_names=None):
    """Run tiers 1-2 across a labpack's configs. Returns (findings, configs_checked)."""
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
