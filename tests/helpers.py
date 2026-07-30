"""Small helpers shared across test tiers.

Deliberately NOT in a conftest.py: several tiers have their own conftest, and `from conftest import
...` binds to whichever one Python imported first (the tier directories are not packages, so the
module name collides). That makes the suite fail to collect when it is invoked by path rather than
by marker. tests/ is on sys.path via pytest's `pythonpath` setting, so this name is unambiguous.
"""
import os
import time


def unobtrusive_screen(**kwargs):
    """A windowed Screen that keeps out of the way of whoever is running the suite.

    Every test that builds a server with screens should use this rather than Screen() directly.

    On Linux the screen subprocess picks its Qt platform from the session (see
    stim_server.launch_screen): a Wayland session gets the wayland plugin, under which a window
    cannot decline focus -- the compositor decides, and mutter activates new toplevels regardless.
    Naming an X display selects xcb instead, where STIMPACK_NO_FOCUS is honoured, so the window
    appears without stealing the keyboard. Under a real X11 session or xvfb-run this is what would
    have happened anyway; on macOS/Windows DISPLAY is unset and nothing changes.
    """
    from stimpack.visual_stim.screen import Screen

    kwargs.setdefault('fullscreen', False)
    kwargs.setdefault('vsync', False)
    if 'x_display' not in kwargs and os.environ.get('DISPLAY'):
        kwargs['x_display'] = os.environ['DISPLAY']
    return Screen(**kwargs)


def wait_until(predicate, timeout=10.0, interval=0.05):
    """Poll predicate until it is true or timeout elapses. Returns whether it became true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
