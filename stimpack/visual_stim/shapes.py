import numpy as np
from numpy import matlib
from math import radians
from . import util

class GlVertices:
    def __init__(self, vertices=None, colors=None, tex_coords=None):
        self.vertices = vertices
        self.colors = colors
        self.tex_coords = tex_coords

    def add(self, obj):
        # add vertices
        if self.vertices is None:
            self.vertices = obj.vertices
        else:
            self.vertices = np.concatenate((self.vertices, obj.vertices), axis=1)

        # add colors
        if self.colors is None:
            self.colors = obj.colors
        else:
            self.colors = np.concatenate((self.colors, obj.colors), axis=1)

        # add tex_coords
        if self.tex_coords is None:
            self.tex_coords = obj.tex_coords
        else:
            self.tex_coords = np.concatenate((self.tex_coords, obj.tex_coords), axis=1)

    def rotate(self, z, x, y):
        """
        :param z: rotation around z axis (yaw), radians
        :param x: rotation around x axis (pitch), radians
        :param y: rotation around y axis (roll), radians
        """
        return GlVertices(vertices=util.rotate(self.vertices, z, x, y), colors=self.colors, tex_coords=self.tex_coords)

    def rotx(self, th):
        return GlVertices(vertices=util.rotx(self.vertices, th), colors=self.colors, tex_coords=self.tex_coords)

    def roty(self, th):
        return GlVertices(vertices=util.roty(self.vertices, th), colors=self.colors, tex_coords=self.tex_coords)

    def rotz(self, th):
        return GlVertices(vertices=util.rotz(self.vertices, th), colors=self.colors, tex_coords=self.tex_coords)

    def scale(self, amt):
        return GlVertices(vertices=util.scale(self.vertices, amt), colors=self.colors, tex_coords=self.tex_coords)

    def translate(self, amt):
        return GlVertices(vertices=util.translate(self.vertices, amt), colors=self.colors, tex_coords=self.tex_coords)

    def set_color(self, color):
        new_colors = np.tile(np.array(color), (self.vertices.shape[1], 1)).T
        return GlVertices(vertices=self.vertices, colors=new_colors, tex_coords=self.tex_coords)

    def shift_texture(self, shift):
        new_tex_coords = self.tex_coords + np.tile(shift, (self.tex_coords.shape[1], 1)).T
        return GlVertices(vertices=self.vertices, colors=self.colors, tex_coords=new_tex_coords)

    @property
    def data(self):
        if self.tex_coords is not None:
            data = np.concatenate((self.vertices, self.colors, self.tex_coords), axis=0)
        else:
            data = np.concatenate((self.vertices, self.colors), axis=0)
        return data.flatten(order='F')


class GlTri(GlVertices):
    def __init__(self, v1, v2, v3, color, tc1=None, tc2=None, tc3=None, texture=None):
        vertices = np.concatenate((v1, v2, v3)).reshape((3, 3), order='F')
        colors = np.concatenate((color, color, color)).reshape((4, 3), order='F')

        if tc1 is not None:
            tex_coords = np.concatenate((tc1, tc2, tc3)).reshape((2, 3), order='F')
        else:
            tex_coords = None
        super().__init__(vertices=vertices, colors=colors, tex_coords=tex_coords)


class GlQuad(GlVertices):
    def __init__(self, v1, v2, v3, v4, color, tc1=(0, 0), tc2=(1, 0), tc3=(1, 1), tc4=(0, 1), texture_shift=(0, 0), use_texture=False):
        super().__init__()
        if use_texture:
            self.add(GlTri(v1, v2, v3, color,
                           [sum(x) for x in zip(tc1, texture_shift)],
                           [sum(x) for x in zip(tc2, texture_shift)],
                           [sum(x) for x in zip(tc3, texture_shift)]))
            self.add(GlTri(v1, v3, v4, color,
                           [sum(x) for x in zip(tc1, texture_shift)],
                           [sum(x) for x in zip(tc3, texture_shift)],
                           [sum(x) for x in zip(tc4, texture_shift)]))
        else:
            self.add(GlTri(v1, v2, v3, color))
            self.add(GlTri(v1, v3, v4, color))

