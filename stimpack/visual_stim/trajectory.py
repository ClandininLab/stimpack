"""
Class + functions for making parameter trajectories for stimpack.visual_stim stims.

Generally access this class using make_as_trajectory and return_for_time_t
"""
from scipy.interpolate import interp1d
import numpy as np
from stimpack.util import make_as

def make_as_trajectory(parameter):
    """Return parameter as Trajectory object if it is a dictionary."""
    return make_as(parameter, parent_class=Trajectory)

def return_for_time_t(parameter, t):
    """Return param value at time t, if it is a Trajectory object."""
    if isinstance(parameter, Trajectory):
        return parameter.getValue(t)
    else: # not specified as a trajectory dict., just return the original param value
        return parameter

class Trajectory:
    """Trajectory class."""

    def __init__(self):
        """
        Trajectory class. Can be used to specify parameter values as functions of time.
        """
        raise NotImplementedError
    
class TVPairs(Trajectory):
    """
    List of arbitrary time-value pairs.

    :tv_pairs: list of time, value tuples. [(t0, v0), (t1, v1), ..., (tn, vn)]
    :kind: interpolation type. See scipy.interpolate.interp1d for options.
    """
    def __init__(self, tv_pairs, kind='linear', fill_value='extrapolate'):
        times, values = zip(*tv_pairs)
        self.getValue = interp1d(times, values, kind=kind, fill_value=fill_value, axis=0)

class Sinusoid(Trajectory):
    """
    Temporal sinusoid trajectory.

    :offset: Y offset
    :amplitude:
    :temporal_frequency: Hz
    """
    def __init__(self, amplitude, temporal_frequency, offset):
        self.getValue = lambda t: offset + amplitude * np.sin(2*np.pi*temporal_frequency*t)

class SinusoidInTimeWindow(Trajectory):
    """
    Temporal sinusoid trajectory, only shown during a time window, defined by stim_start and stim_end.
    Alpha is 0 when

    :offset: Y offset
    :amplitude:
    :temporal_frequency: Hz
    :stim_start:
    :stim_end:
    """
    def __init__(self, amplitude, temporal_frequency, offset, stim_start, stim_end):
        self.getValue = lambda t: [0,0,0,0] if t < stim_start or t >= stim_end else offset + amplitude * np.sin(2*np.pi*temporal_frequency*t)

class Loom(Trajectory):
    """
    Expanding loom trajectory.

    :rv_ratio: sec
    :stim_time: sec
    :start_size: deg., diameter of spot
    :end_size: deg., diameter of spot

    : returns RADIUS of spot for time t
    """
    def __init__(self, rv_ratio, stim_time, start_size, end_size):
        def get_loom_size(t):
            # calculate angular size at t
            angular_size = 2 * np.rad2deg(np.arctan(rv_ratio * (1 / (stim_time - t))))

            # shift curve vertically so it starts at start_size. Calc t=0 size of trajector
            min_size = 2 * np.rad2deg(np.arctan(rv_ratio * (1 / (stim_time - 0))))
            size_adjust = min_size - start_size
            angular_size = angular_size - size_adjust

            # Cap the curve at end_size and have it just hang there
            if (angular_size > end_size):
                angular_size = end_size

            # divide by  2 to get spot radius
            return angular_size / 2
        self.getValue = get_loom_size
        