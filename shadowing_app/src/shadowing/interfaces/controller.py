from __future__ import annotations

from typing import Protocol, runtime_checkable

from shadowing.types import (
    AudioBehaviorSnapshot,
    AudioMatchSnapshot,
    ProgressEstimate,
    SignalQuality,
    TrackingSnapshot,
)


@runtime_checkable
class Controller(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def tick(self, now_sec: float) -> ProgressEstimate | None:
        ...

    def snapshot(self) -> ProgressEstimate | None:
        ...

    def on_asr_event(self, event) -> None:
        ...

    def on_signal_quality(self, signal_quality: SignalQuality) -> None:
        ...

    def on_tracking_snapshot(self, snapshot: TrackingSnapshot) -> None:
        ...

    def on_audio_match_snapshot(self, snapshot: AudioMatchSnapshot) -> None:
        ...

    def on_audio_behavior_snapshot(self, snapshot: AudioBehaviorSnapshot) -> None:
        ...

    def on_playback_generation_changed(self, now_sec: float) -> None:
        ...