"""Geometry for projecting onto a smoothly curved screen.

A `SubScreen` is a flat quad rendered through a Kooima off-axis frustum, which is exact for a planar
screen and only a planar screen. A curved screen -- a hemisphere, a cylinder -- has to be handled
some other way.

The approach here is the one flystim1.0 used, and it is worth stating plainly because it is not the
same as adding more subscreens. The screen is described as a *mesh*, where every vertex carries two
things:

    ndc        where that point of the screen lands on the projector, in [-1, +1]
    direction  which way that point lies, as seen by the subject

Rendering then draws that one mesh, and each fragment knows the direction it represents. What
supplies the colour for a direction is a separate question -- flystim1.0 evaluated a closed-form
function, which is why it could not render 3D scenes; stimpack will sample a cube map, which can.
This module is only concerned with building the mesh, and does not depend on how it is drawn.

The distinction that matters for accuracy: with subscreens, facet size sets *rendering* error,
because each facet gets its own planar frustum. Here it only sets how well the mesh approximates the
surface's shape, because direction is interpolated across each triangle and sampled per fragment. So
a modest tessellation goes a long way -- flystim1.0 used 10x10 over a whole hemisphere.
"""
import numpy as np

from stimpack.visual_stim.util import normalize


class PinholeProjector:
    """A projector modelled as a pinhole, mapping points in the rig to projector NDC.

    This answers the question the renderer cannot proceed without: for a point on the screen, which
    part of the projector image illuminates it? The GPU draws into the projector's framebuffer, so
    every vertex of the screen mesh needs its position there.

    "Pinhole" because a projector is optically a camera run backwards -- rays through a point onto a
    rectangle, emitted rather than collected -- so the same algebra applies. Throw ratio is the
    manufacturer's way of quoting focal length: in NDC units the focal length is 2 * throw_ratio,
    which is where the factor of 2 below comes from.

    Generalizes the model in flystim1.0's examples/hemisphere.py, which assumed a projector on the
    +z axis pointing back at the origin. Here the pose is explicit, so an off-axis or tilted mount
    can be described without rederiving the algebra.

    This class is the only description of the optics anywhere. build_screen_mesh calls to_ndc() and
    nothing else, so a rig whose optics are not a pinhole -- a fisheye lens, a fold mirror, or a
    mapping measured with structured light -- can substitute a different class here without
    disturbing anything downstream.

    The defaults are a placeholder chosen to cover the default SphericalSurface. They describe no
    real rig: supply the measured pose and the projector's actual throw ratio before pointing this
    at hardware, and check the result with draw_curved_screen().

    :param position: projector pinhole, in meters, in the same frame as the screen
    :param forward: direction the projector points
    :param up: which way is up in the projected image
    :param throw_ratio: throw distance / image width, as quoted by the manufacturer
    :param aspect_ratio: image width / height
    """

    def __init__(self, position=(0, 0, 0.30), forward=(0, 0, -1), up=(0, 1, 0),
                 throw_ratio=0.5, aspect_ratio=1.6):
        self.position = tuple(float(v) for v in position)
        self.forward = tuple(float(v) for v in forward)
        self.up = tuple(float(v) for v in up)
        self.throw_ratio = float(throw_ratio)
        self.aspect_ratio = float(aspect_ratio)

    def _basis(self):
        forward = normalize(np.asarray(self.forward, dtype=float))
        up_hint = np.asarray(self.up, dtype=float)
        right = np.cross(forward, up_hint)
        if np.linalg.norm(right) < 1e-9:
            raise ValueError('projector `up` is parallel to `forward`; they must differ')
        right = normalize(right)
        up = normalize(np.cross(right, forward))
        return right, up, forward

    def to_ndc(self, points):
        """Project points (N, 3) in meters to projector NDC (N, 2).

        Points behind the projector have no image; they come back as NaN rather than silently
        folding onto the wrong side, which is what dividing by a negative depth would do.
        """
        points = np.atleast_2d(np.asarray(points, dtype=float))
        right, up, forward = self._basis()

        relative = points - np.asarray(self.position, dtype=float)
        depth = relative @ forward

        with np.errstate(divide='ignore', invalid='ignore'):
            ndc_x = 2 * self.throw_ratio * (relative @ right) / depth
            ndc_y = 2 * self.throw_ratio * self.aspect_ratio * (relative @ up) / depth

        ndc = np.stack([ndc_x, ndc_y], axis=-1)
        ndc[depth <= 0] = np.nan
        return ndc

    def serialize(self):
        return {'position': self.position, 'forward': self.forward, 'up': self.up,
                'throw_ratio': self.throw_ratio, 'aspect_ratio': self.aspect_ratio}

    @classmethod
    def deserialize(cls, data):
        return cls(**data)

    @classmethod
    def wintech_pro4500(cls, position, forward=(0, 0, -1), up=(0, 1, 0), lens='long'):
        """The WinTech PRO4500 optical engine (TI DLP4500, 0.45" WXGA 912x1140 diamond DMD).

        Aspect and throw are read off the manufacturer's working-distance table:

            92 mm  ->  65.6 x 41 mm     aspect 1.600, throw 1.402
            700 mm ->  400  x 250 mm    aspect 1.600, throw 1.750

        Two things follow. The aspect ratio is 1.6 (16:10), not the 16/9 flystim1.0 assumed -- so
        that example was slightly off in the axis its own coverage was worst in. And 1.75 is not an
        arbitrary number: it is this engine's long lens, which is presumably where flystim1.0 got it.
        The lenses are field-swappable, so check which one is fitted.

        The engine's other published figures are what make the pinhole model appropriate here:
        "all glass 0% offset optics" means the optical axis runs through the image centre, so no
        offset term is needed, and distortion is quoted at <1% (0.1-0.5% over much of the range),
        which is below what this screen geometry needs to resolve.

        :param position: the pinhole, in meters, in the rig frame -- must be measured
        :param lens: 'long' (throw 1.75) or 'short' (throw 1.40)
        """
        throw = {'long': 1.750, 'short': 1.402}
        if lens not in throw:
            raise ValueError(f"lens must be one of {sorted(throw)}, not {lens!r}")
        return cls(position=position, forward=forward, up=up,
                   throw_ratio=throw[lens], aspect_ratio=1.6)


