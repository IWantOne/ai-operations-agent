"""Execution clock using the agreed movable start / frozen stop timestamps."""
from __future__ import annotations


def start(now: float) -> tuple[float, None]:
    return now, None


def elapsed(started: float | None, stopped: float | None, now: float) -> float:
    if started is None:
        return 0.0
    return max(0.0, (now if stopped is None else stopped) - started)


def freeze(started: float | None, stopped: float | None, now: float) -> tuple[float | None, float | None]:
    if started is None or stopped is not None:
        return started, stopped
    return started, max(started, now)


def resume(started: float | None, stopped: float | None, now: float) -> tuple[float, None]:
    if started is None:
        return start(now)
    if stopped is None:
        return started, None
    return now - elapsed(started, stopped, now), None
