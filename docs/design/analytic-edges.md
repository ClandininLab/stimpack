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

*Half of that is now addressed: `Screen(msaa_samples=n)` multisamples the framebuffer a frame is
drawn into. The cube faces are still single-sample, and deliberately -- see "It reaches the flat
path fully and the curved path barely" below.*

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
float alpha = clamp(0.5 - (angle - R)/px, 0.0, 1.0);
```

**Linear, not `smoothstep`.** The graphics convention is `smoothstep`, whose S-curve makes edges
look soft rather than creased. It is wrong here in two ways. A pixel 30% covered should emit 30% of
the light; `smoothstep` emits 22%, and the worst luminance error is 9.6 percentage points. Worse,
the mapping from edge position to emitted intensity is then non-linear, so a constant-velocity edge
appears to stall and then hurry once per pixel crossed -- reintroducing, in miniature, the very
motion artefact this exists to remove. The linear form is the true covered fraction for a straight
edge, which is what a photoreceptor integrating over that pixel receives.

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

Smallest useful change: `GlSphericalCirc`, covering `MovingSpot` and `LoomingCircle`. Then
`GlSphericalRect`, `GlSphericalEllipse`, and the cylindrical patches.

**Not the fly's wings**, which an earlier draft of this note claimed. Two independent things put
them out of reach, and both are properties of the design rather than oversights:

- the wing is `GlCircle(radius=1.0).scale([0.25, 0.5, 0.5])`, a *non-uniform* scale, so it is not a
  circle by the time it is drawn;
- it is then `add()`ed into `GlFly.Thorax`, and `add()` concatenates vertex arrays into one mesh.
  One draw call carries one set of uniforms, so **a composite cannot hold per-shape edges at all**.

The second point **used to be** the boundary of what this approach reaches, and it no longer is.
`add()` now records where each merged component landed along with what it declared, and the
renderer draws the runs separately -- one set of edge uniforms each. A composite of analytic shapes
stays analytic.

That matters because the case is not hypothetical. The labpack's `PatchFieldWithOnDemandCoherentPulses`
and `ExponentiallyRefreshingMovingPatchFieldWithCoherentPulse` build twenty `GlSphericalEllipse` or
`GlSphericalRect` patches and merge them, and those are coherent-motion stimuli where each patch's
edge motion *is* the signal. All twenty declarations were being discarded.

It costs one draw call and one set of uniform writes per component, which is linear and not free:

| components | extra per frame | of a 360 Hz budget |
|---|---|---|
| 5 | +0.025 ms | 0.9% |
| 20 | +0.096 ms | 3.5% |
| 50 | +0.240 ms | 8.6% |

Fine for a twenty-patch field, and worth watching past about fifty. If a stimulus ever needs
hundreds, the declaration would have to move from uniforms to a per-vertex attribute so it could go
back to one draw call -- more vertex data, no per-component cost.

The wings are still out of reach, but now for only one reason rather than two: a non-uniform scale
turns that circle into an ellipse, which no kind here describes.

### What a shape declares

The disc needed a centre direction and an angle. A rectangle needs an *orientation* -- "20 degrees
wide" is a statement about a frame, not about a point -- so the declaration is a frame and a pair
of half-extents, which covers both:

```python
EDGE_KIND = EDGE_ANGULAR_RECT
self.edge_frame = CANONICAL_PATCH_FRAME          # azimuth, elevation, forward; rows
self.edge_extent = (radians(width) / 2, radians(height) / 2)
```

A declaration also says **where it is measured from**. That anchor is what lets a shape be moved
without invalidating what it declared: move the anchor with the shape and every direction and
distance from it is unchanged, so rotation, translation and uniform scaling all carry exactly.
Only a *non-uniform* scale drops the declaration, and it has to -- it turns a disc into an ellipse
and a spherical patch into something with no equation here, and a wrong analytic edge is worse than
none.

Without the anchor this was not merely a restriction but a latent bug:
`GlSphericalCirc(circle_radius=15, sphere_location=(0.5, 0, 0))` put its geometry at the location
and declared an angle measured from the origin, where the rim spans 13 to 39 degrees rather than a
constant 15. Nothing passed a non-zero location, so it never fired.

The bound is widened by `EDGE_BOUND_MARGIN` rather than being exact. A rectangle's constant-azimuth
sides are great circles, which triangle edges follow *exactly* -- flush against the bound with
nothing to spare -- so rounding at a corner could nick a real sliver off the patch, and a fragment
shader can only remove coverage, never add it. The disc needs no margin: its bound is an octagon
circumscribing the circle, so only the eight tangent points come close.

The kinds share their arithmetic. Each answers one question -- how far outside the shape this
fragment is -- and the coverage step is then the same three lines for all of them, which is what
keeps this from becoming a shader per shape. The units are the kind's own choice, because `excess`
is divided by `fwidth(excess)` and both scale together: the ratio is always "how many pixels
outside".

There is one branch above that, and it is the only taxonomy the shader has:

```glsl
vec3 offset = v_world - edge_anchor;
if (edge_kind == EDGE_WORLD_DISC) return length(offset) - edge_extent.x;   // metric: how FAR
vec3 dir = normalize(offset);                                              // angular: which WAY
```

An **angular** kind asks which direction a fragment lies in and answers in angle; a **metric** kind
asks how far away it is and answers in metres. `GlCircle` is the metric one: a flat disc's
fragments all lie in the disc's plane, so the distance from its centre in three dimensions is the
radius in two, and one line is its boundary exactly. Its bound needs no margin either -- polygon
and circle are both planar, a triangle edge is a straight line in that plane, and perspective
scales both by the same factor, so a circumscribing polygon contains the circle at every distance.

The rectangle uses the exact distance outside a box rather than `max()` of the two axes. `max()` is
the Chebyshev distance, which past a corner reports the longer leg where the truth is the
hypotenuse -- under-reporting by up to sqrt(2), so corners read as extended by 0.4 of a pixel.

### Which ellipse

Making the boundary an equation forces a definition where there was only an accident. The old
`GlSphericalEllipse` was an ellipse drawn on the azimuth/elevation grid -- and that grid is not
uniform, since a degree of azimuth is a shorter arc the higher you go. So it came out right at its
four extreme points and pinched in between. Setting the axes equal did not give a disc:

| shape | rim, angle from centre | should be |
|---|---|---|
| `GlSphericalEllipse(45, 45)` | 22.358 to 22.500 deg | flat at 22.5 |
| `GlSphericalEllipse(60, 60)` | 29.649 to 30.000 deg | flat at 30 |

0.35 degrees at 60 degrees is four pixels on the bowl, and it means `MovingEllipse(w, w)` was not
`MovingSpot(w/2)`.

Three definitions were considered, all normalised to the same width and height: the chart ellipse
above; the **cone**, a flat ellipse projected outward from the subject -- what an elliptical hole
held in front of the eye leaves unblocked, and what an ellipse drawn on a flat screen subtends; and
the **true spherical ellipse**, constant sum of great-circle distances to two foci. How far the
edge moves between them:

| width x height | cone vs chart | true vs chart | in pixels (bowl) |
|---|---|---|---|
| 10 x 5 | 0.0005 deg | 0.0006 deg | 0.0 |
| 20 x 10 | 0.0041 deg | 0.0052 deg | 0.0 |
| 45 x 22 | 0.0434 deg | 0.0627 deg | 0.5 - 0.7 |
| 90 x 45 | 0.3165 deg | 0.5388 deg | 3.6 - 6.1 |

Across every size configured in `clandinin_labpack` (5-40 degrees) all three agree to well under a
pixel, so this was not a fidelity decision. **The cone was adopted**, on three grounds:

- **It is what the disc already is.** `GlSphericalCirc` means "every direction within angle R of
  forward", which is a circular cone. So the disc is the equal-extent case of the ellipse, one
  branch serves both, and the kind count stays at two rather than going to three.
- **It is the one you can build.** A card with an elliptical hole. Nothing in a lab produces a
  constant-sum-of-geodesics curve.
- **No special cases.** The foci construction needs `acos(cos a / cos b)`, so it requires width
  >= height and an axis swap otherwise.

Both the cone and the true ellipse degenerate exactly to the disc; only the chart version does not.

### Why the bound needs no fudge factor

Gnomonic projection -- divide a direction by its forward component -- takes great circles to
straight lines, and the edge the GPU rasterises between two vertices on a sphere sweeps a great
circle. In those coordinates the drawn polygon *is* the polygon, so an octagon circumscribing the
ellipse there circumscribes the real shape exactly, at any size, with nothing to tune. That is why
`EDGE_BOUND_MARGIN` applies to the rectangle and not to the cone.

A cone cannot describe more than a hemisphere, so a half-extent at or past 90 degrees has no
analytic form to declare; those fall back to the fan and to a geometry-defined edge.

### The cylindrical patches are not a separate problem

`cylindrical_w_phi_to_cartesian(r, theta, phi)` and `spherical_to_cartesian(r, theta, phi)` put a
given `(theta, phi)` in the **same direction** -- verified to 1e-6 degrees across the sphere. They
differ only in how far along that ray the vertex sits.

An edge declaration is a statement about direction: the shader works from
`normalize(v_world - subject_position)` and never learns what surface the triangle came from. So
`GlCylindricalWithPhiRect` and `GlCylindricalWithPhiEllipse` take the *same two kinds* their
spherical twins do, with no new shader code, no new uniforms, and no new carry rules -- only the
declaration, and a builder parameterised by where the vertices land.

The containment argument survives the change of surface for the same reason. A straight segment
seen from the subject sweeps a great-circle arc whatever distance its endpoints are at, so the set
of directions a triangle spans depends only on the directions of its corners. The gnomonic bound is
therefore correct on any surface.

The rendered proof: `moving_patch_on_cylinder` is **pixel-identical** to `moving_patch_center`, and
the two ellipses differ by a single pixel. A pinhole projection maps direction to screen position,
so shapes covering the same directions produce the same image.

This is why the kind is called `EDGE_ANGULAR_RECT` and not `EDGE_SPHERICAL_RECT`.

## The same idea inside a texture

The panoramic stimuli -- `CylindricalGrating`, `Checkerboard`, `RandomGrid`, `RandomBars`,
`PixMap` -- paint a texture on a wall that fills the visual field. Their edges are not the shape's
boundary but boundaries between texels, which is data rather than an equation, so no shape
declaration reaches them. Measured on a scanline through a 256x256 render, before:

| stimulus | intermediate pixels in the scanline |
|---|---|
| Checkerboard | 0 |
| CylindricalGrating, square | 0 |
| RandomGrid | 0 |
| CylindricalGrating, sine | 124 (a gradient; it has no edges) |

And it carried the same motion cost, on a square grating drifting at 10 deg/s at 360 Hz. Tracking
one bar:

```
before:  edge frozen in 27 of 29 frames; 3 distinct positions in 30 frames; jumps of a whole pixel
after:   edge frozen in  0 of 29 frames; 30 distinct positions in 30; largest jump 0.121 px
```

`NEAREST` filtering is why, and it is *not* a mistake: it exists so a checkerboard stays a
checkerboard rather than being blurred into a gradient. `LINEAR` is not the fix -- it ramps over a
whole texel, and a texel here is 0.69 degrees (grating) to 15 degrees (checkerboard) against a
0.088 degree pixel, so it would smear the pattern across 8 to 170 pixels.

The fix keeps the intent and drops the aliasing: filter `LINEAR`, but move the sample point.
Everywhere but within one pixel of a boundary the sample lands exactly on a texel centre, which is
what `NEAREST` would have returned; across the boundary it ramps, and the hardware's own
interpolation then mixes the two texels in the proportion the pixel is covered by each. Same
covered-fraction rule as the shape edges, reached through the filter rather than through alpha.
See `shapes.sharp_texel_coord` for the rule and `sample_texture` in the fragment shader.

Clamping the ramp to one texel makes it degrade to ordinary bilinear filtering under minification,
where there is no single boundary to antialias and mipmaps are the answer instead.

### But a texture can be jagged before it is ever sampled

None of the above reaches a boundary that was quantised when the texture was *written*. An angled
`CylindricalGrating` thresholded a sampled sine, which puts every bar edge on a texel boundary, so
a diagonal came out as a staircase. Measured at bowl scale, one bar edge's deviation from a
straight line:

| `n_steps` | texels/period | edge RMS | worst |
|---|---|---|---|
| 512 (the old default) | 43 | 2.512 px | 5.68 px |
| 2048 | 171 | 0.553 px | 1.33 px |
| 2048, storing coverage | 171 | **0.142 px** | 0.62 px |

Three things, and together they cost *less* than what they replace:

- **The tile was built by a nested Python loop**, one scalar `np.sin` per texel, which is what made
  resolution expensive: 17.3 ms at 2048. Vectorised it is 0.21 ms.
- **The square profile stores coverage rather than a threshold.** The phase field is linear, so the
  covered fraction of a texel is the same `clamp(0.5 - d/w, 0, 1)` rule the fragment shader uses --
  matching 16x16 supersampling to a mean of 0.004 for 1/200th of its cost.
- **Texels are sampled at their centres.** A texel's value is displayed across the whole texel, so
  it has to describe the texel. Sampling at the leading edge shifted every grating by half a texel,
  which was 0.35 degrees of phase at the old resolution.

Storing coverage changes which filter is right, and the drifting-edge test caught it: a
pre-antialiased texture must be sampled `LINEAR`, not snapped to texel centres. Snapping quantises
the edge position back onto the texel grid -- the staircase again, one texel wide. `NEAREST` stays
right where a texel *is* the datum, a checker square or a noise cell, with no sub-texel structure
to recover.

And a texture generated finer than the display needs **mipmaps**. At 2048 texels a drifting square
grating froze for 12 frames of 29 when rendered at 0.35 degrees per pixel, because one sample per
pixel of a finer texture is aliasing; with mipmaps, none. They are built for the smooth path only --
on the sharp-texel path a mipmap would blur exactly what those textures encode.

Cost: 0.028 to 0.029 ms per frame on a full-field checkerboard at 1280x800 -- about a microsecond,
against a 2.78 ms budget at 360 Hz.

## The audit: what is still hard-edged

Every stimulus rendered and its partially-lit pixels counted. **16 soft, 3 hard**, 6 not renderable
with defaults. The three:

- **`AlternatingAnnuli`** -- correctly excluded, and its own docstring says why: the shader carries
  one edge equation per draw and this is many rings. A commissioning pattern, 0.01 degrees of
  radial error at `n_azimuth=128`.
- **`MovingBox`** -- `GlBox`, polyhedral and world-space. Its edges are genuinely straight lines.
- **`LoomingCircle`** -- the one with a case behind it. See below.

The structural limit found along the way: **a composite cannot hold per-shape edges.** `add()`
concatenates vertex arrays into one mesh, and one draw call carries one set of uniforms. That is
what puts `GlFly`'s wings and `Forest`'s trees out of reach, and it is the question to ask of any
future candidate before converting it.

## Where the polygon still is the shape

`LoomingCircle` draws a *flat* disc in metres receding in depth, not a spherical patch, so nothing
above reaches it. It has two separable defects, and only one is worth paying for:

**The polygon is a systematic bias.** An inscribed n-gon holds `(n/2pi) sin(2pi/n)` of its circle's
area, so at `n_steps=36` every frame of every approach under-reported the disc by **0.51%** -- one
direction, constant through the whole approach, on exactly the quantity a looming experiment reads.
The shape is built once in `configure` and only translated afterwards, so sides cost nothing per
frame. Raised to 128, the bias is 0.045%. `Tower` had the same shape of problem (`n_faces=16` put a
0.5 m tower 5.8 pixels narrow at 1 m, worsening as the subject approaches) and is now 64.

**The pixel grid is not, mostly.** Without coverage the edge cannot sit between pixels. Tracking a
point on the contour, at bowl scale, of a 5 cm object approaching from 1 m at 0.9 m/s:

| window | distance | angular radius | frames per step |
|---|---|---|---|
| 0-60 ms | 0.925 m | 3.09 deg | 15.0 |
| 120-180 ms | 0.625 m | 4.57 deg | 6.0 |
| 300-360 ms | 0.175 m | 15.95 deg | 1.0 |

So it is concentrated entirely in the early, slow phase -- 42 ms frozen at the start, moving every
frame by the end. But the **total area** advances in 348 of 359 frames, because the rim is long and
different parts of it cross pixel boundaries at different moments.

Which means: if an experiment reads angular size or area, `n_steps` was the whole problem and it is
fixed. If it reads local edge velocity, or has small receptive fields sitting on the contour, the
42 ms freeze is real and only an analytic edge removes it.

**What that would take**, if it is ever wanted: a world-space kind, `length(v_world - edge_origin)
- radius`, in metres. The carry rules would then split cleanly rather than messily -- a kind is
anchored either *at the subject* (angular: only rotations preserve it, as now) or *in the world*
(its anchor transforms exactly like a vertex, so translate, rotate and uniform scale all carry;
non-uniform scale drops, since it is an ellipse then). That dichotomy would also make `Tower` and
`MovingBox` reachable. About thirty lines. Not built, because nothing has asked for it.

Note the substitution that looks tempting and is wrong: `LoomingCircle`'s disc *is* exactly a
circular cone seen from the origin, so `EDGE_CONE` describes it -- but only for a subject at the
origin. Off-axis the two diverge (0.115 degrees at 2 cm, 0.586 at 10 cm), and nothing in the code
would enforce or report the precondition. A wrong analytic edge is worse than none, which is why
`translate` and `scale` drop their declarations in the first place.

## Measured: reusing one bound across sizes

Because the geometry now only *bounds*, a shape whose size changes need not be rebuilt at all --
keep a bound and change `edge_extent` per frame. Verified: a single 40 degree bound renders 5, 10,
20 and 40 degree discs correctly, agreeing with purpose-built ones to 0.5% of area. This was
impossible when the triangles *were* the shape.

**A bound needs resizing when the declaration changes, not when the picture changes.** That is a
narrower condition than it first sounds, and it is worth stating carefully, because "the shape gets
bigger" is true of a loom in a way that does not imply the declaration moves at all:

| stimulus | what it declares | changes per frame? | needs a bound policy? |
|---|---|---|---|
| `MovingSpot` with a Loom radius | an angle | yes -- the angle *is* the parameter | yes |
| `LoomingCircle`, if given a world-space kind | a radius in metres | no -- a rigid object | **no** |

`LoomingCircle` draws a flat disc of fixed physical radius, built once in `configure` and only
translated afterwards; its geometry never changes and only its distance does. Were it given the
world-space kind sketched above, its declaration would be metric too, and perspective scales a
circle and its circumscribing polygon by the same factor -- so the bound contains the disc at every
distance, verified from 2 m down to 0.1 m, and never needs rebuilding. Build once, translate, done.

So the policy question below is about angular declarations on shapes whose angle is a trajectory:
`MovingSpot` and its relatives.

Three policies, 360 frames at 1920x1080, draw time isolated from readback:

| trajectory | renderer | rebuild every frame | one bound at the maximum | bound 1.5x, hysteresis |
|---|---|---|---|---|
| Loom, 5-40 deg | RTX A4500 | 0.0740 ms | 0.0191 | **0.0114** |
| Loom, 5-40 deg | llvmpipe | 0.1686 | 0.4432 | **0.1340** |
| linear, 10-40 deg | RTX A4500 | 0.0764 | 0.0194 | **0.0146** |
| linear, 10-40 deg | llvmpipe | **0.2233** | 0.4455 | 0.2417 |

**Hysteresis is the right policy for a resizing shape**, and on a real loom it wins on both
renderers -- 6.5x on the A4500, 1.26x on llvmpipe -- rebuilding 6 times instead of 360. A loom's
angular size grows slowly and then explosively, so it spends most of its frames small and a
1.5x-of-current bound is small with it. A linear ramp spends far longer large, which is where an
oversized bound starts costing fill, and there it is a wash on the fill-limited renderer.

**A bound sized for the maximum is never a safe default.** 92x overdraw on the first frame of that
loom: +0.012 ms on the A4500, +0.428 ms on llvmpipe. Thirty-five times apart, crossing the 0.064 ms
rebuild cost in opposite directions.

**For a shape that moves but keeps its size there is no bound question at all.** Build once, rotate
per frame -- `_carry_edge` already carries the declaration through a rotation. That is 6x cheaper
in Python than rebuilding *and* has no overdraw, since the bound stays exactly right. The two are
complementary, keyed on whether the size changes, not alternatives.

**Whether to build either is still a judgement call on magnitude.** The saving is 0.063 ms/frame on
the A4500 and 0.035 on llvmpipe -- about 2% of the 2.78 ms budget at 360 Hz -- against caching state
added to `eval_at` for six stimuli. Worth having if a protocol ever runs many analytic stimuli at
once, or if the per-frame budget gets tight. Not urgent.

## What to check before starting

Whether MSAA can simply be made to work. If a multisampled FBO can be resolved into the
QOpenGLWidget's, §1 improves everywhere for a much smaller change, though it would not fix §2 and
would cost fill. Worth half a day before committing to shader work, and worth knowing either way,
since the code currently asks for 24x and silently receives none.

---

## Measured: can MSAA simply be made to work?

*Answering the "what to check before starting" question above.*

**Yes, through an explicit multisampled framebuffer.** The surface-format route is a dead end --
`setSamples(24)` is ignored because QOpenGLWidget renders into its own FBO -- but rendering into a
multisampled renderbuffer and resolving with `copy_framebuffer` works:

```
samples= 0 -> 0 partially-covered pixels on a slanted edge   (aliased)
samples= 4 -> 1 partially-covered pixels                     (antialiased)
samples=16 -> 2 partially-covered pixels                     (antialiased)
```

`ctx.detect_framebuffer()` already resolves Qt's widget FBO correctly, so the change is to render
into the multisampled one and resolve into the detected one at the end of `paintGL`.

**But it does not fit the 360 Hz budget.** 1280x800, 200 triangles, Mesa Intel:

| samples | ms/frame | max Hz | headroom at 360 Hz |
|---|---|---|---|
| 0 | 1.348 | 742 | 2.1x |
| 2 | 2.021 | 495 | 1.4x |
| 4 | 2.129 | 470 | 1.3x |
| 8 | 3.251 | 308 | **0.9x** |
| 16 | 6.428 | 156 | **0.4x** |

At 360 Hz the frame budget is 2.78 ms. 4x samples leaves 1.3x headroom on an integrated GPU with a
trivial scene -- before the cube pass, before a real stimulus, before the subframe multiplexing
that draws the scene three times per frame. 8x does not fit at all.

So MSAA is affordable at 120 Hz and marginal at 360. That is an argument for analytic coverage
rather than against antialiasing: `smoothstep` over `fwidth` costs a few instructions in a shader
that already runs, has no framebuffer cost, and does not multiply with the subframe count.

**Worth doing anyway, in one respect.** `make_qt_format` currently asks for 24x and silently
receives none. Whatever is decided about antialiasing, that request should either be made to work
or be removed with a comment saying why -- leaving it is a claim the code does not deliver.

### Where it landed

Built, as `Screen(msaa_samples=n)`, defaulting to none. What it earns is narrower than "it
antialiases everything": **it quantises edge position to 1/n of a pixel rather than a whole one.**
A finer staircase, not the continuous sub-pixel motion an analytic edge gives. A box drifting at
2 deg/s at 360 Hz, largest single jump in edge position:

| samples | 0 | 2 | 4 | 8 | 16 | *analytic edge* |
|---|---|---|---|---|---|---|
| jump | 1.000 px | 0.502 | 0.251 | 0.126 | 0.063 | *0.024* |

So it is not for shapes that already carry an equation -- it leaves those alone to within 0.04% of
their total light, which is what makes it safe to leave on. It is for the geometry that can never
carry one: `MovingBox`, `Tower`, `Forest`, the labpack's `GlFly`, and anything else assembled with
`add()`.

Rig-specific because the cost is, by more than an order of magnitude. A 16-tree forest at
1920x1080: 1.7% of a 360 Hz frame at 4x and 5.7% at 16x on an RTX A4500; 89% at 4x on a software
rasteriser, where 8x does not fit at all. Measure on the rig before raising it.

### It reaches the flat path fully and the curved path barely

`msaa_samples` multisamples the framebuffer `paintGL` draws into. On a **planar** screen that is the
stimulus geometry itself. On a **curved** screen it is not: the scene is rasterised into the cube
faces first -- ordinary single-sample framebuffers -- and the only thing drawn into the multisampled
target is the warp pass, one draw of the screen mesh. Stimulus edges are already fixed in the cube
by the time multisampling sees anything; what gets antialiased is the mesh's own silhouette.

Partially-covered pixels along the edges of a 16-tree forest, Quadro M2000, 1280x800:

| path | 0x | 4x | 16x |
|---|---|---|---|
| planar | **0** | 1526 | 2060 |
| curved | 1506 | 1789 | 3221 |

Two things to read off it. The planar row is the case the feature exists for -- literally no
intermediate pixels at all, a fully hard staircase, fixed at 4x. And the curved row *starts* at
1506 rather than 0, because the warp is already antialiasing: it samples the cube bilinearly while
**minifying**, 17.1 px/deg of cube into a projector that resolves 12.0, so it averages as it goes.

### Multisampling the cube faces: prototyped, not built

Core GL 3.3 has no multisampled cube map, so a face cannot be rendered into directly. The route is
one multisampled renderbuffer reused for every face -- draw the scene into it, resolve it into that
face's framebuffer, which already points at the cube texture. Memory does not scale with face
count; only the resolve does. About 25 lines in `CubeMapRenderer` plus a `resolve_face()` in the
face loop.

Measured on the BrukerJr bowl, 3 faces, forest as above:

| cube res | px/deg | samples | VRAM | partial px | ms/frame |
|---|---|---|---|---|---|
| 768 | 8.5 | 0 | 14M | 2948 | 0.61 |
| 768 | 8.5 | 4 | 33M | 4352 | 1.21 |
| 1280 | 14.2 | 0 | 39M | 1812 | 0.71 |
| **1536** | 17.1 | 0 | 57M | 1506 | **0.78** |
| 1536 | 17.1 | 4 | 132M | 2180 | **2.60** |
| 1536 | 17.1 | 16 | 359M | 2232 | 5.84 |
| 2048 | 22.8 | 0 | 101M | 1108 | 0.88 |

**Not worth building at this rig's settings.** 4x more than triples the cube pass for a 1.4x change
that saturates immediately -- 4x, 8x and 16x are within 2% of each other.

The 768 row says why, and says when it would be worth it. Where the cube is *coarser* than the
projector, multisampling does a lot: 2948 -> 4352. Where it is finer, the warp's minification has
already done that job, and extra samples add detail below what the projector can display. So the
condition is not "is the geometry aliased" but **is the cube coarser than the optics**.

And in that regime resolution is the cheaper lever, because it is not equivalent to samples:
1536 -> 2048 costs +0.10 ms and takes 1506 -> 1108, a larger quality change than 4x MSAA at a
twentieth of the cost. Resolution helps because the warp then averages more texels per output
pixel; samples help only *within* a texel the warp is already averaging away. Cube MSAA only wins
where a rig is at its resolution ceiling -- VRAM, or clears dominating -- and still cube-limited.

### Coverage is alpha, and alpha is order-dependent

A partially covered fragment writes depth as though it were fully covered. So a near shape's edge
depth-rejects whatever is behind it and blends against the background instead, and an opaque scene
renders differently depending on draw order. Two spots at 0.8 m and 2.0 m, overlapping: **88 pixels
differ between the two orders, by up to 255**.

It is real, and it is latent. Three measurements bound it:

| case | pixels differing |
|---|---|
| overlapping, different depths | 88 |
| overlapping, **same depth** | 0 |
| different depths, not overlapping | 0 |

Same-depth is the case that matters, because it is what actually renders: every protocol in the
labpack this was found on uses `sphere_radius: 1` throughout. Co-planar fragments never
depth-reject each other.

And the framework's own ordering is the correct one. `BaseProtocol.load_stimuli` sends
`ConstantBackground` before the trial's own stimuli, so the far surface is in the colour buffer
before the near one's edge blends over it. Against a 4x supersampled reference:

```
skybox first (as shipped)   mean |err| 0.035 per pixel
stimulus first              mean |err| 0.433
```

So the trap needs a near analytic shape loaded *before* a far one, which nothing does today.
`tests/gl/test_draw_order.py` pins all of it, with the defect itself recorded as a strict `xfail`
so that fixing it fails the suite rather than leaving a stale note behind.

**The fix, when it is worth making.** Not sorting -- that is per-frame work, needs a depth per
stimulus that a general shape does not have, and still leaves overlaps inside one composite. Split
the draw instead: a global interior pass that writes depth in any order, then a global edge pass
that blends with depth testing but no depth write. Correct regardless of edge order, no sorting,
and the residual error is edge-against-edge, which is a few pixels. It costs double the draw calls
and has to be global across `stim_list` rather than per stimulus, which makes it architectural.

`GL_SAMPLE_ALPHA_TO_COVERAGE` is the other candidate: correct by construction and no second pass,
but it quantises coverage to 1/n, which gives back most of what an analytic edge buys, and it needs
multisampling on -- off by default and per-rig. Worth measuring against the two-pass split rather
than assumed either way.

### Revised recommendation

1. Fix or remove the ineffective `setSamples(24)`, and report the granted count at start-up.
2. Write the two edge tests (transition width; per-frame edge movement).
3. Analytic edges for `GlSphericalCirc` and `GlCircle`. This is the main event: it fixes the
   polygon error, which MSAA cannot, and buys sub-pixel edge position without a per-frame cost.
4. Consider 4x MSAA as a per-rig option for 120 Hz rigs, off by default. It antialiases everything
   including geometry that has no analytic form, which is a genuine complement to (3).
