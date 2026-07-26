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


def test_off_projector_fraction_flags_a_projector_that_misses_the_screen():
    surface = SphericalSurface(radius=1.0)
    covering = build_screen_mesh(surface, flystim_projector(throw=0.5))
    missing = build_screen_mesh(surface, flystim_projector(throw=1.75))

    assert covering.off_projector_fraction() < 0.1
    assert missing.off_projector_fraction() > 0.5, \
        'flystim1.0 example throw ratio should not cover a full hemisphere'


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
