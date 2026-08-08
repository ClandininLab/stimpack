"""
Geometry primitives: triangle meshes with per-vertex colours and texture coordinates.

Every stimulus builds one of these in :meth:`~stimpack.visual_stim.base.BaseProgram.eval_at` and
hands its vertex, colour and texture-coordinate arrays to the GPU. Shapes compose -- ``add()``
merges one into another -- and transform in place, so a stimulus assembles what it needs and then
positions the whole thing::

    patch = GlSphericalRect(width=10, height=30, color=[1, 1, 1, 1])
    patch = patch.rotate(np.radians(theta), np.radians(phi), np.radians(angle))

Coordinates are stimpack's: metres, with the subject at the origin and heading ``(0, 0, 0)``
looking along **+y**. Shapes named ``Spherical`` or ``Cylindrical`` take their extents in
**degrees** subtended at the subject, and lie on a sphere or cylinder of the given radius, which
is what keeps a patch the same angular size wherever it is placed.
"""
import numpy as np
from math import radians
from . import util

# Edge kinds the fragment shader can evaluate. A shape declaring one hands the shader an equation
# for its true boundary; the triangles then only have to *cover* that boundary, and the shader
# clips them back to it. NONE is every shape that has not opted in: the geometry defines the edge,
# exactly as it always has.
EDGE_NONE = 0
EDGE_CONE = 1                # inside the cone of a flat ellipse of half-extents `extent`
EDGE_ANGULAR_RECT = 2        # |azimuth| <= extent.x and |elevation| <= extent.y, in the shape's frame

# Both are statements about *direction*, so neither mentions the surface the triangles sit on. A
# patch on a cylinder covers exactly the directions its spherical twin does -- only the distance
# along each ray differs -- so the same two kinds serve both, and the shader needs nothing new.


#: How far past its true bound a spherical rectangle draws, as a fraction. Only has to swallow
#: rounding: the geometry is a cover, and every surplus fragment is given zero coverage by the
#: shader. The cone shapes need no margin at all -- see :func:`cone_bound_directions` for why.
EDGE_BOUND_MARGIN = 0.01

#: Rows are the axes a sphere patch is built against at theta = phi = pi/2: the azimuth tangent,
#: the elevation tangent, and the outward direction. Every shape here is constructed in this frame
#: and rotated into place by its caller, so the frame turns with the shape.
CANONICAL_PATCH_FRAME = ((-1.0, 0.0, 0.0),     # +azimuth  (d/dtheta)
                         (0.0, 0.0, -1.0),     # +elevation (d/dphi)
                         (0.0, 1.0, 0.0))      # forward


def cone_bound_directions(extent_x, extent_y, n_steps, frame=CANONICAL_PATCH_FRAME):
    """Directions of a polygon whose edges are tangent to the cone of the given half-extents.

    Gnomonic projection -- divide a direction by its forward component, giving the coordinates of
    the flat card the cone is projected from -- takes great circles to straight lines. The edge the
    GPU rasterises between two vertices on a sphere sweeps a great circle, so it *is* a straight
    line in these coordinates. That makes the bound exact rather than approximate: a polygon
    circumscribing the ellipse on the card circumscribes the real shape, at any size, with no
    margin needed and nothing to tune.

    A regular n-gon with its vertices at radius 1/cos(pi/n) has its edges tangent to the unit
    circle, and scaling that by (tan extent_x, tan extent_y) is an affine map, which preserves both
    the tangency and the containment.

    :param extent_x: half-extent across, radians; must be under 90 degrees, since a cone cannot
        describe more than a hemisphere
    :param extent_y: half-extent up, radians
    :param n_steps: sides of the polygon. Sets surplus area only, never accuracy.
    """
    reach = 1.0 / np.cos(np.pi / n_steps)
    bearings = np.linspace(0, 2*np.pi, n_steps, endpoint=False)
    x = np.tan(extent_x) * reach * np.cos(bearings)
    y = np.tan(extent_y) * reach * np.sin(bearings)
    frame = np.asarray(frame, dtype=float)
    directions = x[:, None]*frame[0] + y[:, None]*frame[1] + frame[2]
    return directions / np.linalg.norm(directions, axis=1, keepdims=True)


