from __future__ import annotations

from dataclasses import dataclass

from shadowing.types import AudioBehaviorSnapshot


@dataclass(slots=True)
class _BehaviorState:
    mode: str = "unknown"
    mode_run: int = 0
    last_emitted_at_sec: float = 0.0
    last_active_follow_at_sec: float = 0.0
    last_pause_like_at_sec: float = 0.0
    last_reentry_like_at_sec: float = 0.0
    last_repeat_like_at_sec: float = 0.0


class AudioBehaviorClassifier:
    def __init__(
        self,
        *,
        repeat_backtrack_sec: float = 1.5,
        reentry_silence_min_sec: float = 0.45,
        smooth_alpha: float = 0.30,
        repeat_trigger_conf: float = 0.62,
        reentry_trigger_conf: float = 0.60,
        pause_trigger_silence_sec: float = 0.70,
    ) -> None:
        self.repeat_backtrack_sec = float(repeat_backtrack_sec)
        self.reentry_silence_min_sec = float(reentry_silence_min_sec)
        self.smooth_alpha = float(smooth_alpha)
        self.repeat_trigger_conf = float(repeat_trigger_conf)
        self.reentry_trigger_conf = float(reentry_trigger_conf)
        self.pause_trigger_silence_sec = float(pause_trigger_silence_sec)

        self._last_snapshot: AudioBehaviorSnapshot | None = None
        self._state = _BehaviorState()

    def reset(self) -> None:
        self._last_snapshot = None
        self._state = _BehaviorState()

    def update(
        self,
        *,
        audio_match,
        signal_quality,
        progress,
        playback_status,
    ) -> AudioBehaviorSnapshot | None:
        if audio_match is None:
            return self._last_snapshot

        signal_conf = 0.0
        silence_run_sec = 0.0
        quality_score = 0.0
        if signal_quality is not None:
            signal_conf = float(
                max(
                    signal_quality.speaking_likelihood,
                    0.48 if signal_quality.vad_active else 0.0,
                )
            )
            silence_run_sec = float(signal_quality.silence_run_sec)
            quality_score = float(signal_quality.quality_score)

        match_conf = float(audio_match.confidence)
        local_similarity = float(getattr(audio_match, "local_similarity", 0.0))
        repeated_score = float(audio_match.repeated_pattern_score)
        mode = str(getattr(audio_match, "mode", "tracking"))

        still_following = max(
            0.0,
            min(
                1.0,
                0.48 * match_conf + 0.22 * local_similarity + 0.30 * signal_conf,
            ),
        )

        repeated = repeated_score
        reentry = 0.0
        paused = 0.0

        if signal_quality is not None:
            paused = min(1.0, max(0.0, silence_run_sec / 1.6))
            if silence_run_sec >= self.pause_trigger_silence_sec and signal_conf < 0.42:
                paused = max(paused, 0.62)

        if (
            playback_status is not None
            and silence_run_sec >= self.reentry_silence_min_sec
            and abs(
                float(audio_match.estimated_ref_time_sec)
                - float(playback_status.t_ref_heard_content_sec)
            )
            <= 0.60
            and match_conf >= 0.56
        ):
            reentry = min(1.0, 0.52 + 0.36 * match_conf)

        if progress is not None:
            tracking_q = float(getattr(progress, "tracking_quality", 0.0))
            joint_conf = float(getattr(progress, "joint_confidence", 0.0))
            position_source = str(getattr(progress, "position_source", "text"))

            if tracking_q >= 0.72:
                still_following = max(still_following, 0.68)
            if joint_conf >= 0.74 and position_source in {"joint", "audio"}:
                still_following = max(still_following, 0.72)

            if getattr(progress, "recently_progressed", False):
                paused *= 0.70

            if getattr(progress, "active_speaking", False):
                still_following = max(still_following, 0.70)
                paused *= 0.78

        if mode == "repeat":
            repeated = max(repeated, min(1.0, 0.60 + 0.24 * match_conf))
        if mode == "reentry":
            reentry = max(reentry, min(1.0, 0.60 + 0.24 * match_conf))
        if mode == "recovery":
            still_following = max(still_following, min(1.0, 0.58 + 0.22 * match_conf))

        if quality_score < 0.40 and signal_conf < 0.36:
            still_following *= 0.88

        state_mode = self._infer_mode(
            still_following=still_following,
            repeated=repeated,
            reentry=reentry,
            paused=paused,
            emitted_at_sec=float(audio_match.emitted_at_sec),
        )

        if state_mode == "repeat":
            repeated = max(repeated, 0.72)
            paused *= 0.82
        elif state_mode == "reentry":
            reentry = max(reentry, 0.72)
            paused *= 0.72
            still_following = max(still_following, 0.70)
        elif state_mode == "pause":
            paused = max(paused, 0.72)
            repeated *= 0.86
        elif state_mode == "following":
            still_following = max(still_following, 0.72)
            paused *= 0.68

        snap = AudioBehaviorSnapshot(
            still_following_likelihood=float(still_following),
            repeated_likelihood=float(repeated),
            reentry_likelihood=float(reentry),
            paused_likelihood=float(paused),
            confidence=float(
                max(
                    0.0,
                    min(
                        1.0,
                        max(
                            still_following,
                            repeated,
                            reentry,
                            1.0 - paused if paused > 0 else 0.0,
                        ),
                    ),
                )
            ),
            emitted_at_sec=float(audio_match.emitted_at_sec),
        )
        snap = self._smooth(snap)
        self._last_snapshot = snap
        return snap

    def _infer_mode(
        self,
        *,
        still_following: float,
        repeated: float,
        reentry: float,
        paused: float,
        emitted_at_sec: float,
    ) -> str:
        prev = self._state.mode

        candidate = "unknown"
        if repeated >= self.repeat_trigger_conf and repeated >= reentry and repeated >= still_following:
            candidate = "repeat"
        elif reentry >= self.reentry_trigger_conf and reentry >= repeated:
            candidate = "reentry"
        elif paused >= 0.66 and still_following < 0.58:
            candidate = "pause"
        elif still_following >= 0.64:
            candidate = "following"

        if candidate == prev:
            self._state.mode_run += 1
        else:
            self._state.mode = candidate
            self._state.mode_run = 1

        if candidate == "following":
            self._state.last_active_follow_at_sec = emitted_at_sec
        elif candidate == "pause":
            self._state.last_pause_like_at_sec = emitted_at_sec
        elif candidate == "reentry":
            self._state.last_reentry_like_at_sec = emitted_at_sec
        elif candidate == "repeat":
            self._state.last_repeat_like_at_sec = emitted_at_sec

        self._state.last_emitted_at_sec = emitted_at_sec

        if candidate in {"repeat", "reentry"}:
            if self._state.mode_run >= 1:
                return candidate
        if candidate in {"pause", "following"}:
            if self._state.mode_run >= 2:
                return candidate

        if prev == "repeat" and (emitted_at_sec - self._state.last_repeat_like_at_sec) <= 0.35:
            return "repeat"
        if prev == "reentry" and (emitted_at_sec - self._state.last_reentry_like_at_sec) <= 0.45:
            return "reentry"
        if prev == "pause" and (emitted_at_sec - self._state.last_pause_like_at_sec) <= 0.40:
            return "pause"
        if prev == "following" and (emitted_at_sec - self._state.last_active_follow_at_sec) <= 0.35:
            return "following"

        return candidate

    def _smooth(self, current: AudioBehaviorSnapshot) -> AudioBehaviorSnapshot:
        prev = self._last_snapshot
        if prev is None:
            return current

        a = max(0.0, min(1.0, self.smooth_alpha))
        still_following = (1.0 - a) * prev.still_following_likelihood + a * current.still_following_likelihood
        repeated = (1.0 - a) * prev.repeated_likelihood + a * current.repeated_likelihood
        reentry = (1.0 - a) * prev.reentry_likelihood + a * current.reentry_likelihood
        paused = (1.0 - a) * prev.paused_likelihood + a * current.paused_likelihood
        conf = max(still_following, repeated, reentry, 1.0 - paused if paused > 0 else 0.0)

        return AudioBehaviorSnapshot(
            still_following_likelihood=float(max(0.0, min(1.0, still_following))),
            repeated_likelihood=float(max(0.0, min(1.0, repeated))),
            reentry_likelihood=float(max(0.0, min(1.0, reentry))),
            paused_likelihood=float(max(0.0, min(1.0, paused))),
            confidence=float(max(0.0, min(1.0, conf))),
            emitted_at_sec=float(current.emitted_at_sec),
        )