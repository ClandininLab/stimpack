# Orienting the cube map to the screen

*How many cube faces a curved screen needs is a function of where the cube is pointed, and the
answer is closed-form rather than something to search for. Recorded because the derivation is worth
more than the optimisation: measured, the optimisation is not currently worth building.*

## The question

`CubeMapRenderer` renders only the faces the screen mesh samples (`faces_for_mesh`), because a face
nothing reads still costs a full scene draw. The cube is currently **axis-aligned to the rig**, and
nothing chooses its orientation.

But the face count depends on that orientation. A screen covering one patch of the sphere may
straddle five faces where it is, and three if the cube is turned. Each face avoided is a scene draw
saved every frame.

## The structure

Two observations reduce this from a search to a formula.

**A screen that is a spherical cap has a symmetry.** `SphericalSurface` with a single
`elevation_range` about a pole is rotationally symmetric about that pole, so only the *direction of
the cap's axis relative to the cube* matters. That is **two degrees of freedom, not three** — roll
about the cap's own axis cannot change anything. Searching yaw/pitch/roll wastes a dimension, and
any answer that reports a roll angle is reporting noise.

**A face's region is an intersection of half-spaces.** Cube maps sample by dominant axis, so face
`+Z` covers `{d : d_z >= |d_x| and d_z >= |d_y|}` — a spherical square bounded by four planes
through the origin, with corners at `(±1, ±1, 1)/√3`.

Together: **a cap of half-angle α about axis c touches face f if and only if the angular distance
from c to face f's region is less than α.**

That distance is elementary — zero if `c` is inside the region, otherwise the smaller of the
distance to each bounding edge (where the perpendicular foot lands on the edge) and to each corner.

## The answer

Only three alignments matter, by symmetry. All three are verified against the distance computation
above, and the whole predictor is verified against `faces_for_directions` on a real rig geometry.

| cap axis aligned to | distances to the six regions | faces needed |
|---|---|---|
| **a face centre** `(0,0,1)` | 0, and 45° ×4, and 125.26° | 1 if α ≤ 45°; **5** if 45° < α ≤ 125.26° |
| **an edge midpoint** `(0,1,1)` | 0 ×2, and 35.26° ×2, and 90° ×2 | 2 if α ≤ 35.26°; **4** if 35.26° < α ≤ 90° |
| **a corner** `(1,1,1)` | 0 ×3, and 70.53° ×3 | **3** if α < 70.53°; 6 above |

The three thresholds are exact:

```
45°       = the face boundary, where z = |x|
35.26°    = arccos(2/√6)     corner (1,1,1)/√3 seen from edge midpoint (0,1,1)/√2
70.53°    = arccos(1/3)      corner (-1,1,1)/√3 seen from corner (1,1,1)/√3
125.26°   = arccos(-1/√3)    opposite face's nearest corner seen from a face axis
```

**The corner threshold is the useful one.** A cap on a cube corner touches only three faces so long
as its half-angle is under `arccos(1/3) = 70.53°`. That is a surprisingly generous bound — nearly a
110° cone fits in three faces if the cube is turned to meet it.

**Margin matters as much as the count.** The margin is the distance to the nearest *excluded*
region minus α, and it says how far the geometry can drift before a face reappears:

| cap half-angle | corner-aligned | margin | edge-aligned | margin |
|---|---|---|---|---|
| 60° | 3 | 10.5° | 4 | 30.0° |
| 68° | 3 | 2.5° | 4 | 22.0° |
| 70° | 3 | **0.5°** | 4 | 20.0° |
| 72° | 6 | — | 4 | 18.0° |

A cap close to 70.53° gets three faces on a knife edge; falling off it costs *three* faces at once,
not one. Edge alignment is the robust choice, and the one to prefer unless the cap is comfortably
under about 65°.

## Why this is not built

Measured on the BrukerJr flymax bowl (12,600-triangle mesh, 1536² faces, Mesa Intel):

```
scene                     tri/face   3 faces      4       5       6   5->4 saves
background only                  0     1.95    1.58    2.01    2.28      0.43 ms
+ Forest, 30 towers            960     1.80    2.20    2.48    2.73      0.28 ms
+ Forest, 150 towers          4800     2.75    3.40    3.68    3.98      0.28 ms
+ Forest, 600 towers         19200     7.28    8.67    9.09    9.58      0.41 ms
                                                          120 Hz budget = 8.33 ms
```

