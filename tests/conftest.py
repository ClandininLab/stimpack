"""Shared fixtures/config for the stimpack test suite.

Test tiers (see markers in pyproject.toml):
  - unit     : pure logic, no hardware/GL/GUI. Runs everywhere, fast.
  - gl       : needs an OpenGL context; uses a standalone headless moderngl context (xvfb in CI).
  - hardware : needs a real rig (DAQ/projector/tracker). Not run in CI.
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Render and (over)write GL reference images instead of comparing against them.",
    )


@pytest.fixture
def update_goldens(request):
    return request.config.getoption("--update-goldens")


@pytest.fixture
def headless_gl():
    """A standalone headless moderngl context for GL tests; skips if none is available."""
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as e:  # no GPU / display / software GL available
        pytest.skip(f"No headless GL context available: {e}")
    yield ctx
    ctx.release()
