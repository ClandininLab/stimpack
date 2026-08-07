"""
Reading labpack configs and loading the modules they name.

A *labpack* is a lab's own directory of protocols, data classes, rig configs, stimuli and device
drivers, kept outside stimpack. A config file selects a rig and points at those modules by file
path; this module finds the config, merges in any lab-wide defaults, and imports the modules.

Loading is by path rather than by package name, so a labpack need not be installed and may be
called whatever a lab likes. The cost is that a path which no longer resolves fails quietly --
which is what :mod:`stimpack.experiment.util.check_labpack` exists to catch.
"""
import contextlib
from copy import deepcopy
import hashlib
import importlib
import os
import re
import glob
from platformdirs import user_config_dir
import yaml
import sys
import types
from typing import Any, Optional
import warnings

from stimpack.util import ROOT_DIR

from deepmerge import Merger
from importlib.util import spec_from_file_location, module_from_spec


class TupleSafeLoader(yaml.SafeLoader):
    """A yaml.SafeLoader that also reconstructs !!python/tuple.

    Preset (`<Protocol>.yaml`) and ensemble (`.spens`) files are written with the default yaml
    dumper, so tuple-valued parameters (e.g. ``center: (0, 0)`` or a ``width_height`` list of
    ``(w, h)`` tuples) are serialized as ``!!python/tuple``. A plain SafeLoader refuses those tags;
    the full yaml.Loader honors them but also honors dangerous constructors such as
    ``!!python/object/apply:os.system`` (arbitrary code execution on load). This loader permits only
    the tuple tag, preserving the on-disk format while refusing arbitrary object construction.
    """


TupleSafeLoader.add_constructor(
    'tag:yaml.org,2002:python/tuple',
    lambda loader, node: tuple(loader.construct_sequence(node, deep=True)))


def safe_load_yaml_with_tuples(stream):
    """yaml.safe_load extended to reconstruct !!python/tuple; safe against arbitrary-code YAML."""
    return yaml.load(stream, Loader=TupleSafeLoader)


class TupleSafeDumper(yaml.SafeDumper):
    """Writes exactly what TupleSafeLoader can read: plain YAML, plus ``!!python/tuple``.

    These files used to be written with the default yaml.Dumper, which serializes whatever Python
    type it is handed. That made the writer and the reader disagree: anything beyond plain data and
    tuples produced a file stimpack could write and then refuse to load. It happened -- run
    parameters became a dict subclass in 0.3, the dumper tagged it
    ``!!python/object/new:...RunParameters``, and selecting a protocol with a saved preset aborted
    the GUI.

    Basing this on SafeDumper makes that a RepresenterError at save time, in front of whoever
    introduced the type, rather than a file that fails later on a rig.

    The tuple tag stays, and is not decoration: a protocol parameter given as a *list* of more than
    one value is one that varies from trial to trial (see BaseProtocol.process_input_parameters),
    while a tuple is a single value with components. Writing ``center: (5, -5)`` as ``[5, -5]``
    would not lose a type, it would turn one centred stimulus into two trials at different
    positions.
    """


TupleSafeDumper.add_representer(
    tuple,
    lambda dumper, data: dumper.represent_sequence('tag:yaml.org,2002:python/tuple', data))

# RunParameters is a mapping and is written as one. Registered here rather than left to
# inheritance: add_representer snapshots the base class's table on its first call, so whichever of
# the two modules imports second would otherwise not be seen by the other.
from stimpack.experiment.deprecated_names import _register_run_parameters_representer  # noqa: E402

_register_run_parameters_representer(TupleSafeDumper)


def safe_dump_yaml_with_tuples(data, stream=None, **kwargs):
    """Counterpart to safe_load_yaml_with_tuples. Raises on any type neither can round-trip."""
    return yaml.dump(data, stream, Dumper=TupleSafeDumper, **kwargs)


# Prefix for every labpack module registered in sys.modules.
#
# Deliberately a fixed name owned by stimpack, rather than the labpack's own package name. A labpack
# is a real installed package: sys.modules['clandinin_labpack'] is that package, and registering
# synthesized modules underneath it would mean squatting inside someone else's namespace -- the same
# mistake as the bare 'protocol'/'data' names this replaced, one level up. It is also not reliably
# knowable: the repository name, the directory name and the package name need not agree, and a
# module_paths entry may be an absolute path outside the labpack entirely. Which labpack a module
# came from is recorded where it cannot go stale -- the module's __file__.
USER_MODULE_NAMESPACE = 'stimpack_labpack'


