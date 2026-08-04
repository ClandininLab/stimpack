# Rendering in projector space, by ray-casting analytic geometry

*Design note for the `projector-space-raycast` branch. Nothing here is implemented.*

**Superseded.** Phase 0 refuted the argument below (see the last section), and the defect it was
reaching for turned out to be neither the cube's fault nor fixable by removing it: stimulus edges
are quantised by the projector's own pixel grid, on every rig, because multisampling is requested
and not granted. `analytic-edges.md` addresses that at its actual cause. Read this note for the
measurements and for the record of a wrong turn; act on that one.

The current curved-screen path renders the scene into a cube map and then warps the screen mesh,
each fragment sampling the cube along its own interpolated direction. That works, is committed on
`dev`, and is the right shape for a general scene. This note argues it is the wrong shape for the
scenes stimpack actually draws, and sketches what would replace it.

## The problem with any direction-space intermediate

A cube map is parameterised by **direction**. A projector is parameterised by **image position**.
On a real bowl those two disagree enormously.

Measured from flymax's own constants (`stimgen/calculatePixelsOnSphere.m`: r = 76.2 mm, 39.5° tilt,
throw 1.4, 1140 px):

| where on the screen | projector delivers |
|---|---|
| centre of the projector image | 34.5 px/deg |
| edge of its reach (74° off axis) | 0.2 px/deg |

A **138-fold** spread, because a single projector throwing onto a sphere spreads its pixels wildly
across the surface. Against that, stimpack's cube map at the shipped 1024 px/face gives a flat
11.4 px/deg (varying only 2.3× centre-to-corner within a face).

So the intermediate is wrong in both directions at once:

- **at the centre it is the bottleneck** — 11.4 px/deg where the optics could deliver 34.5, so the
  projector's best resolution is discarded exactly where the animal's acuity is highest
- **at the rim it is waste** — 11.4 px/deg where the optics deliver 0.2

Raising the cube resolution fixes the first by worsening the second. There is no setting that is
right everywhere, because the mismatch is structural rather than a tuning problem. To stop being
the bottleneck at the centre would need ~3105 px/face, i.e. 4096 — 336 MB across five faces.

Note also that the docstring justifying 1024 px/face argues from the animal's acuity (~5° between
ommatidia). That is the wrong quantity: what decides whether the intermediate throws information
away is the *projector's* density, not the fly's.

## The cost, stated plainly

The intermediate costs more fill than the image it exists to produce:

| | fill per frame | vs the projector panel |
|---|---|---|
| projector panel (1140 × 912) | 1.04 Mpx | 1× |
| cube, 5 faces at 1024² | 5.24 Mpx | 5.0× |
| cube, 5 faces at 2048² | 20.97 Mpx | 20.2× |
| cube, 5 faces at 4096² | 83.89 Mpx | 80.7× |

At 360 Hz the shipped configuration is 1.89 Gpx/s of intermediate to deliver 0.37 Gpx/s of image.

## The alternative

Rasterise the **screen mesh** straight into the projector framebuffer. Every fragment already
carries its own direction from the subject — that is the interpolated attribute the warp shader
uses today. Instead of sampling a cube along it, intersect the scene along it, in closed form.

Resolution is then the projector's, exactly, everywhere, by construction. One pass. No resampling.

This is what flymax does, with one difference that matters: flymax precomputes the answer offline
as a `[phi, theta, time]` movie and warps it, which is why it cannot close a loop. Evaluating the
same function live in a fragment shader is the modern form of the same idea, and closed loop falls
out for free.

## Why it can work here: the geometry is already analytic

Ray casting needs surfaces that can be intersected in closed form. A survey of both repositories
says every stimulus is built from exactly that.

**stimpack's own library** (`visual_stim/stimuli.py`, 24 classes) draws on:

```
8  GlCylinder                        3  GlQuad     1  GlCircle
4  GlSphericalTexturedRect           1  GlCube     1  GlBox
2  GlSphericalRect                   2  GlCylindricalWithPhiRect
1  GlSphericalEllipse                1  GlCylindricalWithPhiEllipse
1  GlSphericalCirc                   1  GlVertices
```

