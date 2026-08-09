# Orienting the cube map to the screen

*How many cube faces a curved screen needs is a function of where the cube is pointed, and the
answer is closed-form rather than something to search for.*

**Built, and on by default.** `cube_orientation='auto'`; pass `None` for the axis-aligned cube
every rig ran before. The derivation below is the whole of the design; what changed since it was
first written is the measurement, twice -- see below, and do not trust a figure on this page that
is not dated to the current code.

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

## What it measures, and how two earlier answers went wrong

**Current numbers.** BrukerJr flymax bowl, 65-degree cap, five faces to three, on the rig's own
Quadro M2000. Medians of three runs, each **interleaving the two conditions frame by frame** so
thermal drift hits both equally:

| scene | axis-aligned | auto | saving |
|---|---|---|---|
| annuli (2.7k vertices) | 1.15 ms | 1.07 ms | −7% |
| 50 towers | 0.80 ms | 0.73 ms | −9% |
| 200 towers | 1.29 ms | 1.17 ms | −9% |
| 400 towers | 1.80 ms | 1.62 ms | −10% |
| 800 towers | 2.66 ms | 2.46 ms | −8% |

So **7-10% of the cube pass**, and on this GPU nothing came near the 8.33 ms budget at 120 Hz —
the saving is headroom, not frames recovered. Absolute times drifted about 20% between runs while
the ratios held to a point or two, which is the interleaving earning its keep.

### The first wrong answer: it measured the wrong alignment, on a drifting GPU

An early round concluded turning the cube saved 0.28-0.41 ms and was not worth the code.

**It compared `5 -> 4` and reported it as the saving from turning the cube.** The alignment that
matters is `5 -> 3`.

**It ran the two conditions in sequence on a thermally throttling GPU.** Consecutive runs of the
same configuration varied between 8.95 and 12.13 ms -- more than the effect being measured. One run
even showed turning the cube making things worse.

### The second wrong answer: it was measuring an unrelated bug

The round that replaced it reported, on a Mesa Intel RPL-S:

```
background    2.75 -> 1.85 ms                       -33%
Forest 400   10.82 ->  7.40 ms   92% of frames dropped -> 9%
```

Interleaved, and right about the alignment — but **it overstated this by roughly two**, because at
the time `paint_at` re-uploaded a stimulus's vertex and colour buffers *once per cube face*. Face
count therefore multiplied vertex traffic as well as draw calls, and a large part of what "turning
the cube" appeared to save was that redundant upload.

Uploading once per frame is the larger win, and it is orthogonal to orientation. Isolated at a
fixed face count -- same stimulus, same renderer, only the upload differing (two runs agreeing to
0.3%):

| vertices | faces | upload per face | upload once | saving |
|---|---|---|---|---|
| 2,688 | 3 | 0.39 ms | 0.31 ms | −19% |
| 2,688 | 5 | 0.51 ms | 0.38 ms | −26% |
| 10,752 | 3 | 0.71 ms | 0.45 ms | −37% |
| 10,752 | 5 | 1.06 ms | 0.53 ms | −50% |
| 43,008 | 3 | 2.11 ms | 1.03 ms | −51% |
| 43,008 | 5 | 3.28 ms | 1.15 ms | −65% |

With that fixed, orientation is left saving draw calls and rasterisation only, which is the 7-10%
above rather than the 33% reported here. The dropped-frame line was on a slower GPU whose baseline
was already over budget; it has not been reproduced since the upload fix, and should not be quoted.

**The lesson, and it is the third time this page has needed one:** a measurement of an optimisation
is only as good as the code around it. This one was faithfully measuring an unrelated inefficiency
and attributing it to the thing under test. Interleaving protects against the machine drifting; it
does nothing about the benchmark measuring the wrong cause.

## What would change the verdict

- **A screen whose cap sits well under 65°**, where corner alignment gives three faces with real
  margin. Two faces saved rather than one, and safely.
- **A much heavier per-face cost than resolution can absorb** — a stimulus whose geometry, not fill,
  dominates. Face count multiplies geometry directly; resolution does not touch it.
- **A rig where the cube pass is measured to be the frame-rate limit.** It has not been, on any rig.
  `report_frame_count` over a known interval is the check.

## How it is implemented

Four pieces, all in place:

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

*Measurements: BrukerJr flymax bowl, `CAP_HALF_ANGLE = 65`, 1536² cube faces, on the rig's own
Quadro M2000, except the superseded 2.75/10.82 figures, which were a Mesa Intel RPL-S.*