def _module_identifier(full_module_path: str, hash_length: int = 8) -> str:
    """A readable, unique identifier for a file: its stem plus a hash of its absolute path.

    The stem carries it: 'mc_protocol_062271c8' says which file a traceback is in, where a bare hash
    says nothing. The hash is only the disambiguator, for two labpacks that both have a
    protocol/mc_protocol.py -- it has to stay because keying on the path is the whole point.
    """
    stem = os.path.splitext(os.path.basename(full_module_path))[0]
    stem = re.sub(r'\W', '_', stem).strip('_') or 'module'
    if stem[0].isdigit():
        stem = f'_{stem}'
    digest = hashlib.sha1(os.path.realpath(full_module_path).encode('utf-8')).hexdigest()
    return f'{stem}_{digest[:hash_length]}'


def get_stimpack_config_directory(ensure_exists=True):
    """Where stimpack keeps its own settings, notably the recorded path to the labpack."""
    return user_config_dir(appname="stimpack", ensure_exists=ensure_exists)

# Set by using_labpack_directory() below, and consulted by get_labpack_directory() ahead of the
# recorded path. Module paths in a config are resolved through get_labpack_directory(), so without
# an override there is no way to work with a labpack other than the configured one: you would find
# one labpack's configs and then load another labpack's modules.
_labpack_directory_override = None


@contextlib.contextmanager
def using_labpack_directory(path):
    """Temporarily treat `path` as the labpack directory, without touching path_to_labpack.txt.

    Pass None to mean "use the configured one", so callers can wrap unconditionally.
    """
    global _labpack_directory_override
    previous = _labpack_directory_override
    if path is not None:
        _labpack_directory_override = path
    try:
        yield
    finally:
        _labpack_directory_override = previous


def get_labpack_directory():
    """The labpack currently in use -- an override if one is active, else the recorded path."""
    if _labpack_directory_override is not None:
        return _labpack_directory_override

    stimpack_config_dir = get_stimpack_config_directory(ensure_exists=False)
    path_to_labpack = os.path.join(stimpack_config_dir, 'path_to_labpack.txt')
    if os.path.exists(path_to_labpack):
        with open(path_to_labpack) as path_file:
            labpack_path = path_file.read().strip()
        if len(get_available_config_files(labpack_path)) == 0:
            labpack_path = ''
    else:
        labpack_path = ''

    return labpack_path

def set_labpack_directory(path):
    """Record which labpack to use from now on. Written to stimpack's config directory."""
    stimpack_config_dir = get_stimpack_config_directory(ensure_exists=True)
    path_to_labpack = os.path.join(stimpack_config_dir, 'path_to_labpack.txt')
    with open(path_to_labpack, "w") as text_file:
        text_file.write(path)

# %% Functions for finding and loading user configuration files

# Built-in storage backends, keyed by the config's data_format value. Values are import paths
# rather than classes so that importing config_tools does not pull in pynwb, which is optional.
BUILTIN_DATA_FORMATS = {
    'hdf5': ('stimpack.experiment.data', 'BaseData'),
    'nwb':  ('stimpack.experiment.data_nwb', 'NWBData'),
    # The layout stimpack wrote before it renamed epoch -> trial and epoch run -> series.
    # Same code, old names, so analysis that walks epoch_runs/.../epochs keeps working.
    'legacy_hdf5': ('stimpack.experiment.data_legacy', 'LegacyHdf5Data'),
}

# A labpack may put settings shared by everyone in the lab in configs/<LAB_CONFIG_NAME>. It is
# merged underneath each individual config, so lab-wide values (institution, lab name, a shared
# subject_metadata schema, ...) live in one place instead of being copied into every rig's config
# and drifting. It is not itself selectable as a config -- see get_available_config_files.
LAB_CONFIG_NAME = 'lab_config.yaml'


def get_default_config():
    """A minimal config, used when no labpack config is available."""
    return {'experimenter': 'JohnDoe',
            'subject_metadata': {},
            'current_rig_name': 'default',
            'current_cfg_name': 'default',
            'rig_config' : {'default': {'screen_center': [0, 0]
                                        }
                            },
            'loco_available': True
            }