Spheres, cylinders, planes, boxes, points. There is **no mesh loader and no imported geometry**.
The stimuli I had assumed needed rasterisation do not: `Tower` and `Forest` are `GlCylinder`,
`Floor` and `CheckerboardFloor` are `GlQuad`, `MovingBox` is `GlBox`.

**The Clandinin labpack** is the harder case and still passes. `GlFly` — a fly model, the most
mesh-like object in either repository — decomposes to five ellipsoids and two elliptical discs:

```
Head    : icosphere scaled -> ellipsoid, + 2 eyes (scaled, rotated ellipsoids)
Thorax  : icosphere scaled -> ellipsoid, + 2 wings
Wing    : GlCircle scaled (0.25, 0.5, 0.5) -> a flat ellipse
Abdomen : icosphere scaled -> ellipsoid
```

An ellipsoid is a transformed unit sphere; a disc is a plane test and an inside-ellipse check. Both
closed-form. The 16 `GlVertices()` uses in the labpack's stimuli are empty composite containers,
not raw vertex data.

So the library is **defined** analytically and merely **represented** as triangles. The
representation is expensive: `GlIcosphere(n_subdivisions=5)` is 20,480 triangles per ellipsoid, so
one fly is 102,400 triangles standing in for seven primitives — submitted once per cube face.

## What this would mean in practice

Each shape gains an intersection routine and a shading function, and stops being a vertex buffer.
Roughly:

```glsl
// per fragment, in projector image space
vec3 origin    = subject_position;
vec3 direction = normalize(interpolated_direction);
Hit  nearest   = trace(origin, direction);   // over the scene's analytic primitives
color          = shade(nearest, time);
```

Depth and occlusion come from comparing intersection distances — no depth buffer. Two shells of
different radii work directly, and when the subject translates off centre in closed loop they give
genuine parallax, which "painting on a sphere" cannot.

## Is this undoing flystim 1.0 -> 2.0?

Partly, and the part it undoes is the one worth arguing about.

**flystim 1.0 was a direction-space renderer.** `base.py` describes `calc_color` as "GLSL shader
code used to compute the monochromatic color of each pixel as a function of spherical coordinates
(r, theta, phi)", and `glsl.py` is a small library for generating that GLSL from Python. A stimulus
*was* a fragment program:

```python
class ConstantBackground(BaseProgram):
    uniforms   = [Uniform('background', float)]
    calc_color = 'color = background;\n'
```

All 14 of its stimuli are functions of direction — gratings, bars, patches, grids, checkerboards.
There is no `Tower`, no `Forest`, no `Floor`, no `Box`, no textured surface, no colour.

**2.0 replaced that with composable geometry** and went to 24 classes. What it bought:

1. **3D scenes with parallax.** `Tower`, `Forest`, `Floor`, `CheckerboardFloor`, `MovingBox`,
   `TexturedGround` cannot be written as f(theta, phi) at all. This is what made closed-loop
   position experiments possible.
2. **Composition in Python.** A stimulus assembles primitives instead of emitting GLSL. `GlFly` is
   five ellipsoids and two discs, written by a labpack, in Python.
3. **Textures and colour**, from vertex attributes, rather than monochrome analytic functions.
4. **Extensibility without touching the core.** A labpack adds `GlIcosphere` and `GlFly` in its own
   file. stimpack never sees them.

Against that, this proposal is **not** a return to 1.0. Ray casting analytic surfaces keeps (1) —
it does parallax and occlusion properly, from intersection distances, which 1.0's direction
functions could not do at all. It keeps (2), provided intersection routines live in the shape
library rather than in each stimulus: a stimulus still says "cylinder here, ellipsoid there". (3)
is mostly fine, since sphere, cylinder and plane all have natural analytic parameterisations,
though each primitive would need its UV written by hand instead of getting it from vertex data.

**(4) is the real loss, and it is the one that matters most here.** In 2.0 a labpack adds geometry
without stimpack's involvement. In a ray-cast renderer every primitive type must have an
intersection routine compiled into one shared tracer, and a labpack cannot inject GLSL into
stimpack's shader without a mechanism that does not exist. That is in direct tension with the
labpack separation this project leads with everywhere else, including in its paper.