class GlCircle(GlVertices):
    '''
    Circle parallel to the xz plane
    '''
    def __init__(self, color=(1, 1, 1, 1), center=(0, 0, 0), radius=1.0, n_steps=36):
        # call the super constructor
        super().__init__()

        color = util.get_rgba(color)

        angles = np.linspace(0, 2*np.pi, n_steps+1)
        for wedge in range(n_steps):
            v1 = (radius*np.sin(angles[wedge]),
                  0,
                  radius*np.cos(angles[wedge]))
            v2 = (radius*np.sin(angles[wedge+1]),
                  0,
                  radius*np.cos(angles[wedge+1]))

            self.add(GlTri(v1, v2, (0,0,0), color).translate(center))

class GlCube(GlVertices):
    def __init__(self, colors=None, center=[0, 0, 0], side_length=1.0):
        # call the super constructor
        super().__init__()

        # set defaults
        if colors is None:
            colors = {}
        if '+x' not in colors:
            colors['+x'] = (0, 0, 1, 1)
        if '-x' not in colors:
            colors['-x'] = (0, 1, 0, 1)
        if '+y' not in colors:
            colors['+y'] = (1, 0, 0, 1)
        if '-y' not in colors:
            colors['-y'] = (0, 1, 1, 1)
        if '+z' not in colors:
            colors['+z'] = (1, 1, 0, 1)
        if '-z' not in colors:
            colors['-z'] = (1, 0, 1, 1)

        # shorten name for side length for readability
        s = side_length/2

        # add all of the faces
        self.add(GlQuad((+s, -s, -s), (+s, +s, -s), (+s, +s, +s), (+s, -s, +s), colors['+x']).translate(center))
        self.add(GlQuad((-s, -s, -s), (-s, +s, -s), (-s, +s, +s), (-s, -s, +s), colors['-x']).translate(center))
        self.add(GlQuad((+s, +s, -s), (-s, +s, -s), (-s, +s, +s), (+s, +s, +s), colors['+y']).translate(center))
        self.add(GlQuad((+s, -s, -s), (-s, -s, -s), (-s, -s, +s), (+s, -s, +s), colors['-y']).translate(center))
        self.add(GlQuad((+s, -s, +s), (+s, +s, +s), (-s, +s, +s), (-s, -s, +s), colors['+z']).translate(center))
        self.add(GlQuad((+s, -s, -s), (+s, +s, -s), (-s, +s, -s), (-s, -s, -s), colors['-z']).translate(center))

class GlBox(GlVertices):
    def __init__(self, colors=None, center=(0, 0, 0), side_lengths={'x':1.0, 'y':1.0, 'z':1.0}):
        # call the super constructor
        super().__init__()

        # set defaults
        if colors is None:
            colors = {}
        if '+x' not in colors:
            colors['+x'] = (0, 0, 1, 1)
        if '-x' not in colors:
            colors['-x'] = (0, 1, 0, 1)
        if '+y' not in colors:
            colors['+y'] = (1, 0, 0, 1)
        if '-y' not in colors:
            colors['-y'] = (0, 1, 1, 1)
        if '+z' not in colors:
            colors['+z'] = (1, 1, 0, 1)
        if '-z' not in colors:
            colors['-z'] = (1, 0, 1, 1)

        # shorten name for side length for readability
        x = side_lengths['x']/2
        y = side_lengths['y']/2
        z = side_lengths['z']/2

        # add all of the faces
        self.add(GlQuad((+x, -y, -z), (+x, +y, -z), (+x, +y, +z), (+x, -y, +z), colors['+x']).translate(center))
        self.add(GlQuad((-x, -y, -z), (-x, +y, -z), (-x, +y, +z), (-x, -y, +z), colors['-x']).translate(center))
        self.add(GlQuad((+x, +y, -z), (-x, +y, -z), (-x, +y, +z), (+x, +y, +z), colors['+y']).translate(center))
        self.add(GlQuad((+x, -y, -z), (-x, -y, -z), (-x, -y, +z), (+x, -y, +z), colors['-y']).translate(center))
        self.add(GlQuad((+x, -y, +z), (+x, +y, +z), (-x, +y, +z), (-x, -y, +z), colors['+z']).translate(center))
        self.add(GlQuad((+x, -y, -z), (+x, +y, -z), (-x, +y, -z), (-x, -y, -z), colors['-z']).translate(center))

