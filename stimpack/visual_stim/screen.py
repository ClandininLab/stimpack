"""
Describing a physical display to stimpack.

A :class:`Screen` is one display device; a :class:`SubScreen` is a rectangular region of it,
given by its three physical corners in **metres** (``pa`` lower-left, ``pb`` lower-right, ``pc``
upper-left) plus a viewport within the display. Those corners are what perspective correction is
computed from, so measuring them accurately is what makes the geometry on screen correct.

Several subscreens may share one display, and several screens may make up a rig.
"""
from math import sqrt

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
        # 360 Hz monochrome display. subframes=3 makes the renderer draw three timepoints per frame
        # and write each to one channel; subframes=1 is ordinary rendering and changes nothing.
        #
        # Colour is what pays for it. Each channel becomes a slice of time rather than a colour, so
        # stimuli have to be greyscale.
        if subframes not in (1, 3):
            raise ValueError(f'subframes must be 1 or 3 (the three 8-bit channels of a frame), '
                             f'not {subframes}')
        if subframes > 1 and refresh_rate is None:
            raise ValueError('subframes > 1 needs refresh_rate (the video link rate, e.g. 120), '
                             'to know how far apart in time the subframes are')
        if sorted(subframe_channel_order) != [0, 1, 2]:
            raise ValueError(f'subframe_channel_order must be a permutation of (0, 1, 2) -- which '
                             f'colour channel carries each successive subframe -- not '
                             f'{subframe_channel_order}')

        self.subframes = int(subframes)
        self.subframe_channel_order = tuple(int(c) for c in subframe_channel_order)
        self.refresh_rate = refresh_rate

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

    @property
    def subframe_interval(self):
        """Seconds between successive subframes, or 0 when not multiplexing."""
        if self.subframes <= 1:
            return 0.0
        return 1.0 / (self.refresh_rate * self.subframes)

    def subframe_color_masks(self):
        """One (r, g, b, a) write mask per subframe, in the order they are displayed.

        Which channel the projector shows first is set by its pattern LUT, not by us, so the order
        is configuration rather than a constant. Getting it wrong reorders three frames in time --
        motion still looks like motion, just wrong -- so it wants checking with a photodiode rather
        than by eye.
        """
        if self.subframes <= 1:
            return [(True, True, True, True)]
        return [tuple(i == channel for i in range(3)) + (True,)
                for channel in self.subframe_channel_order[:self.subframes]]

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

        # do some post-processing as necessary
        kwargs['subscreens'] = [SubScreen.deserialize(sub) for sub in kwargs['subscreens']]

        return Screen(**kwargs)

def main():
    Screen()

if __name__ == '__main__':
    main()
