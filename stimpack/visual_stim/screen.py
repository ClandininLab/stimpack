"""
Describing a physical display to stimpack.

A :class:`Screen` is one display device; a :class:`SubScreen` is a rectangular region of it,
given by its three physical corners in **meters** (``pa`` lower-left, ``pb`` lower-right, ``pc``
upper-left) plus a viewport within the display. Those corners are what perspective correction is
computed from, so measuring them accurately is what makes the geometry on screen correct.

Several subscreens may share one display, and several screens may make up a rig.
"""
from math import sqrt

# The color channels of a frame, in index order.
#
# Under subframe multiplexing the same permutation has to be told to two things in two vocabularies:
# the renderer works in indices, because a color write mask is positional, while a projector's
# pattern LUT is configured by channel name. Writing it out twice is how a rig ends up with the two
# halves transposed -- which reorders timepoints without producing an error, since scrambled motion
# is still motion. These two functions let a rig hold one permutation and derive the other reading.
CHANNEL_NAMES = ('red', 'green', 'blue')


def channel_names(channel_order):
    """Name the channels in `channel_order`, e.g. (2, 0, 1) -> ('blue', 'red', 'green').

    For handing a screen's ``subframe_channel_order`` to a projector driver that takes names.
    """
    # Checked by membership rather than by indexing and catching IndexError: CHANNEL_NAMES[-1] is a
    # legal lookup that quietly answers 'blue', and a wrong name here is a wrong pattern LUT. `in`
    # rejects negatives and non-integers while still accepting a numpy integer.
    try:
        valid = all(index in range(len(CHANNEL_NAMES)) for index in channel_order)
    except TypeError:
        valid = False
    if not valid:
        raise ValueError(f'channel indices must be drawn from 0, 1, 2 ({", ".join(CHANNEL_NAMES)}), '
                         f'not {channel_order}')
    return tuple(CHANNEL_NAMES[index] for index in channel_order)


def channel_indices(names):
    """The inverse of :func:`channel_names`: ('blue', 'red') -> (2, 0)."""
    unknown = [name for name in names if name not in CHANNEL_NAMES]
    if unknown:
        raise ValueError(f'unknown channel name(s) {unknown}; expected from {list(CHANNEL_NAMES)}')
    return tuple(CHANNEL_NAMES.index(name) for name in names)


class SubScreen:
    """
    SubScreen of a Screen object
    defined by physical screen dimensions and a viewport on the display device
    pa, pb, pc as in: https://csc.lsu.edu/~kooima/articles/genperspective/index.html
    i.e. pa is the lower-left corner of the screen, from the perspective of the viewer

    pc
    |
    |
    |
    |
    pa-----------pb

    """

    def __init__(self, pa=(-0.15, 0.30, -0.15), pb=(+0.15, 0.30, -0.15), pc=(-0.15, 0.30, +0.15), viewport_ll=(-1.0,-1.0), viewport_width=2.0, viewport_height=2.0):
        """
        :param pa: meters (x,y,z)
        :param pb: meters (x,y,z)
        :param pc: meters (x,y,z)
        :param viewport_ll: (x, y) NDC coordinates of lower-left corner of viewport for SubScreen [-1, +1]
        :param viewport_width: NDC width of viewport [0, 2]
        :param viewport_height: NDC height of viewport [0, 2]

        """
        self.pa = pa
        self.pb = pb
        self.pc = pc

        self.viewport_ll = viewport_ll
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

    def get_viewport(self, display_width, display_height):
        # convert from ndc to viewport
        # ref: https://github.com/pyqtgraph/pyqtgraph/issues/422
        x = (1+self.viewport_ll[0]) * display_width/2
        y = (1+self.viewport_ll[1]) * display_height/2
        return (int(x), int(y), int((self.viewport_width/2)*display_width), int((self.viewport_height/2)*display_height))


    def serialize(self):
        return [
            self.pa,
            self.pb,
            self.pc,
            self.viewport_ll,
            self.viewport_width,
            self.viewport_height
        ]

    @classmethod
    def deserialize(cls, data):
        return SubScreen(*data)


