from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

class ProfileStore:
    def __init__(self, profile_path: str) -> None:
        self.profile_path = Path(profile_path)
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.profile_path.exists():
            return {"devices": {}}
        try:
            return json.loads(self.profile_path.read_text(encoding="utf-8"))
        except Exception:
            return {"devices": {}}

    def save(self, data: dict[str, Any]) -> None:
        self.profile_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _device_key(self, input_device_id: str, output_device_id: str) -> str:
        return f"{input_device_id} -> {output_device_id}"

    def load_warm_start(
        self,
        *,
        input_device_id: str,
        output_device_id: str,
    ) -> dict[str, Any]:
        data = self.load()
        key = self._device_key(input_device_id, output_device_id)
        entry = data.get("devices", {}).get(key)
        if not isinstance(entry, dict):
            return {}

        control = dict(entry.get("recommended_control", {}))
        playback = dict(entry.get("recommended_playback", {}))
        signal = dict(entry.get("recommended_signal", {}))

        return {
            "control": control,
            "playback": playback,
            "signal": signal,
            "meta": {
                "sessions": int(entry.get("sessions", 0)),
                "last_updated_at": entry.get("last_updated_at", ""),
            },
        }

    def update_from_session(
        self,
        *,
        input_device_id: str,
        output_device_id: str,
        device_profile: dict[str, Any],
        metrics: dict[str, Any],
        latency_calibration: dict[str, Any] | None,
    ) -> None:
        data = self.load()
        devices = data.setdefault("devices", {})
        key = self._device_key(input_device_id, output_device_id)

        prev = devices.get(key, {})
        sessions = int(prev.get("sessions", 0))
        new_sessions = sessions + 1

        def ema(prev_value: float, new_value: float, n: int) -> float:
            if n <= 1:
                return float(new_value)
            alpha = min(0.35, 2.0 / (n + 1.0))
            return (1.0 - alpha) * float(prev_value) + alpha * float(new_value)

        avg_first_reliable = ema(
            float(prev.get("avg_first_reliable_progress_time_sec", 3.5)),
            float(metrics.get("first_reliable_progress_time_sec") or 6.0),
            new_sessions,
        )
        avg_startup_false_hold = ema(
            float(prev.get("avg_startup_false_hold_count", 0.0)),
            float(metrics.get("startup_false_hold_count", 0)),
            new_sessions,
        )
        avg_hold_count = ema(
            float(prev.get("avg_hold_count", 0.0)),
            float(metrics.get("hold_count", 0)),
            new_sessions,
        )
        avg_lost_count = ema(
            float(prev.get("avg_lost_count", 0.0)),
            float(metrics.get("lost_count", 0)),
            new_sessions,
        )
        avg_tracking_quality = ema(
            float(prev.get("avg_mean_tracking_quality", 0.55)),
            float(metrics.get("mean_tracking_quality", 0.0)),
            new_sessions,
        )
        avg_reacquire_count = ema(
            float(prev.get("avg_reacquire_count", 0.0)),
            float(metrics.get("reacquire_count", 0)),
            new_sessions,
        )

        estimated_output_latency_ms = float(
            (
                latency_calibration or {}
            ).get(
                "estimated_output_latency_ms",
                prev.get(
                    "estimated_output_latency_ms",
                    float(device_profile.get("estimated_output_latency_ms", 180.0)),
                ),
            )
        )

        estimated_input_latency_ms = float(
            (
                latency_calibration or {}
            ).get(
                "estimated_input_latency_ms",
                prev.get(
                    "estimated_input_latency_ms",
                    float(device_profile.get("estimated_input_latency_ms", 50.0)),
                ),
            )
        )

        recommended_control = self._derive_recommended_control(
            avg_first_reliable_progress_time_sec=avg_first_reliable,
            avg_startup_false_hold_count=avg_startup_false_hold,
            avg_hold_count=avg_hold_count,
            avg_lost_count=avg_lost_count,
            avg_mean_tracking_quality=avg_tracking_quality,
            avg_reacquire_count=avg_reacquire_count,
            reliability_tier=str(device_profile.get("reliability_tier", "medium")),
            input_gain_hint=str(device_profile.get("input_gain_hint", "normal")),
        )

        recommended_playback = {
            "bluetooth_output_offset_sec": max(0.0, estimated_output_latency_ms / 1000.0)
        }

        recommended_signal = self._derive_recommended_signal(
            reliability_tier=str(device_profile.get("reliability_tier", "medium")),
            input_gain_hint=str(device_profile.get("input_gain_hint", "normal")),
            noise_floor_rms=float(device_profile.get("noise_floor_rms", 0.0025)),
        )

        devices[key] = {
            "sessions": new_sessions,
            "input_device_id": input_device_id,
            "output_device_id": output_device_id,
            "device_profile": device_profile,
            "avg_first_reliable_progress_time_sec": avg_first_reliable,
            "avg_startup_false_hold_count": avg_startup_false_hold,
            "avg_hold_count": avg_hold_count,
            "avg_lost_count": avg_lost_count,
            "avg_reacquire_count": avg_reacquire_count,
            "avg_mean_tracking_quality": avg_tracking_quality,
            "estimated_output_latency_ms": estimated_output_latency_ms,
            "estimated_input_latency_ms": estimated_input_latency_ms,
            "recommended_control": recommended_control,
            "recommended_playback": recommended_playback,
            "recommended_signal": recommended_signal,
            "last_updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        self.save(data)

    def _derive_recommended_control(
        self,
        *,
        avg_first_reliable_progress_time_sec: float,
        avg_startup_false_hold_count: float,
        avg_hold_count: float,
        avg_lost_count: float,
        avg_mean_tracking_quality: float,
        avg_reacquire_count: float,
        reliability_tier: str,
        input_gain_hint: str,
    ) -> dict[str, float]:
        guide_play_sec = 2.20
        no_progress_hold_min_play_sec = 4.00
        progress_stale_sec = 1.10
        hold_trend_sec = 0.75
        tracking_quality_hold_min = 0.60
        tracking_quality_seek_min = 0.72
        resume_from_hold_speaking_lead_slack_sec = 0.45
        gain_soft_duck = 0.42

        if avg_first_reliable_progress_time_sec >= 4.5:
            guide_play_sec += 0.8
            no_progress_hold_min_play_sec += 1.2
            progress_stale_sec += 0.18
            hold_trend_sec += 0.12
            resume_from_hold_speaking_lead_slack_sec += 0.10

        if avg_startup_false_hold_count >= 1.0:
            guide_play_sec += 0.8
            no_progress_hold_min_play_sec += 1.0
            hold_trend_sec += 0.15
            tracking_quality_hold_min += 0.04

        if avg_lost_count >= 2.0 or avg_reacquire_count >= 4.0:
            progress_stale_sec += 0.14
            hold_trend_sec += 0.12
            tracking_quality_hold_min += 0.03
            tracking_quality_seek_min += 0.05
            gain_soft_duck -= 0.04

        if avg_mean_tracking_quality >= 0.78 and avg_hold_count <= 2.0:
            guide_play_sec -= 0.35
            no_progress_hold_min_play_sec -= 0.50
            hold_trend_sec -= 0.08
            tracking_quality_hold_min -= 0.03

        if reliability_tier == "low":
            guide_play_sec += 0.6
            no_progress_hold_min_play_sec += 0.8
            tracking_quality_seek_min += 0.05
            gain_soft_duck -= 0.04

        if input_gain_hint == "high":
            tracking_quality_hold_min -= 0.02
        elif input_gain_hint == "low":
            tracking_quality_hold_min += 0.03
            progress_stale_sec += 0.10

        return {
            "guide_play_sec": round(max(1.4, min(4.2, guide_play_sec)), 3),
            "no_progress_hold_min_play_sec": round(max(2.5, min(6.5, no_progress_hold_min_play_sec)), 3),
            "progress_stale_sec": round(max(0.8, min(1.8, progress_stale_sec)), 3),
            "hold_trend_sec": round(max(0.45, min(1.30, hold_trend_sec)), 3),
            "tracking_quality_hold_min": round(max(0.50, min(0.80, tracking_quality_hold_min)), 3),
            "tracking_quality_seek_min": round(max(0.64, min(0.90, tracking_quality_seek_min)), 3),
            "resume_from_hold_speaking_lead_slack_sec": round(
                max(0.25, min(0.90, resume_from_hold_speaking_lead_slack_sec)),
                3,
            ),
            "gain_soft_duck": round(max(0.28, min(0.55, gain_soft_duck)), 3),
        }

    def _derive_recommended_signal(
        self,
        *,
        reliability_tier: str,
        input_gain_hint: str,
        noise_floor_rms: float,
    ) -> dict[str, float]:
        min_vad_rms = 0.006
        vad_noise_multiplier = 2.8

        if reliability_tier == "low":
            min_vad_rms += 0.001
            vad_noise_multiplier += 0.2

        if input_gain_hint == "high":
            min_vad_rms -= 0.001
        elif input_gain_hint == "low":
            min_vad_rms += 0.001

        if noise_floor_rms >= 0.004:
            min_vad_rms += 0.001
            vad_noise_multiplier += 0.25

        return {
            "min_vad_rms": round(max(0.003, min(0.012, min_vad_rms)), 4),
            "vad_noise_multiplier": round(max(2.0, min(4.2, vad_noise_multiplier)), 3),
        }