def user_config_directory_exists(labpack_dir=None):
    """Whether the labpack has a ``configs/`` directory."""
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()
    if not labpack_dir.strip()=="" and os.path.exists(os.path.join(labpack_dir, 'configs')):
        return True
    else:
        return False

def get_available_config_files(labpack_dir=None):
    """Config files the startup dialog offers, excluding the lab-wide one."""
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()
    if user_config_directory_exists(labpack_dir):
        cfg_names = [os.path.split(f)[1] for f in glob.glob(os.path.join(labpack_dir, 'configs', '*.yaml'))]
    else:
        cfg_names = []

    # lab_config.yaml is merged into every config rather than being chosen as one.
    cfg_names = [x for x in cfg_names if x != LAB_CONFIG_NAME]
        
    return cfg_names


def merge_configs(base_cfg: dict, cfg: dict) -> dict:
    """
    Merge cfg over base_cfg, deeply. Values in cfg win.

    Dicts merge key by key, so a config can override one rig without restating the others; lists
    concatenate without duplicating; anything else is replaced outright.
    """
    merger = Merger(
        [
            (list, ["append_unique"]),   # lists: add new items, but only if they are not present
            (dict, ["merge"]),           # dicts: merge deeply
        ],
        ["override"],                    # everything else: the later value wins
        ["override"],                    # and likewise when the two types disagree
    )
    # deepcopy the base: Merger.merge writes into its first argument, and base_cfg is the lab-wide
    # config, which would then accumulate one rig's settings and hand them to the next caller.
    return merger.merge(deepcopy(base_cfg), cfg)


def get_configuration_file(cfg_name: str, labpack_dir: Optional[str] = None,
                           merge_lab_config: bool = True) -> dict[str, Any]:
    """Returns config, as dictionary, from  labpack_directory/configs/ based on cfg_name.yaml

    If the labpack has a lab_config.yaml, its contents are used as defaults underneath this
    config. Pass merge_lab_config=False to read a config exactly as written on disk.
    """
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()

    cfg_path = os.path.join(labpack_dir, 'configs', cfg_name)
    if os.path.exists(cfg_path):
        with open(cfg_path, 'r') as ymlfile:
            # Same loader as presets. Plain safe_load raises on !!python/tuple, so a config could
            # not express a tuple even though a preset right next to it could -- an inconsistency
            # with no reason behind it. This loader accepts tuples and nothing else dangerous.
            cfg = safe_load_yaml_with_tuples(ymlfile)
    else:
        cfg = get_default_config()

    if merge_lab_config and cfg_name != LAB_CONFIG_NAME:
        lab_cfg = get_lab_config(labpack_dir)
        if lab_cfg is not None:
            cfg = merge_configs(lab_cfg, cfg)

    warn_about_legacy_config_keys(cfg, cfg_name)

    return cfg


def get_lab_config(labpack_dir: Optional[str] = None) -> Optional[dict[str, Any]]:
    """The labpack's lab-wide config, or None if it has none."""
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()
    if labpack_dir is None or not os.path.exists(os.path.join(labpack_dir, 'configs', LAB_CONFIG_NAME)):
        return None
    return get_configuration_file(LAB_CONFIG_NAME, labpack_dir, merge_lab_config=False)


# Keys that stimpack used to honor but no longer reads. A config still carrying one of these looks
# fine and loads fine, but the setting is silently ignored -- so warn loudly instead.
#
# Each maps to (severity, explanation). Severity is about what the experiment does next, not about
# how old the key is:
#   'error'   the run will silently do the wrong thing, and nothing on screen says so
#   'warning' the setting is ignored, but the consequence is visible or benign
LEGACY_CONFIG_KEYS = {
    'visual_stim_module_paths': (
        'error',
        "custom stimulus modules are no longer read from server_options; move them to "
        "module_paths.visual_stim (a list of directories), or the stimuli will never be loaded on "
        "the server and referencing them fails with '0 stimulus candidates found'"),
    'disp_server_id': (
        'warning',
        "no longer read; select the display with the Screen's display_index / x_display in your "
        "rig server script"),
}