class Screen:
    """
    Class representing the configuration of a single screen used in the display of stimuli.
    Parameters such as screen coordinates and the ID # are represented.
    """

    def __init__(self, subscreens=None, x_display=None, display_index=0, fullscreen=None, vsync=None,
                 square_size=None, square_loc=None, square_on_color=None, square_off_color=None, name=None, horizontal_flip=False, 
                 pa=(-0.15, 0.30, -0.15), pb=(+0.15, 0.30, -0.15), pc=(-0.15, 0.30, +0.15), use_egl=None,
                 subframes=1, subframe_channel_order=(0, 1, 2), refresh_rate=None, msaa_samples=0,
                 split_blended_pass=True):
        """
        :param subscreens: list of SubScreen objects (see above), if none are provided, one full-viewport subscreen will be produced using inputs pa, pb, pc
        :param x_display: $DISPLAY environment variable relevant if using Xorg as display server. If None, the default display is used.
        :param display_index: Index # of the screen (starts from 0). Follows what QT uses for screen numbering. 
        :param fullscreen: Boolean.  If True, display stimulus fullscreen (default).  Otherwise, display stimulus
        in a window.
        :param vsync: Boolean.  If True, lock the framerate to the redraw rate of the screen.
        :param square_size: (width, height) of photodiode synchronization square (NDC)
        :param square_loc: (x, y) Location of lower left corner of photodiode synchronization square (NDC)
        :param square_max_color: scales square color such that maximum value is set as indicated (0 - square_max_color)
        :param name: descriptive name to associate with this screen
        :param horizontal_flip: Boolean. Flip horizontal axis of image, for rear-projection devices
        :param use_egl: Boolean. If True, use EGL for rendering. If False (Default), use GLX. 
                                 If the display server is Wayland (Linux), EGL will be used regardless.
        :param msaa_samples: multisampling, 0 (default) for none. Rig-specific on purpose: it costs
            fill, and how much fill a rig can spare differs by more than an order of magnitude.

            What it buys is edge position quantized to 1/n of a pixel instead of a whole one -- so
            it is a finer staircase, not the continuous sub-pixel motion an analytic edge gives.
            Measured on a box drifting at 2 deg/s at 360 Hz, the largest single jump was 1.000 px
            at 0, 0.251 at 4x, 0.063 at 16x, against 0.024 px for a shape with an analytic edge.

            So it is not for shapes that already have one -- it leaves those alone to within 0.04%
            of their total light. It is for the geometry that can never have one: a box, a tower, a
            forest, an avatar. Anything built by merging shapes with ``add()`` is drawn in one call
            with one edge equation, so this is the only antialiasing it can get.

            Cost on a 16-tree forest at 1920x1080: 1.7% of a 360 Hz frame budget at 4x and 5.7% at
            16x on an RTX A4500; 89% at 4x on a software rasterizer, where it does not fit. Measure
            on the rig before raising it.
            **On a CurvedScreen this reaches much less than it looks.** It multisamples the
            framebuffer the frame is drawn into, and on the curved path the scene has already been
            rasterized into the cube faces, which are ordinary single-sample framebuffers. Only the
            warp pass -- one draw of the screen mesh -- is multisampled, so what it smooths is the
            screen's own silhouette rather than the stimuli on it. The same forest measured on a
            Quadro M2000 went from 0 partially-covered edge pixels to 1526 at 4x on a flat screen,
            and only 1506 to 1789 on the bowl -- which also starts far from zero because the warp
            samples the cube bilinearly while minifying, and so antialiases for free. Multisampling
            the cube faces as well was prototyped and rejected; see docs/design/analytic-edges.md.
        :param split_blended_pass: draw each frame in two passes so that blending stops depending on
            draw order. True by default; pass False to get back the single pass rigs ran before.

            Blending against a depth buffer is order-dependent: a fragment that is only partly
            covered still writes depth as though it were opaque, so whatever is behind it is
            rejected and it blends against the background instead. An opaque scene then renders
            differently depending on which stimulus was loaded first. Splitting the frame -- opaque
            fragments with depth writes on, then blended ones with depth writes off -- fixes that
            without sorting anything.

            This is not specific to analytic edges, though they made it universal: any stimulus with
            ``color`` alpha below 1 has always had it. Measured on a background and 100 overlapping
            dots, reversing the draw order changed 770 pixels in one pass and 5 in two. On the bowl
            the cube faces go from 7679 differing texels to 20 of seven million, and the warped
            image from 3984 pixels to 5. The remainder is where two blended fragments overlap each
            other, which needs per-sample storage to fix.

            The cost is small but not free. On this rig's Quadro M2000, a background and one spot:
            +0.07 ms flat, +0.49 ms curved, the curved figure paid once per cube face. That is under
            6% of a 120 Hz frame and no rig currently runs fast enough for it to bite -- it would be
            18% at 360 Hz, which nothing here does yet. Content with nothing to blend still pays for
            the second pass's vertex and rasterization work, since the discard happens in the
            fragment shader. The opt-out is here for a rig that outgrows that margin, not for one
            that has.
        """
        if subscreens is None:
            subscreens = [ SubScreen(pa=pa, pb=pb, pc=pc) ]
        if display_index is None:
            display_index = 0
        if fullscreen is None:
            fullscreen = True
        if vsync is None:
            vsync = True
        if square_size is None:
            square_size = (0.25, 0.25)
        if square_loc is None:
            square_loc = (-1, -1)
        if square_on_color is None:
            square_on_color = 1.0
        if square_off_color is None:
            square_off_color = 1.0
        square_on_color = max(min(square_on_color, 1.0), 0.0)
        square_off_color = max(min(square_off_color, 1.0), 0.0)
        if use_egl is None:
            use_egl = False
        if msaa_samples is None:
            msaa_samples = 0

        if name is None:
            name = 'Screen ' + str(display_index)

        # Temporal multiplexing: a DLPC350 in video-pattern mode can read the three 8-bit color
        # channels of one frame as three successive patterns, turning a 120 Hz video link into a
        # 360 Hz monochrome display. subframes=n makes the renderer draw n timepoints per frame and
        # write each to one channel; subframes=1 is ordinary rendering and changes nothing.
        #
        # Color is what pays for it. Each channel becomes a slice of time rather than a color, so
        # stimuli have to be grayscale.
        self.set_subframes(subframes, refresh_rate=refresh_rate,
                           channel_order=subframe_channel_order)

        # Save settings
        self.subscreens=subscreens
        self.x_display = x_display
        self.display_index = display_index
        self.fullscreen = fullscreen
        self.vsync = vsync
        self.square_size = square_size
        self.square_loc = square_loc
        self.square_on_color = square_on_color
        self.square_off_color = square_off_color
        self.msaa_samples = int(msaa_samples)
        self.split_blended_pass = bool(split_blended_pass)
        self.name = name
        self.horizontal_flip = horizontal_flip
        self.pa = pa
        self.pb = pb
        self.pc = pc
        self.use_egl = use_egl
        self.width = sqrt((pa[0]-pb[0])**2 + (pa[1]-pb[1])**2 + (pa[2]-pb[2])**2)
        self.height = sqrt((pa[0]-pc[0])**2 + (pa[1]-pc[1])**2 + (pa[2]-pc[2])**2)

    def set_subframes(self, subframes, refresh_rate=None, channel_order=None):
        """Change how many subframes a frame carries, validating as the constructor does.

        Shared with __init__ so a screen cannot be put into a state it could not have been built
        in. Called at run time it takes effect on the next frame: paintGL asks for the masks and
        the interval every frame and caches neither, so nothing is rebuilt.

        :param subframes: 1 for ordinary rendering, or 2-3 to read that many color channels as
            successive patterns. 3 is the usual case; 2 suits a rig with only two usable LEDs, or
            one trading rate for exposure per subframe.
        :param refresh_rate: video link rate in Hz. None means ask the display -- StimDisplay
            resolves it from the Qt screen at start-up, which is a number the system already knows
            and an experimenter should not have to repeat. Pass one only to override, and expect a
            warning if it disagrees with what the display reports.
        :param channel_order: which color channel carries each successive subframe. Always a full
            permutation of (0, 1, 2), even at 2 subframes -- the trailing entries just name the
            channels that go unused, which is what lets the order survive a change of `subframes`.
            None keeps the current order.
        """
        if subframes not in (1, 2, 3):
            raise ValueError(f'subframes must be 1, 2 or 3: a frame has three 8-bit color '
                             f'channels, so it can carry at most three timepoints. Got {subframes}')
        if channel_order is None:
            channel_order = getattr(self, 'subframe_channel_order', (0, 1, 2))
        if sorted(channel_order) != [0, 1, 2]:
            raise ValueError(f'subframe_channel_order must be a permutation of (0, 1, 2) -- which '
                             f'color channel carries each successive subframe -- not '
                             f'{channel_order}')

        self.subframes = int(subframes)
        self.subframe_channel_order = tuple(int(c) for c in channel_order)
        if refresh_rate is not None or not hasattr(self, 'refresh_rate'):
            self.refresh_rate = refresh_rate

    @property
    def subframe_interval(self):
        """Seconds between successive subframes, or 0 when not multiplexing.

        This is not "the frame divided by n". It is how far into the future subframe k will be
        photons, which is set by the projector's pattern exposure rather than by anything stimpack
        can see -- so it is taken from the video link rate, which the two agree on whenever the
        projector was configured with pattern_mode(fps=<link rate>).

        Deliberately not measured from stimpack's own frame times: that number jitters, has nothing
        to measure on the first frame, and doubles when a frame is dropped -- while the projector's
        exposure does not move at all.
        """
        if self.subframes <= 1:
            return 0.0
        if self.refresh_rate is None:
            raise ValueError(
                f'screen {self.name!r} carries {self.subframes} subframes but has no refresh_rate. '
                f'It is normally resolved from the display at start-up; set it explicitly if this '
                f'screen is used outside a StimDisplay.')
        return 1.0 / (self.refresh_rate * self.subframes)

    def subframe_color_masks(self):
        """One (r, g, b, a) write mask per subframe, in the order they are displayed.

        Which channel the projector shows first is set by its pattern LUT, not by us, so the order
        is configuration rather than a constant. Getting it wrong reorders three frames in time --
        motion still looks like motion, just wrong -- so it wants checking with a photodiode rather
        than by eye.

        Only the first `subframes` entries of the order are used; any channel past that is never
        written, and keeps whatever the frame was cleared to.
        """
        if self.subframes <= 1:
            return [(True, True, True, True)]
        return [tuple(i == channel for i in range(3)) + (True,)
                for channel in self.subframe_channel_order[:self.subframes]]

    def subframe_channel_names(self):
        """The same thing :meth:`subframe_color_masks` returns, named rather than positional.

        This is what a projector's pattern LUT is configured with, so a rig can set both halves
        from one permutation instead of writing it out twice and risking a transposition. Empty
        when not multiplexing, since there is then no per-channel ordering to preserve.
        """
        if self.subframes <= 1:
            return ()
        return channel_names(self.subframe_channel_order[:self.subframes])

    def serialize(self):
        # get all variables needed to reconstruct the screen object
        vars = ['x_display', 'display_index', 'fullscreen', 'vsync', 'square_size', 'square_loc', 
                'square_on_color', 'square_off_color', 'name', 'horizontal_flip', 'pa', 'pb', 'pc', 'use_egl',
                'subframes', 'subframe_channel_order', 'refresh_rate', 'msaa_samples',
                'split_blended_pass']
        data = {var: getattr(self, var) for var in vars}

        # special handling for tri_list since it could contain numpy values
        data['subscreens'] = [sub.serialize() for sub in self.subscreens]

        return data

    @classmethod
    def deserialize(cls, data):
        # start building up the argument list to instantiate a screen
        kwargs = data.copy()

        # A curved screen serializes through this same path, since launch_screen and the screen
        # subprocess only know about Screen. Dispatch on the tag rather than making every caller
        # know which kind it has.
        if kwargs.pop('kind', None) == 'curved':
            from stimpack.visual_stim.curved_screen import CurvedScreen
            return CurvedScreen.deserialize_curved(kwargs)

        # do some post-processing as necessary
        kwargs['subscreens'] = [SubScreen.deserialize(sub) for sub in kwargs['subscreens']]

        return Screen(**kwargs)

def main():
    Screen()

if __name__ == '__main__':
    main()
