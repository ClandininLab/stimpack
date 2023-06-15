import numpy as np
from stimpack import util as sp_util

def make_as_distribution(parameter):
    """Return parameter as Distribution object if it is a dictionary."""
    return sp_util.make_as(parameter, parent_class=Distribution)

class Distribution:
    def __init__(self):
        raise NotImplementedError
    

class Uniform(Distribution):
    def __init__(self, rand_min, rand_max):
        self.rand_min = rand_min
        self.rand_max = rand_max

    def get_random_values(self, output_shape):
        rand_values = np.random.uniform(self.rand_min, self.rand_max, size=output_shape)
        return rand_values


class Gaussian(Distribution):
    def __init__(self, rand_mean, rand_stdev):
        self.rand_mean = rand_mean
        self.rand_stdev = rand_stdev

    def get_random_values(self, output_shape):
        rand_values = np.random.normal(self.rand_mean, self.rand_stdev, size=output_shape)
        return rand_values


class Binary(Distribution):
    def __init__(self, rand_min, rand_max):
        self.rand_min = rand_min
        self.rand_max = rand_max

    def get_random_values(self, output_shape):
        rand_values = np.random.choice([self.rand_min, self.rand_max], size=output_shape)
        return rand_values


class Ternary(Distribution):
    def __init__(self, rand_min, rand_max):
        self.rand_min = rand_min
        self.rand_max = rand_max

    def get_random_values(self, output_shape):
        rand_values = np.random.choice([self.rand_min, (self.rand_min + self.rand_max)/2, self.rand_max], size=output_shape)
        return rand_values
