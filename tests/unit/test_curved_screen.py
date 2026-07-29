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

    assert data.shape == (mesh.n_triangles * 3, 5)     # ndc_x, ndc_y, dir_x, dir_y, dir_z
    assert data.dtype == np.float32
    first = mesh.triangles[0, 0]
    assert np.allclose(data[0, :2], mesh.ndc[first])
    assert np.allclose(data[0, 2:], mesh.directions[first])


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
    assert mesh.interleaved().shape == (3, 5)


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
