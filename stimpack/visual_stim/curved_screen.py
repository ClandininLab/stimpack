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

from stimpack.visual_stim.screen import Screen, SubScreen
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

    def __init__(self, position=(0, 0, 0.30), forward=None, up=(0, 1, 0),
                 throw_ratio=0.5, aspect_ratio=1.6, look_at=None):
        if forward is None and look_at is None:
            look_at = (0.0, 0.0, 0.0)     # aim at the origin, where the subject is
        if look_at is not None:
            if forward is not None:
                raise ValueError('give either forward or look_at, not both')
            forward = np.asarray(look_at, dtype=float) - np.asarray(position, dtype=float)
            if np.linalg.norm(forward) < 1e-9:
                raise ValueError('look_at coincides with the projector position')
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
    def wintech_pro4500(cls, position, forward=None, up=(0, 1, 0), lens='long', look_at=None):
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
        return cls(position=position, forward=forward, up=up, look_at=look_at,
                   throw_ratio=throw[lens], aspect_ratio=1.6)


class CurvedSurface:
    """A screen surface, tessellated into a triangle mesh of points in the rig, in meters."""

    def vertices_and_triangles(self):
        """Return (vertices (N, 3) in meters, triangles (M, 3) of indices into vertices)."""
        raise NotImplementedError

    def outward_normals(self, vertices):
        """Unit normals pointing away from the surface's axis or centre, one per vertex.

        Needed to work out which part of the screen a projector can actually light. Being inside the
        projector's frustum is not enough -- on a bowl, the far side is squarely within the frustum
        and squarely behind the near side.
        """
        raise NotImplementedError

    def serialize(self):
        raise NotImplementedError


class SphericalSurface(CurvedSurface):
    """A sphere (or a cap of one) centred on the subject.

    Angles follow the rig convention used elsewhere in stimpack: azimuth is measured in the
    horizontal plane from +y (the direction the subject faces), and elevation from that plane
    towards +z.

    ``pole`` tilts the whole patch. The ranges above are measured in the surface's *own* frame, so
    they can only describe a bowl whose rim is horizontal; a bowl mounted at an angle -- which is
    the usual way to put a hemisphere in front of an animal rather than under it -- has a rim that
    is not a range of rig elevations at all. Naming where the surface's own axis points says it
    directly, and leaves the ranges meaning what they meant.

    Worth knowing what this does *not* affect: nothing about the projection. Where a point lands on
    the projector and which direction it lies in from the subject both depend only on the sphere and
    the optics, and a sphere is unchanged by rotating it about its centre. Getting the pole wrong
    therefore does not distort the image -- it changes which parts of the sphere are screen, so the
    mesh can run past the real rim at one edge and fall short at another.

    :param radius: meters
    :param azimuth_range: (min, max) degrees; the default is the full 360
    :param elevation_range: (min, max) degrees; the default is the upper hemisphere
    :param n_azimuth: tessellation steps around
    :param n_elevation: tessellation steps up
    :param pole: rig-frame direction of the surface's own +z axis, about which the ranges above are
        measured; the default (0, 0, 1) leaves the patch where the ranges put it
    :param roll: degrees about ``pole``, which decides where azimuth zero lands. Only matters for a
        patch that does not go all the way round.
    """

    def __init__(self, radius=0.15, azimuth_range=(-180, 180), elevation_range=(0, 90),
                 n_azimuth=36, n_elevation=9, pole=(0, 0, 1), roll=0.0):
        self.radius = float(radius)
        self.azimuth_range = tuple(float(v) for v in azimuth_range)
        self.elevation_range = tuple(float(v) for v in elevation_range)
        self.n_azimuth = int(n_azimuth)
        self.n_elevation = int(n_elevation)
        self.pole = tuple(float(v) for v in pole)
        self.roll = float(roll)
        if np.linalg.norm(self.pole) < 1e-9:
            raise ValueError('pole must be a direction, not the zero vector')

    def vertices_and_triangles(self):
        azimuth = np.radians(np.linspace(*self.azimuth_range, self.n_azimuth + 1))
        elevation = np.radians(np.linspace(*self.elevation_range, self.n_elevation + 1))
        az, el = np.meshgrid(azimuth, elevation, indexing='ij')

        horizontal = self.radius * np.cos(el)
        vertices = np.stack([horizontal * np.sin(az),      # x, right of the subject
                             horizontal * np.cos(az),      # y, in front of the subject
                             self.radius * np.sin(el)],    # z, above the subject
                            axis=-1).reshape(-1, 3)

        # Built in the surface's own frame above, then turned to face where it is mounted. The
        # triangles are indices, so they are unaffected.
        rotation = _rotation_from_pole(self.pole, self.roll)
        vertices = vertices @ rotation.T
        return vertices, _grid_triangles(self.n_azimuth + 1, self.n_elevation + 1)

    def outward_normals(self, vertices):
        return np.asarray(vertices, dtype=float) / self.radius

    def serialize(self):
        return {'kind': 'spherical', 'radius': self.radius, 'azimuth_range': self.azimuth_range,
                'elevation_range': self.elevation_range, 'n_azimuth': self.n_azimuth,
                'n_elevation': self.n_elevation, 'pole': self.pole, 'roll': self.roll}


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

    def outward_normals(self, vertices):
        normals = np.asarray(vertices, dtype=float).copy()
        normals[:, 2] = 0.0                      # the axis direction has no curvature
        return normals / self.radius

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

    def __init__(self, ndc, directions, triangles, positions, lit=None):
        self.ndc = np.asarray(ndc, dtype=np.float32)
        self.directions = np.asarray(directions, dtype=np.float32)
        self.triangles = np.asarray(triangles, dtype=np.int32)
        self.positions = np.asarray(positions, dtype=np.float32)
        # Per vertex: does the projector actually light this point? Needs both that it falls inside
        # the image and that the surface faces the projector at all.
        self.lit = (np.ones(len(self.ndc), dtype=bool) if lit is None
                    else np.asarray(lit, dtype=bool))

    @property
    def n_triangles(self):
        return len(self.triangles)

    def interleaved(self):
        """(ndc_x, ndc_y, dir_x, dir_y, dir_z) per vertex, expanded per triangle.

        The layout a vertex buffer wants: one draw call renders the whole screen.
        """
        flat = self.triangles.reshape(-1)
        return np.hstack([self.ndc[flat], self.directions[flat]]).astype(np.float32)

    def coverage(self, radius=None):
        """What part of the screen this projector actually lights, as a dict.

        Not an error metric. A rig may well cover only part of its screen on purpose -- a projector
        mounted to one side of a bowl lights the part it faces and nothing else -- so this reports a
        fact about the setup rather than scoring it. What it is good for is checking the covered
        patch is where you meant it to be, and knowing which part of the subject's visual field is
        actually being stimulated.
        """
        lit = self.lit
        result = {'fraction': float(lit.mean())}
        if not lit.any():
            return result | {'azimuth': None, 'elevation': None}

        positions = self.positions[lit]
        azimuth = np.degrees(np.arctan2(positions[:, 0], positions[:, 1]))
        if radius is None:
            radius = float(np.linalg.norm(self.positions, axis=1).max())
        elevation = np.degrees(np.arcsin(np.clip(positions[:, 2] / radius, -1, 1)))
        return result | {'azimuth': _circular_range(azimuth),
                         'elevation': (float(elevation.min()), float(elevation.max()))}

