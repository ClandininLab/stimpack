import numpy as np
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import matplotlib.pyplot as plt
from collections.abc import Iterable

from stimpack.visual_stim.util import normalize

COLOR_LIST = ['b', 'g', 'r', 'c', 'm', 'y']


def draw_screens(screens):
    if not isinstance(screens, Iterable):
        screens = [screens]

    fig = plt.figure()
    ax = Axes3D(fig)

    for screen in screens:
        for s_ind, subscreen in enumerate(screen.subscreens):
            # grab just the xyz coordinates of each point in the triangle
            pa = np.array(subscreen.pa)
            pb = np.array(subscreen.pb)
            pc = np.array(subscreen.pc)

            # draw the primary screen triangle
            tri_draw(pa, pb, pc, ax=ax, color=COLOR_LIST[screen.id % len(COLOR_LIST)])

            # draw the screen normal, should point TOWARDS the viewer
            vr = normalize(pb - pa)
            vu = normalize(pc - pa)
            vn = normalize(np.cross(vr, vu))
            ax.quiver(pa[0], pa[1], pa[2], vn[0], vn[1], vn[2], length=0.1, normalize=True, color=COLOR_LIST[screen.id % len(COLOR_LIST)])

    # draw fly in the center
    ax.scatter(0, 0, 0, c='g')
    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    lim = 0.25
    ax.set_xlim([-lim, +lim])
    ax.set_ylim([-lim, +lim])
    ax.set_zlim([-lim, +lim])

    plt.show()


def tri_draw(p1, p2, p3, ax, color=None, alpha=0.8):
    coll = Poly3DCollection([[p1, p2, p3]])
    coll.set_alpha(alpha)

    if color is not None:
        coll.set_facecolor(color)

    ax.add_collection3d(coll)
