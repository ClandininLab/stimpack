import os
import glob
from platformdirs import user_config_dir
import yaml
import sys
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


def get_configuration_file(cfg_name, labpack_dir=None):
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

def get_paths_to_module(cfg, module_name, single_item_in_list=False):
    """
    Returns path to user defined module as specified in cfg file (not necessarily full path)
    If module_name is in the cfg, 
        returns file paths for the specified module.
        If there are multiple paths specified for the module, returns a list.
        If there is only one path specified, single_item_in_list determines whether the return is in a list or not.
    """

    module_paths_entry = cfg.get('module_paths', None)
    if module_paths_entry is None:
        return None
    else:
        module_paths = module_paths_entry.get(module_name, None)

    if module_paths is None:
        return None
    
    if not isinstance(module_paths, list) and single_item_in_list:
        module_paths = [module_paths]
    return module_paths

def convert_labpack_relative_path_to_full_path(path):
    """Converts a path relative to the labpack directory to a full path"""
    if os.path.isabs(path):
        full_path = path
    else:
        full_path = os.path.join(get_labpack_directory(), path)

    return full_path

def get_full_paths_to_module(cfg, module_name, single_item_in_list=False):
    """
    Returns full paths to user defined module as specified in cfg file
    If module_name is in the cfg, 
        returns file paths for the specified module.
        If there are multiple paths specified for the module, returns a list.
        If there is only one path specified, single_item_in_list determines whether the return is in a list or not.
    """
    module_paths = get_paths_to_module(cfg, module_name, single_item_in_list=True)
    if module_paths is None:
        return None
    else:
        full_paths = [convert_labpack_relative_path_to_full_path(mp) for mp in module_paths]
        if len(full_paths) == 1 and not single_item_in_list:
            return full_paths[0]
        return full_paths

def user_module_exists(cfg, module_name, single_item_in_list=False):
    """
    Checks whether specified user module is defined and exists on this machine. 
    Returns False if module_name is not in the cfg.
    If module_name is in the cfg, 
        returns True/False based on whether the specified module path exists.
        If there are multiple paths specified for the module, returns a list of booleans.
        If there is only one path specified, single_item_in_list determines whether the return is in a list or not.
    """

    full_module_paths = get_full_paths_to_module(cfg, module_name, single_item_in_list=True)
    if full_module_paths is None:
        return False
    else:
        exists = [os.path.exists(p) for p in full_module_paths]
        if len(exists) == 1 and not single_item_in_list:
            return exists[0]
        return exists


def load_user_module(cfg, module_name):
    """Imports user defined module and returns the loaded package."""
    if user_module_exists(cfg, module_name):
        path_to_module = get_full_paths_to_module(cfg, module_name)
        if isinstance(path_to_module, list):
            print("This function only supports single module import but there are multiple module files specified. Using the first one.")
            path_to_module = path_to_module[0]
        return load_user_module_from_path(path_to_module, module_name)
    else:
        return None

def load_user_module_from_path(full_module_path, module_name):
    """Imports user defined module and returns the loaded package."""
    if os.path.exists(full_module_path):
        spec = spec_from_file_location(module_name, full_module_path)
        loaded_mod = module_from_spec(spec)
        sys.modules[module_name] = loaded_mod
        spec.loader.exec_module(loaded_mod)

        print('Loaded {} module from {}'.format(module_name, full_module_path))
        return loaded_mod
    else:
        print(f'Error: {full_module_path} does not exist. Could not load module {module_name}.')
        return None

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
        print('Loaded trigger device from {}.{}'.format(get_full_paths_to_module(cfg, 'daq'), trigger_device_definition))
        return trigger_device

# %%

def get_screen_center(cfg):
    if 'current_rig_name' in cfg:
        screen_center = cfg.get('rig_config').get(cfg.get('current_rig_name')).get('screen_center', [0, 0])
    else:
        print('No rig selected, using default screen center')
        screen_center = [0, 0]

    return screen_center

def get_server_options(cfg):
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
