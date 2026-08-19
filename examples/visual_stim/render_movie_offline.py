#!/usr/bin/env python3
"""
Render a stimulus to a movie with no rig, no server and no window.

Frames are a pure function of time, so this runs anywhere Python and a GPU driver exist --
a workstation with no display included -- and two runs produce identical files.

The second render drives the subject position along a trajectory: the same mechanism that
makes it a point-of-view movie when the trajectory comes from a recorded trial's position log.
"""
from stimpack.visual_stim.offline import render_stim

# A drifting patch, described exactly as a protocol's trial_stim_parameters would.
patch = {'name': 'MovingPatch', 'width': 20, 'height': 20, 'color': [1, 0.5, 0, 1],
         'sphere_radius': 1.0, 'angle': 0, 'phi': 0,
         'theta': {'name': 'TVPairs', 'tv_pairs': [(0, -40), (2, 40)], 'kind': 'linear'}}

render_stim(patch, duration=2.0, fps=60, size=(512, 512), out='moving_patch.mp4')
print('wrote moving_patch.mp4')

# The same stimulus, seen by a subject that turns 90 degrees over the trial: the patch's motion
# on screen is now stimulus motion minus self motion, which is the whole point of a POV render.
turn = {'theta': {'name': 'TVPairs', 'tv_pairs': [(0, 0), (2, 90)], 'kind': 'linear'}}
render_stim(patch, duration=2.0, fps=60, size=(512, 512),
            subject_trajectory=turn, out='moving_patch_pov.mp4')
print('wrote moving_patch_pov.mp4')
