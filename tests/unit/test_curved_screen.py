"""Unit tests for curved-screen geometry.

The load-bearing test is the first one: the projector model has to reproduce flystim1.0's
to_screen_pt exactly, because that model is the one that was actually validated against the
hemisphere rig. Everything else here is guarding the tessellation and bookkeeping around it.
"""
from math import cos, radians, sin

import pytest

pytest.importorskip("numpy")
import numpy as np  # noqa: E402

from stimpack.visual_stim.curved_screen import (  # noqa: E402
    CylindricalSurface, PinholeProjector, ScreenMesh, SphericalSurface,
    build_screen_mesh, deserialize_surface,
)

pytestmark = pytest.mark.unit


def flystim_to_screen_pt(lon, lat, radius=1.0, distance=1.0, throw=1.75, aspect=16 / 9):
    """flystim1.0's examples/hemisphere.py, verbatim, as the reference implementation."""
    r_xy = radius * sin(radians(lat))
    x, y, z = r_xy * cos(radians(lon)), r_xy * sin(radians(lon)), radius * cos(radians(lat))
    ndc_x = 2 * throw * x / (radius + distance - z)
    ndc_y = 2 * throw * aspect * y / (radius + distance - z)
    return (ndc_x, ndc_y), (x, y, z)


def flystim_projector(radius=1.0, distance=1.0, throw=1.75, aspect=16 / 9):
    """The projector pose flystim1.0 assumed implicitly: on +z, looking back at the origin."""
    return PinholeProjector(position=(0, 0, radius + distance), forward=(0, 0, -1), up=(0, 1, 0),
                            throw_ratio=throw, aspect_ratio=aspect)


# --- the projector model -------------------------------------------------------------------------

def test_projector_reproduces_flystim1_exactly():
    """This model is a generalization of flystim1.0's, so it must agree with it where they overlap.

    Not approximately: the flystim1.0 hemisphere was calibrated on real hardware, so any drift here
    is a silent change to where stimuli land on the screen.
    """
    points, expected = [], []
    for lon in range(0, 360, 15):
        for lat in range(0, 90, 10):
            ndc, cart = flystim_to_screen_pt(lon, lat)
            points.append(cart)
            expected.append(ndc)

    got = flystim_projector().to_ndc(np.array(points))

    assert np.allclose(got, np.array(expected), rtol=0, atol=1e-12)


def test_a_point_on_the_projector_axis_maps_to_the_centre():
    projector = PinholeProjector(position=(0, 0, 1), forward=(0, 0, -1), up=(0, 1, 0))
    assert np.allclose(projector.to_ndc([[0, 0, 0]]), [[0, 0]])


def test_points_behind_the_projector_are_not_projected():
    """Dividing by a negative depth would fold them onto the image, mirrored, with no complaint."""
    projector = PinholeProjector(position=(0, 0, 1), forward=(0, 0, -1), up=(0, 1, 0))
    ndc = projector.to_ndc([[0.1, 0, 2.0]])          # behind the projector
    assert np.isnan(ndc).all()


def test_projector_up_parallel_to_forward_is_rejected():
    with pytest.raises(ValueError, match='parallel'):
        PinholeProjector(forward=(0, 0, -1), up=(0, 0, 1)).to_ndc([[0, 0, 0]])


def test_a_further_projector_gives_a_smaller_image():
    """Basic pinhole behaviour, and a guard on the sign of the depth term."""
    near = PinholeProjector(position=(0, 0, 0.5), forward=(0, 0, -1), up=(0, 1, 0))
    far = PinholeProjector(position=(0, 0, 2.0), forward=(0, 0, -1), up=(0, 1, 0))
    point = [[0.1, 0, 0]]
    assert abs(near.to_ndc(point)[0, 0]) > abs(far.to_ndc(point)[0, 0])


# --- surfaces ------------------------------------------------------------------------------------

def test_sphere_vertices_all_lie_on_the_sphere():
    vertices, _ = SphericalSurface(radius=0.15).vertices_and_triangles()
    assert np.allclose(np.linalg.norm(vertices, axis=1), 0.15)


def test_sphere_angles_follow_the_rig_convention():
    """Azimuth from +y (the direction the subject faces), elevation up towards +z."""
    surface = SphericalSurface(radius=1.0, azimuth_range=(0, 90), elevation_range=(0, 90),
                               n_azimuth=1, n_elevation=1)
    vertices, _ = surface.vertices_and_triangles()

    assert any(np.allclose(v, [0, 1, 0], atol=1e-9) for v in vertices), 'azimuth 0 should face +y'
    assert any(np.allclose(v, [1, 0, 0], atol=1e-9) for v in vertices), 'azimuth 90 should be +x'
    assert any(np.allclose(v, [0, 0, 1], atol=1e-9) for v in vertices), 'elevation 90 should be +z'


