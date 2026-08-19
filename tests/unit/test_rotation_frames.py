"""rotation_frame: 'world' (historical fixed-axis z,x,y) vs 'subject' (intrinsic yaw-pitch-roll).

The compatibility contract is the first test: the two frames are IDENTICAL whenever at most one
angle is nonzero, which is every planar experiment ever recorded -- so the option cannot change
any existing rig or replay. The semantic contract is the third: at heading 90 deg, world-frame
pitch is exactly subject-frame roll of the opposite sign, which is the failure mode ('phi reads
as roll') that motivated the option. Pure matrix math, no GL.
"""
import numpy as np
import pytest

from stimpack.visual_stim.cubemap import face_matrices
from stimpack.visual_stim.framework import get_perspective
from stimpack.visual_stim.screen import Screen

pytestmark = pytest.mark.unit

PA, PB, PC = (-0.15, 0.30, -0.15), (0.15, 0.30, -0.15), (-0.15, 0.30, 0.15)


def P(theta, phi, roll, frame):
    matrix = get_perspective({'x': 0, 'y': 0, 'z': 0, 'theta': theta, 'phi': phi, 'roll': roll},
                             PA, PB, PC, False, rotation_frame=frame)
    return np.frombuffer(matrix, dtype='f4') if isinstance(matrix, (bytes, bytearray)) \
        else np.asarray(matrix, dtype='f4')


def test_the_frames_agree_whenever_at_most_one_angle_is_nonzero():
    """The backward-compatibility guarantee: all planar data renders identically under both."""
    for theta in (0, 37, 90, 200):
        assert np.allclose(P(theta, 0, 0, 'world'), P(theta, 0, 0, 'subject'))
    assert np.allclose(P(0, 25, 0, 'world'), P(0, 25, 0, 'subject'))
    assert np.allclose(P(0, 0, 25, 'world'), P(0, 0, 25, 'subject'))


def test_the_frames_differ_when_two_angles_combine():
    assert not np.allclose(P(90, 10, 0, 'world'), P(90, 10, 0, 'subject'))


def test_world_pitch_at_heading_ninety_is_subject_roll():
    """The precise statement of 'phi reads as roll': at theta = 90 deg the world x axis lies
    along the line of sight, so world-frame phi is subject-frame roll, opposite sign
    (verified numerically when the option was built)."""
    assert np.allclose(P(90, 10, 0, 'world'), P(90, 0, -10, 'subject'), atol=1e-6)


def test_the_cube_path_matches_the_planar_path_per_frame():
    """cubemap.face_view_projections documents that its composition matches get_perspective
    exactly -- that promise now includes rotation_frame, or curved rigs would silently disagree
    with flat ones the moment someone combined angles."""
    planar_pos = {'x': 0, 'y': 0, 'z': 0, 'theta': 55, 'phi': 0, 'roll': 0}
    combined_pos = {'x': 0, 'y': 0, 'z': 0, 'theta': 90, 'phi': 10, 'roll': 0}
    swapped_pos = {'x': 0, 'y': 0, 'z': 0, 'theta': 90, 'phi': 0, 'roll': -10}

    assert face_matrices(planar_pos, rotation_frame='world') == \
        face_matrices(planar_pos, rotation_frame='subject')
    assert face_matrices(combined_pos, rotation_frame='world') != \
        face_matrices(combined_pos, rotation_frame='subject')
    world = [np.frombuffer(m, dtype='f4') for m in face_matrices(combined_pos, rotation_frame='world')]
    subject = [np.frombuffer(m, dtype='f4') for m in face_matrices(swapped_pos, rotation_frame='subject')]
    assert all(np.allclose(w, s, atol=1e-6) for w, s in zip(world, subject))


def test_screen_carries_and_serializes_the_choice():
    screen = Screen(fullscreen=False, vsync=False, rotation_frame='subject')
    assert Screen.deserialize(screen.serialize()).rotation_frame == 'subject'
    assert Screen(fullscreen=False, vsync=False).rotation_frame == 'world'   # the legacy default

    with pytest.raises(AssertionError, match='world'):
        Screen(fullscreen=False, vsync=False, rotation_frame='intrinsic')    # say the real names
