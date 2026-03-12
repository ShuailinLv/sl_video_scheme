from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StartSession:
    lesson_id: str


@dataclass(slots=True)
class StopSession:
    reason: str = "user_requested"


@dataclass(slots=True)
class HoldPlayback:
    reason: str


@dataclass(slots=True)
class ResumePlayback:
    reason: str


@dataclass(slots=True)
class SeekPlayback:
    target_time_sec: float
    reason: str