def test_cylinder_vertices_lie_on_the_cylinder():
    surface = CylindricalSurface(radius=0.15, height_range=(-0.05, 0.05))
    vertices, _ = surface.vertices_and_triangles()
    assert np.allclose(np.hypot(vertices[:, 0], vertices[:, 1]), 0.15)
    assert vertices[:, 2].min() == pytest.approx(-0.05)
    assert vertices[:, 2].max() == pytest.approx(0.05)


@pytest.mark.parametrize('surface', [
    SphericalSurface(n_azimuth=6, n_elevation=3),
    CylindricalSurface(n_azimuth=6, n_height=2),
])
def test_triangles_index_real_vertices_and_have_area(surface):
    vertices, triangles = surface.vertices_and_triangles()
    assert triangles.min() >= 0 and triangles.max() < len(vertices)

    a, b, c = (vertices[triangles[:, i]] for i in range(3))
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    assert (areas > 0).all(), 'a degenerate triangle would render as nothing'


@pytest.mark.parametrize('surface', [SphericalSurface(), CylindricalSurface()])
def test_surfaces_round_trip_through_serialization(surface):
    """Screens are serialized to reach the screen subprocess, so this is on the live path."""
    restored = deserialize_surface(surface.serialize())
    assert type(restored) is type(surface)
    original_v, original_t = surface.vertices_and_triangles()
    restored_v, restored_t = restored.vertices_and_triangles()
    assert np.allclose(original_v, restored_v)
    assert np.array_equal(original_t, restored_t)


def test_an_unknown_surface_kind_is_rejected():
    with pytest.raises(ValueError, match='unknown surface kind'):
        deserialize_surface({'kind': 'toroidal', 'radius': 1})


# --- the mesh ------------------------------------------------------------------------------------

def test_mesh_directions_are_unit_vectors_towards_each_point():
    mesh = build_screen_mesh(SphericalSurface(radius=0.15), flystim_projector())
    assert np.allclose(np.linalg.norm(mesh.directions, axis=1), 1.0, atol=1e-6)
    # with the subject at the origin, direction is just the normalized position
    assert np.allclose(mesh.directions,
                       mesh.positions / np.linalg.norm(mesh.positions, axis=1, keepdims=True),
                       atol=1e-6)


def test_directions_are_relative_to_the_subject_not_the_origin():
    offset = (0.0, 0.05, 0.0)
    mesh = build_screen_mesh(SphericalSurface(radius=0.15), flystim_projector(),
                             subject_position=offset)
    expected = mesh.positions - np.array(offset, dtype=np.float32)
    expected = expected / np.linalg.norm(expected, axis=1, keepdims=True)
    assert np.allclose(mesh.directions, expected, atol=1e-6)


def test_triangles_the_projector_cannot_see_are_dropped():
    """A NaN in the vertex buffer would corrupt the whole screen mesh, not just one triangle."""
    surface = SphericalSurface(radius=1.0, elevation_range=(-90, 90), n_azimuth=12, n_elevation=6)
    # projector close above the sphere, so the lower half is behind it
    mesh = build_screen_mesh(surface, PinholeProjector(position=(0, 0, 1.5), forward=(0, 0, -1),
                                                       up=(0, 1, 0)))
    kept = mesh.ndc[mesh.triangles.reshape(-1)]
    assert np.isfinite(kept).all(), 'a dropped-triangle vertex still carries NaN'
    assert mesh.n_triangles > 0, 'everything was dropped; the test is not exercising anything'


def test_interleaved_buffer_layout():
    mesh = build_screen_mesh(SphericalSurface(n_azimuth=6, n_elevation=3), flystim_projector())
    data = mesh.interleaved()

    # ndc_x, ndc_y, dir_x, dir_y, dir_z, gain
    assert data.shape == (mesh.n_triangles * 3, 6)
    assert data.dtype == np.float32
    first = mesh.triangles[0, 0]
    assert np.allclose(data[0, :2], mesh.ndc[first])
    assert np.allclose(data[0, 2:5], mesh.directions[first])
    assert np.allclose(data[0, 5], mesh.gain[first])


def test_coverage_reports_how_much_of_the_screen_is_lit():
    surface = SphericalSurface(radius=1.0)
    wide = build_screen_mesh(surface, flystim_projector(throw=0.5)).coverage()
    narrow = build_screen_mesh(surface, flystim_projector(throw=1.75)).coverage()

    assert wide['fraction'] > narrow['fraction'], 'a longer throw should light less of the screen'


