"""Pause the cyclic garbage collector while a block builds many objects that hold no cycle."""

import gc
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_lock = threading.Lock()
_pauses = 0
_resume = False


@contextmanager
def collector_paused() -> Iterator[None]:
    """Run the block with the cyclic collector paused; reference counting still frees.

    The collector is process-wide and blocks overlap on other threads, so pauses are
    counted: the collector resumes when the last one ends, and only if it ran when the
    first one began.
    """
    global _pauses, _resume
    with _lock:
        if _pauses == 0:
            _resume = gc.isenabled()
            gc.disable()
        _pauses += 1
    try:
        yield
    finally:
        with _lock:
            _pauses -= 1
            if _pauses == 0 and _resume:
                gc.enable()
