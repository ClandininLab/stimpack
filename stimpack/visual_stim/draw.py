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
            tri_draw(pa, pb, pc, ax=ax, color=COLOR_LIST[screen.display_index % len(COLOR_LIST)])

            # draw the screen normal, should point TOWARDS the viewer
            vr = normalize(pb - pa)
            vu = normalize(pc - pa)
            vn = normalize(np.cross(vr, vu))
            ax.quiver(pa[0], pa[1], pa[2], vn[0], vn[1], vn[2], length=0.1, normalize=True, color=COLOR_LIST[screen.display_index % len(COLOR_LIST)])

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


def draw_curved_screen(mesh, surface=None, projector=None, show=True, save_to=None):
    """Look at a curved screen's geometry before rendering anything through it.

    Two views, because the two ways this goes wrong look different:

      left   the screen in the rig, coloured by azimuth, with the subject at the origin. Wrong
             surface dimensions or extents show up here.
      right  the same mesh in projector coordinates, with the projector image as a dashed box.
             A wrong projector pose, throw ratio or aspect shows up here -- as a mesh that spills
             far outside the box, or huddles in a corner of it.

    :param mesh: a ScreenMesh from build_screen_mesh
    :param save_to: path to write the figure to instead of (or as well as) showing it
    """
    fig = plt.figure(figsize=(13, 6))

    ax = fig.add_subplot(1, 2, 1, projection='3d')
    # Colour by whether the projector lights it. On a rig that covers its screen only partly -- a
    # projector to one side of a bowl -- this is the thing worth looking at.
    tri_lit = mesh.lit[mesh.triangles].all(axis=1).astype(float)
    ax.plot_trisurf(mesh.positions[:, 0], mesh.positions[:, 1], mesh.positions[:, 2],
                    triangles=mesh.triangles, cmap='RdYlGn', array=tri_lit,
                    vmin=0, vmax=1, edgecolor='none', alpha=0.9)
    ax.scatter(0, 0, 0, c='g', s=40, label='subject')
    if projector is not None:
        ax.scatter(*projector.position, c='r', s=40, marker='^', label='projector')
    ax.set_xlabel('X (m)'); ax.set_ylabel('Y (m)'); ax.set_zlabel('Z (m)')
    ax.set_title(f'screen in the rig  ({mesh.n_triangles} triangles; green = lit)')
    ax.legend(loc='upper left')

    ax2 = fig.add_subplot(1, 2, 2)
    finite = np.isfinite(mesh.ndc).all(axis=1)
    keep = finite[mesh.triangles].all(axis=1)
    ax2.triplot(mesh.ndc[:, 0], mesh.ndc[:, 1], mesh.triangles[keep], lw=0.4, color='0.3')
    ax2.add_patch(plt.Rectangle((-1, -1), 2, 2, fill=False, ls='--', lw=1.5, color='r'))
    ax2.set_aspect('equal')
    ax2.set_xlabel('projector NDC x'); ax2.set_ylabel('projector NDC y')
    coverage = mesh.coverage()
    subtitle = f"projector view  ({coverage['fraction']:.0%} of the screen lit"
    if coverage['azimuth'] is not None:
        subtitle += (f"; az {coverage['azimuth'][0]:+.0f} to {coverage['azimuth'][1]:+.0f}"
                     f", el {coverage['elevation'][0]:+.0f} to {coverage['elevation'][1]:+.0f})")
    else:
        subtitle += ')'
    ax2.set_title(subtitle)

    if surface is not None:
        fig.suptitle(type(surface).__name__)
    fig.tight_layout()

    if save_to is not None:
        fig.savefig(save_to, dpi=110)
    if show:
        plt.show()
    return fig