def test_coverage_is_a_fact_not_a_failure():
    """Partial coverage is normal -- a projector to one side of a bowl lights the side it faces.

    coverage() must therefore describe the lit patch rather than score it, or it would report a
    correctly configured rig as broken.
    """
    bowl = SphericalSurface(radius=0.15, elevation_range=(-90, 0), n_azimuth=72, n_elevation=18)
    projector = PinholeProjector.wintech_pro4500(position=(0, -0.6, 0), forward=(0, 1, 0),
                                                 up=(0, 0, 1))
    coverage = build_screen_mesh(bowl, projector).coverage(radius=0.15)

    assert 0 < coverage['fraction'] < 1
    assert coverage['elevation'][0] < 0 and coverage['elevation'][1] <= 0, 'a bowl is below'


def test_the_far_side_of_a_bowl_is_not_reported_as_lit():
    """It sits inside the frustum and behind the near wall; only a facing test excludes it."""
    bowl = SphericalSurface(radius=0.15, elevation_range=(-90, 0), n_azimuth=72, n_elevation=18)
    projector = PinholeProjector.wintech_pro4500(position=(0, -0.6, 0), forward=(0, 1, 0),
                                                 up=(0, 0, 1))
    mesh = build_screen_mesh(bowl, projector)

    # the projector sits on -y, so it lights the far hemisphere in azimuth, around 180 degrees
    lit_positions = mesh.positions[mesh.lit]
    assert (lit_positions[:, 1] < 0.15).all()
    start, end = mesh.coverage(radius=0.15)['azimuth']
    assert start > 0 and end < 0, f'expected an arc wrapping through 180, got {start} to {end}'


def test_azimuth_range_handles_the_wraparound():
    """min/max on an angle calls a patch spanning 170..190 the whole circle."""
    from stimpack.visual_stim.curved_screen import _circular_range

    assert _circular_range([170, 175, 180, -175, -170]) == (170.0, -170.0)
    assert _circular_range([-20, -10, 0, 10, 20]) == (-20.0, 20.0)


def test_a_vertex_at_the_subject_is_an_error_not_a_nan():
    mesh_surface = SphericalSurface(radius=0.15)
    with pytest.raises(ValueError, match='coincides with the subject'):
        build_screen_mesh(mesh_surface, flystim_projector(), subject_position=(0, 0.15, 0))


def test_mesh_accepts_plain_arrays():
    """ScreenMesh is constructed by the builder, but should not be fussy if built by hand."""
    mesh = ScreenMesh(ndc=[[0, 0], [1, 0], [0, 1]],
                      directions=[[0, 1, 0], [1, 0, 0], [0, 0, 1]],
                      triangles=[[0, 1, 2]], positions=[[0, 1, 0], [1, 0, 0], [0, 0, 1]])
    assert mesh.n_triangles == 1
    assert mesh.interleaved().shape == (3, 6)
    assert np.allclose(mesh.gain, 1.0), 'an uncorrected mesh should not attenuate'


# --- the actual projector ------------------------------------------------------------------------

def test_pro4500_matches_the_published_working_distance_table():
    """Both rows of WinTech's table must fall out of the model, or the numbers are being misread.

        92 mm  ->  65.6 x 41 mm
        700 mm ->  400  x 250 mm
    """
    for distance_mm, width_mm, height_mm, lens in ((92, 65.6, 41, 'short'), (700, 400, 250, 'long')):
        d, w, h = distance_mm / 1000, width_mm / 1000, height_mm / 1000
        projector = PinholeProjector.wintech_pro4500(position=(0, 0, 0), forward=(0, 0, 1),
                                                     up=(0, 1, 0), lens=lens)
        # the corners of the quoted field, at the quoted working distance, should be the image edges
        corners = np.array([[w / 2, h / 2, d], [-w / 2, -h / 2, d]])
        ndc = projector.to_ndc(corners)
        assert np.allclose(np.abs(ndc), 1.0, atol=0.005), \
            f'{lens} lens: field corners map to {ndc}, expected the image boundary'


def test_pro4500_aspect_is_16_10_not_16_9():
    """flystim1.0 used 16/9; the engine is 1.6, and the error lands in the worse-covered axis."""
    assert PinholeProjector.wintech_pro4500(position=(0, 0, 1)).aspect_ratio == pytest.approx(1.6)


def test_pro4500_rejects_an_unknown_lens():
    with pytest.raises(ValueError, match='lens must be one of'):
        PinholeProjector.wintech_pro4500(position=(0, 0, 1), lens='fisheye')


# --- a bowl that is not mounted level ------------------------------------------------------------

def test_the_default_pole_changes_nothing():
    """Added to a working rig, so an unspecified pole has to reproduce the old mesh exactly rather
    than merely equivalently."""
    from stimpack.visual_stim.curved_screen import SphericalSurface

    plain = SphericalSurface(radius=0.0715, n_azimuth=12, n_elevation=6)
    with_pole = SphericalSurface(radius=0.0715, n_azimuth=12, n_elevation=6, pole=(0, 0, 1))

    a, ta = plain.vertices_and_triangles()
    b, tb = with_pole.vertices_and_triangles()
    assert np.array_equal(a, b)
    assert np.array_equal(ta, tb)