def _add_cone_patch(shape, extent_x, extent_y, surface_radius, color, location, n_steps,
                    to_cartesian=util.spherical_to_cartesian):
    """Fill `shape` with a bounding fan for a cone patch, and declare its analytic edge.

    Shared by every disc and ellipse here, on either surface. A disc *is* the equal-extent case of
    an ellipse -- the same cone with different numbers -- and a cylindrical patch is the same cone
    again, its vertices merely pushed further along the same rays. One builder, one shader branch.

    :param to_cartesian: where a (radius, theta, phi) lands -- the sphere or the cylinder wall.
        Both put a given (theta, phi) in the same *direction*, which is the only thing the edge
        declaration is about.
    """
    v_center = to_cartesian(surface_radius, np.pi/2, np.pi/2)

    if not (0 < max(extent_x, extent_y) < np.pi/2):
        # A cone cannot describe more than a hemisphere, so past that there is no analytic form to
        # declare. Fall back to the inscribed fan this drew before, and to a geometry-defined edge
        # -- the path every unconverted shape takes.
        shape.EDGE_KIND = EDGE_NONE
        bearings = np.linspace(0, 2*np.pi, n_steps+1)
        for wedge in range(n_steps):
            v1 = to_cartesian(surface_radius, np.pi/2 + extent_x*np.cos(bearings[wedge]),
                              np.pi/2 + extent_y*np.sin(bearings[wedge]))
            v2 = to_cartesian(surface_radius, np.pi/2 + extent_x*np.cos(bearings[wedge+1]),
                              np.pi/2 + extent_y*np.sin(bearings[wedge+1]))
            shape.add(GlTri(v1, v2, v_center, color).translate(location))
        return

    # The bound is a set of directions; put each one on whichever surface this shape lives on.
    # Which surface cannot affect whether it covers: a straight segment seen from the subject
    # sweeps a great-circle arc whatever distance its endpoints are at, so the directions a
    # triangle spans depend only on the directions of its corners.
    _, theta, phi = util.cartesian_to_spherical(*cone_bound_directions(extent_x, extent_y, n_steps).T)
    corners = np.array(to_cartesian(surface_radius, theta, phi)).T
    for wedge in range(n_steps):
        shape.add(GlTri(corners[wedge], corners[(wedge + 1) % n_steps], v_center,
                        color).translate(location))

    # What the shader needs to rebuild the cone: the frame the patch was built in, and how far out
    # on the flat card its ellipse reaches in each axis.
    shape.edge_frame = CANONICAL_PATCH_FRAME
    shape.edge_extent = (float(extent_x), float(extent_y))


def _add_angular_rect_patch(shape, width, height, surface_radius, color, n_steps_x, n_steps_y,
                            to_cartesian=util.spherical_to_cartesian):
    """Fill `shape` with a bounding grid for a rectangular patch, and declare its analytic edge.

    Shared by the spherical and cylindrical rectangles, for the same reason the cone builder is:
    the declaration is about direction, and both surfaces put a given (theta, phi) in the same one.

    :param width: degrees of azimuth subtended
    :param height: degrees of elevation subtended
    """
    # The grid is a bound, and the shader clips it to the true rectangle. Its sides already cover:
    # a constant-azimuth boundary is a great circle, which a triangle edge reproduces exactly, and
    # a constant-elevation one is a small circle, which the great-circle arc between two of its
    # points bulges outside. Only the four corners land exactly on the bound, so widen by a whisker
    # to keep rounding from nicking them.
    drawn_width = radians(width) * (1.0 + EDGE_BOUND_MARGIN)
    drawn_height = radians(height) * (1.0 + EDGE_BOUND_MARGIN)

    d_theta = (1/n_steps_x) * drawn_width
    d_phi = (1/n_steps_y) * drawn_height
    for rr in range(n_steps_y):
        for cc in range(n_steps_x):
            # render the patch at the equator (phi=pi/2) so it is not near the poles, and at
            # theta = 90 degrees, where stimpack's heading (0,0,0) looks
            theta = np.pi/2 + drawn_width * (-1/2 + (cc/n_steps_x))
            phi = np.pi/2 + drawn_height * (-1/2 + (rr/n_steps_y))
            v1 = to_cartesian(surface_radius, theta, phi)
            v2 = to_cartesian(surface_radius, theta, phi + d_phi)
            v3 = to_cartesian(surface_radius, theta + d_theta, phi)
            v4 = to_cartesian(surface_radius, theta + d_theta, phi + d_phi)
            shape.add(GlTri(v1, v2, v4, color))
            shape.add(GlTri(v1, v3, v4, color))

    shape.edge_frame = CANONICAL_PATCH_FRAME
    shape.edge_extent = (float(radians(width) / 2), float(radians(height) / 2))


