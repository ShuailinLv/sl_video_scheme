from __future__ import annotations

from abc import ABC, abstractmethod

from shadowing.types import ControlDecision, PlaybackStatus, ProgressEstimate, SignalQuality


class Controller(ABC):
    @abstractmethod
    def decide(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> ControlDecision: ...