That argues for a second path rather than a replacement, and for the cube remaining the fallback.
But "a labpack cannot extend a ray-cast renderer" is too strong, and the rest of this section is
why.

### How a labpack could still add geometry

Three mechanisms, in increasing order of how much they preserve.

**1. The labpack ships GLSL.** An intersection function and a shading function with fixed
signatures, composed into the tracer by stimpack. Separation is fully preserved. This is not
hypothetical: it is what flystim 1.0 did, with `glsl.py` generating GLSL from Python declarations
and substituting it into `base.template`. The mechanism existed in this lineage and was retired
because 2.0 made it unnecessary, not because it failed. The cost is that labpack authors write
GLSL, which is a steep barrier for people who write protocols in Python.

**2. Primitives as data rather than code.** A labpack declares a quadric -- a 4x4 matrix Q -- and
stimpack has one generic intersector, since ray-vs-quadric is a quadratic in t. That single routine
covers spheres, ellipsoids, cylinders, cones and paraboloids; boxes are a CSG of half-spaces. No
GLSL from the labpack. It covers everything in both libraries, `GlFly` included.

**3. Shapes declare their own analytic form, and labpacks change nothing.** `GlIcosphere` already
*is* a unit sphere and `GlCylinder` already *is* a cylinder. stimpack could derive the quadric from
the objects a labpack already composes -- except that today every transform discards exactly that:

```python
def scale(self, amt):
    return GlVertices(vertices=util.scale(self.vertices, amt), ...)
```

`GlIcosphere(...).scale(...)` returns a plain `GlVertices`, so both the identity and the transform
are baked into vertex data and lost. Preserving the subclass and accumulating the transform matrix
is a modest change in stimpack's own `shapes.py`, and independently worth it: a shape could then be
re-transformed without regenerating 100k vertices.

With (3), a labpack composing stock primitives gets the fast path having written nothing new, and
anything built from raw `GlVertices` falls back to the cube automatically.

So the residual cost is narrow: a labpack wanting a genuinely novel *kind* of surface, not
expressible as a quadric or a CSG of quadrics, either writes GLSL or takes the cube path. Nothing
becomes impossible. There is even an argument this improves matters -- `GlFly` as seven quadrics is
exact, smaller and re-transformable, against 102,400 baked triangles today.

The honest framing of this work is therefore not "the cube was wrong" but "a fast path exists for
the geometry we actually draw, it needs primitives to be declarative rather than vertex soup, and
the cube stays for everything else".

## What would have to be true

Open questions, in the order that would settle whether to continue.

1. **Does the resolution actually cost anything on the rigs in use?** The 138× spread is one bowl's
   geometry, lit at 39.5° off-axis. A gentler arrangement narrows it. The diagnostic to write first
   reports projector px/deg across the screen for a given `SphericalSurface` and
   `PinholeProjector` — we already model both — alongside the cube resolution that would match it.
   Everything here rests on that number being bad.

2. **How many primitives per scene, and does the per-fragment loop stay cheap?** A `Forest` of
   cylinders means a linear scan per fragment unless it is spatially sorted. Rasterisation gets
   this for free; ray casting does not.

3. **Does anything need arbitrary meshes?** Nothing does today, in either repository. But a
   labpack could import one tomorrow, and the answer must be that the cube path remains available
   rather than that meshes become impossible.

4. **Do shapes keep their analytic identity through a transform?** This is the prerequisite for
   the whole approach being extensible without labpacks writing GLSL -- see mechanism (3) above.
   It is a change to `shapes.py`, it is small, and it is worth doing on its own merits. Do it
   first, independently of any renderer, and the rest becomes possible rather than blocked.

## Recommendation

Keep the cube as the default and the fallback. Add this beside it, chosen per stimulus, once (1)
shows the resolution loss is real on a rig somebody runs and (4) has an answer that does not put
labpack geometry back inside stimpack. If either fails, this note is the record of why we did not
do it.

