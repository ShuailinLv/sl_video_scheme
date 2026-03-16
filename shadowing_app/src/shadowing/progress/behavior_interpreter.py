from __future__ import annotations

from shadowing.types import SignalQuality, TrackingMode, TrackingSnapshot, UserReadState


class BehaviorInterpreter:
    def __init__(
        self,
        *,
        recent_progress_sec: float = 0.90,
        strong_signal_threshold: float = 0.58,
        weak_signal_threshold: float = 0.42,
        repeat_penalty_threshold: float = 0.34,
        skip_forward_tokens: int = 8,
        pause_silence_sec: float = 1.10,
        rejoin_signal_sec: float = 0.55,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.strong_signal_threshold = float(strong_signal_threshold)
        self.weak_signal_threshold = float(weak_signal_threshold)
        self.repeat_penalty_threshold = float(repeat_penalty_threshold)
        self.skip_forward_tokens = int(skip_forward_tokens)
        self.pause_silence_sec = float(pause_silence_sec)
        self.rejoin_signal_sec = float(rejoin_signal_sec)

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
        audio_confidence: float = 0.0,
        audio_support_strength: float = 0.0,
        position_source: str = "text",
    ) -> UserReadState:
        signal_speaking = self._is_signal_speaking(signal_quality)
        signal_weak_speaking = self._is_signal_weak_speaking(signal_quality)
        silence_run = 9999.0 if signal_quality is None else float(signal_quality.silence_run_sec)

        repeat_penalty = tracking.repeat_penalty if tracking is not None else 0.0
        forward_delta = int(candidate_idx) - int(estimated_idx)

        if (
            silence_run >= self.pause_silence_sec
            and progress_age > min(1.15, self.recent_progress_sec + 0.15)
            and audio_support_strength < 0.52
        ):
            return UserReadState.PAUSED

        if tracking_mode == TrackingMode.LOST:
            if signal_speaking or audio_support_strength >= 0.60 or audio_confidence >= 0.62:
                return UserReadState.REJOINING
            return UserReadState.LOST

        if tracking_mode == TrackingMode.REACQUIRING:
            if signal_speaking or audio_support_strength >= 0.58 or audio_confidence >= 0.60:
                return UserReadState.REJOINING
            return UserReadState.HESITATING

        if (
            repeat_penalty >= self.repeat_penalty_threshold
            and (signal_speaking or audio_support_strength >= 0.58)
        ):
            return UserReadState.REPEATING

        if forward_delta >= self.skip_forward_tokens and tracking_quality >= 0.72:
            return UserReadState.SKIPPING

        if progress_age <= self.recent_progress_sec:
            if tracking_quality >= 0.60 or audio_support_strength >= 0.64:
                return UserReadState.FOLLOWING
            if signal_speaking or audio_confidence >= 0.58:
                return UserReadState.HESITATING
            return UserReadState.WARMING_UP

        if (
            silence_run <= self.rejoin_signal_sec
            and (signal_speaking or audio_support_strength >= 0.60 or audio_confidence >= 0.60)
            and tracking_quality >= 0.36
        ):
            return UserReadState.REJOINING

        if (
            (signal_speaking and tracking_quality >= 0.42)
            or audio_support_strength >= 0.64
            or (position_source != "text" and audio_confidence >= 0.58)
        ):
            return UserReadState.HESITATING

        if signal_weak_speaking or audio_support_strength >= 0.46 or audio_confidence >= 0.48:
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