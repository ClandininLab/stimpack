"""
Stimulus classes.

Each class is is derived from stimpack.visual_stim.base.BaseProgram, which handles the GL context and shader programs

"""

import numpy as np
from stimpack.visual_stim.base import BaseProgram
from stimpack.visual_stim.trajectory import make_as_trajectory, return_for_time_t
import stimpack.visual_stim.distribution as distribution
from stimpack.visual_stim import shapes
from stimpack.visual_stim import util
import copy
from multiprocessing import shared_memory

class ConstantBackground(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, color=[0.5, 0.5, 0.5, 1.0], center=[0, 0, 0], side_length=100):
        """
        Big skybox to simulate a constant background behind stimuli.

        :param color: [r,g,b,a]
        :param center: [x,y,z]
        :param side_length: meters, side length of cube
        """
        self.color = color
        self.center = center
        self.side_length = side_length

        colors = {'+x': self.color, '-x': self.color,
                  '+y': self.color, '-y': self.color,
                  '+z': self.color, '-z': self.color}
        self.stim_object = shapes.GlCube(colors, center=self.center, side_length=self.side_length)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

class Floor(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, color=[0.5, 0.5, 0.5, 1.0], z_level=-0.1, side_length=10):
        """
        Infinite floor.

        :param color: [r,g,b,a]
        :param z_level: meters, level at which the floor is on the z axis (-z is below the fly)
        :param side_length: meters or (x, y) tuple of meters
        """
        self.color = color

        if isinstance(side_length, tuple):
            x_length = side_length[0]
            y_length = side_length[1]
        else:
            x_length = side_length
            y_length = side_length

        v1 = (-x_length/2, -y_length/2, z_level)
        v2 = (x_length/2, -y_length/2, z_level)
        v3 = (x_length/2, y_length/2, z_level)
        v4 = (-x_length/2, y_length/2, z_level)

        self.stim_object = shapes.GlQuad(v1, v2, v3, v4, color)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

class TexturedGround(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)
        self.use_texture = True

    def configure(self, color=[0.5, 0.5, 0.5, 1.0], z_level=-0.1, side_length=10, rand_seed=0):
        """
        Infinite textured ground.

        :param color: [r,g,b,a]
        :param z_level: meters, level at which the floor is on the z axis (-z is below the fly)
        :param side_length: meters or (x, y) tuple of meters
        """
        self.color = color
        self.rand_seed = rand_seed

        if isinstance(side_length, tuple):
            x_length = side_length[0]
            y_length = side_length[1]
        else:
            x_length = side_length
            y_length = side_length

        v1 = (-x_length/2, -y_length/2, z_level)
        v2 = (x_length/2, -y_length/2, z_level)
        v3 = (x_length/2, y_length/2, z_level)
        v4 = (-x_length/2, y_length/2, z_level)

        self.stim_object = shapes.GlQuad(v1, v2, v3, v4, self.color,
                                        tc1=(0, 0), tc2=(1, 0), tc3=(1, 1), tc4=(0, 1),
                                        texture_shift=(0, 0), use_texture=True)

        # create the texture
        np.random.seed(self.rand_seed)
        face_colors = np.random.uniform(size=(128, 128))

        # make and apply the texture
        img = (255*face_colors).astype(np.uint8)
        self.add_texture_gl(img, texture_interpolation='LINEAR')

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

class CheckerboardFloor(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)
        self.use_texture = True

    def configure(self, mean, contrast, center=(0,0,-0.1), side_length=10, patch_width=1):
        """
        Grayscale Checkerboard floor.

        :param mean: float, mean of the checkerboard (0-1)
        :param contrast: float, contrast of the checkerboard (0-1)
        :param center: (x,y,z) meters
        :param side_length: meters or (x, y) tuple of meters
        """
        self.mean = mean
        self.contrast = contrast
        self.patch_width = patch_width

        if isinstance(side_length, tuple):
            x_length = side_length[0]
            y_length = side_length[1]
        else:
            x_length = side_length
            y_length = side_length
        
        center_x, center_y, center_z = center

        v1 = (-x_length/2 + center_x, -y_length/2 + center_y, center_z)
        v2 = ( x_length/2 + center_x, -y_length/2 + center_y, center_z)
        v3 = ( x_length/2 + center_x,  y_length/2 + center_y, center_z)
        v4 = (-x_length/2 + center_x,  y_length/2 + center_y, center_z)

        # each texture patch is 2x2 checkerboard patches
        n_texture_patches_x = x_length / (self.patch_width * 2)
        n_texture_patches_y = y_length / (self.patch_width * 2)
        
        tc1 = (0,                   0)
        tc2 = (n_texture_patches_x, 0)
        tc3 = (n_texture_patches_x, n_texture_patches_y)
        tc4 = (0,                   n_texture_patches_y)

        self.stim_object = shapes.GlQuad(v1, v2, v3, v4, (1,1,1,1),
                                        tc1=tc1, tc2=tc2, tc3=tc3, tc4=tc4,
                                        texture_shift=(0, 0), use_texture=True)

        # make and apply the texture
        texture_patch = np.array([[1, -1], [-1, 1]]) # 2x2 checkerboard patch
        img = (255*(mean + contrast*mean*texture_patch)).astype(np.uint8)
        self.add_texture_gl(img, texture_interpolation='NEAREST')

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

