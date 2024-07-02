from math import sin, cos, radians, sqrt
import numpy as np

class ScreenPoint:
    def __init__(self, ndc, cart):
        self.ndc = ndc  # Normalized Device Coordinates (x, y)
        self.cart = cart  # Cartesian coordinates (x, y, z)

    def serialize(self):
        return [
            self.ndc,
            self.cart
        ]

    @classmethod
    def deserialize(cls, data):
        return ScreenPoint(
            ndc=data[0],
            cart=data[1]
        )

    def __str__(self):
        return f'({str(self.ndc)}, {str(self.cart)})'

class TriSubScreen:
    def __init__(self, p1: ScreenPoint, p2: ScreenPoint, p3: ScreenPoint):
        self.p1 = p1
        self.p2 = p2
        self.p3 = p3

        # Calculate the bounding box in NDC
        ndc_x = [p1.ndc[0], p2.ndc[0], p3.ndc[0]]
        ndc_y = [p1.ndc[1], p2.ndc[1], p3.ndc[1]]

        ndc_x_min = min(ndc_x)
        ndc_x_max = max(ndc_x)
        ndc_y_min = min(ndc_y)
        ndc_y_max = max(ndc_y)

        ndc_points = np.array([
            [p1.ndc[0], p1.ndc[1], 1],
            [p2.ndc[0], p2.ndc[1], 1],
            [p3.ndc[0], p3.ndc[1], 1]
        ])
        cart_points = np.array([
            [p1.cart[0], p1.cart[1], p1.cart[2]],
            [p2.cart[0], p2.cart[1], p2.cart[2]],
            [p3.cart[0], p3.cart[1], p3.cart[2]]
        ])
        ndc_to_cart_transfom = np.linalg.solve(ndc_points, cart_points)

        self.viewport_ll = (ndc_x_min, ndc_y_min)  # Lower-left corner in NDC
        self.viewport_width = ndc_x_max - ndc_x_min
        self.viewport_height = ndc_y_max - ndc_y_min

        # Bounding box. Same geometry as that of rectangular SubScreen
        self.pa = ScreenPoint((ndc_x_min, ndc_y_min), np.dot([ndc_x_min, ndc_y_min, 1], ndc_to_cart_transfom))
        self.pb = ScreenPoint((ndc_x_max, ndc_y_min), np.dot([ndc_x_max, ndc_y_min, 1], ndc_to_cart_transfom))
        self.pc = ScreenPoint((ndc_x_min, ndc_y_max), np.dot([ndc_x_min, ndc_y_max, 1], ndc_to_cart_transfom))

        # Calculate p1, p2, p3 NDC coordinates relative to the viewport
        p1_rel_ndc = (2 * (p1.ndc[0] - ndc_x_min) / self.viewport_width - 1, 2 * (p1.ndc[1] - ndc_y_min) / self.viewport_height - 1)
        p2_rel_ndc = (2 * (p2.ndc[0] - ndc_x_min) / self.viewport_width - 1, 2 * (p2.ndc[1] - ndc_y_min) / self.viewport_height - 1)
        p3_rel_ndc = (2 * (p3.ndc[0] - ndc_x_min) / self.viewport_width - 1, 2 * (p3.ndc[1] - ndc_y_min) / self.viewport_height - 1)

        self.p1_rel = ScreenPoint(p1_rel_ndc, p1.cart)
        self.p2_rel = ScreenPoint(p2_rel_ndc, p2.cart)
        self.p3_rel = ScreenPoint(p3_rel_ndc, p3.cart)

        print((self.pa.cart, self.pb.cart, self.pc.cart))

    def get_cartesian_coords(self):
        return (self.p1.cart, self.p2.cart, self.p3.cart)
    
    def get_ndc_coords(self):
        return (self.p1.ndc, self.p2.ndc, self.p3.ndc)

    def get_relative_cartesian_coords(self):
        return (self.p1_rel.cart, self.p2_rel.cart, self.p3_rel.cart)
    
    def get_relative_ndc_coords(self):
        return (self.p1_rel.ndc, self.p2_rel.ndc, self.p3_rel.ndc)
    
    def get_bounding_box_cart_coords(self):
        return (self.pa.cart, self.pb.cart, self.pc.cart)
    
    def get_bounding_box_ndc_coords(self):
        return (self.pa.ndc, self.pb.ndc, self.pc.ndc)

    def get_viewport(self, display_width, display_height):
        # convert from ndc to viewport
        # ref: https://github.com/pyqtgraph/pyqtgraph/issues/422
        x = (1+self.viewport_ll[0]) * display_width/2
        y = (1+self.viewport_ll[1]) * display_height/2
        viewport =  (int(x), int(y), int((self.viewport_width/2)*display_width), int((self.viewport_height/2)*display_height))
        return viewport

    def serialize(self):
        return [
            self.p1.serialize(),
            self.p2.serialize(),
            self.p3.serialize()
        ]

    @classmethod
    def deserialize(cls, data):
        return TriSubScreen(
            p1=ScreenPoint.deserialize(data[0]),
            p2=ScreenPoint.deserialize(data[1]),
            p3=ScreenPoint.deserialize(data[2])
        )

    def __str__(self):
        return f'({str(self.p1)}, {str(self.p2)}, {str(self.p3)})'
    
    # @classmethod
    # def quad_to_tri_list(cls, p1, p2, p3, p4):
    #     # convert points to ScreenPoints if necessary
    #     p1 = p1 if isinstance(p1, ScreenPoint) else ScreenPoint.deserialize(p1)
    #     p2 = p2 if isinstance(p2, ScreenPoint) else ScreenPoint.deserialize(p2)
    #     p3 = p3 if isinstance(p3, ScreenPoint) else ScreenPoint.deserialize(p3)
    #     p4 = p4 if isinstance(p4, ScreenPoint) else ScreenPoint.deserialize(p4)

    #     # create a mesh consisting of two triangles
    #     return [ScreenTriangle(p1, p2, p4), ScreenTriangle(p2, p3, p4)]

