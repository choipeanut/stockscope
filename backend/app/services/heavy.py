"""Process-wide guard for memory-heavy jobs (dataset builds, catalyst runs).

On a 512 MB box the failure mode isn't one job being too big — locally each
peaks ~150 MB — it's TWO running at once (predict dataset build + catalyst run +
walk-forward eval, triggered by different tabs/polls) stacking their peaks past
the limit. A single global semaphore serialises all of them so peak memory is
bounded to one job at a time, no matter how many requests pile up.

Background workers should wrap their body in `with heavy_slot():`. It blocks
until the previous heavy job finishes — fine, since these already run in
detached threads behind a polling API.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

# Exactly one heavy job process-wide.
_heavy_lock = threading.Lock()


@contextmanager
def heavy_slot():
    _heavy_lock.acquire()
    try:
        yield
    finally:
        _heavy_lock.release()