class MovingPatch(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, width=10, height=10, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0, angle=0):
        """
        Stimulus consisting of a rectangular patch on the surface of a sphere. Patch is rectangular in spherical coordinates.

        :param width: Width in degrees (azimuth)
        :param height: Height in degrees (elevation)
        :param sphere_radius: Radius of the sphere (meters)
        :param color: [r,g,b,a] or mono. Color of the patch
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        :param angle: degrees orientation of patch (roll rotation around x axis)
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.width = make_as_trajectory(width)
        self.height = make_as_trajectory(height)
        self.sphere_radius = sphere_radius
        self.color = make_as_trajectory(color)
        self.theta = make_as_trajectory(theta)
        self.phi = make_as_trajectory(phi)
        self.angle = make_as_trajectory(angle)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        width = return_for_time_t(self.width, t)
        height = return_for_time_t(self.height, t)
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)
        color = return_for_time_t(self.color, t)
        # TODO: is there a way to make this object once in configure then update with width/height in eval_at?
        self.stim_object = shapes.GlSphericalRect(width=width,
                                                height=height,
                                                sphere_radius=self.sphere_radius,
                                                color=color).rotate(np.radians(theta), np.radians(phi), np.radians(angle))

class MovingPatchOnCylinder(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, width=10, height=10, cylinder_radius=1, color=[1, 1, 1, 1], theta=0, phi=0, angle=0):
        """
        Stimulus consisting of a rectangular patch on the surface of a cylinder. Patch is rectangular in cylindrical coordinates.

        :param width: Width in degrees (azimuth)
        :param height: Height in degrees (elevation)
        :param cylinder_radius: Radius of the cylinder (meters)
        :param color: [r,g,b,a] or mono. Color of the patch
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        :param angle: degrees orientation of patch (roll rotation around x axis)
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.width = make_as_trajectory(width)
        self.height = make_as_trajectory(height)
        self.cylinder_radius = cylinder_radius
        self.color = make_as_trajectory(color)
        self.theta = make_as_trajectory(theta)
        self.phi = make_as_trajectory(phi)
        self.angle = make_as_trajectory(angle)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        width = return_for_time_t(self.width, t)
        height = return_for_time_t(self.height, t)
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)
        color = return_for_time_t(self.color, t)
        # TODO: is there a way to make this object once in configure then update with width/height in eval_at?
        self.stim_object = shapes.GlCylindricalWithPhiRect(width=width,
                                                        height=height,
                                                        cylinder_radius=self.cylinder_radius,
                                                        color=color).rotate(np.radians(theta), np.radians(phi), np.radians(angle))

class MovingEllipse(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, width=20, height=10, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0, angle=0):
        """
        Stimulus consisting of a circular patch on the surface of a sphere. Patch is circular in spherical coordinates.

        :param width: width of ellipse in degrees
        :param height: height of ellipse in degrees
        :param sphere_radius: Radius of the sphere (meters)
        :param color: [r,g,b,a] or mono. Color of the patch
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        :param angle: degrees orientation of patch (roll rotation around x axis)
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.sphere_radius = sphere_radius

        self.width = make_as_trajectory(width)
        self.height = make_as_trajectory(height)
        self.color = make_as_trajectory(color)
        self.theta = make_as_trajectory(theta)
        self.phi = make_as_trajectory(phi)
        self.angle = make_as_trajectory(angle)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        width = return_for_time_t(self.width, t)
        height = return_for_time_t(self.height, t)
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)
        color = return_for_time_t(self.color, t)
        # TODO: is there a way to make this object once in configure then update with radius in eval_at?
        self.stim_object = shapes.GlSphericalEllipse(width=width, 
                                                    height=height,
                                                    sphere_radius=self.sphere_radius,
                                                    color=color,
                                                    n_steps=36).rotate(np.radians(theta), np.radians(phi), np.radians(angle))

class MovingEllipseOnCylinder(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, width=20, height=10, cylinder_radius=1, color=[1, 1, 1, 1], theta=0, phi=0, angle=0):
        """
        Stimulus consisting of a circular patch on the surface of a sphere. Patch is circular in spherical coordinates.

        :param width: width of ellipse in degrees
        :param height: height of ellipse in degrees
        :param cylinder_radius: Radius of the cylinder (meters)
        :param color: [r,g,b,a] or mono. Color of the patch
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        :param angle: degrees orientation of patch (roll rotation around x axis)
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.cylinder_radius = cylinder_radius

        self.width = make_as_trajectory(width)
        self.height = make_as_trajectory(height)
        self.color = make_as_trajectory(color)
        self.theta = make_as_trajectory(theta)
        self.phi = make_as_trajectory(phi)
        self.angle = make_as_trajectory(angle)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        width = return_for_time_t(self.width, t)
        height = return_for_time_t(self.height, t)
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)
        color = return_for_time_t(self.color, t)
        # TODO: is there a way to make this object once in configure then update with radius in eval_at?
        self.stim_object = shapes.GlCylindricalWithPhiEllipse(width=width, 
                                                            height=height,
                                                            cylinder_radius=self.cylinder_radius,
                                                            color=color,
                                                            n_steps=36).rotate(np.radians(theta), np.radians(phi), np.radians(angle))

class MovingSpot(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, radius=10, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0):
        """
        Stimulus consisting of a circular patch on the surface of a sphere. Patch is circular in spherical coordinates.

        :param radius: radius of circle in degrees
        :param sphere_radius: Radius of the sphere (meters)
        :param color: [r,g,b,a] or mono. Color of the patch
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.sphere_radius = sphere_radius

        self.radius = make_as_trajectory(radius)
        self.color = make_as_trajectory(color)
        self.theta = make_as_trajectory(theta)
        self.phi = make_as_trajectory(phi)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        radius = return_for_time_t(self.radius, t)
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        color = return_for_time_t(self.color, t)
        # TODO: is there a way to make this object once in configure then update with radius in eval_at?
        self.stim_object = shapes.GlSphericalCirc(circle_radius=radius,
                                                sphere_radius=self.sphere_radius,
                                                color=color,
                                                n_steps=36).rotate(np.radians(theta), np.radians(phi), 0)

class LoomingCircle(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, radius=0.5, color=(1, 1, 1, 1), starting_distance=1, speed=-1, n_steps=36):
        """
        Circle looming towards animal.
        
        :param radius: radius of circle in meters
        :param color: [r,g,b,a] or mono. Color of the circle
        :param starting_distance: distance from animal to start the circle in meters
        :param speed: speed of the circle in meters per second
        :param n_steps: number of steps to draw the circle
        """
        self.color = make_as_trajectory(color)
        self.speed = make_as_trajectory(speed)
        self.starting_distance = starting_distance
        self.radius = radius
        self.n_steps = n_steps
        self.t_prev = 0

        self.stim_object = shapes.GlCircle(color=return_for_time_t(self.color, 0), 
                                        center=(0, self.starting_distance, 0), 
                                        radius=self.radius, 
                                        n_steps=self.n_steps)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        color = return_for_time_t(self.color, t)
        speed = return_for_time_t(self.speed, t)
                
        self.stim_object = self.stim_object.translate((0, speed * (t - self.t_prev), 0)
                                ).set_color(util.get_rgba(color))
        self.t_prev = t

class UniformWhiteNoise(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, width=10, height=10, sphere_radius=1, distribution_data=None,
                  theta=0, phi=0, angle=0, update_rate=60.0, start_seed=0):
        """
        Stimulus consisting of a rectangular patch on the surface of a sphere. Patch is rectangular in spherical coordinates.

        :param width: Width in degrees (azimuth)
        :param height: Height in degrees (elevation)
        :param sphere_radius: Radius of the sphere (meters)
        :param distribution_data: dict. containing name and args/kwargs for random distribution (see stimpack.visual_stim.distribution)
        :param update_rate: Hz, update rate of bar intensity
        :param start_seed: seed with which to start rng at the beginning of the stimulus presentation
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        :param angle: degrees orientation of patch (roll rotation around x axis)
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.width = width
        self.height = height
        self.sphere_radius = sphere_radius
        self.theta = theta
        self.phi = phi
        self.angle = angle
        self.update_rate = update_rate
        self.start_seed = start_seed

        # get the noise distribution
        if distribution_data is None:
            distribution_data = {'name': 'Uniform',
                                 'rand_min': 0,
                                 'rand_max': 1}
        self.noise_distribution = distribution.make_as_distribution(distribution_data)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        # set the seed
        seed = int(round(self.start_seed + t*self.update_rate))
        np.random.seed(seed)

        color = self.noise_distribution.get_random_values(1)
        color = [color, color, color, 1]
        # TODO: is there a way to make this object once in configure then update with width/height in eval_at?
        self.stim_object = shapes.GlSphericalRect(width=self.width,
                                                height=self.height,
                                                sphere_radius=self.sphere_radius,
                                                color=color).rotate(np.radians(self.theta), np.radians(self.phi), np.radians(self.angle))