def test_the_pole_tilts_the_whole_patch():
    """A hemisphere's rim is perpendicular to its pole, wherever the pole points."""
    from stimpack.visual_stim.curved_screen import SphericalSurface

    tilt = 35.0
    pole = (0, -np.sin(np.radians(tilt)), np.cos(np.radians(tilt)))     # tilted forward
    surface = SphericalSurface(radius=0.0715, elevation_range=(0, 90), n_azimuth=36, n_elevation=9,
                               pole=pole)
    vertices, _ = surface.vertices_and_triangles()

    # every vertex is still on the sphere, and still within 90 degrees of the pole
    assert np.allclose(np.linalg.norm(vertices, axis=1), 0.0715)
    angle = np.degrees(np.arccos(np.clip(vertices @ np.array(pole) / 0.0715, -1, 1)))
    assert angle.max() <= 90 + 1e-9
    assert np.isclose(angle.max(), 90, atol=1e-6), 'the rim should reach exactly 90 degrees'

    # the rim (elevation 0 in the surface frame) lies in the plane perpendicular to the pole
    rim = vertices[np.isclose(angle, 90, atol=1e-6)]
    assert np.allclose(rim @ np.array(pole), 0, atol=1e-9)


def test_the_pole_leaves_the_sphere_alone():
    """The whole point of the parameter: it says which parts are screen, and nothing else. A sphere
    is unchanged by rotating it about its centre, so the set of points is identical."""
    from stimpack.visual_stim.curved_screen import SphericalSurface

    level = SphericalSurface(radius=0.0715, elevation_range=(-90, 90), n_azimuth=36, n_elevation=18)
    tilted = SphericalSurface(radius=0.0715, elevation_range=(-90, 90), n_azimuth=36, n_elevation=18,
                              pole=(0, -0.6, 0.8))

    a, _ = level.vertices_and_triangles()
    b, _ = tilted.vertices_and_triangles()
    assert np.allclose(np.sort(np.linalg.norm(a, axis=1)), np.sort(np.linalg.norm(b, axis=1)))
    assert not np.allclose(a, b), 'a partial sphere should actually move'


def test_roll_turns_the_patch_about_its_own_pole():
    from stimpack.visual_stim.curved_screen import SphericalSurface

    kwargs = dict(radius=0.0715, azimuth_range=(-30, 30), elevation_range=(0, 60),
                  n_azimuth=6, n_elevation=3)
    straight, _ = SphericalSurface(**kwargs).vertices_and_triangles()
    rolled, _ = SphericalSurface(**kwargs, roll=90).vertices_and_triangles()

    assert not np.allclose(straight, rolled)
    # a roll about +z cannot change how high anything is
    assert np.allclose(np.sort(straight[:, 2]), np.sort(rolled[:, 2]))


def test_a_full_ring_is_symmetric_under_roll():
    from stimpack.visual_stim.curved_screen import SphericalSurface

    kwargs = dict(radius=0.0715, elevation_range=(0, 90), n_azimuth=36, n_elevation=9)
    straight, _ = SphericalSurface(**kwargs).vertices_and_triangles()
    rolled, _ = SphericalSurface(**kwargs, roll=30).vertices_and_triangles()

    # the same set of points, in a different order round the ring
    assert np.allclose(np.sort(np.linalg.norm(straight, axis=1)),
                       np.sort(np.linalg.norm(rolled, axis=1)))
    assert np.allclose(np.sort(straight[:, 2]), np.sort(rolled[:, 2]))


def test_an_upside_down_pole_is_handled():
    """The cross product says nothing about the axis when the pole is antiparallel to +z, which is
    exactly the bowl-underneath case."""
    from stimpack.visual_stim.curved_screen import SphericalSurface

    surface = SphericalSurface(radius=0.0715, elevation_range=(0, 90), n_azimuth=12, n_elevation=6,
                               pole=(0, 0, -1))
    vertices, _ = surface.vertices_and_triangles()

    assert np.all(np.isfinite(vertices))
    assert vertices[:, 2].max() <= 1e-9, 'the patch should hang below the subject'
    assert np.allclose(np.linalg.norm(vertices, axis=1), 0.0715)


def test_a_zero_pole_is_refused():
    from stimpack.visual_stim.curved_screen import SphericalSurface

    with pytest.raises(ValueError, match='direction'):
        SphericalSurface(pole=(0, 0, 0))


