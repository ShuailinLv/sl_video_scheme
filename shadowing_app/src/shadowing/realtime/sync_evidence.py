from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from shadowing.types import FusionEvidence, ProgressEstimate, SignalQuality, TrackingMode


class SpeechState(str, Enum):
    NONE = "none"
    POSSIBLE = "possible"
    ACTIVE = "active"
    SUSTAINED = "sustained"


class TrackingState(str, Enum):
    NONE = "none"
    WEAK = "weak"
    RELIABLE = "reliable"
    LOCKED = "locked"


class SyncState(str, Enum):
    BOOTSTRAP = "bootstrap"
    CONVERGING = "converging"
    STABLE = "stable"
    DEGRADED = "degraded"


@dataclass(slots=True)
class SyncEvidence:
    speech_state: SpeechState
    tracking_state: TrackingState
    sync_state: SyncState
    speech_confidence: float
    tracking_confidence: float
    sync_confidence: float
    should_open_asr_gate: bool
    should_keep_asr_gate: bool
    allow_latency_observation: bool
    allow_seek: bool
    startup_mode: bool
    bluetooth_mode: bool
    bluetooth_long_session_mode: bool
    audio_confidence: float = 0.0
    still_following_likelihood: float = 0.0
    reentry_likelihood: float = 0.0
    repeated_likelihood: float = 0.0


