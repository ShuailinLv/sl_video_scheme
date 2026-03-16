from __future__ import annotations

from shadowing.types import AudioBehaviorSnapshot


class AudioBehaviorClassifier:
    def __init__(
        self,
        *,
        repeat_backtrack_sec: float = 1.5,
        reentry_silence_min_sec: float = 0.45,
        smooth_alpha: float = 0.30,
    ) -> None:
        self.repeat_backtrack_sec = float(repeat_backtrack_sec)
        self.reentry_silence_min_sec = float(reentry_silence_min_sec)
        self.smooth_alpha = float(smooth_alpha)
        self._last_snapshot: AudioBehaviorSnapshot | None = None

    def reset(self) -> None:
        self._last_snapshot = None

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
        if signal_quality is not None:
            signal_conf = float(
                max(
                    signal_quality.speaking_likelihood,
                    0.45 if signal_quality.vad_active else 0.0,
                )
            )
            silence_run_sec = float(signal_quality.silence_run_sec)

        still_following = max(0.0, min(1.0, 0.58 * audio_match.confidence + 0.42 * signal_conf))
        repeated = float(audio_match.repeated_pattern_score)
        reentry = 0.0

        if (
            playback_status is not None
            and silence_run_sec >= self.reentry_silence_min_sec
            and abs(
                float(audio_match.estimated_ref_time_sec)
                - float(playback_status.t_ref_heard_content_sec)
            )
            <= 0.55
            and audio_match.confidence >= 0.58
        ):
            reentry = min(1.0, 0.55 + 0.35 * audio_match.confidence)

        paused = 0.0
        if signal_quality is not None:
            paused = min(1.0, max(0.0, silence_run_sec / 1.5))

        if progress is not None and getattr(progress, "tracking_quality", 0.0) >= 0.72:
            still_following = max(still_following, 0.70)

        if audio_match.mode == "repeat":
            repeated = max(repeated, min(1.0, 0.58 + 0.25 * audio_match.confidence))
        if audio_match.mode == "reentry":
            reentry = max(reentry, min(1.0, 0.58 + 0.25 * audio_match.confidence))

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
                        max(still_following, repeated, reentry, 1.0 - paused if paused > 0 else 0.0),
                    ),
                )
            ),
            emitted_at_sec=float(audio_match.emitted_at_sec),
        )
        snap = self._smooth(snap)
        self._last_snapshot = snap
        return snap

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