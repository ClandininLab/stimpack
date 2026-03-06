"""
Generalized perspective projection

See:
https://csc.lsu.edu/~kooima/articles/genperspective/index.html
"""

import numpy as np

from stimpack.visual_stim.util import normalize, rotx, roty, rotz


class GenPerspective:
    def __init__(self, pa, pb, pc, pe=(0, 0, 0), near=0.0001, far=1000, subject_xyz=(0, 0, 0), horizontal_flip=False):
        # save settings
        self.pa = pa
        self.pb = pb
        self.pc = pc
        self.pe = pe
        self.subject_xyz = subject_xyz
        self.near = near
        self.far = far
        self.horizontal_flip = horizontal_flip # for rear-projection display

    @property
    def matrix(self):
        # format vectors as numpy arrays
        pa = np.array(self.pa, dtype=float)
        pb = np.array(self.pb, dtype=float)
        pc = np.array(self.pc, dtype=float)
        pe = np.array(self.pe, dtype=float)
        subject_xyz = np.array(self.subject_xyz, dtype=float)

        # make aliases for "near" and "far" so that the code is easier to read
        n = self.near
        f = self.far

        # compute vector normals
        vr = normalize(pb - pa)
        vu = normalize(pc - pa)
        vn = normalize(np.cross(vr, vu))

        # compute relative position of screen
        va = pa - pe
        vb = pb - pe
        vc = pc - pe

        # compute distance parameters
        d = -np.dot(vn, va)
        b = np.dot(vu, va) * n / d
        t = np.dot(vu, vc) * n / d
        if self.horizontal_flip: # flip l and r distance parameters
            r = np.dot(vr, va) * n / d
            l = np.dot(vr, vb) * n / d
        else:
            l = np.dot(vr, va) * n / d
            r = np.dot(vr, vb) * n / d


        # create projection matrices
        P =  np.array([[2*n/(r-l),         0,  (r+l)/(r-l),            0],
                       [        0, 2*n/(t-b),  (t+b)/(t-b),            0],
                       [        0,         0, -(f+n)/(f-n), -2*f*n/(f-n)],
                       [        0,         0,           -1,            0]], dtype=float)
        M = np.array([[vr[0], vu[0], vn[0], 0],
                      [vr[1], vu[1], vn[1], 0],
                      [vr[2], vu[2], vn[2], 0],
                      [    0,     0,     0, 1]], dtype=float)
        T = np.array([[1, 0, 0, -subject_xyz[0]],
                      [0, 1, 0, -subject_xyz[1]],
                      [0, 0, 1, -subject_xyz[2]],
                      [0, 0, 0,      1]], dtype=float)

        return P.dot((M.T).dot(T)).astype('f4').tobytes(order='F')

    def rotx(self, th):
        return GenPerspective(pa=rotx(self.pa, th), pb=rotx(self.pb, th), pc=rotx(self.pc, th),
                              pe=rotx(self.pe, th), near=self.near, far=self.far, subject_xyz=self.subject_xyz, horizontal_flip=self.horizontal_flip)

    def roty(self, th):
        return GenPerspective(pa=roty(self.pa, th), pb=roty(self.pb, th), pc=roty(self.pc, th),
                              pe=roty(self.pe, th), near=self.near, far=self.far, subject_xyz=self.subject_xyz, horizontal_flip=self.horizontal_flip)

    def rotz(self, th):
        return GenPerspective(pa=rotz(self.pa, th), pb=rotz(self.pb, th), pc=rotz(self.pc, th),
                              pe=rotz(self.pe, th), near=self.near, far=self.far, subject_xyz=self.subject_xyz, horizontal_flip=self.horizontal_flip)
