# Plan: projector-space ray casting

*Companion to `projector-space-raycast.md`, which argues why. This is what to build, in what order,
and where to stop.*

The organising principle is that **every phase is independently useful and every gate can end the
project**. Nothing here requires committing to the renderer before knowing whether it pays.

---

## Phase 0 — find out whether it pays

**Deliverable.** `ScreenMesh.projector_resolution()`, reporting projector px/deg across the screen
for a given surface and projector, plus the cube resolution that would match its best region. We
already model both, so this is arithmetic on data in hand — the same calculation flymax does in
`stimgen/calculatePixelsOnSphere.m`.

Report, per rig: px/deg at the best and worst points on the screen, the ratio, and the cube
resolution at which the intermediate stops being the bottleneck.

**Also measure the second claim, which is independent of the first.** Motion quantisation depends
on cube texel size against per-frame displacement, not on the projector:

| stimulus speed | edge movement per frame at 360 Hz | cube texels |
|---|---|---|
| 5 °/s | 0.0139° | 0.16 — frozen ~6 frames |
| 20 °/s | 0.0556° | 0.63 — frozen ~1.6 frames |
| 40 °/s | 0.1111° | 1.26 — moves every frame |

There is no multisampling on the cube faces, so a patch edge lands on a texel boundary and stays
there. Below ~32 °/s the intermediate is discarding temporal resolution that 360 Hz exists to
provide. Confirm this on a rig with a photodiode or a high-speed camera before trusting the
arithmetic.

**Gate.** If the projector is coarser than the cube everywhere on every rig in use, *and* nobody
runs stimuli below ~32 °/s, stop. The cube is fine and this note is the record of why.

**Cost.** Small. Days, not weeks. Useful on its own as a rig-commissioning tool regardless of what
follows.

---

## Phase 1 — shapes keep their analytic identity

Prerequisite for everything after, and worth doing on its own merits.

Today every transform destroys what it operates on:

```python
def scale(self, amt):
    return GlVertices(vertices=util.scale(self.vertices, amt), ...)
```

`GlIcosphere(...).scale(...)` returns a plain `GlVertices`: the subclass is gone and the transform
is baked into vertex data.

**Deliverable.** Transforms preserve the subclass and accumulate a 4×4 matrix instead of rewriting
vertices. Shapes gain `analytic_form()`, returning a primitive description or `None`.

**Independent benefit.** A shape can be re-transformed without regenerating its vertices. `GlFly`
is 102,400 triangles rebuilt on every move today; it becomes a matrix update.

**Risks.** The labpack subclasses `GlVertices` and relies on the current chaining behaviour, so
this is an API change with an out-of-repo consumer. Vertices must still be produced on demand for
the cube path, so laziness has to be genuinely lazy.

**Gate.** Both repositories' test suites pass, and `clandinin_labpack`'s stimuli still render
identically. This one is checkable by golden image.

---

## Phase 2 — a scene description that is not vertices

**Deliverable.** Walk a stimulus's shape tree and produce either a list of analytic primitives with
transforms, or `None` if anything in it cannot be described. Pure Python, no GL, fully testable.

**Measure the coverage this buys.** For every stimulus in stimpack and in `clandinin_labpack`,
report whether it yields a complete analytic description. The survey in the companion note says it
should be all of them; this turns that into a number that cannot rot.

**Gate.** If coverage is low, the fast path is a curiosity. Expect it to be high.

**Cost.** Small, and it is all in Python.

---

## Phase 3 — a spike: one stimulus, end to end

Do not build a general renderer yet. Build the narrowest thing that answers whether the gains are
real: **`MovingPatch`, ray-cast, against the cube path, side by side.**

**Deliverable.** A fragment shader that traces one primitive type, the screen mesh rendered into
the projector framebuffer, and a comparison test in the manner of `test_curved_vs_planar.py` —
which is already the pattern for checking one rendering path against another, and which found two
real bugs when it was written for the curved path.

**Measure exactly the three claimed gains.**

1. **Edge sharpness** — the transition width of a patch boundary, in degrees, both paths.
2. **Motion quantisation** — step a patch across the screen at 20 °/s and record the edge position
   per frame. The cube path should show a staircase; the ray-cast path should not.
3. **Fill** — pixels touched per frame, both paths.

**Gate.** If the measured gains do not match the predictions, stop. This is the phase that either
justifies the rest or ends it, and it should be reached before any broad implementation.

---

## Phase 4 — coverage, in order of what is used