def warn_about_legacy_config_keys(cfg, cfg_name: str = '') -> list[str]:
    """Warn about config keys stimpack no longer reads. Returns the legacy keys found.

    These are silent failures otherwise: the YAML parses, the run starts, and the setting simply has
    no effect.
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in LEGACY_CONFIG_KEYS:
                    found.append(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(cfg)

    where = f' in {cfg_name}' if cfg_name else ''
    for key in dict.fromkeys(found):     # de-duplicated, order preserved
        _, explanation = LEGACY_CONFIG_KEYS[key]
        warnings.warn(f"Config key '{key}'{where} is no longer used by stimpack: {explanation}.")
    return found

# %% Functions for pulling stuff out of the config dictionary

def get_available_rig_configs(cfg):
    """Rig names defined in this config; the user picks one at startup."""
    return list((cfg.get('rig_config') or {}).keys())

def get_parameter_preset_directory(cfg):
    """Where this config's protocol parameter presets are saved."""
    presets_dir = cfg.get('parameter_presets_dir', None)
    if presets_dir is not None:
        return os.path.join(get_labpack_directory(), presets_dir)
    else:
        print('!!! No parameter preset directory is defined by configuration file !!!')
        return os.getcwd()


# %% Functions for finding and loading user-defined modules

def user_module_specified(cfg, module_name: str) -> bool:
    """
    Checks whether specified user module is defined in the cfg.
    Returns True if module_name is in the cfg, False otherwise.
    """
    return module_name in cfg.get('module_paths', {})

def get_module_paths(cfg, module_name: str) -> list[str]:
    """
    Returns list of module paths specified in cfg file for the given module_name
    """
    if not user_module_specified(cfg, module_name):
        warnings.warn(f'No user module specified for {module_name} in the cfg file.')
        return []
    
    module_paths = cfg.get('module_paths', {}).get(module_name, [])
    if isinstance(module_paths, dict):
        # A data module mapped per format -- see get_data_module_paths_by_format. Everything from
        # here down asks only "which files does this config name", and the values are the answer.
        # Without this the mapping reached os.path as a dict, so --check-labpack crashed on the
        # configs it exists to check.
        module_paths = [split_data_module_spec(spec)[0] for spec in module_paths.values()]
    if not isinstance(module_paths, list):
        module_paths = [module_paths]
    return module_paths

#: Prefix marking a ``module_paths`` entry as relative to stimpack's own package directory rather
#: than to the labpack, e.g. ``stimpack:experiment/example_protocol.py``.
#:
#: A labpack that wants stimpack's own modules alongside its own -- the example protocols, most
#: usefully -- cannot name them relatively, since they are not in the labpack, and cannot name them
#: absolutely either: a config is shared across the machines a lab runs on, and stimpack sits at a
#: different path on each. The labpack directory has ``path_to_labpack.txt`` to solve exactly this;
#: this is the equivalent for stimpack, which needs no file because it can find itself.
STIMPACK_PATH_PREFIX = 'stimpack:'


def convert_labpack_relative_path_to_full_path(path, labpack_dir=None):
    """Resolve a ``module_paths`` entry to a full path.

    Absolute paths are used as given; a ``stimpack:`` prefix resolves against stimpack's package
    directory; anything else is relative to the labpack directory.

    The one place this is decided. It was briefly two -- check_labpack kept its own copy -- and the
    copy did not learn about the ``stimpack:`` prefix, so a config that loaded perfectly well was
    reported as naming a file that does not exist.

    :param labpack_dir: resolve relative paths against this directory rather than the configured
        one, which is how ``--check-labpack`` checks a labpack that is not the current one.
    """
    if path.startswith(STIMPACK_PATH_PREFIX):
        relative = path[len(STIMPACK_PATH_PREFIX):].lstrip('/')
        full_path = os.path.join(ROOT_DIR, relative)
    elif os.path.isabs(path):
        full_path = path
    else:
        full_path = os.path.join(labpack_dir if labpack_dir is not None
                                 else get_labpack_directory(), path)

    return full_path

def get_module_full_paths(cfg, module_name: str) -> list[str]:
    """
    Returns full paths to user defined module as specified in cfg file
    """
    module_paths = get_module_paths(cfg, module_name)
    return [convert_labpack_relative_path_to_full_path(mp) for mp in module_paths]

