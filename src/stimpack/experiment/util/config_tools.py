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
            'loco_available': False
            }

def user_config_directory_exists(labpack_dir=None):
    if labpack_dir is None:
        labpack_dir = get_labpack_directory()
    if os.path.exists(os.path.join(labpack_dir, 'configs')):
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

def get_path_to_module(cfg, module_name):
    """Returns full path to user defined module as specified in cfg file"""

    module_paths_entry = cfg.get('module_paths', None)
    if module_paths_entry is None:
        return None
    else:
        module_path = module_paths_entry.get(module_name, None)

    if module_path is None:
        return None
    else:
        full_module_path = os.path.join(get_labpack_directory(), module_path)

    return full_module_path

def user_module_exists(cfg, module_name):
    """Checks whether specified user module is defined and exists on this machine. Returns True/False."""

    full_module_path = get_path_to_module(cfg, module_name)
    if full_module_path is None:
        return False
    else:
        return os.path.exists(full_module_path)


def load_user_module(cfg, module_name):
    """Imports user defined module and returns the loaded package."""
    if user_module_exists(cfg, module_name):
        path_to_module = get_path_to_module(cfg, module_name)
        spec = spec_from_file_location(module_name, path_to_module)
        loaded_mod = module_from_spec(spec)
        sys.modules[module_name] = loaded_mod
        spec.loader.exec_module(loaded_mod)

        print('Loaded {} module from {}'.format(module_name, path_to_module))
        return loaded_mod
    else:
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
        print('Loaded trigger device from {}.{}'.format(get_path_to_module(cfg, 'daq'), trigger_device_definition))
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
    if 'current_rig_name' in cfg:
        server_options = cfg.get('rig_config').get(cfg.get('current_rig_name')).get('server_options', {'host': '0.0.0.0', 'port': 60629, 'use_server': False})
    else:
        print('No rig selected, using default server settings')
        server_options = {'host': '0.0.0.0',
                          'port': 60629,
                          'use_server': False,
                          'data_directory': None}
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
        loco_available = cfg.get('rig_config').get(cfg.get('current_rig_name')).get('loco_available', False)
    else:
        print('No rig selected, not using locomotion')
        loco_available = False
    return loco_available

def get_experimenter(cfg):
    return cfg.get('experimenter', '')
