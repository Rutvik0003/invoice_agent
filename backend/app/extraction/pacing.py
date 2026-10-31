"""Keeps AI requests at least AI_REQUEST_GAP_S seconds apart, across every run in this server process.

Free tiers limit requests per minute. Live runs, batches and the Test Suite all pass through here before the
model is called, so a batch of 20 invoices never bursts past the limit.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

_lock = threading.Lock()
_last_request = float("-inf")


def wait_for_turn(gap_s: float, sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic) -> float:
    """Block until gap_s has passed since the previous AI request, then claim this slot. Returns seconds waited."""
    global _last_request
    with _lock:
        waited = max(0.0, _last_request + gap_s - clock())
        if waited > 0:
            sleep(waited)
        _last_request = clock()
        return waited


def reset() -> None:
    """Forget the previous request (tests)."""
    global _last_request
    with _lock:
        _last_request = float("-inf")
