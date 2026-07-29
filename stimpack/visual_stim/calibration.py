"""Measuring a rig's brightness falloff, so it can be corrected.

`projector_irradiance` in curved_screen computes the part of the falloff that follows from geometry.
The rest -- lens vignetting, uneven illumination of the DMD, an apodizing filter, the screen
material's transmission at angle -- has to be measured on the rig. This module is the measuring end:
pick where to measure, and put a spot there.

**Measure from where the animal sits, aimed at the screen, not with a sensor on the screen surface.**
A sensor on the screen reads the irradiance arriving at it; what the correction should even out is
the radiance leaving the screen *towards the animal*, and those differ by the material's angular
behaviour -- which is exactly the part no model predicts, and which a diffusing rear-projection
screen has plenty of. Measuring from the animal's position folds it in for free, and is far easier
than reaching a sensor into a 7 cm bowl past the objective.

A photometer is recommended over photographing the screen. A camera's own falloff is radially
symmetric and strongest at the edges of its frame -- the same signature as the thing being measured
-- so an uncharacterised camera returns a smooth, plausible curve that is partly projector and
partly lens, with nothing in the data to separate them. A photometer's errors (positioning, sparse
sampling) show up as scatter between points, which is visible. A camera earns its place once the
residual is genuinely two-dimensional, and then it needs characterising first.
"""
from typing import NamedTuple

import moderngl
import numpy as np

from stimpack.visual_stim.curved_screen import MeasuredFalloff


class CalibrationSamples(NamedTuple):
    """Where to measure, in the three forms the workflow needs.

    :param positions: (N, 3) points on the screen, in meters -- hand these to
        MeasuredFalloff.from_measurements alongside the readings
    :param ndc: (N, 2) where each sits in the projector image -- show a spot at each in turn
    :param radius: (N,) isotropic radius in the image, for plotting readings against
    """
    positions: np.ndarray
    ndc: np.ndarray
    radius: np.ndarray


def calibration_samples(mesh, projector, n=16):
    """Choose points to measure, spread across the projector's image.

    Spread by *radius*, not by area: the residual varies with distance from the centre of the
    image, so clustering samples where there is most screen wastes readings on one radius.

    Azimuth is varied deliberately as well, by advancing roughly a golden angle between radial
    bins. If the optics really are rotationally symmetric this costs nothing, and if they are not,
    two samples at the same radius disagree and the scatter says so -- rather than the asymmetry
    being averaged silently into a radial curve that fits nothing.

    Only lit vertices are offered: a spot shown where the projector does not reach measures the
    room.

    :param mesh: a built ScreenMesh
    :param projector: the PinholeProjector that built it
    :param n: how many points. 12-20 is plenty for a smooth radial curve.
    """
    if n < 2:
        raise ValueError(f'ask for at least 2 samples, not {n}')

    lit = np.flatnonzero(mesh.lit)
    if len(lit) < n:
        raise ValueError(f'only {len(lit)} lit vertices to choose from; ask for fewer than {n}, '
                         f'or tessellate the surface more finely')

    ndc = np.asarray(mesh.ndc, dtype=float)[lit]
    radius = MeasuredFalloff.radius_in_image(ndc, projector.aspect_ratio)
    azimuth = np.arctan2(ndc[:, 1], ndc[:, 0])

    # Aim at n radii spread evenly across the lit range, and at azimuths advancing by the golden
    # angle. For each target take the nearest unused vertex in radius, breaking ties by azimuth.
    #
    # Nearest-to-a-target rather than one-per-bin: a bin can be empty -- the lit area is not evenly
    # distributed in radius -- and skipping it quietly returns fewer points than were asked for,
    # which for a manual measurement is a worse failure than a sample landing slightly off its
    # intended radius.
    targets = np.linspace(radius.min(), radius.max(), n)
    golden = np.pi * (3 - np.sqrt(5))
    neighbourhood = max(4, len(radius) // (2 * n))

    chosen, used = [], np.zeros(len(radius), dtype=bool)
    for index, target_radius in enumerate(targets):
        available = np.flatnonzero(~used)
        nearest = available[np.argsort(np.abs(radius[available] - target_radius))[:neighbourhood]]
        target_azimuth = np.angle(np.exp(1j * golden * index))
        difference = np.abs(np.angle(np.exp(1j * (azimuth[nearest] - target_azimuth))))
        pick = nearest[np.argmin(difference)]
        used[pick] = True
        chosen.append(pick)

    chosen = np.array(sorted(chosen), dtype=int)
    picked = lit[chosen]
    return CalibrationSamples(positions=np.asarray(mesh.positions, dtype=float)[picked],
                              ndc=ndc[chosen], radius=radius[chosen])


class CalibrationSpot:
    """A filled circle at a given place in the projector image, on an otherwise black screen.

    Drawn in projector coordinates and after the warp, like the corner square -- the whole point is
    to put light at a *known position in the image*, so it must not be resampled by the screen mesh.

    Black everywhere else on purpose: a photometer aimed at the spot also collects whatever the rest
    of the screen scatters back, and on a white bowl that is not small. Take a reading with the spot
    hidden as well, and subtract.
    """

    VERTEX_SHADER = '''
        #version 330
        in vec2 pos;
        out vec2 v_pos;
        void main() {
            v_pos = pos;
            gl_Position = vec4(pos, 0.0, 1.0);
        }
    '''

    FRAGMENT_SHADER = '''
        #version 330
        uniform vec2 centre;
        uniform float radius;
        uniform float aspect_ratio;
        uniform float intensity;
        in vec2 v_pos;
        out vec4 f_color;
        void main() {
            // Round in the image, which NDC is not: y spans the height and x the width, and the
            // image is wider than tall, so a circle in NDC would reach the photometer as an ellipse.
            vec2 offset = vec2(v_pos.x - centre.x, (v_pos.y - centre.y) / aspect_ratio);
            if (length(offset) > radius) discard;
            f_color = vec4(vec3(intensity), 1.0);
        }
    '''

    def __init__(self):
        self.ctx = None
        self.centre = (0.0, 0.0)
        self.radius = 0.05
        self.intensity = 1.0
        self.aspect_ratio = 1.0
        self.visible = False

    def initialize(self, ctx, aspect_ratio=1.0):
        self.ctx = ctx
        self.aspect_ratio = float(aspect_ratio)
        self.prog = ctx.program(vertex_shader=self.VERTEX_SHADER,
                                fragment_shader=self.FRAGMENT_SHADER)
        corners = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        self.vbo = ctx.buffer(corners.tobytes())
        self.vao = ctx.vertex_array(self.prog, [(self.vbo, '2f', 'pos')],
                                    mode=moderngl.TRIANGLE_STRIP)

    def show(self, ndc_x, ndc_y, radius=0.05, intensity=1.0):
        self.centre = (float(ndc_x), float(ndc_y))
        self.radius = float(radius)
        self.intensity = float(intensity)
        self.visible = True

    def hide(self):
        self.visible = False

    def paint(self):
        if not self.visible or self.ctx is None:
            return
        self.prog['centre'].value = self.centre
        self.prog['radius'].value = self.radius
        self.prog['aspect_ratio'].value = self.aspect_ratio
        self.prog['intensity'].value = self.intensity
        self.vao.render()
