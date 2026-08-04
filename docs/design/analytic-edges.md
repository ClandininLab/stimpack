# Analytic edges: exact shapes, and motion below the pixel grid

*Supersedes the ray-casting proposal in `projector-space-raycast.md`, which Phase 0 refuted. This
addresses the defect that proposal was reaching for, on every rig rather than one, without changing
the render architecture.*

## Two measured faults

### 1. Nothing is antialiased

`make_qt_format` asks for 24x multisampling. It is not granted. From `report_surface_format`'s own
docstring, measured on two GPUs:

> setSamples(24) yields samples=0 on Mesa/Intel and on an RTX A4500 -- QOpenGLWidget renders into
> an FBO, where the surface sample count does not apply

The cube faces have no multisampling either. So every stimulus edge, on every path, is hard-
quantised to the framebuffer's pixel grid.

The consequence is a motion artefact. Without coverage information an edge cannot sit between
pixels, so it stays on one and then jumps. Frames an edge is frozen before it moves:

| rig | edge step | 2 °/s | 5 °/s | 10 °/s | 20 °/s |
|---|---|---|---|---|---|
| flat screen (Bruker-like) | 0.0400° | 7.2 | 2.9 | 1.4 | — |
| bowl, cube texel | 0.0879° | 15.8 | 6.3 | 3.2 | 1.6 |
| bowl, projector pixel | 0.0962° | 17.3 | 6.9 | 3.5 | 1.7 |

Note the last two rows are nearly identical. **The intermediate is not the cause** -- the projector's
own pixel grid quantises at almost exactly the same scale. This is what finally disposes of the
ray-casting proposal: removing the cube would not fix this, because the cube was never the limit.

Slow drift is common in visual physiology, and 2-10 °/s is squarely where this bites.

### 2. Curved shapes are polygons

`GlSphericalCirc` and `GlCircle` are fans of `n_steps=36` triangles. The polygon sits inside the
true circle by 1 - cos(pi/n) = 0.38% of the radius:

| stimulus | radial error |
|---|---|
| `LoomingCircle`, 20° radius | 0.076° |
| `LoomingCircle`, 5° radius | 0.019° |
| `MovingSpot`, 2° radius | 0.008° |

Against a flat screen's 0.04° pixel, a 20° looming disc is visibly polygonal -- the geometry error
is nearly twice the pixel. And a looming stimulus is one whose edge *is* the signal.

`GlSphericalRect` has the same shape of problem with `n_steps_x=6, n_steps_y=6`: its edges are
chords of the great circles they should follow.

## The fix

Keep rasterising geometry. Change what the fragment shader does with it.

Draw a conservative bounding polygon -- deliberately *coarser* than today, since it only has to
cover -- and compute the true edge per fragment:

```glsl
// disc of angular radius R about direction c; d is this fragment's direction
float angle = acos(clamp(dot(normalize(d), c), -1.0, 1.0));
float px    = fwidth(angle);                       // angular size of one pixel, here
float alpha = 1.0 - smoothstep(R - 0.5*px, R + 0.5*px, angle);
```

Three things fall out of those three lines.

**The edge is exact.** No `n_steps`, no polygon, no tessellation constant. A circle is a circle at
any radius and any zoom.

**Motion goes sub-pixel.** `smoothstep` across one pixel is analytic coverage: an edge halfway
across a pixel emits half intensity. Edge position is then carried by intensity rather than by
which pixel is lit, so it moves smoothly at any speed -- which is the fault in §1, fixed at its
actual cause.

**Geometry gets cheaper, not dearer.** A 36-triangle fan becomes a bounding quad or octagon. The
same argument applies to `GlIcosphere`'s 20,480 triangles per ellipsoid.

`fwidth` is a screen-space derivative, so the antialiasing is automatically correct for whatever
the fragment's local scale is -- no need to know the projector's resolution, the screen's shape, or
which path is rendering.

## Why this is not the ray-casting proposal

It changes no architecture. No projector-space pass, no tracer, no scene description, no per-
fragment loop over primitives, no depth compositing. Stimuli are still composed in Python from
shapes; shapes are still rasterised; the cube still does what it does.

It also cannot fail the way that proposal did, because it does not rest on a resolution comparison.
The polygon error and the missing coverage are both present regardless of projector, screen shape,
or intermediate.

## Caveat on the curved path

Through a cube map, `fwidth` measures the cube face's pixel, not the projector's. On flymax's rig
those are 0.088° and 0.096°, so the antialiasing lands at very nearly the right scale. On a rig
where they diverge, the curved path would antialias at the cube's scale rather than the screen's --
correct in kind, slightly off in width. Worth knowing; not worth architecture.

## Scope

Smallest useful change: `GlSphericalCirc` and `GlCircle`, which cover `MovingSpot`,
`LoomingCircle`, and the fly's wings. Then `GlSphericalRect` and the cylindrical patches.

The test to write first is the one that would have caught this: render a disc, measure the width of
its intensity transition in degrees, and assert it is about one pixel rather than zero. A companion
test steps a disc across the screen at 5 °/s and asserts the measured edge position changes every
frame -- which today it does not.

## What to check before starting

Whether MSAA can simply be made to work. If a multisampled FBO can be resolved into the
QOpenGLWidget's, §1 improves everywhere for a much smaller change, though it would not fix §2 and
would cost fill. Worth half a day before committing to shader work, and worth knowing either way,
since the code currently asks for 24x and silently receives none.