def test_the_pole_survives_serialization():
    """The surface is serialized to reach the screen subprocess, so a pole that did not round-trip
    would give a correct mesh in the parent and a level one on the rig."""
    from stimpack.visual_stim.curved_screen import SphericalSurface, deserialize_surface

    surface = SphericalSurface(radius=0.0715, pole=(0, -0.6, 0.8), roll=15)
    restored = deserialize_surface(surface.serialize())

    assert restored.pole == surface.pole
    assert restored.roll == surface.roll
    assert np.allclose(restored.vertices_and_triangles()[0], surface.vertices_and_triangles()[0])


def test_a_tilted_bowl_lit_along_its_own_axis_stays_inside_its_rim():
    """The flymax rig: a hemisphere mounted at an angle, with the projector on its axis aimed at
    the animal at the sphere's centre. Everything drawn must land on real screen."""
    from stimpack.visual_stim.curved_screen import (SphericalSurface, PinholeProjector,
                                                    build_screen_mesh)

    radius, distance, tilt = 0.0715, 0.302067, 35.0
    axis = np.array([0, -np.sin(np.radians(tilt)), -np.cos(np.radians(tilt))])   # bowl faces up-ish

    surface = SphericalSurface(radius=radius, elevation_range=(0, 90),
                               n_azimuth=72, n_elevation=18, pole=axis)
    projector = PinholeProjector(position=tuple(distance * axis), look_at=(0, 0, 0),
                                 throw_ratio=1.57523511, aspect_ratio=1.6)
    mesh = build_screen_mesh(surface, projector)

    drawn = mesh.positions[np.unique(mesh.triangles)]
    angle = np.degrees(np.arccos(np.clip(drawn @ axis / radius, -1, 1)))

    # nothing past the rim, and nothing beyond where the projector's rays graze the limb
    tangent_limit = 90 - np.degrees(np.arcsin(radius / distance))
    assert angle.max() <= 90, 'the mesh runs past the bowl rim'
    assert angle.max() <= tangent_limit + 1e-6
    assert np.isclose(angle.max(), tangent_limit, atol=6.0), 'should reach nearly to the limb'
    assert 0.6 < mesh.lit.mean() < 0.95


# --- brightness correction -----------------------------------------------------------------------

def flat_surface_perpendicular(distance=0.3, half_width=0.2, n=9):
    """A flat screen square-on to a projector at (0, 0, distance), as a CurvedSurface."""
    from stimpack.visual_stim.curved_screen import CurvedSurface

    class Flat(CurvedSurface):
        def vertices_and_triangles(self):
            xs = np.linspace(-half_width, half_width, n)
            x, y = np.meshgrid(xs, xs, indexing='ij')
            verts = np.stack([x.ravel(), y.ravel(), np.zeros(x.size)], axis=-1)
            return verts, np.zeros((0, 3), dtype=int)

        def outward_normals(self, vertices):
            return np.tile([0.0, 0.0, 1.0], (len(vertices), 1))

    return Flat()


def test_a_flat_screen_square_on_is_evenly_lit():
    """The result that makes the third term worth having. Distance and obliquity both say the edges
    should be dimmer; the shrinking solid angle of an off-axis DMD pixel says brighter; they cancel
    exactly. A model with only the first two would 'correct' a screen that needs no correcting."""
    from stimpack.visual_stim.curved_screen import PinholeProjector, projector_irradiance

    surface = flat_surface_perpendicular(distance=0.3)
    projector = PinholeProjector(position=(0, 0, 0.3), look_at=(0, 0, 0), throw_ratio=1.0)
    positions, _ = surface.vertices_and_triangles()

    irradiance = projector_irradiance(surface, projector, positions)
    assert np.allclose(irradiance, 1.0), f'spread {irradiance.min():.6f}..{irradiance.max():.6f}'


def test_the_geometric_model_reproduces_the_rig_s_measured_falloff():
    """The claim the whole design rests on: enough of the falloff is geometry that it is worth
    computing, and the rest has to be measured. Measured on the Clandinin hemisphere rig, 7 points
    across the projected cap, normalised to the centre."""
    from stimpack.visual_stim.curved_screen import (SphericalSurface, PinholeProjector,
                                                    projector_irradiance)

    radius, distance = 0.0715, 0.302067
    measured = np.array([33, 32.5, 29.5, 21, 12, 6.5, 3.5], dtype=float)
    measured /= measured[0]
    phi = np.linspace(0, np.radians(76.31), len(measured))

    surface = SphericalSurface(radius=radius, elevation_range=(-90, 90))
    projector = PinholeProjector(position=(0, 0, distance), look_at=(0, 0, 0),
                                 throw_ratio=1.57523511, aspect_ratio=1.6)
    positions = radius * np.stack([np.sin(phi), np.zeros_like(phi), np.cos(phi)], axis=-1)
    predicted = projector_irradiance(surface, projector, positions)

    # Out to 64 degrees, geometry alone lands within 20% with nothing fitted.
    ratio = predicted[:-1] / measured[:-1]
    assert np.all(np.abs(ratio - 1) < 0.2), np.round(ratio, 3)

    # The last point is the limb, where incidence reaches 90 degrees. The model says zero; the real
    # screen still passes light. That gap is why the residual has to be measured per rig.
    assert predicted[-1] < 1e-6 < measured[-1]


