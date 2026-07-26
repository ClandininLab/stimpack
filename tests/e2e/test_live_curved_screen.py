"""A curved screen driven end to end: real subprocess, real GL context, real frames.

The gl tier covers the geometry and the cube-map renderer against a standalone context. What it
cannot cover is the join to everything else -- that a CurvedScreen survives serialization to the
subprocess, that StimDisplay picks the cube-map path, and that paintGL actually produces frames
through it. Every one of those has failed at some point during this work while the gl tests stayed
green.
"""
import time

import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")
pytest.importorskip("PyQt6")

from helpers import wait_until          # noqa: E402 - tests/helpers.py

pytestmark = pytest.mark.e2e


def curved_screen(cube_resolution=256):
    from stimpack.visual_stim.curved_screen import (
        CurvedScreen, PinholeProjector, SphericalSurface,
    )
    return CurvedScreen(
        surface=SphericalSurface(radius=0.06, elevation_range=(-90, 0),
                                 n_azimuth=48, n_elevation=12),
        projector=PinholeProjector.wintech_pro4500(position=(0, -0.25, -0.15),
                                                   look_at=(0, 0, -0.03)),
        cube_resolution=cube_resolution,
        fullscreen=False, vsync=False, display_index=0)


@pytest.fixture(scope='module')
def curved_server():
    """A live curved screen, held until its render loop is confirmed running.

    The gate matters: paintGL is what drains the RPC queue, so until the first frame is drawn every
    command sits in the queue and a timing-sensitive test races the subprocess's boot. Asking for a
    frame count and waiting for the answer proves the whole chain -- serialization, GL context,
    cube-map path, render loop -- is up.
    """
    from stimpack.visual_stim.stim_server import VisualStimServer

    try:
        server = VisualStimServer(screens=[curved_screen()], auto_stop=False)
    except Exception as e:
        pytest.skip(f'could not launch a curved screen here: {type(e).__name__}: {e}')

    manager = server.screen_managers[0]
    messages = capture_messages(manager)

    def rendering():
        manager.report_frame_count()
        manager.process_queue()
        return any('frame_count=' in text for _, text in messages)

    if not wait_until(rendering, timeout=60, interval=0.25):
        server.close()
        pytest.skip('the curved screen subprocess never started rendering')

    server._test_messages = messages
    yield server
    try:
        server.close()
    except Exception:
        pass


def capture_messages(manager):
    """Intercept what the screen pushes back.

    VisualStimServer already registers report_server_message on each screen manager (that is how
    screen-side errors reach the client), so this replaces the handler rather than adding one.
    """
    messages = []
    original = manager.functions.get('report_server_message')

    def record(level, text):
        messages.append((level, text))
        if original is not None:
            original(level, text)

    manager.functions['report_server_message'] = record
    return messages


def frames_rendered(manager, messages, timeout=20):
    """Ask the screen how many frames it has drawn, and wait for the answer."""
    before = len(messages)
    manager.report_frame_count()

    def answered():
        manager.process_queue()
        return any('frame_count=' in text for _, text in messages[before:])

    assert wait_until(answered, timeout=timeout), 'the screen never reported a frame count'
    reported = [t for _, t in messages[before:] if 'frame_count=' in t]
    return int(reported[-1].split('frame_count=')[1].split()[0])


def test_a_curved_screen_renders_a_real_stimulus(curved_server):
    """The whole chain: serialized screen, cube-map path chosen, frames actually produced."""
    manager = curved_server.screen_managers[0]
    messages = curved_server._test_messages
    messages.clear()

    before = frames_rendered(manager, messages)

    manager.load_stim(name='MovingSpot', radius=20, sphere_radius=1,
                      color=[1, 1, 1, 1], theta=0, phi=-30)
    manager.start_stim(t=time.time())
    time.sleep(0.6)
    manager.stop_stim()

    after = frames_rendered(manager, messages)
    assert after > before, f'the curved screen drew no frames while the stimulus ran ({before} -> {after})'
    assert not [m for m in messages if m[0] == 'error'], f'errors from the screen: {messages}'


def test_a_curved_screen_reports_a_bad_stimulus_like_any_other(curved_server):
    """Error reporting has to survive the different render path, not just the happy case."""
    manager = curved_server.screen_managers[0]
    messages = curved_server._test_messages
    messages.clear()

    manager.load_stim(name='NoSuchStimulus_Curved')

    def arrived():
        manager.process_queue()
        return any(level == 'error' for level, _ in messages)

    assert wait_until(arrived, timeout=20), 'a bad stimulus produced no error from the curved screen'
    assert any('NoSuchStimulus_Curved' in text for _, text in messages)
