from __future__ import annotations

from abc import ABC, abstractmethod

from shadowing.types import AlignResult, ControlDecision, PlaybackStatus


class Controller(ABC):
    @abstractmethod
    def decide(self, playback: PlaybackStatus, alignment: AlignResult | None) -> ControlDecision: ...