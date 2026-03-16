from __future__ import annotations

from shadowing.types import FusionEvidence


class EvidenceFuser:
    def __init__(
        self,
        *,
        text_priority_threshold: float = 0.72,
        audio_takeover_threshold: float = 0.62,
    ) -> None:
        self.text_priority_threshold = float(text_priority_threshold)
        self.audio_takeover_threshold = float(audio_takeover_threshold)

    def reset(self) -> None:
        return

    def fuse(
        self,
        *,
        now_sec: float,
        tracking,
        progress,
        audio_match,
        audio_behavior,
        signal_quality,
        playback_status,
    ) -> FusionEvidence | None:
        if progress is None and audio_match is None:
            return None

        text_conf = 0.0
        text_ref_time_sec = None
        text_ref_idx = 0
        if progress is not None:
            text_conf = max(
                0.0,
                min(
                    1.0,
                    0.56 * float(getattr(progress, "tracking_quality", 0.0))
                    + 0.30 * float(getattr(progress, "confidence", 0.0))
                    + 0.14 * (1.0 if getattr(progress, "stable", False) else 0.0),
                ),
            )
            text_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
            text_ref_idx = int(getattr(progress, "estimated_ref_idx", 0))

        audio_conf = 0.0 if audio_match is None else float(audio_match.confidence)
        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(audio_behavior.confidence) * 0.94)

        if text_ref_time_sec is None and audio_match is not None:
            est_ref_time_sec = float(audio_match.estimated_ref_time_sec)
            est_ref_idx = int(audio_match.estimated_ref_idx_hint)
        elif audio_match is None or text_conf >= self.text_priority_threshold:
            est_ref_time_sec = float(text_ref_time_sec or 0.0)
            est_ref_idx = int(text_ref_idx)
        elif audio_conf >= self.audio_takeover_threshold and text_conf < 0.52:
            est_ref_time_sec = float(audio_match.estimated_ref_time_sec)
            est_ref_idx = int(audio_match.estimated_ref_idx_hint)
        else:
            w_text = max(0.18, text_conf)
            w_audio = max(0.22, audio_conf)
            denom = w_text + w_audio
            est_ref_time_sec = (
                w_text * float(text_ref_time_sec or 0.0)
                + w_audio * float(audio_match.estimated_ref_time_sec)
            ) / denom
            est_ref_idx = int(
                round(
                    (w_text * text_ref_idx + w_audio * float(audio_match.estimated_ref_idx_hint)) / denom
                )
            )

        still_following = 0.0
        repeated = 0.0
        reentry = 0.0
        if audio_behavior is not None:
            still_following = float(audio_behavior.still_following_likelihood)
            repeated = float(audio_behavior.repeated_likelihood)
            reentry = float(audio_behavior.reentry_likelihood)
        elif audio_match is not None:
            still_following = float(audio_match.confidence) * 0.84
            repeated = float(audio_match.repeated_pattern_score)
            reentry = 0.55 if audio_match.mode == "reentry" else 0.0

        if progress is not None and getattr(progress, "recently_progressed", False):
            still_following = max(still_following, 0.64)

        fused_conf = max(text_conf, audio_conf)
        disagreement = 0.0
        if text_conf > 0.0 and audio_conf > 0.0 and audio_match is not None:
            disagreement = abs(float(text_ref_time_sec or 0.0) - float(audio_match.estimated_ref_time_sec))
            if disagreement <= 0.42:
                fused_conf = min(1.0, max(text_conf, audio_conf) + 0.08)
            elif disagreement >= 1.20:
                fused_conf = max(0.0, fused_conf - 0.10)

        should_prevent_hold = bool(
            (
                (text_conf < 0.60 and still_following >= 0.66)
                or (text_conf < 0.54 and audio_conf >= 0.64)
                or (reentry >= 0.62)
            )
            and repeated < 0.78
        )

        should_prevent_seek = bool(
            repeated >= 0.60
            or (audio_conf >= 0.64 and text_conf < 0.52)
            or (reentry >= 0.58)
        )

        should_recenter_aligner_window = bool(
            audio_match is not None
            and (
                (audio_conf >= 0.66 and text_conf < 0.56)
                or (disagreement >= 0.95 and audio_conf >= 0.62 and text_conf < 0.64)
            )
        )

        should_widen_reacquire_window = bool(
            audio_match is not None
            and (
                (audio_conf >= 0.56 and text_conf < 0.48)
                or (reentry >= 0.56)
                or (repeated >= 0.56)
            )
        )

        return FusionEvidence(
            estimated_ref_time_sec=float(est_ref_time_sec),
            estimated_ref_idx_hint=int(max(0, est_ref_idx)),
            text_confidence=float(text_conf),
            audio_confidence=float(audio_conf),
            fused_confidence=float(max(0.0, min(1.0, fused_conf))),
            still_following_likelihood=float(still_following),
            repeated_likelihood=float(repeated),
            reentry_likelihood=float(reentry),
            should_prevent_hold=should_prevent_hold,
            should_prevent_seek=should_prevent_seek,
            should_widen_reacquire_window=should_widen_reacquire_window,
            should_recenter_aligner_window=should_recenter_aligner_window,
            emitted_at_sec=float(now_sec),
        )