def test_correction_flattens_the_screen_to_the_chosen_level():
    from stimpack.visual_stim.curved_screen import (SphericalSurface, PinholeProjector,
                                                    projector_irradiance, brightness_gain)

    surface = SphericalSurface(radius=0.0715, elevation_range=(0, 90), n_azimuth=36, n_elevation=12)
    projector = PinholeProjector(position=(0, 0, 0.302067), look_at=(0, 0, 0),
                                 throw_ratio=1.57523511, aspect_ratio=1.6)
    positions, _ = surface.vertices_and_triangles()
    irradiance = projector_irradiance(surface, projector, positions)

    target = 0.25
    gain = brightness_gain(irradiance, target=target)
    corrected = irradiance * gain

    bright_enough = irradiance >= target
    assert bright_enough.any(), 'the test is not exercising the corrected region'
    assert np.allclose(corrected[bright_enough], target), 'the corrected region is not flat'
    assert np.all(gain <= 1.0), 'a projector cannot amplify'


def test_points_dimmer_than_the_target_are_left_alone_not_blacked_out():
    """The trap in the obvious implementation: the dimmest lit point on a bowl is at the limb, where
    irradiance goes to zero, so flattening to the true minimum turns the whole screen off."""
    from stimpack.visual_stim.curved_screen import brightness_gain

    irradiance = np.array([1.0, 0.5, 0.2, 0.05, 0.0])
    gain = brightness_gain(irradiance, target=0.25)

    assert np.allclose(gain[:2], [0.25, 0.5])          # brighter than target: attenuated onto it
    assert np.allclose(gain[2:], 1.0)                  # dimmer: untouched, not driven to zero
    assert gain.max() <= 1.0


def test_gamma_converts_a_light_ratio_into_a_commanded_one():
    """The gain is a ratio of light; the shader multiplies a commanded value. On a display with
    response light ~ commanded^gamma, applying the light ratio directly overcorrects."""
    from stimpack.visual_stim.curved_screen import brightness_gain

    irradiance = np.array([1.0, 0.5])
    linear = brightness_gain(irradiance, target=0.5, gamma=1.0)
    encoded = brightness_gain(irradiance, target=0.5, gamma=2.2)

    assert np.isclose(linear[0], 0.5)
    assert np.isclose(encoded[0], 0.5 ** (1 / 2.2))
    # and the light it produces is the same either way
    assert np.isclose(encoded[0] ** 2.2, linear[0])
    assert encoded[0] > linear[0], 'encoding for a gamma display asks for a larger commanded value'


def test_no_correction_leaves_the_mesh_exactly_as_it_was():
    from stimpack.visual_stim.curved_screen import SphericalSurface, build_screen_mesh

    surface = SphericalSurface(radius=0.0715, n_azimuth=12, n_elevation=6)
    projector = flystim_projector()

    plain = build_screen_mesh(surface, projector)
    explicit = build_screen_mesh(surface, projector, brightness_correction=None)

    assert np.allclose(plain.gain, 1.0)
    assert np.array_equal(plain.interleaved(), explicit.interleaved())


def test_the_correction_reaches_the_vertex_buffer():
    from stimpack.visual_stim.curved_screen import SphericalSurface, build_screen_mesh

    surface = SphericalSurface(radius=0.0715, elevation_range=(0, 90), n_azimuth=24, n_elevation=8)
    projector = PinholeProjector(position=(0, 0, 0.302067), look_at=(0, 0, 0),
                                 throw_ratio=1.57523511, aspect_ratio=1.6)
    mesh = build_screen_mesh(surface, projector, brightness_correction=0.25)

    assert mesh.gain.min() < 0.9, 'nothing was attenuated'
    assert mesh.gain.max() <= 1.0
    flat = mesh.triangles.reshape(-1)
    assert np.allclose(mesh.interleaved()[:, 5], mesh.gain[flat])


def test_a_nonsensical_target_is_refused():
    from stimpack.visual_stim.curved_screen import brightness_gain

    for bad in (0.0, -0.5, 1.5):
        with pytest.raises(ValueError, match='fraction of peak'):
            brightness_gain(np.array([1.0]), target=bad)
    with pytest.raises(ValueError, match='gamma'):
        brightness_gain(np.array([1.0]), target=0.5, gamma=0)


