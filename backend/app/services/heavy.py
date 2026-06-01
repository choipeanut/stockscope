"""Process-wide guard for memory-heavy jobs (dataset builds, catalyst runs).

On a 512 MB box the failure mode isn't one job being too big — locally each
peaks ~150 MB — it's TWO running at once (predict dataset build + catalyst run +
walk-forward eval, triggered by different tabs/polls) stacking their peaks past
the limit. A single global semaphore serialises all of them so peak memory is
bounded to one job at a time, no matter how many requests pile up.

But serialising execution isn't enough on its own: a finished job can leave a
big object cached in memory (e.g. the predict dataset panel, kept for an hour so
/predict can reuse /predict/eval's build). That retained memory then stacks on
top of the NEXT job's peak — so "just running the screener" OOMs because a
predict panel from an earlier tab is still resident. To fix that, jobs that
don't need those caches drop them on entry via `heavy_slot(drop_caches=True)`.

Background workers should wrap their body in `with heavy_slot():`. It blocks
until the previous heavy job finishes — fine, since these already run in
detached threads behind a polling API.
"""
from __future__ import annotations

import gc
import threading
from contextlib import contextmanager
from typing import Callable

# Exactly one heavy job process-wide.
_heavy_lock = threading.Lock()

# Callbacks that free retained, module-level caches (registered at import time).
_cache_droppers: list[Callable[[], None]] = []


def register_cache_dropper(fn: Callable[[], None]) -> None:
    """Register a callable that frees a module's retained heavy memory.

    Called by jobs that don't need those caches, so a previous job's resident
    panel/dataset can't stack onto the current job's peak and OOM the box.
    """
    _cache_droppers.append(fn)


def drop_retained_caches() -> None:
    for fn in _cache_droppers:
        try:
            fn()
        except Exception:
            pass
    gc.collect()


@contextmanager
def heavy_slot(drop_caches: bool = False):
    _heavy_lock.acquire()
    try:
        if drop_caches:
            # We hold the lock, so no other heavy job is mid-build — safe to
            # free everything another job left resident before we spike memory.
            drop_retained_caches()
        yield
    finally:
        if drop_caches:
            drop_retained_caches()
        _heavy_lock.release()
