from __future__ import annotations

from shadowing.types import FusionEvidence


class EvidenceFuser:
    """
    优化目标：
    1. 不再只做“文本 vs 音频”的硬切换，而是输出更稳定的融合证据
    2. 更明确地区分：
       - 文本高可信主导
       - 音频辅助校正
       - 音频接管（仅限文本弱、且音频连续可靠）
    3. 强化 repeat / reentry / pause 对 hold / seek 的抑制逻辑
    """

    def __init__(
        self,
        *,
        text_priority_threshold: float = 0.72,
        audio_takeover_threshold: float = 0.62,
        disagreement_soft_sec: float = 0.42,
        disagreement_hard_sec: float = 1.20,
    ) -> None:
        self.text_priority_threshold = float(text_priority_threshold)
        self.audio_takeover_threshold = float(audio_takeover_threshold)
        self.disagreement_soft_sec = float(disagreement_soft_sec)
        self.disagreement_hard_sec = float(disagreement_hard_sec)

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
        tracking_quality = 0.0
        recently_progressed = False
        active_speaking = False
        position_source = "text"

        if progress is not None:
            tracking_quality = float(getattr(progress, "tracking_quality", 0.0))
            progress_conf = float(getattr(progress, "confidence", 0.0))
            joint_conf = float(getattr(progress, "joint_confidence", 0.0))
            stable = 1.0 if bool(getattr(progress, "stable", False)) else 0.0
            recently_progressed = bool(getattr(progress, "recently_progressed", False))
            active_speaking = bool(getattr(progress, "active_speaking", False))
            position_source = str(getattr(progress, "position_source", "text"))

            # 文本可信度：更强调 tracking_quality 与稳定性
            text_conf = max(
                0.0,
                min(
                    1.0,
                    0.42 * tracking_quality
                    + 0.22 * progress_conf
                    + 0.16 * joint_conf
                    + 0.10 * stable
                    + 0.10 * (1.0 if recently_progressed else 0.0),
                ),
            )
            text_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
            text_ref_idx = int(getattr(progress, "estimated_ref_idx", 0))

            # 如果 progress 本来就是 audio/joint 源，降低它作为“纯文本证据”的强度
            if position_source == "audio":
                text_conf *= 0.84
            elif position_source == "joint":
                text_conf *= 0.92

        audio_conf = 0.0
        audio_ref_time_sec = None
        audio_ref_idx = 0
        repeated = 0.0
        reentry = 0.0
        still_following = 0.0
        paused = 0.0
        audio_mode = "tracking"

        if audio_match is not None:
            audio_ref_time_sec = float(audio_match.estimated_ref_time_sec)
            audio_ref_idx = int(audio_match.estimated_ref_idx_hint)
            audio_conf = float(audio_match.confidence)
            repeated = float(audio_match.repeated_pattern_score)
            still_following = max(still_following, audio_conf * 0.80)
            audio_mode = str(getattr(audio_match, "mode", "tracking"))

        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.96)
            still_following = max(still_following, float(getattr(audio_behavior, "still_following_likelihood", 0.0)))
            repeated = max(repeated, float(getattr(audio_behavior, "repeated_likelihood", 0.0)))
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            paused = float(getattr(audio_behavior, "paused_likelihood", 0.0))

        # 信号质量对音频证据做轻量修正
        if signal_quality is not None:
            speaking_like = float(
                max(
                    signal_quality.speaking_likelihood,
                    0.45 if signal_quality.vad_active else 0.0,
                )
            )
            if speaking_like >= 0.56:
                still_following = max(still_following, min(1.0, 0.55 + 0.30 * speaking_like))
            if signal_quality.dropout_detected:
                audio_conf *= 0.90
                still_following *= 0.92
            if float(signal_quality.quality_score) < 0.40:
                audio_conf *= 0.94

        # 没文本，直接以音频为主
        if text_ref_time_sec is None and audio_ref_time_sec is not None:
            est_ref_time_sec = float(audio_ref_time_sec)
            est_ref_idx = int(audio_ref_idx)
            fused_conf = max(audio_conf, still_following * 0.92)
            return FusionEvidence(
                estimated_ref_time_sec=float(est_ref_time_sec),
                estimated_ref_idx_hint=int(max(0, est_ref_idx)),
                text_confidence=0.0,
                audio_confidence=float(audio_conf),
                fused_confidence=float(max(0.0, min(1.0, fused_conf))),
                still_following_likelihood=float(still_following),
                repeated_likelihood=float(repeated),
                reentry_likelihood=float(reentry),
                should_prevent_hold=bool(still_following >= 0.66 and repeated < 0.78),
                should_prevent_seek=bool(repeated >= 0.60 or reentry >= 0.58),
                should_widen_reacquire_window=bool(audio_conf >= 0.56 or reentry >= 0.56),
                should_recenter_aligner_window=bool(audio_conf >= 0.66),
                emitted_at_sec=float(now_sec),
            )

        if text_ref_time_sec is None:
            return None

        disagreement = 0.0
        if audio_ref_time_sec is not None:
            disagreement = abs(float(text_ref_time_sec) - float(audio_ref_time_sec))

        # 情况 1：文本强可信，优先文本
        if audio_ref_time_sec is None or text_conf >= self.text_priority_threshold:
            est_ref_time_sec = float(text_ref_time_sec)
            est_ref_idx = int(text_ref_idx)
            fused_conf = text_conf
            if audio_ref_time_sec is not None:
                if disagreement <= self.disagreement_soft_sec:
                    fused_conf = min(1.0, fused_conf + 0.06)
                elif disagreement >= self.disagreement_hard_sec:
                    fused_conf = max(0.0, fused_conf - 0.06)

        else:
            # 情况 2：文本弱 + 音频强，可接管
            audio_can_takeover = bool(
                audio_conf >= self.audio_takeover_threshold
                and still_following >= 0.66
                and repeated < 0.72
                and (
                    reentry >= 0.56
                    or audio_mode in {"reentry", "recovery"}
                    or text_conf < 0.52
                )
            )

            if audio_can_takeover and disagreement <= 1.40:
                est_ref_time_sec = float(audio_ref_time_sec)
                est_ref_idx = int(audio_ref_idx)
                fused_conf = max(audio_conf * 0.94, still_following * 0.90, text_conf * 0.84)
            else:
                # 情况 3：联合估计
                w_text = max(0.16, text_conf)
                w_audio = max(0.18, audio_conf)

                # repeat 时不要让音频大幅影响主进度
                if repeated >= 0.68:
                    w_audio *= 0.22
                elif paused >= 0.72:
                    w_audio *= 0.38
                elif disagreement >= self.disagreement_hard_sec:
                    # 相差过大时，除非 reentry 很强，否则更信文本
                    if reentry < 0.62:
                        w_audio *= 0.46

                denom = max(1e-6, w_text + w_audio)
                est_ref_time_sec = (
                    w_text * float(text_ref_time_sec)
                    + w_audio * float(audio_ref_time_sec)
                ) / denom
                est_ref_idx = int(
                    round(
                        (w_text * float(text_ref_idx) + w_audio * float(audio_ref_idx)) / denom
                    )
                )

                fused_conf = max(
                    text_conf,
                    audio_conf * 0.90,
                    0.55 * text_conf + 0.45 * audio_conf,
                )
                if disagreement <= self.disagreement_soft_sec:
                    fused_conf = min(1.0, fused_conf + 0.06)
                elif disagreement >= self.disagreement_hard_sec:
                    fused_conf = max(0.0, fused_conf - 0.08)

        # 控制保护逻辑
        should_prevent_hold = bool(
            (
                (text_conf < 0.60 and still_following >= 0.66)
                or (text_conf < 0.54 and audio_conf >= 0.64)
                or (reentry >= 0.62)
                or (active_speaking and still_following >= 0.62)
            )
            and repeated < 0.78
            and paused < 0.78
        )

        should_prevent_seek = bool(
            repeated >= 0.60
            or reentry >= 0.58
            or (audio_conf >= 0.64 and text_conf < 0.52 and disagreement <= 1.20)
        )

        should_recenter_aligner_window = bool(
            audio_ref_time_sec is not None
            and (
                (audio_conf >= 0.66 and text_conf < 0.56)
                or (disagreement >= 0.95 and audio_conf >= 0.62 and text_conf < 0.64)
                or (reentry >= 0.62)
            )
        )

        should_widen_reacquire_window = bool(
            audio_ref_time_sec is not None
            and (
                (audio_conf >= 0.56 and text_conf < 0.48)
                or (reentry >= 0.56)
                or (repeated >= 0.56)
                or (paused >= 0.72 and still_following < 0.58)
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