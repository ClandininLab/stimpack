"""The suite must not take over the desktop it runs on.

Screen subprocesses need a real GL context, so they cannot render offscreen the way the rest of the
suite does -- their windows really do appear. What they must not do is take the keyboard: a test run
lasting a minute used to steal focus repeatedly from whoever was working while it ran.

Both checks here are structural. The property they protect -- "the window did not take focus" -- can
only be observed with a real compositor, so no assertion in CI can catch a regression directly; it
was verified by measurement (X11/XWayland honours the hint, wayland ignores it) and these keep the
mechanism that measurement validated from being quietly removed.
"""
import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TESTS_DIR = Path(__file__).resolve().parents[1]

# Tiers whose Screens get handed to a server, and so become real windows. Screens built in the unit
# and gl tiers are geometry/standalone-context objects that never open one.
WINDOWING_TIERS = ('e2e', 'integration')


def test_windowing_tiers_build_screens_through_the_unobtrusive_helper():
    """Screen(...) straight from a test that launches a server reintroduces focus theft.

    helpers.unobtrusive_screen names an X display, which selects the xcb platform, which is where a
    window is allowed to decline focus. A plain Screen() on a Wayland session gets the wayland
    plugin, under which the compositor decides focus and mutter activates every new toplevel.
    """
    offenders = []
    for tier in WINDOWING_TIERS:
        for path in sorted((TESTS_DIR / tier).glob('*.py')):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'Screen':
                    offenders.append(f'{path.relative_to(TESTS_DIR)}:{node.lineno}')

    assert not offenders, (
        'construct screens with helpers.unobtrusive_screen() instead of Screen() in the '
        f'{"/".join(WINDOWING_TIERS)} tiers, so test windows do not steal focus: '
        + ', '.join(offenders))


def test_screen_windows_can_be_told_not_to_take_focus():
    """framework.main must still consult STIMPACK_NO_FOCUS and act on it before showing the window.

    Setting the attribute after show() would be too late, so the order is checked too.
    """
    import inspect
    import textwrap
    from stimpack.visual_stim import framework

    tree = ast.parse(textwrap.dedent(inspect.getsource(framework.main)))

    reads_env = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and n.value == 'STIMPACK_NO_FOCUS']
    assert reads_env, 'framework.main no longer consults STIMPACK_NO_FOCUS'

    declines_focus = [n.lineno for n in ast.walk(tree)
                      if isinstance(n, ast.Attribute) and n.attr == 'WA_ShowWithoutActivating']
    assert declines_focus, 'framework.main no longer sets WA_ShowWithoutActivating'

    shows = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) in ('show', 'showFullScreen')]
    assert shows, 'framework.main no longer shows the window at all'
    assert min(declines_focus) < min(shows), \
        'WA_ShowWithoutActivating is set after the window is shown, which is too late to matter'