class SubScreen:
    """
    Rectangular SubScreen of a Screen object
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

    def __init__(self, pa=(-0.15, 0.30, -0.15), pb=(+0.15, 0.30, -0.15), pc=(-0.15, 0.30, +0.15), 
                 viewport_ll=(-1,-1), viewport_width=2, viewport_height=2):
        """
        :param pa: meters (x,y,z)
        :param pb: meters (x,y,z)
        :param pc: meters (x,y,z)
        :param viewport_ll: (x, y) NDC coordinates of lower-left corner of viewport for SubScreen [-1, +1]
        :param viewport_width: NDC width of viewport [0, 2]
        :param viewport_height: NDC height of viewport [0, 2]
        :param tri_list: list of triangular patches defining the subscreen geometry.  this is a list of ScreenTriangles.
                if the triangle list is not specified, then one is constructed automatically using pa, pb, and pc.
                if using tri_list, the pa, pb, and pc values are ignored. 
        """
        self.pa = pa
        self.pb = pb
        self.pc = pc

        self.viewport_ll = viewport_ll
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

    def get_cartesian_coords(self):
        return (self.pa, self.pb, self.pc)

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
        self.width = sqrt((pa[0]-pb[0])**2 + (pa[1]-pb[1])**2 + (pa[2]-pb[2])**2)
        self.height = sqrt((pa[0]-pc[0])**2 + (pa[1]-pc[1])**2 + (pa[2]-pc[2])**2)

    def serialize(self):
        # get all variables needed to reconstruct the screen object
        vars = ['id', 'server_number', 'fullscreen', 'vsync', 'square_size', 'square_loc', 
                'square_on_color', 'square_off_color', 'name', 'horizontal_flip', 'pa', 'pb', 'pc']
        data = {var: getattr(self, var) for var in vars}

        # special handling for tri_list since it could contain numpy values
        data['subscreens'] = [(type(sub).__name__, sub.serialize()) for sub in self.subscreens]

        return data

    @classmethod
    def deserialize(cls, data):
        # start building up the argument list to instantiate a screen
        kwargs = data.copy()

        # do some post-processing as necessary
        kwargs['subscreens'] = []
        for sub_class_name, subscreen in data['subscreens']:
            if sub_class_name == 'SubScreen':
                kwargs['subscreens'].append(SubScreen.deserialize(subscreen))
            elif sub_class_name == 'TriSubScreen':
                kwargs['subscreens'].append(TriSubScreen.deserialize(subscreen))
            else:
                raise ValueError(f'Unknown subscreen class name: {sub_class_name}')

        return Screen(**kwargs)

def main():
    screen = Screen(offset=(0.0, +0.3, 0.0), rotation=0)

if __name__ == '__main__':
    main()
