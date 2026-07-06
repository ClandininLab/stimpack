# GL reference images (golden images)

`test_stimuli_render.py` renders each stimulus headlessly and compares it to a committed reference
PNG in this directory. These references are the source of truth for "the stimulus renders correctly",
so they must be **generated once, reviewed by eye, and committed**.

## Generating / updating references

```bash
# Generate (or regenerate) every reference PNG in this directory:
xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 pytest -m gl --update-goldens

# Then LOOK at the PNGs and confirm each shows what it should
# (a centered spot, a grating, etc.) before committing them.
git add tests/gl/reference/*.png && git commit
```

Once references exist, `pytest -m gl` compares against them and fails if a change alters the output.
When a change *intentionally* changes rendering, regenerate, re-review, and commit the new PNGs.

## Why software GL

Different GPUs/drivers rasterize edges and anti-aliasing slightly differently, so a reference made on
one machine can spuriously fail on another. Generate references with the **software** GL driver
(`LIBGL_ALWAYS_SOFTWARE=1`, i.e. Mesa llvmpipe) — the same backend CI uses — so the committed images
are reproducible everywhere. The comparison uses a small mean-absolute-error tolerance (per case) to
absorb any remaining minor differences; widen a case's `tol` in `test_stimuli_render.py` if needed.

## On failure

Mismatches write `tests/gl/_failures/<case>.actual.png` and `<case>.diff.png` for inspection (CI
uploads them as an artifact). That directory is git-ignored.