def _carry_edge(source, result, rotation=None):
    """Move a declared analytic edge onto a transformed copy.

    Call this from a transform that leaves the shape *being that shape*: rotations, and the
    appearance-only ones. Rotations preserve angles, so a patch of a given angular size is still
    one of that size afterwards -- the whole frame turns with it. Translation and scaling are not,
    since they move the shape off the sphere its angular size was measured on or stretch it out of
    being that shape at all, so those simply do not call this and the result falls back to a
    geometry-defined edge -- the path every unconverted shape already takes.

    :param rotation: a callable turning a (3, N) array of directions, or None if the transform
        does not move the shape at all
    """
    if source.edge_kind == EDGE_NONE:
        return result
    result.EDGE_KIND = source.EDGE_KIND
    frame = np.asarray(source.edge_frame)
    if rotation is not None:
        frame = np.asarray(rotation(frame.T)).T
    result.edge_frame = tuple(tuple(axis) for axis in frame)
    result.edge_extent = source.edge_extent
    return result


def edge_coverage(distance, pixel):
    """What fraction of a pixel a shape covers, given how far its edge is from the pixel centre.

    The reference implementation of what the fragment shader computes, kept in Python so the rule
    can be stated and tested without a GL context.

    Linear, not ``smoothstep``. The graphics convention is the latter, whose S-curve makes edges
    look soft rather than creased, and it is wrong here twice over. A pixel 30% covered should emit
    30% of the light and smoothstep emits 22%, worst case 9.6 percentage points of luminance. Worse,
    it makes emitted intensity a non-linear function of edge position, so a constant-velocity edge
    appears to stall and then hurry once per pixel crossed -- which is a smaller copy of the motion
    artefact analytic coverage exists to remove. This form is the true covered fraction for a
    straight edge, which is what a photoreceptor integrating over that pixel receives.

    :param distance: how far the edge is beyond the pixel, in the same units as `pixel`;
        negative is inside the shape
    :param pixel: the size of one pixel in those units
    """
    if pixel <= 0:
        return float(distance <= 0)
    return float(np.clip(0.5 - distance / pixel, 0.0, 1.0))