class GlSphericalRect(GlVertices):
    def __init__(self,
                 width=20,  # degrees, theta
                 height=20,  # degrees, phi
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 n_steps_x=6,
                 n_steps_y=6):
        super().__init__()
        color = util.get_rgba(color)

        d_theta = (1/n_steps_x) * radians(width)
        d_phi = (1/n_steps_y) * radians(height)
        for rr in range(n_steps_y):
            for cc in range(n_steps_x):
                # render patch at the equator (phi=pi/2) so it's not near the poles
                # Also render it at theta = 90 degrees, for stimpack.visual_stim coordinates where heading (0,0,0) is +y axis
                theta = np.pi/2 + radians(width) * (-1/2 + (cc/n_steps_x))
                phi = np.pi/2 + radians(height) * (-1/2 + (rr/n_steps_y))
                v1 = util.spherical_to_cartesian(sphere_radius, theta, phi)
                v2 = util.spherical_to_cartesian(sphere_radius, theta, phi + d_phi)
                v3 = util.spherical_to_cartesian(sphere_radius, theta + d_theta, phi)
                v4 = util.spherical_to_cartesian(sphere_radius, theta + d_theta, phi + d_phi)
                self.add(GlTri(v1, v2, v4, color))
                self.add(GlTri(v1, v3, v4, color))

class GlSphericalTexturedRect(GlVertices):
    def __init__(self,
                 width=20,  # degrees, theta
                 height=20,  # degrees, phi
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 n_steps_x=6,
                 n_steps_y=6,
                 texture=False,
                 texture_shift=(0, 0)):
        super().__init__()
        color = util.get_rgba(color)

        d_theta = (1/n_steps_x) * radians(width)
        d_phi = (1/n_steps_y) * radians(height)
        for rr in range(n_steps_y):
            for cc in range(n_steps_x):
                # render patch at the equator (phi=pi/2) so it's not near the poles
                # Also render it at theta = 90 degrees, for stimpack.visual_stim coordinates where heading (0,0,0) is +y axis
                theta = np.pi/2 + radians(width) * (-1/2 + (cc/n_steps_x))
                phi = np.pi/2 + radians(height) * (-1/2 + (rr/n_steps_y))
                v1 = util.spherical_to_cartesian(sphere_radius, theta, phi)
                v2 = util.spherical_to_cartesian(sphere_radius, theta, phi + d_phi)
                v3 = util.spherical_to_cartesian(sphere_radius, theta + d_theta, phi)
                v4 = util.spherical_to_cartesian(sphere_radius, theta + d_theta, phi + d_phi)
                if texture:
                    tc1 = (cc/n_steps_x, rr/n_steps_y)
                    tc2 = (cc/n_steps_x, (rr+1)/n_steps_y)
                    tc3 = ((cc+1)/n_steps_x, rr/n_steps_y)
                    tc4 = ((cc+1)/n_steps_x, (rr+1)/n_steps_y)
                    self.add(GlTri(v1, v2, v4, color, [sum(x) for x in zip(tc1, texture_shift)],
                                                      [sum(x) for x in zip(tc2, texture_shift)],
                                                      [sum(x) for x in zip(tc4, texture_shift)]))

                    self.add(GlTri(v1, v3, v4, color, [sum(x) for x in zip(tc1, texture_shift)],
                                                      [sum(x) for x in zip(tc3, texture_shift)],
                                                      [sum(x) for x in zip(tc4, texture_shift)]))
                else:
                    self.add(GlTri(v1, v2, v4, color))
                    self.add(GlTri(v1, v3, v4, color))

