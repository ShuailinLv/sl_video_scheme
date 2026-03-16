from __future__ import annotations

from shadowing.interfaces.controller import Controller
from shadowing.types import (
    AudioBehaviorSnapshot,
    AudioMatchSnapshot,
    ProgressEstimate,
    SignalQuality,
    TrackingSnapshot,
)


class StateMachineController(Controller):
    def __init__(
        self,
        *,
        progress_estimator,
        control_policy,
    ) -> None:
        self._progress_estimator = progress_estimator
        self._control_policy = control_policy

        self._running = False
        self._last_progress: ProgressEstimate | None = None
        self._last_signal_quality: SignalQuality | None = None
        self._last_tracking_snapshot: TrackingSnapshot | None = None
        self._last_audio_match_snapshot: AudioMatchSnapshot | None = None
        self._last_audio_behavior_snapshot: AudioBehaviorSnapshot | None = None

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def snapshot(self) -> ProgressEstimate | None:
        return self._last_progress

    def on_asr_event(self, event) -> None:
        _ = event

    def on_signal_quality(self, signal_quality: SignalQuality) -> None:
        self._last_signal_quality = signal_quality

    def on_tracking_snapshot(self, snapshot: TrackingSnapshot) -> None:
        self._last_tracking_snapshot = snapshot

    def on_audio_match_snapshot(self, snapshot: AudioMatchSnapshot) -> None:
        self._last_audio_match_snapshot = snapshot

    def on_audio_behavior_snapshot(self, snapshot: AudioBehaviorSnapshot) -> None:
        self._last_audio_behavior_snapshot = snapshot

    def on_playback_generation_changed(self, now_sec: float) -> None:
        if hasattr(self._progress_estimator, "on_playback_generation_changed"):
            self._progress_estimator.on_playback_generation_changed(now_sec)

    def tick(self, now_sec: float) -> ProgressEstimate | None:
        if not self._running:
            return self._last_progress

        progress = self._progress_estimator.update(
            tracking=self._last_tracking_snapshot,
            audio_match=self._last_audio_match_snapshot,
            audio_behavior=self._last_audio_behavior_snapshot,
            signal_quality=self._last_signal_quality,
            now_sec=float(now_sec),
        )
        self._last_progress = progress

        if progress is not None and hasattr(self._control_policy, "update"):
            self._control_policy.update(progress=progress, now_sec=float(now_sec))

        return progress