Only after Phase 3. Add primitives in the order the libraries actually need them:

1. **ellipsoid** (sphere under transform) — `GlSphericalRect`, `GlSphericalCirc`, `GlIcosphere`, `GlFly`
2. **cylinder**, bounded — the most-used primitive in the library, 8 uses
3. **plane / disc** — `GlQuad`, `GlCircle`, `Floor`, wings
4. **box** — CSG of six half-spaces

Then textures: each primitive needs an analytic UV parameterisation. Sphere and cylinder have
natural ones; a plane's is its own coordinates.

**The hard part is transparency.** The cube path gets compositing from the depth buffer and blend
state. Ray casting has to collect hits along the ray, sort them, and composite by hand.
`GlCylinder` already takes `alpha_by_face`, so this is in use, not hypothetical. Treat it as its
own piece of work with its own test, and consider whether the first release simply refuses
translucent primitives on the fast path.

---

## Phase 5 — selection and fallback

Fallback is what makes this safe, and the question is what granularity it works at. Three answers,
only one of which is right.

**Per shape, mixed within a scene: possible, and not worth it.** The cube pass can write a depth
cube beside the colour cube; warp both into the projector framebuffer, then run the ray-cast pass
with depth testing, and the two composite correctly. Nothing becomes unrenderable. But a scene
containing one non-analytic shape already pays five scene draws and 5.24 Mpx of fill, so the traced
pass is added cost rather than saved cost -- mixed is *slower* than pure cube. It also makes
transparency much harder, since blending needs an ordering the two paths do not share.

**Per stimulus, chosen automatically: correct, and quietly dangerous.** Consider a protocol whose
conditions include a moving patch and something the cube must draw. The patch arrives with 0.029
degree edges and smooth motion; the other with 0.088 degree edges and a motion staircase below
32 deg/s. Those conditions now differ in a way that has nothing to do with the experiment, and it
would pass every test, because each image is correct in isolation. In a game engine that is a
quality setting. Here it is a confound.

**Per experiment, declared: the rule to adopt.** The render path is a property of the run, not of
each stimulus. If anything in a protocol -- or in an ensemble -- needs the cube, everything uses the
cube, so every condition an animal sees is rendered identically. Uniformity across conditions
matters more than the quality of any single one.

**Deliverable.**

- resolve the path once, from the whole set of stimuli a run will present, before the run starts
- refuse rather than silently downgrade: if the config asks for the traced path and a stimulus
  cannot take it, say which stimulus and why, at protocol-check time, not mid-run
- record the path in the data file next to `stimpack_version` and `data_format`, so analysis can
  tell how a series was rendered without being told
- report it in `--check-labpack`, which already exercises every protocol: which would trace, which
  would not, and what stopped them

---

## Risks, in the order they are likely to bite

**Per-fragment cost scales with primitive count.** `Forest` is many cylinders and a fragment must
test each one. At 1 Mpx and 360 Hz, ten primitives is 3.7 G intersection tests per second. This is
the risk most likely to end the project, and it is invisible until Phase 3 has a working tracer —
so measure primitive counts per scene during Phase 2, and treat anything past a few dozen as
requiring spatial acceleration, which is a different project.

**Transparency**, as above.

**Numerical precision.** A naive quadratic solve loses precision on grazing rays, which is exactly
the geometry at a bowl's rim. Use the stable form; test at grazing incidence specifically.

**Two paths must agree.** Any divergence between cube and ray-cast is a silent change in what an
animal saw. The comparison test from Phase 3 has to keep running across the whole primitive set,
not just for the spike.

**Labpack API churn.** Phase 1 changes a class the labpack subclasses. Coordinate it, and keep
`clandinin_labpack` rendering identically as the acceptance test.

---

## What this is not

Not a replacement for the cube. The cube stays as the general path, the fallback, and the thing
that makes arbitrary geometry possible. This adds a fast path for the geometry stimpack actually
draws, and it has to be opt-in-able and always overridable.

Not a return to flystim 1.0. Stimuli are still composed in Python from shapes; nobody writes GLSL
to add a stimulus. What changes is that a primitive is a declaration rather than a vertex buffer.

---

## Suggested order of work

1. Phase 0 diagnostic. Run on every rig in use. **Decide whether to continue.**
2. Phase 1, on its own merits, whatever Phase 0 said.
3. Phase 2 coverage survey.
4. Phase 3 spike on `MovingPatch`. **Decide whether to continue.**
5. Phases 4 and 5 only if the spike's numbers hold.
