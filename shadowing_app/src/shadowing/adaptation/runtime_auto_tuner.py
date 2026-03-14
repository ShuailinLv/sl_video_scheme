from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AutoTuningState:
    speaker_style: str = "unknown"
    environment_style: str = "unknown"
    device_risk: str = "medium"
    startup_profile_decided: bool = False
    last_tuned_at_sec: float = 0.0


class RuntimeAutoTuner:
    def __init__(self) -> None:
        self.state = AutoTuningState()

    def reset(self, reliability_tier: str) -> None:
        self.state = AutoTuningState(
            device_risk=str(reliability_tier or "medium"),
        )

    def apply_warm_start(
        self,
        *,
        controller_policy,
        player,
        signal_monitor,
        warm_start: dict,
    ) -> None:
        control = dict(warm_start.get("control", {}))
        playback = dict(warm_start.get("playback", {}))
        signal = dict(warm_start.get("signal", {}))

        for key, value in control.items():
            if hasattr(controller_policy, key):
                setattr(controller_policy, key, value)

        if signal:
            if "min_vad_rms" in signal:
                signal_monitor.min_vad_rms = float(signal["min_vad_rms"])
            if "vad_noise_multiplier" in signal:
                signal_monitor.vad_noise_multiplier = float(signal["vad_noise_multiplier"])

        if playback:
            offset = playback.get("bluetooth_output_offset_sec")
            if offset is not None and hasattr(player, "set_output_offset_sec"):
                player.set_output_offset_sec(float(offset))

    def maybe_tune(
        self,
        *,
        now_sec: float,
        controller_policy,
        player,
        signal_monitor,
        metrics_summary: dict,
        signal_quality,
        progress,
        latency_snapshot,
        device_profile,
    ) -> dict[str, float]:
        if (now_sec - self.state.last_tuned_at_sec) < 1.2:
            return {}

        updates: dict[str, float] = {}

        first_signal = metrics_summary.get("first_signal_active_time_sec")
        first_partial = metrics_summary.get("first_asr_partial_time_sec")
        first_reliable = metrics_summary.get("first_reliable_progress_time_sec")
        startup_false_hold_count = int(metrics_summary.get("startup_false_hold_count", 0))
        mean_tracking_quality = float(metrics_summary.get("mean_tracking_quality", 0.0))
        lost_count = int(metrics_summary.get("lost_count", 0))
        reacquire_count = int(metrics_summary.get("reacquire_count", 0))

        if not self.state.startup_profile_decided:
            speaker_style = self._infer_speaker_style(
                first_signal_active_time_sec=first_signal,
                first_asr_partial_time_sec=first_partial,
                first_reliable_progress_time_sec=first_reliable,
                signal_quality=signal_quality,
            )
            self.state.speaker_style = speaker_style
            self.state.environment_style = self._infer_environment_style(signal_quality)
            self.state.startup_profile_decided = True

            if speaker_style == "quiet":
                updates["guide_play_sec"] = min(4.0, controller_policy.guide_play_sec + 0.6)
                updates["no_progress_hold_min_play_sec"] = min(
                    6.0,
                    controller_policy.no_progress_hold_min_play_sec + 0.8,
                )
                updates["progress_stale_sec"] = min(1.8, controller_policy.progress_stale_sec + 0.14)
                updates["resume_from_hold_speaking_lead_slack_sec"] = min(
                    0.90,
                    controller_policy.resume_from_hold_speaking_lead_slack_sec + 0.12,
                )
                updates["tracking_quality_hold_min"] = min(
                    0.78,
                    controller_policy.tracking_quality_hold_min + 0.02,
                )

            elif speaker_style == "fast":
                updates["progress_stale_sec"] = max(0.85, controller_policy.progress_stale_sec - 0.10)
                updates["hold_trend_sec"] = max(0.50, controller_policy.hold_trend_sec - 0.08)
                updates["resume_from_hold_speaking_lead_slack_sec"] = min(
                    0.90,
                    controller_policy.resume_from_hold_speaking_lead_slack_sec + 0.08,
                )

            if self.state.environment_style == "noisy":
                updates["tracking_quality_hold_min"] = min(
                    0.82,
                    controller_policy.tracking_quality_hold_min + 0.04,
                )
                updates["tracking_quality_seek_min"] = min(
                    0.90,
                    controller_policy.tracking_quality_seek_min + 0.04,
                )
                signal_monitor.vad_noise_multiplier = min(4.2, signal_monitor.vad_noise_multiplier + 0.20)

        if startup_false_hold_count >= 1:
            updates["guide_play_sec"] = min(4.2, controller_policy.guide_play_sec + 0.25)
            updates["no_progress_hold_min_play_sec"] = min(
                6.5,
                controller_policy.no_progress_hold_min_play_sec + 0.35,
            )
            updates["hold_trend_sec"] = min(1.30, controller_policy.hold_trend_sec + 0.05)

        if progress is not None:
            if (
                progress.tracking_quality < 0.55
                and progress.active_speaking
                and progress.progress_age_sec < 1.2
            ):
                updates["gain_soft_duck"] = max(0.28, controller_policy.gain_soft_duck - 0.03)
                updates["resume_from_hold_speaking_lead_slack_sec"] = min(
                    0.90,
                    controller_policy.resume_from_hold_speaking_lead_slack_sec + 0.04,
                )

            if (
                progress.tracking_quality >= 0.80
                and progress.tracking_mode.value == "locked"
                and mean_tracking_quality >= 0.76
            ):
                updates["tracking_quality_seek_min"] = max(
                    0.66,
                    controller_policy.tracking_quality_seek_min - 0.01,
                )

        if lost_count >= 2 or reacquire_count >= 3:
            updates["tracking_quality_hold_min"] = min(
                0.82,
                controller_policy.tracking_quality_hold_min + 0.03,
            )
            updates["tracking_quality_seek_min"] = min(
                0.90,
                controller_policy.tracking_quality_seek_min + 0.03,
            )
            updates["hold_trend_sec"] = min(1.30, controller_policy.hold_trend_sec + 0.05)
            updates["progress_stale_sec"] = min(1.90, controller_policy.progress_stale_sec + 0.06)

        if mean_tracking_quality >= 0.82 and startup_false_hold_count == 0 and lost_count == 0:
            updates["tracking_quality_hold_min"] = max(
                0.54,
                controller_policy.tracking_quality_hold_min - 0.01,
            )
            updates["hold_trend_sec"] = max(0.50, controller_policy.hold_trend_sec - 0.02)

        if latency_snapshot is not None and hasattr(player, "set_output_offset_sec"):
            player.set_output_offset_sec(
                max(0.0, float(latency_snapshot.estimated_output_latency_ms) / 1000.0)
            )

        self._apply_updates(controller_policy, updates)
        self.state.last_tuned_at_sec = float(now_sec)
        return updates

    def _apply_updates(self, controller_policy, updates: dict[str, float]) -> None:
        for key, value in updates.items():
            if hasattr(controller_policy, key):
                setattr(controller_policy, key, float(value))

    def _infer_speaker_style(
        self,
        *,
        first_signal_active_time_sec,
        first_asr_partial_time_sec,
        first_reliable_progress_time_sec,
        signal_quality,
    ) -> str:
        sig = 999.0 if first_signal_active_time_sec is None else float(first_signal_active_time_sec)
        part = 999.0 if first_asr_partial_time_sec is None else float(first_asr_partial_time_sec)
        prog = 999.0 if first_reliable_progress_time_sec is None else float(first_reliable_progress_time_sec)

        speaking_likelihood = 0.0 if signal_quality is None else float(signal_quality.speaking_likelihood)
        rms = 0.0 if signal_quality is None else float(signal_quality.rms)

        if rms < 0.010 and speaking_likelihood < 0.55:
            return "quiet"
        if prog <= 2.0 and part <= 1.5:
            return "fast"
        if sig > 1.2 or prog > 4.0:
            return "quiet"
        return "normal"

    def _infer_environment_style(self, signal_quality) -> str:
        if signal_quality is None:
            return "unknown"
        if signal_quality.dropout_detected:
            return "unstable"
        if signal_quality.clipping_ratio >= 0.03:
            return "clipping"
        if signal_quality.quality_score < 0.42:
            return "noisy"
        return "normal"