class GlSphericalEllipse(GlVertices):
    def __init__(self,
                 width=20,  # degrees in spherical coordinates
                 height=10,  # degrees in spherical coordinates
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 sphere_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of sphere
                 n_steps=36):
        super().__init__()
        color = util.get_rgba(color)

        v_center = util.spherical_to_cartesian(sphere_radius, np.pi/2, np.pi/2)

        angles = np.linspace(0, 2*np.pi, n_steps+1)
        for wedge in range(n_steps):
            # render circle at the equator (phi=pi/2) so it's not near the poles
            # Also render it at theta = 90 degrees, for stimpack.visual_stim coordinates where heading (0,0,0) is +y axis
            v1 = util.spherical_to_cartesian(sphere_radius,
                                        np.pi/2 + radians(width/2)*np.cos(angles[wedge]),
                                        np.pi/2 + radians(height/2)*np.sin(angles[wedge]))
            v2 = util.spherical_to_cartesian(sphere_radius,
                                        np.pi/2 + radians(width/2)*np.cos(angles[wedge+1]),
                                        np.pi/2 + radians(height/2)*np.sin(angles[wedge+1]))

            self.add(GlTri(v1, v2, v_center, color).translate(sphere_location))

class GlCylindricalWithPhiEllipse(GlVertices):
    def __init__(self,
                 width=20,  # degrees in spherical coordinates
                 height=10,  # degrees in spherical coordinates
                 cylinder_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 cylinder_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of cylinder
                 n_steps=36):
        super().__init__()
        color = util.get_rgba(color)

        v_center = util.cylindrical_w_phi_to_cartesian(cylinder_radius, np.pi/2, np.pi/2)

        angles = np.linspace(0, 2*np.pi, n_steps+1)
        for wedge in range(n_steps):
            # render circle at the equator (phi=pi/2) so it's not near the poles
            # Also render it at theta = 90 degrees, for stimpack.visual_stim coordinates where heading (0,0,0) is +y axis
            v1 = util.cylindrical_w_phi_to_cartesian(cylinder_radius,
                                            np.pi/2 + radians(width/2)*np.cos(angles[wedge]),
                                            np.pi/2 + radians(height/2)*np.sin(angles[wedge]))
            v2 = util.cylindrical_w_phi_to_cartesian(cylinder_radius,
                                            np.pi/2 + radians(width/2)*np.cos(angles[wedge+1]),
                                            np.pi/2 + radians(height/2)*np.sin(angles[wedge+1]))

            self.add(GlTri(v1, v2, v_center, color).translate(cylinder_location))

class GlSphericalCirc(GlVertices):
    def __init__(self,
                 circle_radius=10,  # degrees in spherical coordinates
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 sphere_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of sphere
                 n_steps=36):
        super().__init__()
        color = util.get_rgba(color)

        v_center = util.spherical_to_cartesian(sphere_radius, np.pi/2, np.pi/2)

        angles = np.linspace(0, 2*np.pi, n_steps+1)
        for wedge in range(n_steps):
            # render circle at the equator (phi=pi/2) so it's not near the poles
            # Also render it at theta = 90 degrees, for stimpack.visual_stim coordinates where heading (0,0,0) is +y axis
            v1 = util.spherical_to_cartesian(sphere_radius,
                                        np.pi/2 + radians(circle_radius)*np.cos(angles[wedge]),
                                        np.pi/2 + radians(circle_radius)*np.sin(angles[wedge]))
            v2 = util.spherical_to_cartesian(sphere_radius,
                                        np.pi/2 + radians(circle_radius)*np.cos(angles[wedge+1]),
                                        np.pi/2 + radians(circle_radius)*np.sin(angles[wedge+1]))

            self.add(GlTri(v1, v2, v_center, color).translate(sphere_location))

class GlCylindricalPoints(GlVertices):
    def __init__(self,
                 cylinder_radius=1,  # meters
                 cylinder_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of cylinder (r = 0 and z = height/2)
                 color=[1, 1, 1, 1],
                 theta=[0],
                 phi=[0]):

        color = util.get_rgba(color)

        cartesian_coords = []
        for pt in range(len(theta)):
            cartesian_coords.append(util.cylindrical_w_phi_to_cartesian(cylinder_radius, radians(theta[pt]), radians(phi[pt])))

        vertices = np.vstack(cartesian_coords).T  # 3 x n_points
        colors = matlib.repmat(color, len(theta), 1).T  # 4 x n_points

        super().__init__(vertices=vertices, colors=colors)

class GlSphericalPoints(GlVertices):
    def __init__(self,
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],
                 theta=[0],
                 phi=[0]):

        color = util.get_rgba(color)

        cartesian_coords = []
        for pt in range(len(theta)):
            cartesian_coords.append(util.spherical_to_cartesian(sphere_radius, np.pi/2 + radians(theta[pt]), np.pi/2 + radians(phi[pt])))

        vertices = np.vstack(cartesian_coords).T  # 3 x n_points
        colors = matlib.repmat(color, len(theta), 1).T  # 4 x n_points

        super().__init__(vertices=vertices, colors=colors)

