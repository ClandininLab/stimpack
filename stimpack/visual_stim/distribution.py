"""
Intensity distributions for stimuli that draw random values.

A stimulus that needs randomness -- noise, randomly-seeded grids, flickering patches -- takes a
``distribution_data`` dictionary rather than sampling directly, so the choice of distribution is
part of the saved protocol parameters and the stimulus itself stays agnostic::

    distribution_data = {'name': 'Binary', 'rand_min': 0, 'rand_max': 1}

The ``name`` key selects the class below; the remaining keys are passed to its constructor. See
:func:`stimpack.util.make_as`.

Values are drawn with NumPy's global random state, which stimuli seed per update interval (see
:class:`stimpack.visual_stim.stimuli.UniformWhiteNoise`), so a given protocol replays identically.
"""
import numpy as np
from stimpack import util as sp_util

def make_as_distribution(parameter):
    """Return parameter as Distribution object if it is a dictionary."""
    return sp_util.make_as(parameter, parent_class=Distribution)

class Distribution:
    """
    Base class for intensity distributions.

    Subclasses store their parameters on construction and implement
    :meth:`get_random_values`. This class is not usable on its own.
    """
    def __init__(self):
        raise NotImplementedError

    def get_random_values(self, output_shape):
        """
        Draw samples from the distribution.

        :param output_shape: shape of the array to draw, in NumPy's sense -- an int for a flat
            array, a tuple for a grid. Stimuli drawing one intensity pass ``1``, which returns
            an array of shape ``(1,)`` rather than a scalar.
        :return: array of samples of the requested shape.
        """
        raise NotImplementedError


class Uniform(Distribution):
    """
    Values drawn uniformly from ``[rand_min, rand_max)``.

    The default for stimuli that take a distribution and are given none.
    """
    def __init__(self, rand_min, rand_max):
        self.rand_min = rand_min
        self.rand_max = rand_max

    def get_random_values(self, output_shape):
        rand_values = np.random.uniform(self.rand_min, self.rand_max, size=output_shape)
        return rand_values


class Gaussian(Distribution):
    """
    Values drawn from a normal distribution.

    Note that samples are not clipped, so with a wide standard deviation some will fall outside
    the displayable 0-1 intensity range and be clamped by the display.
    """
    def __init__(self, rand_mean, rand_stdev):
        self.rand_mean = rand_mean
        self.rand_stdev = rand_stdev

    def get_random_values(self, output_shape):
        rand_values = np.random.normal(self.rand_mean, self.rand_stdev, size=output_shape)
        return rand_values


class Binary(Distribution):
    """
    Values drawn with equal probability from the two extremes, ``rand_min`` or ``rand_max``.

    The usual choice for full-contrast noise, where every sample should be at one limit or the
    other rather than spread between them.
    """
    def __init__(self, rand_min, rand_max):
        self.rand_min = rand_min
        self.rand_max = rand_max

    def get_random_values(self, output_shape):
        rand_values = np.random.choice([self.rand_min, self.rand_max], size=output_shape)
        return rand_values


class Ternary(Distribution):
    """
    Values drawn with equal probability from ``rand_min``, its midpoint with ``rand_max``, and
    ``rand_max`` -- so a third of samples carry no contrast against a mid-grey background.
    """
    def __init__(self, rand_min, rand_max):
        self.rand_min = rand_min
        self.rand_max = rand_max

    def get_random_values(self, output_shape):
        rand_values = np.random.choice([self.rand_min, (self.rand_min + self.rand_max)/2, self.rand_max], size=output_shape)
        return rand_values