def test_the_correction_survives_serialization():
    """It is set in a config and used in the screen subprocess, so a value that did not round-trip
    would correct in the parent and not on the rig."""
    from stimpack.visual_stim.curved_screen import CurvedScreen

    from stimpack.visual_stim.screen import Screen

    screen = CurvedScreen(brightness_correction=0.3, gamma=2.2)
    # Through Screen.deserialize, which is the path the screen subprocess actually takes
    restored = Screen.deserialize(screen.serialize())
    assert isinstance(restored, CurvedScreen)
    # ...and directly, which is what anyone reading the class would try
    assert CurvedScreen.deserialize_curved(screen.serialize()).gamma == 2.2

    assert restored.brightness_correction == 0.3
    assert restored.gamma == 2.2
    assert np.allclose(restored.build_mesh().gain, screen.build_mesh().gain)


# --- the measured residual -------------------------------------------------------------------------

def hemisphere_rig():
    """The Clandinin hemisphere, from its own measurements."""
    from stimpack.visual_stim.curved_screen import SphericalSurface, PinholeProjector

    surface = SphericalSurface(radius=0.0715, elevation_range=(0, 90),
                               n_azimuth=36, n_elevation=12)
    projector = PinholeProjector(position=(0, 0, 0.302067), look_at=(0, 0, 0),
                                 throw_ratio=1.57523511, aspect_ratio=1.6)
    return surface, projector


def test_a_known_residual_is_recovered_from_readings():
    """The round trip that matters: invent an optical falloff, simulate what a photometer would
    read through it, and check from_measurements gets it back rather than the total."""
    from stimpack.visual_stim.curved_screen import (MeasuredFalloff, projector_irradiance)

    surface, projector = hemisphere_rig()
    positions, _ = surface.vertices_and_triangles()
    lit = projector_irradiance(surface, projector, positions) > 0
    positions = positions[lit][::7]

    geometric = projector_irradiance(surface, projector, positions)
    radius = MeasuredFalloff.radius_in_image(projector.to_ndc(positions), projector.aspect_ratio)
    true_residual = 1 - 0.4 * radius            # a plain vignette, the thing geometry cannot know
    readings = 12.5 * geometric * true_residual  # arbitrary photometer units

    falloff = MeasuredFalloff.from_measurements(positions, readings, surface, projector)
    recovered = falloff(projector.to_ndc(positions))

    assert np.allclose(recovered, true_residual / true_residual.max(), atol=1e-6)


def test_the_readings_units_and_level_do_not_matter():
    """Only ratios between points are used, so the photometer's units and the commanded value it
    was measured at both cancel -- which is also why no gamma enters here."""
    from stimpack.visual_stim.curved_screen import MeasuredFalloff, projector_irradiance

    surface, projector = hemisphere_rig()
    positions, _ = surface.vertices_and_triangles()
    positions = positions[projector_irradiance(surface, projector, positions) > 0][::9]
    readings = projector_irradiance(surface, projector, positions) * (1 - 0.3 * np.arange(len(positions)) / len(positions))

    one = MeasuredFalloff.from_measurements(positions, readings, surface, projector)
    other = MeasuredFalloff.from_measurements(positions, readings * 87.3, surface, projector)

    assert np.allclose(one.values, other.values)


def test_passing_raw_readings_as_a_residual_double_counts():
    """The trap the API is shaped to avoid. Handing the raw curve straight to MeasuredFalloff --
    rather than through from_measurements -- multiplies the geometry in twice, and the result is a
    plausible-looking over-correction rather than an obvious failure."""
    from stimpack.visual_stim.curved_screen import (MeasuredFalloff, build_screen_mesh,
                                                    projector_irradiance)

    surface, projector = hemisphere_rig()
    positions, _ = surface.vertices_and_triangles()
    sample = positions[projector_irradiance(surface, projector, positions) > 0][::7]
    readings = projector_irradiance(surface, projector, sample)      # pure geometry, no residual

    right = MeasuredFalloff.from_measurements(sample, readings, surface, projector)

    # What building the table by hand from raw readings looks like: same averaging by radius, but
    # without dividing the geometry out first.
    radius = MeasuredFalloff.radius_in_image(projector.to_ndc(sample), projector.aspect_ratio)
    keys, groups = np.unique(np.round(radius, 6), return_inverse=True)
    averaged = np.bincount(groups, weights=readings) / np.bincount(groups)
    wrong = MeasuredFalloff(keys, averaged, aspect_ratio=projector.aspect_ratio)

    # Done right, the residual is flat -- there was nothing for it to explain.
    assert np.allclose(right.values, 1.0, atol=1e-6)
    assert wrong.values.min() < 0.5, 'the raw curve should be far from flat'

    # The symptom is not a bigger number anywhere -- the smallest gain is always the target -- it
    # is that the result stops being flat. Believing the screen is dimmer than it is over-corrects
    # towards the edges, so the residual gradient comes back inverted.
    truth = projector_irradiance(surface, projector, positions)
    correct = build_screen_mesh(surface, projector, brightness_correction=0.3,
                                measured_falloff=right).gain
    doubled = build_screen_mesh(surface, projector, brightness_correction=0.3,
                                measured_falloff=wrong).gain

    corrected_region = (correct < 1) & (doubled < 1) & (truth > 0)
    assert corrected_region.sum() > 20, 'not enough of the screen is being corrected to compare'

    right_light = truth[corrected_region] * correct[corrected_region]
    wrong_light = truth[corrected_region] * doubled[corrected_region]
    assert np.allclose(right_light, right_light[0], rtol=1e-3), 'the correct residual is not flat'
    assert wrong_light.max() / wrong_light.min() > 1.5, 'double counting left the screen flat'