class GlVertices:
    """
    A triangle mesh: vertices, per-vertex RGBA colours, and texture coordinates.

    The base of every shape below, and usable directly for arbitrary geometry. Transform methods
    (:meth:`rotate`, :meth:`translate`, :meth:`scale`) return the object, so they chain.

    :param vertices: 3 x n array of vertex positions, in metres
    :param colors: 4 x n array of RGBA values, one per vertex
    :param tex_coords: 2 x n array of texture coordinates, for textured shapes
    """
    EDGE_KIND = EDGE_NONE
    edge_frame = CANONICAL_PATCH_FRAME
    edge_extent = (0.0, 0.0)

    @property
    def edge_kind(self):
        """Which edge equation the fragment shader should evaluate for this shape, if any."""
        return self.EDGE_KIND

    def __init__(self, vertices=None, colors=None, tex_coords=None):
        self.vertices = vertices
        self.colors = colors
        self.tex_coords = tex_coords

    def add(self, obj):
        """Merge another shape into this one, concatenating its vertices, colours and texture coordinates."""
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
        return _carry_edge(self, GlVertices(vertices=util.rotate(self.vertices, z, x, y), colors=self.colors,
                                            tex_coords=self.tex_coords),
                          rotation=lambda v: util.rotate(v, z, x, y))

    def rotx(self, th):
        """Rotate about the x axis by ``th`` radians. Returns self, so calls chain."""
        return _carry_edge(self, GlVertices(vertices=util.rotx(self.vertices, th), colors=self.colors,
                                            tex_coords=self.tex_coords),
                          rotation=lambda v: util.rotx(v, th))

    def roty(self, th):
        """Rotate about the y axis by ``th`` radians. Returns self, so calls chain."""
        return _carry_edge(self, GlVertices(vertices=util.roty(self.vertices, th), colors=self.colors,
                                            tex_coords=self.tex_coords),
                          rotation=lambda v: util.roty(v, th))

    def rotz(self, th):
        """Rotate about the z axis by ``th`` radians. Returns self, so calls chain."""
        return _carry_edge(self, GlVertices(vertices=util.rotz(self.vertices, th), colors=self.colors,
                                            tex_coords=self.tex_coords),
                          rotation=lambda v: util.rotz(v, th))

    def scale(self, amt):
        """Scale about the origin. Returns self, so calls chain."""
        return GlVertices(vertices=util.scale(self.vertices, amt), colors=self.colors, tex_coords=self.tex_coords)

    def translate(self, amt):
        """Translate by an (x, y, z) offset in metres. Returns self, so calls chain."""
        return GlVertices(vertices=util.translate(self.vertices, amt), colors=self.colors, tex_coords=self.tex_coords)

    def set_color(self, color):
        """Set every vertex to one colour."""
        new_colors = np.tile(np.array(color), (self.vertices.shape[1], 1)).T
        return _carry_edge(self, GlVertices(vertices=self.vertices, colors=new_colors,
                                            tex_coords=self.tex_coords))

    def shift_texture(self, shift):
        """Offset texture coordinates by (u, v) -- how a texture is scrolled across a shape."""
        new_tex_coords = self.tex_coords + np.tile(shift, (self.tex_coords.shape[1], 1)).T
        return _carry_edge(self, GlVertices(vertices=self.vertices, colors=self.colors,
                                            tex_coords=new_tex_coords))

    @property
    def data(self):
        if self.tex_coords is not None:
            data = np.concatenate((self.vertices, self.colors, self.tex_coords), axis=0)
        else:
            data = np.concatenate((self.vertices, self.colors), axis=0)
        return data.flatten(order='F')


class GlTri(GlVertices):
    """
    A single triangle from three vertices, optionally textured.

    The unit every other shape is built from.
    """
    def __init__(self, v1, v2, v3, color, tc1=None, tc2=None, tc3=None, texture=None):
        vertices = np.concatenate((v1, v2, v3)).reshape((3, 3), order='F')
        colors = np.concatenate((color, color, color)).reshape((4, 3), order='F')

        if tc1 is not None:
            tex_coords = np.concatenate((tc1, tc2, tc3)).reshape((2, 3), order='F')
        else:
            tex_coords = None
        super().__init__(vertices=vertices, colors=colors, tex_coords=tex_coords)