def build_screen_mesh(surface, projector, subject_position=(0, 0, 0)):
    """Tessellate `surface` and work out, for each vertex, where it projects and where it lies.

    Two different things are worked out here and it is worth not conflating them.

    Triangles the projector cannot *see* are dropped -- either because they fall behind it, which
    would put NaNs in the vertex buffer, or because the surface turns away from it. On a bowl lit
    from one side, the far wall sits squarely inside the frustum and squarely behind the near wall;
    without the facing test it would be drawn as though lit, and the reported coverage would claim
    the whole 360 degrees of azimuth.

    Triangles that merely fall outside the image are *kept*. Partial coverage is normal, and a
    triangle straddling the edge of the image should be drawn and clipped by the rasterizer, not
    dropped whole -- dropping it would eat a triangle's worth of real screen at every edge.
    """
    positions, triangles = surface.vertices_and_triangles()
    ndc = projector.to_ndc(positions)

    towards_projector = np.asarray(projector.position, dtype=float) - positions
    faces_projector = np.einsum('ij,ij->i', surface.outward_normals(positions), towards_projector) > 0

    directions = positions - np.asarray(subject_position, dtype=float)
    lengths = np.linalg.norm(directions, axis=1, keepdims=True)
    if np.any(lengths < 1e-9):
        raise ValueError('a screen vertex coincides with the subject; direction is undefined there')
    directions = directions / lengths

    visible = np.isfinite(ndc).all(axis=1) & faces_projector
    triangles = triangles[visible[triangles].all(axis=1)]

    if len(triangles) == 0:
        # Silently returning an empty mesh would give a screen that renders nothing, with nothing
        # anywhere explaining it. Almost always the projector is aimed away from the surface, or is
        # on the wrong side of it -- rear projection lights the convex face.
        behind = int((~np.isfinite(ndc).all(axis=1)).sum())
        turned_away = int((~faces_projector).sum())
        raise ValueError(
            f'the projector lights no part of this surface: of {len(positions)} points, '
            f'{behind} fall behind it and {turned_away} face away from it. Check that it is '
            f'aimed at the screen (look_at=) and on the side the screen is projected from.')

    lit = visible & (np.abs(np.nan_to_num(ndc, nan=np.inf)) <= 1).all(axis=1)
    return ScreenMesh(ndc=ndc, directions=directions, triangles=triangles, positions=positions,
                      lit=lit)