class TexturedSphericalPatch(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)
        self.use_texture = True

    def configure(self, width=10, height=10, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0, angle=0, n_steps_x=12, n_steps_y=12):
        """
        Stimulus consisting of a rectangular patch on the surface of a sphere. Patch is rectangular in spherical coordinates.

        :param width: Width in degrees (azimuth)
        :param height: Height in degrees (elevation)
        :param sphere_radius: Radius of the sphere (meters)
        :param color: [r,g,b,a] or mono. Color of the patch
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        :param angle: degrees orientation of patch (roll rotation around x axis)
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.width = width
        self.height = height
        self.sphere_radius = sphere_radius
        self.color = color
        self.theta = theta
        self.phi = phi
        self.angle = angle

        self.stim_object = shapes.GlSphericalTexturedRect(width=self.width,
                                                        height=self.height,
                                                        sphere_radius=self.sphere_radius,
                                                        color=self.color, n_steps_x=n_steps_x, n_steps_y=n_steps_y, texture=True
                                                        ).rotate(np.radians(self.theta), np.radians(self.phi), np.radians(self.angle))

    def updateTexture(self):
        # overwrite in subclass
        pass

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        # overwrite in subclass
        pass

class RandomGridOnSphericalPatch(TexturedSphericalPatch):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, patch_width=5, patch_height=5, distribution_data=None, update_rate=60.0, start_seed=0,
                  width=30, height=30, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0, angle=0, rgb_texture=False, n_steps_x=12, n_steps_y=12):
        """
        Random square grid pattern painted on a spherical patch.

        :param patch width: Azimuth extent (degrees) of each patch
        :param patch height: Elevation extent (degrees) of each patch
        :param distribution_data: dict. containing name and args/kwargs for random distribution (see stimpack.visual_stim.distribution)
        :param update_rate: Hz, update rate of bar intensity
        :param start_seed: seed with which to start rng at the beginning of the stimulus presentation

        :other params: see TexturedSphericalPatch
        """
        self.rgb_texture = rgb_texture

        super().configure(width=width, height=height, sphere_radius=sphere_radius, color=color, theta=theta, phi=phi, angle=angle, n_steps_x=n_steps_x, n_steps_y=n_steps_y)

        # get the noise distribution
        if distribution_data is None:
            distribution_data = {'name': 'Uniform',
                                 'rand_min': 0,
                                 'rand_max': 1}
        self.noise_distribution = distribution.make_as_distribution(distribution_data)

        self.patch_width = patch_width
        self.patch_height = patch_height
        self.start_seed = start_seed
        self.update_rate = update_rate

        self.n_patches_width = int(np.floor(width/self.patch_width))
        self.n_patches_height = int(np.floor(height/self.patch_height))

        if self.rgb_texture:
            img = np.zeros((self.n_patches_height, self.n_patches_width, 3)).astype(np.uint8)
        else:
            img = np.zeros((self.n_patches_height, self.n_patches_width)).astype(np.uint8)
        self.add_texture_gl(img, texture_interpolation='NEAREST')

    def updateTexture(self, t):
        # set the seed
        seed = int(round(self.start_seed + t*self.update_rate))
        np.random.seed(seed)

        # get the random values
        if self.rgb_texture:  # shape = (x, y, 3)
            face_colors = 255*self.noise_distribution.get_random_values((self.n_patches_height, self.n_patches_width, 3))
            img = np.reshape(face_colors, (self.n_patches_height, self.n_patches_width, 3)).astype(np.uint8)
        else:  # shape = (x, y) monochromatic
            face_colors = 255*self.noise_distribution.get_random_values((self.n_patches_height, self.n_patches_width))
            img = np.reshape(face_colors, (self.n_patches_height, self.n_patches_width)).astype(np.uint8)

        # TEST CHECKERBOARD
        # x = np.zeros((self.n_patches_height, self.n_patches_width), dtype=int)
        # x[1::2, ::2] = 255
        # x[::2, 1::2] = 255
        # img = x.astype(np.uint8)

        self.update_texture_gl(img)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        self.updateTexture(t)

class TexturedCylinder(BaseProgram):
    def __init__(self, screen, **kwargs):
        super().__init__(screen=screen, **kwargs)
        self.use_texture = True

    def configure(self, color=[1, 1, 1, 1], cylinder_radius=1, cylinder_location=(0,0,0), cylinder_height=10, theta=0, phi=0, angle=0.0):
        """
        Parent class for a Cylinder with a texture painted on it. Fly is at (0, 0, 0).

        :param color: [r,g,b,a] color of cylinder. Applied to entire texture, which is monochrome.
        :param cylinder_radius: meters
        :param cylinder_height: meters
        :param theta: degrees, azimuth of the center of the patch (yaw rotation around z axis)
        :param phi: degrees, elevation of the center of the patch (pitch rotation around y axis)
        :param angle: degrees orientation of patch (roll rotation around x axis)
        """
        self.color = color
        self.cylinder_radius = cylinder_radius
        self.cylinder_location = cylinder_location
        self.cylinder_height = cylinder_height
        self.theta = make_as_trajectory(theta)
        self.phi = make_as_trajectory(phi)
        self.angle = make_as_trajectory(angle)

    def updateTexture(self):
        # overwrite in subclass
        pass

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        # overwrite in subclass
        pass

class CylindricalGrating(TexturedCylinder):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, period=20, mean=0.5, contrast=1.0, offset=0.0, grating_angle=0.0, profile='sine',
                  color=[1, 1, 1, 1], cylinder_radius=1, cylinder_location=(0,0,0), cylinder_height=10, theta=0, phi=0, angle=0.0,
                  n_steps_x=512, n_steps_y=512):
        """
        Grating texture painted on a cylinder.

        :param period: spatial period, degrees
        :param mean: mean intensity of grating texture
        :param contrast: Weber contrast of grating texture
        :param offset: phase offset of grating texture, degrees
        :param profile: 'sine' or 'square'; spatial profile of grating texture
        :param n_steps_x: number of steps in x direction to draw the texture (approximate; lowerbound)
        :param n_steps_y: number of steps in y direction to draw the texture (approximate; lowerbound)

        :params color, cylinder_radius, cylinder_height, theta, phi, angle: see parent class
        *Any of these params except cylinder_radius, cylinder_height, profile, n_steps_x, and n_steps_y can be passed as a trajectory dict to vary as a function of time
        """
        super().configure(color=color, cylinder_radius=cylinder_radius, cylinder_location=cylinder_location, cylinder_height=cylinder_height, theta=theta, phi=phi, angle=angle)

        self.period = period
        self.mean = mean
        self.contrast = contrast
        self.offset = offset
        self.grating_angle = grating_angle
        self.profile = profile

        t = 0
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)

        circumference = 2*np.pi*self.cylinder_radius
        cylinder_y_x_ratio = self.cylinder_height / circumference # ratio of y extent to x extent of cylinder
        cylinder_x_angular_extent_rad = 2 * np.pi # angular extent of cylinder in x direction
        cylinder_y_angulear_extent_rad = cylinder_y_x_ratio * cylinder_x_angular_extent_rad # angular extent of cylinder in y direction 

        # make the texture image

        # If the grating is parallel to the cylinder axis:
        #    Define the 1-cycle texture in the x direction, then repeat it along x direction and stretch it out in the y direction
        #    Grating period is in the x direction. 
        #    If the period is not a divisor of 360, then the grating will have a seam.
        if np.isclose(np.mod(self.grating_angle, 180), 0.0):
            patch_x_angular_extent_rad = 2 * np.pi # angular extent of patch in x direction
            period_x_rad = np.radians(self.period)
            n_patches_x = cylinder_x_angular_extent_rad / period_x_rad
            n_patches_y = 1 # placeholder
            n_steps_x_per_patch = int(np.ceil(n_steps_x / n_patches_x))
            xx_patch = np.linspace(0, patch_x_angular_extent_rad, n_steps_x_per_patch, endpoint=False)

            img = np.sin(np.radians(offset) + xx_patch)

            if np.isclose(np.mod(self.grating_angle, 360), 180.0): # If grating angle is 180, flip the image
                img = np.flip(img, axis=0)
            
            img = np.expand_dims(img, axis=0)  # pass as x by 1, gets stretched out by shader
        
        # If the grating is orthogonal to the cylinder axis:
        #    Define the 1-cycle texture in the y direction, then repeat it along y direction and stretch it out in the x direction
        #    Grating period is defined relative to the cylinder full angle (360 degrees) and circumference.
        #    i.e. for a tower with a circumference of 1m, a period of 60 degrees will correspond to 1/6 m height.
        elif np.isclose(np.mod(self.grating_angle, 180), 90.0): 
            patch_y_angular_extent_rad = 2 * np.pi # angular extent of patch in y direction
            period_y_rad = np.radians(self.period)
            n_patches_x = 1 # placeholder
            n_patches_y = cylinder_y_angulear_extent_rad / period_y_rad
            n_steps_y_per_patch = int(np.ceil(n_steps_y / n_patches_y))
            yy_patch = np.linspace(0, patch_y_angular_extent_rad, n_steps_y_per_patch, endpoint=False)
            
            img = np.sin(np.radians(offset) + yy_patch)

            if np.isclose(np.mod(self.grating_angle, 360), 270.0): # If grating angle is 270, flip the image
                img = np.flip(img, axis=0)
            
            img = np.expand_dims(img, axis=1)  # pass as 1 by y, gets stretched out by shader
        
        # If the grating is at an angle to the cylinder axis:
        #    Each cycle of the grating is sheared by the grating angle, 
        #       such that along the x axis, the period is the same as if the grating were parallel to the cylinder axis
        #    The texture is a 2D patch, where the x axis is one cycle of the grating, and y = x / tan(grating_angle).
        #    The texture is then repeated along x and y directions by appropriate amounts to cover the cylinder.
        else:
            tangent_angle = np.tan(np.radians(self.grating_angle))
            patch_x_y_ratio = np.abs(tangent_angle) # ratio of x extent to y extent of patch

            patch_x_angular_extent_rad = 2 * np.pi # angular extent of patch in x direction
            patch_y_angular_extent_rad = patch_x_angular_extent_rad / patch_x_y_ratio # angular extent of patch in y direction

            period_x_rad = np.radians(self.period)
            period_y_rad = period_x_rad / patch_x_y_ratio

            n_patches_x = cylinder_x_angular_extent_rad / period_x_rad
            n_patches_y = cylinder_y_angulear_extent_rad / period_y_rad

            if n_patches_y < 1:
                patch_y_angular_extent_rad *= n_patches_y
                n_patches_y = 1
            
            # number of steps in one patch of the texture
            n_steps_x_per_patch = int(np.ceil(n_steps_x / n_patches_x))
            n_steps_y_per_patch = int(np.ceil(n_steps_y / n_patches_y))

            xx_patch = np.linspace(0, patch_x_angular_extent_rad, n_steps_x_per_patch, endpoint=False)
            yy_patch = np.linspace(0, patch_y_angular_extent_rad, n_steps_y_per_patch, endpoint=False)
                
            img = np.zeros((n_steps_y_per_patch, n_steps_x_per_patch))
            for i in range(n_steps_x_per_patch):
                for j in range(n_steps_y_per_patch):
                    x_rot = xx_patch[i] + yy_patch[j]*tangent_angle
                    img[j,i] = np.sin(np.radians(offset) + x_rot)

        if self.profile == 'square':
            img[img >= 0] = 1
            img[img < 0] = -1
        img = (255*(mean + contrast*mean*img)).astype(np.uint8)

        texture_interpolation = 'LINEAR' if self.profile == 'sine' else 'NEAREST'

        self.add_texture_gl(img, texture_interpolation=texture_interpolation)

        self.stim_object = shapes.GlCylinder(cylinder_height=self.cylinder_height,
                                            cylinder_radius=self.cylinder_radius,
                                            cylinder_angular_extent=360.0,
                                            color=[1, 1, 1, 1],
                                            texture=True,
                                            n_texture_repeat_x=n_patches_x,
                                            n_texture_repeat_y=n_patches_y
                                        ).rotate(np.radians(theta), np.radians(phi), np.radians(angle)
                                        ).translate(self.cylinder_location)
        
        self.n_patches_x = n_patches_x
        self.n_patches_y = n_patches_y

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

class RotatingGrating(CylindricalGrating):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, rate=10, hold_duration = 0, period=20, mean=0.5, contrast=1.0, offset=0.0, grating_angle=0.0, profile='sine',
                  color=[1, 1, 1, 1], cylinder_radius=1, cylinder_location=(0,0,0), cylinder_height=10, theta=0, phi=0, angle=0.0,
                  n_steps_x=512, n_steps_y=512):
        """
        Subclass of CylindricalGrating that rotates the grating along the varying axis of the grating.

        Note that the rotation effect is achieved by translating the texture on a semi-cylinder. This
        allows for arbitrary spatial periods to be achieved with no discontinuities in the grating

        :param rate: rotation rate, degrees/sec
        :param hold_duration: duration for which the initial image is held (seconds)
        :other params: see CylindricalGrating, TexturedCylinder
        """
        super().configure(period=period, mean=mean, contrast=contrast, offset=offset, grating_angle=grating_angle, profile=profile,
                          color=color, cylinder_radius=cylinder_radius, cylinder_location=cylinder_location, cylinder_height=cylinder_height,
                          theta=theta, phi=phi, angle=angle, n_steps_x=n_steps_x, n_steps_y=n_steps_y)

        self.rate = make_as_trajectory(rate)
        self.hold_duration = hold_duration

        self.theta_prev = return_for_time_t(self.theta, 0)
        self.phi_prev = return_for_time_t(self.phi, 0)
        self.angle_prev = return_for_time_t(self.angle, 0)
        self.t_prev = 0

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)
        rate = return_for_time_t(self.rate, t)

        if t < self.hold_duration:
            grating_rotation_dt = 0
            self.t_prev = self.hold_duration
        else:
            grating_rotation_dt = rate * (t - self.t_prev)
            self.t_prev = t

        shift_u = grating_rotation_dt / self.period
        self.stim_object = self.stim_object.translate((-self.cylinder_location[0], -self.cylinder_location[1], -self.cylinder_location[2])
                                            ).rotate(np.radians(theta - self.theta_prev), np.radians(phi - self.phi_prev), np.radians(angle - self.angle_prev)
                                            ).translate(self.cylinder_location
                                            ).shift_texture((shift_u, 0)
                                            )
        self.theta_prev = theta
        self.phi_prev = phi
        self.angle_prev = angle

class ExpandingEdges(TexturedCylinder):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, rate=60, period=20, vert_extent=80, theta_offset=0,
                  expander_color = 0.0, opposite_color = 1.0, width_0=2, n_theta_pixels=360, hold_duration=0.550,
                  color=[1, 1, 1, 1], cylinder_radius=1, theta=0, phi=0, angle=0.0, cylinder_location=(0, 0, 0)):
        """
        Periodic bars of randomized intensity painted on the inside of a cylinder.

        :param rate: rotation rate of the expanding bars, degrees/sec
        :param period: spatial period (degrees)
        :param width_0: width (degrees) of each expanding bar at the beginning
        :param vert_extent: vertical extent (degrees) of bars
        :param theta_offset: phase offset of periodic bar pattern (degrees)
        :param expander_color: color of the expanding edge [0, 1]
        :param opposite_color: color of the diminishing edge [0, 1]
        :param n_theta_pixels: number of pixels in theta for the image painted onto the cylinder
        :param hold_duration: duration for which the initial image is held (seconds)
        :other params: see TexturedCylinder
        """
        # assuming fly is at (0,0,0), calculate cylinder height required to achieve vert_extent (degrees)
        # tan(vert_extent/2) = (cylinder_height/2) / cylinder_radius
        assert vert_extent < 180
        cylinder_height = 2 * cylinder_radius * np.tan(np.radians(vert_extent/2))
        super().configure(color=color, cylinder_radius=cylinder_radius, cylinder_height=cylinder_height, theta=theta, phi=phi, angle=angle)

        self.rate = rate
        self.period = period
        self.vert_extent = vert_extent
        self.theta_offset = theta_offset
        self.cylinder_location = cylinder_location

        self.expander_color = expander_color
        self.opposite_color = opposite_color
        self.width_0 = width_0 #degrees
        self.n_x = int(n_theta_pixels) # number of theta pixels in img (approximate, as the number of pixels in each subimage is floored)
        self.hold_duration = hold_duration #seconds

        self.n_subimg = int(np.floor(360/self.period)) # number of subimages to be repeated
        self.n_x_subimg = int(np.floor(self.n_x / self.n_subimg)) # number of theta pixels in each subimg
        self.rate_abs = np.abs(rate)

        self.subimg_mask = np.empty(self.n_x_subimg, dtype=bool)
        self.subimg = np.empty((1,self.n_x_subimg), dtype=np.uint8)

        img = np.zeros((1, int(self.n_x))).astype(np.uint8)
        self.add_texture_gl(img, texture_interpolation='NEAREST')

        # Only renders part of the cylinder if the period is not a divisor of 360
        self.cylinder_angular_extent = self.n_subimg * self.period  # degrees

        self.stim_object_template = shapes.GlCylinder(cylinder_height=self.cylinder_height,
                                                    cylinder_radius=self.cylinder_radius,
                                                    cylinder_angular_extent=self.cylinder_angular_extent,
                                                    color=self.color,
                                                    cylinder_location=self.cylinder_location,
                                                    texture=True)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)

        self.stim_object = copy.copy(self.stim_object_template).rotate(np.radians(theta), np.radians(phi), np.radians(angle))

        # Construct one subimg

        fill_to_degrees = self.width_0 + self.rate_abs * max(t - self.hold_duration, 0)
        fill_to_proportion = min(fill_to_degrees/self.period, 1)
        fill_to_subimg_x = int(np.round(fill_to_proportion * self.n_x_subimg))

        self.subimg_mask[:fill_to_subimg_x] = True
        self.subimg_mask[fill_to_subimg_x:] = False
        if np.sign(self.rate) > 0:
            self.subimg_mask = np.flip(self.subimg_mask)

        self.subimg[:,self.subimg_mask] = np.uint8(self.expander_color * 255)
        self.subimg[:,~self.subimg_mask] = np.uint8(self.opposite_color * 255)
        img = np.tile(self.subimg, self.n_subimg)

        # theta_offset
        theta_offset_degs = self.period * (self.theta_offset / 360)
        img = np.roll(img, int(np.round(theta_offset_degs * self.n_x / 360)), axis=1)

        self.update_texture_gl(img)

class RandomBars(TexturedCylinder):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, period=20, width=5, vert_extent=80, theta_offset=0, background=0.5,
                  distribution_data=None, update_rate=60.0, start_seed=0,
                  color=[1, 1, 1, 1], cylinder_radius=1, theta=0, phi=0, angle=0.0, cylinder_location=(0, 0, 0)):
        """
        Periodic bars of randomized intensity painted on the inside of a cylinder.

        :param period: spatial period (degrees) of bar locations
        :param width: width (degrees) of each bar
        :param vert_extent: vertical extent (degrees) of bars
        :param theta_offset: offset of periodic bar pattern (degrees)
        :param background: intensity (mono) of texture background, where no bars appear
        :param distribution_data: dict. containing name and args/kwargs for random distribution (see stimpack.visual_stim.distribution)
        :param update_rate: Hz, update rate of bar intensity
        :param start_seed: seed with which to start rng at the beginning of the stimulus presentation

        :other params: see TexturedCylinder
        """
        # assuming fly is at (0,0,0), calculate cylinder height required to achieve vert_extent (degrees)
        # tan(vert_extent/2) = (cylinder_height/2) / cylinder_radius
        assert vert_extent < 180
        cylinder_height = 2 * cylinder_radius * np.tan(np.radians(vert_extent/2))
        super().configure(color=color, cylinder_radius=cylinder_radius, cylinder_height=cylinder_height, theta=theta, phi=phi, angle=angle)

        # get the noise distribution
        if distribution_data is None:
            distribution_data = {'name': 'Uniform',
                                 'rand_min': 0,
                                 'rand_max': 1}
        self.noise_distribution = distribution.make_as_distribution(distribution_data)

        self.period = period
        self.width = width
        self.vert_extent = vert_extent
        self.theta_offset = theta_offset
        self.background = background
        self.update_rate = update_rate
        self.start_seed = start_seed
        self.cylinder_location = cylinder_location

        img = np.zeros((1, 255)).astype(np.uint8)
        self.add_texture_gl(img, texture_interpolation='NEAREST')

        # Only renders part of the cylinder if the period is not a divisor of 360
        self.n_bars = int(np.floor(360/self.period))
        self.cylinder_angular_extent = self.n_bars * self.period  # degrees

        self.stim_object_template = shapes.GlCylinder(cylinder_height=self.cylinder_height,
                                                    cylinder_radius=self.cylinder_radius,
                                                    cylinder_angular_extent=self.cylinder_angular_extent,
                                                    color=self.color,
                                                    cylinder_location=self.cylinder_location,
                                                    texture=True)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        theta = return_for_time_t(self.theta, t)
        phi = return_for_time_t(self.phi, t)
        angle = return_for_time_t(self.angle, t)

        self.stim_object = copy.copy(self.stim_object_template).rotate(np.radians(theta), np.radians(phi), np.radians(angle))

        # set the seed
        seed = int(round(self.start_seed + t*self.update_rate))
        np.random.seed(seed)
        # get the random values
        bar_colors = self.noise_distribution.get_random_values(self.n_bars)

        # get the x-profile
        xx = np.mod(np.linspace(0, self.cylinder_angular_extent, 256)[:-1] + self.theta_offset, 360)
        profile = np.array([bar_colors[int(x/self.period)] for x in xx])
        duty_cycle = self.width/self.period
        inds = np.modf(xx/self.period)[0] > duty_cycle
        profile[inds] = self.background

        # make the texture
        img = np.expand_dims(255*profile, axis=0).astype(np.uint8)  # pass as x by 1, gets stretched out by shader
        self.update_texture_gl(img)

class RandomGrid(TexturedCylinder):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, patch_width=10, patch_height=10, cylinder_vertical_extent=160, cylinder_angular_extent=360,
                  distribution_data=None, update_rate=60.0, start_seed=0,
                  color=[1, 1, 1, 1], cylinder_radius=1, theta=0, phi=0, angle=0.0, rgb_texture=False):
        """
        Random square grid pattern painted on the inside of a cylinder.

        :param patch width: Azimuth extent (degrees) of each patch
        :param patch height: Elevation extent (degrees) of each patch
        :param cylinder_vertical_extent: Elevation extent of the entire cylinder (degrees)
        :param cylinder_angular_extent: Azimuth extent of the cylinder `texture` (degrees)
        :param distribution_data: dict. containing name and args/kwargs for random distribution (see stimpack.visual_stim.distribution)
        :param update_rate: Hz, update rate of bar intensity
        :param start_seed: seed with which to start rng at the beginning of the stimulus presentation

        :other params: see TexturedCylinder
        """
        self.rgb_texture = rgb_texture

        # Only renders part of the cylinder if the period is not a divisor of cylinder_angular_extent
        self.n_patches_width = int(np.floor(cylinder_angular_extent/patch_width))
        self.cylinder_angular_extent = self.n_patches_width * patch_width

        # assuming fly is at (0,0,0), calculate cylinder height required to achieve (approx.) vert_extent (degrees)
        # actual vert. extent is based on floor-nearest integer number of patch heights
        assert cylinder_vertical_extent < 180
        self.n_patches_height = int(np.floor(cylinder_vertical_extent/patch_height))
        patch_height_m = cylinder_radius * np.tan(np.radians(patch_height))  # in meters
        cylinder_height = self.n_patches_height * patch_height_m

        super().configure(color=color, angle=angle, cylinder_radius=cylinder_radius, cylinder_height=cylinder_height, theta=theta, phi=phi)

        # get the noise distribution
        if distribution_data is None:
            distribution_data = {'name': 'Uniform',
                                 'rand_min': 0,
                                 'rand_max': 1}
        self.noise_distribution = distribution.make_as_distribution(distribution_data)

        self.patch_width = patch_width
        self.patch_height = patch_height
        self.start_seed = start_seed
        self.update_rate = update_rate

        if self.rgb_texture:
            img = np.zeros((self.n_patches_height, self.n_patches_width, 3)).astype(np.uint8)
        else:
            img = np.zeros((self.n_patches_height, self.n_patches_width)).astype(np.uint8)

        self.add_texture_gl(img, texture_interpolation='NEAREST')

        self.stim_object = shapes.GlCylinder(cylinder_height=self.cylinder_height,
                                            cylinder_radius=self.cylinder_radius,
                                            cylinder_angular_extent=self.cylinder_angular_extent,
                                            color=self.color,
                                            texture=True
                                            ).rotate(np.radians(self.theta), np.radians(self.phi), np.radians(self.angle))

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        # set the seed
        seed = int(round(self.start_seed + t*self.update_rate))
        np.random.seed(seed)

        # get the random values
        if self.rgb_texture:  # shape = (x, y, 3)
            face_colors = 255*self.noise_distribution.get_random_values((self.n_patches_height, self.n_patches_width, 3))
            img = np.reshape(face_colors, (self.n_patches_height, self.n_patches_width, 3)).astype(np.uint8)
        else:  # shape = (x, y) monochromatic
            face_colors = 255*self.noise_distribution.get_random_values((self.n_patches_height, self.n_patches_width))
            img = np.reshape(face_colors, (self.n_patches_height, self.n_patches_width)).astype(np.uint8)
        # make the texture
        self.update_texture_gl(img)

class Checkerboard(TexturedCylinder):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, patch_width=4, patch_height=4, cylinder_vertical_extent=160, cylinder_angular_extent=360,
                  color=[1, 1, 1, 1], cylinder_radius=1, theta=0, phi=0, angle=0.0):
        """
        Periodic checkerboard pattern painted on the inside of a cylinder.

        :param patch width: Azimuth extent (degrees) of each patch
        :param patch height: Elevation extent (degrees) of each patch
        :param cylinder_vertical_extent: Elevation extent of the entire cylinder (degrees)
        :param cylinder_angular_extent: Azimuth extent of the cylinder texture (degrees)

        :other params: see TexturedCylinder
        """

        # Only renders part of the cylinder if the period is not a divisor of cylinder_angular_extent
        self.n_patches_width = int(np.floor(cylinder_angular_extent/patch_width))
        self.cylinder_angular_extent = self.n_patches_width * patch_width

        # assuming fly is at (0,0,0), calculate cylinder height required to achieve (approx.) vert_extent (degrees)
        # actual vert. extent is based on floor-nearest integer number of patch heights
        assert cylinder_vertical_extent < 180
        self.n_patches_height = int(np.floor(cylinder_vertical_extent/patch_height))
        patch_height_m = cylinder_radius * np.tan(np.radians(patch_height))  # in meters
        cylinder_height = self.n_patches_height * patch_height_m

        super().configure(color=color, angle=angle, cylinder_radius=cylinder_radius, cylinder_height=cylinder_height)

        self.patch_width = patch_width
        self.patch_height = patch_height

        # Only renders part of the cylinder if the period is not a divisor of 360
        self.n_patches_width = int(np.floor(360/self.patch_width))
        self.cylinder_angular_extent = self.n_patches_width * self.patch_width
        self.patch_height_m = self.cylinder_radius * np.tan(np.radians(self.patch_height))  # in meters
        self.n_patches_height = int(np.floor(self.cylinder_height/self.patch_height_m))

        # create the texture
        face_colors = np.zeros((self.n_patches_height, self.n_patches_width))
        face_colors[0::2, 0::2] = 1
        face_colors[1::2, 1::2] = 1

        # make and apply the texture
        img = (255*face_colors).astype(np.uint8)
        self.add_texture_gl(img, texture_interpolation='NEAREST')

        self.stim_object = shapes.GlCylinder(cylinder_height=self.cylinder_height,
                                            cylinder_radius=self.cylinder_radius,
                                            cylinder_angular_extent=self.cylinder_angular_extent,
                                            color=self.color,
                                            texture=True
                                            ).rotate(np.radians(self.theta), np.radians(self.phi), np.radians(self.angle))

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

class MovingBox(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, x_length=1, y_length=1, z_length=1, color=[1, 1, 1, 1], x=0, y=0, z=0, yaw=0, pitch=0, roll=0):
        """
        Stimulus consisting of a rectangular patch on the surface of a sphere. Patch is rectangular in spherical coordinates.

        :param x_length: meters, length of box in x direction
        :param y_length: meters, length of box in y direction
        :param z_length: meters, length of box in z direction
        :param color: [r,g,b,a] or mono. Color of the box
        :param x: meters, x position of center of sphere
        :param y: meters, y position of center of sphere
        :param z: meters, z position of center of sphere
        :param yaw: degrees, rotation around z axis
        :param pitch: degrees, rotation around y axis
        :param roll: degrees, rotation around x axis
        *Any of these params can be passed as a trajectory dict to vary these as a function of time elapsed
        """
        self.x_length = make_as_trajectory(x_length)
        self.y_length = make_as_trajectory(y_length)
        self.z_length = make_as_trajectory(z_length)
        self.color = make_as_trajectory(color)
        self.x = make_as_trajectory(x)
        self.y = make_as_trajectory(y)
        self.z = make_as_trajectory(z)
        self.yaw = make_as_trajectory(yaw)
        self.pitch = make_as_trajectory(pitch)
        self.roll = make_as_trajectory(roll)
        
        color = (0,0,0,1)
        colors = {'+x': color, '-x': color,
                  '+y': color, '-y': color,
                  '+z': color, '-z': color}
        self.stim_object_template = shapes.GlBox(colors, (0, 0, 0), {'x':1, 'y':1, 'z':1})
        
    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        x_length = return_for_time_t(self.x_length, t)
        y_length = return_for_time_t(self.y_length, t)
        z_length = return_for_time_t(self.z_length, t)
        color    = return_for_time_t(self.color, t)
        x        = return_for_time_t(self.x, t)
        y        = return_for_time_t(self.y, t)
        z        = return_for_time_t(self.z, t)
        yaw    = return_for_time_t(self.yaw, t)
        pitch      = return_for_time_t(self.pitch, t)
        roll    = return_for_time_t(self.roll, t)

        self.stim_object = copy.copy(self.stim_object_template
                                    ).scale(np.array([x_length, y_length, z_length]).reshape(3,1)
                                    ).rotate(np.radians(yaw), np.radians(pitch), np.radians(roll)
                                    ).translate((x, y, z)
                                    ).set_color(util.get_rgba(color))

class Tower(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen)

    def configure(self, color=[1, 0, 0, 1], cylinder_radius=0.5, cylinder_height=0.5, cylinder_location=[+5, 0, 0], n_faces=16):
        """
        Cylindrical tower object in arbitrary x, y, z coords.

        :param color: [r,g,b,a] color of cylinder. Applied to entire texture, which is monochrome
        :param cylinder_radius: meters
        :param cylinder_height: meters
        :param cylinder_location: [x, y, z] location of the center of the cylinder, meters
        :param n_faces: number of quad faces to make the cylinder out of
        """
        self.color = color
        self.cylinder_radius = cylinder_radius
        self.cylinder_height = cylinder_height
        self.cylinder_location = cylinder_location
        self.n_faces = n_faces

        self.stim_object = shapes.GlCylinder(cylinder_height=self.cylinder_height,
                                            cylinder_radius=self.cylinder_radius,
                                            cylinder_location=self.cylinder_location,
                                            color=self.color,
                                            n_faces=self.n_faces)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

class Forest(BaseProgram):
    def __init__(self, screen):
        super().__init__(screen=screen, num_tri=1000)

    def configure(self, color=[1, 1, 1, 1], cylinder_radius=0.5, cylinder_height=0.5, n_faces=16, cylinder_locations=[[+5, 0, 0]]):
        """
        Collection of tower objects created with a single shader program.

        """
        self.color = color
        self.cylinder_radius = cylinder_radius
        self.cylinder_height = cylinder_height
        self.cylinder_locations = cylinder_locations
        self.n_faces = n_faces

        self.stim_object = shapes.GlVertices()

        # This step is slow. Make template once then use .translate() on copies to make cylinders
        cylinder = shapes.GlCylinder(cylinder_height=self.cylinder_height,
                                    cylinder_radius=self.cylinder_radius,
                                    cylinder_location=[0, 0, 0],
                                    color=self.color,
                                    n_faces=self.n_faces)

        for tree_loc in self.cylinder_locations:
            new_cyl = copy.copy(cylinder).translate(tree_loc)
            self.stim_object.add(new_cyl)

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        pass

# %%

class PixMap(TexturedCylinder):
    def __init__(self, screen):
        super().__init__(screen=screen, num_tri=10000)

    def configure(self, memname='test', frame_size=None, rgb_texture=True, width=180, radius=1, 
                        n_steps=16, surface='cylindrical'):

        height = frame_size[0] / frame_size[1]
        height *= width

        self.rgb_texture=rgb_texture

        self.existing_shm = shared_memory.SharedMemory(name=memname)
        frame = np.ndarray(frame_size,dtype=np.uint8, buffer=self.existing_shm.buf)
        self.frame_size = frame_size

        self.add_texture_gl(frame, texture_interpolation='NEAREST')
        
        if surface == 'cylindrical':
            n_patches_height = frame_size[0]
            patch_height_m = radius * np.tan(np.radians(height/n_patches_height))  # in meters
            cylinder_height = n_patches_height * patch_height_m
            self.stim_object = shapes.GlCylinder(cylinder_height=cylinder_height, cylinder_angular_extent=280, 
                                                n_faces=n_steps, texture=True).rotate(np.radians(90),0,0)

        elif surface == 'cylindrical_with_phi':
            self.stim_object = shapes.GlCylindricalWithPhiRect(width= width,  # degrees, theta
                     height=height,  # degrees, phi
                     cylinder_radius=radius,  # meters
                     color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                     n_steps_x=n_steps,
                     n_steps_y=n_steps)
        # self.stim_object = GlSphericalTexturedRect(height=1080/1920*270/2, width=270, n_steps_x=48, n_steps_y=48, texture=True)
        
        elif surface == 'spherical':
            self.stim_object = shapes.GlSphericalTexturedRect(height=height, width=width, sphere_radius=radius,
                                                                n_steps_x = n_steps, n_steps_y = n_steps, 
                                                                color=[1,1,1,1], texture=True)
            # self.stim_object = shapes.GlSphericalTexturedRect(width=10,
            #                                                 height=10,
            #                                                 sphere_radius=1,
            #                                                 color=[1,1,1,1], n_steps_x=n_steps, n_steps_y=n_steps, texture=True)

        self.last_time = 0
        self.memname=memname        

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):

        frame = np.ndarray(self.frame_size,dtype=np.uint8, buffer=self.existing_shm.buf)
        self.update_texture_gl(frame)

    def destroy(self):
        super().destroy()
        self.existing_shm.close()

