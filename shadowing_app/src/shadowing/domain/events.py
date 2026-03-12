from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SessionStarted:
    lesson_id: str


@dataclass(slots=True)
class SessionStopped:
    lesson_id: str
    reason: str


@dataclass(slots=True)
class PlaybackHeld:
    reason: str


@dataclass(slots=True)
class PlaybackResumed:
    reason: str


@dataclass(slots=True)
class PlaybackSeeked:
    target_time_sec: float
    reason: str