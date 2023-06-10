from math import radians
from time import time
from PIL import Image

from stimpack.visual_stim import GenPerspective, GlCube, CaveSystem, rel_path
from common import run_qt, run_headless, get_img_err

def get_perspective(theta, phi):
    # nominal position
    perspective = GenPerspective(pa=(+1, -1, -1), pb=(+1, +1, -1), pc=(+1, -1, 1), pe=(+5, 0, 0))

    # rotate screen and eye position
    return perspective.roty(-radians(phi)).rotz(radians(theta))

def register_cave(display, omega=0):
    # create the CAVE system with various perspectives
    cave = CaveSystem()
    cave.add_subscreen((0, 256, 256, 256), get_perspective(theta=0, phi=0))
    cave.add_subscreen((256, 256, 256, 256), get_perspective(theta=45, phi=0))
    cave.add_subscreen((256, 0, 256, 256), get_perspective(theta=45, phi=45))

    # add cube rendering to the render action list
    def_alpha = 1
    colors = {'+x': (0, 0, 1, def_alpha), '-x': (0, 1, 0, def_alpha),
              '+y': (1, 0, 0, def_alpha), '-y': (0, 1, 1, def_alpha),
              '+z': (1, 1, 0, def_alpha), '-z':(1, 0, 1, def_alpha)}
    display.render_objs.append(cave)
    t0 = time()
    display.render_actions.append(lambda: cave.render(GlCube(colors=colors).rotz(radians(omega*(time()-t0)))))

def test_color_cube(max_err=1000):
    # render image
    obs = run_headless(register_cave)

    # load image for comparison
    ref = Image.open(rel_path('tests', 'data', 'color_cube.png'))

    # compute error
    error = get_img_err(obs, ref)
    print(error)

    # check that error is OK
    assert error <= max_err, f'Error {error} exceeds limit of {max_err}.'

if __name__ == '__main__':
    run_qt(lambda display: register_cave(display, omega=45))
    #test_color_cube()
