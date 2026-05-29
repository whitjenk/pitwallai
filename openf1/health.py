"""OpenF1 availability tracker — distinguishes outage from quiet race."""

from __future__ import annotations

import time
from dataclasses import dataclass

_FAILURE_THRESHOLD = 3  # consecutive failed API calls


@dataclass
class OpenF1Health:
    consecutive_failures: int = 0
    last_error: str | None = None
    last_success_at: float | None = None

    @property
    def is_unavailable(self) -> bool:
        return self.consecutive_failures >= _FAILURE_THRESHOLD


_state = OpenF1Health()


def record_openf1_success() -> None:
    _state.consecutive_failures = 0
    _state.last_error = None
    _state.last_success_at = time.monotonic()


def record_openf1_failure(exc: BaseException) -> None:
    _state.consecutive_failures += 1
    _state.last_error = str(exc)[:200]


def openf1_health() -> OpenF1Health:
    return _state


def reset_openf1_health() -> None:
    global _state
    _state = OpenF1Health()