Turning the cube saves **0.28–0.41 ms** at every scene complexity tested. That is 3–5% of a frame
budget with 4× headroom in ordinary use. And at the one complexity that does exceed the budget —
600 towers, 9.09 ms — going from five faces to four still leaves it over; only the knife-edge
three-face alignment clears it.

Cube resolution is the lever that works, by an order of magnitude:

```
600-tower Forest, 5 faces
  1536²   9.67 ms   over budget    17.1 px/deg supplied
  1024²   4.64 ms   ok             11.4
   768²   3.24 ms   ok              8.5
```

Halving the face size halves the cost, against optics delivering about 12 px/deg — so 1024 gives up
almost nothing real. Rotation buys 4%; resolution buys 52%.

## What would change the verdict

- **A screen whose cap sits well under 65°**, where corner alignment gives three faces with real
  margin. Two faces saved rather than one, and safely.
- **A much heavier per-face cost than resolution can absorb** — a stimulus whose geometry, not fill,
  dominates. Face count multiplies geometry directly; resolution does not touch it.
- **A rig where the cube pass is measured to be the frame-rate limit.** It has not been, on any rig.
  `report_frame_count` over a known interval is the check.

## Implementation sketch

Four pieces, none large:

1. **`CubeMapRenderer.__init__` takes an orientation.** `face_view_projections` already accepts one
   — yaw about z, pitch about x, roll about y, matching `get_perspective` — so the scene can be
   rendered into a turned cube today.
2. **The mesh directions must be rotated into cube space before sampling.** The mesh is static, so
   rotate `mesh.directions` once when the vertex buffer is built rather than per fragment.
3. **`faces_for_mesh` operates in the rotated frame.** It already takes directions, so it needs the
   rotated ones.
4. **Choosing the orientation.** Not a search: take the mesh's cap axis, and rotate the cube so that
   axis meets a corner (if α < 65°) or an edge midpoint (otherwise). The tables above say which and
   what margin results.

The trap to avoid is the one that made the first attempt at this wrong: the subject's heading is
*already* applied by rotating each face's axes, so cube space stays aligned with the rig and the
mesh's fixed directions can sample it. A screen-orientation rotation composes with that, and getting
the order wrong gives a picture that is plausible and rotated — hard to spot by eye, and exactly the
failure `face_view_projections` warns about in its own docstring.

## Reference implementation of the predictor

Exact, and validated against `faces_for_directions` on real rig geometry:

```python
def region(face):
    """(inward plane normals, corners) of a cube face's spherical square, GL face order."""
    ax, sign = [(0, +1), (0, -1), (1, +1), (1, -1), (2, +1), (2, -1)][face]
    a = np.zeros(3); a[ax] = sign
    others = [i for i in range(3) if i != ax]
    normals = [(lambda n: n / np.linalg.norm(n))(np.where(np.arange(3) == i, -s, a))
               for i, s in itertools.product(others, (+1, -1))]
    corners = []
    for s1, s2 in itertools.product((+1, -1), repeat=2):
        v = a.copy(); v[others[0]] = s1; v[others[1]] = s2
        corners.append(v / np.linalg.norm(v))
    return np.array(normals), np.array(corners)


def distance_to_region(c, face):
    """Angular distance from unit vector c to a face's region; 0 if inside."""
    normals, corners = region(face)
    if np.all(normals @ c >= -1e-12):
        return 0.0
    best = np.inf
    for n in normals:                       # perpendicular foot on each bounding edge
        p = c - (c @ n) * n
        if np.linalg.norm(p) > 1e-12:
            p /= np.linalg.norm(p)
            if np.all(normals @ p >= -1e-9):
                best = min(best, np.arccos(np.clip(c @ p, -1, 1)))
    for v in corners:
        best = min(best, np.arccos(np.clip(c @ v, -1, 1)))
    return best


def faces_for_cap(axis, half_angle):
    """The faces a cap of this half-angle about `axis` needs. Exact."""
    return tuple(f for f in range(6) if distance_to_region(axis, f) < half_angle)
```

---

*Measurements: BrukerJr flymax bowl, `CAP_HALF_ANGLE = 70`, 1536² cube faces, Mesa Intel RPL-S.
The rig itself runs a Quadro M2000, where the absolute times will differ but the ratios should not.*
