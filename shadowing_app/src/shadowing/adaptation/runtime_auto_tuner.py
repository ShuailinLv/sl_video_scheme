from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AutoTuningState:
    speaker_style: str = "unknown"
    environment_style: str = "unknown"
    device_risk: str = "medium"
    bluetooth_mode: bool = False
    startup_profile_decided: bool = False
    phase: str = "startup"
    last_tuned_at_sec: float = 0.0
    freeze_until_sec: float = 0.0
    baseline_control: dict[str, float] = field(default_factory=dict)
    last_good_control: dict[str, float] = field(default_factory=dict)
    best_tracking_quality: float = 0.0


class RuntimeAutoTuner:
    _CONTROL_KEYS = (
        "guide_play_sec",
        "no_progress_hold_min_play_sec",
        "progress_stale_sec",
        "hold_trend_sec",
        "tracking_quality_hold_min",
        "tracking_quality_seek_min",
        "resume_from_hold_speaking_lead_slack_sec",
        "gain_soft_duck",
        "seek_cooldown_sec",
    )

    _MAX_DELTAS = {
        "guide_play_sec": 0.90,
        "no_progress_hold_min_play_sec": 1.20,
        "progress_stale_sec": 0.24,
        "hold_trend_sec": 0.20,
        "tracking_quality_hold_min": 0.06,
        "tracking_quality_seek_min": 0.06,
        "resume_from_hold_speaking_lead_slack_sec": 0.14,
        "gain_soft_duck": 0.08,
        "seek_cooldown_sec": 0.50,
    }

    _HARD_BOUNDS = {
        "guide_play_sec": (1.4, 4.2),
        "no_progress_hold_min_play_sec": (2.5, 6.5),
        "progress_stale_sec": (0.8, 1.9),
        "hold_trend_sec": (0.45, 1.30),
        "tracking_quality_hold_min": (0.50, 0.82),
        "tracking_quality_seek_min": (0.64, 0.92),
        "resume_from_hold_speaking_lead_slack_sec": (0.25, 0.90),
        "gain_soft_duck": (0.28, 0.55),
        "seek_cooldown_sec": (0.90, 2.40),
    }

    def __init__(self) -> None:
        self.state = AutoTuningState()

    def reset(self, reliability_tier: str, bluetooth_mode: bool = False) -> None:
        self.state = AutoTuningState(
            device_risk=str(reliability_tier or "medium"),
            bluetooth_mode=bool(bluetooth_mode),
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

        self._capture_baseline(controller_policy)

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
        if not self.state.baseline_control:
            self._capture_baseline(controller_policy)

        if progress is not None and progress.tracking_quality >= max(0.76, self.state.best_tracking_quality):
            self.state.best_tracking_quality = float(progress.tracking_quality)
            self.state.last_good_control = self._snapshot_control(controller_policy)

        if now_sec < self.state.freeze_until_sec:
            return {}

        if (now_sec - self.state.last_tuned_at_sec) < 1.5:
            return {}

        if progress is not None:
            if (
                self.state.last_good_control
                and progress.tracking_quality < max(0.50, self.state.best_tracking_quality - 0.16)
                and progress.tracking_mode.value in ("reacquiring", "lost")
            ):
                self._restore_control(controller_policy, self.state.last_good_control)
                self.state.last_tuned_at_sec = float(now_sec)
                self.state.freeze_until_sec = float(now_sec) + 2.0
                return dict(self.state.last_good_control)

        updates: dict[str, float] = {}
        first_signal = metrics_summary.get("first_signal_active_time_sec")
        first_partial = metrics_summary.get("first_asr_partial_time_sec")
        first_reliable = metrics_summary.get("first_reliable_progress_time_sec")
        startup_false_hold_count = int(metrics_summary.get("startup_false_hold_count", 0))
        mean_tracking_quality = float(metrics_summary.get("mean_tracking_quality", 0.0))
        lost_count = int(metrics_summary.get("lost_count", 0))
        reacquire_count = int(metrics_summary.get("reacquire_count", 0))
        seek_count = int(metrics_summary.get("seek_count", 0))

        if now_sec <= 6.0:
            self.state.phase = "startup"
        elif mean_tracking_quality >= 0.70 and lost_count == 0:
            self.state.phase = "steady"
        else:
            self.state.phase = "recovery"

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
                updates["guide_play_sec"] = controller_policy.guide_play_sec + 0.55
                updates["no_progress_hold_min_play_sec"] = controller_policy.no_progress_hold_min_play_sec + 0.70
                updates["progress_stale_sec"] = controller_policy.progress_stale_sec + 0.12
                updates["resume_from_hold_speaking_lead_slack_sec"] = (
                    controller_policy.resume_from_hold_speaking_lead_slack_sec + 0.10
                )
                updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min + 0.02
            elif speaker_style == "fast":
                updates["progress_stale_sec"] = controller_policy.progress_stale_sec - 0.08
                updates["hold_trend_sec"] = controller_policy.hold_trend_sec - 0.06

            if self.state.environment_style == "noisy":
                updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min + 0.04
                updates["tracking_quality_seek_min"] = controller_policy.tracking_quality_seek_min + 0.03
                signal_monitor.vad_noise_multiplier = min(4.2, signal_monitor.vad_noise_multiplier + 0.20)

            if self.state.bluetooth_mode:
                updates["guide_play_sec"] = max(
                    updates.get("guide_play_sec", controller_policy.guide_play_sec),
                    controller_policy.guide_play_sec + 0.30,
                )
                updates["seek_cooldown_sec"] = controller_policy.seek_cooldown_sec + 0.30

        if self.state.phase == "startup":
            if startup_false_hold_count >= 1:
                updates["guide_play_sec"] = controller_policy.guide_play_sec + 0.22
                updates["no_progress_hold_min_play_sec"] = controller_policy.no_progress_hold_min_play_sec + 0.28
                updates["hold_trend_sec"] = controller_policy.hold_trend_sec + 0.05

        elif self.state.phase == "steady":
            if progress is not None:
                if (
                    progress.tracking_quality >= 0.82
                    and progress.tracking_mode.value == "locked"
                    and mean_tracking_quality >= 0.78
                    and seek_count == 0
                ):
                    updates["tracking_quality_seek_min"] = controller_policy.tracking_quality_seek_min - 0.01
                    updates["hold_trend_sec"] = controller_policy.hold_trend_sec - 0.02

            if mean_tracking_quality >= 0.82 and startup_false_hold_count == 0 and lost_count == 0:
                updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min - 0.01

        else:
            if lost_count >= 2 or reacquire_count >= 3:
                updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min + 0.03
                updates["tracking_quality_seek_min"] = controller_policy.tracking_quality_seek_min + 0.03
                updates["hold_trend_sec"] = controller_policy.hold_trend_sec + 0.05
                updates["progress_stale_sec"] = controller_policy.progress_stale_sec + 0.06
                updates["seek_cooldown_sec"] = controller_policy.seek_cooldown_sec + 0.15

        if seek_count >= 2:
            updates["tracking_quality_seek_min"] = controller_policy.tracking_quality_seek_min + 0.02
            updates["seek_cooldown_sec"] = controller_policy.seek_cooldown_sec + 0.20

        if latency_snapshot is not None and hasattr(player, "set_output_offset_sec"):
            effective_output_ms = float(
                getattr(latency_snapshot, "estimated_output_latency_ms", 0.0)
                + getattr(latency_snapshot, "runtime_output_drift_ms", 0.0)
            )
            player.set_output_offset_sec(max(0.0, effective_output_ms / 1000.0))

        updates = self._clamp_updates(controller_policy, updates)
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

    def _capture_baseline(self, controller_policy) -> None:
        self.state.baseline_control = self._snapshot_control(controller_policy)
        if not self.state.last_good_control:
            self.state.last_good_control = dict(self.state.baseline_control)

    def _snapshot_control(self, controller_policy) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in self._CONTROL_KEYS:
            if hasattr(controller_policy, key):
                out[key] = float(getattr(controller_policy, key))
        return out

    def _restore_control(self, controller_policy, values: dict[str, float]) -> None:
        for key, value in values.items():
            if hasattr(controller_policy, key):
                setattr(controller_policy, key, float(value))

    def _clamp_updates(self, controller_policy, updates: dict[str, float]) -> dict[str, float]:
        baseline = self.state.baseline_control or self._snapshot_control(controller_policy)
        clamped: dict[str, float] = {}
        for key, value in updates.items():
            if key not in baseline:
                continue
            base = float(baseline[key])
            max_delta = float(self._MAX_DELTAS.get(key, 0.0))
            lo_hard, hi_hard = self._HARD_BOUNDS.get(key, (-1e9, 1e9))
            lo = max(lo_hard, base - max_delta)
            hi = min(hi_hard, base + max_delta)
            clamped[key] = max(lo, min(hi, float(value)))
        return clamped