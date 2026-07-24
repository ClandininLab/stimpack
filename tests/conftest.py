"""Shared fixtures/config for the stimpack test suite.

Test tiers (see markers in pyproject.toml):
  - unit        : pure logic, no hardware/GL/GUI. Runs everywhere, fast.
  - integration : real client/protocol/data objects over a fake RPC link.
  - gui         : drives the real PyQt6 GUI (offscreen).
  - gl          : needs an OpenGL context; uses a standalone headless moderngl context.
  - e2e         : a LIVE server with real screen (and KeyTrac) subprocesses.
  - hardware    : needs a real rig (DAQ/projector/tracker). Not run in CI.

RUN THE TIERS SEPARATELY, as CI does:

    pytest -m unit && pytest -m "integration or gui" && pytest -m gl && pytest -m e2e

A single `pytest` over everything puts a standalone moderngl context and Qt's own GL context in one
process, which can segfault on software GL -- an interaction between the graphics stack and Qt, not
a failure of the code under test. Each tier passes on its own.

The e2e tier launches real screen subprocesses, so stimulus windows appear briefly unless you run
under a virtual display (`xvfb-run -a pytest -m e2e`). They are torn down when the server closes.
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Render and (over)write GL reference images instead of comparing against them.",
    )
    parser.addoption(
        "--save-renders",
        action="store_true",
        default=False,
        help="Write each GL test's rendered image to tests/gl/_output/ (without touching references).",
    )


@pytest.fixture
def update_goldens(request):
    return request.config.getoption("--update-goldens")


@pytest.fixture
def save_renders(request):
    return request.config.getoption("--save-renders")


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
