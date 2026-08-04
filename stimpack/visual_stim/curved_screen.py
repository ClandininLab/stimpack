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
    :param n_azimuth: tessellation steps around. The default is 5 degrees a step, matching the
        tessellation flymax settled on. Finer costs almost nothing -- the whole screen is one draw
        call however many facets it has -- and it buys geometric accuracy, not sharpness: a flat
        facet sags inside the true sphere, so the direction a fragment samples along is wrong by
        about 0.055 degrees mid-facet at 5 degrees, against 0.218 at 10. Sharpness comes from the
        cube map instead (see CubeMapRenderer.resolution).
    :param n_elevation: tessellation steps up
    :param pole: rig-frame direction of the surface's own +z axis, about which the ranges above are
        measured; the default (0, 0, 1) leaves the patch where the ranges put it
    :param roll: degrees about ``pole``, which decides where azimuth zero lands. Only matters for a
        patch that does not go all the way round.
    """

    def __init__(self, radius=0.15, azimuth_range=(-180, 180), elevation_range=(0, 90),
                 n_azimuth=72, n_elevation=18, pole=(0, 0, 1), roll=0.0):
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
                 n_azimuth=72, n_height=4):
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


# Below this, a triangle is a sliver of the tessellation rather than a piece of screen, and the
# pixels-per-solid-angle ratio stops meaning anything. See ScreenMesh.projector_resolution.
DEGENERATE_SOLID_ANGLE = 1e-9


class ScreenMesh:
    """The screen as the renderer needs it: where each point projects, and where it lies.

    :param ndc: (N, 2) projector coordinates in [-1, +1]
    :param directions: (N, 3) unit vectors from the subject towards each point
    :param triangles: (M, 3) indices into the above
    :param positions: (N, 3) the points themselves, in meters -- kept for visualisation and checking
    """

    def __init__(self, ndc, directions, triangles, positions, lit=None, gain=None):
        self.ndc = np.asarray(ndc, dtype=np.float32)
        self.directions = np.asarray(directions, dtype=np.float32)
        self.triangles = np.asarray(triangles, dtype=np.int32)
        self.positions = np.asarray(positions, dtype=np.float32)
        # Per vertex: does the projector actually light this point? Needs both that it falls inside
        # the image and that the surface faces the projector at all.
        self.lit = (np.ones(len(self.ndc), dtype=bool) if lit is None
                    else np.asarray(lit, dtype=bool))
        # Per vertex: what the fragment shader multiplies the sampled colour by, to even out an
        # uneven projector. Kept separate from `lit` rather than folded into one weight -- they
        # answer different questions, and coverage() reports the fraction of the screen the
        # projector *reaches*, which a float would quietly turn into a mean attenuation. It also
        # keeps "unreachable" distinct from "corrected to nearly nothing", which is a distinction
        # anyone debugging a dark rig wants.
        self.gain = (np.ones(len(self.ndc), dtype=np.float32) if gain is None
                     else np.asarray(gain, dtype=np.float32))

    @property
    def n_triangles(self):
        return len(self.triangles)

    def interleaved(self):
        """(ndc_x, ndc_y, dir_x, dir_y, dir_z, gain) per vertex, expanded per triangle.

        The layout a vertex buffer wants: one draw call renders the whole screen.
        """
        flat = self.triangles.reshape(-1)
        return np.hstack([self.ndc[flat], self.directions[flat],
                          self.gain[flat, None]]).astype(np.float32)

    def projector_resolution(self, projector_pixels, cube_resolution=None):
        """How finely the projector resolves each part of the screen, in pixels per degree.

        This is the number that says whether an intermediate is throwing information away. A
        projector throwing onto a curved surface spreads its pixels wildly: the same panel that
        resolves tens of pixels per degree near its optical axis may deliver a fraction of one at
        grazing incidence, so a single figure for "the resolution of the rig" does not exist.

        Measured, not modelled twice over. Each triangle of the mesh already carries both halves of
        the map -- where its corners land in the projector image (``ndc``) and which way they lie
        from the subject (``directions``) -- so the local density is the ratio of the two areas,
        and needs no assumption the renderer does not already make.

        Linear density rather than areal: a patch subtending an angle t on a side holds (t*d)^2
        pixels, so d = sqrt(pixels / solid angle) is the pixels-per-radian a feature of that size
        actually gets.

        :param projector_pixels: (width, height) of the projector panel, in pixels
        :param cube_resolution: pixels per cube-map face to compare against; defaults to the
            renderer's own default, so the answer is about the rig as it would actually run
        :return: dict with the per-triangle densities, their spread, and what a cube map would
            have to be to keep up

        The comparison to draw from the result is between ``best`` and ``cube_px_per_deg``. Where
        the projector is finer than the cube, the intermediate is the limit and detail the optics
        could deliver is being discarded; where it is coarser, the cube is spending fill on
        resolution the screen cannot show.
        """
        from stimpack.visual_stim.cubemap import CUBE_FACE_DEGREES, DEFAULT_CUBE_RESOLUTION

        if cube_resolution is None:
            cube_resolution = DEFAULT_CUBE_RESOLUTION
        width, height = (float(v) for v in projector_pixels)

        corners = self.triangles.reshape(-1, 3)
        lit = self.lit[corners].all(axis=1)
        if not lit.any():
            return {'lit_triangles': 0, 'best': None, 'worst': None, 'ratio': None,
                    'cube_px_per_deg': cube_resolution / CUBE_FACE_DEGREES,
                    'cube_resolution_to_match': None, 'fraction_cube_limited': None}
        corners = corners[lit]

        # area in the projector image, converted to pixels. NDC spans [-1, 1] on each axis, so the
        # whole image is 4 units of area and holds width*height pixels.
        a, b, c = (self.ndc[corners[:, i]].astype(float) for i in range(3))
        edge1, edge2 = b - a, c - a
        ndc_area = 0.5 * np.abs(edge1[:, 0] * edge2[:, 1] - edge1[:, 1] * edge2[:, 0])
        pixels = ndc_area * (width * height / 4.0)

        # solid angle the same triangle subtends at the subject (Van Oosterom & Strackee)
        da, db, dc = (self.directions[corners[:, i]].astype(float) for i in range(3))
        for v in (da, db, dc):
            v /= np.linalg.norm(v, axis=1, keepdims=True)
        numerator = np.abs(np.einsum('ij,ij->i', da, np.cross(db, dc)))
        denominator = (1.0 + np.einsum('ij,ij->i', da, db)
                       + np.einsum('ij,ij->i', db, dc)
                       + np.einsum('ij,ij->i', dc, da))
        solid_angle = 2.0 * np.arctan2(numerator, denominator)

        # A spherical tessellation collapses at its pole: triangles there have vanishing solid
        # angle, so the ratio below is a division of two near-zeros and lands anywhere. On the
        # default bowl 72 of 1896 triangles are such slivers, carrying 0.0000% of the screen's
        # solid angle between them -- and left in, they set the reported maximum, which is how a
        # first version of this reported 187 px/deg for a rig that reaches about 11.
        usable = (solid_angle > DEGENERATE_SOLID_ANGLE) & (ndc_area > 0)
        if not usable.any():
            return {'lit_triangles': 0, 'best': None, 'worst': None, 'ratio': None,
                    'cube_px_per_deg': cube_resolution / CUBE_FACE_DEGREES,
                    'cube_resolution_to_match': None, 'fraction_cube_limited': None}

        density = np.sqrt(pixels[usable] / solid_angle[usable]) * np.pi / 180.0
        weight = solid_angle[usable]

        # Percentiles, weighted by how much screen each triangle actually covers, rather than
        # min and max: an extremum over a mesh is a property of the tessellation as much as of
        # the optics, and every consumer of this wants "what does most of the screen get".
        order = np.argsort(density)
        cumulative = np.cumsum(weight[order]) / weight.sum()
        def at(fraction):
            return float(density[order][np.searchsorted(cumulative, fraction)])

        cube_px_per_deg = cube_resolution / CUBE_FACE_DEGREES
        best, worst = at(0.99), at(0.01)
        return {
            'lit_triangles': int(usable.sum()),
            'degenerate_triangles': int((~usable).sum()),
            'px_per_deg': density,
            'solid_angle': weight,
            # 99th and 1st percentiles by screen area, not extrema -- see above
            'best': best,
            'worst': worst,
            'median': at(0.5),
            'ratio': best / worst if worst > 0 else float('inf'),
            'cube_px_per_deg': cube_px_per_deg,
            # what the cube would have to be to stop limiting the screen's best region
            'cube_resolution_to_match': float(best * CUBE_FACE_DEGREES),
            # share of the screen, by solid angle, where the cube rather than the optics is the
            # limit -- i.e. where the experimenter is getting less than the rig could deliver
            'fraction_cube_limited': float(weight[density > cube_px_per_deg].sum() / weight.sum()),
        }


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

def projector_irradiance(surface, projector, positions):
    """How brightly the projector lights each point, relative to the brightest one.

    Three factors, and the third is the one that is easy to leave out::

        E  ~  cos(alpha) / ( L^2 * cos^3(theta) )

        alpha   between the arriving beam and the surface normal -- an oblique beam spreads
        L       projector to that point -- inverse square
        theta   that point off the projector's optical axis

    The first two say brightness falls off away from the centre, which is the intuition. The third
    says the opposite: a DMD pixel at angle theta subtends LESS solid angle from the pinhole
    (foreshortening x distance squared), so its fixed flux is packed into a narrower cone.

    For a flat screen square-on to the projector these cancel exactly, and the screen is evenly lit
    -- which has to be so, because a pinhole projection of a flat DMD onto a parallel plane is a
    pure magnification, and every pixel therefore lights an equal area. Any falloff a rig sees on
    such a screen is optical (lens vignetting, lamp non-uniformity) and no geometry predicts it.
    Geometry only bites when the screen is tilted, off-axis, or curved.

    Checked against the Clandinin hemisphere rig's own measured curve: this reproduces it to within
    about 15% out to 64 degrees off the axis, with no fitting. It diverges at the limb, where
    incidence reaches 90 degrees and this goes to zero while a real diffusing screen still passes
    some light, and it cannot know about deliberate optics -- that rig has an apodizing filter,
    which changes the edge by a factor of 20.

    So this is the computable half. The rest has to be measured per rig, and multiplied in.

    :return: (N,) relative irradiance in [0, 1], zero where the projector does not reach
    """
    positions = np.atleast_2d(np.asarray(positions, dtype=float))
    _, _, forward = projector._basis()

    ray = positions - np.asarray(projector.position, dtype=float)
    distance = np.linalg.norm(ray, axis=1)
    with np.errstate(divide='ignore', invalid='ignore'):
        towards = ray / distance[:, None]

    cos_theta = towards @ forward
    cos_alpha = -np.einsum('ij,ij->i', towards, surface.outward_normals(positions))

    with np.errstate(divide='ignore', invalid='ignore'):
        irradiance = cos_alpha / (distance ** 2 * cos_theta ** 3)

    # Behind the projector, edge-on, or facing away: no light, rather than a negative or infinite
    # amount. Points facing away are the far wall of a bowl, which the caller drops anyway.
    irradiance = np.where((cos_theta > 0) & (cos_alpha > 0) & np.isfinite(irradiance),
                          irradiance, 0.0)
    peak = irradiance.max()
    return irradiance / peak if peak > 0 else irradiance


class MeasuredFalloff:
    """A rig's measured brightness variation, as a function of position in the projector's image.

    The half of the falloff that geometry cannot predict: lens vignetting, uneven illumination of
    the DMD, an apodizing filter someone installed, the screen material's transmission at angle.
    Every one of those is a property of the projector or of the material, not of where the screen
    happens to sit -- which is why this is indexed by projector NDC rather than by position on the
    screen. A table measured that way survives moving the screen, and two projectors lighting one
    screen each keep their own.

    (The rig this was written against indexes its curve by position on the sphere instead. That
    works there because its projector sits on the bowl's axis, which makes the two equivalent; it
    stops working the moment anything is off-axis.)

    **This is a residual, not a measurement.** It multiplies the computed geometric term rather than
    replacing it, so handing it raw photometer readings counts the geometry twice -- the screen then
    gets corrected about twice as hard as it needs, which looks like a plausible over-correction
    rather than an obvious bug. Use from_measurements(), which divides the geometry out for you.

    :param radii: sample positions, as isotropic radius in the projector image (see radius_in_image)
    :param values: relative brightness there, any scale -- normalised on construction
    :param aspect_ratio: of the projector, needed to make the radius isotropic
    """

    def __init__(self, radii, values, aspect_ratio=1.0):
        radii = np.asarray(radii, dtype=float)
        values = np.asarray(values, dtype=float)
        if radii.shape != values.shape or radii.ndim != 1 or len(radii) < 2:
            raise ValueError('radii and values must be 1-D arrays of the same length, at least 2')
        if np.any(np.diff(radii) <= 0):
            raise ValueError('radii must increase; sort the samples before constructing')
        if np.any(values <= 0):
            raise ValueError('brightness values must be positive')

        self.radii = radii
        self.values = values / values.max()
        self.aspect_ratio = float(aspect_ratio)

    @staticmethod
    def radius_in_image(ndc, aspect_ratio):
        """Distance from the centre of the projector image, in units where its half-WIDTH is 1.

        NDC is anisotropic -- x spans the width and y the height, and the image is wider than it is
        tall -- so plain hypot(x, y) is not a distance in the image and would smear a rotationally
        symmetric optic into an elliptical one. Dividing y by the aspect ratio restores it.
        """
        ndc = np.atleast_2d(np.asarray(ndc, dtype=float))
        return np.hypot(ndc[:, 0], ndc[:, 1] / aspect_ratio)

    def __call__(self, ndc):
        """Relative brightness at each NDC position, in [0, 1]. Flat beyond the sampled range."""
        radius = self.radius_in_image(ndc, self.aspect_ratio)
        return np.interp(radius, self.radii, self.values)

    @classmethod
    def from_measurements(cls, positions, measured, surface, projector):
        """Build a residual from raw photometer readings taken on the screen.

        The one that should be used. It divides out what the geometry already accounts for, so what
        is stored is only what the geometry got wrong.

        Readings may be in any units and taken at any single commanded value: only ratios between
        points are used, so the display's transfer function cancels and no gamma is involved here.

        :param positions: (N, 3) where each reading was taken, in meters, in the rig frame
        :param measured: (N,) photometer readings there
        """
        positions = np.atleast_2d(np.asarray(positions, dtype=float))
        measured = np.asarray(measured, dtype=float)
        if len(positions) != len(measured):
            raise ValueError(f'{len(positions)} positions but {len(measured)} readings')

        geometric = projector_irradiance(surface, projector, positions)
        if np.any(geometric <= 0):
            raise ValueError('some measurement positions are not lit by this projector at all; '
                             'check they are on the screen and the projector pose is right')

        residual = measured / geometric
        radius = cls.radius_in_image(projector.to_ndc(positions), projector.aspect_ratio)

        # Readings at the same radius are repeats: for an optic symmetric about the projector's
        # axis they sample the same place in the image, just at different azimuths. Averaging them
        # is both what the table needs -- one value per radius -- and better statistics than
        # picking one. A ring of measurements round the screen is a natural way to collect these,
        # so this is the common case rather than an edge one.
        keys, groups = np.unique(np.round(radius, 6), return_inverse=True)
        averaged = np.bincount(groups, weights=residual) / np.bincount(groups)
        return cls(keys, averaged, aspect_ratio=projector.aspect_ratio)

    def serialize(self):
        return {'radii': self.radii.tolist(), 'values': self.values.tolist(),
                'aspect_ratio': self.aspect_ratio}

    @classmethod
    def deserialize(cls, data):
        return cls(**data)


def brightness_gain(irradiance, target, gamma=1.0):
    """Per-vertex multiplier that flattens `irradiance` to `target` x its peak.

    A correction can only ever scale *down*, so flattening means bringing everything to the level of
    the dimmest point being corrected. On a bowl the dimmest lit point is at the limb, where
    irradiance goes to zero -- so "flatten everything" means "black screen". `target` is what stops
    that: it names the fraction of peak brightness to flatten to, and points already dimmer than
    that are left alone rather than driven to zero.

    Lower target, flatter screen, less light. The Clandinin rig faces the same trade in MATLAB and
    answers it by keeping two curves, one for the full screen and one for a restricted region.

    `gamma` is the display's transfer function: light ~ commanded^gamma. The gain above is a ratio
    of *light*, but what the shader multiplies is a *commanded value*, so it has to be converted.
    The default of 1.0 assumes a linear projector, which is almost certainly wrong and is what a rig
    gets until someone measures it -- see the note in CurvedScreen.

    :param irradiance: (N,) relative, as projector_irradiance returns
    :param target: fraction of peak brightness to flatten to, in (0, 1]
    :param gamma: exponent of the display's response
    :return: (N,) multipliers in [0, 1]
    """
    if not 0 < target <= 1:
        raise ValueError(f'target must be a fraction of peak brightness in (0, 1], not {target}')
    if gamma <= 0:
        raise ValueError(f'gamma must be positive, not {gamma}')

    irradiance = np.asarray(irradiance, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        gain = np.where(irradiance > 0, target / irradiance, 1.0)
    # Above 1 means this point is already dimmer than the target and would need amplifying, which a
    # projector cannot do. Left at 1: dimmer than the rest, but visible.
    return np.clip(gain, 0.0, 1.0) ** (1.0 / gamma)


def build_screen_mesh(surface, projector, subject_position=(0, 0, 0),
                      brightness_correction=None, gamma=1.0, measured_falloff=None):
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

    gain = None
    if brightness_correction is not None:
        irradiance = projector_irradiance(surface, projector, positions)
        if measured_falloff is not None:
            # The measured residual multiplies the computed geometry rather than replacing it; see
            # MeasuredFalloff, which is also where the trap of passing raw readings is described.
            irradiance = irradiance * measured_falloff(ndc)
            peak = irradiance.max()
            if peak > 0:
                irradiance = irradiance / peak
        gain = brightness_gain(irradiance, target=brightness_correction, gamma=gamma)

    return ScreenMesh(ndc=ndc, directions=directions, triangles=triangles, positions=positions,
                      lit=lit, gain=gain)


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
    :param brightness_correction: None for none, or the fraction of peak brightness to flatten the
        screen to. A projector does not light a curved screen evenly, and the gradient is a
        confound in any experiment where the stimulus moves across it. Correcting costs light --
        see brightness_gain -- so the level is yours to choose rather than implied.
    :param gamma: exponent of the display's response, light ~ commanded^gamma. Only used when
        correcting. The default of 1.0 says the projector is linear, which is very likely wrong:
        nothing in stimpack measures this, and until a rig does, its correction is directionally
        right and quantitatively off. Measuring it is one photometer and eight levels.
    """

    def __init__(self, surface=None, projector=None, cube_resolution=1024,
                 brightness_correction=None, gamma=1.0, measured_falloff=None, **kwargs):
        super().__init__(**kwargs)
        self.surface = surface if surface is not None else SphericalSurface()
        self.projector = projector if projector is not None else PinholeProjector()
        self.cube_resolution = int(cube_resolution)
        self.brightness_correction = (None if brightness_correction is None
                                      else float(brightness_correction))
        self.gamma = float(gamma)
        self.measured_falloff = measured_falloff

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
        return build_screen_mesh(self.surface, self.projector,
                                subject_position=subject_position,
                                brightness_correction=self.brightness_correction,
                                gamma=self.gamma, measured_falloff=self.measured_falloff)

    def serialize(self):
        data = super().serialize()
        data['kind'] = 'curved'
        data['surface'] = self.surface.serialize()
        data['projector'] = self.projector.serialize()
        data['cube_resolution'] = self.cube_resolution
        data['brightness_correction'] = self.brightness_correction
        data['gamma'] = self.gamma
        data['measured_falloff'] = (None if self.measured_falloff is None
                                    else self.measured_falloff.serialize())
        return data

    @classmethod
    def deserialize_curved(cls, data):
        kwargs = dict(data)
        # Screen.deserialize strips this before delegating here, so production never carries it --
        # but serialize() emits it, and a pair that cannot round-trip its own output is a trap for
        # anyone who calls these directly.
        kwargs.pop('kind', None)
        kwargs['subscreens'] = [SubScreen.deserialize(sub) for sub in kwargs.get('subscreens', [])]
        kwargs['surface'] = deserialize_surface(kwargs['surface'])
        kwargs['projector'] = PinholeProjector.deserialize(kwargs['projector'])
        if kwargs.get('measured_falloff') is not None:
            kwargs['measured_falloff'] = MeasuredFalloff.deserialize(kwargs['measured_falloff'])
        return cls(**kwargs)
