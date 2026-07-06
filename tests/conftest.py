"""Shared fixtures for the stimpack test suite.

Test tiers (see markers in pyproject.toml):
  - unit     : pure logic, no hardware/GL/GUI. Runs everywhere, fast.
  - gl       : needs an OpenGL context; uses a standalone headless moderngl context (xvfb in CI).
  - hardware : needs a real rig (DAQ/projector/tracker). Not run in CI.
"""
import pytest


@pytest.fixture
def headless_gl():
    """A standalone headless moderngl context for GL tests; skips if none is available."""
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as e:  # no GPU / display available in this environment
        pytest.skip(f"No headless GL context available: {e}")
    yield ctx
    ctx.release()
