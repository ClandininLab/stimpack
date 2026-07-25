"""Small helpers shared across test tiers.

Deliberately NOT in a conftest.py: several tiers have their own conftest, and `from conftest import
...` binds to whichever one Python imported first (the tier directories are not packages, so the
module name collides). That makes the suite fail to collect when it is invoked by path rather than
by marker. tests/ is on sys.path via pytest's `pythonpath` setting, so this name is unambiguous.
"""
import time


def wait_until(predicate, timeout=10.0, interval=0.05):
    """Poll predicate until it is true or timeout elapses. Returns whether it became true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
