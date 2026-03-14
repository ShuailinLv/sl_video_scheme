from __future__ import annotations

from shadowing.types import SignalQuality, TrackingMode, TrackingSnapshot, UserReadState


class BehaviorInterpreter:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        strong_signal_threshold: float = 0.58,
        weak_signal_threshold: float = 0.42,
        repeat_penalty_threshold: float = 0.34,
        skip_forward_tokens: int = 8,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.strong_signal_threshold = float(strong_signal_threshold)
        self.weak_signal_threshold = float(weak_signal_threshold)
        self.repeat_penalty_threshold = float(repeat_penalty_threshold)
        self.skip_forward_tokens = int(skip_forward_tokens)

    def infer(
        self,
        *,
        progress_age: float,
        signal_quality: SignalQuality | None,
        tracking: TrackingSnapshot | None,
        tracking_mode: TrackingMode,
        tracking_quality: float,
        candidate_idx: int,
        estimated_idx: int,
    ) -> UserReadState:
        signal_speaking = self._is_signal_speaking(signal_quality)
        signal_weak_speaking = self._is_signal_weak_speaking(signal_quality)

        if tracking_mode == TrackingMode.LOST:
            if signal_speaking:
                return UserReadState.REJOINING
            return UserReadState.LOST

        if tracking_mode == TrackingMode.REACQUIRING:
            if signal_speaking:
                return UserReadState.REJOINING
            return UserReadState.HESITATING

        repeat_penalty = tracking.repeat_penalty if tracking is not None else 0.0
        if repeat_penalty >= self.repeat_penalty_threshold and signal_speaking:
            return UserReadState.REPEATING

        if candidate_idx - estimated_idx >= self.skip_forward_tokens and tracking_quality >= 0.72:
            return UserReadState.SKIPPING

        if progress_age <= self.recent_progress_sec:
            if tracking_quality >= 0.60:
                return UserReadState.FOLLOWING
            if signal_speaking:
                return UserReadState.HESITATING
            return UserReadState.WARMING_UP

        if progress_age <= 1.80:
            if signal_speaking and tracking_quality >= 0.36:
                return UserReadState.HESITATING
            if signal_weak_speaking:
                return UserReadState.WARMING_UP

        if not signal_speaking and progress_age > 1.20:
            return UserReadState.PAUSED

        if signal_speaking:
            return UserReadState.WARMING_UP

        return UserReadState.NOT_STARTED

    def _is_signal_speaking(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= self.strong_signal_threshold
        )

    def _is_signal_weak_speaking(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= self.weak_signal_threshold
        )