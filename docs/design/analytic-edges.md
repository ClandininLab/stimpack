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

That second point is the boundary of what this approach reaches: a shape can declare an edge only
if it is drawn as itself. It costs nothing here -- the fly is 102,400 triangles of icosphere, and
its wings are not where its quality lives -- but it is worth stating, because it is the question to
ask of any future candidate before converting it.

### What a shape declares

The disc needed a centre direction and an angle. A rectangle needs an *orientation* -- "20 degrees
wide" is a statement about a frame, not about a point -- so the declaration is a frame and a pair
of half-extents, which covers both:

```python
EDGE_KIND = EDGE_ANGULAR_RECT
self.edge_frame = CANONICAL_PATCH_FRAME          # azimuth, elevation, forward; rows
self.edge_extent = (radians(width) / 2, radians(height) / 2)
```

Every shape here is built facing forward and rotated into place by its stimulus, so the frame has
to turn with it. Rotations carry the declaration and rotate the frame; translation and scaling drop
it, because they move the shape off the sphere its angular size was measured against, and a wrong
analytic edge is worse than none.

The bound is widened by `EDGE_BOUND_MARGIN` rather than being exact. A rectangle's constant-azimuth
sides are great circles, which triangle edges follow *exactly* -- flush against the bound with
nothing to spare -- so rounding at a corner could nick a real sliver off the patch, and a fragment
shader can only remove coverage, never add it. The disc needs no margin: its bound is an octagon
circumscribing the circle, so only the eight tangent points come close.

The two kinds share their arithmetic. Each answers one question -- how far outside the shape this
fragment is -- and the coverage step is then the same three lines for both, which is what keeps
this from becoming a shader per shape. The units are the kind's own choice, because `excess` is
divided by `fwidth(excess)` and both scale together: the ratio is always "how many pixels outside".

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
where there is no single boundary to antialias and mipmaps would be the answer instead.

Cost: 0.028 to 0.029 ms per frame on a full-field checkerboard at 1280x800 -- about a microsecond,
against a 2.78 ms budget at 360 Hz.

## What is left, and what is out of reach

`GlCylinder` is the remaining cylindrical shape, and it is a different animal -- a world-space
solid, not an angular patch, so its boundary would be an equation in metres about its axis rather
than in degrees about the subject. Its ten users split three ways:

- **The panoramic textured stimuli** are handled by the sharp-texel sampling above rather than by
  a shape declaration, since their edges are inside the texture.
- **`Forest`** builds one cylinder and `add()`s a translated copy per tree. Both of those drop the
  declaration, for the reasons above. Out of reach, exactly like the fly's wings.
- **`Tower`** is the one genuine candidate: a single cylinder, whose 32-gon silhouette sits inside
  the true circle by 0.48% of the radius -- 0.046 degrees, about half a pixel, for the default
  0.5 m tower at 3 m. Half a pixel is not much, and buying it costs a world-space kind plus
  translation carry rules. Not obviously worth it; measure on a rig before deciding.

`GlCircle` remains unconverted for the reasons given above.

The test to write first is the one that would have caught this: render a disc, measure the width of
its intensity transition in degrees, and assert it is about one pixel rather than zero. A companion
test steps a disc across the screen at 5 °/s and asserts the measured edge position changes every
frame -- which today it does not.

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

### Revised recommendation

1. Fix or remove the ineffective `setSamples(24)`, and report the granted count at start-up.
2. Write the two edge tests (transition width; per-frame edge movement).
3. Analytic edges for `GlSphericalCirc` and `GlCircle`. This is the main event: it fixes the
   polygon error, which MSAA cannot, and buys sub-pixel edge position without a per-frame cost.
4. Consider 4x MSAA as a per-rig option for 120 Hz rigs, off by default. It antialiases everything
   including geometry that has no analytic form, which is a genuine complement to (3).
