from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shadowing.audio.device_profile import normalize_device_name


class ProfileStore:
    _DEFAULT_DATA = {
        "schema_version": 2,
        "devices": {},
    }

    def __init__(self, profile_path: str) -> None:
        self.profile_path = Path(profile_path)
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.profile_path.exists():
            return dict(self._DEFAULT_DATA)

        try:
            raw = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except Exception:
            return dict(self._DEFAULT_DATA)

        if not isinstance(raw, dict):
            return dict(self._DEFAULT_DATA)

        devices = raw.get("devices", {})
        if not isinstance(devices, dict):
            devices = {}

        schema_version = raw.get("schema_version", 1)
        try:
            schema_version = int(schema_version)
        except Exception:
            schema_version = 1

        return {
            "schema_version": schema_version,
            "devices": devices,
        }

    def save(self, data: dict[str, Any]) -> None:
        payload = dict(data or {})
        devices = payload.get("devices", {})
        if not isinstance(devices, dict):
            devices = {}

        payload["schema_version"] = 2
        payload["devices"] = devices

        self.profile_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _normalized_scalar_text(self, value: Any, default: str = "unknown") -> str:
        text = str(value or "").strip().lower()
        return text if text else default

    def _normalized_device_id(self, value: Any) -> str:
        text = normalize_device_name(value)
        return text if text else "unknown"

    def _canonical_device_key(
        self,
        *,
        input_device_id: str,
        output_device_id: str,
        hostapi_name: str = "",
        capture_backend: str = "",
        duplex_sample_rate: int | None = None,
        reliability_tier: str = "",
        bluetooth_mode: bool = False,
    ) -> str:
        return " | ".join(
            [
                f"in={self._normalized_device_id(input_device_id)}",
                f"out={self._normalized_device_id(output_device_id)}",
                f"hostapi={self._normalized_scalar_text(hostapi_name)}",
                f"backend={self._normalized_scalar_text(capture_backend)}",
                f"duplex_sr={max(0, int(duplex_sample_rate or 0))}",
                f"risk={self._normalized_scalar_text(reliability_tier)}",
                f"bt={int(bool(bluetooth_mode))}",
            ]
        )

    def _legacy_device_key(
        self,
        *,
        input_device_id: str,
        output_device_id: str,
        hostapi_name: str = "",
        capture_backend: str = "",
        duplex_sample_rate: int | None = None,
        reliability_tier: str = "",
        bluetooth_mode: bool = False,
    ) -> str:
        return " | ".join(
            [
                f"in={input_device_id}",
                f"out={output_device_id}",
                f"hostapi={hostapi_name or 'unknown'}",
                f"backend={capture_backend or 'unknown'}",
                f"duplex_sr={int(duplex_sample_rate or 0)}",
                f"risk={reliability_tier or 'unknown'}",
                f"bt={int(bool(bluetooth_mode))}",
            ]
        )

    def _candidate_keys(
        self,
        *,
        input_device_id: str,
        output_device_id: str,
        hostapi_name: str = "",
        capture_backend: str = "",
        duplex_sample_rate: int | None = None,
        reliability_tier: str = "",
        bluetooth_mode: bool = False,
    ) -> list[str]:
        canonical = self._canonical_device_key(
            input_device_id=input_device_id,
            output_device_id=output_device_id,
            hostapi_name=hostapi_name,
            capture_backend=capture_backend,
            duplex_sample_rate=duplex_sample_rate,
            reliability_tier=reliability_tier,
            bluetooth_mode=bluetooth_mode,
        )
        legacy = self._legacy_device_key(
            input_device_id=input_device_id,
            output_device_id=output_device_id,
            hostapi_name=hostapi_name,
            capture_backend=capture_backend,
            duplex_sample_rate=duplex_sample_rate,
            reliability_tier=reliability_tier,
            bluetooth_mode=bluetooth_mode,
        )
        if canonical == legacy:
            return [canonical]
        return [canonical, legacy]

    def _to_float(self, value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
        except Exception:
            return float(default)
        if out != out:
            return float(default)
        return float(out)

    def _to_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    def load_warm_start(
        self,
        *,
        input_device_id: str,
        output_device_id: str,
        hostapi_name: str = "",
        capture_backend: str = "",
        duplex_sample_rate: int | None = None,
        reliability_tier: str = "",
        bluetooth_mode: bool = False,
    ) -> dict[str, Any]:
        data = self.load()
        devices = data.get("devices", {})
        if not isinstance(devices, dict):
            return {}

        key = ""
        entry: dict[str, Any] | None = None
        for candidate_key in self._candidate_keys(
            input_device_id=input_device_id,
            output_device_id=output_device_id,
            hostapi_name=hostapi_name,
            capture_backend=capture_backend,
            duplex_sample_rate=duplex_sample_rate,
            reliability_tier=reliability_tier,
            bluetooth_mode=bluetooth_mode,
        ):
            maybe = devices.get(candidate_key)
            if isinstance(maybe, dict):
                key = candidate_key
                entry = maybe
                break

        if not isinstance(entry, dict):
            return {}

        control = dict(entry.get("recommended_control", {}))
        playback = dict(entry.get("recommended_playback", {}))
        signal = dict(entry.get("recommended_signal", {}))
        latency = dict(entry.get("recommended_latency", {}))

        stable_target_lead_sec = self._to_float(entry.get("stable_target_lead_sec", 0.0), 0.0)
        startup_target_lead_sec = self._to_float(entry.get("startup_target_lead_sec", 0.0), 0.0)

        if stable_target_lead_sec > 0.0:
            latency["stable_target_lead_sec"] = stable_target_lead_sec
        if startup_target_lead_sec > 0.0:
            latency["startup_target_lead_sec"] = startup_target_lead_sec

        return {
            "control": control,
            "playback": playback,
            "signal": signal,
            "latency": latency,
            "meta": {
                "sessions": self._to_int(entry.get("sessions", 0), 0),
                "last_updated_at": str(entry.get("last_updated_at", "")),
                "key": key,
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
        hostapi_name: str = "",
        capture_backend: str = "",
        duplex_sample_rate: int | None = None,
        bluetooth_mode: bool = False,
    ) -> None:
        data = self.load()
        devices = data.setdefault("devices", {})
        if not isinstance(devices, dict):
            devices = {}
            data["devices"] = devices

        reliability_tier = str(device_profile.get("reliability_tier", "medium"))

        candidate_keys = self._candidate_keys(
            input_device_id=input_device_id,
            output_device_id=output_device_id,
            hostapi_name=hostapi_name,
            capture_backend=capture_backend,
            duplex_sample_rate=duplex_sample_rate,
            reliability_tier=reliability_tier,
            bluetooth_mode=bluetooth_mode,
        )
        key = candidate_keys[0]

        prev: dict[str, Any] = {}
        matched_legacy_key: str | None = None
        for candidate_key in candidate_keys:
            maybe = devices.get(candidate_key)
            if isinstance(maybe, dict):
                prev = maybe
                if candidate_key != key:
                    matched_legacy_key = candidate_key
                break

        sessions = self._to_int(prev.get("sessions", 0), 0)
        new_sessions = sessions + 1

        def ema(prev_value: float, new_value: float, n: int) -> float:
            if n <= 1:
                return float(new_value)
            alpha = min(0.30, 2.0 / (n + 2.0))
            return (1.0 - alpha) * float(prev_value) + alpha * float(new_value)

        avg_first_reliable = ema(
            self._to_float(prev.get("avg_first_reliable_progress_time_sec", 3.6), 3.6),
            self._to_float(metrics.get("first_reliable_progress_time_sec"), 6.0),
            new_sessions,
        )
        avg_startup_false_hold = ema(
            self._to_float(prev.get("avg_startup_false_hold_count", 0.0), 0.0),
            self._to_float(metrics.get("startup_false_hold_count", 0), 0.0),
            new_sessions,
        )
        avg_hold_count = ema(
            self._to_float(prev.get("avg_hold_count", 0.0), 0.0),
            self._to_float(metrics.get("hold_count", 0), 0.0),
            new_sessions,
        )
        avg_lost_count = ema(
            self._to_float(prev.get("avg_lost_count", 0.0), 0.0),
            self._to_float(metrics.get("lost_count", 0), 0.0),
            new_sessions,
        )
        avg_tracking_quality = ema(
            self._to_float(prev.get("avg_mean_tracking_quality", 0.55), 0.55),
            self._to_float(metrics.get("mean_tracking_quality", 0.0), 0.0),
            new_sessions,
        )
        avg_reacquire_count = ema(
            self._to_float(prev.get("avg_reacquire_count", 0.0), 0.0),
            self._to_float(metrics.get("reacquire_count", 0), 0.0),
            new_sessions,
        )
        avg_seek_count = ema(
            self._to_float(prev.get("avg_seek_count", 0.0), 0.0),
            self._to_float(metrics.get("seek_count", 0), 0.0),
            new_sessions,
        )

        lc = latency_calibration or {}

        estimated_output_latency_ms = self._to_float(
            lc.get(
                "estimated_output_latency_ms",
                prev.get(
                    "estimated_output_latency_ms",
                    device_profile.get("estimated_output_latency_ms", 180.0),
                ),
            ),
            180.0,
        )
        estimated_input_latency_ms = self._to_float(
            lc.get(
                "estimated_input_latency_ms",
                prev.get(
                    "estimated_input_latency_ms",
                    device_profile.get("estimated_input_latency_ms", 50.0),
                ),
            ),
            50.0,
        )

        runtime_output_drift_ms = self._to_float(
            lc.get("runtime_output_drift_ms", prev.get("runtime_output_drift_ms", 0.0)),
            0.0,
        )
        runtime_input_drift_ms = self._to_float(
            lc.get("runtime_input_drift_ms", prev.get("runtime_input_drift_ms", 0.0)),
            0.0,
        )

        stable_target_lead_sec = self._to_float(
            lc.get(
                "stable_target_lead_sec",
                prev.get("stable_target_lead_sec", 0.35 if bluetooth_mode else 0.15),
            ),
            0.35 if bluetooth_mode else 0.15,
        )
        startup_target_lead_sec = self._to_float(
            lc.get(
                "startup_target_lead_sec",
                prev.get("startup_target_lead_sec", 0.28 if bluetooth_mode else 0.15),
            ),
            0.28 if bluetooth_mode else 0.15,
        )

        recommended_control = self._derive_recommended_control(
            avg_first_reliable_progress_time_sec=avg_first_reliable,
            avg_startup_false_hold_count=avg_startup_false_hold,
            avg_hold_count=avg_hold_count,
            avg_lost_count=avg_lost_count,
            avg_mean_tracking_quality=avg_tracking_quality,
            avg_reacquire_count=avg_reacquire_count,
            avg_seek_count=avg_seek_count,
            reliability_tier=reliability_tier,
            input_gain_hint=str(device_profile.get("input_gain_hint", "normal")),
            bluetooth_mode=bool(bluetooth_mode),
        )

        recommended_playback = {
            "bluetooth_output_offset_sec": max(
                0.0,
                (estimated_output_latency_ms + runtime_output_drift_ms) / 1000.0,
            )
        }

        recommended_signal = self._derive_recommended_signal(
            reliability_tier=reliability_tier,
            input_gain_hint=str(device_profile.get("input_gain_hint", "normal")),
            noise_floor_rms=self._to_float(device_profile.get("noise_floor_rms", 0.0025), 0.0025),
            bluetooth_mode=bool(bluetooth_mode),
        )

        recommended_latency = {
            "estimated_output_latency_ms": round(estimated_output_latency_ms, 3),
            "estimated_input_latency_ms": round(estimated_input_latency_ms, 3),
            "runtime_output_drift_ms": round(runtime_output_drift_ms, 3),
            "runtime_input_drift_ms": round(runtime_input_drift_ms, 3),
            "stable_target_lead_sec": round(stable_target_lead_sec, 3),
            "startup_target_lead_sec": round(startup_target_lead_sec, 3),
        }

        normalized_input_device_id = self._normalized_device_id(input_device_id)
        normalized_output_device_id = self._normalized_device_id(output_device_id)

        devices[key] = {
            "schema_version": 2,
            "sessions": new_sessions,
            "input_device_id": normalized_input_device_id,
            "output_device_id": normalized_output_device_id,
            "hostapi_name": self._normalized_scalar_text(hostapi_name),
            "capture_backend": self._normalized_scalar_text(capture_backend),
            "duplex_sample_rate": max(0, int(duplex_sample_rate or 0)),
            "bluetooth_mode": bool(bluetooth_mode),
            "device_profile": dict(device_profile),
            "avg_first_reliable_progress_time_sec": avg_first_reliable,
            "avg_startup_false_hold_count": avg_startup_false_hold,
            "avg_hold_count": avg_hold_count,
            "avg_lost_count": avg_lost_count,
            "avg_reacquire_count": avg_reacquire_count,
            "avg_seek_count": avg_seek_count,
            "avg_mean_tracking_quality": avg_tracking_quality,
            "estimated_output_latency_ms": estimated_output_latency_ms,
            "estimated_input_latency_ms": estimated_input_latency_ms,
            "runtime_output_drift_ms": runtime_output_drift_ms,
            "runtime_input_drift_ms": runtime_input_drift_ms,
            "stable_target_lead_sec": stable_target_lead_sec,
            "startup_target_lead_sec": startup_target_lead_sec,
            "recommended_control": recommended_control,
            "recommended_playback": recommended_playback,
            "recommended_signal": recommended_signal,
            "recommended_latency": recommended_latency,
            "last_updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        if matched_legacy_key is not None and matched_legacy_key in devices and matched_legacy_key != key:
            try:
                del devices[matched_legacy_key]
            except Exception:
                pass

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
        avg_seek_count: float,
        reliability_tier: str,
        input_gain_hint: str,
        bluetooth_mode: bool,
    ) -> dict[str, float]:
        guide_play_sec = 2.20
        no_progress_hold_min_play_sec = 4.00
        progress_stale_sec = 1.10
        hold_trend_sec = 0.75
        tracking_quality_hold_min = 0.60
        tracking_quality_seek_min = 0.72
        resume_from_hold_speaking_lead_slack_sec = 0.45
        gain_soft_duck = 0.42
        seek_cooldown_sec = 1.20

        if avg_first_reliable_progress_time_sec >= 4.5:
            guide_play_sec += 0.7
            no_progress_hold_min_play_sec += 1.0
            progress_stale_sec += 0.16
            hold_trend_sec += 0.10
            resume_from_hold_speaking_lead_slack_sec += 0.08

        if avg_startup_false_hold_count >= 1.0:
            guide_play_sec += 0.6
            no_progress_hold_min_play_sec += 0.8
            hold_trend_sec += 0.10

        if avg_lost_count >= 2.0 or avg_reacquire_count >= 4.0:
            progress_stale_sec += 0.10
            hold_trend_sec += 0.10
            tracking_quality_hold_min += 0.03
            tracking_quality_seek_min += 0.04
            gain_soft_duck -= 0.03

        if avg_seek_count >= 2.0:
            tracking_quality_seek_min += 0.03
            seek_cooldown_sec += 0.30

        if avg_mean_tracking_quality >= 0.78 and avg_hold_count <= 2.0:
            guide_play_sec -= 0.30
            no_progress_hold_min_play_sec -= 0.40
            hold_trend_sec -= 0.06
            tracking_quality_hold_min -= 0.02

        if reliability_tier == "low":
            guide_play_sec += 0.5
            no_progress_hold_min_play_sec += 0.7
            tracking_quality_seek_min += 0.04
            seek_cooldown_sec += 0.25
            gain_soft_duck -= 0.03

        if bluetooth_mode:
            guide_play_sec += 0.35
            no_progress_hold_min_play_sec += 0.45
            progress_stale_sec += 0.08
            tracking_quality_seek_min += 0.05
            seek_cooldown_sec += 0.40
            resume_from_hold_speaking_lead_slack_sec += 0.06

        if input_gain_hint == "high":
            tracking_quality_hold_min -= 0.02
        elif input_gain_hint == "low":
            tracking_quality_hold_min += 0.03
            progress_stale_sec += 0.08

        return {
            "guide_play_sec": round(max(1.4, min(4.4, guide_play_sec)), 3),
            "no_progress_hold_min_play_sec": round(max(2.5, min(6.8, no_progress_hold_min_play_sec)), 3),
            "progress_stale_sec": round(max(0.8, min(1.9, progress_stale_sec)), 3),
            "hold_trend_sec": round(max(0.45, min(1.35, hold_trend_sec)), 3),
            "tracking_quality_hold_min": round(max(0.50, min(0.82, tracking_quality_hold_min)), 3),
            "tracking_quality_seek_min": round(max(0.66, min(0.92, tracking_quality_seek_min)), 3),
            "resume_from_hold_speaking_lead_slack_sec": round(
                max(0.25, min(0.95, resume_from_hold_speaking_lead_slack_sec)),
                3,
            ),
            "gain_soft_duck": round(max(0.28, min(0.55, gain_soft_duck)), 3),
            "seek_cooldown_sec": round(max(0.9, min(2.4, seek_cooldown_sec)), 3),
        }

    def _derive_recommended_signal(
        self,
        *,
        reliability_tier: str,
        input_gain_hint: str,
        noise_floor_rms: float,
        bluetooth_mode: bool,
    ) -> dict[str, float]:
        min_vad_rms = 0.006
        vad_noise_multiplier = 2.8

        if reliability_tier == "low":
            min_vad_rms += 0.001
            vad_noise_multiplier += 0.2

        if bluetooth_mode:
            min_vad_rms += 0.0005
            vad_noise_multiplier += 0.15

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