class GlQuad(GlVertices):
    """
    A planar quadrilateral from four vertices, drawn as two triangles.

    Vertices are taken in order around the perimeter. Texture coordinates default to the corners
    of the texture, so ``use_texture=True`` maps one full copy across the quad.
    """
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
    """
    A flat disc parallel to the xz plane, built as a fan of ``n_steps`` wedges.

    Flat rather than spherical: its apparent size changes with the subject's distance from it.
    For a patch that subtends a fixed angle, use :class:`GlSphericalCirc`.
    """
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
    """
    An axis-aligned cube, one colour per face.

    :param colors: dict of face name to colour, or None for a default set of six distinct
        colours -- useful as a visible reference object when checking perspective.
    """
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
    """
    An axis-aligned rectangular box, one colour per face.

    :class:`GlCube` with independent side lengths in x, y and z.
    """
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
    """
    A patch on the surface of a sphere, rectangular in spherical coordinates.

    Width and height are angles subtended at the centre of the sphere, so the patch keeps its
    angular size however the sphere is scaled. Built at the equator and at theta = 90 degrees --
    facing the subject's default heading -- then rotated into place by the caller, which avoids
    the distortion a patch would pick up near the poles.

    :param width: degrees of azimuth (theta)
    :param height: degrees of elevation (phi)
    :param sphere_radius: metres
    :param n_steps_x: subdivisions across the width; more make the patch follow the sphere's
        curvature more closely, at the cost of vertices
    :param n_steps_y: subdivisions down the height
    """
    EDGE_KIND = EDGE_ANGULAR_RECT

    def __init__(self,
                 width=20,  # degrees, theta
                 height=20,  # degrees, phi
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 n_steps_x=6,
                 n_steps_y=6):
        super().__init__()
        _add_angular_rect_patch(self, width, height, sphere_radius, util.get_rgba(color),
                                n_steps_x, n_steps_y)

class GlSphericalTexturedRect(GlVertices):
    """
    :class:`GlSphericalRect` carrying texture coordinates, for image and grating stimuli.
    """
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
    """
    An elliptical patch, of fixed angular width and height, on the surface of a sphere.

    Defined as the sphere cut by the cone of a flat ellipse: the shape an elliptical hole held in
    front of the subject would leave unblocked, and the shape an ellipse drawn on a flat screen
    subtends. As with :class:`GlSphericalCirc`, the triangles are a *bound* and the fragment shader
    clips them to the true boundary, so the edge is exact at any size and carries sub-pixel
    coverage.

    This is the same cone as the disc, with the two half-extents allowed to differ -- so
    ``GlSphericalEllipse(w, w)`` is exactly ``GlSphericalCirc(w/2)``, which was not true of the
    ellipse this replaces. That one was built on the azimuth/elevation grid, which is not uniform,
    and so came out pinched at the diagonals: 0.35 degrees, four pixels, on a 60 degree shape.

    :param width: degrees of azimuth subtended at the subject
    :param height: degrees of elevation subtended at the subject
    :param n_steps: sides of the bounding polygon. Not the accuracy of the ellipse.
    """
    EDGE_KIND = EDGE_CONE

    def __init__(self,
                 width=20,  # degrees in spherical coordinates
                 height=10,  # degrees in spherical coordinates
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 sphere_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of sphere
                 n_steps=8):
        super().__init__()
        _add_cone_patch(self, radians(width/2), radians(height/2), sphere_radius,
                        util.get_rgba(color), sphere_location, n_steps)

class GlCylindricalWithPhiEllipse(GlVertices):
    """
    :class:`GlSphericalEllipse` laid on a cylinder rather than a sphere.

    Azimuth follows the cylinder wall; elevation is still an angle subtended at the subject, so
    the shape suits rigs whose screens wrap horizontally but not vertically.

    It carries the same analytic edge as its spherical twin, and for a reason worth stating: the
    two occupy *identical directions*, and differ only in how far along each ray the vertices sit.
    An edge declaration is a statement about direction, so the surface never enters into it.

    :param n_steps: sides of the bounding polygon. Not the accuracy of the ellipse.
    """
    EDGE_KIND = EDGE_CONE

    def __init__(self,
                 width=20,  # degrees in spherical coordinates
                 height=10,  # degrees in spherical coordinates
                 cylinder_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 cylinder_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of cylinder
                 n_steps=8):
        super().__init__()
        _add_cone_patch(self, radians(width/2), radians(height/2), cylinder_radius,
                        util.get_rgba(color), cylinder_location, n_steps,
                        to_cartesian=util.cylindrical_w_phi_to_cartesian)