class CurvedSurface:
    """A screen surface, tessellated into a triangle mesh of points in the rig, in meters."""

    def vertices_and_triangles(self):
        """Return (vertices (N, 3) in meters, triangles (M, 3) of indices into vertices)."""
        raise NotImplementedError

    def serialize(self):
        raise NotImplementedError


class SphericalSurface(CurvedSurface):
    """A sphere (or a cap of one) centred on the subject.

    Angles follow the rig convention used elsewhere in stimpack: azimuth is measured in the
    horizontal plane from +y (the direction the subject faces), and elevation from that plane
    towards +z.

    :param radius: meters
    :param azimuth_range: (min, max) degrees; the default is the full 360
    :param elevation_range: (min, max) degrees; the default is the upper hemisphere
    :param n_azimuth: tessellation steps around
    :param n_elevation: tessellation steps up
    """

    def __init__(self, radius=0.15, azimuth_range=(-180, 180), elevation_range=(0, 90),
                 n_azimuth=36, n_elevation=9):
        self.radius = float(radius)
        self.azimuth_range = tuple(float(v) for v in azimuth_range)
        self.elevation_range = tuple(float(v) for v in elevation_range)
        self.n_azimuth = int(n_azimuth)
        self.n_elevation = int(n_elevation)

    def vertices_and_triangles(self):
        azimuth = np.radians(np.linspace(*self.azimuth_range, self.n_azimuth + 1))
        elevation = np.radians(np.linspace(*self.elevation_range, self.n_elevation + 1))
        az, el = np.meshgrid(azimuth, elevation, indexing='ij')

        horizontal = self.radius * np.cos(el)
        vertices = np.stack([horizontal * np.sin(az),      # x, right of the subject
                             horizontal * np.cos(az),      # y, in front of the subject
                             self.radius * np.sin(el)],    # z, above the subject
                            axis=-1).reshape(-1, 3)
        return vertices, _grid_triangles(self.n_azimuth + 1, self.n_elevation + 1)

    def serialize(self):
        return {'kind': 'spherical', 'radius': self.radius, 'azimuth_range': self.azimuth_range,
                'elevation_range': self.elevation_range, 'n_azimuth': self.n_azimuth,
                'n_elevation': self.n_elevation}