def test_the_residual_multiplies_the_geometry_rather_than_replacing_it():
    from stimpack.visual_stim.curved_screen import MeasuredFalloff, build_screen_mesh

    surface, projector = hemisphere_rig()
    flat = MeasuredFalloff([0.0, 2.0], [1.0, 1.0], aspect_ratio=projector.aspect_ratio)

    without = build_screen_mesh(surface, projector, brightness_correction=0.3).gain
    with_flat = build_screen_mesh(surface, projector, brightness_correction=0.3,
                                  measured_falloff=flat).gain
    assert np.allclose(without, with_flat), 'a flat residual should change nothing'

    vignette = MeasuredFalloff([0.0, 1.0], [1.0, 0.25], aspect_ratio=projector.aspect_ratio)
    with_vignette = build_screen_mesh(surface, projector, brightness_correction=0.3,
                                      measured_falloff=vignette).gain
    assert not np.allclose(without, with_vignette), 'a real residual should change the correction'


def test_the_radius_is_isotropic_in_the_image():
    """NDC x spans the width and y the height, and the image is wider than tall, so plain hypot
    would smear a rotationally symmetric optic into an elliptical one."""
    from stimpack.visual_stim.curved_screen import MeasuredFalloff

    aspect = 1.6
    # the right edge midpoint and the top edge midpoint are at different distances in the image
    right_edge = MeasuredFalloff.radius_in_image([[1.0, 0.0]], aspect)
    top_edge = MeasuredFalloff.radius_in_image([[0.0, 1.0]], aspect)

    assert np.isclose(right_edge[0], 1.0)
    assert np.isclose(top_edge[0], 1.0 / aspect)
    assert np.isclose(MeasuredFalloff.radius_in_image([[0.0, 0.0]], aspect)[0], 0.0)


def test_a_falloff_refuses_input_it_cannot_use():
    from stimpack.visual_stim.curved_screen import MeasuredFalloff

    with pytest.raises(ValueError, match='at least 2'):
        MeasuredFalloff([0.0], [1.0])
    with pytest.raises(ValueError, match='increase'):
        MeasuredFalloff([1.0, 0.0], [1.0, 0.5])
    with pytest.raises(ValueError, match='positive'):
        MeasuredFalloff([0.0, 1.0], [1.0, 0.0])

    surface, projector = hemisphere_rig()
    with pytest.raises(ValueError, match='positions but'):
        MeasuredFalloff.from_measurements(np.zeros((3, 3)), [1.0, 2.0], surface, projector)


def test_measurements_off_the_lit_area_are_refused():
    """Dividing by a geometric term of zero would produce an infinite residual, and silently."""
    from stimpack.visual_stim.curved_screen import MeasuredFalloff

    surface, projector = hemisphere_rig()
    behind = np.array([[0.0, 0.0, -0.0715], [0.0, 0.0, 0.0715]])
    with pytest.raises(ValueError, match='not lit'):
        MeasuredFalloff.from_measurements(behind, [1.0, 1.0], surface, projector)


def test_the_residual_survives_serialization():
    from stimpack.visual_stim.curved_screen import CurvedScreen, MeasuredFalloff
    from stimpack.visual_stim.screen import Screen

    surface, projector = hemisphere_rig()
    falloff = MeasuredFalloff([0.0, 0.5, 1.0], [1.0, 0.8, 0.4], aspect_ratio=1.6)
    screen = CurvedScreen(surface=surface, projector=projector,
                          brightness_correction=0.3, measured_falloff=falloff)

    restored = Screen.deserialize(screen.serialize())
    assert np.allclose(restored.measured_falloff.values, falloff.values)
    assert np.allclose(restored.build_mesh().gain, screen.build_mesh().gain)