class GlSphericalCirc(GlVertices):
    """
    A circular patch on the surface of a sphere, of fixed angular radius.

    The triangles are a *bound*, not the shape. They are pushed out until their edges are tangent
    to the true circle, and the fragment shader clips them back to it -- so the disc is exact at
    any radius, and its edge carries sub-pixel coverage rather than snapping to whole pixels.

    That inverts what `n_steps` is for. It used to set accuracy: vertices sat on the circle, so the
    chords between them cut 1 - cos(pi/n) inside it -- 0.38% of the radius at 36 steps, which is
    0.076 degrees on a 20 degree disc and nearly twice a pixel on a flat rig. Now it only sets how
    much surplus area is drawn and then found to be outside, so 8 is enough and cheaper than 36.

    :param circle_radius: degrees subtended at the subject
    :param n_steps: sides of the bounding polygon. Not the accuracy of the disc.
    """
    EDGE_KIND = EDGE_CONE

    def __init__(self,
                 circle_radius=10,  # degrees in spherical coordinates
                 sphere_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 sphere_location=(0, 0, 0),  # (x,y,z) meters. (0,0,0) is center of sphere
                 n_steps=8):
        super().__init__()
        _add_cone_patch(self, radians(circle_radius), radians(circle_radius), sphere_radius,
                        util.get_rgba(color), sphere_location, n_steps)


class GlSphericalAnnuli(GlVertices):
    """
    Concentric annuli of equal angular width about the forward axis, in alternating colours.

    A commissioning pattern rather than an experimental stimulus. Every band subtends the same
    angle at the subject, so on a screen that is a sphere centred on the subject every band is the
    same *physical* width on the surface -- which makes a ruler or a photograph a direct test of
    the renderer's geometry, needing no model of the rig to interpret. In the projector image the
    same bands are emphatically not equal: they compress towards the rim, and that compression is
    the warp doing its job.

    Built exactly, from the angle-from-axis definition, rather than by offsetting theta and phi
    around the canonical patch centre the way :class:`GlSphericalCirc` does. That parameterisation
    is a tangent-plane approximation, exact only to first order in the offset -- fine for a patch a
    few degrees across, and wrong by a degree or so at the 45 degrees these rings are meant to
    reach, which is exactly the error this pattern exists to detect.

    No analytic edge: the shader carries one edge equation per draw, and this is many rings. The
    boundaries are therefore polygonal, and ``n_azimuth`` says how finely. The radial error is
    ``1 - cos(pi / n_azimuth)`` of the ring radius -- at the default 128 that is 0.03% of it, about
    0.01 degrees at 45, well under a projector pixel on any rig this is useful for.

    :param band_width: angular width of each band, in degrees
    :param max_radius: how far out to draw, in degrees from the axis. Rounded up to a whole band,
        so the outermost band is never a partial one masquerading as a full one.
    :param sphere_radius: metres. Only has to put the pattern outside anything else in the scene.
    :param colors: the two colours to alternate, innermost first. ``[r,g,b,a]`` or mono.
    :param n_azimuth: steps around the axis. See above for what it costs.
    """

    def __init__(self,
                 band_width=5.0,
                 max_radius=45.0,
                 sphere_radius=1.0,
                 colors=(1.0, 0.0),
                 n_azimuth=128):
        super().__init__()

        if band_width <= 0:
            raise ValueError(f'band_width must be positive, got {band_width}')
        if max_radius <= 0:
            raise ValueError(f'max_radius must be positive, got {max_radius}')
        if n_azimuth < 3:
            raise ValueError(f'n_azimuth must be at least 3, got {n_azimuth}')

        # Whole bands only. A truncated outer band reads as a band of its own, and someone checking
        # that the widths are equal would find one that is not and go looking for a bug in the warp.
        n_bands = int(np.ceil(max_radius / band_width))
        edges = np.radians(np.arange(n_bands + 1) * band_width)

        inner, outer = edges[:-1, None], edges[1:, None]            # (B, 1)
        azimuth = np.linspace(0, 2 * np.pi, n_azimuth + 1)
        left, right = azimuth[None, :-1], azimuth[None, 1:]         # (1, A)

        def direction(angle, around):
            """Unit vectors `angle` from +y, at `around` about it. Exact at any angle."""
            angle, around = np.broadcast_arrays(angle, around)
            return np.stack([np.sin(angle) * np.cos(around),
                             np.cos(angle) * np.ones_like(around),
                             np.sin(angle) * np.sin(around)])       # (3, B, A)

        # Each cell of the (band, azimuth) grid becomes two triangles. The innermost band's inner
        # edge is a point, so its first triangle is degenerate and draws nothing -- cheaper than
        # special-casing a fan, and it keeps one array shape for the whole pattern.
        corners = (direction(inner, left), direction(inner, right),
                   direction(outer, right), direction(outer, left))
        a, b, c, d = corners
        triangles = np.stack([a, b, c, a, c, d], axis=-1)           # (3, B, A, 6)

        band_colors = np.stack([util.get_rgba(colors[index % len(colors)])
                                for index in range(n_bands)], axis=1)   # (4, B)

        self.vertices = (sphere_radius * triangles).reshape(3, -1)
        self.colors = np.broadcast_to(band_colors[:, :, None, None],
                                      (4, n_bands, n_azimuth, 6)).reshape(4, -1)