The framing that survives scrutiny is not "the cube map was a mistake" -- it is the right general
answer, and flystim 2.0 was right to move to composable geometry. It is that stimpack draws a
narrow enough class of geometry that a faster path exists, and that path costs extensibility, so it
has to be opt-in and cannot be the only one.

---

## Phase 0 result: the case does not survive the real geometry

*Added after running the diagnostic against flymax's actual rig parameters, from
`stimgen/pmeshdf.m` and `stimgen/sphere2plane.m`. It contradicts the argument above, and the
argument above was wrong.*

The numbers this note was built on came from a **reconstruction of flymax's rig, not its rig**. I
took `r`, `t` and `c` from `stimgen/calculatePixelsOnSphere.m` -- an exploratory script, with an
"arbitrary starting point" in its own comments -- and, crucially, assumed the screen was a full
hemisphere. It is not.

The real parameters:

```matlab
% pmeshdf.m
screen 's' (small, new) : r = 71.5 mm,  c = 110 mm arc      % -> 44.07 deg HALF-angle
screen 'l' (large, old) : r = 77.5 mm,  c = 105 mm arc      % -> 38.81 deg half-angle
t = 1.57523511   % throw ratio, measured rather than from specs
a = 1.6          % aspect
g = 2            % degrees between mesh vertices
```

`c` is an arc length in millimetres, converted by `sphere2plane.m` as `c = c/r/2` into a **half**
subtended angle. So flymax's screen is a cap of roughly 40-44 degrees half-angle -- about 80-88
degrees of visual angle across -- and not a hemisphere at all.

Rebuilt from those, with the projector placed as `d = 2*r*t*a*sin(c) + r*cos(c)` puts it (302.1 mm
for screen 's', which matches the 302 mm recorded independently in the brightness note):

| screen | px/deg, 1st | median | 99th | spread | cube-limited |
|---|---|---|---|---|---|
| 's' small/new | 7.8 | 9.2 | 10.9 | **1.4x** | 0.0% |
| 'l' large/old | 9.1 | 10.4 | 12.0 | **1.3x** | 18.3% |

**The 138-fold spread was an artifact of my wrong screen extent.** A hemisphere runs out to grazing
incidence at its rim, where a projector's pixels smear to nothing; a 44-degree cap never goes near
it. The rig was designed so the projector matches the screen, which is what a rig designer would do.

With the spread gone, both arguments for this branch collapse:

- **Resolution.** Matching the projector needs 978-1076 px/face. The shipped default is 1024. The
  cube is correctly sized, by accident or by judgement, and is the limit over 0% of screen 's'.
- **Motion quantisation.** A cube texel is 0.088 deg and a projector pixel on these rigs is about
  0.10 deg. The cube is *finer* than the optics, so it adds no quantisation the projector does not
  already impose. The earlier table assumed 0.029 deg pixels, which came from the same bad
  reconstruction.

### What the real geometry did buy

The cheap change already on `dev` turns out to matter far more than the expensive one proposed
here. A 44-degree cap fits inside a single cube face:

```
screen 's': 1/6 faces ['+Z']   saves 83% of scene draws
screen 'l': 1/6 faces ['+Z']   saves 83% of scene draws
```

`faces_for_mesh` finds this automatically, with no configuration. Against that, this branch's
best case was 5x fill on a claim that has now evaporated.

### Also corrected

The tessellation default was changed to 5 degrees on this branch's premise that it "matched
flymax". flymax uses **2** (`pmeshdf.m`, `g = 2`). The docstring no longer claims otherwise. The
5-degree default is still defensible on its own terms -- flymax's mesh carries the stimulus, so its
spacing is a real resolution limit there, and here it is only a geometry approximation -- but it
was not the reason given.

### Recommendation

**Stop.** Do not build Phases 1-5. The diagnostic that was supposed to justify them refutes them
instead, which is what a gate is for, and it cost days rather than the months a renderer would
have.

Keep: `ScreenMesh.projector_resolution()`, which is a rig-commissioning tool on its own and is how
anyone can re-open this question with a rig whose numbers differ. Re-open only if a rig appears
with a genuinely wide screen -- a real hemisphere, or one lit at a shallow angle -- where the
spread returns.