def user_module_paths_exist(cfg, module_name: str) -> list[bool]:
    """
    Checks whether the specified paths for the user module of given module_name exist.
    """
    if not user_module_specified(cfg, module_name):
        warnings.warn(f'No user module specified for {module_name} in the cfg file.')
        return []
    module_paths = get_module_full_paths(cfg, module_name)
    return [os.path.exists(p) for p in module_paths]

def load_user_module(cfg, module_name: str, allow_multiple=False, distinct_module_names=True) -> list[types.ModuleType]:
    """
    Import a labpack's own module, named by file path in the config's ``module_paths``.

    Loaded by path rather than by package name, so a labpack can be called whatever a lab
    likes and need not be installed. The consequence is that a path which no longer resolves
    fails quietly -- see :mod:`stimpack.experiment.util.check_labpack`.

    :param cfg: configuration dictionary
    :param module_name: which entry of ``module_paths`` to load -- ``'protocol'``, ``'data'``,
        ``'client'``, ``'daq'``, ``'visual_stim'``, ...
    :param allow_multiple: load every path listed for this entry, rather than only the first.
        A lab may keep several protocol modules, for instance.
    :param distinct_module_names: give each loaded module its own name in ``sys.modules``.
        With ``False`` they share one name, so loading a second would evict the first.
    :return: the loaded modules, in the order their paths were listed. Empty if the config
        names none.
    """
    if not user_module_specified(cfg, module_name):
        warnings.warn(f'No user module specified for {module_name} in the cfg file.')
        return []
    
    paths_to_module = get_module_full_paths(cfg, module_name)
    if len(paths_to_module) > 1 and not allow_multiple:
        warnings.warn("Only one module import is allowed but there are multiple module files specified. Using only the first one.")
        paths_to_module = paths_to_module[:1]

    loaded_modules = []

    for module_path in paths_to_module:
        if not os.path.exists(module_path):
            warnings.warn(f'Path for user module {module_name} specified in the cfg file does not exist: {module_path}')
        else:
            if distinct_module_names and allow_multiple and len(loaded_modules)>0:
                # append an index to the module name to ensure distinct module names
                module_name_w_idx = f"{module_name}_{len(loaded_modules)}"
            else:
                module_name_w_idx = module_name
            loaded_module = load_user_module_from_path(full_module_path=module_path, module_name=module_name_w_idx)
            loaded_modules.append(loaded_module)
    return loaded_modules


def user_module_sys_name(module_name: str, full_module_path: str) -> str:
    """The sys.modules key for a user module: namespaced, and keyed on the file it came from.

    Not the bare config key ('protocol', 'data', 'client', 'daq'). Those are ordinary words, so
    registering them at top level both collides with any installed package of the same name and,
    worse, makes every config's module indistinguishable from every other config's: loading
    alice_config's data.py and then bob_config's returned Alice's Data class to Bob, reporting only
    "already loaded, using cached version" -- which reads as an optimization, not as running someone
    else's code. Keying on the path keeps the caching (the same file twice is still one import)
    while making two different files two different modules.
    """
    return f'{USER_MODULE_NAMESPACE}.{module_name}.{_module_identifier(full_module_path)}'

