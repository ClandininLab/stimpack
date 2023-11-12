from math import sin, cos, radians

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

    def __init__(self, pa=(-0.15, 0.30, -0.15), pb=(+0.15, 0.30, -0.15), pc=(-0.15, 0.30, +0.15), viewport_ll=(-1,-1), viewport_width=2, viewport_height=2):
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

    def __init__(self, subscreens=None, server_number=None, id=None, fullscreen=None, vsync=None,
                 square_size=None, square_loc=None, square_on_color=None, square_off_color=None, name=None, horizontal_flip=False, 
                 pa=(-0.15, 0.30, -0.15), pb=(+0.15, 0.30, -0.15), pc=(-0.15, 0.30, +0.15)):
        """
        :param subscreens: list of SubScreen objects (see above), if none are provided, one full-viewport subscreen will be produced using inputs pa, pb, pc
        :param server_number: ID # of the X server
        :param id: ID # of the screen
        :param fullscreen: Boolean.  If True, display stimulus fullscreen (default).  Otherwise, display stimulus
        in a window.
        :param vsync: Boolean.  If True, lock the framerate to the redraw rate of the screen.
        :param square_size: (width, height) of photodiode synchronization square (NDC)
        :param square_loc: (x, y) Location of lower left corner of photodiode synchronization square (NDC)
        :param square_max_color: scales square color such that maximum value is set as indicated (0 - square_max_color)
        :param name: descriptive name to associate with this screen
        :param horizontal_flip: Boolean. Flip horizontal axis of image, for rear-projection devices

        """
        if subscreens is None:
            subscreens = [ SubScreen(pa=pa, pb=pb, pc=pc) ]
        if server_number is None: # server_number and id of -1 means use default X server. See stim_server.launch_screen
            server_number = -1
        if id is None:
            id = -1
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

        if name is None:
            name = 'Screen' + str(id)

        # Save settings
        self.subscreens=subscreens
        self.id = id
        self.server_number = server_number
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

    def serialize(self):
        # get all variables needed to reconstruct the screen object
        vars = ['id', 'server_number', 'fullscreen', 'vsync', 'square_size', 'square_loc', 
                'square_on_color', 'square_off_color', 'name', 'horizontal_flip', 'pa', 'pb', 'pc']
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
    screen = Screen(offset=(0.0, +0.3, 0.0), rotation=0)

if __name__ == '__main__':
    main()