class GlPointCollection(GlVertices):
    def __init__(self,
                 locations=[[0, 0, 0]],
                 color=[1, 1, 1, 1]):
        color = util.get_rgba(color)

        vertices = np.vstack(locations)  # 3 x n_points
        colors = matlib.repmat(color, vertices.shape[1], 1).T  # 4 x n_points

        super().__init__(vertices=vertices, colors=colors)

class GlCylinder(GlVertices):
    def __init__(self,
                 cylinder_height=10,  # meters
                 cylinder_radius=1,  # meters
                 cylinder_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of cylinder (r = 0 and z = height/2)
                 cylinder_angular_extent=360,  # degrees
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 n_faces=32,
                 alpha_by_face=None,
                 texture=False,
                 texture_shift=(0, 0), # (u,v) coordinates to translate texture on shape. + is right, up.
                 n_texture_repeat_x=1, # number of times the texture is repeated along the x axis of the texture
                 n_texture_repeat_y=1):  

        super().__init__()
        color = util.get_rgba(color)

        if alpha_by_face is None:
            alpha_by_face = color[3]*np.ones(n_faces)

        d_theta = np.radians(cylinder_angular_extent) / n_faces
        theta_start = -np.radians(cylinder_angular_extent)/2
        for face in range(n_faces):
            v1 = util.cylindrical_to_cartesian(cylinder_radius, theta_start+face*d_theta, cylinder_height/2)
            v2 = util.cylindrical_to_cartesian(cylinder_radius, theta_start+face*d_theta, -cylinder_height/2)
            v3 = util.cylindrical_to_cartesian(cylinder_radius, theta_start+(face+1)*d_theta, -cylinder_height/2)
            v4 = util.cylindrical_to_cartesian(cylinder_radius, theta_start+(face+1)*d_theta, cylinder_height/2)

            new_color = [color[0], color[1], color[2], alpha_by_face[face]]

            if texture:
                self.add(GlQuad(v1, v2, v3, v4, new_color,
                                tc1=(face/n_faces*n_texture_repeat_x, n_texture_repeat_y),
                                tc2=(face/n_faces*n_texture_repeat_x, 0),
                                tc3=((face+1)/n_faces*n_texture_repeat_x, 0),
                                tc4=((face+1)/n_faces*n_texture_repeat_x, n_texture_repeat_y),
                                texture_shift=texture_shift,
                                use_texture=True).translate(cylinder_location))
            else:
                self.add(GlQuad(v1, v2, v3, v4, color).translate(cylinder_location))

class GlCylindricalWithPhiRect(GlVertices):
    def __init__(self,
                 width=20,  # degrees, theta
                 height=20,  # degrees, phi
                 cylinder_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 n_steps_x=6,
                 n_steps_y=6):
        super().__init__()
        color = util.get_rgba(color)

        d_theta = (1/n_steps_x) * radians(width)
        d_phi = (1/n_steps_y) * radians(height)
        for rr in range(n_steps_y):
            for cc in range(n_steps_x):
                # render patch at the equator (phi=pi/2) so it's not near the poles
                # Also render it at theta = 90 degrees, for stimpack.visual_stim coordinates where heading (0,0,0) is +y axis
                theta = np.pi/2 + radians(width) * (-1/2 + (cc/n_steps_x))
                phi = np.pi/2 + radians(height) * (-1/2 + (rr/n_steps_y))
                v1 = util.cylindrical_w_phi_to_cartesian(cylinder_radius, theta, phi)
                v2 = util.cylindrical_w_phi_to_cartesian(cylinder_radius, theta, phi + d_phi)
                v3 = util.cylindrical_w_phi_to_cartesian(cylinder_radius, theta + d_theta, phi)
                v4 = util.cylindrical_w_phi_to_cartesian(cylinder_radius, theta + d_theta, phi + d_phi)
                self.add(GlTri(v1, v2, v4, color))
                self.add(GlTri(v1, v3, v4, color))