def load_user_module_from_path(full_module_path: str, module_name: str) -> types.ModuleType:
    """Imports user defined module and returns the loaded package."""
    if not os.path.exists(full_module_path):
        raise FileNotFoundError(f'Could not find module {module_name} at {full_module_path}.')

    # Registered under a namespaced, path-keyed name rather than the bare config key -- see
    # user_module_sys_name(). Both places that later look a user module up do so via a class's
    # __module__ (protocol.py's protocol-path recording, gui.py's protocol label), so they follow
    # this name without caring what it is.
    sys_name = user_module_sys_name(module_name, full_module_path)

    cached = sys.modules.get(sys_name)
    if cached is not None:
        # Same file already imported in this process: reuse it, as a normal import would. This is
        # what the old bare-name check was reaching for, but keyed on the file rather than on a word
        # like 'data', so one config can no longer be served another config's module.
        return cached

    spec = spec_from_file_location(sys_name, full_module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load spec for module {module_name} from {full_module_path}.')
    loaded_mod = module_from_spec(spec)
    sys.modules[sys_name] = loaded_mod
    spec.loader.exec_module(loaded_mod)

    print('Loaded {} module from {}'.format(module_name, full_module_path))
    return loaded_mod

def load_trigger_device(cfg):
    """Loads trigger device specified in rig config from the user daq module """
    daq_module_list = load_user_module(cfg, 'daq')

    # fetch the trigger device definition from the config
    rig_config = (cfg.get('rig_config') or {}).get(cfg.get('current_rig_name')) or {}
    trigger_device_definition = rig_config.get('trigger', None)

    if not daq_module_list or trigger_device_definition is None:
        print('No trigger device defined')
        return None
    else:
        daq = daq_module_list[0]  # noqa: F841 - referenced by name inside the eval() below
        trigger_device = eval(f'daq.{trigger_device_definition}')
        print(f'Loaded trigger device from {get_module_full_paths(cfg, "daq")[0]}.{trigger_device_definition}')
        return trigger_device

# %%

def get_screen_center(cfg):
    """Center of the current rig's screen, which protocols position stimuli relative to."""
    if 'current_rig_name' in cfg:
        screen_center = ((cfg.get('rig_config') or {}).get(cfg.get('current_rig_name')) or {}).get('screen_center', [0, 0])
    else:
        print('No rig selected, using default screen center')
        screen_center = [0, 0]

    return screen_center

def get_server_options(cfg) -> dict[str, int|str|bool|None]: 
    # potential TODO: add type hints for the dictionary values by defining a TypedDict
    default_server_options = {'use_remote_server': False,
                              'data_directory': None}
    if 'current_rig_name' in cfg:
        server_options = ((cfg.get('rig_config') or {}).get(cfg.get('current_rig_name')) or {}).get('server_options', default_server_options)
    else:
        print('No rig selected, using default server settings')
        server_options = default_server_options
    return server_options

def get_data_directory(cfg):
    """Where the current rig writes experiment data."""
    if 'current_rig_name' in cfg:
        data_directory = ((cfg.get('rig_config') or {}).get(cfg.get('current_rig_name')) or {}).get('data_directory', os.getcwd())
    else:
        print('No rig selected, using default data directory')
        data_directory = os.getcwd()
    return data_directory

def get_loco_available(cfg):
    """Whether this rig has a movement tracker."""
    if 'current_rig_name' in cfg:
        loco_available = ((cfg.get('rig_config') or {}).get(cfg.get('current_rig_name')) or {}).get('loco_available', True)
    else:
        print('No rig selected, using locomotion')
        loco_available = True
    return loco_available

def get_experimenter(cfg):
    """Default experimenter name for this config."""
    return cfg.get('experimenter', '')

def get_data_format(cfg):
    """
    Which built-in storage backend to use: 'hdf5' (default) or 'nwb'.

    Set in a config file as:

        data_format: nwb

    Ignored when the config points to a labpack's own data module, which takes precedence over
    both built-ins. See stimpack.experiment.data / data_nwb.
    """
    if cfg.get('data_format') is None:
        return get_default_data_format(cfg)

    data_format = str(cfg['data_format']).lower()
    # Validated against what THIS config can write, not against the built-ins alone. Checking only
    # the built-ins made a labpack-defined format unreachable, and left the dialog offering a
    # format this function then refused to resolve -- one config, two answers.
    available = get_available_data_formats(cfg)
    if data_format not in available:
        fallback = get_default_data_format(cfg)
        warnings.warn(f"Unknown data_format '{data_format}' in config; expected one of "
                      f"{available}. Falling back to '{fallback}'.")
        return fallback
    return data_format


def get_data_module_paths_by_format(cfg) -> dict[str, str]:
    """
    ``{format: path}`` when a config maps its data modules by format, ``{}`` otherwise.

    A config may name its own data class either way::

        module_paths:
          data: labpack/data.py            # one class, whatever the format

        module_paths:
          data:                            # one class per format, chosen like a built-in
            hdf5: labpack/data.py
            nwb:  labpack/data_nwb.py

    The first fixes the format, because the class's base is what decides it -- so ``data_format``
    and the startup dialog cannot be honoured and are not consulted. The second leaves the choice
    open: they select among the labpack's own classes exactly as they select among the built-ins.

    The mapping exists because the first form quietly took the choice away. A labpack with a
    ``data.py`` and a ``data_nwb.py`` sitting side by side could name only one of them, so picking
    NWB in the dialog produced an HDF5 file.
    """
    entry = (cfg.get('module_paths') or {}).get('data')
    if not isinstance(entry, dict):
        return {}
    return {str(fmt).lower(): spec for fmt, spec in entry.items()}


def split_data_module_spec(spec: str) -> tuple[str, str]:
    """
    ``'labpack/data.py:DataLegacy'`` -> ``('labpack/data.py', 'DataLegacy')``; the class defaults
    to ``Data``.

    Without this a mapping needs one module per format, and the two HDF5 layouts differ only in
    five strings -- so a labpack supporting both would put its overrides in a mixin and write two
    three-line modules importing it. Naming the class lets one module hold all of them.

    Split on the last colon and only when what follows is an identifier, so a path containing one
    (a Windows drive letter, say) is not mistaken for a class name.
    """
    path, sep, class_name = str(spec).rpartition(':')
    if sep and class_name.isidentifier():
        return path, class_name
    return str(spec), 'Data' 


def get_available_data_formats(cfg) -> list[str]:
    """
    Every format this config can write: stimpack's built-ins, plus any the labpack adds.

    This used to return the mapping's keys alone, which conflated two different things -- which
    formats stimpack can write (always all the built-ins) and which ones the labpack has
    *customized*. A lab that customized HDF5 could then not reach NWB from the dialog at all,
    though nothing stopped stimpack writing it, and the same choice was still available through
    ``--data-format``. Offering a built-in where the labpack has no class is fine as long as it
    is labelled, which is what the dialog does.

    A mapping may also name a format stimpack has never heard of. The class is loaded by path and
    only ever duck-typed, so a labpack can add its own backend this way.
    """
    return sorted(set(BUILTIN_DATA_FORMATS) | set(get_data_module_paths_by_format(cfg)))


def get_default_data_format(cfg) -> str:
    """What ``data_format`` means when a config does not set one.

    ``hdf5`` as it always has -- except for a config that maps data modules, where defaulting to a
    format the labpack did not customize would quietly bypass every class it supplied.
    """
    mapped = get_data_module_paths_by_format(cfg)
    if not mapped:
        return 'hdf5'
    return 'hdf5' if 'hdf5' in mapped else sorted(mapped)[0]


def load_user_data_class(cfg):
    """
    The labpack's data class for this config, or ``None`` if it names none usable.

    ``None`` means "use the built-in for ``data_format``", which is also the answer when a config
    maps its modules by format and the requested format is not among them -- a labpack that
    customizes HDF5 and not NWB should still be able to write NWB, using stimpack's own class,
    rather than being refused or silently handed the HDF5 one.
    """
    # Naming no data module is the normal case -- stimpack has built-ins -- so it is not worth a
    # warning. load_user_module warns for every unspecified module, which made a correct config
    # print 'No user module specified for data' at every launch.
    if not user_module_specified(cfg, 'data'):
        return None

    mapped = get_data_module_paths_by_format(cfg)
    if not mapped:
        module = next(iter(load_user_module(cfg, 'data')), None)
        return getattr(module, 'Data', None) if module is not None else None

    data_format = get_data_format(cfg)
    spec = mapped.get(data_format)
    if spec is None:
        warnings.warn(f"This config maps its data modules by format and has none for "
                      f"'{data_format}' (it has {sorted(mapped)}). Using stimpack's built-in.")
        return None

    path, class_name = split_data_module_spec(spec)
    module = load_user_module_from_path(convert_labpack_relative_path_to_full_path(path), 'data')
    data_class = getattr(module, class_name, None)
    if data_class is None:
        raise AttributeError(f"module_paths.data maps '{data_format}' to {spec}, but {path} "
                             f"defines no class named '{class_name}'.")
    return data_class


def get_builtin_data_class(cfg):
    """
    Import and return the built-in data class named by the config's data_format.

    Imported on demand so an HDF5-only install never touches pynwb, and so a missing pynwb
    surfaces as its own install hint rather than as an import error at GUI start-up.
    """
    module_name, class_name = BUILTIN_DATA_FORMATS[get_data_format(cfg)]
    return getattr(importlib.import_module(module_name), class_name)


def get_lab(cfg):
    """Lab name, written into NWB files as top-level metadata."""
    return cfg.get('lab', '')

def get_institution(cfg):
    """Institution name, written into NWB files as top-level metadata."""
    return cfg.get('institution', '')