class CylindricalSurface(CurvedSurface):
    """A cylinder (or a sector of one) about the vertical axis through the subject.

    :param radius: meters
    :param height_range: (bottom, top) in meters, relative to the subject
    :param azimuth_range: (min, max) degrees
    """

    def __init__(self, radius=0.15, height_range=(-0.05, 0.05), azimuth_range=(-180, 180),
                 n_azimuth=36, n_height=4):
        self.radius = float(radius)
        self.height_range = tuple(float(v) for v in height_range)
        self.azimuth_range = tuple(float(v) for v in azimuth_range)
        self.n_azimuth = int(n_azimuth)
        self.n_height = int(n_height)

    def vertices_and_triangles(self):
        azimuth = np.radians(np.linspace(*self.azimuth_range, self.n_azimuth + 1))
        height = np.linspace(*self.height_range, self.n_height + 1)
        az, z = np.meshgrid(azimuth, height, indexing='ij')

        vertices = np.stack([self.radius * np.sin(az),
                             self.radius * np.cos(az),
                             z], axis=-1).reshape(-1, 3)
        return vertices, _grid_triangles(self.n_azimuth + 1, self.n_height + 1)

    def serialize(self):
        return {'kind': 'cylindrical', 'radius': self.radius, 'height_range': self.height_range,
                'azimuth_range': self.azimuth_range, 'n_azimuth': self.n_azimuth,
                'n_height': self.n_height}


SURFACE_KINDS = {'spherical': SphericalSurface, 'cylindrical': CylindricalSurface}


def deserialize_surface(data):
    data = dict(data)
    kind = data.pop('kind')
    if kind not in SURFACE_KINDS:
        raise ValueError(f"unknown surface kind {kind!r}; expected one of {sorted(SURFACE_KINDS)}")
    return SURFACE_KINDS[kind](**data)


class ScreenMesh:
    """The screen as the renderer needs it: where each point projects, and where it lies.

    :param ndc: (N, 2) projector coordinates in [-1, +1]
    :param directions: (N, 3) unit vectors from the subject towards each point
    :param triangles: (M, 3) indices into the above
    :param positions: (N, 3) the points themselves, in meters -- kept for visualisation and checking
    """

    def __init__(self, ndc, directions, triangles, positions):
        self.ndc = np.asarray(ndc, dtype=np.float32)
        self.directions = np.asarray(directions, dtype=np.float32)
        self.triangles = np.asarray(triangles, dtype=np.int32)
        self.positions = np.asarray(positions, dtype=np.float32)

    @property
    def n_triangles(self):
        return len(self.triangles)

    def interleaved(self):
        """(ndc_x, ndc_y, dir_x, dir_y, dir_z) per vertex, expanded per triangle.

        The layout a vertex buffer wants: one draw call renders the whole screen.
        """
        flat = self.triangles.reshape(-1)
        return np.hstack([self.ndc[flat], self.directions[flat]]).astype(np.float32)

    def off_projector_fraction(self):
        """Fraction of vertices that miss the projector image, as a sanity check on the geometry.

        Zero is not necessarily right -- a projector that overfills the screen is normal -- but a
        large value usually means the projector pose or throw ratio is wrong.
        """
        finite = np.isfinite(self.ndc).all(axis=1)
        inside = finite & (np.abs(self.ndc) <= 1).all(axis=1)
        return 1.0 - inside.mean()


def build_screen_mesh(surface, projector, subject_position=(0, 0, 0)):
    """Tessellate `surface` and work out, for each vertex, where it projects and where it lies.

    Triangles with any vertex the projector cannot see are dropped: they have no image, and keeping
    them would put NaNs in the vertex buffer.
    """
    positions, triangles = surface.vertices_and_triangles()
    ndc = projector.to_ndc(positions)

    directions = positions - np.asarray(subject_position, dtype=float)
    lengths = np.linalg.norm(directions, axis=1, keepdims=True)
    if np.any(lengths < 1e-9):
        raise ValueError('a screen vertex coincides with the subject; direction is undefined there')
    directions = directions / lengths

    visible = np.isfinite(ndc).all(axis=1)
    triangles = triangles[visible[triangles].all(axis=1)]

    return ScreenMesh(ndc=ndc, directions=directions, triangles=triangles, positions=positions)


def _grid_triangles(n_u, n_v):
    """Triangle indices over an n_u x n_v grid of vertices laid out in row-major (u, v) order."""
    u, v = np.meshgrid(np.arange(n_u - 1), np.arange(n_v - 1), indexing='ij')
    lower_left = (u * n_v + v).reshape(-1)
    lower_right = lower_left + n_v
    upper_left = lower_left + 1
    upper_right = lower_right + 1
    return np.concatenate([
        np.stack([lower_left, lower_right, upper_right], axis=-1),
        np.stack([lower_left, upper_right, upper_left], axis=-1),
    ]).astype(np.int32)
