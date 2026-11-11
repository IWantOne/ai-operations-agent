"""Durable work vocabulary; a diagnostic state never replaces error evidence."""
from dataclasses import dataclass
from typing import Callable

TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT", "NEEDS_REVIEW"})
PENDING = frozenset({"QUEUED", "RETRY_WAIT", "RUNNING"})


@dataclass(frozen=True)
class Executor:
    execute: Callable
    lane: str
    restart_safe: bool = False
    # Cancellation of an await does not stop a thread or an external side effect.
    # Only managed execution boundaries may opt in after stopping their children.
    interruptible: bool = False


