import contextlib
import hashlib
import os
import re
import glob
from platformdirs import user_config_dir
import yaml
import sys
import types
from typing import Any, Optional
import warnings

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
    stimpack_config_dir = get_stimpack_config_directory(ensure_exists=True)
    path_to_labpack = os.path.join(stimpack_config_dir, 'path_to_labpack.txt')
    with open(path_to_labpack, "w") as text_file:
        text_file.write(path)

# %% Functions for finding and loading user configuration files

def merge_configs(cfg1, cfg2):
    my_merger = Merger(
    # pass in a list of tuple, with the
    # strategies you are looking to apply
    # to each type.
    [
        (list, ["append_unique"]), # For lists: append new items, but only if they are unique
        (dict, ["merge"]), # For dictionaries: deep merge them
    ],
    # next, choose the fallback strategies,
    # applied to all other types:
    ["override"],
    # finally, choose the strategies in
    # the case where the types conflict:
    ["override"]
    )

    merged = my_merger.merge(cfg1, cfg2)
    return merged

def get_default_config():
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
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()
    if not labpack_dir.strip()=="" and os.path.exists(os.path.join(labpack_dir, 'configs')):
        return True
    else:
        return False

def get_available_config_files(labpack_dir=None):
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()
    if user_config_directory_exists(labpack_dir):
        cfg_names = [os.path.split(f)[1] for f in glob.glob(os.path.join(labpack_dir, 'configs', '*.yaml'))]
    else:
        cfg_names = []

    cfg_names = [x for x in cfg_names if x != 'lab_config.yaml']
        
    return cfg_names


def get_configuration_file(cfg_name: str, labpack_dir: Optional[str] = None) -> dict[str, Any]:
    """Returns config, as dictionary, from  labpack_directory/configs/ based on cfg_name.yaml"""
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

    warn_about_legacy_config_keys(cfg, cfg_name)

    return cfg


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
    return list((cfg.get('rig_config') or {}).keys())

def get_parameter_preset_directory(cfg):
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
    if not isinstance(module_paths, list):
        module_paths = [module_paths]
    return module_paths

def convert_labpack_relative_path_to_full_path(path):
    """Converts a path relative to the labpack directory to a full path"""
    if os.path.isabs(path):
        full_path = path
    else:
        full_path = os.path.join(get_labpack_directory(), path)

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
    Imports user defined module and returns the loaded package.
    
    Inputs:
        cfg: configuration dictionary
        module_name: name of the module to be loaded (e.g. 'protocol', 'data', 'client', 'daq', 'visual_stim', etc.)
        allow_multiple: 
            if True, loads all specified module paths.
            if False, loads only the first specified module path.
            Default: False.
        distinct_module_names:
            Options for handling multiple loaded modules with the same module name.
            if True, appends an index to the module name for each loaded module to ensure distinct module names.
            if False, uses the same module name for caching into sys.modules.
    Returns:
        list of loaded modules
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
    trigger_device_definition = cfg.get('rig_config')[cfg.get('current_rig_name')].get('trigger', None)

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
    if 'current_rig_name' in cfg:
        data_directory = ((cfg.get('rig_config') or {}).get(cfg.get('current_rig_name')) or {}).get('data_directory', os.getcwd())
    else:
        print('No rig selected, using default data directory')
        data_directory = os.getcwd()
    return data_directory

def get_loco_available(cfg):
    if 'current_rig_name' in cfg:
        loco_available = ((cfg.get('rig_config') or {}).get(cfg.get('current_rig_name')) or {}).get('loco_available', True)
    else:
        print('No rig selected, using locomotion')
        loco_available = True
    return loco_available

def get_experimenter(cfg):
    return cfg.get('experimenter', '')

def get_lab(cfg):
    return cfg.get('lab', '')

def get_institution(cfg):
    return cfg.get('institution', '')
