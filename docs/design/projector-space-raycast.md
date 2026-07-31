# Rendering in projector space, by ray-casting analytic geometry

*Design note for the `projector-space-raycast` branch. Nothing here is implemented; this records
why the branch exists and what would have to be true for it to be worth finishing.*

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

4. **What does it cost a labpack author?** Writing a stimulus becomes writing an intersection
   routine, not assembling shapes. That is a real cost to the people who write the most stimuli,
   and it is the strongest argument for keeping this as a second path rather than a replacement.

## Recommendation

Keep the cube. Add this beside it, chosen per stimulus, once (1) shows the resolution loss is real
on a rig somebody runs. If it is not real, this note is the record of why we did not do it.