def _circular_range(angles_deg):
    """The arc a set of azimuths occupies, as (start, end) degrees, going anticlockwise.

    Plain min/max is wrong for an angle: a patch centred behind the subject spans, say, 170 to -170,
    and min/max calls that the entire circle. Find the widest gap between neighbouring angles
    instead; the covered arc is everything else. The returned start may exceed the end, which is how
    a wrapped arc reads (170 to -170 is the 20-degree patch behind, not the 340 degrees in front).
    """
    angles = np.sort(np.mod(np.asarray(angles_deg, dtype=float), 360.0))
    if len(angles) < 2:
        return (float(angles[0]), float(angles[0]))

    gaps = np.diff(np.concatenate([angles, angles[:1] + 360.0]))
    widest = int(np.argmax(gaps))

    start = angles[(widest + 1) % len(angles)]
    end = angles[widest]
    wrap = lambda a: float((a + 180.0) % 360.0 - 180.0)      # noqa: E731 - back to (-180, +180]
    return (wrap(start), wrap(end))


def _skew(vector):
    x, y, z = vector
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def _rotation_from_pole(pole, roll_degrees=0.0):
    """Rotation taking +z to `pole`, then turning by `roll` degrees about it.

    The shortest such rotation, so that a surface with the default pole comes back exactly
    unrotated rather than merely equivalent -- an identity here means the existing mesh is
    reproduced bit for bit, which is what makes the parameter safe to add to a working rig.

    Roll is applied after, and is the only thing that distinguishes rotations sharing a pole. It
    matters for a patch that does not go all the way round in azimuth; for one that does, the
    surface is symmetric under it.

    :param pole: rig-frame direction the surface's own +z should point (need not be normalized)
    :param roll_degrees: rotation about that direction
    """
    pole = np.asarray(pole, dtype=float)
    pole = pole / np.linalg.norm(pole)
    z = np.array([0.0, 0.0, 1.0])

    axis = np.cross(z, pole)
    sine, cosine = np.linalg.norm(axis), float(z @ pole)
    if sine < 1e-12:
        # Parallel or antiparallel, where the cross product says nothing about the axis. Turning
        # about x by 180 degrees is one of the many rotations that inverts z; any of them will do,
        # since a pole antiparallel to z leaves the roll to pick between them anyway.
        align = np.eye(3) if cosine > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        skew = _skew(axis)
        align = np.eye(3) + skew + skew @ skew * ((1 - cosine) / sine ** 2)

    theta = np.radians(roll_degrees)
    skew = _skew(pole)
    spin = np.eye(3) + np.sin(theta) * skew + (1 - np.cos(theta)) * skew @ skew
    return spin @ align


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


class CurvedScreen(Screen):
    """A Screen whose surface is curved, rendered through a cube map rather than flat frusta.

    Subclasses Screen so everything around it -- launching the subprocess, the photodiode square,
    fullscreen and display selection, the EGL path -- keeps working untouched. What changes is only
    how the stimulus reaches the display: StimDisplay draws the scene into a cube map and then draws
    this screen's mesh once, instead of drawing every stimulus once per flat subscreen.

    The inherited subscreens are left in place and unused, so a curved screen can still answer the
    questions the planar code asks of it.

    :param surface: a CurvedSurface -- the shape of the screen
    :param projector: a PinholeProjector -- where its light lands
    :param cube_resolution: pixels per cube face. 512 is already well under what a fly resolves.
    """

    def __init__(self, surface=None, projector=None, cube_resolution=1024, **kwargs):
        super().__init__(**kwargs)
        self.surface = surface if surface is not None else SphericalSurface()
        self.projector = projector if projector is not None else PinholeProjector()
        self.cube_resolution = int(cube_resolution)

    def build_mesh(self, subject_position=(0, 0, 0)):
        """The screen mesh. subject_position is where the subject physically sits, not where it is
        in the virtual world.

        For a tethered animal those differ, and only the first belongs here: the mesh describes
        fixed geometry -- which direction each part of the screen lies in, as seen from the animal.
        Virtual movement is handled entirely by rendering the cube map from the virtual position,
        exactly as the planar path handles it (GenPerspective keeps its eye at the rig origin and
        translates the world instead). Passing the virtual position here as well applies the
        translation twice; a test comparing the two paths caught that at 14 px on a 192 px screen.
        """
        return build_screen_mesh(self.surface, self.projector, subject_position=subject_position)

    def serialize(self):
        data = super().serialize()
        data['kind'] = 'curved'
        data['surface'] = self.surface.serialize()
        data['projector'] = self.projector.serialize()
        data['cube_resolution'] = self.cube_resolution
        return data

    @classmethod
    def deserialize_curved(cls, data):
        kwargs = dict(data)
        kwargs['subscreens'] = [SubScreen.deserialize(sub) for sub in kwargs.get('subscreens', [])]
        kwargs['surface'] = deserialize_surface(kwargs['surface'])
        kwargs['projector'] = PinholeProjector.deserialize(kwargs['projector'])
        return cls(**kwargs)
