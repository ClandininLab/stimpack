import os
import glob
from platformdirs import user_config_dir
import yaml
import sys
import types
from typing import Any, Optional
import warnings
from importlib.util import spec_from_file_location, module_from_spec

def get_stimpack_config_directory(ensure_exists=True):
    return user_config_dir(appname="stimpack", ensure_exists=ensure_exists)

def get_labpack_directory():
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
        
    return cfg_names


def get_configuration_file(cfg_name: str, labpack_dir: Optional[str] = None) -> dict[str, Any]:
    """Returns config, as dictionary, from  labpack_directory/configs/ based on cfg_name.yaml"""
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()
    
    cfg_path = os.path.join(labpack_dir, 'configs', cfg_name)
    if os.path.exists(cfg_path):
        with open(cfg_path, 'r') as ymlfile:
            cfg = yaml.safe_load(ymlfile)
    else:
        cfg = get_default_config()

    return cfg

# %% Functions for pulling stuff out of the config dictionary

def get_available_rig_configs(cfg):
    return list(cfg.get('rig_config').keys())

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
    
    if module_name in sys.modules and not allow_multiple:
        warnings.warn(f'User module {module_name} already loaded, using cached version.')
        return [sys.modules[module_name]]
    
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

def load_user_module_from_path(full_module_path: str, module_name: str) -> types.ModuleType:
    """Imports user defined module and returns the loaded package."""
    if not os.path.exists(full_module_path):
        raise FileNotFoundError(f'Could not find module {module_name} at {full_module_path}.')

    spec = spec_from_file_location(module_name, full_module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load spec for module {module_name} from {full_module_path}.')
    loaded_mod = module_from_spec(spec)
    sys.modules[module_name] = loaded_mod
    spec.loader.exec_module(loaded_mod)

    print('Loaded {} module from {}'.format(module_name, full_module_path))
    return loaded_mod

def load_trigger_device(cfg):
    """Loads trigger device specified in rig config from the user daq module """
    daq = load_user_module(cfg, 'daq')
    # fetch the trigger device definition from the config
    trigger_device_definition = cfg.get('rig_config')[cfg.get('current_rig_name')].get('trigger', None)

    if daq is None or trigger_device_definition is None:
        print('No trigger device defined')
        return None
    else:
        trigger_device = eval('daq.{}'.format(trigger_device_definition))
        print('Loaded trigger device from {}.{}'.format(get_module_full_paths(cfg, 'daq'), trigger_device_definition))
        return trigger_device

# %%

def get_screen_center(cfg):
    if 'current_rig_name' in cfg:
        screen_center = cfg.get('rig_config').get(cfg.get('current_rig_name')).get('screen_center', [0, 0])
    else:
        print('No rig selected, using default screen center')
        screen_center = [0, 0]

    return screen_center

def get_server_options(cfg) -> dict[str, int|str|bool|None]:
    default_server_options = {'use_remote_server': False,
                              'data_directory': None}
    if 'current_rig_name' in cfg:
        server_options = cfg.get('rig_config').get(cfg.get('current_rig_name')).get('server_options', default_server_options)
    else:
        print('No rig selected, using default server settings')
        server_options = default_server_options
    return server_options

def get_data_directory(cfg):
    if 'current_rig_name' in cfg:
        data_directory = cfg.get('rig_config').get(cfg.get('current_rig_name')).get('data_directory', os.getcwd())
    else:
        print('No rig selected, using default data directory')
        data_directory = os.getcwd()
    return data_directory

def get_loco_available(cfg):
    if 'current_rig_name' in cfg:
        loco_available = cfg.get('rig_config').get(cfg.get('current_rig_name')).get('loco_available', True)
    else:
        print('No rig selected, using locomotion')
        loco_available = True
    return loco_available

def get_experimenter(cfg):
    return cfg.get('experimenter', '')
