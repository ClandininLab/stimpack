from math import sin, cos
from numbers import Number
import numpy as np
import os, sys
from importlib.util import spec_from_file_location, module_from_spec
import random
import string
import warnings

def load_stim_module_from_path(path, module_name='loaded_module', submodules=['stimuli', 'trajectory', 'distribution']):
    '''
    Load a module from specified path. Module must contained specified submodules.
    '''
    for submodule_name in submodules:
        submodule_name_full = module_name+'.'+submodule_name
        submodule_path = os.path.join(path, submodule_name+'.py')
        if not os.path.exists(submodule_path):
            warnings.warn(f'Could not find {submodule_name} at {submodule_path}')
            continue
        spec = spec_from_file_location(submodule_name_full, submodule_path)
        loaded_mod = module_from_spec(spec)
        sys.modules[submodule_name_full] = loaded_mod
        spec.loader.exec_module(loaded_mod)
    return

def generate_lowercase_barcode(length=5, existing_barcodes=[]):
    """Generates a random barcode that is not in existing_barcodes"""
    barcode = ''.join(random.choice(string.ascii_lowercase) for i in range(length))
    while barcode in existing_barcodes:
        barcode = ''.join(random.choice(string.ascii_lowercase) for i in range(length))
    return barcode

def normalize(vec):
    return vec / np.linalg.norm(vec)

def qimage2ndarray(qimage):
    '''  Converts a QImage into an opencv MAT format  '''

    qimage = qimage.convertToFormat(4)

    width = qimage.width()
    height = qimage.height()

    ptr = qimage.bits()
    ptr.setsize(qimage.byteCount())
    arr = np.array(ptr).reshape(height, width, 4)  #  Copies the data
    return arr

# rotation matrix reference:
# https://en.wikipedia.org/wiki/Rotation_matrix

def rotate(pts, yaw, pitch, roll):
    """
    :param yaw: rotation around z axis, radians
    :param pitch: rotation around x axis, radians
    :param roll: rotation around y axis, radians
    """
    R = rot_mat(yaw, pitch, roll)
    return R @ pts

def rot_mat(yaw, pitch, roll):
    """
    :param yaw: rotation around z axis, radians
    :param pitch: rotation around x axis, radians
    :param roll: rotation around y axis, radians
    """
    return rotz_mat(yaw) @ rotx_mat(pitch) @ roty_mat(roll)

def rotx(pts, th):
    return rotx_mat(th).dot(pts)

def rotx_mat(th):
    return np.array([[1,       0,         0],
                     [0, +cos(th), -sin(th)],
                     [0, +sin(th), +cos(th)]], dtype=float)

def roty(pts, th):
    return roty_mat(th).dot(pts)

def roty_mat(th):
    return np.array([[+cos(th), 0, +sin(th)],
                     [0,        1,        0],
                     [-sin(th), 0, +cos(th)]], dtype=float)

def rotz(pts, th):
    return rotz_mat(th).dot(pts)

def rotz_mat(th):
    return np.array([[+cos(th), -sin(th), 0],
                     [+sin(th), +cos(th), 0],
                     [       0,        0, 1]], dtype=float)

def scale(pts, amt):
    return np.multiply(amt, pts)

def spherical_to_cartesian(r, theta, phi):
    x = r * np.sin(phi) * np.cos(theta)
    y = r * np.sin(phi) * np.sin(theta)
    z = r * np.cos(phi)
    return x, y, z

def cartesian_to_spherical(x, y, z):
    r = np.sqrt(x**2 + y**2 + z**2)
    theta = np.arctan2(y, z)
    phi = np.arccos(z/r) # np.arctan2(np.sqrt(x**2 + y**2), z)
    return r, theta, phi

def cylindrical_to_cartesian(r, theta, z):
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    z = z
    return x, y, z

def cartesian_to_cylindrical(x, y, z):
    r = np.sqrt(x**2 + y**2)
    theta = np.arctan2(y, x)
    z = z
    return r, theta, z

def cylindrical_w_phi_to_cartesian(r, theta, phi):
    '''
    Converts cylindrical coordinates with phi instead of z (r, theta, phi) to cartesian coordinates
    '''
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    z = r / np.tan(phi)
    return x, y, z

def cartesian_to_cylindrical_w_phi(x, y, z):
    r = np.sqrt(x**2 + y**2)
    theta = np.arctan2(y, x)
    phi = np.arctan2(z, r)
    return r, theta, phi

def translate(pts, amt):
    # convert point(s) and translate amount to numpy arrays
    pts = np.array(pts, dtype=float)
    amt = np.array(amt, dtype=float)

    # add offset in a manner that depends on whether the input is 1D or 2D
    if len(pts.shape) == 1:
        return pts + amt
    elif len(pts.shape) == 2:
        return pts + amt[:, np.newaxis]

def get_rgba(val, def_alpha=1):
    # interpret string as RGB
    if isinstance(val, str):
        if val.lower() == 'red':
            val = (1, 0, 0)
        elif val.lower() == 'green':
            val = (0, 1, 0)
        elif val.lower() == 'blue':
            val = (0, 0, 1)
        elif val.lower() == 'yellow':
            val = (1, 1, 0)
        elif val.lower() == 'magenta':
            val = (1, 0, 1)
        elif val.lower() == 'cyan':
            val = (0, 1, 1)
        elif val.lower() == 'white':
            val = (1, 1, 1)
        elif val.lower() == 'black':
            val = (0, 0, 0)
        else:
            raise ValueError(f'Unknown color: {val}')

    # convert single value to float
    if np.asarray(val).size == 1:
        val = float(val)

    # if a single number is given treat as monochrome
    if isinstance(val, Number):
        return (val, val, val, def_alpha)

    # otherwise if three numbers are given add the default alpha
    if len(val) == 3:
        return (val[0], val[1], val[2], def_alpha)
    elif len(val) == 4:
        return val
    else:
        raise ValueError(f'Cannot use value with length {len(val)}.')
