"""Which frame does the first photodiode edge mark?

The corner square is the timing signal everything is aligned by, and a protocol starts a trial by
sending start_stim and corner_square_toggle_start in one batch while the square sits at its idle
level (black). The square used to draw first and invert afterwards, so the first stimulus frame
was painted at the idle level and the photodiode saw nothing until the second frame: every onset
measured from the first edge was one refresh late. These drive the real SquareProgram's state
machine through a fake GL context and read back what was actually drawn each frame.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")

from stimpack.visual_stim.square import SquareProgram  # noqa: E402

pytestmark = pytest.mark.unit


class FakeUniform:
    value = None


class FakeProgram:
    def __init__(self):
        self.color = FakeUniform()

    def __getitem__(self, name):
        assert name == 'color'
        return self.color


class FakeVao:
    """Records the colour uniform at each render: the level the frame was drawn with."""

    def __init__(self, program, drawn):
        self.program = program
        self.drawn = drawn

    def render(self, mode=None):
        self.drawn.append(self.program.color.value)


def square_on_a_fake_display():
    square = SquareProgram(screen=SimpleNamespace(use_egl=False))
    drawn = []
    square.ctx = SimpleNamespace(viewport=None)
    square.viewport = (0, 0, 8, 8)
    square.prog = FakeProgram()
    square.vao = FakeVao(square.prog, drawn)
    return square, drawn


def idle(square):
    """What the client and every protocol leave the square at between trials."""
    square.toggle_stop()
    square.turn_off()


def test_the_first_toggled_frame_is_the_first_edge():
    """Three idle frames at black, then toggle_start between two refreshes, as start_stimuli sends
    it: frame 0 of the stimulus must already differ from the idle level."""
    square, drawn = square_on_a_fake_display()
    idle(square)
    for _ in range(3):
        square.paint()
    square.toggle_start()
    for _ in range(4):
        square.paint()

    assert drawn == [0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0]


def test_turning_the_square_on_holds_it_white():
    """corner_square_on's docstring promises it stops the toggling. It did not, which is what made
    the first-frame workaround in labpacks possible; now it does."""
    square, drawn = square_on_a_fake_display()
    square.toggle_start()
    square.turn_on()
    for _ in range(3):
        square.paint()

    assert drawn == [1.0, 1.0, 1.0]


def test_stopping_after_a_trial_returns_to_the_idle_level():
    """The tail-time batch: toggle_stop then corner_square_off, whatever phase the toggling was in."""
    square, drawn = square_on_a_fake_display()
    idle(square)
    square.toggle_start()
    for _ in range(3):
        square.paint()
    square.toggle_stop()
    square.turn_off()
    for _ in range(2):
        square.paint()

    assert drawn[-2:] == [0.0, 0.0]


def test_a_hidden_square_keeps_toggling():
    """hide_corner_square's contract: nothing drawn, but the phase advances, so showing it again
    does not shift the photodiode's view of which frames were which."""
    square, drawn = square_on_a_fake_display()
    idle(square)
    square.toggle_start()
    square.draw = False
    for _ in range(3):
        square.paint()
    square.draw = True
    square.paint()

    assert drawn == [0.0]