class SyncEvidenceBuilder:
    def __init__(
        self,
        *,
        startup_window_sec: float = 4.0,
        seek_enable_after_sec: float = 8.0,
        sustained_speaking_sec: float = 0.65,
    ) -> None:
        self.startup_window_sec = float(startup_window_sec)
        self.seek_enable_after_sec = float(seek_enable_after_sec)
        self.sustained_speaking_sec = float(sustained_speaking_sec)
        self._session_started_at_sec = 0.0
        self._last_speech_like_at_sec = 0.0
        self._last_engaged_like_at_sec = 0.0

    def reset(self, now_sec: float) -> None:
        self._session_started_at_sec = float(now_sec)
        self._last_speech_like_at_sec = 0.0
        self._last_engaged_like_at_sec = 0.0

    def build(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        progress: ProgressEstimate | None,
        fusion_evidence: FusionEvidence | None,
        bluetooth_mode: bool,
        bluetooth_long_session_mode: bool = False,
    ) -> SyncEvidence:
        startup_window = self.startup_window_sec + (2.0 if bluetooth_mode else 0.0)
        startup_mode = (now_sec - self._session_started_at_sec) <= startup_window

        speech_conf = self._speech_confidence(signal_quality)
        if speech_conf >= 0.36:
            self._last_speech_like_at_sec = float(now_sec)

        speech_state = self._speech_state(
            now_sec=now_sec,
            signal_quality=signal_quality,
            speech_confidence=speech_conf,
        )

        tracking_conf = self._tracking_confidence(progress, fusion_evidence)
        tracking_state = self._tracking_state(progress, tracking_conf)

        audio_conf = 0.0 if fusion_evidence is None else float(fusion_evidence.audio_confidence)
        still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)
        repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)

        progress_recent = False
        progress_active = False
        progress_conf = 0.0
        progress_quality = 0.0
        progress_stable = False
        progress_age = 9999.0
        if progress is not None:
            progress_recent = bool(getattr(progress, "recently_progressed", False))
            progress_active = bool(getattr(progress, "active_speaking", False))
            progress_conf = float(getattr(progress, "confidence", 0.0))
            progress_quality = float(getattr(progress, "tracking_quality", 0.0))
            progress_stable = bool(getattr(progress, "stable", False))
            progress_age = float(getattr(progress, "progress_age_sec", 9999.0))

        engaged_like = bool(
            progress_recent
            or progress_active
            or still_following >= 0.60
            or reentry >= 0.54
            or (speech_conf >= 0.46 and progress_quality >= 0.46)
        )
        if engaged_like:
            self._last_engaged_like_at_sec = float(now_sec)

        engaged_tail_sec = 1.70 if bluetooth_mode else 1.10
        engaged_recent = (
            self._last_engaged_like_at_sec > 0.0
            and (now_sec - self._last_engaged_like_at_sec) <= engaged_tail_sec
        )

        sync_conf = max(
            0.0,
            min(
                1.0,
                0.34 * speech_conf
                + 0.36 * tracking_conf
                + 0.20 * max(audio_conf, still_following)
                + 0.10 * (1.0 if engaged_recent else 0.0),
            ),
        )

        sync_state = self._sync_state(
            startup_mode=startup_mode,
            speech_state=speech_state,
            tracking_state=tracking_state,
            sync_confidence=sync_conf,
            fusion_evidence=fusion_evidence,
            engaged_recent=engaged_recent,
        )

        should_open_asr_gate = bool(
            speech_state in (SpeechState.POSSIBLE, SpeechState.ACTIVE, SpeechState.SUSTAINED)
            or (engaged_recent and still_following >= 0.52)
        )

        gate_tail_sec = 1.15 if bluetooth_mode else 0.65
        should_keep_asr_gate = bool(
            should_open_asr_gate
            or (
                self._last_speech_like_at_sec > 0.0
                and (now_sec - self._last_speech_like_at_sec) <= gate_tail_sec
            )
            or engaged_recent
        )

        allow_latency_observation = bool(
            not startup_mode
            and speech_state in (SpeechState.ACTIVE, SpeechState.SUSTAINED)
            and tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED)
            and sync_state in (SyncState.CONVERGING, SyncState.STABLE)
            and repeated < 0.50
            and reentry < 0.70
            and progress_age <= (1.10 if bluetooth_mode else 0.95)
            and progress_conf >= 0.52
            and (
                fusion_evidence is None
                or fusion_evidence.fused_confidence >= (0.54 if bluetooth_mode else 0.58)
            )
        )

        if bluetooth_mode:
            allow_seek = False
        else:
            allow_seek = bool(
                (now_sec - self._session_started_at_sec) >= self.seek_enable_after_sec
                and not startup_mode
                and tracking_state == TrackingState.LOCKED
                and sync_state == SyncState.STABLE
                and progress_stable
                and progress_quality >= 0.78
                and progress_conf >= 0.74
                and progress_age <= 0.85
                and repeated < 0.42
                and reentry < 0.42
                and still_following < 0.72
                and (
                    fusion_evidence is None
                    or not fusion_evidence.should_prevent_seek
                )
            )

        return SyncEvidence(
            speech_state=speech_state,
            tracking_state=tracking_state,
            sync_state=sync_state,
            speech_confidence=speech_conf,
            tracking_confidence=tracking_conf,
            sync_confidence=sync_conf,
            should_open_asr_gate=should_open_asr_gate,
            should_keep_asr_gate=should_keep_asr_gate,
            allow_latency_observation=allow_latency_observation,
            allow_seek=allow_seek,
            startup_mode=startup_mode,
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=bool(bluetooth_long_session_mode),
            audio_confidence=audio_conf,
            still_following_likelihood=still_following,
            reentry_likelihood=reentry,
            repeated_likelihood=repeated,
        )

    def _speech_confidence(self, signal_quality: SignalQuality | None) -> float:
        if signal_quality is None:
            return 0.0

        score = 0.0
        score += min(0.34, max(0.0, signal_quality.speaking_likelihood) * 0.46)
        score += min(0.30, max(0.0, signal_quality.rms) * 18.0)
        score += min(0.18, max(0.0, signal_quality.peak) * 2.0)

        if signal_quality.vad_active:
            score += 0.18
        if signal_quality.dropout_detected:
            score -= 0.16
        if signal_quality.clipping_ratio >= 0.05:
            score -= 0.08

        return max(0.0, min(1.0, score))

    def _speech_state(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        speech_confidence: float,
    ) -> SpeechState:
        if signal_quality is None:
            return SpeechState.NONE
        if speech_confidence < 0.16:
            return SpeechState.NONE
        if speech_confidence < 0.40:
            return SpeechState.POSSIBLE
        if self._last_speech_like_at_sec > 0.0 and (
            now_sec - self._last_speech_like_at_sec
        ) <= self.sustained_speaking_sec:
            return SpeechState.SUSTAINED
        return SpeechState.ACTIVE

    def _tracking_confidence(
        self,
        progress: ProgressEstimate | None,
        fusion_evidence: FusionEvidence | None,
    ) -> float:
        score = 0.0

        if progress is not None:
            score += min(0.42, float(progress.tracking_quality) * 0.50)
            score += min(0.28, float(progress.confidence) * 0.34)
            if progress.stable:
                score += 0.14
            if progress.recently_progressed:
                score += 0.10
            if progress.progress_age_sec > 1.5:
                score -= 0.10

        if fusion_evidence is not None and (progress is None or getattr(progress, "tracking_quality", 0.0) < 0.56):
            score += min(0.16, float(fusion_evidence.audio_confidence) * 0.20)
            score += min(0.14, float(fusion_evidence.still_following_likelihood) * 0.18)

        return max(0.0, min(1.0, score))

    def _tracking_state(
        self,
        progress: ProgressEstimate | None,
        tracking_confidence: float,
    ) -> TrackingState:
        if progress is None:
            return TrackingState.NONE

        mode = progress.tracking_mode
        if mode == TrackingMode.LOCKED and tracking_confidence >= 0.72:
            return TrackingState.LOCKED
        if mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED) and tracking_confidence >= 0.52:
            return TrackingState.RELIABLE
        if tracking_confidence >= 0.30:
            return TrackingState.WEAK
        return TrackingState.NONE

    def _sync_state(
        self,
        *,
        startup_mode: bool,
        speech_state: SpeechState,
        tracking_state: TrackingState,
        sync_confidence: float,
        fusion_evidence: FusionEvidence | None,
        engaged_recent: bool,
    ) -> SyncState:
        if startup_mode:
            return SyncState.BOOTSTRAP

        if (
            speech_state in (SpeechState.ACTIVE, SpeechState.SUSTAINED)
            and tracking_state == TrackingState.LOCKED
            and sync_confidence >= 0.72
        ):
            return SyncState.STABLE

        if fusion_evidence is not None:
            if (
                fusion_evidence.still_following_likelihood >= 0.66
                or fusion_evidence.reentry_likelihood >= 0.54
            ) and sync_confidence >= 0.54:
                return SyncState.CONVERGING

        if engaged_recent and tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED):
            return SyncState.CONVERGING

        if speech_state != SpeechState.NONE and tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED):
            return SyncState.CONVERGING

        return SyncState.DEGRADED