class GlCylindricalPoints(GlVertices):
    """
    Points placed on a cylinder wall at given azimuths and elevations.

    Drawn as GL points rather than triangles -- see ``draw_mode`` on the stimulus.
    """
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
        colors = np.tile(color, (len(theta), 1)).T  # 4 x n_points

        super().__init__(vertices=vertices, colors=colors)

class GlSphericalPoints(GlVertices):
    """
    Points placed on a sphere at given azimuths (``theta``) and elevations (``phi``), in degrees.
    """
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
        colors = np.tile(color, (len(theta), 1)).T  # 4 x n_points

        super().__init__(vertices=vertices, colors=colors)

class GlPointCollection(GlVertices):
    """
    Points at arbitrary Cartesian positions, all one colour.

    :param locations: sequence of (x, y, z) positions in metres
    """
    def __init__(self,
                 locations=[[0, 0, 0]],
                 color=[1, 1, 1, 1]):
        color = util.get_rgba(color)

        vertices = np.vstack(locations)  # 3 x n_points
        colors = np.tile(color, (vertices.shape[1], 1)).T  # 4 x n_points

        super().__init__(vertices=vertices, colors=colors)

class GlCylinder(GlVertices):
    """
    A cylinder wall around the subject -- the surface most panoramic stimuli are painted on.

    :param cylinder_height: metres
    :param cylinder_radius: metres
    :param cylinder_angular_extent: degrees of azimuth covered; 360 closes the cylinder, less
        leaves an arc
    :param n_faces: flat faces approximating the wall
    :param alpha_by_face: per-face alpha, for fading a cylinder out towards its edges
    :param texture: whether to generate texture coordinates
    :param n_texture_repeat_x: how many times the texture tiles around the cylinder
    :param n_texture_repeat_y: how many times it tiles vertically
    """
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
    """
    A rectangular patch on a cylinder wall, sized in degrees of azimuth and elevation.

    The cylindrical counterpart of :class:`GlSphericalRect`, and analytic on the same terms: the
    two cover identical directions, so the same declaration describes both.
    """
    EDGE_KIND = EDGE_ANGULAR_RECT

    def __init__(self,
                 width=20,  # degrees, theta
                 height=20,  # degrees, phi
                 cylinder_radius=1,  # meters
                 color=[1, 1, 1, 1],  # [r,g,b,a] or single value for monochrome, alpha = 1
                 n_steps_x=6,
                 n_steps_y=6):
        super().__init__()
        _add_angular_rect_patch(self, width, height, cylinder_radius, util.get_rgba(color),
                                n_steps_x, n_steps_y,
                                to_cartesian=util.cylindrical_w_phi_to_cartesian)
