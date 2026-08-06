"""
Describing a physical display to stimpack.

A :class:`Screen` is one display device; a :class:`SubScreen` is a rectangular region of it,
given by its three physical corners in **metres** (``pa`` lower-left, ``pb`` lower-right, ``pc``
upper-left) plus a viewport within the display. Those corners are what perspective correction is
computed from, so measuring them accurately is what makes the geometry on screen correct.

Several subscreens may share one display, and several screens may make up a rig.
"""
from math import sqrt

# The colour channels of a frame, in index order.
#
# Under subframe multiplexing the same permutation has to be told to two things in two vocabularies:
# the renderer works in indices, because a colour write mask is positional, while a projector's
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
                 subframes=1, subframe_channel_order=(0, 1, 2), refresh_rate=None):
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

        if name is None:
            name = 'Screen ' + str(display_index)

        # Temporal multiplexing: a DLPC350 in video-pattern mode can read the three 8-bit colour
        # channels of one frame as three successive patterns, turning a 120 Hz video link into a
        # 360 Hz monochrome display. subframes=n makes the renderer draw n timepoints per frame and
        # write each to one channel; subframes=1 is ordinary rendering and changes nothing.
        #
        # Colour is what pays for it. Each channel becomes a slice of time rather than a colour, so
        # stimuli have to be greyscale.
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

        :param subframes: 1 for ordinary rendering, or 2-3 to read that many colour channels as
            successive patterns. 3 is the usual case; 2 suits a rig with only two usable LEDs, or
            one trading rate for exposure per subframe.
        :param refresh_rate: video link rate in Hz. None means ask the display -- StimDisplay
            resolves it from the Qt screen at start-up, which is a number the system already knows
            and an experimenter should not have to repeat. Pass one only to override, and expect a
            warning if it disagrees with what the display reports.
        :param channel_order: which colour channel carries each successive subframe. Always a full
            permutation of (0, 1, 2), even at 2 subframes -- the trailing entries just name the
            channels that go unused, which is what lets the order survive a change of `subframes`.
            None keeps the current order.
        """
        if subframes not in (1, 2, 3):
            raise ValueError(f'subframes must be 1, 2 or 3: a frame has three 8-bit colour '
                             f'channels, so it can carry at most three timepoints. Got {subframes}')
        if channel_order is None:
            channel_order = getattr(self, 'subframe_channel_order', (0, 1, 2))
        if sorted(channel_order) != [0, 1, 2]:
            raise ValueError(f'subframe_channel_order must be a permutation of (0, 1, 2) -- which '
                             f'colour channel carries each successive subframe -- not '
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
                'subframes', 'subframe_channel_order', 'refresh_rate']
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
