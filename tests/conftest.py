"""Shared fixtures/config for the stimpack test suite.

Test tiers (see markers in pyproject.toml):
  - unit        : pure logic, no hardware/GL/GUI. Runs everywhere, fast.
  - integration : real client/protocol/data objects over a fake RPC link.
  - gui         : drives the real PyQt6 GUI (offscreen).
  - gl          : needs an OpenGL context; uses a standalone headless moderngl context.
  - e2e         : a LIVE server with real screen (and KeyTrac) subprocesses.
  - hardware    : needs a real rig (DAQ/projector/tracker). Not run in CI.

A bare `pytest` runs everything in one process and passes. Tiers can also be run individually:

    pytest -m unit && pytest -m "integration or gui" && pytest -m gl && pytest -m e2e

(This used to segfault. Two real bugs caused it, both since fixed: runSeriesThread defined a
__del__ that called self.wait(), so a QThread was touched at arbitrary GC time; and
ExperimentGUI.closeEvent never disconnected or waited for that thread, so its finished signal could
fire into a destroyed window. MySocketClient also had no way to stop its reader thread. Keep the
whole-suite run in CI -- it is what catches this class of bug.)

Running the suite must not take over the desktop it runs on. Two things are done about that, below:
the process itself renders offscreen, and the screen subprocesses -- which need a real GL context,
so they cannot be offscreen -- open without taking focus. Both are overridable, so you can still
watch a run. For a run that is invisible as well as unfocused, use a virtual display:
`xvfb-run -a pytest`.

The e2e tier launches real screen subprocesses, so stimulus windows still appear briefly (they are
torn down when the server closes); they just no longer steal your keyboard.
"""
import os

import pytest

# The GUI tier's own docstring calls itself offscreen, but nothing here made it so: locally the
# ExperimentGUI, its modal dialogs and the KeyTrac subprocess all opened real windows and took
# focus. CI has always set this; now a workstation run behaves the same way.
#
# setdefault, not assignment: `QT_QPA_PLATFORM=wayland pytest -m gui` still shows you the GUI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Screen subprocesses cannot use the offscreen platform -- they need a real GL context -- so they
# stay visible, and instead open without activating. See framework.main() and unobtrusive_screen().
os.environ.setdefault("STIMPACK_NO_FOCUS", "1")


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
