# 项目快照

自动生成。已移除 Python 注释、docstring、print 和空行。

---
### 文件: `shadowing_app/src/shadowing/adaptation/profile_store.py`

```python
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
```

---
### 文件: `shadowing_app/src/shadowing/adaptation/runtime_auto_tuner.py`

```python
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
```

---
### 文件: `shadowing_app/src/shadowing/analytics/pipeline.py`

```python
from __future__ import annotations
from shadowing.interfaces.analytics import AnalyticsProvider
class SessionAnalyticsPipeline:
    def __init__(self, provider: AnalyticsProvider) -> None:
        self.provider = provider
    def run(self, lesson_text: str, user_audio_path: str, output_dir: str) -> dict:
        return self.provider.analyze_session(
                lesson_text=lesson_text,
                audio_path=user_audio_path,
                output_dir=output_dir,
                        )
```

---
### 文件: `shadowing_app/src/shadowing/analytics/providers/elevenlabs_scribe.py`

```python
from __future__ import annotations
from shadowing.interfaces.analytics import AnalyticsProvider
class ElevenLabsScribeProvider(AnalyticsProvider):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
    def analyze_session(self, lesson_text: str, audio_path: str, output_dir: str) -> dict:
        raise NotImplementedError("Wire your preferred ElevenLabs Scribe batch endpoint here.")
```

---
### 文件: `shadowing_app/src/shadowing/audio/audio_behavior_classifier.py`

```python
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
```

---
### 文件: `shadowing_app/src/shadowing/audio/audio_feature_ring_buffer.py`

```python
from __future__ import annotations
from collections import deque
from shadowing.audio.frame_feature_extractor import AudioFrameFeature
class AudioFeatureRingBuffer:
    def __init__(self, max_duration_sec: float = 6.0) -> None:
        self.max_duration_sec = max(1.0, float(max_duration_sec))
        self._items: deque[AudioFrameFeature] = deque()
    def reset(self) -> None:
        self._items.clear()
    def append_many(self, frames: list[AudioFrameFeature]) -> None:
        for item in frames:
            self._items.append(item)
        self._trim()
    def get_recent(self, duration_sec: float) -> list[AudioFrameFeature]:
        if not self._items:
            return []
        latest = self._items[-1].observed_at_sec
        cutoff = latest - max(0.0, float(duration_sec))
        return [x for x in self._items if x.observed_at_sec >= cutoff]
    def latest_time_sec(self) -> float:
        if not self._items:
            return 0.0
        return float(self._items[-1].observed_at_sec)
    def _trim(self) -> None:
        if not self._items:
            return
        latest = self._items[-1].observed_at_sec
        cutoff = latest - self.max_duration_sec
        while self._items and self._items[0].observed_at_sec < cutoff:
            self._items.popleft()
```

---
### 文件: `shadowing_app/src/shadowing/audio/bluetooth_preflight.py`

```python
from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
import numpy as np
import sounddevice as sd
from shadowing.audio.device_profile import (
    normalize_device_name,
)
_BLUETOOTH_KEYWORDS = (
    "bluetooth",
    "headset",
    "hands-free",
    "hands free",
    "airpods",
    "buds",
    "earbuds",
    "zero air",
    "耳机",
    "蓝牙",
)
def _looks_like_bluetooth(name: str | None) -> bool:
    text = str(name or "").strip().lower()
    if not text:
        return False
    return any(k in text for k in _BLUETOOTH_KEYWORDS)
def _device_family_key(name: str | None) -> str:
    text = str(name or "").strip().lower()
    if not text:
        return ""
    normalized = (
        text.replace("hands-free", "handsfree")
        .replace("hands free", "handsfree")
        .replace("(", " ")
        .replace(")", " ")
        .replace("[", " ")
        .replace("]", " ")
        .replace("-", " ")
        .replace("_", " ")
    )
    for token in (
        "zero air",
        "airpods",
        "earbuds",
        "buds",
        "handsfree",
        "headset",
        "耳机",
        "蓝牙",
    ):
        if token in normalized:
            return token
    return " ".join(normalized.split())
@dataclass(slots=True)
class ResolvedDevice:
    index: int
    name: str
    normalized_name: str
    family_key: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    hostapi_name: str
@dataclass(slots=True)
class BluetoothPreflightConfig:
    input_device: int | str | None
    output_device: int | str | None
    preferred_input_samplerate: int = 48000
    preferred_output_samplerate: int = 44100
    duration_sec: float = 4.0
    warmup_ignore_sec: float = 0.9
    blocksize: int = 0
    probe_tone_hz: float = 880.0
    probe_tone_amp: float = 0.05
    min_mean_rms: float = 0.0015
    min_peak: float = 0.0150
    min_nonzero_ratio: float = 0.010
    min_voiced_frame_ratio: float = 0.12
    strong_rms: float = 0.0060
    strong_peak: float = 0.0200
    strong_voiced_frame_ratio: float = 0.22
    max_status_events: int = 10
@dataclass(slots=True)
class BluetoothPreflightResult:
    should_run: bool
    passed: bool
    input_device_index: int | None = None
    input_device_name: str = ""
    input_device_family_key: str = ""
    input_hostapi_name: str = ""
    output_device_index: int | None = None
    output_device_name: str = ""
    output_device_family_key: str = ""
    output_hostapi_name: str = ""
    samplerate: int = 0
    mean_rms: float = 0.0
    max_peak: float = 0.0
    nonzero_ratio: float = 0.0
    voiced_frame_ratio: float = 0.0
    tail_mean_rms: float = 0.0
    tail_max_peak: float = 0.0
    tail_nonzero_ratio: float = 0.0
    tail_voiced_frame_ratio: float = 0.0
    status_events: int = 0
    failure_reason: str = ""
    notes: list[str] = field(default_factory=list)
def _resolve_hostapi_name(dev: dict) -> str:
    hostapis = sd.query_hostapis()
    return str(hostapis[int(dev["hostapi"])]["name"])
def _build_resolved_device(idx: int, dev: dict) -> ResolvedDevice:
    name = str(dev["name"])
    return ResolvedDevice(
        index=int(idx),
        name=name,
        normalized_name=normalize_device_name(name),
        family_key=_device_family_key(name),
        max_input_channels=int(dev["max_input_channels"]),
        max_output_channels=int(dev["max_output_channels"]),
        default_samplerate=float(dev["default_samplerate"]),
        hostapi_name=_resolve_hostapi_name(dev),
    )
def _resolve_input_device(device: int | str | None) -> ResolvedDevice:
    devices = sd.query_devices()
    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(
                f"Resolved input device is not an input device: idx={device}, name={dev['name']}"
            )
        return _build_resolved_device(int(device), dev)
    if device is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            raise RuntimeError("No default input device available for bluetooth preflight.")
        dev = sd.query_devices(int(default_in))
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(
                f"Default input device is invalid: idx={default_in}, name={dev['name']}"
            )
        return _build_resolved_device(int(default_in), dev)
    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return _build_resolved_device(int(idx), dev)
    raise RuntimeError(f"No matching input device found for bluetooth preflight: {device!r}")
def _resolve_output_device(device: int | str | None) -> ResolvedDevice:
    devices = sd.query_devices()
    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_output_channels"]) <= 0:
            raise RuntimeError(
                f"Resolved output device is not an output device: idx={device}, name={dev['name']}"
            )
        return _build_resolved_device(int(device), dev)
    if device is None:
        _, default_out = sd.default.device
        if default_out is None or int(default_out) < 0:
            raise RuntimeError("No default output device available for bluetooth preflight.")
        dev = sd.query_devices(int(default_out))
        if int(dev["max_output_channels"]) <= 0:
            raise RuntimeError(
                f"Default output device is invalid: idx={default_out}, name={dev['name']}"
            )
        return _build_resolved_device(int(default_out), dev)
    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_output_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return _build_resolved_device(int(idx), dev)
    raise RuntimeError(f"No matching output device found for bluetooth preflight: {device!r}")
def should_run_bluetooth_preflight(
    input_device: int | str | None,
    output_device: int | str | None,
) -> bool:
    try:
        input_resolved = _resolve_input_device(input_device)
        output_resolved = _resolve_output_device(output_device)
    except Exception:
        return False
    input_is_bt = _looks_like_bluetooth(input_resolved.name)
    output_is_bt = _looks_like_bluetooth(output_resolved.name)
    if not (input_is_bt and output_is_bt):
        return False
    if (
        input_resolved.family_key
        and output_resolved.family_key
        and input_resolved.family_key != output_resolved.family_key
    ):
        return False
    return True
def _pick_duplex_samplerate(
    input_dev: ResolvedDevice,
    output_dev: ResolvedDevice,
    preferred_input_sr: int,
    preferred_output_sr: int,
) -> int:
    candidates: list[int] = []
    for sr in (
        preferred_input_sr,
        preferred_output_sr,
        48000,
        44100,
        32000,
        24000,
        16000,
        int(input_dev.default_samplerate),
        int(output_dev.default_samplerate),
    ):
        if sr > 0 and sr not in candidates:
            candidates.append(int(sr))
    last_error: Exception | None = None
    for sr in candidates:
        try:
            sd.check_input_settings(
                device=input_dev.index,
                samplerate=sr,
                channels=1,
                dtype="float32",
            )
            sd.check_output_settings(
                device=output_dev.index,
                samplerate=sr,
                channels=1,
                dtype="float32",
            )
            return int(sr)
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(
        "No common duplex samplerate available for bluetooth preflight. "
        f"input={input_dev.name!r}, output={output_dev.name!r}, last_error={last_error}"
    )
def _safe_mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0
def _safe_max(values: list[float]) -> float:
    return float(np.max(values)) if values else 0.0
def run_bluetooth_duplex_preflight(
    config: BluetoothPreflightConfig,
) -> BluetoothPreflightResult:
    if not should_run_bluetooth_preflight(config.input_device, config.output_device):
        return BluetoothPreflightResult(
            should_run=False,
            passed=True,
            notes=["当前不是同一蓝牙耳机的双工会话，跳过蓝牙双工预检。"],
        )
    input_dev = _resolve_input_device(config.input_device)
    output_dev = _resolve_output_device(config.output_device)
    samplerate = _pick_duplex_samplerate(
        input_dev=input_dev,
        output_dev=output_dev,
        preferred_input_sr=config.preferred_input_samplerate,
        preferred_output_sr=config.preferred_output_samplerate,
    )
    result = BluetoothPreflightResult(
        should_run=True,
        passed=False,
        input_device_index=input_dev.index,
        input_device_name=input_dev.normalized_name,
        input_device_family_key=input_dev.family_key,
        input_hostapi_name=input_dev.hostapi_name,
        output_device_index=output_dev.index,
        output_device_name=output_dev.normalized_name,
        output_device_family_key=output_dev.family_key,
        output_hostapi_name=output_dev.hostapi_name,
        samplerate=samplerate,
    )
    rms_values: list[float] = []
    peak_values: list[float] = []
    nonzero_ratios: list[float] = []
    voiced_flags: list[int] = []
    tail_rms_values: list[float] = []
    tail_peak_values: list[float] = []
    tail_nonzero_ratios: list[float] = []
    tail_voiced_flags: list[int] = []
    status_events = 0
    done = threading.Event()
    started_at = time.monotonic()
    tone_phase = 0.0
    lock = threading.Lock()
    def callback(indata, outdata, frames, time_info, status) -> None:
        nonlocal status_events, tone_phase
        _ = time_info
        now = time.monotonic()
        elapsed = now - started_at
        if status:
            with lock:
                status_events += 1
        audio = np.asarray(indata, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        nonzero_ratio = float(np.mean(np.abs(audio) > 1e-4)) if audio.size else 0.0
        voiced = 1 if (rms >= config.strong_rms or peak >= config.strong_peak) else 0
        with lock:
            rms_values.append(rms)
            peak_values.append(peak)
            nonzero_ratios.append(nonzero_ratio)
            voiced_flags.append(voiced)
            if elapsed >= config.warmup_ignore_sec:
                tail_rms_values.append(rms)
                tail_peak_values.append(peak)
                tail_nonzero_ratios.append(nonzero_ratio)
                tail_voiced_flags.append(voiced)
        t = (np.arange(frames, dtype=np.float32) + tone_phase) / float(samplerate)
        tone = config.probe_tone_amp * np.sin(2.0 * np.pi * config.probe_tone_hz * t).astype(
            np.float32,
            copy=False,
        )
        tone_phase += frames
        outdata.fill(0.0)
        outdata[:, 0] = tone
        if elapsed >= config.duration_sec:
            done.set()
            outdata.fill(0.0)
    try:
        with sd.Stream(
            samplerate=samplerate,
            blocksize=int(config.blocksize),
            dtype="float32",
            channels=(1, 1),
            callback=callback,
            device=(input_dev.index, output_dev.index),
            latency="low",
        ):
            finished = done.wait(timeout=max(1.0, float(config.duration_sec) + 1.5))
            if not finished:
                result.failure_reason = "bluetooth_duplex_preflight_timeout"
                result.notes.append("蓝牙双工预检超时，音频回调可能未按预期工作。")
                return result
    except Exception as e:
        result.failure_reason = (
            "bluetooth_duplex_open_failed: "
            f"input={input_dev.name!r}, output={output_dev.name!r}, samplerate={samplerate}, error={e}"
        )
        return result
    with lock:
        result.mean_rms = _safe_mean(rms_values)
        result.max_peak = _safe_max(peak_values)
        result.nonzero_ratio = _safe_mean(nonzero_ratios)
        result.voiced_frame_ratio = _safe_mean(voiced_flags)
        result.tail_mean_rms = _safe_mean(tail_rms_values)
        result.tail_max_peak = _safe_max(tail_peak_values)
        result.tail_nonzero_ratio = _safe_mean(tail_nonzero_ratios)
        result.tail_voiced_frame_ratio = _safe_mean(tail_voiced_flags)
        result.status_events = int(status_events)
    failure_reasons: list[str] = []
    if result.status_events > config.max_status_events:
        failure_reasons.append(
            f"status_events_too_many({result.status_events}>{config.max_status_events})"
        )
    strong_pass = (
        result.tail_max_peak >= config.strong_peak
        and result.tail_voiced_frame_ratio >= config.strong_voiced_frame_ratio
    )
    weak_pass = (
        result.tail_max_peak >= config.min_peak
        and result.tail_voiced_frame_ratio >= config.min_voiced_frame_ratio
        and (
            result.tail_nonzero_ratio >= config.min_nonzero_ratio
            or result.tail_mean_rms >= config.min_mean_rms
        )
    )
    if not strong_pass and not weak_pass:
        if result.tail_max_peak < config.min_peak:
            failure_reasons.append(
                f"tail_peak_too_low(tail_max_peak={result.tail_max_peak:.6f})"
            )
        if result.tail_voiced_frame_ratio < config.min_voiced_frame_ratio:
            failure_reasons.append(
                "tail_voice_activity_too_low("
                f"tail_voiced_frame_ratio={result.tail_voiced_frame_ratio:.6f})"
            )
        if (
            result.tail_nonzero_ratio < config.min_nonzero_ratio
            and result.tail_mean_rms < config.min_mean_rms
        ):
            failure_reasons.append(
                "tail_input_too_weak("
                f"tail_mean_rms={result.tail_mean_rms:.6f}, "
                f"tail_nonzero_ratio={result.tail_nonzero_ratio:.6f})"
            )
    if failure_reasons:
        result.failure_reason = "; ".join(failure_reasons)
        result.notes.append("蓝牙耳机双工链路未通过启动前检测。")
        result.notes.append("这通常表示系统未切到稳定通话模式，或当前输入链路在实时采集下过弱。")
        result.notes.append("对这类耳机，建议固定 input samplerate=48000。")
        result.notes.append("如果你刚才一直在持续说话但仍失败，当前系统蓝牙双工状态不适合直接启动实时跟读。")
        return result
    result.passed = True
    result.notes.append("蓝牙耳机双工预检通过。")
    result.notes.append("本次结果已按该耳机前段迟滞特性进行容忍。")
    return result
```

---
### 文件: `shadowing_app/src/shadowing/audio/device_profile.py`

```python
from __future__ import annotations
from dataclasses import dataclass
import re
_BLUETOOTH_KEYWORDS = (
    "bluetooth",
    "headset",
    "hands-free",
    "hands free",
    "airpods",
    "buds",
    "earbuds",
    "zero air",
    "耳机",
    "蓝牙",
)
_USB_KEYWORDS = (
    "usb",
    "type-c",
    "type c",
    "dongle",
)
_INPUT_MIC_KEYWORDS = (
    "microphone",
    "mic",
    "麦克风",
    "话筒",
)
_BUILTIN_MIC_KEYWORDS = (
    "array",
    "阵列",
    "realtek",
    "internal",
    "built-in",
    "builtin",
    "内置",
)
_SPEAKER_KEYWORDS = (
    "speaker",
    "speakers",
    "扬声器",
    "喇叭",
)
_WIRED_HEADSET_KEYWORDS = (
    "headphone",
    "headphones",
    "headset",
    "耳麦",
    "耳机",
    "3.5mm",
    "line out",
    "line-out",
)
def _normalize_text(value: int | str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text
def _normalize_compact_text(value: int | str | None) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = (
        text.replace("hands-free", "handsfree")
        .replace("hands free", "handsfree")
        .replace("built-in", "builtin")
        .replace("line-out", "lineout")
        .replace("type-c", "typec")
        .replace("type c", "typec")
    )
    text = re.sub(r"[\[\]{}()<>]", " ", text)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    if not text:
        return False
    return any(k in text for k in keywords)
def _looks_like_bluetooth(name: str | None) -> bool:
    text = _normalize_text(name)
    if not text:
        return False
    return _contains_any(text, _BLUETOOTH_KEYWORDS)
def _device_family_key(name: str | None) -> str:
    text = _normalize_compact_text(name)
    if not text:
        return ""
    for token in (
        "zero air",
        "airpods",
        "earbuds",
        "buds",
        "handsfree",
        "headset",
        "耳机",
        "蓝牙",
    ):
        if token in text:
            return token
    return " ".join(text.split())
def normalize_device_name(device_name: int | str | None) -> str:
    text = _normalize_text(device_name)
    return text if text else "unknown"
def normalize_device_id(
    *,
    device_name: int | str | None,
    hostapi_name: str | None = None,
    device_index: int | None = None,
) -> str:
    norm_name = normalize_device_name(device_name)
    norm_hostapi = _normalize_text(hostapi_name) or "unknown"
    parts = [f"hostapi={norm_hostapi}", f"name={norm_name}"]
    if device_index is not None:
        try:
            parts.append(f"idx={int(device_index)}")
        except Exception:
            pass
    return " | ".join(parts)
@dataclass(slots=True)
class DeviceProfile:
    input_device_id: str
    output_device_id: str
    input_device_name: str
    output_device_name: str
    input_family_key: str
    output_family_key: str
    input_kind: str
    output_kind: str
    input_sample_rate: int
    output_sample_rate: int
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    noise_floor_rms: float
    input_gain_hint: str
    reliability_tier: str
    bluetooth_mode: bool = False
    hostapi_name: str = ""
    capture_backend: str = ""
def classify_input_device(device_name: int | str | None) -> str:
    name = _normalize_text(device_name)
    if not name:
        return "unknown"
    if _looks_like_bluetooth(name):
        return "bluetooth_headset"
    if _contains_any(name, _USB_KEYWORDS) and (
        _contains_any(name, _INPUT_MIC_KEYWORDS) or "audio" in name
    ):
        return "usb_mic"
    if _contains_any(name, _BUILTIN_MIC_KEYWORDS):
        return "builtin_mic"
    if _contains_any(name, _INPUT_MIC_KEYWORDS):
        return "mic"
    return "unknown"
def classify_output_device(device_name: int | str | None) -> str:
    name = _normalize_text(device_name)
    if not name:
        return "unknown"
    if _looks_like_bluetooth(name):
        return "bluetooth_headset"
    if _contains_any(name, _SPEAKER_KEYWORDS):
        return "speaker"
    if _contains_any(name, _USB_KEYWORDS) and (
        _contains_any(name, _WIRED_HEADSET_KEYWORDS) or "audio" in name
    ):
        return "wired_headset"
    if _contains_any(name, _WIRED_HEADSET_KEYWORDS):
        return "wired_headset"
    return "unknown"
def infer_input_gain_hint(noise_floor_rms: float) -> str:
    value = max(0.0, float(noise_floor_rms))
    if value < 0.0015:
        return "high"
    if value < 0.0040:
        return "normal"
    return "low"
def infer_reliability_tier(input_kind: str, output_kind: str) -> str:
    input_kind = str(input_kind or "unknown")
    output_kind = str(output_kind or "unknown")
    if input_kind == "bluetooth_headset" or output_kind == "bluetooth_headset":
        return "low"
    if input_kind == "unknown" or output_kind == "unknown":
        return "medium"
    if input_kind in {"builtin_mic", "mic"} and output_kind == "speaker":
        return "medium"
    return "high"
def default_input_latency_ms(input_kind: str) -> float:
    kind = str(input_kind or "unknown")
    if kind == "bluetooth_headset":
        return 140.0
    if kind == "usb_mic":
        return 35.0
    if kind == "builtin_mic":
        return 28.0
    if kind == "mic":
        return 40.0
    return 50.0
def default_output_latency_ms(output_kind: str) -> float:
    kind = str(output_kind or "unknown")
    if kind == "bluetooth_headset":
        return 180.0
    if kind == "wired_headset":
        return 40.0
    if kind == "speaker":
        return 35.0
    return 60.0
def build_device_profile(
    input_device_name: int | str | None,
    output_device_name: int | str | None,
    input_sample_rate: int,
    output_sample_rate: int,
    noise_floor_rms: float,
    *,
    hostapi_name: str = "",
    capture_backend: str = "",
    input_device_id: str | None = None,
    output_device_id: str | None = None,
) -> DeviceProfile:
    normalized_input_name = normalize_device_name(input_device_name)
    normalized_output_name = normalize_device_name(output_device_name)
    input_kind = classify_input_device(normalized_input_name)
    output_kind = classify_output_device(normalized_output_name)
    normalized_noise_floor = max(0.0, float(noise_floor_rms))
    bluetooth_mode = bool(
        input_kind == "bluetooth_headset" or output_kind == "bluetooth_headset"
    )
    resolved_input_device_id = (
        str(input_device_id).strip()
        if str(input_device_id or "").strip()
        else normalize_device_id(
            device_name=normalized_input_name,
            hostapi_name=hostapi_name,
        )
    )
    resolved_output_device_id = (
        str(output_device_id).strip()
        if str(output_device_id or "").strip()
        else normalize_device_id(
            device_name=normalized_output_name,
            hostapi_name=hostapi_name,
        )
    )
    return DeviceProfile(
        input_device_id=resolved_input_device_id,
        output_device_id=resolved_output_device_id,
        input_device_name=normalized_input_name,
        output_device_name=normalized_output_name,
        input_family_key=_device_family_key(normalized_input_name),
        output_family_key=_device_family_key(normalized_output_name),
        input_kind=input_kind,
        output_kind=output_kind,
        input_sample_rate=max(0, int(input_sample_rate)),
        output_sample_rate=max(0, int(output_sample_rate)),
        estimated_input_latency_ms=float(default_input_latency_ms(input_kind)),
        estimated_output_latency_ms=float(default_output_latency_ms(output_kind)),
        noise_floor_rms=normalized_noise_floor,
        input_gain_hint=infer_input_gain_hint(normalized_noise_floor),
        reliability_tier=infer_reliability_tier(input_kind, output_kind),
        bluetooth_mode=bluetooth_mode,
        hostapi_name=str(hostapi_name or ""),
        capture_backend=str(capture_backend or ""),
    )
```

---
### 文件: `shadowing_app/src/shadowing/audio/frame_feature_extractor.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
@dataclass(slots=True)
class AudioFrameFeature:
    observed_at_sec: float
    envelope: float
    onset_strength: float
    voiced_ratio: float
    band_energy: list[float]
    embedding: list[float] = field(default_factory=list)
class FrameFeatureExtractor:
    def __init__(
        self,
        sample_rate: int,
        frame_size_sec: float = 0.025,
        hop_sec: float = 0.010,
        n_bands: int = 6,
        min_voiced_rms: float = 0.005,
        n_mels: int = 24,
        embedding_alpha: float = 0.35,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.frame_size_sec = float(frame_size_sec)
        self.hop_sec = float(hop_sec)
        self.n_bands = max(2, int(n_bands))
        self.min_voiced_rms = float(min_voiced_rms)
        self.n_mels = max(8, int(n_mels))
        self.embedding_alpha = float(max(0.0, min(1.0, embedding_alpha)))
        self.frame_size = max(16, int(round(self.sample_rate * self.frame_size_sec)))
        self.hop_size = max(8, int(round(self.sample_rate * self.hop_sec)))
        self._tail = np.zeros((0,), dtype=np.float32)
        self._last_envelope = 0.0
        self._last_log_mel = np.zeros((self.n_mels,), dtype=np.float32)
    def reset(self) -> None:
        self._tail = np.zeros((0,), dtype=np.float32)
        self._last_envelope = 0.0
        self._last_log_mel = np.zeros((self.n_mels,), dtype=np.float32)
    def process_pcm16(
        self,
        pcm_bytes: bytes,
        *,
        observed_at_sec: float,
    ) -> list[AudioFrameFeature]:
        if not pcm_bytes:
            return []
        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return []
        audio_f32 = (audio_i16.astype(np.float32) / 32768.0).astype(
            np.float32,
            copy=False,
        )
        start_time_sec = float(observed_at_sec) - (
            audio_f32.shape[0] / float(self.sample_rate)
        )
        return self.process_float_audio(audio_f32, start_time_sec=start_time_sec)
    def process_float_audio(
        self,
        audio_f32: np.ndarray,
        *,
        start_time_sec: float,
    ) -> list[AudioFrameFeature]:
        arr = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return []
        old_tail_len = self._tail.shape[0]
        full = np.concatenate([self._tail, arr], axis=0)
        full_start_time_sec = float(start_time_sec) - (
            old_tail_len / float(self.sample_rate)
        )
        out: list[AudioFrameFeature] = []
        pos = 0
        while pos + self.frame_size <= full.shape[0]:
            frame = full[pos : pos + self.frame_size]
            frame_time_sec = full_start_time_sec + pos / float(self.sample_rate)
            out.append(self._extract_frame_feature(frame, frame_time_sec))
            pos += self.hop_size
        self._tail = full[pos:].astype(np.float32, copy=False)
        max_tail = max(self.frame_size, self.hop_size) * 2
        if self._tail.shape[0] > max_tail:
            self._tail = self._tail[-max_tail:]
        return out
    def _extract_frame_feature(
        self,
        frame: np.ndarray,
        frame_time_sec: float,
    ) -> AudioFrameFeature:
        envelope = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        onset_strength = max(0.0, envelope - self._last_envelope)
        self._last_envelope = envelope
        abs_frame = np.abs(frame)
        voiced_ratio = (
            float(np.mean(abs_frame >= max(self.min_voiced_rms, envelope * 0.55)))
            if frame.size
            else 0.0
        )
        win = np.hanning(frame.shape[0]).astype(np.float32, copy=False)
        spec = np.abs(np.fft.rfft(frame * win))
        if spec.size <= 1:
            band_energy = [0.0] * self.n_bands
            log_mel = np.zeros((self.n_mels,), dtype=np.float32)
        else:
            band_energy = self._compute_band_energy(spec)
            log_mel = self._compute_log_mel(spec)
        delta = log_mel - self._last_log_mel
        smoothed = (
            (1.0 - self.embedding_alpha) * self._last_log_mel
            + self.embedding_alpha * log_mel
        )
        self._last_log_mel = smoothed.astype(np.float32, copy=False)
        embedding = np.concatenate(
            [
                smoothed,
                delta,
                np.asarray(
                    [envelope, onset_strength, voiced_ratio],
                    dtype=np.float32,
                ),
            ],
            axis=0,
        )
        norm = float(np.linalg.norm(embedding))
        if norm > 1e-6:
            embedding = embedding / norm
        return AudioFrameFeature(
            observed_at_sec=float(frame_time_sec),
            envelope=float(envelope),
            onset_strength=float(onset_strength),
            voiced_ratio=float(voiced_ratio),
            band_energy=band_energy,
            embedding=embedding.astype(np.float32, copy=False).tolist(),
        )
    def _compute_band_energy(self, spec: np.ndarray) -> list[float]:
        eps = 1e-8
        power = np.square(np.asarray(spec, dtype=np.float32))
        edges = np.linspace(0, power.shape[0], self.n_bands + 1, dtype=int)
        band_energy: list[float] = []
        total = float(np.sum(power) + eps)
        for i in range(self.n_bands):
            lo = int(edges[i])
            hi = int(edges[i + 1])
            if hi <= lo:
                band_energy.append(0.0)
            else:
                band_energy.append(float(np.sum(power[lo:hi]) / total))
        return band_energy
    def _compute_log_mel(self, spec: np.ndarray) -> np.ndarray:
        power = np.square(np.asarray(spec, dtype=np.float32))
        n_bins = power.shape[0]
        edges = np.linspace(0, n_bins, self.n_mels + 1, dtype=int)
        mel = np.zeros((self.n_mels,), dtype=np.float32)
        for i in range(self.n_mels):
            lo = int(edges[i])
            hi = max(lo + 1, int(edges[i + 1]))
            mel[i] = float(np.mean(power[lo:hi]))
        mel = np.log1p(mel)
        mu = float(np.mean(mel))
        sigma = float(np.std(mel))
        if sigma > 1e-6:
            mel = (mel - mu) / sigma
        else:
            mel = mel - mu
        return mel.astype(np.float32, copy=False)
```

---
### 文件: `shadowing_app/src/shadowing/audio/latency_calibrator.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from statistics import median
from shadowing.audio.device_profile import DeviceProfile
from shadowing.types import SignalQuality
@dataclass(slots=True)
class LatencyCalibrationState:
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    runtime_input_drift_ms: float
    runtime_output_drift_ms: float
    confidence: float
    calibrated: bool
    baseline_target_lead_sec: float = 0.15
@dataclass(slots=True)
class _RobustBuffer:
    values: list[float] = field(default_factory=list)
    def add(self, value: float, maxlen: int = 40) -> None:
        self.values.append(float(value))
        if len(self.values) > maxlen:
            self.values = self.values[-maxlen:]
    def clear(self) -> None:
        self.values.clear()
    def robust_center(self) -> float | None:
        if not self.values:
            return None
        vals = sorted(float(v) for v in self.values)
        if len(vals) >= 5:
            lo = max(0, int(len(vals) * 0.15))
            hi = min(len(vals), max(lo + 1, int(len(vals) * 0.85)))
            vals = vals[lo:hi]
        if not vals:
            return None
        return float(median(vals))
class LatencyCalibrator:
    def __init__(
        self,
        target_shadow_lead_sec: float = 0.15,
        min_update_interval_sec: float = 1.0,
        min_tracking_quality: float = 0.84,
    ) -> None:
        self.target_shadow_lead_sec = float(target_shadow_lead_sec)
        self.min_update_interval_sec = float(min_update_interval_sec)
        self.min_tracking_quality = float(min_tracking_quality)
        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._last_update_at_sec = 0.0
        self._obs_error_ema_ms = 0.0
        self._obs_consistency_run = 0
        self._max_observation_error_ms = 900.0
        self._min_error_ms_to_adjust = 32.0
        self._max_runtime_output_drift_ms = 90.0
        self._max_runtime_input_drift_ms = 60.0
        self._bluetooth_mode = False
        self._bluetooth_long_session_mode = False
        self._startup_fast_calibration_until_sec = 0.0
        self._stable_lead_buffer = _RobustBuffer()
        self._stable_output_error_buffer = _RobustBuffer()
        self._stable_input_error_buffer = _RobustBuffer()
        self._last_baseline_refresh_at_sec = 0.0
    def reset(
        self,
        device_profile: DeviceProfile,
        bluetooth_mode: bool = False,
        bluetooth_long_session_mode: bool = False,
        now_sec: float = 0.0,
    ) -> None:
        self._bluetooth_mode = bool(bluetooth_mode)
        self._bluetooth_long_session_mode = bool(bluetooth_long_session_mode)
        base_target_lead_sec = 0.15
        if self._bluetooth_mode:
            base_target_lead_sec = 0.35 if self._bluetooth_long_session_mode else 0.28
        self.target_shadow_lead_sec = float(base_target_lead_sec)
        self.min_update_interval_sec = 0.55 if self._bluetooth_mode else 1.0
        self.min_tracking_quality = 0.74 if self._bluetooth_mode else 0.84
        self._min_error_ms_to_adjust = 22.0 if self._bluetooth_mode else 32.0
        self._max_runtime_output_drift_ms = 180.0 if self._bluetooth_mode else 90.0
        self._max_runtime_input_drift_ms = 70.0 if self._bluetooth_mode else 60.0
        self._startup_fast_calibration_until_sec = float(now_sec) + (18.0 if self._bluetooth_mode else 0.0)
        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            runtime_input_drift_ms=0.0,
            runtime_output_drift_ms=0.0,
            confidence=0.20,
            calibrated=False,
            baseline_target_lead_sec=float(base_target_lead_sec),
        )
        self._last_active_at_sec = 0.0
        self._last_update_at_sec = 0.0
        self._obs_error_ema_ms = 0.0
        self._obs_consistency_run = 0
        self._stable_lead_buffer.clear()
        self._stable_output_error_buffer.clear()
        self._stable_input_error_buffer.clear()
        self._last_baseline_refresh_at_sec = float(now_sec)
    def observe_signal(self, signal_quality: SignalQuality) -> None:
        if self._state is None:
            return
        if signal_quality.vad_active or signal_quality.speaking_likelihood >= 0.52:
            self._last_active_at_sec = float(signal_quality.observed_at_sec)
    def snapshot(self) -> LatencyCalibrationState | None:
        return self._state
    def effective_output_latency_ms(self) -> float | None:
        if self._state is None:
            return None
        return float(self._state.estimated_output_latency_ms + self._state.runtime_output_drift_ms)
    def effective_input_latency_ms(self) -> float | None:
        if self._state is None:
            return None
        return float(self._state.estimated_input_latency_ms + self._state.runtime_input_drift_ms)
    def corrected_playback_ref_time_sec(self, playback_ref_time_sec: float) -> float:
        input_ms = self.effective_input_latency_ms() or 0.0
        return float(playback_ref_time_sec) - max(0.0, input_ms / 1000.0)
    def observe_sync(
        self,
        *,
        playback_ref_time_sec: float,
        user_ref_time_sec: float,
        tracking_quality: float,
        stable: bool,
        active_speaking: bool,
        allow_observation: bool = True,
        source_is_text_dominant: bool = True,
        source_mode: str | None = None,
        audio_text_disagreement_sec: float | None = None,
    ) -> None:
        if self._state is None:
            return
        now_sec = max(float(playback_ref_time_sec), float(user_ref_time_sec))
        if not allow_observation:
            self._reset_observation_run(decay_only=True)
            return
        if not stable or tracking_quality < self.min_tracking_quality or not active_speaking:
            self._reset_observation_run(decay_only=True)
            return
        if self._last_active_at_sec <= 0.0 or (now_sec - self._last_active_at_sec) > 1.05:
            self._reset_observation_run(decay_only=True)
            return
        mode = str(source_mode or ("text" if source_is_text_dominant else "joint")).strip().lower()
        if mode not in {"text", "joint", "audio"}:
            mode = "text"
        if mode == "audio":
            source_weight = 0.40 if self._bluetooth_mode else 0.0
        elif mode == "joint":
            source_weight = 0.74
        else:
            source_weight = 1.00
        if source_weight <= 0.0:
            self._reset_observation_run(decay_only=True)
            return
        if audio_text_disagreement_sec is not None:
            max_allowed = 0.70 if self._bluetooth_mode else 0.55
            if abs(float(audio_text_disagreement_sec)) > max_allowed:
                self._reset_observation_run(decay_only=True)
                return
        corrected_playback_ref = self.corrected_playback_ref_time_sec(playback_ref_time_sec)
        lead_sec = float(corrected_playback_ref) - float(user_ref_time_sec)
        error_ms = (lead_sec - self.target_shadow_lead_sec) * 1000.0
        error_ms *= source_weight
        if abs(error_ms) > self._max_observation_error_ms:
            self._reset_observation_run(decay_only=True)
            return
        if stable and tracking_quality >= max(self.min_tracking_quality, 0.82 if not self._bluetooth_mode else 0.76):
            self._stable_lead_buffer.add(float(lead_sec), maxlen=48)
            self._stable_output_error_buffer.add(float(error_ms) * 0.80, maxlen=48)
            self._stable_input_error_buffer.add(float(error_ms) * 0.20, maxlen=48)
        if self._last_update_at_sec > 0.0 and (now_sec - self._last_update_at_sec) < self.min_update_interval_sec:
            self._increase_confidence(0.006, max_conf=0.86)
            self._maybe_refresh_baseline(now_sec=now_sec)
            return
        self._accumulate_observation(error_ms)
        self._increase_confidence(0.012, max_conf=0.80 if self._bluetooth_mode else 0.78)
        required_consistency = 2 if (self._bluetooth_mode and now_sec <= self._startup_fast_calibration_until_sec) else 3
        if self._obs_consistency_run < required_consistency:
            self._maybe_refresh_baseline(now_sec=now_sec)
            return
        if abs(self._obs_error_ema_ms) < self._min_error_ms_to_adjust:
            self._increase_confidence(0.020, max_conf=0.94 if self._bluetooth_mode else 0.92)
            self._last_update_at_sec = now_sec
            self._maybe_refresh_baseline(now_sec=now_sec)
            return
        self._apply_runtime_correction(self._obs_error_ema_ms, now_sec=now_sec)
        self._last_update_at_sec = now_sec
        self._increase_confidence(0.030, max_conf=0.97 if self._bluetooth_mode else 0.96)
        self._maybe_refresh_baseline(now_sec=now_sec)
    def _accumulate_observation(self, error_ms: float) -> None:
        error_ms = float(max(-320.0, min(320.0, error_ms)))
        if self._obs_consistency_run <= 0:
            self._obs_error_ema_ms = error_ms
            self._obs_consistency_run = 1
            return
        tolerance = 90.0 if self._bluetooth_mode else 70.0
        if abs(error_ms - self._obs_error_ema_ms) <= tolerance:
            self._obs_consistency_run += 1
        else:
            self._obs_consistency_run = max(1, self._obs_consistency_run - 1)
        alpha = 0.28 if self._bluetooth_mode else 0.22
        self._obs_error_ema_ms = (1.0 - alpha) * self._obs_error_ema_ms + alpha * error_ms
    def _apply_runtime_correction(self, error_ms: float, now_sec: float) -> None:
        assert self._state is not None
        bounded = float(max(-260.0, min(260.0, error_ms)))
        magnitude = abs(bounded)
        fast_startup = self._bluetooth_mode and now_sec <= self._startup_fast_calibration_until_sec
        if self._bluetooth_mode:
            if fast_startup:
                output_step = max(4.0, min(14.0, magnitude * 0.080))
                input_step = max(0.4, min(2.2, magnitude * 0.010))
            else:
                output_step = max(3.0, min(12.0, magnitude * 0.055))
                input_step = max(0.3, min(1.6, magnitude * 0.006))
        else:
            output_step = max(1.0, min(5.0, magnitude * 0.040))
            input_step = max(0.5, min(2.2, magnitude * 0.016))
        if bounded > 0.0:
            self._state.runtime_output_drift_ms -= output_step
            self._state.runtime_input_drift_ms += input_step
        else:
            self._state.runtime_output_drift_ms += output_step
            self._state.runtime_input_drift_ms -= input_step
        self._state.runtime_output_drift_ms = max(
            -self._max_runtime_output_drift_ms,
            min(self._max_runtime_output_drift_ms, self._state.runtime_output_drift_ms),
        )
        self._state.runtime_input_drift_ms = max(
            -self._max_runtime_input_drift_ms,
            min(self._max_runtime_input_drift_ms, self._state.runtime_input_drift_ms),
        )
        self._obs_consistency_run = max(1, self._obs_consistency_run - 1)
    def _maybe_refresh_baseline(self, *, now_sec: float) -> None:
        assert self._state is not None
        min_refresh_gap = 14.0 if self._bluetooth_mode else 20.0
        if (now_sec - self._last_baseline_refresh_at_sec) < min_refresh_gap:
            return
        robust_lead = self._stable_lead_buffer.robust_center()
        robust_output_err = self._stable_output_error_buffer.robust_center()
        robust_input_err = self._stable_input_error_buffer.robust_center()
        updated = False
        if robust_lead is not None:
            target = 0.35 if self._bluetooth_long_session_mode else (0.28 if self._bluetooth_mode else 0.15)
            lead_bias_ms = (float(robust_lead) - target) * 1000.0
            if abs(lead_bias_ms) >= (26.0 if self._bluetooth_mode else 34.0):
                nudge = max(-8.0, min(8.0, lead_bias_ms * 0.18))
                self._state.estimated_output_latency_ms = max(
                    0.0,
                    self._state.estimated_output_latency_ms - nudge,
                )
                updated = True
        if robust_output_err is not None:
            nudge = max(-10.0, min(10.0, float(robust_output_err) * 0.10))
            if abs(nudge) >= 0.6:
                self._state.estimated_output_latency_ms = max(
                    0.0,
                    self._state.estimated_output_latency_ms - nudge,
                )
                updated = True
        if robust_input_err is not None:
            nudge = max(-4.0, min(4.0, float(robust_input_err) * 0.06))
            if abs(nudge) >= 0.4:
                self._state.estimated_input_latency_ms = max(
                    0.0,
                    self._state.estimated_input_latency_ms - nudge,
                )
                updated = True
        if updated:
            self._increase_confidence(0.012, max_conf=0.98 if self._bluetooth_mode else 0.96)
        self._last_baseline_refresh_at_sec = float(now_sec)
    def _increase_confidence(self, delta: float, *, max_conf: float) -> None:
        assert self._state is not None
        self._state.confidence = min(float(max_conf), self._state.confidence + float(delta))
        self._state.calibrated = self._state.confidence >= 0.60
    def _reset_observation_run(self, *, decay_only: bool) -> None:
        if decay_only:
            self._obs_consistency_run = max(0, self._obs_consistency_run - 1)
            self._obs_error_ema_ms *= 0.84 if self._bluetooth_mode else 0.80
        else:
            self._obs_consistency_run = 0
            self._obs_error_ema_ms = 0.0
```

---
### 文件: `shadowing_app/src/shadowing/audio/live_audio_matcher.py`

```python
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass
import numpy as np
from shadowing.audio.audio_feature_ring_buffer import AudioFeatureRingBuffer
from shadowing.audio.frame_feature_extractor import AudioFrameFeature
from shadowing.audio.reference_audio_features import ReferenceAudioFeatures
from shadowing.types import AudioMatchSnapshot
@dataclass(slots=True)
class _Candidate:
    idx: int
    env_score: float
    onset_score: float
    band_score: float
    embed_score: float
    stretch_factor: float
    total_score: float
    rank: int = 0
class LiveAudioMatcher:
    def __init__(
        self,
        *,
        search_window_sec: float = 3.0,
        match_window_sec: float = 1.8,
        update_interval_sec: float = 0.12,
        min_frames_for_match: int = 20,
        ring_buffer_sec: float = 6.0,
    ) -> None:
        self.search_window_sec = float(search_window_sec)
        self.match_window_sec = float(match_window_sec)
        self.update_interval_sec = float(update_interval_sec)
        self.min_frames_for_match = max(8, int(min_frames_for_match))
        self.ring = AudioFeatureRingBuffer(max_duration_sec=ring_buffer_sec)
        self._stretch_factors = (0.94, 1.00, 1.06)
        self._dtw_top_k = 4
        self._dtw_band_ratio = 0.20
        self._recovery_window_sec = max(6.0, self.search_window_sec * 2.2)
        self._global_anchor_step_sec = 0.9
        self._ref_features: ReferenceAudioFeatures | None = None
        self._ref_times = np.zeros((0,), dtype=np.float32)
        self._ref_env = np.zeros((0,), dtype=np.float32)
        self._ref_onset = np.zeros((0,), dtype=np.float32)
        self._ref_band = np.zeros((0, 0), dtype=np.float32)
        self._ref_embed = np.zeros((0, 0), dtype=np.float32)
        self._boundary_times = np.zeros((0,), dtype=np.float32)
        self._global_anchor_indices = np.zeros((0,), dtype=np.int32)
        self._last_snapshot: AudioMatchSnapshot | None = None
        self._last_emit_at_sec = 0.0
        self._low_confidence_run = 0
    def reset(self, ref_features: ReferenceAudioFeatures, ref_map) -> None:
        _ = ref_map
        self._ref_features = ref_features
        self.ring.reset()
        self._last_snapshot = None
        self._last_emit_at_sec = 0.0
        self._low_confidence_run = 0
        self._ref_times = np.asarray([x.time_sec for x in ref_features.frames], dtype=np.float32)
        self._ref_env = np.asarray([x.envelope for x in ref_features.frames], dtype=np.float32)
        self._ref_onset = np.asarray([x.onset_strength for x in ref_features.frames], dtype=np.float32)
        if ref_features.frames and ref_features.frames[0].band_energy:
            self._ref_band = np.asarray([x.band_energy for x in ref_features.frames], dtype=np.float32)
        else:
            self._ref_band = np.zeros((len(ref_features.frames), 0), dtype=np.float32)
        if ref_features.frames and ref_features.frames[0].embedding:
            self._ref_embed = np.asarray([x.embedding for x in ref_features.frames], dtype=np.float32)
        else:
            self._ref_embed = np.zeros((len(ref_features.frames), 0), dtype=np.float32)
        self._boundary_times = np.asarray([float(x.time_sec) for x in ref_features.boundaries], dtype=np.float32)
        self._global_anchor_indices = self._build_global_anchor_indices()
    def feed_features(self, frames: list[AudioFrameFeature]) -> None:
        self.ring.append_many(frames)
    def snapshot(
        self,
        *,
        now_sec: float,
        progress_hint_ref_time_sec: float | None,
        playback_ref_time_sec: float | None,
        text_tracking_confidence: float,
    ) -> AudioMatchSnapshot | None:
        if self._ref_features is None or self._ref_env.size == 0:
            return None
        if self._last_snapshot is not None and (now_sec - self._last_emit_at_sec) < self.update_interval_sec:
            return self._last_snapshot
        live = self.ring.get_recent(self.match_window_sec)
        if len(live) < self.min_frames_for_match:
            return self._last_snapshot
        live_env = np.asarray([x.envelope for x in live], dtype=np.float32)
        live_onset = np.asarray([x.onset_strength for x in live], dtype=np.float32)
        live_band = (
            np.asarray([x.band_energy for x in live], dtype=np.float32)
            if live and live[0].band_energy
            else np.zeros((len(live), 0), dtype=np.float32)
        )
        live_embed = (
            np.asarray([x.embedding for x in live], dtype=np.float32)
            if live and live[0].embedding
            else np.zeros((len(live), 0), dtype=np.float32)
        )
        recovery_mode = self._should_enter_recovery(
            progress_hint_ref_time_sec=progress_hint_ref_time_sec,
            playback_ref_time_sec=playback_ref_time_sec,
            text_tracking_confidence=text_tracking_confidence,
        )
        centers = self._choose_search_centers(
            progress_hint_ref_time_sec=progress_hint_ref_time_sec,
            playback_ref_time_sec=playback_ref_time_sec,
            text_tracking_confidence=text_tracking_confidence,
            recovery_mode=recovery_mode,
        )
        candidates = self._search_candidates(
            live_env=live_env,
            live_onset=live_onset,
            live_band=live_band,
            live_embed=live_embed,
            center_time_secs=centers,
            recovery_mode=recovery_mode,
        )
        if not candidates:
            return self._last_snapshot
        best = candidates[0]
        dtw_score, dtw_cost, dtw_coverage, best_candidate_idx = self._refine_with_dtw(
            live_embed=live_embed,
            candidates=candidates,
            live_len=len(live),
        )
        if best_candidate_idx >= 0:
            best = next((c for c in candidates if c.idx == best_candidate_idx), best)
        rhythm_score = self._rhythm_consistency(live_onset, best.idx, len(live_onset))
        boundary_bonus = self._boundary_bonus(best.idx, len(live_onset))
        stretch_bonus = self._stretch_bonus(best.stretch_factor)
        local_similarity = max(
            0.0,
            min(
                1.0,
                0.22 * best.env_score
                + 0.14 * best.onset_score
                + 0.12 * best.band_score
                + 0.24 * best.embed_score
                + 0.14 * rhythm_score
                + 0.12 * dtw_score
                + 0.01 * boundary_bonus
                + 0.01 * stretch_bonus,
            ),
        )
        conf = float(max(0.0, min(1.0, 0.08 + 0.92 * local_similarity)))
        center_ref_idx = min(best.idx + max(0, len(live) // 2 - 1), len(self._ref_times) - 1)
        ref_time = float(self._ref_times[center_ref_idx])
        ref_idx_hint = self._time_to_ref_idx(ref_time)
        repeated_pattern_score = 0.0
        if progress_hint_ref_time_sec is not None:
            delta = float(progress_hint_ref_time_sec) - ref_time
            if 0.30 <= delta <= 2.60 and local_similarity >= 0.56:
                repeated_pattern_score = min(1.0, 0.35 * (delta / 2.60) + 0.65 * max(0.0, 1.0 - dtw_coverage))
        drift_sec = 0.0 if progress_hint_ref_time_sec is None else float(ref_time - progress_hint_ref_time_sec)
        mode = "tracking"
        if text_tracking_confidence < 0.42 and conf >= 0.62:
            mode = "bootstrap"
        if repeated_pattern_score >= 0.55:
            mode = "repeat"
        if (
            playback_ref_time_sec is not None
            and abs(ref_time - float(playback_ref_time_sec)) <= 0.60
            and text_tracking_confidence < 0.52
            and conf >= 0.58
        ):
            mode = "reentry"
        if recovery_mode and conf >= 0.60 and abs(drift_sec) >= 1.2:
            mode = "recovery"
        snap = AudioMatchSnapshot(
            estimated_ref_time_sec=ref_time,
            estimated_ref_idx_hint=int(ref_idx_hint),
            confidence=conf,
            local_similarity=float(local_similarity),
            envelope_alignment_score=float(best.env_score),
            onset_alignment_score=float(best.onset_score),
            band_alignment_score=float(best.band_score),
            rhythm_consistency_score=float(rhythm_score),
            repeated_pattern_score=float(repeated_pattern_score),
            drift_sec=float(drift_sec),
            mode=mode,
            emitted_at_sec=float(now_sec),
            dtw_cost=float(dtw_cost),
            dtw_path_score=float(dtw_score),
            dtw_coverage=float(dtw_coverage),
            coarse_candidate_rank=int(best.rank),
            time_offset_sec=float(drift_sec),
        )
        if conf < 0.56:
            self._low_confidence_run += 1
        else:
            self._low_confidence_run = 0
        self._last_snapshot = snap
        self._last_emit_at_sec = float(now_sec)
        return snap
    def _should_enter_recovery(
        self,
        *,
        progress_hint_ref_time_sec: float | None,
        playback_ref_time_sec: float | None,
        text_tracking_confidence: float,
    ) -> bool:
        if self._last_snapshot is None:
            return False
        if self._low_confidence_run >= 2:
            return True
        if self._last_snapshot.confidence < 0.54:
            return True
        if progress_hint_ref_time_sec is not None:
            if abs(self._last_snapshot.estimated_ref_time_sec - float(progress_hint_ref_time_sec)) >= 1.10:
                return True
        if playback_ref_time_sec is not None and text_tracking_confidence < 0.50:
            if abs(self._last_snapshot.estimated_ref_time_sec - float(playback_ref_time_sec)) >= 1.40:
                return True
        return False
    def _choose_search_centers(
        self,
        *,
        progress_hint_ref_time_sec: float | None,
        playback_ref_time_sec: float | None,
        text_tracking_confidence: float,
        recovery_mode: bool,
    ) -> list[float]:
        centers: list[float] = []
        def add(x: float | None) -> None:
            if x is None:
                return
            val = float(x)
            if any(abs(val - old) < 0.25 for old in centers):
                return
            centers.append(val)
        if progress_hint_ref_time_sec is not None:
            add(progress_hint_ref_time_sec)
        if self._last_snapshot is not None:
            add(self._last_snapshot.estimated_ref_time_sec)
        if playback_ref_time_sec is not None:
            add(playback_ref_time_sec)
        if text_tracking_confidence < 0.48 and playback_ref_time_sec is not None:
            add(float(playback_ref_time_sec) - 1.2)
            add(float(playback_ref_time_sec) + 1.0)
        if recovery_mode and self._ref_times.size > 0 and self._global_anchor_indices.size > 0:
            for idx in self._global_anchor_indices[: min(16, len(self._global_anchor_indices))]:
                add(float(self._ref_times[int(idx)]))
        if not centers:
            add(0.0)
        return centers
    def _search_candidates(
        self,
        *,
        live_env: np.ndarray,
        live_onset: np.ndarray,
        live_band: np.ndarray,
        live_embed: np.ndarray,
        center_time_secs: list[float],
        recovery_mode: bool,
    ) -> list[_Candidate]:
        ref_n = int(self._ref_env.shape[0])
        live_n = int(live_env.shape[0])
        if live_n <= 0 or ref_n < live_n or self._ref_times.size == 0:
            return []
        assert self._ref_features is not None
        radius_sec = self._recovery_window_sec if recovery_mode else self.search_window_sec
        radius_frames = max(live_n, int(round(radius_sec / max(1e-6, self._ref_features.frame_hop_sec))))
        windows: list[tuple[int, int]] = []
        for center_time_sec in center_time_secs:
            center_idx = int(np.searchsorted(self._ref_times, center_time_sec))
            center_start_idx = max(0, center_idx - live_n // 2)
            start = max(0, center_start_idx - radius_frames)
            end = min(ref_n - live_n, center_start_idx + radius_frames)
            if end >= start:
                windows.append((start, end))
        if recovery_mode and ref_n > live_n:
            step = max(8, int(round(self._global_anchor_step_sec / max(1e-6, self._ref_features.frame_hop_sec))))
            for anchor in range(0, ref_n - live_n, step):
                windows.append((anchor, min(ref_n - live_n, anchor + step)))
        windows = self._merge_windows(windows)
        scores: list[_Candidate] = []
        for stretch in self._stretch_factors:
            warped_env = self._time_warp_1d(live_env, target_len=live_n, stretch_factor=stretch)
            warped_onset = self._time_warp_1d(live_onset, target_len=live_n, stretch_factor=stretch)
            warped_band = self._time_warp_2d(live_band, target_len=live_n, stretch_factor=stretch)
            warped_embed = self._time_warp_2d(live_embed, target_len=live_n, stretch_factor=stretch)
            live_env_z = self._zscore(warped_env)
            live_onset_z = self._zscore(warped_onset)
            live_band_z = self._zscore_rows(warped_band)
            live_embed_z = self._zscore_rows(warped_embed)
            for start, end in windows:
                for idx in range(start, end + 1):
                    ref_env = self._ref_env[idx : idx + live_n]
                    ref_onset = self._ref_onset[idx : idx + live_n]
                    ref_band = self._ref_band[idx : idx + live_n] if self._ref_band.size > 0 else np.zeros((live_n, 0), dtype=np.float32)
                    ref_embed = self._ref_embed[idx : idx + live_n] if self._ref_embed.size > 0 else np.zeros((live_n, 0), dtype=np.float32)
                    env_score = self._corr(live_env_z, self._zscore(ref_env))
                    onset_score = self._corr(live_onset_z, self._zscore(ref_onset))
                    band_score = self._band_similarity(live_band_z, self._zscore_rows(ref_band))
                    embed_score = self._band_similarity(live_embed_z, self._zscore_rows(ref_embed))
                    boundary_bonus = self._boundary_bonus(idx, live_n)
                    total = 0.24 * env_score + 0.12 * onset_score + 0.14 * band_score + 0.42 * embed_score + 0.08 * boundary_bonus
                    scores.append(
                        _Candidate(
                            idx=idx,
                            env_score=float(env_score),
                            onset_score=float(onset_score),
                            band_score=float(band_score),
                            embed_score=float(embed_score),
                            stretch_factor=float(stretch),
                            total_score=float(total),
                        )
                    )
        scores.sort(key=lambda x: x.total_score, reverse=True)
        deduped: list[_Candidate] = []
        seen: set[int] = set()
        for cand in scores:
            bucket = int(cand.idx // max(4, live_n // 3))
            if bucket in seen:
                continue
            seen.add(bucket)
            deduped.append(cand)
            if len(deduped) >= max(self._dtw_top_k + 2, 8):
                break
        for i, cand in enumerate(deduped, start=1):
            cand.rank = i
        return deduped
    def _merge_windows(self, windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not windows:
            return []
        windows.sort()
        merged = [windows[0]]
        for s, e in windows[1:]:
            ls, le = merged[-1]
            if s <= le + 2:
                merged[-1] = (ls, max(le, e))
            else:
                merged.append((s, e))
        return merged
    def _build_global_anchor_indices(self) -> np.ndarray:
        if self._ref_times.size == 0:
            return np.zeros((0,), dtype=np.int32)
        total = float(self._ref_times[-1])
        step = max(0.6, self._global_anchor_step_sec)
        anchors: list[int] = []
        t = 0.0
        while t <= total:
            idx = int(np.searchsorted(self._ref_times, t))
            idx = max(0, min(idx, len(self._ref_times) - 1))
            anchors.append(idx)
            t += step
        return np.asarray(sorted(set(anchors)), dtype=np.int32)
    def _refine_with_dtw(
        self,
        *,
        live_embed: np.ndarray,
        candidates: list[_Candidate],
        live_len: int,
    ) -> tuple[float, float, float, int]:
        if live_embed.size == 0 or self._ref_embed.size == 0:
            best = candidates[0]
            return max(0.0, min(1.0, best.embed_score)), 0.0, 0.0, int(best.idx)
        best_score = -1.0
        best_cost = 1e9
        best_coverage = 0.0
        best_candidate_idx = -1
        for cand in candidates[: self._dtw_top_k]:
            lo = max(0, cand.idx - max(2, live_len // 6))
            hi = min(self._ref_embed.shape[0], cand.idx + live_len + max(2, live_len // 6))
            ref_seg = self._ref_embed[lo:hi]
            score, cost, coverage = self._constrained_dtw_similarity(live_embed, ref_seg)
            if score > best_score:
                best_score = score
                best_cost = cost
                best_coverage = coverage
                best_candidate_idx = int(cand.idx)
        return max(0.0, best_score), float(best_cost), float(best_coverage), best_candidate_idx
    def _constrained_dtw_similarity(self, live: np.ndarray, ref: np.ndarray) -> tuple[float, float, float]:
        n = int(live.shape[0])
        m = int(ref.shape[0])
        if n == 0 or m == 0:
            return 0.0, 1e9, 0.0
        band = max(2, int(round(max(n, m) * self._dtw_band_ratio)))
        dp = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
        dp[0, 0] = 0.0
        for i in range(1, n + 1):
            j0 = max(1, i - band)
            j1 = min(m, i + band + max(0, m - n))
            for j in range(j0, j1 + 1):
                cost = 1.0 - self._cosine(live[i - 1], ref[j - 1])
                dp[i, j] = cost + min(dp[i - 1, j], dp[i, j - 1], dp[i - 1, j - 1])
        end_j = int(np.argmin(dp[n, 1:])) + 1
        final_cost = float(dp[n, end_j])
        path_len = float(n + end_j)
        mean_cost = final_cost / max(1.0, path_len)
        score = max(0.0, min(1.0, 1.0 - mean_cost * 1.55))
        coverage = max(0.0, min(1.0, end_j / max(1, m)))
        return score, final_cost, coverage
    def _time_to_ref_idx(self, ref_time_sec: float) -> int:
        assert self._ref_features is not None
        hints = self._ref_features.token_time_hints_sec
        if not hints:
            return 0
        idx = bisect_right(hints, float(ref_time_sec)) - 1
        return max(0, min(idx, len(hints) - 1))
    def _rhythm_consistency(self, live_onset: np.ndarray, ref_start_idx: int, n: int) -> float:
        ref_onset = self._ref_onset[ref_start_idx : ref_start_idx + n]
        if live_onset.size <= 2 or ref_onset.size != live_onset.size:
            return 0.0
        live_peaks = np.where(live_onset >= max(1e-6, np.percentile(live_onset, 75)))[0]
        ref_peaks = np.where(ref_onset >= max(1e-6, np.percentile(ref_onset, 75)))[0]
        if live_peaks.size == 0 or ref_peaks.size == 0:
            return 0.0
        live_gaps = np.diff(live_peaks)
        ref_gaps = np.diff(ref_peaks)
        if live_gaps.size == 0 or ref_gaps.size == 0:
            return 0.55
        a = float(np.mean(live_gaps))
        b = float(np.mean(ref_gaps))
        if max(a, b) <= 1e-6:
            return 0.0
        return float(max(0.0, min(1.0, 1.0 - abs(a - b) / max(a, b))))
    def _boundary_bonus(self, ref_start_idx: int, n: int) -> float:
        if self._boundary_times.size == 0 or self._ref_times.size == 0:
            return 0.0
        center_idx = min(ref_start_idx + max(0, n // 2), len(self._ref_times) - 1)
        center_time = float(self._ref_times[center_idx])
        nearest = np.min(np.abs(self._boundary_times - center_time))
        radius = 0.24
        if nearest > radius:
            return 0.0
        return float(max(0.0, 1.0 - nearest / radius))
    def _stretch_bonus(self, stretch_factor: float) -> float:
        diff = abs(float(stretch_factor) - 1.0)
        return float(max(0.0, 1.0 - diff / 0.10))
    def _time_warp_1d(self, x: np.ndarray, *, target_len: int, stretch_factor: float) -> np.ndarray:
        if x.size == 0 or target_len <= 0:
            return np.zeros((0,), dtype=np.float32)
        src = np.asarray(x, dtype=np.float32).reshape(-1)
        src_len = src.shape[0]
        if src_len == target_len and abs(stretch_factor - 1.0) <= 1e-6:
            return src
        mid = (src_len - 1) * 0.5
        out_pos = np.arange(target_len, dtype=np.float32)
        base_pos = out_pos * (src_len - 1) / max(1, target_len - 1)
        warped_pos = mid + (base_pos - mid) / max(1e-6, stretch_factor)
        warped_pos = np.clip(warped_pos, 0.0, src_len - 1.0)
        lo = np.floor(warped_pos).astype(np.int32)
        hi = np.clip(lo + 1, 0, src_len - 1)
        frac = warped_pos - lo
        return ((1.0 - frac) * src[lo] + frac * src[hi]).astype(np.float32, copy=False)
    def _time_warp_2d(self, x: np.ndarray, *, target_len: int, stretch_factor: float) -> np.ndarray:
        arr = np.asarray(x, dtype=np.float32)
        if arr.size == 0 or target_len <= 0 or arr.ndim != 2:
            return np.zeros((target_len, 0), dtype=np.float32)
        cols = [self._time_warp_1d(arr[:, i], target_len=target_len, stretch_factor=stretch_factor) for i in range(arr.shape[1])]
        return np.stack(cols, axis=1).astype(np.float32, copy=False)
    def _corr(self, a: np.ndarray, b: np.ndarray) -> float:
        if a.size == 0 or b.size == 0 or a.size != b.size:
            return 0.0
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom <= 1e-8:
            return 0.0
        return float(max(0.0, min(1.0, (np.dot(a, b) / denom + 1.0) * 0.5)))
    def _band_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        if a.size == 0 or b.size == 0 or a.shape != b.shape:
            return 0.0
        diff = float(np.mean(np.abs(a - b)))
        return float(1.0 / (1.0 + diff))
    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom <= 1e-8:
            return 0.0
        return float(max(-1.0, min(1.0, np.dot(a, b) / denom)))
    def _zscore(self, x: np.ndarray) -> np.ndarray:
        if x.size == 0:
            return x
        mu = float(np.mean(x))
        sigma = float(np.std(x))
        if sigma <= 1e-6:
            return x - mu
        return (x - mu) / sigma
    def _zscore_rows(self, x: np.ndarray) -> np.ndarray:
        if x.size == 0:
            return x
        mu = np.mean(x, axis=0, keepdims=True)
        sigma = np.std(x, axis=0, keepdims=True)
        sigma = np.where(sigma <= 1e-6, 1.0, sigma)
        return (x - mu) / sigma
```

---
### 文件: `shadowing_app/src/shadowing/audio/playback_config.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass(slots=True)
class PlaybackConfig:
    sample_rate: int
    channels: int = 1
    device: int | str | None = None
    latency: str | float = "high"
    blocksize: int = 0
    bluetooth_output_offset_sec: float = 0.0
```

---
### 文件: `shadowing_app/src/shadowing/audio/reference_audio_analyzer.py`

```python
from __future__ import annotations
import numpy as np
from shadowing.audio.frame_feature_extractor import FrameFeatureExtractor
from shadowing.audio.reference_audio_features import (
    ReferenceAudioFeatures,
    ReferenceAudioFrameFeatures,
    ReferenceBoundaryHint,
    ReferenceTokenAcousticTemplate,
)
from shadowing.preprocess.reference_builder import SegmentTimelineRecord
class ReferenceAudioAnalyzer:
    def __init__(self, frame_size_sec: float = 0.025, hop_sec: float = 0.010, n_bands: int = 6) -> None:
        self.frame_size_sec = float(frame_size_sec)
        self.hop_sec = float(hop_sec)
        self.n_bands = int(n_bands)
    def analyze(
        self,
        *,
        lesson_id: str,
        chunks: list,
        reference_map,
        segment_records: list[SegmentTimelineRecord] | None = None,
    ) -> ReferenceAudioFeatures:
        if not chunks:
            return ReferenceAudioFeatures(
                lesson_id=lesson_id,
                frame_hop_sec=self.hop_sec,
                frame_size_sec=self.frame_size_sec,
                sample_rate=16000,
            )
        sample_rate = int(chunks[0].sample_rate)
        extractor = FrameFeatureExtractor(
            sample_rate=sample_rate,
            frame_size_sec=self.frame_size_sec,
            hop_sec=self.hop_sec,
            n_bands=self.n_bands,
        )
        frames: list[ReferenceAudioFrameFeatures] = []
        for chunk in chunks:
            samples = np.asarray(chunk.samples, dtype=np.float32)
            if samples.ndim == 2:
                samples = np.mean(samples, axis=1).astype(np.float32, copy=False)
            features = extractor.process_float_audio(samples, start_time_sec=float(chunk.start_time_sec))
            for item in features:
                frames.append(
                    ReferenceAudioFrameFeatures(
                        time_sec=float(item.observed_at_sec),
                        envelope=float(item.envelope),
                        onset_strength=float(item.onset_strength),
                        voiced_ratio=float(item.voiced_ratio),
                        band_energy=list(item.band_energy),
                        embedding=list(item.embedding),
                    )
                )
            extractor.reset()
        boundaries = self._build_boundaries(
            frames=frames,
            reference_map=reference_map,
            segment_records=segment_records,
        )
        token_time_hints_sec = self._build_token_time_hints(reference_map=reference_map)
        token_templates = self._build_token_templates(
            frames=frames,
            reference_map=reference_map,
            segment_records=segment_records,
        )
        total_duration_sec = float(getattr(reference_map, "total_duration_sec", 0.0))
        return ReferenceAudioFeatures(
            lesson_id=str(lesson_id),
            frame_hop_sec=self.hop_sec,
            frame_size_sec=self.frame_size_sec,
            sample_rate=sample_rate,
            frames=frames,
            boundaries=boundaries,
            token_time_hints_sec=token_time_hints_sec,
            token_acoustic_templates=token_templates,
            total_duration_sec=total_duration_sec,
        )
    def _build_boundaries(self, *, frames, reference_map, segment_records: list[SegmentTimelineRecord] | None) -> list[ReferenceBoundaryHint]:
        boundaries: list[ReferenceBoundaryHint] = []
        if segment_records:
            for seg in segment_records:
                start_sec = self._segment_effective_start(seg)
                end_sec = self._segment_effective_end(seg)
                boundaries.append(
                    ReferenceBoundaryHint(
                        time_sec=float(start_sec),
                        kind="segment_start",
                        weight=1.25,
                    )
                )
                if end_sec > start_sec:
                    boundaries.append(
                        ReferenceBoundaryHint(
                            time_sec=float(end_sec),
                            kind="segment_end",
                            weight=0.95,
                        )
                    )
        seen_clause_ids: set[int] = set()
        seen_sentence_ids: set[int] = set()
        for token in getattr(reference_map, "tokens", []):
            clause_id = int(getattr(token, "clause_id", -1))
            sentence_id = int(getattr(token, "sentence_id", -1))
            t_start = float(getattr(token, "t_start", 0.0))
            if clause_id >= 0 and clause_id not in seen_clause_ids:
                boundaries.append(ReferenceBoundaryHint(time_sec=t_start, kind="clause", weight=1.0))
                seen_clause_ids.add(clause_id)
            if sentence_id >= 0 and sentence_id not in seen_sentence_ids:
                boundaries.append(ReferenceBoundaryHint(time_sec=t_start, kind="sentence", weight=1.2))
                seen_sentence_ids.add(sentence_id)
        if frames:
            onset_values = np.asarray([x.onset_strength for x in frames], dtype=np.float32)
            if onset_values.size >= 5:
                threshold = float(np.percentile(onset_values, 85))
                for idx in range(1, len(frames) - 1):
                    cur = frames[idx].onset_strength
                    if cur >= threshold and cur >= frames[idx - 1].onset_strength and cur >= frames[idx + 1].onset_strength:
                        boundaries.append(
                            ReferenceBoundaryHint(
                                time_sec=float(frames[idx].time_sec),
                                kind="peak",
                                weight=0.7,
                            )
                        )
        boundaries.sort(key=lambda x: (float(x.time_sec), str(x.kind), -float(x.weight)))
        deduped: list[ReferenceBoundaryHint] = []
        for item in boundaries:
            if deduped and abs(float(item.time_sec) - float(deduped[-1].time_sec)) <= 0.008 and item.kind == deduped[-1].kind:
                if item.weight > deduped[-1].weight:
                    deduped[-1] = item
            else:
                deduped.append(item)
        return deduped
    def _build_token_time_hints(self, *, reference_map) -> list[float]:
        return [float(getattr(t, "t_start", 0.0)) for t in getattr(reference_map, "tokens", [])]
    def _build_token_templates(
        self,
        *,
        frames: list[ReferenceAudioFrameFeatures],
        reference_map,
        segment_records: list[SegmentTimelineRecord] | None,
    ) -> list[ReferenceTokenAcousticTemplate]:
        if not frames:
            return []
        frame_times = np.asarray([f.time_sec for f in frames], dtype=np.float32)
        embeddings = (
            np.asarray([f.embedding for f in frames], dtype=np.float32)
            if frames[0].embedding
            else np.zeros((len(frames), 0), dtype=np.float32)
        )
        if embeddings.size == 0:
            return []
        token_windows = None
        if segment_records:
            token_windows = self._build_token_windows_from_segments(segment_records)
        templates: list[ReferenceTokenAcousticTemplate] = []
        for token in getattr(reference_map, "tokens", []):
            token_idx = int(getattr(token, "idx", len(templates)))
            t0, t1 = self._resolve_token_window(
                token=token,
                token_idx=token_idx,
                token_windows=token_windows,
            )
            mask = np.where((frame_times >= t0) & (frame_times <= t1))[0]
            if mask.size == 0:
                ref_t = float(getattr(token, "t_start", 0.0))
                idx = int(np.argmin(np.abs(frame_times - ref_t)))
                mask = np.asarray([idx], dtype=np.int32)
            emb = np.mean(embeddings[mask], axis=0)
            norm = float(np.linalg.norm(emb))
            if norm > 1e-6:
                emb = emb / norm
            templates.append(
                ReferenceTokenAcousticTemplate(
                    token_idx=token_idx,
                    time_sec=float(getattr(token, "t_start", 0.0)),
                    embedding=emb.astype(np.float32, copy=False).tolist(),
                )
            )
        return templates
    def _build_token_windows_from_segments(
        self,
        segment_records: list[SegmentTimelineRecord],
    ) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for seg in segment_records:
            base_start = self._segment_effective_start(seg)
            local_starts = [float(x) for x in seg.local_starts]
            local_ends = [float(x) for x in seg.local_ends]
            trim_head = float(seg.trim_head_sec or 0.0)
            trim_tail = float(seg.trim_tail_sec or 0.0)
            effective_seg_end = self._segment_effective_end(seg)
            for ls, le in zip(local_starts, local_ends, strict=True):
                t0 = max(base_start, base_start + max(0.0, ls - trim_head))
                t1 = max(t0, base_start + max(0.0, le - trim_head))
                if effective_seg_end > 0.0:
                    t0 = min(t0, effective_seg_end)
                    t1 = min(t1, effective_seg_end)
                if trim_tail > 0.0 and effective_seg_end <= 0.0:
                    t1 = max(t0, t1 - trim_tail)
                out.append((float(t0), float(t1)))
        return out
    def _resolve_token_window(
        self,
        *,
        token,
        token_idx: int,
        token_windows: list[tuple[float, float]] | None,
    ) -> tuple[float, float]:
        if token_windows and 0 <= token_idx < len(token_windows):
            t0, t1 = token_windows[token_idx]
            if t1 >= t0:
                return float(t0 - 0.015), float(t1 + 0.020)
        t0 = float(getattr(token, "t_start", 0.0)) - 0.03
        t1 = float(getattr(token, "t_end", t0 + 0.06)) + 0.03
        return t0, t1
    def _segment_effective_start(self, seg: SegmentTimelineRecord) -> float:
        if seg.assembled_start_sec is not None:
            return float(seg.assembled_start_sec)
        return float(seg.global_start_sec)
    def _segment_effective_end(self, seg: SegmentTimelineRecord) -> float:
        if seg.assembled_end_sec is not None:
            return float(seg.assembled_end_sec)
        if seg.local_ends:
            return float(seg.global_start_sec + max(float(x) for x in seg.local_ends))
        return float(seg.global_start_sec)
```

---
### 文件: `shadowing_app/src/shadowing/audio/reference_audio_features.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
@dataclass(slots=True)
class ReferenceAudioFrameFeatures:
    time_sec: float
    envelope: float
    onset_strength: float
    voiced_ratio: float
    band_energy: list[float]
    embedding: list[float] = field(default_factory=list)
@dataclass(slots=True)
class ReferenceBoundaryHint:
    time_sec: float
    kind: str
    weight: float = 1.0
@dataclass(slots=True)
class ReferenceTokenAcousticTemplate:
    token_idx: int
    time_sec: float
    embedding: list[float] = field(default_factory=list)
@dataclass(slots=True)
class ReferenceAudioFeatures:
    lesson_id: str
    frame_hop_sec: float
    frame_size_sec: float
    sample_rate: int
    frames: list[ReferenceAudioFrameFeatures] = field(default_factory=list)
    boundaries: list[ReferenceBoundaryHint] = field(default_factory=list)
    token_time_hints_sec: list[float] = field(default_factory=list)
    token_acoustic_templates: list[ReferenceTokenAcousticTemplate] = field(default_factory=list)
    total_duration_sec: float = 0.0
```

---
### 文件: `shadowing_app/src/shadowing/audio/reference_audio_store.py`

```python
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from shadowing.audio.reference_audio_features import (
    ReferenceAudioFeatures,
    ReferenceAudioFrameFeatures,
    ReferenceBoundaryHint,
    ReferenceTokenAcousticTemplate,
)
class ReferenceAudioStore:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
    def _path_for(self, lesson_id: str) -> Path:
        return self.base_dir / lesson_id / "reference_audio_features.json"
    def save(self, lesson_id: str, features: ReferenceAudioFeatures) -> str:
        path = self._path_for(lesson_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(features), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    def exists(self, lesson_id: str) -> bool:
        return self._path_for(lesson_id).exists()
    def load(self, lesson_id: str) -> ReferenceAudioFeatures:
        path = self._path_for(lesson_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        frames = [ReferenceAudioFrameFeatures(**item) for item in data.get("frames", [])]
        boundaries = [ReferenceBoundaryHint(**item) for item in data.get("boundaries", [])]
        token_templates = [ReferenceTokenAcousticTemplate(**item) for item in data.get("token_acoustic_templates", [])]
        return ReferenceAudioFeatures(
            lesson_id=str(data["lesson_id"]),
            frame_hop_sec=float(data.get("frame_hop_sec", 0.010)),
            frame_size_sec=float(data.get("frame_size_sec", 0.025)),
            sample_rate=int(data.get("sample_rate", 16000)),
            frames=frames,
            boundaries=boundaries,
            token_time_hints_sec=[float(x) for x in data.get("token_time_hints_sec", [])],
            token_acoustic_templates=token_templates,
            total_duration_sec=float(data.get("total_duration_sec", 0.0)),
        )
```

---
### 文件: `shadowing_app/src/shadowing/bootstrap.py`

```python
from __future__ import annotations
from pathlib import Path
from typing import Any
from shadowing.adaptation.profile_store import ProfileStore
from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner
from shadowing.audio.audio_behavior_classifier import AudioBehaviorClassifier
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.audio.live_audio_matcher import LiveAudioMatcher
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.fusion.evidence_fuser import EvidenceFuser
from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.playback.sounddevice_player import PlaybackConfig, SoundDevicePlayer
from shadowing.realtime.runtime import RealtimeRuntimeConfig, ShadowingRuntime
from shadowing.telemetry.event_logger import EventLogger
def _normalize_device_context(raw: dict[str, Any] | None, *, capture_backend: str) -> dict[str, Any]:
    ctx = dict(raw or {})
    ctx["capture_backend"] = str(capture_backend or "").strip().lower()
    def _int_or(default: int, value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)
    def _float_or(default: float, value: Any) -> float:
        try:
            out = float(value)
        except Exception:
            return float(default)
        if out != out:
            return float(default)
        return float(out)
    ctx["input_sample_rate"] = _int_or(16000, ctx.get("input_sample_rate", 16000))
    ctx["output_sample_rate"] = _int_or(0, ctx.get("output_sample_rate", 0))
    ctx["noise_floor_rms"] = _float_or(0.0025, ctx.get("noise_floor_rms", 0.0025))
    ctx["hostapi_name"] = str(ctx.get("hostapi_name", "") or "").strip()
    ctx["input_device_name"] = str(ctx.get("input_device_name", "unknown") or "unknown")
    ctx["output_device_name"] = str(ctx.get("output_device_name", "unknown") or "unknown")
    ctx["input_device_id"] = str(ctx.get("input_device_id", "") or "").strip()
    ctx["output_device_id"] = str(ctx.get("output_device_id", "") or "").strip()
    ctx["bluetooth_mode"] = bool(ctx.get("bluetooth_mode", False))
    ctx["bluetooth_long_session_mode"] = bool(ctx.get("bluetooth_long_session_mode", False))
    return ctx
def build_runtime(config: dict[str, Any]) -> ShadowingRuntime:
    lesson_base_dir = str(config.get("lesson_base_dir", "assets/lessons"))
    playback_cfg = dict(config.get("playback", {}))
    capture_cfg = dict(config.get("capture", {}))
    asr_cfg = dict(config.get("asr", {}))
    alignment_cfg = dict(config.get("alignment", {}))
    control_cfg = dict(config.get("control", {}))
    runtime_cfg = dict(config.get("runtime", {}))
    signal_cfg = dict(config.get("signal", {}))
    adaptation_cfg = dict(config.get("adaptation", {}))
    session_cfg = dict(config.get("session", {}))
    device_context = dict(config.get("device_context", {}))
    debug_cfg = dict(config.get("debug", {}))
    audio_match_cfg = dict(config.get("audio_match", {}))
    session_dir = str(session_cfg.get("session_dir", "runtime/latest_session"))
    event_logging = bool(session_cfg.get("event_logging", False))
    debug_enabled = bool(debug_cfg.get("enabled", False))
    repo = FileLessonRepository(lesson_base_dir)
    player = SoundDevicePlayer(
        PlaybackConfig(
            sample_rate=int(playback_cfg.get("sample_rate", 44100)),
            channels=int(playback_cfg.get("channels", 1)),
            device=playback_cfg.get("device"),
            latency=playback_cfg.get("latency", "low"),
            blocksize=int(playback_cfg.get("blocksize", 0)),
            bluetooth_output_offset_sec=float(
                playback_cfg.get("bluetooth_output_offset_sec", 0.0)
            ),
        )
    )
    capture_backend = str(capture_cfg.get("backend", "sounddevice")).strip().lower()
    if capture_backend == "soundcard":
        from shadowing.realtime.capture.soundcard_recorder import SoundCardRecorder
        recorder = SoundCardRecorder(
            sample_rate_in=int(capture_cfg.get("device_sample_rate", 48000)),
            target_sample_rate=int(capture_cfg.get("target_sample_rate", 16000)),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            block_frames=int(capture_cfg.get("blocksize", 1440) or 1440),
        )
    elif capture_backend == "sounddevice":
        from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
        recorder = SoundDeviceRecorder(
            sample_rate_in=int(capture_cfg.get("device_sample_rate", 48000)),
            target_sample_rate=int(capture_cfg.get("target_sample_rate", 16000)),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            dtype=str(capture_cfg.get("dtype", "float32")),
            blocksize=int(capture_cfg.get("blocksize", 0)),
            latency=capture_cfg.get("latency", "low"),
        )
    else:
        raise ValueError(f"Unsupported capture backend: {capture_backend!r}")
    asr_mode = str(asr_cfg.get("mode", "sherpa")).strip().lower()
    if asr_mode == "fake":
        asr = FakeASRProvider(FakeAsrConfig())
    elif asr_mode == "sherpa":
        asr = SherpaStreamingProvider(
            model_config=asr_cfg,
            hotwords=str(asr_cfg.get("hotwords", "")),
            sample_rate=int(asr_cfg.get("sample_rate", 16000)),
            emit_partial_interval_sec=float(asr_cfg.get("emit_partial_interval_sec", 0.08)),
            enable_endpoint=bool(asr_cfg.get("enable_endpoint", True)),
            debug_feed=bool(asr_cfg.get("debug_feed", False)),
            debug_feed_every_n_chunks=int(asr_cfg.get("debug_feed_every_n_chunks", 20)),
        )
    else:
        raise ValueError(f"Unsupported ASR mode: {asr_mode!r}")
    aligner = IncrementalAligner(
        window_back=int(alignment_cfg.get("window_back", 8)),
        window_ahead=int(alignment_cfg.get("window_ahead", 40)),
        stable_hits=int(alignment_cfg.get("stable_hits", alignment_cfg.get("stable_frames", 2))),
        min_confidence=float(alignment_cfg.get("min_confidence", 0.60)),
        debug=bool(alignment_cfg.get("debug", False)),
    )
    policy = ControlPolicy(**control_cfg)
    controller = StateMachineController(
        policy=policy,
        disable_seek=bool(control_cfg.get("disable_seek", False)),
        debug=debug_enabled,
    )
    signal_monitor = SignalQualityMonitor(
        min_vad_rms=float(signal_cfg.get("min_vad_rms", 0.006)),
        vad_noise_multiplier=float(signal_cfg.get("vad_noise_multiplier", 2.8)),
    )
    latency_calibrator = LatencyCalibrator()
    auto_tuner = RuntimeAutoTuner()
    profile_path = str(adaptation_cfg.get("profile_path", "runtime/device_profiles.json"))
    profile_store = ProfileStore(profile_path)
    event_logger = EventLogger(session_dir=session_dir, enabled=event_logging)
    reference_audio_store = ReferenceAudioStore(lesson_base_dir)
    live_audio_matcher = LiveAudioMatcher(
        search_window_sec=float(audio_match_cfg.get("search_window_sec", 3.0)),
        match_window_sec=float(audio_match_cfg.get("match_window_sec", 1.8)),
        update_interval_sec=float(audio_match_cfg.get("update_interval_sec", 0.12)),
        min_frames_for_match=int(audio_match_cfg.get("min_frames_for_match", 20)),
        ring_buffer_sec=float(audio_match_cfg.get("ring_buffer_sec", 6.0)),
    )
    audio_behavior_classifier = AudioBehaviorClassifier()
    evidence_fuser = EvidenceFuser(
        text_priority_threshold=float(audio_match_cfg.get("text_priority_threshold", 0.72)),
        audio_takeover_threshold=float(audio_match_cfg.get("audio_takeover_threshold", 0.62)),
    )
    enriched_device_context = _normalize_device_context(
        device_context,
        capture_backend=capture_backend,
    )
    enriched_device_context["session_dir"] = str(Path(session_dir).expanduser().resolve())
    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
        device_context=enriched_device_context,
        signal_monitor=signal_monitor,
        latency_calibrator=latency_calibrator,
        auto_tuner=auto_tuner,
        profile_store=profile_store,
        event_logger=event_logger,
        reference_audio_store=reference_audio_store,
        live_audio_matcher=live_audio_matcher,
        audio_behavior_classifier=audio_behavior_classifier,
        evidence_fuser=evidence_fuser,
        audio_queue_maxsize=int(runtime_cfg.get("audio_queue_maxsize", 150)),
        loop_interval_sec=float(runtime_cfg.get("loop_interval_sec", 0.03)),
        debug=debug_enabled,
    )
    runtime = ShadowingRuntime(
        orchestrator=orchestrator,
        config=RealtimeRuntimeConfig(
            tick_sleep_sec=float(runtime_cfg.get("loop_interval_sec", 0.03))
        ),
    )
    return runtime
```

---
### 文件: `shadowing_app/src/shadowing/controller/state_machine_controller.py`

```python
from __future__ import annotations
from shadowing.interfaces.controller import Controller
from shadowing.types import (
    AudioBehaviorSnapshot,
    AudioMatchSnapshot,
    ProgressEstimate,
    SignalQuality,
    TrackingSnapshot,
)
class StateMachineController(Controller):
    def __init__(
        self,
        *,
        progress_estimator,
        control_policy,
    ) -> None:
        self._progress_estimator = progress_estimator
        self._control_policy = control_policy
        self._running = False
        self._last_progress: ProgressEstimate | None = None
        self._last_signal_quality: SignalQuality | None = None
        self._last_tracking_snapshot: TrackingSnapshot | None = None
        self._last_audio_match_snapshot: AudioMatchSnapshot | None = None
        self._last_audio_behavior_snapshot: AudioBehaviorSnapshot | None = None
    def start(self) -> None:
        self._running = True
    def stop(self) -> None:
        self._running = False
    def snapshot(self) -> ProgressEstimate | None:
        return self._last_progress
    def on_asr_event(self, event) -> None:
        _ = event
    def on_signal_quality(self, signal_quality: SignalQuality) -> None:
        self._last_signal_quality = signal_quality
    def on_tracking_snapshot(self, snapshot: TrackingSnapshot) -> None:
        self._last_tracking_snapshot = snapshot
    def on_audio_match_snapshot(self, snapshot: AudioMatchSnapshot) -> None:
        self._last_audio_match_snapshot = snapshot
    def on_audio_behavior_snapshot(self, snapshot: AudioBehaviorSnapshot) -> None:
        self._last_audio_behavior_snapshot = snapshot
    def on_playback_generation_changed(self, now_sec: float) -> None:
        if hasattr(self._progress_estimator, "on_playback_generation_changed"):
            self._progress_estimator.on_playback_generation_changed(now_sec)
    def tick(self, now_sec: float) -> ProgressEstimate | None:
        if not self._running:
            return self._last_progress
        progress = self._progress_estimator.update(
            tracking=self._last_tracking_snapshot,
            audio_match=self._last_audio_match_snapshot,
            audio_behavior=self._last_audio_behavior_snapshot,
            signal_quality=self._last_signal_quality,
            now_sec=float(now_sec),
        )
        self._last_progress = progress
        if progress is not None and hasattr(self._control_policy, "update"):
            self._control_policy.update(progress=progress, now_sec=float(now_sec))
        return progress
```

---
### 文件: `shadowing_app/src/shadowing/fusion/evidence_fuser.py`

```python
from __future__ import annotations
from shadowing.types import FusionEvidence
class EvidenceFuser:
    def __init__(
        self,
        *,
        text_priority_threshold: float = 0.74,
        audio_takeover_threshold: float = 0.66,
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
            text_conf = max(
                0.0,
                min(
                    1.0,
                    0.40 * tracking_quality
                    + 0.22 * progress_conf
                    + 0.18 * joint_conf
                    + 0.10 * stable
                    + 0.10 * (1.0 if recently_progressed else 0.0),
                ),
            )
            text_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
            text_ref_idx = int(getattr(progress, "estimated_ref_idx", 0))
            if position_source == "audio":
                text_conf *= 0.82
            elif position_source == "joint":
                text_conf *= 0.90
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
            still_following = max(still_following, audio_conf * 0.82)
            audio_mode = str(getattr(audio_match, "mode", "tracking"))
        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.98)
            still_following = max(
                still_following,
                float(getattr(audio_behavior, "still_following_likelihood", 0.0)),
            )
            repeated = max(
                repeated,
                float(getattr(audio_behavior, "repeated_likelihood", 0.0)),
            )
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            paused = float(getattr(audio_behavior, "paused_likelihood", 0.0))
        if signal_quality is not None:
            speaking_like = float(
                max(
                    signal_quality.speaking_likelihood,
                    0.45 if signal_quality.vad_active else 0.0,
                )
            )
            if speaking_like >= 0.54:
                still_following = max(still_following, min(1.0, 0.54 + 0.32 * speaking_like))
            if signal_quality.dropout_detected:
                audio_conf *= 0.92
                still_following *= 0.94
            if float(signal_quality.quality_score) < 0.40:
                audio_conf *= 0.95
        if text_ref_time_sec is None and audio_ref_time_sec is not None:
            est_ref_time_sec = float(audio_ref_time_sec)
            est_ref_idx = int(audio_ref_idx)
            fused_conf = max(audio_conf, still_following * 0.92, reentry * 0.90)
            return FusionEvidence(
                estimated_ref_time_sec=float(est_ref_time_sec),
                estimated_ref_idx_hint=int(max(0, est_ref_idx)),
                text_confidence=0.0,
                audio_confidence=float(audio_conf),
                fused_confidence=float(max(0.0, min(1.0, fused_conf))),
                still_following_likelihood=float(still_following),
                repeated_likelihood=float(repeated),
                reentry_likelihood=float(reentry),
                should_prevent_hold=bool(
                    (still_following >= 0.64 or reentry >= 0.56) and paused < 0.80
                ),
                should_prevent_seek=bool(
                    repeated >= 0.54 or reentry >= 0.54 or still_following >= 0.78
                ),
                should_widen_reacquire_window=bool(
                    audio_conf >= 0.54 or reentry >= 0.54
                ),
                should_recenter_aligner_window=bool(
                    audio_conf >= 0.70 and reentry >= 0.52
                ),
                emitted_at_sec=float(now_sec),
            )
        if text_ref_time_sec is None:
            return None
        disagreement = 0.0
        if audio_ref_time_sec is not None:
            disagreement = abs(float(text_ref_time_sec) - float(audio_ref_time_sec))
        if audio_ref_time_sec is None or text_conf >= self.text_priority_threshold:
            est_ref_time_sec = float(text_ref_time_sec)
            est_ref_idx = int(text_ref_idx)
            fused_conf = text_conf
            if audio_ref_time_sec is not None:
                if disagreement <= self.disagreement_soft_sec:
                    fused_conf = min(1.0, fused_conf + 0.05)
                elif disagreement >= self.disagreement_hard_sec:
                    fused_conf = max(0.0, fused_conf - 0.05)
        else:
            audio_can_takeover = bool(
                audio_conf >= self.audio_takeover_threshold
                and (
                    reentry >= 0.58
                    or audio_mode in {"reentry", "recovery"}
                    or (text_conf < 0.50 and still_following >= 0.72)
                )
                and repeated < 0.66
                and paused < 0.78
                and disagreement <= 1.30
            )
            if audio_can_takeover:
                est_ref_time_sec = float(audio_ref_time_sec)
                est_ref_idx = int(audio_ref_idx)
                fused_conf = max(audio_conf * 0.96, still_following * 0.92, text_conf * 0.82)
            else:
                w_text = max(0.22, text_conf)
                w_audio = max(0.16, audio_conf)
                if repeated >= 0.62:
                    w_audio *= 0.18
                elif paused >= 0.72:
                    w_audio *= 0.32
                elif disagreement >= self.disagreement_hard_sec and reentry < 0.60:
                    w_audio *= 0.42
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
                    audio_conf * 0.88,
                    0.60 * text_conf + 0.40 * audio_conf,
                )
                if disagreement <= self.disagreement_soft_sec:
                    fused_conf = min(1.0, fused_conf + 0.05)
                elif disagreement >= self.disagreement_hard_sec:
                    fused_conf = max(0.0, fused_conf - 0.08)
        should_prevent_hold = bool(
            (
                still_following >= 0.64
                or reentry >= 0.58
                or (active_speaking and still_following >= 0.58)
                or (recently_progressed and audio_conf >= 0.54)
                or (text_conf < 0.58 and audio_conf >= 0.60)
            )
            and repeated < 0.78
            and paused < 0.80
        )
        should_prevent_seek = bool(
            repeated >= 0.54
            or reentry >= 0.56
            or still_following >= 0.78
            or (audio_conf >= 0.62 and disagreement <= 1.10 and text_conf < 0.54)
        )
        should_recenter_aligner_window = bool(
            audio_ref_time_sec is not None
            and (
                (audio_conf >= 0.68 and text_conf < 0.56 and reentry >= 0.52)
                or (disagreement >= 0.95 and audio_conf >= 0.64 and reentry >= 0.56)
            )
        )
        should_widen_reacquire_window = bool(
            audio_ref_time_sec is not None
            and (
                audio_conf >= 0.54
                or reentry >= 0.54
                or repeated >= 0.52
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
```

---
### 文件: `shadowing_app/src/shadowing/infrastructure/lesson_repo.py`

```python
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
import numpy as np
import soundfile as sf
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import AudioChunk, LessonManifest, RefToken, ReferenceMap
class FileLessonRepository(LessonRepository):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
    def save_manifest(self, manifest: LessonManifest) -> None:
        lesson_dir = self.base_dir / manifest.lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)
        (lesson_dir / "lesson_manifest.json").write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    def load_manifest(self, lesson_id: str) -> LessonManifest:
        path = self.base_dir / lesson_id / "lesson_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("schema_version", 1)
        data.setdefault("provider_name", "elevenlabs")
        data.setdefault("output_format", "unknown")
        return LessonManifest(**data)
    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str:
        lesson_dir = self.base_dir / lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)
        path = lesson_dir / "reference_map.json"
        path.write_text(json.dumps(asdict(ref_map), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    def load_reference_map(self, lesson_id: str) -> ReferenceMap:
        path = self.base_dir / lesson_id / "reference_map.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        tokens = [RefToken(**token_data) for token_data in data["tokens"]]
        return ReferenceMap(
            lesson_id=data["lesson_id"],
            tokens=tokens,
            total_duration_sec=float(data["total_duration_sec"]),
        )
    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]:
        manifest = self.load_manifest(lesson_id)
        chunks: list[AudioChunk] = []
        current_start_time = 0.0
        expected_sr: int | None = None
        for idx, chunk_path_str in enumerate(manifest.chunk_paths):
            chunk_path = Path(chunk_path_str)
            if not chunk_path.is_absolute():
                chunk_path = (self.base_dir / lesson_id / chunk_path).resolve()
            samples, sr = sf.read(str(chunk_path), dtype="float32", always_2d=False)
            sr = int(sr)
            if expected_sr is None:
                expected_sr = sr
            elif expected_sr != sr:
                raise ValueError(f"Inconsistent chunk sample rate in lesson {lesson_id}: {expected_sr} vs {sr}")
            arr = np.asarray(samples, dtype=np.float32)
            if arr.ndim == 1:
                channels = 1
                duration_sec = arr.shape[0] / sr
            else:
                channels = int(arr.shape[1])
                duration_sec = arr.shape[0] / sr
            chunks.append(
                AudioChunk(
                    chunk_id=idx,
                    sample_rate=sr,
                    channels=channels,
                    samples=arr,
                    duration_sec=float(duration_sec),
                    start_time_sec=float(current_start_time),
                    path=str(chunk_path),
                )
            )
            current_start_time += duration_sec
        return chunks
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/aligner.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from shadowing.types import AsrEvent, AlignResult, ReferenceMap
class Aligner(ABC):
    @abstractmethod
    def reset(self, reference_map: ReferenceMap) -> None: ...
    @abstractmethod
    def update(self, event: AsrEvent) -> AlignResult | None: ...
    @abstractmethod
    def on_playback_generation_changed(self, generation: int) -> None: ...
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/analytics.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
class AnalyticsProvider(ABC):
    @abstractmethod
    def analyze_session(self, lesson_text: str, audio_path: str, output_dir: str) -> dict: ...
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/asr.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from shadowing.types import RawAsrEvent
class ASRProvider(ABC):
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def feed_pcm16(self, pcm_bytes: bytes) -> None: ...
    @abstractmethod
    def poll_raw_events(self) -> list[RawAsrEvent]: ...
    @abstractmethod
    def reset(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/controller.py`

```python
from __future__ import annotations
from typing import Protocol, runtime_checkable
from shadowing.types import (
    AudioBehaviorSnapshot,
    AudioMatchSnapshot,
    ProgressEstimate,
    SignalQuality,
    TrackingSnapshot,
)
@runtime_checkable
class Controller(Protocol):
    def start(self) -> None:
        ...
    def stop(self) -> None:
        ...
    def tick(self, now_sec: float) -> ProgressEstimate | None:
        ...
    def snapshot(self) -> ProgressEstimate | None:
        ...
    def on_asr_event(self, event) -> None:
        ...
    def on_signal_quality(self, signal_quality: SignalQuality) -> None:
        ...
    def on_tracking_snapshot(self, snapshot: TrackingSnapshot) -> None:
        ...
    def on_audio_match_snapshot(self, snapshot: AudioMatchSnapshot) -> None:
        ...
    def on_audio_behavior_snapshot(self, snapshot: AudioBehaviorSnapshot) -> None:
        ...
    def on_playback_generation_changed(self, now_sec: float) -> None:
        ...
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/player.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from shadowing.types import AudioChunk, PlaybackStatus, PlayerCommand
class Player(ABC):
    @abstractmethod
    def load_chunks(self, chunks: list[AudioChunk]) -> None: ...
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def submit_command(self, command: PlayerCommand) -> None: ...
    @abstractmethod
    def get_status(self) -> PlaybackStatus: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/recorder.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Callable
class Recorder(ABC):
    @abstractmethod
    def start(self, on_audio_frame: Callable[[bytes], None]) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/repository.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from shadowing.types import AudioChunk, LessonManifest, ReferenceMap
class LessonRepository(ABC):
    @abstractmethod
    def save_manifest(self, manifest: LessonManifest) -> None: ...
    @abstractmethod
    def load_manifest(self, lesson_id: str) -> LessonManifest: ...
    @abstractmethod
    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str: ...
    @abstractmethod
    def load_reference_map(self, lesson_id: str) -> ReferenceMap: ...
    @abstractmethod
    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]: ...
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/tts.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from shadowing.types import LessonManifest, ReferenceMap
class TTSProvider(ABC):
    @abstractmethod
    def synthesize_lesson(self, lesson_id: str, text: str, output_dir: str) -> tuple[LessonManifest, ReferenceMap]: ...
```

---
### 文件: `shadowing_app/src/shadowing/llm/qwen_hotwords.py`

```python
from __future__ import annotations
import json
import logging
import os
import re
import time
from http import HTTPStatus
from typing import Any
import dashscope
logger = logging.getLogger(__name__)
_DEFAULT_QWEN_MODEL = "qwen-plus"
def _extract_message_text(response: Any) -> str:
    try:
        choice = response.output.choices[0]
        msg = choice.message
    except Exception:
        msg = response.output.choices[0]["message"]
    content = getattr(msg, "content", None)
    if content is None:
        content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict) and "text" in part:
                pieces.append(str(part["text"]))
        return "".join(pieces)
    return str(content)
def _resolve_api_key(api_key: str | None) -> str:
    key = str(api_key or "").strip()
    if key:
        return key
    env_key = str(os.getenv("DASHSCOPE_API_KEY", "")).strip()
    if env_key:
        return env_key
    return ""
def _chat_once(
    *,
    api_key: str | None,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> str:
    resolved_api_key = _resolve_api_key(api_key)
    if not resolved_api_key:
        raise RuntimeError("DashScope API Key 未配置。")
    dashscope.api_key = resolved_api_key
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = dashscope.Generation.call(
        model=str(model or _DEFAULT_QWEN_MODEL).strip(),
        messages=messages,
        result_format="message",
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f"DashScope 调用失败: status={response.status_code}, "
            f"code={getattr(response, 'code', None)}, "
            f"message={getattr(response, 'message', None)}"
        )
    text = _extract_message_text(response)
    return text.strip()
def safe_json_loads(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("输入文本为空")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    text_clean = re.sub(r"```json\s*", "", text, flags=re.IGNORECASE)
    text_clean = re.sub(r"```\s*", "", text_clean)
    try:
        data = json.loads(text_clean, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start = text_clean.find("{")
    end = text_clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text_clean[start : end + 1]
        try:
            data = json.loads(json_str, strict=False)
            if isinstance(data, dict):
                return data
        except Exception:
            try:
                json_str_fixed = json_str.replace("\r", "").replace("\t", "\\t")
                data = json.loads(json_str_fixed, strict=False)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    raise ValueError("无法解析 JSON")
def _normalize_hotword(term: str) -> str:
    term = str(term or "").strip()
    term = term.replace("\u3000", " ")
    term = re.sub(r"\s+", "", term)
    term = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", term)
    return term
def _is_good_hotword(term: str) -> bool:
    if not term:
        return False
    n = len(term)
    if n < 4 or n > 24:
        return False
    if term[0] in "的了在和与及并就也又把被将呢啊吗呀":
        return False
    if term[-1] in "的了在和与及并就也又呢啊吗呀":
        return False
    if re.fullmatch(r"[A-Za-z]+", term):
        return False
    if re.search(r"[A-Za-z]", term):
        if not re.fullmatch(r"[A-Za-z0-9一-龥]+", term):
            return False
    return True
def _dedupe_hotwords(terms: list[str], max_terms: int) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for term in terms:
        t = _normalize_hotword(term)
        if not _is_good_hotword(t):
            continue
        if t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
    cleaned.sort(key=lambda x: (-len(x), x))
    kept: list[str] = []
    for term in cleaned:
        if any(term in existed for existed in kept if existed != term):
            continue
        kept.append(term)
        if len(kept) >= max_terms:
            break
    return kept
def extract_hotwords_with_qwen(
    *,
    lesson_text: str,
    api_key: str | None = None,
    model: str = _DEFAULT_QWEN_MODEL,
    max_terms: int = 24,
    max_retries: int = 3,
    timeout_sleep_sec: float = 2.0,
) -> list[str]:
    lesson_text = str(lesson_text or "").strip()
    if not lesson_text:
        return []
    clipped_text = lesson_text[:6000]
    system_prompt = (
        "你是一个中文语音识别热词提取器。"
        "你的任务是从演讲稿中提取最适合 ASR 热词注入的短语。"
        "必须只输出 JSON，不要输出任何解释。"
    )
    user_prompt = f"""
请从下面这段中文演讲稿中，提取适合“语音识别热词注入”的短语。
目标：
1. 只保留高质量短语
2. 优先保留专有名词、术语、固定表达、业务短语、容易识别错的实体词
3. 不要保留半截句、残片、无意义短语
4. 不要保留单字、双字碎片
5. 每个短语长度控制在 4~24 个字符
6. 宁少勿滥，最多返回 {max_terms} 个
7. 如果某个短语被更长、更完整的短语包含，则优先保留更完整的那个
8. 输出格式必须是 JSON，格式如下：
{{
  "hotwords": [
    "短语1",
    "短语2"
  ]
}}
演讲稿如下：
\"\"\"
{clipped_text}
\"\"\"
""".strip()
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = _chat_once(
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=1200,
            )
            data = safe_json_loads(raw)
            hotwords = data.get("hotwords", [])
            if not isinstance(hotwords, list):
                hotwords = []
            return _dedupe_hotwords([str(x) for x in hotwords], max_terms=max_terms)
        except Exception as e:
            last_error = e
            logger.warning(
                "Qwen 热词提取失败，重试中 (%d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )
            if attempt < max_retries - 1:
                time.sleep(timeout_sleep_sec)
    logger.warning("Qwen 热词提取最终失败，返回空列表: %s", last_error)
    return []
```

---
### 文件: `shadowing_app/src/shadowing/observation/signal_quality.py`

```python
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from shadowing.types import SignalQuality
@dataclass(slots=True)
class _SignalState:
    last_observed_at_sec: float = 0.0
    last_rms: float = 0.0
    last_peak: float = 0.0
    noise_floor_rms: float = 0.0025
    speaking_likelihood: float = 0.0
    last_active_at_sec: float = 0.0
    clipping_ratio: float = 0.0
    dropout_detected: bool = False
    dropout_run_sec: float = 0.0
class SignalQualityMonitor:
    def __init__(
        self,
        min_vad_rms: float = 0.006,
        vad_noise_multiplier: float = 2.8,
        speaking_decay: float = 0.94,
        speaking_rise: float = 0.18,
        clipping_threshold: float = 0.98,
        dropout_min_sec: float = 0.18,
    ) -> None:
        self.min_vad_rms = float(min_vad_rms)
        self.vad_noise_multiplier = float(vad_noise_multiplier)
        self.speaking_decay = float(speaking_decay)
        self.speaking_rise = float(speaking_rise)
        self.clipping_threshold = float(clipping_threshold)
        self.dropout_min_sec = max(0.05, float(dropout_min_sec))
        self.state = _SignalState()
    def feed_pcm16(self, pcm_bytes: bytes, observed_at_sec: float) -> None:
        if not pcm_bytes:
            return
        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return
        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio_f32)))) if audio_f32.size else 0.0
        peak = float(np.max(np.abs(audio_f32))) if audio_f32.size else 0.0
        clipping_ratio = float(np.mean(np.abs(audio_f32) >= self.clipping_threshold)) if audio_f32.size else 0.0
        dt_sec = 0.0
        if self.state.last_observed_at_sec > 0.0 and observed_at_sec >= self.state.last_observed_at_sec:
            dt_sec = float(observed_at_sec - self.state.last_observed_at_sec)
        noise_floor = self.state.noise_floor_rms
        dynamic_threshold = max(self.min_vad_rms, noise_floor * self.vad_noise_multiplier)
        peak_threshold = max(0.012, dynamic_threshold * 1.18)
        vad_active = rms >= dynamic_threshold and peak >= peak_threshold
        weak_voice = rms >= max(self.min_vad_rms * 0.82, dynamic_threshold * 0.90) and peak >= max(0.010, peak_threshold * 0.82)
        if vad_active:
            self.state.last_active_at_sec = observed_at_sec
            self.state.speaking_likelihood = min(
                1.0,
                self.state.speaking_likelihood * self.speaking_decay + self.speaking_rise + 0.12,
            )
        elif weak_voice:
            self.state.last_active_at_sec = observed_at_sec
            self.state.speaking_likelihood = min(
                1.0,
                self.state.speaking_likelihood * self.speaking_decay + self.speaking_rise * 0.55,
            )
        else:
            self.state.speaking_likelihood *= self.speaking_decay
        is_near_zero = rms <= 1e-5 and peak <= 1e-5
        if is_near_zero:
            self.state.dropout_run_sec += max(0.0, dt_sec)
        else:
            self.state.dropout_run_sec = 0.0
        self.state.dropout_detected = self.state.dropout_run_sec >= self.dropout_min_sec
        clearly_non_speech = (not vad_active) and self.state.speaking_likelihood < 0.25
        if clearly_non_speech and rms < max(self.min_vad_rms * 0.75, dynamic_threshold * 0.85):
            self.state.noise_floor_rms = 0.97 * noise_floor + 0.03 * rms
        elif clearly_non_speech:
            self.state.noise_floor_rms = 0.992 * noise_floor + 0.008 * rms
        else:
            self.state.noise_floor_rms = 0.998 * noise_floor + 0.002 * rms
        self.state.last_observed_at_sec = observed_at_sec
        self.state.last_rms = rms
        self.state.last_peak = peak
        self.state.clipping_ratio = clipping_ratio
    def snapshot(self, now_sec: float) -> SignalQuality:
        last_seen = self.state.last_observed_at_sec
        silence_run = 9999.0 if self.state.last_active_at_sec <= 0.0 else max(0.0, now_sec - self.state.last_active_at_sec)
        freshness_penalty = 0.0
        if last_seen > 0.0:
            freshness_penalty = min(0.35, max(0.0, now_sec - last_seen) * 0.30)
        base_quality = 0.50
        base_quality += min(0.20, self.state.last_peak * 0.6)
        base_quality += min(0.18, self.state.speaking_likelihood * 0.24)
        base_quality -= min(0.18, self.state.clipping_ratio * 2.0)
        base_quality -= freshness_penalty
        if self.state.dropout_detected and silence_run > 0.18:
            base_quality -= 0.20
        dynamic_threshold = max(self.min_vad_rms, self.state.noise_floor_rms * self.vad_noise_multiplier)
        vad_active = self.state.last_rms >= dynamic_threshold and self.state.last_peak >= max(0.012, dynamic_threshold * 1.18)
        return SignalQuality(
            observed_at_sec=float(last_seen),
            rms=float(self.state.last_rms),
            peak=float(self.state.last_peak),
            vad_active=bool(vad_active),
            speaking_likelihood=float(max(0.0, min(1.0, self.state.speaking_likelihood))),
            silence_run_sec=float(silence_run),
            clipping_ratio=float(self.state.clipping_ratio),
            dropout_detected=bool(self.state.dropout_detected),
            quality_score=float(max(0.0, min(1.0, base_quality))),
        )
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/assembled_reference_loader.py`

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import soundfile as sf
from shadowing.preprocess.reference_builder import SegmentTimelineRecord
from shadowing.types import AudioChunk
@dataclass(slots=True)
class AssembledReferenceBundle:
    audio_chunk: AudioChunk
    segment_records: list[SegmentTimelineRecord]
    assembled_audio_path: str
    segments_manifest_path: str
class AssembledReferenceLoader:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
    def exists(self, lesson_id: str) -> bool:
        lesson_dir = self.base_dir / lesson_id
        assembled_audio = lesson_dir / "assembled_reference.wav"
        segments_manifest = lesson_dir / "segments_manifest.json"
        return assembled_audio.exists() and segments_manifest.exists()
    def load(self, lesson_id: str) -> AssembledReferenceBundle:
        lesson_dir = self.base_dir / lesson_id
        assembled_audio = lesson_dir / "assembled_reference.wav"
        segments_manifest = lesson_dir / "segments_manifest.json"
        if not assembled_audio.exists():
            raise FileNotFoundError(f"assembled_reference.wav not found: {assembled_audio}")
        if not segments_manifest.exists():
            raise FileNotFoundError(f"segments_manifest.json not found: {segments_manifest}")
        data = json.loads(segments_manifest.read_text(encoding="utf-8"))
        raw_segments = data.get("segments", [])
        segment_records = [self._coerce_segment_record(x, i) for i, x in enumerate(raw_segments)]
        samples, sr = sf.read(str(assembled_audio), dtype="float32", always_2d=False)
        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim == 1:
            channels = 1
            duration_sec = float(arr.shape[0]) / float(sr)
        else:
            channels = int(arr.shape[1])
            duration_sec = float(arr.shape[0]) / float(sr)
        audio_chunk = AudioChunk(
            chunk_id=0,
            sample_rate=int(sr),
            channels=channels,
            samples=arr,
            duration_sec=float(duration_sec),
            start_time_sec=0.0,
            path=str(assembled_audio),
        )
        return AssembledReferenceBundle(
            audio_chunk=audio_chunk,
            segment_records=segment_records,
            assembled_audio_path=str(assembled_audio),
            segments_manifest_path=str(segments_manifest),
        )
    def _coerce_segment_record(self, raw: dict, fallback_idx: int) -> SegmentTimelineRecord:
        chars = raw.get("chars", [])
        pinyins = raw.get("pinyins", [])
        local_starts = raw.get("local_starts", [])
        local_ends = raw.get("local_ends", [])
        return SegmentTimelineRecord(
            segment_id=int(raw.get("segment_id", fallback_idx)),
            text=str(raw.get("text", "")),
            chars=[str(x) for x in chars],
            pinyins=[str(x or "") for x in pinyins],
            local_starts=[float(x) for x in local_starts],
            local_ends=[float(x) for x in local_ends],
            global_start_sec=float(raw.get("global_start_sec", 0.0)),
            sentence_id=int(raw.get("sentence_id", 0)),
            clause_id=int(raw.get("clause_id", fallback_idx)),
            trim_head_sec=float(raw.get("trim_head_sec", 0.0) or 0.0),
            trim_tail_sec=float(raw.get("trim_tail_sec", 0.0) or 0.0),
            assembled_start_sec=(
                None if raw.get("assembled_start_sec") is None else float(raw.get("assembled_start_sec"))
            ),
            assembled_end_sec=(
                None if raw.get("assembled_end_sec") is None else float(raw.get("assembled_end_sec"))
            ),
        )
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/chunker.py`

```python
from __future__ import annotations
import re
class ClauseChunker:
    def __init__(self, max_clause_chars: int = 120) -> None:
        self.max_clause_chars = int(max_clause_chars)
    def split_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        parts = re.split(r"(?<=[。！？!?])", text)
        parts = [p.strip() for p in parts if p.strip()]
        clauses: list[str] = []
        for part in parts:
            if len(part) <= self.max_clause_chars:
                clauses.append(part)
                continue
            subparts = re.split(r"(?<=[，、；,;])", part)
            buf = ""
            for sp in subparts:
                sp = sp.strip()
                if not sp:
                    continue
                if len(buf) + len(sp) <= self.max_clause_chars:
                    buf += sp
                else:
                    if buf:
                        clauses.append(buf)
                    buf = sp
            if buf:
                clauses.append(buf)
        return clauses
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/pipeline.py`

```python
from __future__ import annotations
from pathlib import Path
from shadowing.interfaces.repository import LessonRepository
from shadowing.interfaces.tts import TTSProvider
class LessonPreprocessPipeline:
    def __init__(self, tts_provider: TTSProvider, repo: LessonRepository) -> None:
        self.tts_provider = tts_provider
        self.repo = repo
    def run(self, lesson_id: str, text: str, output_dir: str) -> None:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        manifest, ref_map = self.tts_provider.synthesize_lesson(
            lesson_id=lesson_id,
            text=text,
            output_dir=str(output_path),
        )
        self.repo.save_manifest(manifest)
        self.repo.save_reference_map(lesson_id, ref_map)
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/providers/audio_assembler.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import soundfile as sf
from shadowing.preprocess.reference_builder import SegmentTimelineRecord
@dataclass(slots=True)
class AudioAssemblerConfig:
    silence_rms_threshold: float = 0.0035
    min_silence_keep_sec: float = 0.035
    max_trim_head_sec: float = 0.180
    max_trim_tail_sec: float = 0.220
    crossfade_sec: float = 0.025
    write_trimmed_segment_files: bool = False
    trimmed_segments_dirname: str = "assembled_segments"
@dataclass(slots=True)
class AssembledAudioResult:
    sample_rate: int
    assembled_audio_path: str
    total_duration_sec: float
    segment_records: list[SegmentTimelineRecord]
class AudioAssembler:
    def __init__(self, config: AudioAssemblerConfig | None = None) -> None:
        self.config = config or AudioAssemblerConfig()
    def assemble(
        self,
        *,
        output_dir: str,
        segment_records: list[SegmentTimelineRecord],
        segment_audio_paths: list[str],
        output_filename: str = "assembled_reference.wav",
    ) -> AssembledAudioResult:
        if not segment_records:
            raise ValueError("segment_records is empty")
        if not segment_audio_paths:
            raise ValueError("segment_audio_paths is empty")
        if len(segment_records) != len(segment_audio_paths):
            raise ValueError(
                f"segment_records and segment_audio_paths length mismatch: "
                f"{len(segment_records)} vs {len(segment_audio_paths)}"
            )
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        trimmed_segments_dir = output_path / self.config.trimmed_segments_dirname
        if self.config.write_trimmed_segment_files:
            trimmed_segments_dir.mkdir(parents=True, exist_ok=True)
        loaded_segments: list[tuple[np.ndarray, int]] = []
        sample_rate: int | None = None
        for audio_path in segment_audio_paths:
            audio, sr = self._load_mono_float_audio(audio_path)
            if sample_rate is None:
                sample_rate = int(sr)
            elif int(sr) != int(sample_rate):
                raise ValueError(
                    f"Inconsistent segment sample_rate: {sample_rate} vs {sr}, path={audio_path}"
                )
            loaded_segments.append((audio, int(sr)))
        assert sample_rate is not None
        updated_records: list[SegmentTimelineRecord] = []
        assembled_parts: list[np.ndarray] = []
        assembled_cursor_sec = 0.0
        previous_audio: np.ndarray | None = None
        for idx, ((audio, sr), raw_record, audio_path) in enumerate(
            zip(loaded_segments, segment_records, segment_audio_paths, strict=True)
        ):
            trimmed_audio, trim_head_sec, trim_tail_sec = self._trim_segment_audio(
                audio=audio,
                sample_rate=sr,
            )
            if trimmed_audio.size == 0:
                trimmed_audio = np.zeros((1,), dtype=np.float32)
                trim_head_sec = 0.0
                trim_tail_sec = 0.0
            crossfade_sec = 0.0
            if previous_audio is not None and previous_audio.size > 0 and trimmed_audio.size > 0:
                crossfade_sec = self._effective_crossfade_sec(
                    left_audio=previous_audio,
                    right_audio=trimmed_audio,
                    sample_rate=sr,
                )
            assembled_start_sec = assembled_cursor_sec - crossfade_sec
            assembled_start_sec = max(0.0, assembled_start_sec)
            updated_record = SegmentTimelineRecord(
                segment_id=int(raw_record.segment_id),
                text=str(raw_record.text),
                chars=list(raw_record.chars),
                pinyins=list(raw_record.pinyins),
                local_starts=[float(x) for x in raw_record.local_starts],
                local_ends=[float(x) for x in raw_record.local_ends],
                global_start_sec=float(raw_record.global_start_sec),
                sentence_id=int(raw_record.sentence_id),
                clause_id=int(raw_record.clause_id),
                trim_head_sec=float(trim_head_sec),
                trim_tail_sec=float(trim_tail_sec),
                assembled_start_sec=float(assembled_start_sec),
                assembled_end_sec=None,
            )
            if previous_audio is None or crossfade_sec <= 1e-9:
                assembled_parts.append(trimmed_audio)
                assembled_cursor_sec += float(trimmed_audio.shape[0]) / float(sr)
            else:
                mixed = self._crossfade_two_segments(
                    left_audio=assembled_parts[-1],
                    right_audio=trimmed_audio,
                    sample_rate=sr,
                    crossfade_sec=crossfade_sec,
                )
                assembled_parts[-1] = mixed
                assembled_cursor_sec = self._sum_duration_sec(assembled_parts, sr)
            updated_record.assembled_end_sec = float(assembled_cursor_sec)
            updated_records.append(updated_record)
            if self.config.write_trimmed_segment_files:
                trimmed_path = trimmed_segments_dir / f"{idx:04d}.wav"
                sf.write(
                    str(trimmed_path),
                    trimmed_audio.astype(np.float32, copy=False),
                    sr,
                    subtype="PCM_16",
                )
            previous_audio = trimmed_audio
        final_audio = self._concat_parts(assembled_parts)
        assembled_audio_path = output_path / output_filename
        sf.write(
            str(assembled_audio_path),
            final_audio.astype(np.float32, copy=False),
            sample_rate,
            subtype="PCM_16",
        )
        total_duration_sec = float(final_audio.shape[0]) / float(sample_rate)
        if updated_records:
            updated_records[-1].assembled_end_sec = float(total_duration_sec)
        return AssembledAudioResult(
            sample_rate=int(sample_rate),
            assembled_audio_path=str(assembled_audio_path),
            total_duration_sec=float(total_duration_sec),
            segment_records=updated_records,
        )
    def _load_mono_float_audio(self, audio_path: str) -> tuple[np.ndarray, int]:
        data, sr = sf.read(str(audio_path), dtype="float32", always_2d=False)
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 2:
            arr = np.mean(arr, axis=1).astype(np.float32, copy=False)
        arr = arr.reshape(-1).astype(np.float32, copy=False)
        return arr, int(sr)
    def _trim_segment_audio(
        self,
        *,
        audio: np.ndarray,
        sample_rate: int,
    ) -> tuple[np.ndarray, float, float]:
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return arr, 0.0, 0.0
        head_idx = self._detect_head_trim_index(arr, sample_rate)
        tail_idx = self._detect_tail_trim_index(arr, sample_rate)
        if tail_idx <= head_idx:
            return arr, 0.0, 0.0
        trimmed = arr[head_idx:tail_idx].astype(np.float32, copy=False)
        trim_head_sec = float(head_idx) / float(sample_rate)
        trim_tail_sec = float(arr.shape[0] - tail_idx) / float(sample_rate)
        return trimmed, trim_head_sec, trim_tail_sec
    def _detect_head_trim_index(self, audio: np.ndarray, sample_rate: int) -> int:
        max_trim_samples = int(round(self.config.max_trim_head_sec * sample_rate))
        keep_samples = int(round(self.config.min_silence_keep_sec * sample_rate))
        threshold = float(self.config.silence_rms_threshold)
        if max_trim_samples <= 0:
            return 0
        search_end = min(audio.shape[0], max_trim_samples)
        if search_end <= 0:
            return 0
        first_active = self._find_first_active_sample(audio[:search_end], threshold)
        if first_active is None:
            return 0
        trim_to = max(0, first_active - keep_samples)
        return int(min(trim_to, search_end))
    def _detect_tail_trim_index(self, audio: np.ndarray, sample_rate: int) -> int:
        max_trim_samples = int(round(self.config.max_trim_tail_sec * sample_rate))
        keep_samples = int(round(self.config.min_silence_keep_sec * sample_rate))
        threshold = float(self.config.silence_rms_threshold)
        if max_trim_samples <= 0:
            return int(audio.shape[0])
        search_start = max(0, audio.shape[0] - max_trim_samples)
        tail_region = audio[search_start:]
        if tail_region.size == 0:
            return int(audio.shape[0])
        last_active = self._find_last_active_sample(tail_region, threshold)
        if last_active is None:
            return int(audio.shape[0])
        absolute_last_active = search_start + last_active
        trim_to = min(audio.shape[0], absolute_last_active + keep_samples + 1)
        return int(max(trim_to, 1))
    def _find_first_active_sample(
        self,
        audio: np.ndarray,
        threshold: float,
    ) -> int | None:
        frame = max(32, min(512, audio.shape[0] // 8 if audio.shape[0] >= 8 else 32))
        hop = max(16, frame // 4)
        for start in range(0, max(1, audio.shape[0] - frame + 1), hop):
            win = audio[start : start + frame]
            rms = self._rms(win)
            peak = float(np.max(np.abs(win))) if win.size else 0.0
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                return int(start)
        if audio.shape[0] > 0:
            rms = self._rms(audio)
            peak = float(np.max(np.abs(audio)))
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                return 0
        return None
    def _find_last_active_sample(
        self,
        audio: np.ndarray,
        threshold: float,
    ) -> int | None:
        frame = max(32, min(512, audio.shape[0] // 8 if audio.shape[0] >= 8 else 32))
        hop = max(16, frame // 4)
        last_hit: int | None = None
        for start in range(0, max(1, audio.shape[0] - frame + 1), hop):
            win = audio[start : start + frame]
            rms = self._rms(win)
            peak = float(np.max(np.abs(win))) if win.size else 0.0
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                last_hit = int(start + win.shape[0] - 1)
        if last_hit is None and audio.shape[0] > 0:
            rms = self._rms(audio)
            peak = float(np.max(np.abs(audio)))
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                last_hit = int(audio.shape[0] - 1)
        return last_hit
    def _effective_crossfade_sec(
        self,
        *,
        left_audio: np.ndarray,
        right_audio: np.ndarray,
        sample_rate: int,
    ) -> float:
        desired = max(0.0, float(self.config.crossfade_sec))
        if desired <= 1e-9:
            return 0.0
        max_left = float(left_audio.shape[0]) / float(sample_rate)
        max_right = float(right_audio.shape[0]) / float(sample_rate)
        effective = min(desired, max_left * 0.35, max_right * 0.35)
        return max(0.0, effective)
    def _crossfade_two_segments(
        self,
        *,
        left_audio: np.ndarray,
        right_audio: np.ndarray,
        sample_rate: int,
        crossfade_sec: float,
    ) -> np.ndarray:
        left_arr = np.asarray(left_audio, dtype=np.float32).reshape(-1)
        right_arr = np.asarray(right_audio, dtype=np.float32).reshape(-1)
        fade_samples = int(round(crossfade_sec * sample_rate))
        if fade_samples <= 0:
            return np.concatenate([left_arr, right_arr], axis=0).astype(np.float32, copy=False)
        fade_samples = min(fade_samples, left_arr.shape[0], right_arr.shape[0])
        if fade_samples <= 0:
            return np.concatenate([left_arr, right_arr], axis=0).astype(np.float32, copy=False)
        left_keep = left_arr[:-fade_samples]
        left_fade = left_arr[-fade_samples:]
        right_fade = right_arr[:fade_samples]
        right_keep = right_arr[fade_samples:]
        fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        mixed = left_fade * fade_out + right_fade * fade_in
        return np.concatenate([left_keep, mixed, right_keep], axis=0).astype(np.float32, copy=False)
    def _concat_parts(self, parts: list[np.ndarray]) -> np.ndarray:
        if not parts:
            return np.zeros((0,), dtype=np.float32)
        if len(parts) == 1:
            return np.asarray(parts[0], dtype=np.float32).reshape(-1)
        return np.concatenate(
            [np.asarray(x, dtype=np.float32).reshape(-1) for x in parts],
            axis=0,
        ).astype(np.float32, copy=False)
    def _sum_duration_sec(self, parts: list[np.ndarray], sample_rate: int) -> float:
        total_samples = sum(int(np.asarray(x).shape[0]) for x in parts)
        return float(total_samples) / float(sample_rate)
    def _rms(self, audio: np.ndarray) -> float:
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(arr))))
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/providers/elevenlabs_tts.py`

```python
from __future__ import annotations
import base64
import io
import json
import re
from pathlib import Path
import httpx
import numpy as np
import soundfile as sf
from pypinyin import lazy_pinyin
from shadowing.interfaces.tts import TTSProvider
from shadowing.preprocess.providers.audio_assembler import (
    AudioAssembler,
    AudioAssemblerConfig,
)
from shadowing.preprocess.reference_builder import (
    ReferenceBuilder,
    SegmentTimelineRecord,
)
from shadowing.preprocess.segmenter import ShadowingSegment, ShadowingSegmenter
from shadowing.types import LessonManifest, ReferenceMap
class ElevenLabsTTSProvider(TTSProvider):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
        output_format: str = "pcm_44100",
        timeout_sec: float = 120.0,
        *,
        seed: int | None = 2025,
        continuity_context_chars_prev: int = 100,
        continuity_context_chars_next: int = 100,
        target_chars_per_segment: int = 28,
        hard_max_chars_per_segment: int = 54,
        min_chars_per_segment: int = 6,
        context_window_segments: int = 2,
        max_retries_per_segment: int = 2,
        assemble_reference_audio: bool = True,
        assembled_reference_filename: str = "assembled_reference.wav",
        silence_rms_threshold: float = 0.0035,
        min_silence_keep_sec: float = 0.035,
        max_trim_head_sec: float = 0.180,
        max_trim_tail_sec: float = 0.220,
        crossfade_sec: float = 0.025,
        write_trimmed_segment_files: bool = False,
        trimmed_segments_dirname: str = "assembled_segments",
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.timeout_sec = float(timeout_sec)
        self.seed = seed
        self.max_retries_per_segment = max(1, int(max_retries_per_segment))
        self.continuity_context_chars_prev = max(20, int(continuity_context_chars_prev))
        self.continuity_context_chars_next = max(20, int(continuity_context_chars_next))
        self.assemble_reference_audio = bool(assemble_reference_audio)
        self.assembled_reference_filename = str(assembled_reference_filename)
        self.segmenter = ShadowingSegmenter(
            target_chars_per_segment=target_chars_per_segment,
            hard_max_chars_per_segment=hard_max_chars_per_segment,
            min_chars_per_segment=min_chars_per_segment,
            context_window_segments=context_window_segments,
            context_max_chars=max(
                self.continuity_context_chars_prev,
                self.continuity_context_chars_next,
            ),
        )
        self.reference_builder = ReferenceBuilder()
        self.audio_assembler = AudioAssembler(
            AudioAssemblerConfig(
                silence_rms_threshold=float(silence_rms_threshold),
                min_silence_keep_sec=float(min_silence_keep_sec),
                max_trim_head_sec=float(max_trim_head_sec),
                max_trim_tail_sec=float(max_trim_tail_sec),
                crossfade_sec=float(crossfade_sec),
                write_trimmed_segment_files=bool(write_trimmed_segment_files),
                trimmed_segments_dirname=str(trimmed_segments_dirname),
            )
        )
    def synthesize_lesson(
        self,
        lesson_id: str,
        text: str,
        output_dir: str,
    ) -> tuple[LessonManifest, ReferenceMap]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        chunks_dir = output_path / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        alignments_dir = output_path / "alignments"
        alignments_dir.mkdir(parents=True, exist_ok=True)
        lesson_text = str(text or "").strip()
        if not lesson_text:
            raise ValueError("No valid lesson text provided.")
        segments = self.segmenter.segment_text(lesson_text)
        if not segments:
            raise ValueError("No valid segments found after segmentation.")
        chunk_paths: list[str] = []
        raw_segment_records: list[SegmentTimelineRecord] = []
        segments_manifest_records: list[dict] = []
        global_time_offset = 0.0
        total_audio_duration = 0.0
        sample_rate_out: int | None = None
        with httpx.Client(timeout=self.timeout_sec) as client:
            for seg in segments:
                response = self._request_tts_with_retries(
                    client=client,
                    segment=seg,
                )
                audio_bytes = base64.b64decode(response["audio_base64"])
                chunk_file, chunk_samplerate, chunk_duration = self._write_chunk_audio(
                    chunks_dir=chunks_dir,
                    segment_id=seg.segment_id,
                    audio_bytes=audio_bytes,
                )
                if sample_rate_out is None:
                    sample_rate_out = int(chunk_samplerate)
                elif int(sample_rate_out) != int(chunk_samplerate):
                    raise ValueError(
                        f"Inconsistent chunk sample rate: {sample_rate_out} vs {chunk_samplerate}"
                    )
                chunk_paths.append(str(chunk_file))
                alignment = response.get("alignment") or response.get("normalized_alignment")
                if not alignment:
                    raise ValueError(
                        f"No alignment returned for segment {seg.segment_id}: {seg.text!r}"
                    )
                chars = alignment.get("characters") or []
                local_starts = alignment.get("character_start_times_seconds") or []
                local_ends = alignment.get("character_end_times_seconds") or []
                if not (len(chars) == len(local_starts) == len(local_ends)):
                    raise ValueError(
                        f"Alignment length mismatch in segment {seg.segment_id}: "
                        f"{len(chars)=}, {len(local_starts)=}, {len(local_ends)=}"
                    )
                pinyins = [lazy_pinyin(ch)[0] if str(ch).strip() else "" for ch in chars]
                alignment_path = alignments_dir / f"{seg.segment_id:04d}.alignment.json"
                alignment_payload = {
                    "segment_id": int(seg.segment_id),
                    "text": str(seg.text),
                    "sentence_id": int(seg.sentence_id),
                    "clause_id": int(seg.clause_id),
                    "kind": str(seg.kind),
                    "prev_context_text": str(seg.prev_context_text),
                    "next_context_text": str(seg.next_context_text),
                    "global_start_sec": float(global_time_offset),
                    "duration_sec": float(chunk_duration),
                    "sample_rate": int(chunk_samplerate),
                    "alignment": alignment,
                }
                alignment_path.write_text(
                    json.dumps(alignment_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                alignment_end_sec = max((float(x) for x in local_ends), default=0.0)
                offset_advance_sec = alignment_end_sec if alignment_end_sec > 0.0 else float(chunk_duration)
                raw_record = SegmentTimelineRecord(
                    segment_id=int(seg.segment_id),
                    text=str(seg.text),
                    chars=[str(x) for x in chars],
                    pinyins=[str(x or "") for x in pinyins],
                    local_starts=[float(x) for x in local_starts],
                    local_ends=[float(x) for x in local_ends],
                    global_start_sec=float(global_time_offset),
                    sentence_id=int(seg.sentence_id),
                    clause_id=int(seg.clause_id),
                    trim_head_sec=0.0,
                    trim_tail_sec=0.0,
                    assembled_start_sec=None,
                    assembled_end_sec=None,
                )
                raw_segment_records.append(raw_record)
                segments_manifest_records.append(
                    {
                        "segment_id": int(seg.segment_id),
                        "sentence_id": int(seg.sentence_id),
                        "clause_id": int(seg.clause_id),
                        "kind": str(seg.kind),
                        "text": str(seg.text),
                        "prev_context_text": str(seg.prev_context_text),
                        "next_context_text": str(seg.next_context_text),
                        "audio_path": str(chunk_file),
                        "alignment_path": str(alignment_path),
                        "duration_sec": float(chunk_duration),
                        "sample_rate": int(chunk_samplerate),
                        "char_count": len(self._normalize_text(seg.text)),
                        "alignment_char_count": len(chars),
                        "global_start_sec": float(global_time_offset),
                        "global_end_sec": float(global_time_offset + offset_advance_sec),
                        "request_seed": self.seed,
                        "output_format": self.output_format,
                        "model_id": self.model_id,
                        "chars": [str(x) for x in chars],
                        "pinyins": [str(x or "") for x in pinyins],
                        "local_starts": [float(x) for x in local_starts],
                        "local_ends": [float(x) for x in local_ends],
                        "trim_head_sec": 0.0,
                        "trim_tail_sec": 0.0,
                        "assembled_start_sec": None,
                        "assembled_end_sec": None,
                    }
                )
                global_time_offset += offset_advance_sec
                total_audio_duration = global_time_offset
        final_segment_records = raw_segment_records
        final_total_duration_sec = float(total_audio_duration)
        assembled_audio_path: str | None = None
        if self.assemble_reference_audio and raw_segment_records and chunk_paths:
            assembled = self.audio_assembler.assemble(
                output_dir=str(output_path),
                segment_records=raw_segment_records,
                segment_audio_paths=chunk_paths,
                output_filename=self.assembled_reference_filename,
            )
            final_segment_records = assembled.segment_records
            final_total_duration_sec = float(assembled.total_duration_sec)
            assembled_audio_path = assembled.assembled_audio_path
            manifest_by_id = {int(x["segment_id"]): x for x in segments_manifest_records}
            for record in final_segment_records:
                item = manifest_by_id.get(int(record.segment_id))
                if item is None:
                    continue
                item["trim_head_sec"] = float(record.trim_head_sec)
                item["trim_tail_sec"] = float(record.trim_tail_sec)
                item["assembled_start_sec"] = (
                    None if record.assembled_start_sec is None else float(record.assembled_start_sec)
                )
                item["assembled_end_sec"] = (
                    None if record.assembled_end_sec is None else float(record.assembled_end_sec)
                )
        segments_manifest_path = output_path / "segments_manifest.json"
        segments_manifest_path.write_text(
            json.dumps(
                {
                    "lesson_id": lesson_id,
                    "lesson_text": lesson_text,
                    "voice_id": self.voice_id,
                    "model_id": self.model_id,
                    "output_format": self.output_format,
                    "seed": self.seed,
                    "total_duration_sec": float(final_total_duration_sec),
                    "assembled_audio_path": assembled_audio_path,
                    "segments": segments_manifest_records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        ref_map = self.reference_builder.build_from_segment_records(
            lesson_id=lesson_id,
            segment_records=final_segment_records,
            total_duration_sec=float(final_total_duration_sec),
        )
        manifest = LessonManifest(
            lesson_id=lesson_id,
            lesson_text=lesson_text,
            sample_rate_out=sample_rate_out or 44100,
            chunk_paths=chunk_paths,
            reference_map_path=str(output_path / "reference_map.json"),
            provider_name="elevenlabs",
            output_format=self.output_format,
        )
        return manifest, ref_map
    def _request_tts_with_retries(
        self,
        *,
        client: httpx.Client,
        segment: ShadowingSegment,
    ) -> dict:
        last_error: Exception | None = None
        request_plans = [
            {
                "previous_text": self._trim_context(
                    segment.prev_context_text,
                    self.continuity_context_chars_prev,
                    from_left=True,
                ),
                "next_text": self._trim_context(
                    segment.next_context_text,
                    self.continuity_context_chars_next,
                    from_left=False,
                ),
                "seed": self.seed,
            },
            {
                "previous_text": self._trim_context(segment.prev_context_text, 48, from_left=True),
                "next_text": self._trim_context(segment.next_context_text, 48, from_left=False),
                "seed": self.seed,
            },
            {
                "previous_text": "",
                "next_text": "",
                "seed": self.seed,
            },
        ]
        max_attempts = min(len(request_plans), self.max_retries_per_segment + 1)
        for i in range(max_attempts):
            plan = request_plans[i]
            try:
                return self._request_tts_with_timestamps(
                    client=client,
                    text=segment.text,
                    previous_text=plan["previous_text"],
                    next_text=plan["next_text"],
                    seed=plan["seed"],
                )
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(
            f"ElevenLabs TTS failed after retries for segment={segment.segment_id}, "
            f"text={segment.text!r}, error={last_error}"
        )
    def _write_chunk_audio(
        self,
        chunks_dir: Path,
        segment_id: int,
        audio_bytes: bytes,
    ) -> tuple[Path, int, float]:
        fmt = self.output_format.strip().lower()
        if fmt.startswith("pcm_"):
            return self._write_pcm_like_audio(chunks_dir, segment_id, audio_bytes, fmt)
        ext = self._infer_container_extension(fmt)
        chunk_file = chunks_dir / f"{segment_id:04d}.{ext}"
        chunk_file.write_bytes(audio_bytes)
        info = sf.info(str(chunk_file))
        duration_sec = float(info.duration)
        sample_rate = int(info.samplerate)
        return chunk_file, sample_rate, duration_sec
    def _write_pcm_like_audio(
        self,
        chunks_dir: Path,
        segment_id: int,
        audio_bytes: bytes,
        output_format: str,
    ) -> tuple[Path, int, float]:
        sample_rate = self._parse_pcm_sample_rate(output_format)
        chunk_file = chunks_dir / f"{segment_id:04d}.wav"
        wav_data, wav_sr = self._try_decode_as_container(audio_bytes)
        if wav_data is not None:
            wav_sr = int(wav_sr or sample_rate)
            audio_f32 = self._to_mono_float32(wav_data)
            sf.write(str(chunk_file), audio_f32, wav_sr, subtype="PCM_16")
            duration_sec = float(audio_f32.shape[0]) / float(wav_sr)
            return chunk_file, wav_sr, duration_sec
        if len(audio_bytes) % 2 != 0:
            head = audio_bytes[:16].hex()
            raise ValueError(
                "ElevenLabs returned pcm_* audio payload with odd byte length, "
                f"cannot parse as int16 PCM. segment_id={segment_id}, "
                f"bytes={len(audio_bytes)}, head={head}"
            )
        pcm_i16 = np.frombuffer(audio_bytes, dtype="<i2")
        if pcm_i16.size == 0:
            raise ValueError(f"Empty PCM audio returned for segment {segment_id}.")
        audio_f32 = (pcm_i16.astype(np.float32) / 32768.0).astype(np.float32, copy=False)
        sf.write(str(chunk_file), audio_f32, sample_rate, subtype="PCM_16")
        duration_sec = float(audio_f32.shape[0]) / float(sample_rate)
        return chunk_file, sample_rate, duration_sec
    def _try_decode_as_container(self, audio_bytes: bytes) -> tuple[np.ndarray | None, int | None]:
        try:
            bio = io.BytesIO(audio_bytes)
            data, sr = sf.read(bio, dtype="float32", always_2d=False)
            arr = np.asarray(data, dtype=np.float32)
            if arr.size == 0:
                return None, None
            return arr, int(sr)
        except Exception:
            return None, None
    def _to_mono_float32(self, audio: np.ndarray) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim == 1:
            return arr
        return np.mean(arr, axis=1).astype(np.float32, copy=False)
    def _parse_pcm_sample_rate(self, output_format: str) -> int:
        m = re.fullmatch(r"pcm_(\d+)", output_format.strip().lower())
        if not m:
            raise ValueError(f"Unsupported PCM output_format: {output_format}")
        return int(m.group(1))
    def _infer_container_extension(self, output_format: str) -> str:
        fmt = output_format.strip().lower()
        if fmt.startswith("mp3_"):
            return "mp3"
        if fmt.startswith("ulaw_"):
            return "wav"
        if fmt.startswith("pcm_"):
            return "wav"
        return "bin"
    def _request_tts_with_timestamps(
        self,
        client: httpx.Client,
        text: str,
        previous_text: str = "",
        next_text: str = "",
        seed: int | None = None,
    ) -> dict:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {
            "text": text,
            "model_id": self.model_id,
            "output_format": self.output_format,
        }
        if previous_text:
            payload["previous_text"] = previous_text
        if next_text:
            payload["next_text"] = next_text
        if seed is not None:
            payload["seed"] = int(seed)
        response = client.post(url, headers=headers, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"ElevenLabs TTS failed: status={response.status_code}, body={response.text}"
            ) from e
        data = response.json()
        if "audio_base64" not in data:
            raise RuntimeError(f"ElevenLabs response missing audio_base64: {data}")
        return data
    def _trim_context(self, text: str, max_chars: int, *, from_left: bool) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if len(raw) <= max_chars:
            return raw
        if from_left:
            return raw[-max_chars:]
        return raw[:max_chars]
    def _normalize_text(self, text: str) -> str:
        raw = str(text or "").strip()
        raw = raw.replace("\u3000", " ")
        raw = re.sub(r"\s+", "", raw)
        raw = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", raw)
        return raw
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/reference_audio_pipeline.py`

```python
from __future__ import annotations
from shadowing.preprocess.assembled_reference_loader import AssembledReferenceLoader
class ReferenceAudioFeaturePipeline:
    def __init__(self, repo, feature_store, analyzer) -> None:
        self.repo = repo
        self.feature_store = feature_store
        self.analyzer = analyzer
        base_dir = getattr(repo, "base_dir", None)
        self.assembled_loader = (
            AssembledReferenceLoader(str(base_dir)) if base_dir is not None else None
        )
    def run(self, lesson_id: str) -> str:
        ref_map = self.repo.load_reference_map(lesson_id)
        if self.assembled_loader is not None and self.assembled_loader.exists(lesson_id):
            bundle = self.assembled_loader.load(lesson_id)
            features = self.analyzer.analyze(
                lesson_id=lesson_id,
                chunks=[bundle.audio_chunk],
                reference_map=ref_map,
                segment_records=bundle.segment_records,
            )
            return self.feature_store.save(lesson_id, features)
        chunks = self.repo.load_audio_chunks(lesson_id)
        features = self.analyzer.analyze(
            lesson_id=lesson_id,
            chunks=chunks,
            reference_map=ref_map,
            segment_records=None,
        )
        return self.feature_store.save(lesson_id, features)
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/reference_builder.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Sequence
from shadowing.types import RefToken, ReferenceMap
@dataclass(slots=True)
class SegmentAlignedChar:
    char: str
    pinyin: str
    t_start: float
    t_end: float
    sentence_id: int
    clause_id: int
@dataclass(slots=True)
class SegmentTimelineRecord:
    segment_id: int
    text: str
    chars: list[str]
    pinyins: list[str]
    local_starts: list[float]
    local_ends: list[float]
    global_start_sec: float
    sentence_id: int
    clause_id: int
    trim_head_sec: float = 0.0
    trim_tail_sec: float = 0.0
    assembled_start_sec: float | None = None
    assembled_end_sec: float | None = None
class ReferenceBuilder:
    _DROP_CHARS = {
        " ",
        "\t",
        "\n",
        "\r",
        "\u3000",
        "，",
        "。",
        "！",
        "？",
        "；",
        "：",
        "、",
        ",",
        ".",
        "!",
        "?",
        ";",
        ":",
        '"',
        "'",
        "“",
        "”",
        "‘",
        "’",
        "（",
        "）",
        "(",
        ")",
        "[",
        "]",
        "【",
        "】",
        "<",
        ">",
        "《",
        "》",
        "-",
        "—",
        "…",
        "|",
        "/",
        "\\",
    }
    def build(
        self,
        lesson_id: str,
        chars: list[str],
        pinyins: list[str],
        starts: list[float],
        ends: list[float],
        sentence_ids: list[int],
        clause_ids: list[int],
        total_duration_sec: float,
    ) -> ReferenceMap:
        self._validate_parallel_lists(
            chars=chars,
            pinyins=pinyins,
            starts=starts,
            ends=ends,
            sentence_ids=sentence_ids,
            clause_ids=clause_ids,
        )
        aligned_chars = [
            SegmentAlignedChar(
                char=str(ch),
                pinyin=str(py or ""),
                t_start=float(ts),
                t_end=float(te),
                sentence_id=int(sid),
                clause_id=int(cid),
            )
            for ch, py, ts, te, sid, cid in zip(
                chars,
                pinyins,
                starts,
                ends,
                sentence_ids,
                clause_ids,
                strict=True,
            )
        ]
        return self._build_from_aligned_chars(
            lesson_id=lesson_id,
            aligned_chars=aligned_chars,
            total_duration_sec=total_duration_sec,
        )
    def build_from_segment_records(
        self,
        lesson_id: str,
        segment_records: Sequence[SegmentTimelineRecord | dict],
        total_duration_sec: float | None = None,
    ) -> ReferenceMap:
        aligned_chars: list[SegmentAlignedChar] = []
        max_end_sec = 0.0
        for i, raw in enumerate(segment_records):
            record = self._coerce_segment_record(raw, fallback_segment_id=i)
            self._validate_segment_record(record)
            base_start_sec = (
                float(record.assembled_start_sec)
                if record.assembled_start_sec is not None
                else float(record.global_start_sec)
            )
            trim_head_sec = max(0.0, float(record.trim_head_sec))
            trim_tail_sec = max(0.0, float(record.trim_tail_sec))
            segment_effective_end_sec = (
                float(record.assembled_end_sec)
                if record.assembled_end_sec is not None
                else None
            )
            for ch, py, local_start, local_end in zip(
                record.chars,
                record.pinyins,
                record.local_starts,
                record.local_ends,
                strict=True,
            ):
                raw_global_start = base_start_sec + max(0.0, float(local_start) - trim_head_sec)
                raw_global_end = base_start_sec + max(0.0, float(local_end) - trim_head_sec)
                if segment_effective_end_sec is not None:
                    raw_global_start = min(raw_global_start, segment_effective_end_sec)
                    raw_global_end = min(raw_global_end, segment_effective_end_sec)
                if trim_tail_sec > 0.0 and segment_effective_end_sec is None:
                    raw_global_end = max(raw_global_start, raw_global_end - trim_tail_sec)
                t_start = max(0.0, raw_global_start)
                t_end = max(t_start, raw_global_end)
                aligned_chars.append(
                    SegmentAlignedChar(
                        char=str(ch),
                        pinyin=str(py or ""),
                        t_start=float(t_start),
                        t_end=float(t_end),
                        sentence_id=int(record.sentence_id),
                        clause_id=int(record.clause_id),
                    )
                )
                max_end_sec = max(max_end_sec, t_end)
        resolved_total_duration = (
            float(total_duration_sec)
            if total_duration_sec is not None
            else float(max_end_sec)
        )
        return self._build_from_aligned_chars(
            lesson_id=lesson_id,
            aligned_chars=aligned_chars,
            total_duration_sec=resolved_total_duration,
        )
    def _build_from_aligned_chars(
        self,
        *,
        lesson_id: str,
        aligned_chars: Iterable[SegmentAlignedChar],
        total_duration_sec: float,
    ) -> ReferenceMap:
        tokens: list[RefToken] = []
        next_idx = 0
        for item in aligned_chars:
            ch = str(item.char or "")
            if not ch or ch in self._DROP_CHARS or not ch.strip():
                continue
            t_start = max(0.0, float(item.t_start))
            t_end = max(t_start, float(item.t_end))
            tokens.append(
                RefToken(
                    idx=next_idx,
                    char=ch,
                    pinyin=str(item.pinyin or ""),
                    t_start=t_start,
                    t_end=t_end,
                    sentence_id=int(item.sentence_id),
                    clause_id=int(item.clause_id),
                )
            )
            next_idx += 1
        inferred_total = max(
            [float(total_duration_sec)] + [float(t.t_end) for t in tokens] if tokens else [float(total_duration_sec)]
        )
        return ReferenceMap(
            lesson_id=lesson_id,
            tokens=tokens,
            total_duration_sec=float(inferred_total),
        )
    def _validate_parallel_lists(
        self,
        *,
        chars: Sequence[str],
        pinyins: Sequence[str],
        starts: Sequence[float],
        ends: Sequence[float],
        sentence_ids: Sequence[int],
        clause_ids: Sequence[int],
    ) -> None:
        n = len(chars)
        sizes = {
            "chars": len(chars),
            "pinyins": len(pinyins),
            "starts": len(starts),
            "ends": len(ends),
            "sentence_ids": len(sentence_ids),
            "clause_ids": len(clause_ids),
        }
        if any(size != n for size in sizes.values()):
            raise ValueError(f"ReferenceBuilder input length mismatch: {sizes}")
    def _coerce_segment_record(
        self,
        raw: SegmentTimelineRecord | dict,
        *,
        fallback_segment_id: int,
    ) -> SegmentTimelineRecord:
        if isinstance(raw, SegmentTimelineRecord):
            return raw
        if not isinstance(raw, dict):
            raise TypeError(f"Unsupported segment record type: {type(raw)!r}")
        chars = raw.get("chars")
        if chars is None:
            alignment = raw.get("alignment", {})
            chars = alignment.get("characters", [])
        pinyins = raw.get("pinyins")
        if pinyins is None:
            pinyins = [""] * len(chars)
        local_starts = raw.get("local_starts")
        if local_starts is None:
            alignment = raw.get("alignment", {})
            local_starts = alignment.get("character_start_times_seconds", [])
        local_ends = raw.get("local_ends")
        if local_ends is None:
            alignment = raw.get("alignment", {})
            local_ends = alignment.get("character_end_times_seconds", [])
        return SegmentTimelineRecord(
            segment_id=int(raw.get("segment_id", fallback_segment_id)),
            text=str(raw.get("text", "")),
            chars=[str(x) for x in chars],
            pinyins=[str(x or "") for x in pinyins],
            local_starts=[float(x) for x in local_starts],
            local_ends=[float(x) for x in local_ends],
            global_start_sec=float(raw.get("global_start_sec", 0.0)),
            sentence_id=int(raw.get("sentence_id", 0)),
            clause_id=int(raw.get("clause_id", fallback_segment_id)),
            trim_head_sec=float(raw.get("trim_head_sec", 0.0) or 0.0),
            trim_tail_sec=float(raw.get("trim_tail_sec", 0.0) or 0.0),
            assembled_start_sec=(
                None
                if raw.get("assembled_start_sec") is None
                else float(raw.get("assembled_start_sec"))
            ),
            assembled_end_sec=(
                None
                if raw.get("assembled_end_sec") is None
                else float(raw.get("assembled_end_sec"))
            ),
        )
    def _validate_segment_record(self, record: SegmentTimelineRecord) -> None:
        sizes = {
            "chars": len(record.chars),
            "pinyins": len(record.pinyins),
            "local_starts": len(record.local_starts),
            "local_ends": len(record.local_ends),
        }
        n = sizes["chars"]
        if any(size != n for size in sizes.values()):
            raise ValueError(
                f"SegmentTimelineRecord length mismatch: segment_id={record.segment_id}, sizes={sizes}"
            )
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/segmenter.py`

```python
from __future__ import annotations
from dataclasses import dataclass
import re
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？!?；;])")
_CLAUSE_SPLIT_PATTERN = re.compile(r"(?<=[，、：,:])")
@dataclass(slots=True)
class ShadowingSegment:
    segment_id: int
    text: str
    sentence_id: int
    clause_id: int
    kind: str
    prev_context_text: str = ""
    next_context_text: str = ""
class ShadowingSegmenter:
    def __init__(
        self,
        *,
        target_chars_per_segment: int = 28,
        hard_max_chars_per_segment: int = 54,
        min_chars_per_segment: int = 6,
        context_window_segments: int = 2,
        context_max_chars: int = 100,
    ) -> None:
        self.target_chars_per_segment = max(8, int(target_chars_per_segment))
        self.hard_max_chars_per_segment = max(
            self.target_chars_per_segment + 4,
            int(hard_max_chars_per_segment),
        )
        self.min_chars_per_segment = max(2, int(min_chars_per_segment))
        self.context_window_segments = max(1, int(context_window_segments))
        self.context_max_chars = max(20, int(context_max_chars))
    def segment_text(self, text: str) -> list[ShadowingSegment]:
        raw = str(text or "").strip()
        if not raw:
            return []
        sentences = self._split_sentences(raw)
        base_units: list[tuple[str, int, int, str]] = []
        global_clause_id = 0
        for sentence_id, sent in enumerate(sentences):
            clauses = self._split_sentence_to_clauses(sent)
            followable = self._build_followable_segments_from_clauses(clauses)
            for local_idx, seg_text in enumerate(followable):
                kind = "sentence" if len(followable) == 1 else ("clause" if local_idx < len(followable) - 1 else "tail")
                base_units.append(
                    (
                        seg_text,
                        sentence_id,
                        global_clause_id,
                        kind,
                    )
                )
                global_clause_id += 1
        merged_units = self._merge_too_short_units(base_units)
        segments: list[ShadowingSegment] = []
        for idx, (seg_text, sentence_id, clause_id, kind) in enumerate(merged_units):
            segments.append(
                ShadowingSegment(
                    segment_id=idx,
                    text=seg_text,
                    sentence_id=sentence_id,
                    clause_id=clause_id,
                    kind=kind,
                )
            )
        self._attach_contexts(segments)
        return segments
    def _split_sentences(self, text: str) -> list[str]:
        parts = _SENTENCE_SPLIT_PATTERN.split(text)
        out: list[str] = []
        for part in parts:
            item = str(part).strip()
            if item:
                out.append(item)
        return out
    def _split_sentence_to_clauses(self, sentence: str) -> list[str]:
        if len(sentence) <= self.hard_max_chars_per_segment:
            return [sentence]
        parts = _CLAUSE_SPLIT_PATTERN.split(sentence)
        clauses = [p.strip() for p in parts if p and p.strip()]
        if not clauses:
            return [sentence]
        out: list[str] = []
        buf = ""
        for clause in clauses:
            if not buf:
                buf = clause
                continue
            if len(self._normalize_visible_text(buf + clause)) <= self.target_chars_per_segment:
                buf += clause
            else:
                out.append(buf)
                buf = clause
        if buf:
            out.append(buf)
        return out
    def _build_followable_segments_from_clauses(self, clauses: list[str]) -> list[str]:
        if not clauses:
            return []
        provisional: list[str] = []
        buf = ""
        for clause in clauses:
            clean_clause = clause.strip()
            if not clean_clause:
                continue
            if not buf:
                if len(self._normalize_visible_text(clean_clause)) > self.hard_max_chars_per_segment:
                    provisional.extend(self._force_split_long_text(clean_clause))
                else:
                    buf = clean_clause
                continue
            merged = buf + clean_clause
            merged_len = len(self._normalize_visible_text(merged))
            if merged_len <= self.target_chars_per_segment:
                buf = merged
                continue
            provisional.append(buf)
            if len(self._normalize_visible_text(clean_clause)) > self.hard_max_chars_per_segment:
                provisional.extend(self._force_split_long_text(clean_clause))
                buf = ""
            else:
                buf = clean_clause
        if buf:
            provisional.append(buf)
        final_segments: list[str] = []
        for item in provisional:
            if len(self._normalize_visible_text(item)) > self.hard_max_chars_per_segment:
                final_segments.extend(self._force_split_long_text(item))
            else:
                final_segments.append(item)
        return final_segments
    def _force_split_long_text(self, text: str) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        normalized_len = len(self._normalize_visible_text(raw))
        if normalized_len <= self.hard_max_chars_per_segment:
            return [raw]
        pieces: list[str] = []
        buf = ""
        for ch in raw:
            trial = buf + ch
            if len(self._normalize_visible_text(trial)) <= self.target_chars_per_segment:
                buf = trial
                continue
            if buf:
                pieces.append(buf)
            buf = ch
        if buf:
            pieces.append(buf)
        merged: list[str] = []
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if merged and len(self._normalize_visible_text(piece)) < self.min_chars_per_segment:
                merged[-1] += piece
            else:
                merged.append(piece)
        if len(merged) >= 2 and len(self._normalize_visible_text(merged[-1])) < self.min_chars_per_segment:
            merged[-2] += merged[-1]
            merged.pop()
        return merged or [raw]
    def _merge_too_short_units(
        self,
        units: list[tuple[str, int, int, str]],
    ) -> list[tuple[str, int, int, str]]:
        if not units:
            return []
        out: list[tuple[str, int, int, str]] = []
        i = 0
        while i < len(units):
            text, sentence_id, clause_id, kind = units[i]
            cur_len = len(self._normalize_visible_text(text))
            if cur_len >= self.min_chars_per_segment or not out:
                out.append((text, sentence_id, clause_id, kind))
                i += 1
                continue
            prev_text, prev_sid, prev_cid, prev_kind = out[-1]
            merged_prev = prev_text + text
            if len(self._normalize_visible_text(merged_prev)) <= self.hard_max_chars_per_segment:
                out[-1] = (merged_prev, prev_sid, prev_cid, "merged")
                i += 1
                continue
            if i + 1 < len(units):
                next_text, next_sid, next_cid, next_kind = units[i + 1]
                merged_next = text + next_text
                out.append((merged_next, sentence_id, clause_id, "merged"))
                i += 2
                continue
            out[-1] = (prev_text + text, prev_sid, prev_cid, "merged")
            i += 1
        return out
    def _attach_contexts(self, segments: list[ShadowingSegment]) -> None:
        if not segments:
            return
        for i, seg in enumerate(segments):
            prev_parts: list[str] = []
            next_parts: list[str] = []
            for j in range(max(0, i - self.context_window_segments), i):
                prev_parts.append(segments[j].text)
            for j in range(i + 1, min(len(segments), i + 1 + self.context_window_segments)):
                next_parts.append(segments[j].text)
            seg.prev_context_text = self._trim_context("".join(prev_parts), from_left=True)
            seg.next_context_text = self._trim_context("".join(next_parts), from_left=False)
    def _trim_context(self, text: str, *, from_left: bool) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if len(raw) <= self.context_max_chars:
            return raw
        if from_left:
            return raw[-self.context_max_chars :]
        return raw[: self.context_max_chars]
    def _normalize_visible_text(self, text: str) -> str:
        raw = str(text or "")
        raw = raw.replace("\u3000", " ")
        raw = re.sub(r"\s+", "", raw)
        return raw
```

---
### 文件: `shadowing_app/src/shadowing/progress/audio_aware_progress_estimator.py`

```python
from __future__ import annotations
from shadowing.progress.behavior_interpreter import BehaviorInterpreter
from shadowing.types import (
    ProgressEstimate,
    ReferenceMap,
    SignalQuality,
    TrackingMode,
    TrackingSnapshot,
    UserReadState,
)
class AudioAwareProgressEstimator:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        active_speaking_signal_min: float = 0.45,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.active_speaking_signal_min = float(active_speaking_signal_min)
        self._audio_takeover_conf = 0.70
        self._audio_assist_conf = 0.58
        self._max_audio_jump_sec = 1.20
        self._max_disagreement_for_joint_sec = 1.0
        self.behavior_interpreter = BehaviorInterpreter(recent_progress_sec=recent_progress_sec)
        self._ref_map: ReferenceMap | None = None
        self._ref_times: list[float] = []
        self._estimated_ref_time_sec_f = 0.0
        self._estimated_velocity_ref_sec_per_sec = 0.0
        self._last_update_now_sec = 0.0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_tracking: TrackingSnapshot | None = None
        self._last_snapshot: ProgressEstimate | None = None
        self._force_reacquire_until_sec = 0.0
        self._last_audio_progress_at_sec = 0.0
        self._text_stability_run = 0
        self._audio_stability_run = 0
        self._last_text_obs_time_sec: float | None = None
        self._last_audio_obs_time_sec: float | None = None
    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._ref_times = [float(t.t_start) for t in reference_map.tokens]
        start_time = self._ref_times[start_idx] if self._ref_times else 0.0
        self._estimated_ref_time_sec_f = float(start_time)
        self._estimated_velocity_ref_sec_per_sec = 0.0
        self._last_update_now_sec = 0.0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_tracking = None
        self._last_snapshot = None
        self._force_reacquire_until_sec = 0.0
        self._last_audio_progress_at_sec = 0.0
        self._text_stability_run = 0
        self._audio_stability_run = 0
        self._last_text_obs_time_sec = None
        self._last_audio_obs_time_sec = None
    def on_playback_generation_changed(self, now_sec: float) -> None:
        self._force_reacquire_until_sec = float(now_sec) + 0.80
    def update(
        self,
        *,
        tracking: TrackingSnapshot | None,
        audio_match,
        audio_behavior,
        signal_quality: SignalQuality | None,
        now_sec: float,
    ) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if self._last_update_now_sec <= 0.0:
            dt = 0.0
        else:
            dt = max(0.0, min(0.35, float(now_sec) - self._last_update_now_sec))
        self._last_update_now_sec = float(now_sec)
        if tracking is not None:
            self._last_tracking = tracking
            self._last_event_at_sec = float(tracking.emitted_at_sec)
        self._predict_forward(dt=dt, signal_quality=signal_quality)
        text_obs_time_sec = None
        text_obs_weight = 0.0
        text_candidate_idx = self._time_to_ref_idx(self._estimated_ref_time_sec_f)
        text_committed_idx = text_candidate_idx
        tracking_mode = TrackingMode.BOOTSTRAP
        text_quality = 0.0
        text_conf = 0.0
        stable = False
        if tracking is not None:
            text_candidate_idx = int(tracking.candidate_ref_idx)
            text_committed_idx = int(tracking.committed_ref_idx)
            tracking_mode = tracking.tracking_mode
            text_quality = float(tracking.tracking_quality.overall_score)
            text_conf = float(tracking.confidence)
            stable = bool(tracking.stable)
            base_idx = max(text_candidate_idx, text_committed_idx)
            text_obs_time_sec = self._idx_to_ref_time(base_idx)
            text_obs_weight = self._text_observation_weight(tracking)
            if tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
                if self._last_text_obs_time_sec is None or abs(text_obs_time_sec - self._last_text_obs_time_sec) <= 0.45:
                    self._text_stability_run += 1
                else:
                    self._text_stability_run = 1
                self._last_text_obs_time_sec = text_obs_time_sec
            else:
                self._text_stability_run = 0
        audio_obs_time_sec = None
        audio_obs_weight = 0.0
        audio_conf = 0.0
        repeated = 0.0
        reentry = 0.0
        still_following = 0.0
        paused = 0.0
        audio_mode = "tracking"
        if audio_match is not None:
            audio_obs_time_sec = float(getattr(audio_match, "estimated_ref_time_sec", self._estimated_ref_time_sec_f))
            audio_conf = float(getattr(audio_match, "confidence", 0.0))
            repeated = float(getattr(audio_match, "repeated_pattern_score", 0.0))
            audio_mode = str(getattr(audio_match, "mode", "tracking"))
        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.96)
            still_following = float(getattr(audio_behavior, "still_following_likelihood", 0.0))
            repeated = max(repeated, float(getattr(audio_behavior, "repeated_likelihood", 0.0)))
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            paused = float(getattr(audio_behavior, "paused_likelihood", 0.0))
        if audio_obs_time_sec is not None:
            audio_obs_weight = self._audio_observation_weight(
                audio_conf=audio_conf,
                text_quality=text_quality,
                repeated=repeated,
                reentry=reentry,
                still_following=still_following,
                paused=paused,
                audio_mode=audio_mode,
            )
            if self._last_audio_obs_time_sec is None or abs(audio_obs_time_sec - self._last_audio_obs_time_sec) <= 0.55:
                self._audio_stability_run += 1
            else:
                self._audio_stability_run = 1
            self._last_audio_obs_time_sec = audio_obs_time_sec
        position_source = "text"
        est_before = float(self._estimated_ref_time_sec_f)
        if repeated >= 0.68:
            audio_obs_weight *= 0.18
            text_obs_weight *= 0.90
        elif paused >= 0.72 and still_following < 0.58:
            audio_obs_weight *= 0.35
            text_obs_weight *= 0.70
        elif reentry >= 0.64:
            audio_obs_weight = max(audio_obs_weight, 0.72)
        elif still_following >= 0.72 and text_quality < 0.56:
            audio_obs_weight = max(audio_obs_weight, 0.58)
        if text_obs_time_sec is not None and audio_obs_time_sec is not None:
            disagreement = abs(audio_obs_time_sec - text_obs_time_sec)
            if disagreement <= self._max_disagreement_for_joint_sec:
                fused_obs = (
                    text_obs_weight * text_obs_time_sec + audio_obs_weight * audio_obs_time_sec
                ) / max(1e-6, text_obs_weight + audio_obs_weight)
                fused_weight = max(text_obs_weight, audio_obs_weight, 0.18)
                self._pull_toward_observation(fused_obs, fused_weight)
                position_source = "joint"
            elif audio_obs_weight >= 0.76 and text_obs_weight < 0.42 and reentry >= 0.56:
                self._pull_toward_observation(audio_obs_time_sec, audio_obs_weight)
                position_source = "audio"
            else:
                self._pull_toward_observation(text_obs_time_sec, text_obs_weight)
                position_source = "text"
        elif text_obs_time_sec is not None:
            self._pull_toward_observation(text_obs_time_sec, text_obs_weight)
            position_source = "text"
        elif audio_obs_time_sec is not None:
            if audio_obs_weight >= self._audio_assist_conf:
                self._pull_toward_observation(audio_obs_time_sec, audio_obs_weight)
                position_source = "audio" if audio_obs_weight >= self._audio_takeover_conf else "joint"
        self._apply_monotonic_constraints(
            prev_est_ref_time_sec=est_before,
            text_obs_time_sec=text_obs_time_sec,
            audio_obs_time_sec=audio_obs_time_sec,
            repeated=repeated,
            reentry=reentry,
            paused=paused,
            now_sec=now_sec,
        )
        progressed = self._estimated_ref_time_sec_f > est_before + 1e-4
        if progressed:
            self._last_progress_at_sec = float(now_sec)
            if audio_obs_weight >= self._audio_assist_conf:
                self._last_audio_progress_at_sec = float(now_sec)
        self._last_snapshot = self._render_snapshot(
            now_sec=now_sec,
            signal_quality=signal_quality,
            tracking_mode=tracking_mode,
            tracking_quality=text_quality,
            confidence=text_conf,
            stable=stable,
            source_candidate_ref_idx=text_candidate_idx,
            source_committed_ref_idx=text_committed_idx,
            audio_conf=audio_conf,
            still_following=still_following,
            reentry=reentry,
            position_source=position_source,
        )
        return self._last_snapshot
    def snapshot(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        audio_match=None,
        audio_behavior=None,
    ) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        audio_conf = 0.0
        still_following = 0.0
        reentry = 0.0
        position_source = "text"
        if audio_match is not None:
            audio_conf = float(getattr(audio_match, "confidence", 0.0))
            still_following = max(still_following, audio_conf * 0.80)
        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.96)
            still_following = max(still_following, float(getattr(audio_behavior, "still_following_likelihood", 0.0)))
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            if audio_conf >= self._audio_assist_conf:
                position_source = "joint"
        tracking = self._last_tracking
        tracking_mode = TrackingMode.BOOTSTRAP
        tracking_quality = 0.0
        confidence = 0.0
        stable = False
        source_candidate_ref_idx = self._time_to_ref_idx(self._estimated_ref_time_sec_f)
        source_committed_ref_idx = source_candidate_ref_idx
        if tracking is not None:
            tracking_mode = tracking.tracking_mode
            tracking_quality = tracking.tracking_quality.overall_score
            confidence = tracking.confidence
            stable = tracking.stable
            source_candidate_ref_idx = tracking.candidate_ref_idx
            source_committed_ref_idx = tracking.committed_ref_idx
        self._last_snapshot = self._render_snapshot(
            now_sec=now_sec,
            signal_quality=signal_quality,
            tracking_mode=tracking_mode,
            tracking_quality=tracking_quality,
            confidence=confidence,
            stable=stable,
            source_candidate_ref_idx=source_candidate_ref_idx,
            source_committed_ref_idx=source_committed_ref_idx,
            audio_conf=audio_conf,
            still_following=still_following,
            reentry=reentry,
            position_source=position_source,
        )
        return self._last_snapshot
    def _predict_forward(self, *, dt: float, signal_quality: SignalQuality | None) -> None:
        if dt <= 0.0:
            return
        speaking = False
        if signal_quality is not None:
            speaking = bool(
                signal_quality.vad_active
                or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
            )
        vel = float(self._estimated_velocity_ref_sec_per_sec)
        if not speaking:
            vel *= 0.84
        else:
            vel = min(1.55, max(0.0, vel))
        advance = max(0.0, vel) * dt
        self._estimated_ref_time_sec_f += advance
        self._estimated_ref_time_sec_f = self._clamp_ref_time(self._estimated_ref_time_sec_f)
        self._estimated_velocity_ref_sec_per_sec = vel
    def _text_observation_weight(self, tracking: TrackingSnapshot) -> float:
        weight = 0.0
        weight += 0.46 * float(tracking.tracking_quality.overall_score)
        weight += 0.34 * float(tracking.confidence)
        weight += 0.12 * float(tracking.local_match_ratio)
        if tracking.stable:
            weight += 0.10
        if tracking.tracking_mode == TrackingMode.LOCKED:
            weight += 0.10
        elif tracking.tracking_mode == TrackingMode.WEAK_LOCKED:
            weight += 0.02
        elif tracking.tracking_mode in (TrackingMode.REACQUIRING, TrackingMode.LOST):
            weight -= 0.16
        if self._text_stability_run >= 2:
            weight += 0.08
        return max(0.0, min(1.0, weight))
    def _audio_observation_weight(
        self,
        *,
        audio_conf: float,
        text_quality: float,
        repeated: float,
        reentry: float,
        still_following: float,
        paused: float,
        audio_mode: str,
    ) -> float:
        weight = 0.0
        weight += 0.52 * float(audio_conf)
        weight += 0.22 * float(still_following)
        weight += 0.08 * float(reentry)
        if self._audio_stability_run >= 2:
            weight += 0.10
        if text_quality < 0.54:
            weight += 0.10
        if audio_mode in {"reentry", "recovery"}:
            weight += 0.08
        if paused >= 0.70:
            weight -= 0.16
        if repeated >= 0.68:
            weight -= 0.28
        return max(0.0, min(1.0, weight))
    def _pull_toward_observation(self, obs_ref_time_sec: float, obs_weight: float) -> None:
        cur = float(self._estimated_ref_time_sec_f)
        obs = self._clamp_ref_time(float(obs_ref_time_sec))
        err = obs - cur
        if err <= 0.0:
            beta = 0.10 * max(0.0, min(1.0, obs_weight))
        else:
            beta = 0.16 + 0.44 * max(0.0, min(1.0, obs_weight))
        beta = max(0.04, min(0.78, beta))
        new_val = cur + beta * err
        delta = new_val - cur
        self._estimated_velocity_ref_sec_per_sec = 0.78 * self._estimated_velocity_ref_sec_per_sec + 0.22 * max(0.0, delta / 0.03)
        self._estimated_ref_time_sec_f = self._clamp_ref_time(new_val)
    def _apply_monotonic_constraints(
        self,
        *,
        prev_est_ref_time_sec: float,
        text_obs_time_sec: float | None,
        audio_obs_time_sec: float | None,
        repeated: float,
        reentry: float,
        paused: float,
        now_sec: float,
    ) -> None:
        cur = float(self._estimated_ref_time_sec_f)
        cur = max(cur, prev_est_ref_time_sec)
        if repeated >= 0.68:
            cur = min(cur, prev_est_ref_time_sec + 0.06)
        if paused >= 0.72:
            cur = min(cur, prev_est_ref_time_sec + 0.04)
        if reentry >= 0.64 and audio_obs_time_sec is not None:
            target = max(prev_est_ref_time_sec, min(audio_obs_time_sec, prev_est_ref_time_sec + self._max_audio_jump_sec))
            cur = max(cur, target * 0.65 + cur * 0.35)
        if now_sec <= self._force_reacquire_until_sec:
            if text_obs_time_sec is not None:
                cur = max(cur, min(text_obs_time_sec, prev_est_ref_time_sec + 0.35))
        self._estimated_ref_time_sec_f = self._clamp_ref_time(cur)
    def _render_snapshot(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        tracking_mode: TrackingMode,
        tracking_quality: float,
        confidence: float,
        stable: bool,
        source_candidate_ref_idx: int,
        source_committed_ref_idx: int,
        audio_conf: float,
        still_following: float,
        reentry: float,
        position_source: str,
    ) -> ProgressEstimate:
        assert self._ref_map is not None
        estimated_idx = self._time_to_ref_idx(self._estimated_ref_time_sec_f)
        estimated_ref_time_sec = self._idx_to_ref_time(estimated_idx)
        progress_age = 9999.0
        if self._last_progress_at_sec > 0.0:
            progress_age = max(0.0, now_sec - self._last_progress_at_sec)
        if self._last_audio_progress_at_sec > 0.0 and audio_conf >= self._audio_assist_conf:
            progress_age = min(progress_age, max(0.0, now_sec - self._last_audio_progress_at_sec))
        recently_progressed = progress_age <= self.recent_progress_sec
        signal_speaking = False
        if signal_quality is not None:
            signal_speaking = bool(
                signal_quality.vad_active
                or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
            )
        effective_tracking_mode = tracking_mode
        effective_tracking_quality = float(tracking_quality)
        if now_sec <= self._force_reacquire_until_sec:
            effective_tracking_mode = TrackingMode.REACQUIRING
            effective_tracking_quality = min(effective_tracking_quality, 0.55)
        active_speaking = False
        if recently_progressed:
            active_speaking = True
        elif signal_speaking and effective_tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
            active_speaking = True
        elif signal_speaking and effective_tracking_quality >= 0.70:
            active_speaking = True
        elif audio_conf >= self._audio_assist_conf and (still_following >= 0.62 or reentry >= 0.58):
            active_speaking = True
        joint_conf = max(
            confidence,
            0.56 * confidence + 0.44 * audio_conf,
            0.52 * effective_tracking_quality + 0.48 * audio_conf,
        )
        if position_source == "audio":
            joint_conf = max(joint_conf, audio_conf * 0.92)
        elif position_source == "joint":
            joint_conf = max(joint_conf, 0.58 * joint_conf + 0.42 * max(audio_conf, still_following))
        user_state = self.behavior_interpreter.infer(
            progress_age=progress_age,
            signal_quality=signal_quality,
            tracking=self._last_tracking,
            tracking_mode=effective_tracking_mode,
            tracking_quality=max(effective_tracking_quality, audio_conf * 0.82),
            candidate_idx=max(source_candidate_ref_idx, estimated_idx),
            estimated_idx=estimated_idx,
        )
        if audio_conf >= self._audio_takeover_conf and still_following >= 0.64 and user_state in (
            UserReadState.NOT_STARTED,
            UserReadState.PAUSED,
        ):
            user_state = UserReadState.FOLLOWING
        if reentry >= 0.62:
            user_state = UserReadState.REJOINING
        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=float(estimated_ref_time_sec),
            progress_velocity_idx_per_sec=float(self._estimated_velocity_ref_sec_per_sec),
            event_emitted_at_sec=float(self._last_event_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_age_sec=float(progress_age),
            source_candidate_ref_idx=int(source_candidate_ref_idx),
            source_committed_ref_idx=int(source_committed_ref_idx),
            tracking_mode=effective_tracking_mode,
            tracking_quality=float(max(effective_tracking_quality, audio_conf * 0.72 if position_source != "text" else effective_tracking_quality)),
            stable=bool(stable),
            confidence=float(max(confidence, audio_conf * 0.82 if position_source == "audio" else confidence)),
            active_speaking=bool(active_speaking),
            recently_progressed=bool(recently_progressed),
            user_state=user_state,
            audio_confidence=float(audio_conf),
            joint_confidence=float(max(0.0, min(1.0, joint_conf))),
            position_source=str(position_source),
            audio_support_strength=float(max(still_following, reentry, audio_conf)),
        )
    def _time_to_ref_idx(self, ref_time_sec: float) -> int:
        if not self._ref_times:
            return 0
        t = float(ref_time_sec)
        lo = 0
        hi = len(self._ref_times) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._ref_times[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return max(0, min(lo, len(self._ref_times) - 1))
    def _idx_to_ref_time(self, idx: int) -> float:
        if not self._ref_times:
            return 0.0
        i = max(0, min(int(idx), len(self._ref_times) - 1))
        return float(self._ref_times[i])
    def _clamp_ref_time(self, value: float) -> float:
        if not self._ref_times:
            return max(0.0, float(value))
        return max(0.0, min(float(value), float(self._ref_times[-1])))
```

---
### 文件: `shadowing_app/src/shadowing/progress/behavior_interpreter.py`

```python
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
```

---
### 文件: `shadowing_app/src/shadowing/progress/commercial_progress_estimator.py`

```python
from __future__ import annotations
from shadowing.progress.behavior_interpreter import BehaviorInterpreter
from shadowing.types import (
    ProgressEstimate,
    ReferenceMap,
    SignalQuality,
    TrackingMode,
    TrackingSnapshot,
)
class CommercialProgressEstimator:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        active_speaking_signal_min: float = 0.45,
        min_tracking_for_follow: float = 0.58,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.active_speaking_signal_min = float(active_speaking_signal_min)
        self.min_tracking_for_follow = float(min_tracking_for_follow)
        self.behavior_interpreter = BehaviorInterpreter(
            recent_progress_sec=recent_progress_sec,
        )
        self._ref_map: ReferenceMap | None = None
        self._estimated_idx_f = 0.0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_velocity = 0.0
        self._last_estimated_idx_at_progress = 0.0
        self._last_tracking: TrackingSnapshot | None = None
        self._last_snapshot: ProgressEstimate | None = None
        self._force_reacquire_until_sec = 0.0
    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._estimated_idx_f = float(start_idx)
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_velocity = 0.0
        self._last_estimated_idx_at_progress = float(start_idx)
        self._last_tracking = None
        self._last_snapshot = None
        self._force_reacquire_until_sec = 0.0
    def on_playback_generation_changed(self, now_sec: float) -> None:
        self._force_reacquire_until_sec = float(now_sec) + 0.80
    def update(
        self,
        tracking: TrackingSnapshot | None,
        signal_quality: SignalQuality | None,
        now_sec: float,
    ) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if tracking is None:
            return self.snapshot(now_sec, signal_quality)
        self._last_tracking = tracking
        self._last_event_at_sec = float(tracking.emitted_at_sec)
        current_idx = int(round(self._estimated_idx_f))
        candidate_idx = int(tracking.candidate_ref_idx)
        committed_idx = int(tracking.committed_ref_idx)
        target_idx = float(max(current_idx, committed_idx, candidate_idx))
        weight = self._weight_for_tracking(tracking)
        updated_idx = max(
            self._estimated_idx_f,
            (1.0 - weight) * self._estimated_idx_f + weight * target_idx,
        )
        if (
            tracking.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED)
            and tracking.local_match_ratio >= 0.68
            and candidate_idx > current_idx
        ):
            updated_idx = max(updated_idx, float(current_idx) + 0.60)
        estimated_idx = max(0, min(int(round(updated_idx)), len(self._ref_map.tokens) - 1))
        self._estimated_idx_f = float(estimated_idx)
        progressed = estimated_idx > current_idx
        if progressed:
            if self._last_progress_at_sec > 0.0 and tracking.emitted_at_sec > self._last_progress_at_sec:
                dt = max(1e-6, tracking.emitted_at_sec - self._last_progress_at_sec)
                self._last_velocity = (estimated_idx - self._last_estimated_idx_at_progress) / dt
            self._last_progress_at_sec = float(tracking.emitted_at_sec)
            self._last_estimated_idx_at_progress = float(estimated_idx)
        self._last_snapshot = self._render_snapshot(now_sec, signal_quality)
        return self._last_snapshot
    def snapshot(self, now_sec: float, signal_quality: SignalQuality | None) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if self._last_tracking is None and self._last_snapshot is None:
            return None
        self._last_snapshot = self._render_snapshot(now_sec, signal_quality)
        return self._last_snapshot
    def _weight_for_tracking(self, tracking: TrackingSnapshot) -> float:
        if tracking.tracking_mode == TrackingMode.LOCKED:
            return 0.82 if tracking.stable else 0.68
        if tracking.tracking_mode == TrackingMode.WEAK_LOCKED:
            return 0.42
        if tracking.tracking_mode == TrackingMode.REACQUIRING:
            return 0.16
        return 0.05
    def _render_snapshot(
        self,
        now_sec: float,
        signal_quality: SignalQuality | None,
    ) -> ProgressEstimate:
        assert self._ref_map is not None
        tracking = self._last_tracking
        estimated_idx = max(0, min(int(round(self._estimated_idx_f)), len(self._ref_map.tokens) - 1))
        estimated_ref_time_sec = float(self._ref_map.tokens[estimated_idx].t_start)
        progress_age = 9999.0
        if self._last_progress_at_sec > 0.0:
            progress_age = max(0.0, now_sec - self._last_progress_at_sec)
        recently_progressed = progress_age <= self.recent_progress_sec
        signal_speaking = False
        if signal_quality is not None:
            signal_speaking = (
                signal_quality.vad_active
                or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
            )
        tracking_mode = TrackingMode.BOOTSTRAP
        tracking_quality = 0.0
        confidence = 0.0
        stable = False
        source_candidate_ref_idx = estimated_idx
        source_committed_ref_idx = estimated_idx
        event_emitted_at_sec = self._last_event_at_sec
        if tracking is not None:
            tracking_mode = tracking.tracking_mode
            tracking_quality = tracking.tracking_quality.overall_score
            confidence = tracking.confidence
            stable = tracking.stable
            source_candidate_ref_idx = tracking.candidate_ref_idx
            source_committed_ref_idx = tracking.committed_ref_idx
        if now_sec <= self._force_reacquire_until_sec:
            tracking_mode = TrackingMode.REACQUIRING
            tracking_quality = min(tracking_quality, 0.55)
        active_speaking = False
        if recently_progressed:
            active_speaking = True
        elif signal_speaking and tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
            active_speaking = True
        elif signal_speaking and tracking_quality >= 0.70:
            active_speaking = True
        user_state = self.behavior_interpreter.infer(
            progress_age=progress_age,
            signal_quality=signal_quality,
            tracking=tracking,
            tracking_mode=tracking_mode,
            tracking_quality=tracking_quality,
            candidate_idx=source_candidate_ref_idx,
            estimated_idx=estimated_idx,
        )
        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=estimated_ref_time_sec,
            progress_velocity_idx_per_sec=float(self._last_velocity),
            event_emitted_at_sec=float(event_emitted_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_age_sec=float(progress_age),
            source_candidate_ref_idx=int(source_candidate_ref_idx),
            source_committed_ref_idx=int(source_committed_ref_idx),
            tracking_mode=tracking_mode,
            tracking_quality=float(tracking_quality),
            stable=bool(stable),
            confidence=float(confidence),
            active_speaking=bool(active_speaking),
            recently_progressed=bool(recently_progressed),
            user_state=user_state,
        )
```

---
### 文件: `shadowing_app/src/shadowing/progress/monotonic_estimator.py`

```python
from __future__ import annotations
from shadowing.types import AlignResult, ProgressEstimate, ReferenceMap
class MonotonicProgressEstimator:
    def __init__(
        self,
        active_speaking_confidence: float = 0.68,
        recent_progress_sec: float = 0.90,
        speaking_event_fresh_sec: float = 0.45,
        local_match_for_speaking: float = 0.65,
    ) -> None:
        self.active_speaking_confidence = float(active_speaking_confidence)
        self.recent_progress_sec = float(recent_progress_sec)
        self.speaking_event_fresh_sec = float(speaking_event_fresh_sec)
        self.local_match_for_speaking = float(local_match_for_speaking)
        self._ref_map: ReferenceMap | None = None
        self._estimated_idx_f = 0.0
        self._last_source_candidate_idx = 0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_estimated_idx_at_progress = 0.0
        self._last_velocity = 0.0
        self._last_alignment: AlignResult | None = None
        self._last_snapshot: ProgressEstimate | None = None
    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._estimated_idx_f = float(start_idx)
        self._last_source_candidate_idx = start_idx
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_estimated_idx_at_progress = float(start_idx)
        self._last_velocity = 0.0
        self._last_alignment = None
        self._last_snapshot = None
    def on_playback_generation_changed(self, start_idx: int | None = None) -> None:
        if self._ref_map is None:
            return
        idx = int(round(self._estimated_idx_f)) if start_idx is None else int(start_idx)
        self.reset(self._ref_map, start_idx=idx)
    def update(self, alignment: AlignResult | None) -> ProgressEstimate | None:
        if alignment is None or self._ref_map is None or not self._ref_map.tokens:
            return self._last_snapshot
        self._last_alignment = alignment
        event_time = float(alignment.emitted_at_sec)
        if event_time <= 0.0:
            event_time = self._last_event_at_sec
        candidate_idx = int(alignment.candidate_ref_idx)
        committed_idx = int(alignment.committed_ref_idx)
        current_estimated_idx = int(round(self._estimated_idx_f))
        target_idx = float(max(candidate_idx, committed_idx, current_estimated_idx))
        if alignment.stable:
            weight = 0.88
        elif alignment.confidence >= 0.90:
            weight = 0.72
        elif alignment.confidence >= 0.78:
            weight = 0.50
        else:
            weight = 0.26
        if candidate_idx < current_estimated_idx:
            target_idx = float(current_estimated_idx)
            weight = min(weight, 0.12)
        updated_idx = max(
            self._estimated_idx_f,
            (1.0 - weight) * self._estimated_idx_f + weight * target_idx,
        )
        if alignment.local_match_ratio >= 0.70 and candidate_idx > current_estimated_idx:
            updated_idx = max(updated_idx, float(current_estimated_idx) + 0.60)
        estimated_idx = max(0, min(int(round(updated_idx)), len(self._ref_map.tokens) - 1))
        self._estimated_idx_f = float(estimated_idx)
        progressed = estimated_idx > current_estimated_idx
        if progressed:
            if self._last_progress_at_sec > 0.0 and event_time > self._last_progress_at_sec:
                dt = max(1e-6, event_time - self._last_progress_at_sec)
                self._last_velocity = (estimated_idx - self._last_estimated_idx_at_progress) / dt
            self._last_progress_at_sec = event_time
            self._last_estimated_idx_at_progress = float(estimated_idx)
        self._last_source_candidate_idx = candidate_idx
        self._last_event_at_sec = event_time
        self._last_snapshot = self._render_snapshot(now_sec=event_time)
        return self._last_snapshot
    def snapshot(self, now_sec: float) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if self._last_alignment is None and self._last_snapshot is None:
            return None
        self._last_snapshot = self._render_snapshot(now_sec=now_sec)
        return self._last_snapshot
    def _render_snapshot(self, now_sec: float) -> ProgressEstimate:
        assert self._ref_map is not None
        alignment = self._last_alignment
        estimated_idx = max(0, min(int(round(self._estimated_idx_f)), len(self._ref_map.tokens) - 1))
        estimated_ref_time_sec = float(self._ref_map.tokens[estimated_idx].t_start)
        if self._last_progress_at_sec > 0.0 and now_sec >= self._last_progress_at_sec:
            last_progress_age = now_sec - self._last_progress_at_sec
        else:
            last_progress_age = 9999.0
        recently_progressed = last_progress_age <= self.recent_progress_sec
        active_speaking = False
        if alignment is not None:
            forward_delta = alignment.candidate_ref_idx - estimated_idx
            event_fresh = (
                (now_sec - self._last_event_at_sec) <= self.speaking_event_fresh_sec
                if self._last_event_at_sec > 0.0 and now_sec >= self._last_event_at_sec
                else False
            )
            if recently_progressed:
                active_speaking = True
            elif (
                event_fresh
                and alignment.stable
                and alignment.confidence >= self.active_speaking_confidence
                and forward_delta >= 0
            ):
                active_speaking = True
            elif (
                event_fresh
                and alignment.confidence >= max(self.active_speaking_confidence, 0.76)
                and alignment.local_match_ratio >= self.local_match_for_speaking
                and alignment.candidate_ref_idx > alignment.committed_ref_idx
            ):
                active_speaking = True
        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=estimated_ref_time_sec,
            source_candidate_ref_idx=(
                int(alignment.candidate_ref_idx) if alignment is not None else int(self._last_source_candidate_idx)
            ),
            source_committed_ref_idx=(
                int(alignment.committed_ref_idx) if alignment is not None else estimated_idx
            ),
            confidence=float(alignment.confidence) if alignment is not None else 0.0,
            stable=bool(alignment.stable) if alignment is not None else False,
            event_emitted_at_sec=float(self._last_event_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_velocity_idx_per_sec=float(self._last_velocity),
            recently_progressed=recently_progressed,
            last_progress_age_sec=float(last_progress_age),
            active_speaking=active_speaking,
            phase_hint="follow" if active_speaking or recently_progressed else "wait",
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/aligner.py`

```python
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Any
logger = logging.getLogger(__name__)
def _normalize_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", text)
    return text
def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))
@dataclass(slots=True)
class AlignmentCandidate:
    ref_idx: int
    confidence: float
    local_match_ratio: float
    matched_chars: int
    source_text: str
@dataclass(slots=True)
class AlignmentTrackingQuality:
    local_score: float
    continuity_score: float
    confidence_score: float
    overall_score: float
@dataclass(slots=True)
class AlignmentSnapshot:
    candidate_ref_idx: int
    committed_ref_idx: int
    confidence: float
    stable: bool
    local_match_ratio: float
    repeat_penalty: float
    emitted_at_sec: float
    tracking_mode: str
    tracking_quality: AlignmentTrackingQuality
class RealtimeAligner:
    def __init__(
        self,
        *,
        window_back: int = 8,
        window_ahead: int = 40,
        stable_hits: int = 2,
        min_confidence: float = 0.60,
        debug: bool = False,
    ) -> None:
        self.window_back = max(0, int(window_back))
        self.window_ahead = max(1, int(window_ahead))
        self.stable_hits = max(1, int(stable_hits))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self.debug = bool(debug)
        self._tokens: list[dict[str, Any]] = []
        self._norm_tokens: list[str] = []
        self._committed_ref_idx = 0
        self._last_candidate_ref_idx = 0
        self._same_candidate_run = 0
        self._last_partial_text = ""
        self._last_emitted_at_sec = 0.0
    def reset(self, reference_tokens: list[dict[str, Any]]) -> None:
        self._tokens = list(reference_tokens or [])
        self._norm_tokens = [_normalize_text(x.get("text", "")) for x in self._tokens]
        self._committed_ref_idx = 0
        self._last_candidate_ref_idx = 0
        self._same_candidate_run = 0
        self._last_partial_text = ""
        self._last_emitted_at_sec = 0.0
    def update(
        self,
        *,
        partial_text: str,
        emitted_at_sec: float,
    ) -> AlignmentSnapshot | None:
        if not self._tokens:
            return None
        norm = _normalize_text(partial_text)
        if not norm:
            return self._build_snapshot(
                candidate_ref_idx=self._committed_ref_idx,
                confidence=0.0,
                local_match_ratio=0.0,
                matched_chars=0,
                source_text="",
                emitted_at_sec=emitted_at_sec,
            )
        search_start = max(0, self._committed_ref_idx - self.window_back)
        search_end = min(len(self._tokens), self._committed_ref_idx + self.window_ahead + 1)
        best = self._scan_candidates(
            norm_text=norm,
            search_start=search_start,
            search_end=search_end,
        )
        if best is None:
            return self._build_snapshot(
                candidate_ref_idx=self._committed_ref_idx,
                confidence=0.0,
                local_match_ratio=0.0,
                matched_chars=0,
                source_text=norm,
                emitted_at_sec=emitted_at_sec,
            )
        if best.ref_idx == self._last_candidate_ref_idx:
            self._same_candidate_run += 1
        else:
            self._same_candidate_run = 1
            self._last_candidate_ref_idx = best.ref_idx
        stable = (
            best.confidence >= self.min_confidence
            and self._same_candidate_run >= self.stable_hits
        )
        if stable and best.ref_idx >= self._committed_ref_idx:
            self._committed_ref_idx = best.ref_idx
        snapshot = self._build_snapshot(
            candidate_ref_idx=best.ref_idx,
            confidence=best.confidence,
            local_match_ratio=best.local_match_ratio,
            matched_chars=best.matched_chars,
            source_text=best.source_text,
            emitted_at_sec=emitted_at_sec,
        )
        if self.debug:
            logger.info(
                "align: partial=%r candidate=%s committed=%s conf=%.3f stable=%s ratio=%.3f",
                partial_text,
                snapshot.candidate_ref_idx,
                snapshot.committed_ref_idx,
                snapshot.confidence,
                snapshot.stable,
                snapshot.local_match_ratio,
            )
        self._last_partial_text = norm
        self._last_emitted_at_sec = float(emitted_at_sec)
        return snapshot
    def _scan_candidates(
        self,
        *,
        norm_text: str,
        search_start: int,
        search_end: int,
    ) -> AlignmentCandidate | None:
        best: AlignmentCandidate | None = None
        for idx in range(search_start, search_end):
            candidate = self._score_candidate(idx=idx, norm_text=norm_text)
            if candidate is None:
                continue
            if best is None:
                best = candidate
                continue
            if candidate.confidence > best.confidence + 1e-6:
                best = candidate
            elif abs(candidate.confidence - best.confidence) <= 1e-6:
                if candidate.ref_idx > best.ref_idx:
                    best = candidate
        return best
    def _score_candidate(self, *, idx: int, norm_text: str) -> AlignmentCandidate | None:
        if idx < 0 or idx >= len(self._norm_tokens):
            return None
        token_text = self._norm_tokens[idx]
        if not token_text:
            return None
        overlap = self._longest_common_subsequence_approx(norm_text, token_text)
        if overlap <= 0:
            return None
        local_match_ratio = overlap / max(1, len(token_text))
        source_cover_ratio = overlap / max(1, len(norm_text))
        continuity_bonus = 0.0
        if idx == self._committed_ref_idx:
            continuity_bonus += 0.08
        elif idx == self._committed_ref_idx + 1:
            continuity_bonus += 0.06
        elif idx > self._committed_ref_idx + 1:
            jump = idx - self._committed_ref_idx
            continuity_bonus -= min(0.14, 0.015 * jump)
        elif idx < self._committed_ref_idx:
            back = self._committed_ref_idx - idx
            continuity_bonus -= min(0.18, 0.03 * back)
        confidence = (
            0.58 * local_match_ratio
            + 0.26 * source_cover_ratio
            + continuity_bonus
        )
        confidence = max(0.0, min(1.0, confidence))
        return AlignmentCandidate(
            ref_idx=idx,
            confidence=confidence,
            local_match_ratio=max(0.0, min(1.0, local_match_ratio)),
            matched_chars=overlap,
            source_text=norm_text,
        )
    def _build_snapshot(
        self,
        *,
        candidate_ref_idx: int,
        confidence: float,
        local_match_ratio: float,
        matched_chars: int,
        source_text: str,
        emitted_at_sec: float,
    ) -> AlignmentSnapshot:
        candidate_ref_idx = _clamp(candidate_ref_idx, 0, max(0, len(self._tokens) - 1))
        committed_ref_idx = _clamp(self._committed_ref_idx, 0, max(0, len(self._tokens) - 1))
        stable = confidence >= self.min_confidence and self._same_candidate_run >= self.stable_hits
        repeat_penalty = 0.0
        if committed_ref_idx > candidate_ref_idx:
            repeat_penalty = min(1.0, 0.18 * (committed_ref_idx - candidate_ref_idx))
        elif candidate_ref_idx == committed_ref_idx and source_text == self._last_partial_text:
            repeat_penalty = min(1.0, 0.08 * self._same_candidate_run)
        continuity_score = 1.0
        if candidate_ref_idx < committed_ref_idx:
            continuity_score = max(0.0, 1.0 - 0.18 * (committed_ref_idx - candidate_ref_idx))
        elif candidate_ref_idx > committed_ref_idx:
            continuity_score = max(0.0, 1.0 - 0.04 * (candidate_ref_idx - committed_ref_idx))
        confidence_score = float(confidence)
        overall_score = (
            0.40 * float(local_match_ratio)
            + 0.30 * continuity_score
            + 0.30 * confidence_score
        )
        overall_score = max(0.0, min(1.0, overall_score))
        if confidence < 0.20:
            tracking_mode = "LOST"
        elif stable and confidence >= self.min_confidence:
            tracking_mode = "LOCKED"
        elif confidence >= max(0.35, self.min_confidence - 0.12):
            tracking_mode = "WEAK_LOCKED"
        else:
            tracking_mode = "REACQUIRING"
        return AlignmentSnapshot(
            candidate_ref_idx=int(candidate_ref_idx),
            committed_ref_idx=int(committed_ref_idx),
            confidence=float(max(0.0, min(1.0, confidence))),
            stable=bool(stable),
            local_match_ratio=float(max(0.0, min(1.0, local_match_ratio))),
            repeat_penalty=float(max(0.0, min(1.0, repeat_penalty))),
            emitted_at_sec=float(emitted_at_sec),
            tracking_mode=str(tracking_mode),
            tracking_quality=AlignmentTrackingQuality(
                local_score=float(max(0.0, min(1.0, local_match_ratio))),
                continuity_score=float(max(0.0, min(1.0, continuity_score))),
                confidence_score=float(max(0.0, min(1.0, confidence_score))),
                overall_score=float(max(0.0, min(1.0, overall_score))),
            ),
        )
    def _longest_common_subsequence_approx(self, a: str, b: str) -> int:
        if not a or not b:
            return 0
        longest_substring = self._longest_common_substring_len(a, b)
        prefix = 0
        for x, y in zip(a, b):
            if x != y:
                break
            prefix += 1
        suffix = 0
        for x, y in zip(a[::-1], b[::-1]):
            if x != y:
                break
            suffix += 1
        return max(longest_substring, prefix, suffix)
    def _longest_common_substring_len(self, a: str, b: str) -> int:
        if not a or not b:
            return 0
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        best = 0
        for win in range(len(shorter), 0, -1):
            if win <= best:
                break
            for i in range(0, len(shorter) - win + 1):
                sub = shorter[i : i + win]
                if sub in longer:
                    return win
        return best
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/incremental_aligner.py`

```python
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Sequence
def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+", "", text)
    return text
def _safe_ratio(a: int, b: int) -> float:
    if b <= 0:
        return 0.0
    return max(0.0, min(1.0, float(a) / float(b)))
@dataclass(slots=True)
class AlignmentResult:
    committed: int
    candidate: int
    score: float
    conf: float
    stable: bool
    backward: bool
    matched_n: int
    hyp_n: int
    mode: str
    window: tuple[int, int]
    local_match: float = 0.0
    soft_committed: bool = False
    accepted: bool = False
    raw_text: str = ""
    normalized_text: str = ""
    repeated_candidate: bool = False
    weak_forward: bool = False
    @property
    def advance(self) -> int:
        return max(0, self.candidate - self.committed)
class IncrementalAligner:
    def __init__(
        self,
        reference_text: str | Sequence[str] | None = None,
        *,
        window_back: int = 10,
        window_ahead: int = 48,
        stable_hits: int = 2,
        min_confidence: float = 0.62,
        debug: bool = False,
    ) -> None:
        self.window_back = int(window_back)
        self.window_ahead = int(window_ahead)
        self.stable_hits = max(1, int(stable_hits))
        self.min_confidence = float(min_confidence)
        self.debug = bool(debug)
        self.reference_text = ""
        self.reference_norm = ""
        self._committed = 0
        self._last_candidate = 0
        self._same_candidate_hits = 0
        self._same_zone_hits = 0
        self._last_zone_anchor = 0
        self._forced_center: int | None = None
        self._forced_budget = 0
        self._forced_window_back: int | None = None
        self._forced_window_ahead: int | None = None
        if reference_text is not None:
            self.set_reference(reference_text)
    @property
    def committed_index(self) -> int:
        return self._committed
    def get_committed_index(self) -> int:
        return self._committed
    def set_reference(self, reference_text: str | Sequence[str]) -> None:
        if isinstance(reference_text, (list, tuple)):
            reference_text = "".join(str(x) for x in reference_text)
        self.reference_text = reference_text or ""
        self.reference_norm = _normalize_text(self.reference_text)
        self.reset(committed=0)
    def reset(self, committed: int | None = None) -> None:
        if committed is None:
            self._committed = 0
        else:
            self._committed = max(0, min(int(committed), len(self.reference_norm)))
        self._last_candidate = self._committed
        self._same_candidate_hits = 0
        self._same_zone_hits = 0
        self._last_zone_anchor = (self._committed // 4) * 4
        self._forced_center = None
        self._forced_budget = 0
        self._forced_window_back = None
        self._forced_window_ahead = None
    def force_recenter(
        self,
        committed_hint: int,
        *,
        window_back: int | None = None,
        window_ahead: int | None = None,
        budget_events: int = 6,
    ) -> None:
        if not self.reference_norm:
            return
        hint = max(0, min(int(committed_hint), len(self.reference_norm)))
        self._forced_center = hint
        self._forced_window_back = int(window_back) if window_back is not None else max(16, self.window_back + 6)
        self._forced_window_ahead = int(window_ahead) if window_ahead is not None else max(32, self.window_ahead // 2)
        self._forced_budget = max(1, int(budget_events))
        self._committed = min(self._committed, hint)
    def update(self, hypothesis_text: str) -> AlignmentResult:
        return self.align(hypothesis_text)
    def align(self, hypothesis_text: str) -> AlignmentResult:
        hyp_raw = hypothesis_text or ""
        hyp = _normalize_text(hyp_raw)
        if not self.reference_norm:
            return AlignmentResult(
                committed=self._committed,
                candidate=self._committed,
                score=-1.0,
                conf=0.0,
                stable=False,
                backward=False,
                matched_n=0,
                hyp_n=len(hyp),
                mode="no_reference",
                window=(0, 0),
                raw_text=hyp_raw,
                normalized_text=hyp,
            )
        if not hyp:
            return AlignmentResult(
                committed=self._committed,
                candidate=self._committed,
                score=-1.0,
                conf=0.0,
                stable=False,
                backward=False,
                matched_n=0,
                hyp_n=0,
                mode="empty",
                window=(self._committed, self._committed),
                raw_text=hyp_raw,
                normalized_text=hyp,
            )
        candidate, matched_n, score, conf, backward, mode, window, local_match = self._search_best_candidate(hyp)
        repeated_candidate = candidate == self._last_candidate
        if repeated_candidate:
            self._same_candidate_hits += 1
        else:
            self._same_candidate_hits = 1
        zone_anchor = (candidate // 4) * 4
        if zone_anchor == self._last_zone_anchor and candidate >= self._committed:
            self._same_zone_hits += 1
        else:
            self._same_zone_hits = 1
        self._last_zone_anchor = zone_anchor
        advance = candidate - self._committed
        strong_accept = (
            not backward
            and advance >= 1
            and conf >= self.min_confidence
            and local_match >= 0.60
            and self._same_candidate_hits >= self.stable_hits
        )
        weak_forward = (
            not backward
            and advance >= 3
            and conf >= max(0.80, self.min_confidence + 0.16)
            and local_match >= 0.76
            and self._same_zone_hits >= 2
        )
        accepted = False
        soft_committed = False
        stable = False
        if strong_accept:
            self._committed = max(self._committed, candidate)
            accepted = True
            stable = True
        elif weak_forward:
            self._committed = max(self._committed, candidate)
            accepted = True
            soft_committed = True
        result = AlignmentResult(
            committed=self._committed,
            candidate=candidate,
            score=score,
            conf=conf,
            stable=stable,
            backward=backward,
            matched_n=matched_n,
            hyp_n=len(hyp),
            mode=mode,
            window=window,
            local_match=local_match,
            soft_committed=soft_committed,
            accepted=accepted,
            raw_text=hyp_raw,
            normalized_text=hyp,
            repeated_candidate=repeated_candidate,
            weak_forward=weak_forward,
        )
        self._last_candidate = candidate
        if self._forced_budget > 0:
            self._forced_budget -= 1
            if self._forced_budget <= 0:
                self._forced_center = None
                self._forced_window_back = None
                self._forced_window_ahead = None
        return result
    def _search_best_candidate(
        self,
        hyp: str,
    ) -> tuple[int, int, float, float, bool, str, tuple[int, int], float]:
        ref = self.reference_norm
        committed = self._committed
        start, end, mode = self._build_search_window(hyp)
        best_candidate = committed
        best_matched_n = 0
        best_score = -1e9
        best_conf = 0.0
        best_local_match = 0.0
        for cand in range(start, end + 1):
            seg = ref[cand : min(len(ref), cand + max(len(hyp) + 10, 18))]
            if not seg:
                continue
            sim, matched_n = self._substring_similarity(hyp, seg)
            prefix = self._prefix_match_ratio(hyp, seg)
            suffix = self._suffix_match_ratio(hyp, seg)
            bigram = self._bigram_overlap(hyp, seg)
            local_match = 0.45 * sim + 0.25 * prefix + 0.20 * suffix + 0.10 * bigram
            advance = cand - committed
            backward = advance < 0
            score = (
                10.0 * sim
                + 4.2 * prefix
                + 3.4 * suffix
                + 2.8 * bigram
                + 0.12 * matched_n
                - 0.14 * abs(advance)
                - (1.8 if backward else 0.0)
            )
            if not backward and matched_n >= min(4, len(hyp)):
                score += 0.8
            if not backward and suffix >= 0.68:
                score += 0.5
            if backward and sim < 0.62:
                score -= 1.2
            conf = max(
                0.0,
                min(
                    0.999,
                    0.55 * sim + 0.18 * prefix + 0.14 * suffix + 0.08 * bigram + 0.05 * (0.0 if backward else 1.0),
                ),
            )
            if score > best_score:
                best_score = score
                best_conf = conf
                best_local_match = local_match
                best_matched_n = matched_n
                best_candidate = min(len(ref), cand + max(matched_n, int(round(len(hyp) * max(sim, 0.35)))))
        backward = best_candidate < committed
        if backward and best_conf < 0.58:
            best_candidate = committed
            best_score = min(best_score, -0.8)
            mode = "backward_rejected"
        elif best_conf < 0.44 and mode == "normal":
            mode = "low_confidence"
        return (
            best_candidate,
            best_matched_n,
            float(best_score),
            float(best_conf),
            bool(backward),
            mode,
            (start, end),
            float(best_local_match),
        )
    def _build_search_window(self, hyp: str) -> tuple[int, int, str]:
        ref = self.reference_norm
        committed = self._committed
        if self._forced_center is not None and self._forced_budget > 0:
            center = max(committed, int(self._forced_center))
            back = int(self._forced_window_back or self.window_back)
            ahead = int(self._forced_window_ahead or self.window_ahead)
            return (
                max(0, center - back),
                min(len(ref), center + ahead),
                "forced_recenter",
            )
        long_partial = len(hyp) >= 12
        repeated_zone = self._same_zone_hits >= 3
        recovery_mode = long_partial or repeated_zone
        back = self.window_back + (6 if recovery_mode else 0)
        ahead = self.window_ahead + (10 if recovery_mode else 0)
        return (
            max(0, committed - back),
            min(len(ref), committed + ahead),
            "recovery" if recovery_mode else "normal",
        )
    def _substring_similarity(self, hyp: str, seg: str) -> tuple[float, int]:
        if not hyp or not seg:
            return 0.0, 0
        n = len(hyp)
        m = len(seg)
        best_sim = 0.0
        best_match = 0
        min_len = max(1, int(round(n * 0.70)))
        max_len = min(m, n + 6)
        for take in range(min_len, max_len + 1):
            ref_sub = seg[:take]
            dist = self._edit_distance_banded(hyp, ref_sub, band=max(2, abs(len(hyp) - len(ref_sub)) + 3))
            denom = max(len(hyp), len(ref_sub), 1)
            sim = max(0.0, 1.0 - dist / denom)
            matched = max(0, len(hyp) - dist)
            if sim > best_sim:
                best_sim = sim
                best_match = matched
        return best_sim, best_match
    def _edit_distance_banded(self, a: str, b: str, band: int) -> int:
        n = len(a)
        m = len(b)
        inf = 10**9
        prev = [inf] * (m + 1)
        prev[0] = 0
        for j in range(1, m + 1):
            prev[j] = j
        for i in range(1, n + 1):
            cur = [inf] * (m + 1)
            lo = max(1, i - band)
            hi = min(m, i + band)
            if lo == 1:
                cur[0] = i
            for j in range(lo, hi + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                cur[j] = min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            prev = cur
        return int(prev[m])
    def _prefix_match_ratio(self, a: str, b: str) -> float:
        n = min(len(a), len(b))
        if n <= 0:
            return 0.0
        hit = 0
        for i in range(n):
            if a[i] != b[i]:
                break
            hit += 1
        return _safe_ratio(hit, min(len(a), 10))
    def _suffix_match_ratio(self, a: str, b: str) -> float:
        n = min(len(a), len(b))
        if n <= 0:
            return 0.0
        hit = 0
        for i in range(1, n + 1):
            if a[-i] != b[-i]:
                break
            hit += 1
        return _safe_ratio(hit, min(len(a), 10))
    def _bigram_overlap(self, a: str, b: str) -> float:
        if len(a) < 2 or len(b) < 2:
            return 0.0
        aset = {a[i : i + 2] for i in range(len(a) - 1)}
        bset = {b[i : i + 2] for i in range(len(b) - 1)}
        if not aset:
            return 0.0
        return _safe_ratio(len(aset & bset), len(aset))
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/scoring.py`

```python
from __future__ import annotations
from rapidfuzz import fuzz
class AlignmentScorer:
    def score_token_pair(self, ref_char: str, ref_py: str, hyp_char: str, hyp_py: str) -> float:
        if ref_char == hyp_char:
            return 3.0
        if ref_py and ref_py == hyp_py:
            return 2.0
        py_sim = fuzz.ratio(ref_py, hyp_py) if ref_py and hyp_py else 0.0
        if py_sim >= 80:
            return 1.0
        return -1.5
    def insertion_penalty(self) -> float:
        return -0.7
    def deletion_penalty(self) -> float:
        return -0.9
    def backward_penalty(self) -> float:
        return -2.0
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/window_selector.py`

```python
from __future__ import annotations
from shadowing.types import RefToken, ReferenceMap
class WindowSelector:
    def __init__(self, look_back: int = 8, look_ahead: int = 40) -> None:
        self.look_back = int(look_back)
        self.look_ahead = int(look_ahead)
    def select(
        self,
        ref_map: ReferenceMap,
        committed_idx: int,
        *,
        look_back: int | None = None,
        look_ahead: int | None = None,
    ) -> tuple[list[RefToken], int, int]:
        back = self.look_back if look_back is None else max(1, int(look_back))
        ahead = self.look_ahead if look_ahead is None else max(1, int(look_ahead))
        start = max(0, committed_idx - back)
        end = min(len(ref_map.tokens), committed_idx + ahead + 1)
        return ref_map.tokens[start:end], start, end
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/fake_asr_provider.py`

```python
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
import numpy as np
from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEventType, RawAsrEvent
@dataclass(slots=True)
class FakeAsrStep:
    offset_sec: float
    text: str
    event_type: AsrEventType = AsrEventType.PARTIAL
@dataclass(slots=True)
class FakeAsrConfig:
    scripted_steps: list[FakeAsrStep] = field(default_factory=list)
    reference_text: str = ""
    chars_per_sec: float = 4.0
    emit_partial_interval_sec: float = 0.12
    emit_final_on_endpoint: bool = True
    sample_rate: int = 16000
    bytes_per_sample: int = 2
    channels: int = 1
    vad_rms_threshold: float = 0.01
    vad_min_active_ms: float = 30.0
class FakeASRProvider(ASRProvider):
    def __init__(self, config: FakeAsrConfig) -> None:
        self.config = config
        self._running = False
        self._start_at = 0.0
        self._script_index = 0
        self._last_emit_at = 0.0
        self._bytes_received = 0
        self._speech_bytes_received = 0
        self._last_progress_text = ""
        self._last_final_text = ""
    @classmethod
    def from_reference_text(
        cls,
        reference_text: str,
        chars_per_step: int = 6,
        step_interval_sec: float = 0.28,
        lag_sec: float = 0.5,
        tail_final: bool = True,
    ) -> "FakeASRProvider":
        clean = reference_text.strip()
        steps: list[FakeAsrStep] = []
        t = lag_sec
        cursor = 0
        while cursor < len(clean):
            cursor = min(cursor + chars_per_step, len(clean))
            text = clean[:cursor]
            if text:
                steps.append(
                    FakeAsrStep(
                        offset_sec=t,
                        text=text,
                        event_type=AsrEventType.PARTIAL,
                    )
                )
            t += step_interval_sec
        if tail_final:
            steps.append(
                FakeAsrStep(
                    offset_sec=t + 0.1,
                    text=clean,
                    event_type=AsrEventType.FINAL,
                )
            )
        return cls(FakeAsrConfig(scripted_steps=steps))
    def start(self) -> None:
        self._running = True
        self._start_at = time.monotonic()
        self._script_index = 0
        self._last_emit_at = 0.0
        self._bytes_received = 0
        self._speech_bytes_received = 0
        self._last_progress_text = ""
        self._last_final_text = ""
    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running or not pcm_bytes:
            return
        self._bytes_received += len(pcm_bytes)
        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return
        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio_f32)))) if audio_f32.size else 0.0
        frame_ms = (
            1000.0
            * audio_i16.size
            / max(1, self.config.sample_rate * self.config.channels)
        )
        if rms >= self.config.vad_rms_threshold and frame_ms >= self.config.vad_min_active_ms:
            self._speech_bytes_received += len(pcm_bytes)
    def poll_raw_events(self) -> list[RawAsrEvent]:
        if not self._running:
            return []
        if self.config.scripted_steps:
            return self._poll_scripted()
        if self.config.reference_text:
            return self._poll_progressive()
        return []
    def reset(self) -> None:
        self.start()
    def close(self) -> None:
        self._running = False
    def _poll_scripted(self) -> list[RawAsrEvent]:
        now = time.monotonic()
        elapsed = now - self._start_at
        events: list[RawAsrEvent] = []
        while self._script_index < len(self.config.scripted_steps):
            step = self.config.scripted_steps[self._script_index]
            if elapsed < step.offset_sec:
                break
            events.append(
                RawAsrEvent(
                    event_type=step.event_type,
                    text=step.text,
                    emitted_at_sec=now,
                )
            )
            self._script_index += 1
        return events
    def _poll_progressive(self) -> list[RawAsrEvent]:
        now = time.monotonic()
        if (now - self._last_emit_at) < self.config.emit_partial_interval_sec:
            return []
        total_speech_sec = self._bytes_to_seconds(self._speech_bytes_received)
        n_chars = int(math.floor(total_speech_sec * self.config.chars_per_sec))
        n_chars = max(0, min(n_chars, len(self.config.reference_text)))
        current_text = self.config.reference_text[:n_chars]
        events: list[RawAsrEvent] = []
        if current_text and current_text != self._last_progress_text:
            events.append(
                RawAsrEvent(
                    event_type=AsrEventType.PARTIAL,
                    text=current_text,
                    emitted_at_sec=now,
                )
            )
            self._last_progress_text = current_text
            self._last_emit_at = now
        if (
            self.config.emit_final_on_endpoint
            and n_chars >= len(self.config.reference_text)
            and self._last_final_text != self.config.reference_text
        ):
            events.append(
                RawAsrEvent(
                    event_type=AsrEventType.FINAL,
                    text=self.config.reference_text,
                    emitted_at_sec=now,
                )
            )
            self._last_final_text = self.config.reference_text
        return events
    def _bytes_to_seconds(self, n_bytes: int) -> float:
        bytes_per_sec = (
            self.config.sample_rate
            * self.config.bytes_per_sample
            * self.config.channels
        )
        return n_bytes / bytes_per_sec if bytes_per_sec > 0 else 0.0
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/normalizer.py`

```python
from __future__ import annotations
import re
from pypinyin import lazy_pinyin
from shadowing.types import AsrEvent, RawAsrEvent
class TextNormalizer:
    _drop_pattern = re.compile(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+")
    _digit_map = str.maketrans(
        {
            "0": "零",
            "1": "一",
            "2": "二",
            "3": "三",
            "4": "四",
            "5": "五",
            "6": "六",
            "7": "七",
            "8": "八",
            "9": "九",
        }
    )
    def normalize_text(self, text: str) -> str:
        text = (text or "").strip().replace("\u3000", " ")
        text = text.translate(self._digit_map)
        return self._drop_pattern.sub("", text)
    def to_chars_from_normalized(self, normalized_text: str) -> list[str]:
        return list(normalized_text) if normalized_text else []
    def to_pinyin_seq_from_normalized(self, normalized_text: str) -> list[str]:
        return lazy_pinyin(normalized_text) if normalized_text else []
    def normalize_raw_event(self, event: RawAsrEvent) -> AsrEvent | None:
        normalized = self.normalize_text(event.text)
        if not normalized:
            return None
        return AsrEvent(
            event_type=event.event_type,
            text=event.text,
            normalized_text=normalized,
            chars=self.to_chars_from_normalized(normalized),
            pinyin_seq=self.to_pinyin_seq_from_normalized(normalized),
            emitted_at_sec=event.emitted_at_sec,
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/sherpa_streaming_provider.py`

```python
from __future__ import annotations
import logging
import time
from typing import Any
import numpy as np
from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEventType, RawAsrEvent
logger = logging.getLogger(__name__)
class SherpaStreamingProvider(ASRProvider):
    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
        sample_rate: int = 16000,
        emit_partial_interval_sec: float = 0.08,
        enable_endpoint: bool = True,
        debug_feed: bool = False,
        debug_feed_every_n_chunks: int = 20,
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.sample_rate = int(sample_rate)
        self.emit_partial_interval_sec = float(emit_partial_interval_sec)
        self.enable_endpoint = bool(enable_endpoint)
        self.debug_feed = bool(debug_feed)
        self.debug_feed_every_n_chunks = max(1, int(debug_feed_every_n_chunks))
        self._recognizer: Any | None = None
        self._stream: Any | None = None
        self._running = False
        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0
        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = 0.0
        self._summary_interval_sec = 2.5
        self._last_ready_state = False
        self._last_endpoint_state = False
        self._min_meaningful_text_len = int(self.model_config.get("min_meaningful_text_len", 2))
        self._endpoint_min_interval_sec = float(self.model_config.get("endpoint_min_interval_sec", 0.35))
        self._force_reset_after_empty_endpoints = int(
            self.model_config.get("force_reset_after_empty_endpoints", 999999999)
        )
        self._reset_on_empty_endpoint = bool(self.model_config.get("reset_on_empty_endpoint", False))
        self._preserve_stream_on_partial_only = bool(
            self.model_config.get("preserve_stream_on_partial_only", True)
        )
        self._log_hotwords_on_start = bool(self.model_config.get("log_hotwords_on_start", True))
        self._log_hotwords_preview_on_start = bool(
            self.model_config.get("log_hotwords_preview_on_start", True)
        )
        self._hotwords_preview_limit = max(1, int(self.model_config.get("hotwords_preview_limit", 12)))
        self._info_logging = bool(self.model_config.get("info_logging", True))
    def start(self) -> None:
        self._recognizer = self._build_recognizer()
        self._stream = self._recognizer.create_stream()
        self._running = True
        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0
        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False
        hotword_lines = self._parse_hotword_lines(self.hotwords)
        preview = hotword_lines[: self._hotwords_preview_limit]
        if self._info_logging and self._log_hotwords_on_start:
            logger.info(
                "[ASR-HOTWORDS] count=%d score=%.2f",
                len(hotword_lines),
                float(self.model_config.get("hotwords_score", 1.5)),
            )
            if self._log_hotwords_preview_on_start:
                if preview:
                    logger.info("[ASR-HOTWORDS-PREVIEW] %s", " | ".join(preview))
                else:
                    logger.info("[ASR-HOTWORDS-PREVIEW] <empty>")
        if self.debug_feed:
            logger.debug(
                "[ASR-CONFIG] sample_rate=%d emit_partial_interval_sec=%.3f "
                "enable_endpoint=%s min_meaningful_text_len=%d "
                "endpoint_min_interval_sec=%.3f reset_on_empty_endpoint=%s "
                "preserve_stream_on_partial_only=%s",
                self.sample_rate,
                self.emit_partial_interval_sec,
                self.enable_endpoint,
                self._min_meaningful_text_len,
                self._endpoint_min_interval_sec,
                self._reset_on_empty_endpoint,
                self._preserve_stream_on_partial_only,
            )
    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running or self._recognizer is None or self._stream is None or not pcm_bytes:
            return
        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return
        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        self._feed_counter += 1
        if self.debug_feed and self._feed_counter % self.debug_feed_every_n_chunks == 0:
            abs_mean = float(np.mean(np.abs(audio_f32))) if audio_f32.size else 0.0
            peak = float(np.max(np.abs(audio_f32))) if audio_f32.size else 0.0
            logger.debug(
                "[ASR-FEED] chunks=%d samples=%d abs_mean=%.5f peak=%.5f",
                self._feed_counter,
                audio_f32.size,
                abs_mean,
                peak,
            )
        self._stream.accept_waveform(self.sample_rate, audio_f32)
        ready_before = self._recognizer.is_ready(self._stream)
        if self.debug_feed and ready_before and not self._last_ready_state:
            logger.debug("[ASR-READY] stream became ready at feed_chunks=%d", self._feed_counter)
        self._last_ready_state = bool(ready_before)
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1
        self._maybe_log_summary()
    def poll_raw_events(self) -> list[RawAsrEvent]:
        if not self._running or self._recognizer is None or self._stream is None:
            return []
        now = time.monotonic()
        events: list[RawAsrEvent] = []
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1
        partial_text = self._normalize_text(self._get_result_text())
        if self.debug_feed and partial_text and partial_text != self._last_partial_log_text:
            logger.debug("[ASR-PARTIAL-RAW] %r", partial_text)
            self._last_partial_log_text = partial_text
        if (
            partial_text
            and partial_text != self._last_partial_text
            and (now - self._last_emit_at) >= self.emit_partial_interval_sec
        ):
            events.append(
                RawAsrEvent(
                    event_type=AsrEventType.PARTIAL,
                    text=partial_text,
                    emitted_at_sec=now,
                )
            )
            self._last_partial_text = partial_text
            self._last_emit_at = now
        endpoint_hit = self.enable_endpoint and self._is_endpoint()
        if self.debug_feed and endpoint_hit and not self._last_endpoint_state:
            preview = partial_text[:48]
            logger.debug(
                "[ASR-ENDPOINT-HIT] count_next=%d partial_len=%d preview=%r",
                self._endpoint_count + 1,
                len(partial_text),
                preview,
            )
        self._last_endpoint_state = bool(endpoint_hit)
        if endpoint_hit:
            if (now - self._last_endpoint_at) < self._endpoint_min_interval_sec:
                self._maybe_log_summary()
                return events
            self._endpoint_count += 1
            self._last_endpoint_at = now
            final_text = self._normalize_text(self._get_result_text())
            should_emit_final = self._is_meaningful_result(final_text)
            if self.debug_feed and final_text and final_text != self._last_final_text:
                logger.debug("[ASR-FINAL-RAW] %r", final_text)
            if should_emit_final and final_text != self._last_final_text:
                events.append(
                    RawAsrEvent(
                        event_type=AsrEventType.FINAL,
                        text=final_text,
                        emitted_at_sec=now,
                    )
                )
                self._last_final_text = final_text
                self._final_emit_count += 1
                self._empty_endpoint_count = 0
                self._reset_stream_state_only()
                self._last_partial_text = ""
                self._last_partial_log_text = ""
                self._last_ready_state = False
                self._last_endpoint_state = False
                if self.debug_feed:
                    logger.debug(
                        "[ASR-ENDPOINT] count=%d final_count=%d last_endpoint_at=%.3f "
                        "action=reset_after_final",
                        self._endpoint_count,
                        self._final_emit_count,
                        self._last_endpoint_at,
                    )
            else:
                self._empty_endpoint_count += 1
                if self.debug_feed:
                    logger.debug(
                        "[ASR-ENDPOINT-IGNORED] count=%d empty_count=%d partial_len=%d final_len=%d",
                        self._endpoint_count,
                        self._empty_endpoint_count,
                        len(partial_text),
                        len(final_text),
                    )
                if self._reset_on_empty_endpoint:
                    no_partial_context = not partial_text
                    no_final_context = not final_text
                    if self._preserve_stream_on_partial_only and partial_text and not final_text:
                        no_partial_context = False
                    if (
                        no_partial_context
                        and no_final_context
                        and self._empty_endpoint_count >= self._force_reset_after_empty_endpoints
                    ):
                        self._reset_stream_state_only()
                        self._last_partial_text = ""
                        self._last_partial_log_text = ""
                        self._last_ready_state = False
                        self._last_endpoint_state = False
                        self._empty_endpoint_count = 0
                        if self.debug_feed:
                            logger.debug(
                                "[ASR-ENDPOINT] count=%d final_count=%d last_endpoint_at=%.3f "
                                "action=reset_after_empty_endpoint",
                                self._endpoint_count,
                                self._final_emit_count,
                                self._last_endpoint_at,
                            )
        self._maybe_log_summary()
        return events
    def reset(self) -> None:
        if self._recognizer is None:
            return
        self._reset_stream_state_only()
        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0
        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False
        if self.debug_feed:
            logger.debug("[ASR-RESET] stream reset by external request")
    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None
    def _normalize_text(self, text: str) -> str:
        return str(text or "").strip()
    def _is_meaningful_result(self, text: str) -> bool:
        text = self._normalize_text(text)
        if not text:
            return False
        if len(text) < self._min_meaningful_text_len:
            return False
        return True
    def _get_result_text(self) -> str:
        result = self._recognizer.get_result(self._stream)
        if isinstance(result, str):
            return result
        if hasattr(result, "text"):
            return str(result.text or "")
        if isinstance(result, dict):
            return str(result.get("text", ""))
        return ""
    def _is_endpoint(self) -> bool:
        if self._recognizer is None or self._stream is None:
            return False
        if hasattr(self._recognizer, "is_endpoint"):
            try:
                return bool(self._recognizer.is_endpoint(self._stream))
            except TypeError:
                return False
        return False
    def _reset_stream_state_only(self) -> None:
        if self._recognizer is not None:
            self._stream = self._recognizer.create_stream()
    def _parse_hotword_lines(self, hotwords: str) -> list[str]:
        lines = [line.strip() for line in str(hotwords or "").splitlines() if line.strip()]
        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return deduped
    def _maybe_log_summary(self) -> None:
        if not self.debug_feed:
            return
        now = time.monotonic()
        if (now - self._last_summary_log_at) < self._summary_interval_sec:
            return
        current_text = ""
        if self._recognizer is not None and self._stream is not None:
            current_text = self._get_result_text().strip()
        preview = current_text[:32]
        logger.debug(
            "[ASR-SUMMARY] feeds=%d decodes=%d partials_len=%d finals=%d "
            "endpoints=%d empty_endpoints=%d preview=%r",
            self._feed_counter,
            self._decode_counter,
            len(self._last_partial_text),
            self._final_emit_count,
            self._endpoint_count,
            self._empty_endpoint_count,
            preview,
        )
        self._last_summary_log_at = now
    def _build_recognizer(self):
        import sherpa_onnx
        cfg = self.model_config
        tokens = cfg.get("tokens", "")
        encoder = cfg.get("encoder", "")
        decoder = cfg.get("decoder", "")
        joiner = cfg.get("joiner", "")
        missing = [
            name
            for name, value in (
                ("tokens", tokens),
                ("encoder", encoder),
                ("decoder", decoder),
                ("joiner", joiner),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing sherpa model paths in config: " + ", ".join(missing))
        hotwords = str(self.hotwords or cfg.get("hotwords", "")).strip()
        hotwords_score = float(cfg.get("hotwords_score", 1.5))
        if self.debug_feed:
            hotword_lines = self._parse_hotword_lines(hotwords)
            logger.debug(
                "[ASR-BUILD] hotwords_count=%d hotwords_score=%.2f provider=%s decoding_method=%s",
                len(hotword_lines),
                hotwords_score,
                cfg.get("provider", "cpu"),
                cfg.get("decoding_method", "greedy_search"),
            )
            if hotword_lines:
                logger.debug("[ASR-BUILD-HOTWORDS] %s", " | ".join(hotword_lines[:20]))
        base_kwargs = dict(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=cfg.get("num_threads", 2),
            sample_rate=self.sample_rate,
            feature_dim=cfg.get("feature_dim", 80),
            decoding_method=cfg.get("decoding_method", "greedy_search"),
            provider=cfg.get("provider", "cpu"),
        )
        hotword_kwargs = dict(
            hotwords=hotwords,
            hotwords_score=hotwords_score,
        )
        endpoint_kwargs = dict(
            enable_endpoint_detection=self.enable_endpoint,
            rule1_min_trailing_silence=cfg.get("rule1_min_trailing_silence", 10.0),
            rule2_min_trailing_silence=cfg.get("rule2_min_trailing_silence", 10.0),
            rule3_min_utterance_length=cfg.get("rule3_min_utterance_length", 60.0),
        )
        try:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **hotword_kwargs,
                **endpoint_kwargs,
            )
            if self.debug_feed:
                logger.debug("[ASR-BUILD] recognizer_created mode=transducer+hotwords+endpoint")
            return recognizer
        except TypeError as e1:
            if self.debug_feed:
                logger.debug("[ASR-BUILD] hotwords kwargs not accepted, fallback 1: %s", e1)
        try:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **endpoint_kwargs,
            )
            if self.debug_feed:
                logger.debug("[ASR-BUILD] recognizer_created mode=transducer+endpoint")
            return recognizer
        except TypeError as e2:
            if self.debug_feed:
                logger.debug("[ASR-BUILD] endpoint kwargs not accepted, fallback 2: %s", e2)
        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**base_kwargs)
        if self.debug_feed:
            logger.debug("[ASR-BUILD] recognizer_created mode=transducer_basic")
        return recognizer
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/device_utils.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import sounddevice as sd
@dataclass(slots=True)
class InputDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float
    hostapi_name: str
def list_input_devices() -> list[InputDeviceInfo]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    results: list[InputDeviceInfo] = []
    for idx, dev in enumerate(devices):
        max_in = int(dev["max_input_channels"])
        if max_in <= 0:
            continue
        hostapi_name = hostapis[int(dev["hostapi"])]["name"]
        results.append(
            InputDeviceInfo(
                index=int(idx),
                name=str(dev["name"]),
                max_input_channels=max_in,
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=str(hostapi_name),
            )
        )
    return results
def print_input_devices() -> None:
    devices = list_input_devices()
    if not devices:
        return
    for d in devices:
def get_default_input_device_index() -> int | None:
    default_input, _ = sd.default.device
    if default_input is None or int(default_input) < 0:
        return None
    return int(default_input)
def choose_input_device(
    preferred_index: int | None = None,
    preferred_name_substring: str | None = None,
) -> int | None:
    devices = list_input_devices()
    if not devices:
        return None
    if preferred_index is not None:
        for d in devices:
            if d.index == preferred_index:
                return d.index
    if preferred_name_substring:
        keyword = preferred_name_substring.lower().strip()
        for d in devices:
            if keyword and keyword in d.name.lower():
                return d.index
    default_idx = get_default_input_device_index()
    if default_idx is not None:
        return default_idx
    return devices[0].index
def check_input_settings(
    device: int | None,
    samplerate: int,
    channels: int = 1,
    dtype: str = "float32",
) -> bool:
    try:
        sd.check_input_settings(
            device=device,
            samplerate=int(samplerate),
            channels=int(channels),
            dtype=str(dtype),
        )
        return True
    except Exception:
        return False
def pick_working_input_config(
    preferred_device: int | None = None,
    preferred_name_substring: str | None = None,
    preferred_rates: list[int] | None = None,
    channels: int = 1,
    dtype: str = "float32",
) -> dict[str, Any] | None:
    preferred_rates = preferred_rates or [48000, 44100, 16000]
    device = choose_input_device(
        preferred_index=preferred_device,
        preferred_name_substring=preferred_name_substring,
    )
    if device is None:
        return None
    for sr in preferred_rates:
        if int(sr) <= 0:
            continue
        if check_input_settings(
            device=device,
            samplerate=int(sr),
            channels=int(channels),
            dtype=str(dtype),
        ):
            return {
                "device": int(device),
                "samplerate": int(sr),
                "channels": int(channels),
                "dtype": str(dtype),
            }
    return None
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/resampler.py`

```python
from __future__ import annotations
from math import gcd
import numpy as np
from scipy.signal import resample_poly
class AudioResampler:
    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        g = gcd(self.src_rate, self.dst_rate)
        self.up = self.dst_rate // g
        self.down = self.src_rate // g
    def float_to_pcm16_bytes(self, audio: np.ndarray) -> bytes:
        clipped = np.clip(audio, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()
    def process_float_mono(self, audio: np.ndarray) -> bytes:
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio with shape (n,), got {audio.shape}")
        if self.src_rate == self.dst_rate:
            return self.float_to_pcm16_bytes(audio)
        y = resample_poly(audio, self.up, self.down).astype(np.float32, copy=False)
        return self.float_to_pcm16_bytes(y)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/soundcard_recorder.py`

```python
from __future__ import annotations
import threading
import time
from collections.abc import Callable
import numpy as np
import pythoncom
import soundcard as sc
from shadowing.interfaces.recorder import Recorder
from shadowing.realtime.capture.resampler import AudioResampler
class SoundCardRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        block_frames: int = 1440,
        include_loopback: bool = False,
        debug_level_meter: bool = False,
        debug_level_every_n_blocks: int = 20,
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.block_frames = max(128, int(block_frames))
        self.include_loopback = bool(include_loopback)
        self.debug_level_meter = bool(debug_level_meter)
        self.debug_level_every_n_blocks = max(1, int(debug_level_every_n_blocks))
        self._callback: Callable[[bytes], None] | None = None
        self._mic = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._opened_channels: int | None = None
        self._opened_samplerate: int | None = None
        self._debug_counter = 0
        self._resampler: AudioResampler | None = None
        self._last_error: Exception | None = None
    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._running:
            return
        self._callback = on_audio_frame
        self._mic = self._resolve_microphone(self.device, self.include_loopback)
        open_candidates = self._build_open_candidates()
        last_error: Exception | None = None
        for sr, ch in open_candidates:
            try:
                with self._mic.recorder(samplerate=sr, channels=ch) as rec:
                    _ = rec.record(numframes=min(self.block_frames, 256))
                self._opened_samplerate = int(sr)
                self._opened_channels = int(ch)
                self._resampler = AudioResampler(src_rate=self._opened_samplerate, dst_rate=self.target_sample_rate)
                last_error = None
                break
            except Exception as e:
                last_error = e
        if last_error is not None or self._opened_samplerate is None or self._opened_channels is None:
            msg = str(last_error)
            if "0x80070005" in msg:
                raise RuntimeError(
                    "Failed to open microphone with soundcard: access denied (0x80070005). Please enable Windows microphone privacy permissions and close apps using the mic."
                )
            raise RuntimeError(f"Failed to open microphone with soundcard. device={self.device!r}, last_error={last_error}")
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
    def stop(self) -> None:
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
    def close(self) -> None:
        self.stop()
    def _capture_loop(self) -> None:
        assert self._mic is not None
        assert self._callback is not None
        assert self._opened_samplerate is not None
        assert self._opened_channels is not None
        pythoncom.CoInitialize()
        try:
            with self._mic.recorder(samplerate=self._opened_samplerate, channels=self._opened_channels) as rec:
                while self._running:
                    data = rec.record(numframes=self.block_frames)
                    if data is None:
                        time.sleep(0.005)
                        continue
                    audio = np.asarray(data, dtype=np.float32)
                    if audio.ndim == 1:
                        audio = audio[:, None]
                    if audio.shape[1] > 1:
                        audio = np.mean(audio, axis=1, keepdims=True)
                    mono = np.squeeze(audio, axis=1).astype(np.float32, copy=False)
                    self._debug_counter += 1
                    if self.debug_level_meter and (self._debug_counter <= 3 or self._debug_counter % self.debug_level_every_n_blocks == 0):
                        _rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                        _peak = float(np.max(np.abs(mono))) if mono.size else 0.0
                    if self._resampler is None:
                        raise RuntimeError("SoundCardRecorder resampler is not initialized.")
                    pcm16_bytes = self._resampler.process_float_mono(mono)
                    self._callback(pcm16_bytes)
        except Exception as e:
            self._last_error = e
        finally:
            pythoncom.CoUninitialize()
            self._running = False
    def _build_open_candidates(self) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int]] = []
        candidate_srs: list[int] = []
        for sr in [self.sample_rate_in, 48000, 44100, 16000]:
            if sr > 0 and sr not in candidate_srs:
                candidate_srs.append(sr)
        candidate_channels: list[int] = []
        for ch in [1, self.channels, 2]:
            if ch > 0 and ch not in candidate_channels:
                candidate_channels.append(ch)
        for sr in candidate_srs:
            for ch in candidate_channels:
                candidates.append((int(sr), int(ch)))
        return candidates
    def _resolve_microphone(self, device: int | str | None, include_loopback: bool):
        mics = list(sc.all_microphones(include_loopback=include_loopback))
        if not mics:
            raise RuntimeError("No microphones found via soundcard.")
        if device is None:
            default_mic = sc.default_microphone()
            if default_mic is None:
                raise RuntimeError("No default microphone found via soundcard.")
            return default_mic
        if isinstance(device, int):
            if 0 <= device < len(mics):
                return mics[device]
            raise ValueError(
                f"Soundcard microphone index out of range: {device}. Valid range is 0..{len(mics) - 1}. Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )
        key = str(device).strip().lower()
        if key.isdigit():
            idx = int(key)
            if 0 <= idx < len(mics):
                return mics[idx]
            raise ValueError(
                f"Soundcard microphone index out of range: {idx}. Valid range is 0..{len(mics) - 1}. Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )
        for mic in mics:
            if key in mic.name.lower():
                return mic
        raise ValueError(
            f"No matching microphone found for {device!r}. For soundcard backend, pass either a soundcard microphone list index or a device name substring."
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/sounddevice_recorder.py`

```python
from __future__ import annotations
from collections.abc import Callable
from typing import Any
import numpy as np
import sounddevice as sd
from shadowing.interfaces.recorder import Recorder
from shadowing.realtime.capture.resampler import AudioResampler
class SoundDeviceRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        dtype: str = "float32",
        blocksize: int = 0,
        latency: str | float = "low",
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.dtype = dtype
        self.blocksize = int(blocksize)
        self.latency = latency
        self._stream: sd.InputStream | None = None
        self._callback: Callable[[bytes], None] | None = None
        self._opened_samplerate: int | None = None
        self._opened_channels: int | None = None
        self._resampler: AudioResampler | None = None
    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._stream is not None:
            return
        self._callback = on_audio_frame
        device = self._resolve_input_device(self.device)
        dev_info = sd.query_devices(device, "input")
        max_in = int(dev_info["max_input_channels"])
        if max_in < 1:
            raise RuntimeError(f"Invalid input device: {dev_info}")
        opened_channels = max(1, min(self.channels, max_in))
        sr = self._pick_openable_samplerate(device, dev_info, opened_channels)
        self._opened_samplerate = sr
        self._opened_channels = opened_channels
        self._resampler = AudioResampler(src_rate=sr, dst_rate=self.target_sample_rate)
        self._stream = sd.InputStream(
            samplerate=sr,
            blocksize=self.blocksize,
            device=device,
            channels=opened_channels,
            dtype=self.dtype,
            latency=self.latency,
            callback=self._audio_callback,
        )
        self._stream.start()
    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
    def close(self) -> None:
        self.stop()
    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if self._callback is None:
            return
        audio = np.asarray(indata, dtype=np.float32)
        if audio.ndim == 1:
            mono = audio
        else:
            mono = np.mean(audio, axis=1).astype(np.float32, copy=False)
        if self._resampler is None:
            raise RuntimeError("Recorder resampler is not initialized.")
        self._callback(self._resampler.process_float_mono(mono))
    def _resolve_input_device(self, device: int | str | None) -> int | str | None:
        if device is None:
            return None
        if isinstance(device, int):
            return device
        target = str(device).strip().lower()
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev["max_input_channels"]) > 0 and target in str(dev["name"]).lower():
                return idx
        raise ValueError(f"No matching input device found for {device!r}")
    def _pick_openable_samplerate(self, device: int | str | None, dev_info: Any, opened_channels: int) -> int:
        candidates: list[int] = []
        for sr in [self.sample_rate_in, int(float(dev_info["default_samplerate"])), 48000, 44100, 16000]:
            if sr > 0 and sr not in candidates:
                candidates.append(sr)
        for sr in candidates:
            try:
                sd.check_input_settings(
                    device=device,
                    samplerate=sr,
                    channels=opened_channels,
                    dtype=self.dtype,
                )
                return sr
            except Exception:
                continue
        raise RuntimeError(f"Failed to find openable samplerate for input device: {dev_info}")
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/policy.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass(slots=True)
class ControlPolicy:
    target_lead_sec: float = 0.18
    hold_if_lead_sec: float = 1.05
    resume_if_lead_sec: float = 0.36
    seek_if_lag_sec: float = -2.60
    min_confidence: float = 0.70
    seek_cooldown_sec: float = 2.20
    gain_following: float = 0.52
    gain_transition: float = 0.72
    gain_soft_duck: float = 0.36
    recover_after_seek_sec: float = 0.80
    startup_grace_sec: float = 3.20
    low_confidence_hold_sec: float = 2.20
    bootstrapping_sec: float = 2.20
    guide_play_sec: float = 3.20
    no_progress_hold_min_play_sec: float = 5.80
    speaking_recent_sec: float = 1.10
    progress_stale_sec: float = 1.45
    hold_trend_sec: float = 1.00
    hold_extra_lead_sec: float = 0.22
    low_confidence_continue_sec: float = 1.80
    tracking_quality_hold_min: float = 0.60
    tracking_quality_seek_min: float = 0.84
    resume_from_hold_event_fresh_sec: float = 0.60
    resume_from_hold_speaking_lead_slack_sec: float = 0.72
    reacquire_soft_duck_sec: float = 2.40
    disable_seek: bool = False
    bluetooth_long_session_target_lead_sec: float = 0.38
    bluetooth_long_session_hold_if_lead_sec: float = 1.35
    bluetooth_long_session_resume_if_lead_sec: float = 0.30
    bluetooth_long_session_seek_if_lag_sec: float = -3.20
    bluetooth_long_session_seek_cooldown_sec: float = 3.20
    bluetooth_long_session_progress_stale_sec: float = 1.75
    bluetooth_long_session_hold_trend_sec: float = 1.15
    bluetooth_long_session_tracking_quality_hold_min: float = 0.58
    bluetooth_long_session_tracking_quality_seek_min: float = 0.88
    bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec: float = 0.82
    bluetooth_long_session_gain_following: float = 0.50
    bluetooth_long_session_gain_transition: float = 0.66
    bluetooth_long_session_gain_soft_duck: float = 0.32
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/state_machine_controller.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.sync_evidence import SyncEvidence, SyncState, TrackingState
from shadowing.types import ControlAction, ControlDecision, FusionEvidence, PlaybackState
@dataclass(slots=True)
class _PressureState:
    hold_pressure: float = 0.0
    resume_pressure: float = 0.0
    seek_pressure: float = 0.0
    soft_duck_pressure: float = 0.0
    lead_error_ema: float = 0.0
    lead_error_derivative_ema: float = 0.0
    tracking_quality_ema: float = 0.0
    confidence_ema: float = 0.0
    speech_confidence_ema: float = 0.0
    last_tick_at: float = 0.0
    last_lead_error: float = 0.0
class StateMachineController:
    def __init__(
        self,
        *,
        policy: ControlPolicy,
        disable_seek: bool = False,
        debug: bool = False,
    ) -> None:
        self.policy = policy
        self.disable_seek = bool(disable_seek)
        self.debug = bool(debug)
        now = time.monotonic()
        self._started_at = now
        self._last_resume_at = now
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_soft_duck_at = 0.0
        self._last_voice_like_at = now
        self._last_effective_idx = 0
        self._pressure = _PressureState(last_tick_at=now)
    def reset(self) -> None:
        now = time.monotonic()
        self._started_at = now
        self._last_resume_at = now
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_soft_duck_at = 0.0
        self._last_voice_like_at = now
        self._last_effective_idx = 0
        self._pressure = _PressureState(last_tick_at=now)
    def decide(
        self,
        playback,
        progress,
        signal_quality,
        sync_evidence: SyncEvidence | None = None,
        fusion_evidence: FusionEvidence | None = None,
    ) -> ControlDecision:
        now = time.monotonic()
        fusion_still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        fusion_repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)
        fusion_reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)
        fusion_fused_conf = 0.0 if fusion_evidence is None else float(fusion_evidence.fused_confidence)
        if progress is None:
            if fusion_evidence is None or max(fusion_fused_conf, fusion_still_following, fusion_reentry) < 0.58:
                return ControlDecision(
                    action=ControlAction.NOOP,
                    reason="no_progress",
                    target_gain=self._gain_for_state(
                        playback.state,
                        following=False,
                        bluetooth_long_session_mode=False,
                    ),
                    confidence=0.0,
                )
            effective_idx = int(getattr(fusion_evidence, "estimated_ref_idx_hint", 0))
            tracking_quality = max(0.0, min(1.0, fusion_fused_conf * 0.84))
            confidence = fusion_fused_conf
            active_speaking = bool(fusion_still_following >= 0.60 or fusion_reentry >= 0.56)
            recently_progressed = False
            progress_age_sec = 9999.0
            estimated_ref_time_sec = float(fusion_evidence.estimated_ref_time_sec)
            stable = bool(fusion_fused_conf >= 0.72)
            position_source = "audio"
        else:
            effective_idx = int(getattr(progress, "estimated_ref_idx", 0))
            tracking_quality = float(getattr(progress, "tracking_quality", 0.0))
            confidence = float(getattr(progress, "confidence", 0.0))
            active_speaking = bool(getattr(progress, "active_speaking", False))
            recently_progressed = bool(getattr(progress, "recently_progressed", False))
            progress_age_sec = float(getattr(progress, "progress_age_sec", 9999.0))
            estimated_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
            stable = bool(getattr(progress, "stable", False))
            position_source = str(getattr(progress, "position_source", "text"))
        if active_speaking or recently_progressed or fusion_still_following >= 0.62 or fusion_reentry >= 0.56:
            self._last_voice_like_at = now
        if effective_idx > self._last_effective_idx:
            self._last_effective_idx = effective_idx
        speech_conf = 0.0
        tracking_state = TrackingState.NONE
        sync_state = SyncState.BOOTSTRAP
        allow_seek = False
        bluetooth_mode = False
        bluetooth_long_session_mode = False
        if sync_evidence is not None:
            speech_conf = float(sync_evidence.speech_confidence)
            tracking_state = sync_evidence.tracking_state
            sync_state = sync_evidence.sync_state
            allow_seek = bool(sync_evidence.allow_seek)
            bluetooth_mode = bool(sync_evidence.bluetooth_mode)
            bluetooth_long_session_mode = bool(sync_evidence.bluetooth_long_session_mode)
        target_lead_sec = (
            self.policy.bluetooth_long_session_target_lead_sec
            if bluetooth_long_session_mode
            else self.policy.target_lead_sec
        )
        hold_if_lead_sec = (
            self.policy.bluetooth_long_session_hold_if_lead_sec
            if bluetooth_long_session_mode
            else self.policy.hold_if_lead_sec
        )
        resume_if_lead_sec = (
            self.policy.bluetooth_long_session_resume_if_lead_sec
            if bluetooth_long_session_mode
            else self.policy.resume_if_lead_sec
        )
        seek_if_lag_sec = (
            self.policy.bluetooth_long_session_seek_if_lag_sec
            if bluetooth_long_session_mode
            else self.policy.seek_if_lag_sec
        )
        seek_cooldown_sec = (
            self.policy.bluetooth_long_session_seek_cooldown_sec
            if bluetooth_long_session_mode
            else self.policy.seek_cooldown_sec
        )
        progress_stale_threshold = (
            self.policy.bluetooth_long_session_progress_stale_sec
            if bluetooth_long_session_mode
            else self.policy.progress_stale_sec
        )
        tracking_quality_hold_min = (
            self.policy.bluetooth_long_session_tracking_quality_hold_min
            if bluetooth_long_session_mode
            else self.policy.tracking_quality_hold_min
        )
        tracking_quality_seek_min = (
            self.policy.bluetooth_long_session_tracking_quality_seek_min
            if bluetooth_long_session_mode
            else self.policy.tracking_quality_seek_min
        )
        resume_from_hold_speaking_lead_slack_sec = (
            self.policy.bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec
            if bluetooth_long_session_mode
            else self.policy.resume_from_hold_speaking_lead_slack_sec
        )
        in_startup_grace = (now - self._started_at) < (
            self.policy.startup_grace_sec + (1.2 if bluetooth_long_session_mode else 0.6)
        )
        in_resume_cooldown = (now - self._last_resume_at) < (0.70 if bluetooth_long_session_mode else 0.45)
        in_seek_cooldown = (now - self._last_seek_at) < seek_cooldown_sec
        in_soft_duck_cooldown = (now - self._last_soft_duck_at) < (0.45 if bluetooth_long_session_mode else 0.30)
        speaking_recent = (now - self._last_voice_like_at) <= (
            self.policy.speaking_recent_sec + (0.35 if bluetooth_long_session_mode else 0.15)
        )
        progress_stale = progress_age_sec >= progress_stale_threshold
        playback_ref = float(playback.t_ref_heard_content_sec)
        if fusion_evidence is not None and fusion_evidence.fused_confidence >= 0.60 and tracking_quality < 0.56:
            user_ref = float(fusion_evidence.estimated_ref_time_sec)
        else:
            user_ref = float(estimated_ref_time_sec)
        lead_sec = playback_ref - user_ref
        lead_error_sec = float(lead_sec - target_lead_sec)
        dt = max(0.01, now - self._pressure.last_tick_at)
        self._pressure.last_tick_at = now
        self._update_emas(
            dt=dt,
            lead_error_sec=lead_error_sec,
            tracking_quality=tracking_quality,
            confidence=confidence,
            speech_confidence=speech_conf,
        )
        engaged_recent = bool(
            speaking_recent
            or fusion_still_following >= 0.62
            or fusion_reentry >= 0.56
            or recently_progressed
            or (active_speaking and tracking_quality >= tracking_quality_hold_min - 0.08)
        )
        strong_resume_ok = bool(
            (
                recently_progressed
                or active_speaking
                or fusion_reentry >= 0.62
                or fusion_still_following >= 0.74
            )
            and tracking_quality >= tracking_quality_hold_min - 0.04
            and confidence >= self.policy.min_confidence - 0.14
            and lead_error_sec >= -resume_from_hold_speaking_lead_slack_sec
        )
        weak_resume_ok = bool(
            engaged_recent
            and tracking_quality >= tracking_quality_hold_min - 0.10
            and confidence >= max(0.48, self.policy.min_confidence - 0.22)
            and lead_error_sec >= -resume_from_hold_speaking_lead_slack_sec
        )
        following = bool(
            strong_resume_ok
            or weak_resume_ok
            or tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED)
            or fusion_still_following >= 0.72
        )
        self._update_pressures(
            dt=dt,
            playback_state=playback.state,
            lead_sec=lead_sec,
            lead_error_sec=lead_error_sec,
            progress_stale=progress_stale,
            tracking_quality=tracking_quality,
            confidence=confidence,
            stable=stable,
            speaking_recent=speaking_recent,
            engaged_recent=engaged_recent,
            in_startup_grace=in_startup_grace,
            strong_resume_ok=strong_resume_ok,
            weak_resume_ok=weak_resume_ok,
            in_resume_cooldown=in_resume_cooldown,
            in_seek_cooldown=in_seek_cooldown,
            allow_seek=allow_seek and (not self.disable_seek),
            tracking_state=tracking_state,
            sync_state=sync_state,
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=bluetooth_long_session_mode,
            hold_if_lead_sec=hold_if_lead_sec,
            resume_if_lead_sec=resume_if_lead_sec,
            seek_if_lag_sec=seek_if_lag_sec,
            tracking_quality_hold_min=tracking_quality_hold_min,
            tracking_quality_seek_min=tracking_quality_seek_min,
            fusion_evidence=fusion_evidence,
            position_source=position_source,
        )
        if fusion_evidence is not None:
            if fusion_evidence.should_prevent_hold:
                self._pressure.hold_pressure *= 0.12
            if fusion_evidence.should_prevent_seek:
                self._pressure.seek_pressure *= 0.08
            if playback.state == PlaybackState.HOLDING and (
                fusion_still_following >= 0.74 or fusion_reentry >= 0.60
            ):
                self._pressure.resume_pressure = max(
                    self._pressure.resume_pressure,
                    1.04 if bluetooth_long_session_mode else 1.02,
                )
        if playback.state == PlaybackState.HOLDING and self._pressure.resume_pressure >= 1.0:
            self._last_resume_at = now
            self._pressure.hold_pressure *= 0.25
            self._pressure.resume_pressure = 0.0
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="resume_on_engaged_user",
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.PLAYING,
                    following=True,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=max(confidence, fusion_still_following * 0.88, fusion_fused_conf * 0.84),
                aggressiveness="low",
            )
        if (
            playback.state == PlaybackState.PLAYING
            and self._pressure.soft_duck_pressure >= (0.58 if bluetooth_long_session_mode else 0.62)
            and not in_soft_duck_cooldown
        ):
            self._last_soft_duck_at = now
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="soft_duck_wait_for_user",
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.HOLDING,
                    following=False,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=max(confidence, fusion_still_following * 0.66, fusion_fused_conf * 0.60),
                aggressiveness="low",
            )
        if (
            playback.state == PlaybackState.PLAYING
            and self._pressure.hold_pressure >= 1.0
            and not engaged_recent
            and fusion_repeated < 0.60
            and fusion_reentry < 0.54
        ):
            self._last_hold_at = now
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="hold_when_user_disengaged",
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.HOLDING,
                    following=False,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=confidence,
                aggressiveness="low",
            )
        if (
            playback.state in (PlaybackState.PLAYING, PlaybackState.HOLDING)
            and self._pressure.seek_pressure >= 1.0
            and not self.disable_seek
            and allow_seek
            and not bluetooth_mode
            and fusion_repeated < 0.42
            and fusion_reentry < 0.42
            and not engaged_recent
            and (fusion_evidence is None or not fusion_evidence.should_prevent_seek)
        ):
            self._last_seek_at = now
            self._pressure.seek_pressure = 0.0
            self._pressure.hold_pressure *= 0.3
            target_time_sec = max(0.0, user_ref - target_lead_sec)
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="seek_only_when_clearly_derailed",
                target_time_sec=target_time_sec,
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.PLAYING,
                    following=False,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=max(confidence, 0.30 + 0.40 * fusion_still_following),
                aggressiveness="low",
            )
        return ControlDecision(
            action=ControlAction.NOOP,
            reason="follow_user_smoothly",
            lead_sec=lead_sec,
            target_gain=self._gain_for_state(
                playback.state,
                following=following,
                bluetooth_long_session_mode=bluetooth_long_session_mode,
            ),
            confidence=max(confidence, fusion_still_following * 0.56, fusion_fused_conf * 0.52),
            aggressiveness="low",
        )
    def _update_emas(
        self,
        *,
        dt: float,
        lead_error_sec: float,
        tracking_quality: float,
        confidence: float,
        speech_confidence: float,
    ) -> None:
        alpha = 0.22
        deriv = (float(lead_error_sec) - float(self._pressure.last_lead_error)) / max(0.01, float(dt))
        self._pressure.last_lead_error = float(lead_error_sec)
        self._pressure.lead_error_ema = (
            (1.0 - alpha) * self._pressure.lead_error_ema + alpha * float(lead_error_sec)
        )
        self._pressure.lead_error_derivative_ema = (
            (1.0 - alpha) * self._pressure.lead_error_derivative_ema + alpha * float(deriv)
        )
        self._pressure.tracking_quality_ema = (
            (1.0 - alpha) * self._pressure.tracking_quality_ema + alpha * float(tracking_quality)
        )
        self._pressure.confidence_ema = (
            (1.0 - alpha) * self._pressure.confidence_ema + alpha * float(confidence)
        )
        self._pressure.speech_confidence_ema = (
            (1.0 - alpha) * self._pressure.speech_confidence_ema + alpha * float(speech_confidence)
        )
    def _update_pressures(
        self,
        *,
        dt: float,
        playback_state,
        lead_sec: float,
        lead_error_sec: float,
        progress_stale: bool,
        tracking_quality: float,
        confidence: float,
        stable: bool,
        speaking_recent: bool,
        engaged_recent: bool,
        in_startup_grace: bool,
        strong_resume_ok: bool,
        weak_resume_ok: bool,
        in_resume_cooldown: bool,
        in_seek_cooldown: bool,
        allow_seek: bool,
        tracking_state: TrackingState,
        sync_state: SyncState,
        bluetooth_mode: bool,
        bluetooth_long_session_mode: bool,
        hold_if_lead_sec: float,
        resume_if_lead_sec: float,
        seek_if_lag_sec: float,
        tracking_quality_hold_min: float,
        tracking_quality_seek_min: float,
        fusion_evidence: FusionEvidence | None,
        position_source: str,
    ) -> None:
        decay = (0.88 if bluetooth_long_session_mode else 0.84) ** max(1.0, dt * 15.0)
        self._pressure.hold_pressure *= decay
        self._pressure.resume_pressure *= decay
        self._pressure.seek_pressure *= decay
        self._pressure.soft_duck_pressure *= decay
        fusion_still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        fusion_repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)
        fusion_reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)
        lead_err = float(self._pressure.lead_error_ema)
        lead_err_d = float(self._pressure.lead_error_derivative_ema)
        large_positive_error = lead_sec >= hold_if_lead_sec
        large_negative_error = lead_sec <= seek_if_lag_sec
        near_target = abs(lead_err) <= resume_if_lead_sec
        if playback_state == PlaybackState.PLAYING:
            if large_positive_error:
                self._pressure.soft_duck_pressure += 0.26 if bluetooth_long_session_mode else 0.30
                if (
                    lead_sec >= (hold_if_lead_sec + (0.28 if bluetooth_long_session_mode else 0.20))
                    and not engaged_recent
                    and not in_startup_grace
                ):
                    self._pressure.hold_pressure += 0.18 if bluetooth_long_session_mode else 0.24
            if lead_err > 0.12 and lead_err_d > 0.05 and not engaged_recent:
                self._pressure.soft_duck_pressure += 0.10
            if progress_stale and not engaged_recent and not in_startup_grace:
                self._pressure.soft_duck_pressure += 0.16 if bluetooth_long_session_mode else 0.20
                if tracking_quality < tracking_quality_hold_min - 0.04:
                    self._pressure.hold_pressure += 0.14 if bluetooth_long_session_mode else 0.18
            if tracking_state == TrackingState.WEAK or sync_state == SyncState.DEGRADED:
                if engaged_recent:
                    self._pressure.soft_duck_pressure += 0.10
                else:
                    self._pressure.soft_duck_pressure += 0.16 if bluetooth_long_session_mode else 0.20
            if confidence < max(0.50, self.policy.min_confidence - 0.18) and not engaged_recent:
                self._pressure.soft_duck_pressure += 0.08
            if stable and tracking_quality >= 0.78 and near_target:
                self._pressure.hold_pressure *= 0.90
                self._pressure.soft_duck_pressure *= 0.88
        if playback_state == PlaybackState.HOLDING and not in_resume_cooldown:
            if strong_resume_ok and near_target:
                self._pressure.resume_pressure += 0.44 if bluetooth_long_session_mode else 0.50
            elif strong_resume_ok:
                self._pressure.resume_pressure += 0.30
            elif weak_resume_ok and lead_err >= -0.16:
                self._pressure.resume_pressure += 0.24 if bluetooth_long_session_mode else 0.30
            if fusion_reentry >= 0.60:
                self._pressure.resume_pressure += 0.24
            elif fusion_still_following >= 0.74:
                self._pressure.resume_pressure += 0.18
            if near_target and speaking_recent:
                self._pressure.resume_pressure += 0.12
        seek_trigger = bool(
            allow_seek
            and not in_seek_cooldown
            and playback_state == PlaybackState.PLAYING
            and large_negative_error
            and tracking_quality >= tracking_quality_seek_min
            and confidence >= max(0.74, self.policy.min_confidence)
            and tracking_state == TrackingState.LOCKED
            and sync_state == SyncState.STABLE
            and fusion_repeated < 0.40
            and fusion_reentry < 0.40
            and position_source != "audio"
            and not engaged_recent
            and not bluetooth_mode
            and (fusion_evidence is None or not fusion_evidence.should_prevent_seek)
        )
        if seek_trigger:
            self._pressure.seek_pressure += 0.18
        self._pressure.hold_pressure = max(0.0, min(1.4, self._pressure.hold_pressure))
        self._pressure.resume_pressure = max(0.0, min(1.4, self._pressure.resume_pressure))
        self._pressure.seek_pressure = max(0.0, min(1.4, self._pressure.seek_pressure))
        self._pressure.soft_duck_pressure = max(0.0, min(1.2, self._pressure.soft_duck_pressure))
    def _gain_for_state(self, state, *, following: bool, bluetooth_long_session_mode: bool) -> float:
        if bluetooth_long_session_mode:
            if state == PlaybackState.HOLDING:
                return self.policy.bluetooth_long_session_gain_soft_duck
            if following:
                return self.policy.bluetooth_long_session_gain_following
            return self.policy.bluetooth_long_session_gain_transition
        if state == PlaybackState.HOLDING:
            return self.policy.gain_soft_duck
        if following:
            return self.policy.gain_following
        return self.policy.gain_transition
```

---
### 文件: `shadowing_app/src/shadowing/realtime/controller.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
def _f(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)
def _b(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
@dataclass(slots=True)
class ControlDecision:
    action: str
    reason: str
    target_gain: float
    seek_to_ref_time_sec: float | None = None
class PlaybackController:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self.target_lead_sec = _f(config.get("target_lead_sec"), 0.18)
        self.hold_if_lead_sec = _f(config.get("hold_if_lead_sec"), 1.05)
        self.resume_if_lead_sec = _f(config.get("resume_if_lead_sec"), 0.36)
        self.seek_if_lag_sec = _f(config.get("seek_if_lag_sec"), -2.60)
        self.min_confidence = _f(config.get("min_confidence"), 0.70)
        self.seek_cooldown_sec = _f(config.get("seek_cooldown_sec"), 2.20)
        self.gain_following = _f(config.get("gain_following"), 0.52)
        self.gain_transition = _f(config.get("gain_transition"), 0.72)
        self.gain_soft_duck = _f(config.get("gain_soft_duck"), 0.36)
        self.startup_grace_sec = _f(config.get("startup_grace_sec"), 3.2)
        self.low_confidence_hold_sec = _f(config.get("low_confidence_hold_sec"), 2.2)
        self.guide_play_sec = _f(config.get("guide_play_sec"), 3.20)
        self.no_progress_hold_min_play_sec = _f(config.get("no_progress_hold_min_play_sec"), 5.80)
        self.progress_stale_sec = _f(config.get("progress_stale_sec"), 1.45)
        self.hold_trend_sec = _f(config.get("hold_trend_sec"), 1.00)
        self.tracking_quality_hold_min = _f(config.get("tracking_quality_hold_min"), 0.60)
        self.tracking_quality_seek_min = _f(config.get("tracking_quality_seek_min"), 0.84)
        self.resume_from_hold_speaking_lead_slack_sec = _f(
            config.get("resume_from_hold_speaking_lead_slack_sec"),
            0.72,
        )
        self.disable_seek = _b(config.get("disable_seek"), False)
        self._started_at_sec = 0.0
        self._last_seek_at_sec = -999999.0
        self._hold_started_at_sec = 0.0
        self._is_holding = False
    def reset(self, *, started_at_sec: float) -> None:
        self._started_at_sec = float(started_at_sec)
        self._last_seek_at_sec = -999999.0
        self._hold_started_at_sec = 0.0
        self._is_holding = False
    def decide(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        progress_estimate,
        latency_state=None,
    ) -> ControlDecision:
        if progress_estimate is None:
            return ControlDecision(
                action="guide",
                reason="no_progress_estimate",
                target_gain=self.gain_transition,
            )
        est_ref_time_sec = _f(getattr(progress_estimate, "estimated_ref_time_sec", 0.0), 0.0)
        progress_age_sec = _f(getattr(progress_estimate, "progress_age_sec", 9999.0), 9999.0)
        joint_confidence = _f(getattr(progress_estimate, "joint_confidence", 0.0), 0.0)
        tracking_quality = _f(getattr(progress_estimate, "tracking_quality", 0.0), 0.0)
        active_speaking = bool(getattr(progress_estimate, "active_speaking", False))
        recently_progressed = bool(getattr(progress_estimate, "recently_progressed", False))
        user_state = str(getattr(progress_estimate, "user_state", "UNKNOWN"))
        position_source = str(getattr(progress_estimate, "position_source", "text"))
        target_lead_sec = self.target_lead_sec
        if latency_state is not None:
            target_lead_sec = _f(
                getattr(latency_state, "baseline_target_lead_sec", self.target_lead_sec),
                self.target_lead_sec,
            )
        lead_sec = _f(playback_ref_time_sec, 0.0) - est_ref_time_sec - target_lead_sec
        session_age_sec = max(0.0, float(now_sec) - self._started_at_sec)
        if session_age_sec <= self.startup_grace_sec:
            return ControlDecision(
                action="guide",
                reason="startup_grace",
                target_gain=self.gain_transition,
            )
        if joint_confidence < self.min_confidence:
            if progress_age_sec >= self.low_confidence_hold_sec:
                self._enter_hold(now_sec)
                return ControlDecision(
                    action="hold",
                    reason="low_confidence",
                    target_gain=0.0,
                )
            return ControlDecision(
                action="duck",
                reason="confidence_recovering",
                target_gain=self.gain_soft_duck,
            )
        if progress_age_sec >= self.progress_stale_sec:
            if active_speaking:
                self._enter_hold(now_sec)
                return ControlDecision(
                    action="hold",
                    reason="speaking_but_no_progress",
                    target_gain=0.0,
                )
            return ControlDecision(
                action="duck",
                reason="no_recent_progress",
                target_gain=self.gain_soft_duck,
            )
        if tracking_quality < self.tracking_quality_hold_min and active_speaking:
            self._enter_hold(now_sec)
            return ControlDecision(
                action="hold",
                reason="weak_tracking_while_speaking",
                target_gain=0.0,
            )
        if lead_sec >= self.hold_if_lead_sec and active_speaking:
            self._enter_hold(now_sec)
            return ControlDecision(
                action="hold",
                reason="lead_too_large",
                target_gain=0.0,
            )
        if (
            not self.disable_seek
            and lead_sec <= self.seek_if_lag_sec
            and tracking_quality >= self.tracking_quality_seek_min
            and joint_confidence >= self.min_confidence
            and (now_sec - self._last_seek_at_sec) >= self.seek_cooldown_sec
        ):
            self._last_seek_at_sec = float(now_sec)
            self._leave_hold()
            return ControlDecision(
                action="seek",
                reason="lag_too_large",
                target_gain=self.gain_transition,
                seek_to_ref_time_sec=max(0.0, est_ref_time_sec + target_lead_sec),
            )
        if self._is_holding:
            if (
                lead_sec <= self.resume_if_lead_sec + (self.resume_from_hold_speaking_lead_slack_sec if active_speaking else 0.0)
                and recently_progressed
                and tracking_quality >= self.tracking_quality_hold_min
            ):
                self._leave_hold()
                return ControlDecision(
                    action="resume",
                    reason="hold_released",
                    target_gain=self.gain_transition,
                )
            return ControlDecision(
                action="hold",
                reason="holding",
                target_gain=0.0,
            )
        if user_state in {"REJOINING", "HESITATING"}:
            return ControlDecision(
                action="duck",
                reason=f"user_state_{user_state.lower()}",
                target_gain=self.gain_soft_duck,
            )
        if user_state in {"FOLLOWING", "SKIPPING"} or position_source in {"joint", "audio"}:
            return ControlDecision(
                action="follow",
                reason="tracking_ok",
                target_gain=self.gain_following,
            )
        return ControlDecision(
            action="guide",
            reason="fallback",
            target_gain=self.gain_transition,
        )
    def _enter_hold(self, now_sec: float) -> None:
        if not self._is_holding:
            self._is_holding = True
            self._hold_started_at_sec = float(now_sec)
    def _leave_hold(self) -> None:
        self._is_holding = False
        self._hold_started_at_sec = 0.0
```

---
### 文件: `shadowing_app/src/shadowing/realtime/controller_legacy_adapter.py`

```python
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from typing import Any
from shadowing.realtime.controller import ControlDecision, PlaybackController
def _to_plain_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    out: dict[str, Any] = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        out[name] = value
    return out
class LegacyControllerAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.controller = PlaybackController(config=config)
    def reset(self, *, started_at_sec: float) -> None:
        self.controller.reset(started_at_sec=started_at_sec)
    def decide(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        progress_estimate,
        latency_state=None,
    ) -> dict[str, Any]:
        decision: ControlDecision = self.controller.decide(
            now_sec=now_sec,
            playback_ref_time_sec=playback_ref_time_sec,
            progress_estimate=progress_estimate,
            latency_state=latency_state,
        )
        payload = _to_plain_dict(decision)
        payload.setdefault("action", decision.action)
        payload.setdefault("reason", decision.reason)
        payload.setdefault("target_gain", decision.target_gain)
        payload.setdefault("seek_to_ref_time_sec", decision.seek_to_ref_time_sec)
        return payload
```

---
### 文件: `shadowing_app/src/shadowing/realtime/orchestrator.py`

```python
from __future__ import annotations
import json
import queue
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from shadowing.adaptation.profile_store import ProfileStore
from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner
from shadowing.audio.device_profile import DeviceProfile, build_device_profile
from shadowing.audio.frame_feature_extractor import FrameFeatureExtractor
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.audio_aware_progress_estimator import AudioAwareProgressEstimator
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.realtime.sync_evidence import SyncEvidenceBuilder
from shadowing.telemetry.event_logger import EventLogger
from shadowing.telemetry.metrics import MetricsAggregator
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.types import AsrEventType, PlaybackState, PlayerCommand, PlayerCommandType, ReferenceMap
@dataclass(slots=True)
class OrchestratorStats:
    audio_enqueued: int = 0
    audio_dropped: int = 0
    audio_q_high_watermark: int = 0
    raw_asr_events: int = 0
    normalized_asr_events: int = 0
    ticks: int = 0
    asr_frames_fed: int = 0
    asr_frames_skipped: int = 0
    asr_gate_open_count: int = 0
    asr_gate_close_count: int = 0
    asr_resets_from_silence: int = 0
class ShadowingOrchestrator:
    def __init__(
        self,
        *,
        repo,
        player,
        recorder,
        asr,
        aligner,
        controller,
        device_context: dict[str, Any] | None = None,
        signal_monitor: SignalQualityMonitor | None = None,
        latency_calibrator: LatencyCalibrator | None = None,
        auto_tuner: RuntimeAutoTuner | None = None,
        profile_store: ProfileStore | None = None,
        event_logger: EventLogger | None = None,
        reference_audio_store: ReferenceAudioStore | None = None,
        live_audio_matcher=None,
        audio_behavior_classifier=None,
        evidence_fuser=None,
        audio_queue_maxsize: int = 150,
        asr_event_queue_maxsize: int = 64,
        loop_interval_sec: float = 0.03,
        debug: bool = False,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller
        self.device_context = dict(device_context or {})
        self.signal_monitor = signal_monitor or SignalQualityMonitor()
        self.latency_calibrator = latency_calibrator or LatencyCalibrator()
        self.auto_tuner = auto_tuner or RuntimeAutoTuner()
        self.profile_store = profile_store
        self.event_logger = event_logger
        self.reference_audio_store = reference_audio_store
        self.live_audio_matcher = live_audio_matcher
        self.audio_behavior_classifier = audio_behavior_classifier
        self.evidence_fuser = evidence_fuser
        self.audio_queue: queue.Queue[tuple[float, bytes]] = queue.Queue(
            maxsize=max(16, int(audio_queue_maxsize))
        )
        self.loop_interval_sec = float(loop_interval_sec)
        self.debug = bool(debug)
        self.normalizer = TextNormalizer()
        self.tracking_engine = TrackingEngine(self.aligner, debug=debug)
        self.progress_estimator = AudioAwareProgressEstimator()
        self.metrics = MetricsAggregator()
        self.stats = OrchestratorStats()
        self.sync_builder = SyncEvidenceBuilder()
        self._lesson_id: str | None = None
        self._ref_map: ReferenceMap | None = None
        self._running = False
        self._last_generation = -1
        self._last_tracking_mode = None
        self._last_gain_sent: float | None = None
        self._last_control_action_key: tuple[str, str] | None = None
        self._device_profile: DeviceProfile | None = None
        self._warm_start: dict[str, Any] = {}
        self._session_started_at_sec = 0.0
        self._asr_gate_open = False
        self._asr_gate_last_open_at_sec = 0.0
        self._asr_gate_last_close_at_sec = 0.0
        self._last_human_voice_like_at_sec = 0.0
        self._last_asr_reset_at_sec = 0.0
        self._speech_open_rms = 0.0085
        self._speech_keep_rms = 0.0052
        self._speech_open_peak = 0.022
        self._speech_keep_peak = 0.014
        self._speech_open_likelihood = 0.50
        self._speech_keep_likelihood = 0.34
        self._speech_tail_hold_sec = 0.70
        self._asr_reset_after_silence_sec = 2.80
        self._asr_reset_cooldown_sec = 1.80
        self._reference_audio_features = None
        self._latest_audio_match = None
        self._latest_audio_behavior = None
        self._latest_fusion_evidence = None
        self._last_audio_recentering_at_sec = 0.0
        self._bluetooth_long_session_mode = False
        self._stable_lead_samples: list[float] = []
        self._last_stable_lead_rebaseline_at_sec = 0.0
        target_sr = 16000
        try:
            target_sr = int(getattr(self.asr, "sample_rate", 16000))
        except Exception:
            pass
        self._audio_feature_extractor = FrameFeatureExtractor(sample_rate=target_sr)
        _ = asr_event_queue_maxsize
    def configure_runtime(self, runtime_cfg: dict[str, Any]) -> None:
        if "loop_interval_sec" in runtime_cfg:
            self.loop_interval_sec = float(runtime_cfg["loop_interval_sec"])
    def configure_debug(self, debug_cfg: dict[str, Any]) -> None:
        self.debug = bool(debug_cfg.get("enabled", self.debug))
        self.tracking_engine.debug = self.debug
    def start_session(self, lesson_id: str) -> None:
        self._lesson_id = lesson_id
        self._ref_map = self.repo.load_reference_map(lesson_id)
        self.metrics = MetricsAggregator()
        self.stats = OrchestratorStats()
        self._warm_start = {}
        self.tracking_engine.reset(self._ref_map)
        self.progress_estimator.reset(self._ref_map, start_idx=0)
        self.controller.reset()
        self._audio_feature_extractor.reset()
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        chunks = self.repo.load_audio_chunks(lesson_id)
        self.player.load_chunks(chunks)
        self._session_started_at_sec = time.monotonic()
        self.sync_builder.reset(self._session_started_at_sec)
        self.metrics.mark_session_started(self._session_started_at_sec)
        self._last_generation = -1
        self._last_tracking_mode = None
        self._last_gain_sent = None
        self._last_control_action_key = None
        self._asr_gate_open = False
        self._asr_gate_last_open_at_sec = 0.0
        self._asr_gate_last_close_at_sec = self._session_started_at_sec
        self._last_human_voice_like_at_sec = 0.0
        self._last_asr_reset_at_sec = 0.0
        self._latest_audio_match = None
        self._latest_audio_behavior = None
        self._latest_fusion_evidence = None
        self._last_audio_recentering_at_sec = 0.0
        self._stable_lead_samples = []
        self._last_stable_lead_rebaseline_at_sec = self._session_started_at_sec
        output_sr = chunks[0].sample_rate if chunks else int(self.device_context.get("output_sample_rate", 44100))
        self._device_profile = self._build_initial_device_profile(output_sr)
        bluetooth_mode = bool(self._device_profile.bluetooth_mode) if self._device_profile is not None else False
        total_duration_sec = float(getattr(self._ref_map, "total_duration_sec", 0.0))
        manual_long_session_flag = bool(self.device_context.get("bluetooth_long_session_mode", False))
        self._bluetooth_long_session_mode = bool(
            bluetooth_mode and (manual_long_session_flag or total_duration_sec >= 1800.0)
        )
        if bluetooth_mode:
            self._speech_open_rms = 0.0072
            self._speech_keep_rms = 0.0045
            self._speech_open_peak = 0.018
            self._speech_keep_peak = 0.011
            self._speech_open_likelihood = 0.42
            self._speech_keep_likelihood = 0.28
            self._speech_tail_hold_sec = 1.20
            self._asr_reset_after_silence_sec = 4.20
            self._asr_reset_cooldown_sec = 2.60
        else:
            self._speech_open_rms = 0.0085
            self._speech_keep_rms = 0.0052
            self._speech_open_peak = 0.022
            self._speech_keep_peak = 0.014
            self._speech_open_likelihood = 0.50
            self._speech_keep_likelihood = 0.34
            self._speech_tail_hold_sec = 0.70
            self._asr_reset_after_silence_sec = 2.80
            self._asr_reset_cooldown_sec = 1.80
        self.latency_calibrator.reset(
            self._device_profile,
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=self._bluetooth_long_session_mode,
            now_sec=self._session_started_at_sec,
        )
        self.auto_tuner.reset(
            self._device_profile.reliability_tier,
            bluetooth_mode=bluetooth_mode,
        )
        if self.profile_store is not None and self._device_profile is not None:
            self._warm_start = self.profile_store.load_warm_start(
                input_device_id=self._device_profile.input_device_id,
                output_device_id=self._device_profile.output_device_id,
                hostapi_name=self._device_profile.hostapi_name,
                capture_backend=self._device_profile.capture_backend,
                duplex_sample_rate=int(self._device_profile.input_sample_rate),
                reliability_tier=self._device_profile.reliability_tier,
                bluetooth_mode=bluetooth_mode,
            )
            self.auto_tuner.apply_warm_start(
                controller_policy=self.controller.policy,
                player=self.player,
                signal_monitor=self.signal_monitor,
                warm_start=self._warm_start,
            )
            self._apply_latency_warm_start(self._warm_start)
        if self.reference_audio_store is not None and self.live_audio_matcher is not None:
            try:
                self._reference_audio_features = self.reference_audio_store.load(lesson_id)
            except Exception:
                self._reference_audio_features = None
            if self._reference_audio_features is not None:
                self.live_audio_matcher.reset(self._reference_audio_features, self._ref_map)
        if self.audio_behavior_classifier is not None:
            self.audio_behavior_classifier.reset()
        if self.evidence_fuser is not None:
            self.evidence_fuser.reset()
        try:
            self.asr.start()
            self.recorder.start(self._on_audio_frame)
            self.player.start()
        except Exception:
            self._safe_close_startup_resources()
            raise
        self._running = True
    def stop_session(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self.recorder.stop()
        except Exception:
            pass
        try:
            self.asr.close()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        self._persist_session_profile()
        self._persist_summary()
        try:
            self.player.close()
        except Exception:
            pass
        try:
            self.recorder.close()
        except Exception:
            pass
    def tick(self) -> None:
        if not self._running:
            return
        self.stats.ticks += 1
        self._drain_audio_queue()
        now_sec = time.monotonic()
        signal_snapshot = self.signal_monitor.snapshot(now_sec)
        if signal_snapshot.vad_active or signal_snapshot.speaking_likelihood >= 0.46:
            self.metrics.observe_signal_active(now_sec)
        playback_status = self.player.get_status()
        if playback_status.generation != self._last_generation:
            self._last_generation = playback_status.generation
            self.tracking_engine.on_playback_generation_changed(playback_status.generation)
            self.progress_estimator.on_playback_generation_changed(now_sec)
        raw_events = self.asr.poll_raw_events()
        self.stats.raw_asr_events += len(raw_events)
        last_tracking = None
        for raw_event in raw_events:
            if raw_event.event_type == AsrEventType.PARTIAL:
                self.metrics.observe_asr_partial(raw_event.emitted_at_sec)
            event = self.normalizer.normalize_raw_event(raw_event)
            if event is None:
                continue
            self.stats.normalized_asr_events += 1
            tracking = self.tracking_engine.update(event)
            last_tracking = tracking
            if tracking is None:
                continue
            if self._last_tracking_mode != tracking.tracking_mode:
                self.metrics.observe_tracking_mode(tracking.tracking_mode.value)
                self._last_tracking_mode = tracking.tracking_mode
            if self.event_logger is not None:
                self.event_logger.log(
                    "tracking_snapshot",
                    {
                        "candidate_ref_idx": tracking.candidate_ref_idx,
                        "committed_ref_idx": tracking.committed_ref_idx,
                        "candidate_ref_time_sec": tracking.candidate_ref_time_sec,
                        "tracking_mode": tracking.tracking_mode.value,
                        "overall_score": tracking.tracking_quality.overall_score,
                        "observation_score": tracking.tracking_quality.observation_score,
                        "temporal_consistency_score": tracking.tracking_quality.temporal_consistency_score,
                        "anchor_score": tracking.tracking_quality.anchor_score,
                        "is_reliable": tracking.tracking_quality.is_reliable,
                        "confidence": tracking.confidence,
                        "stable": tracking.stable,
                        "local_match_ratio": tracking.local_match_ratio,
                        "repeat_penalty": tracking.repeat_penalty,
                        "monotonic_consistency": tracking.monotonic_consistency,
                        "anchor_consistency": tracking.anchor_consistency,
                        "matched_text": tracking.matched_text,
                        "emitted_at_sec": tracking.emitted_at_sec,
                    },
                    ts_monotonic_sec=tracking.emitted_at_sec,
                    session_tick=self.stats.ticks,
                )
        audio_match = None
        if self.live_audio_matcher is not None:
            progress_hint = (
                None
                if self.progress_estimator._last_snapshot is None
                else float(self.progress_estimator._last_snapshot.estimated_ref_time_sec)
            )
            text_conf = (
                0.0
                if self.progress_estimator._last_snapshot is None
                else float(self.progress_estimator._last_snapshot.tracking_quality)
            )
            audio_match = self.live_audio_matcher.snapshot(
                now_sec=now_sec,
                progress_hint_ref_time_sec=progress_hint,
                playback_ref_time_sec=float(playback_status.t_ref_heard_content_sec),
                text_tracking_confidence=text_conf,
            )
            self._latest_audio_match = audio_match
        audio_behavior = None
        if self.audio_behavior_classifier is not None:
            audio_behavior = self.audio_behavior_classifier.update(
                audio_match=audio_match,
                signal_quality=signal_snapshot,
                progress=self.progress_estimator._last_snapshot,
                playback_status=playback_status,
            )
            self._latest_audio_behavior = audio_behavior
        progress = self.progress_estimator.update(
            tracking=last_tracking,
            audio_match=audio_match,
            audio_behavior=audio_behavior,
            signal_quality=signal_snapshot,
            now_sec=now_sec,
        )
        if progress is None:
            progress = self.progress_estimator.snapshot(
                now_sec=now_sec,
                signal_quality=signal_snapshot,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
            )
        if progress is not None:
            is_reliable = bool(
                progress.joint_confidence >= self.controller.policy.min_confidence
                and progress.tracking_quality >= self.controller.policy.tracking_quality_hold_min
            )
            self.metrics.observe_progress(
                now_sec=now_sec,
                tracking_quality=progress.tracking_quality,
                is_reliable=is_reliable,
            )
        fusion_evidence = None
        if self.evidence_fuser is not None:
            fusion_evidence = self.evidence_fuser.fuse(
                now_sec=now_sec,
                tracking=last_tracking,
                progress=progress,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
                signal_quality=signal_snapshot,
                playback_status=playback_status,
            )
            self._latest_fusion_evidence = fusion_evidence
        self._maybe_recenter_from_audio(now_sec=now_sec, fusion_evidence=fusion_evidence)
        sync_evidence = self.sync_builder.build(
            now_sec=now_sec,
            signal_quality=signal_snapshot,
            progress=progress,
            fusion_evidence=fusion_evidence,
            bluetooth_mode=self._is_bluetooth_mode(),
            bluetooth_long_session_mode=self._is_bluetooth_long_session_mode(),
        )
        if progress is not None:
            source_mode = str(getattr(progress, "position_source", "text"))
            source_is_text_dominant = source_mode == "text"
            audio_text_disagreement_sec = None
            if audio_match is not None:
                audio_text_disagreement_sec = float(
                    audio_match.estimated_ref_time_sec - progress.estimated_ref_time_sec
                )
            self.latency_calibrator.observe_sync(
                playback_ref_time_sec=playback_status.t_ref_heard_content_sec,
                user_ref_time_sec=progress.estimated_ref_time_sec,
                tracking_quality=progress.tracking_quality,
                stable=progress.stable,
                active_speaking=progress.active_speaking,
                allow_observation=sync_evidence.allow_latency_observation,
                source_is_text_dominant=source_is_text_dominant,
                source_mode=source_mode,
                audio_text_disagreement_sec=audio_text_disagreement_sec,
            )
        self._collect_stable_lead_samples(
            now_sec=now_sec,
            playback_status=playback_status,
            progress=progress,
            sync_evidence=sync_evidence,
        )
        self._maybe_rebaseline_output_offset(now_sec=now_sec)
        playback_status = self.player.get_status()
        decision = self.controller.decide(
            playback=playback_status,
            progress=progress,
            signal_quality=signal_snapshot,
            sync_evidence=sync_evidence,
            fusion_evidence=fusion_evidence,
        )
        self._apply_decision(decision, playback_status)
        self._run_auto_tuning(
            now_sec=now_sec,
            progress=progress,
            signal_snapshot=signal_snapshot,
        )
        self._log_event(
            progress=progress,
            signal_snapshot=signal_snapshot,
            decision=decision,
            sync_evidence=sync_evidence,
            audio_match=audio_match,
            audio_behavior=audio_behavior,
            fusion_evidence=fusion_evidence,
        )
    def _apply_latency_warm_start(self, warm_start: dict[str, Any]) -> None:
        latency = dict(warm_start.get("latency", {}))
        if not latency:
            return
        snap = self.latency_calibrator.snapshot()
        if snap is None:
            return
        stable_target_lead_sec = latency.get("stable_target_lead_sec")
        startup_target_lead_sec = latency.get("startup_target_lead_sec")
        if stable_target_lead_sec is not None:
            try:
                snap.baseline_target_lead_sec = float(stable_target_lead_sec)
            except Exception:
                pass
        if "estimated_output_latency_ms" in latency:
            try:
                snap.estimated_output_latency_ms = float(latency["estimated_output_latency_ms"])
            except Exception:
                pass
        if "estimated_input_latency_ms" in latency:
            try:
                snap.estimated_input_latency_ms = float(latency["estimated_input_latency_ms"])
            except Exception:
                pass
        if startup_target_lead_sec is not None and self._is_bluetooth_mode():
            try:
                self.latency_calibrator.target_shadow_lead_sec = float(startup_target_lead_sec)
            except Exception:
                pass
    def _collect_stable_lead_samples(self, *, now_sec: float, playback_status, progress, sync_evidence) -> None:
        if progress is None:
            return
        if not sync_evidence.allow_latency_observation:
            return
        if not progress.active_speaking:
            return
        if progress.tracking_quality < (0.70 if self._is_bluetooth_mode() else 0.76):
            return
        lead_sec = float(playback_status.t_ref_heard_content_sec) - float(progress.estimated_ref_time_sec)
        if abs(lead_sec) > 2.2:
            return
        self._stable_lead_samples.append(float(lead_sec))
        if len(self._stable_lead_samples) > 240:
            self._stable_lead_samples = self._stable_lead_samples[-240:]
    def _maybe_rebaseline_output_offset(self, *, now_sec: float) -> None:
        if self._is_bluetooth_long_session_mode():
            refresh_gap = 180.0
            need_n = 24
            desired = 0.35
        elif self._is_bluetooth_mode():
            refresh_gap = 120.0
            need_n = 20
            desired = 0.28
        else:
            refresh_gap = 240.0
            need_n = 28
            desired = 0.15
        if (now_sec - self._last_stable_lead_rebaseline_at_sec) < refresh_gap:
            return
        if len(self._stable_lead_samples) < need_n:
            return
        vals = sorted(self._stable_lead_samples)
        mid = vals[len(vals) // 2]
        error_sec = float(mid - desired)
        if abs(error_sec) < 0.040:
            self._last_stable_lead_rebaseline_at_sec = now_sec
            self._stable_lead_samples.clear()
            return
        snap = self.latency_calibrator.snapshot()
        if snap is None:
            return
        new_output_offset_sec = max(
            0.0,
            (
                snap.estimated_output_latency_ms
                + snap.runtime_output_drift_ms
                - error_sec * 1000.0
            )
            / 1000.0,
        )
        if hasattr(self.player, "set_output_offset_sec"):
            self.player.set_output_offset_sec(new_output_offset_sec)
        self._last_stable_lead_rebaseline_at_sec = now_sec
        self._stable_lead_samples.clear()
    def _maybe_recenter_from_audio(self, *, now_sec: float, fusion_evidence) -> None:
        if fusion_evidence is None:
            return
        if (now_sec - self._last_audio_recentering_at_sec) < 0.45:
            return
        if not (
            fusion_evidence.should_recenter_aligner_window
            or fusion_evidence.should_widen_reacquire_window
        ):
            return
        ref_idx_hint = int(getattr(fusion_evidence, "estimated_ref_idx_hint", 0))
        if fusion_evidence.should_widen_reacquire_window:
            back, ahead, budget = 18, 40, 8
        else:
            back, ahead, budget = 10, 24, 6
        self.tracking_engine.recenter_from_audio(
            ref_idx_hint=ref_idx_hint,
            search_back=back,
            search_ahead=ahead,
            budget_events=budget,
        )
        self._last_audio_recentering_at_sec = float(now_sec)
        if self.event_logger is not None:
            self.event_logger.log(
                "audio_recentering",
                {
                    "estimated_ref_idx_hint": ref_idx_hint,
                    "estimated_ref_time_sec": float(
                        getattr(fusion_evidence, "estimated_ref_time_sec", 0.0)
                    ),
                    "audio_confidence": float(getattr(fusion_evidence, "audio_confidence", 0.0)),
                    "fused_confidence": float(getattr(fusion_evidence, "fused_confidence", 0.0)),
                    "should_recenter_aligner_window": bool(
                        getattr(fusion_evidence, "should_recenter_aligner_window", False)
                    ),
                    "should_widen_reacquire_window": bool(
                        getattr(fusion_evidence, "should_widen_reacquire_window", False)
                    ),
                },
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
    def _on_audio_frame(self, pcm_bytes: bytes) -> None:
        item = (time.monotonic(), pcm_bytes)
        try:
            self.audio_queue.put_nowait(item)
            self.stats.audio_enqueued += 1
            self.stats.audio_q_high_watermark = max(
                self.stats.audio_q_high_watermark,
                self.audio_queue.qsize(),
            )
        except queue.Full:
            try:
                _ = self.audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_queue.put_nowait(item)
            except queue.Full:
                pass
            self.stats.audio_dropped += 1
    def _drain_audio_queue(self) -> None:
        while True:
            try:
                observed_at_sec, pcm_bytes = self.audio_queue.get_nowait()
            except queue.Empty:
                break
            self.signal_monitor.feed_pcm16(pcm_bytes, observed_at_sec)
            signal_snapshot = self.signal_monitor.snapshot(observed_at_sec)
            self.latency_calibrator.observe_signal(signal_snapshot)
            if self.live_audio_matcher is not None:
                feat_frames = self._audio_feature_extractor.process_pcm16(
                    pcm_bytes,
                    observed_at_sec=observed_at_sec,
                )
                self.live_audio_matcher.feed_features(feat_frames)
            bootstrap_mode = (observed_at_sec - self._session_started_at_sec) <= 4.0
            bluetooth_mode = self._is_bluetooth_mode()
            should_feed_asr = self._should_feed_asr(
                signal_snapshot=signal_snapshot,
                now_sec=observed_at_sec,
                bootstrap_mode=bootstrap_mode,
                bluetooth_mode=bluetooth_mode,
            )
            if should_feed_asr:
                self.asr.feed_pcm16(pcm_bytes)
                self.stats.asr_frames_fed += 1
            else:
                self.stats.asr_frames_skipped += 1
                self._maybe_reset_asr_for_silence(
                    signal_snapshot=signal_snapshot,
                    now_sec=observed_at_sec,
                    bootstrap_mode=bootstrap_mode,
                    bluetooth_mode=bluetooth_mode,
                )
    def _should_feed_asr(
        self,
        *,
        signal_snapshot,
        now_sec: float,
        bootstrap_mode: bool,
        bluetooth_mode: bool,
    ) -> bool:
        open_rms = 0.0070 if bluetooth_mode else (0.0078 if bootstrap_mode else self._speech_open_rms)
        open_peak = 0.017 if bluetooth_mode else (0.020 if bootstrap_mode else self._speech_open_peak)
        open_likelihood = 0.40 if bluetooth_mode else (0.44 if bootstrap_mode else self._speech_open_likelihood)
        strong_voice = bool(
            signal_snapshot.vad_active
            and signal_snapshot.rms >= open_rms
            and signal_snapshot.peak >= open_peak
        )
        likely_voice = bool(
            signal_snapshot.speaking_likelihood >= open_likelihood
            and signal_snapshot.rms >= self._speech_keep_rms
        )
        keep_voice = bool(
            signal_snapshot.vad_active
            and signal_snapshot.rms >= self._speech_keep_rms
            and signal_snapshot.peak >= self._speech_keep_peak
        ) or bool(
            signal_snapshot.speaking_likelihood >= self._speech_keep_likelihood
            and signal_snapshot.peak >= self._speech_keep_peak
        )
        if strong_voice or likely_voice:
            self._last_human_voice_like_at_sec = float(now_sec)
        gate_should_open = strong_voice or likely_voice
        gate_tail_sec = 1.25 if bluetooth_mode else (0.95 if bootstrap_mode else self._speech_tail_hold_sec)
        gate_should_keep = False
        if self._asr_gate_open and self._last_human_voice_like_at_sec > 0.0:
            gate_should_keep = keep_voice or (
                (now_sec - self._last_human_voice_like_at_sec) <= gate_tail_sec
            )
        new_gate_state = gate_should_open or gate_should_keep
        if new_gate_state and not self._asr_gate_open:
            self._asr_gate_open = True
            self._asr_gate_last_open_at_sec = float(now_sec)
            self.stats.asr_gate_open_count += 1
        elif (not new_gate_state) and self._asr_gate_open:
            self._asr_gate_open = False
            self._asr_gate_last_close_at_sec = float(now_sec)
            self.stats.asr_gate_close_count += 1
        return self._asr_gate_open
    def _maybe_reset_asr_for_silence(
        self,
        *,
        signal_snapshot,
        now_sec: float,
        bootstrap_mode: bool,
        bluetooth_mode: bool,
    ) -> None:
        if self._asr_gate_open or bootstrap_mode or bluetooth_mode:
            return
        recently_had_voice = (
            self._last_human_voice_like_at_sec > 0.0
            and (now_sec - self._last_human_voice_like_at_sec) <= self._asr_reset_after_silence_sec
        )
        if recently_had_voice:
            return
        recently_reset = (
            self._last_asr_reset_at_sec > 0.0
            and (now_sec - self._last_asr_reset_at_sec) <= self._asr_reset_cooldown_sec
        )
        if recently_reset:
            return
        very_quiet = bool(
            signal_snapshot.rms <= self._speech_keep_rms
            and signal_snapshot.peak <= self._speech_keep_peak
            and signal_snapshot.speaking_likelihood <= 0.18
        )
        if not very_quiet:
            return
        try:
            self.asr.reset()
            self._last_asr_reset_at_sec = float(now_sec)
            self.stats.asr_resets_from_silence += 1
        except Exception:
            pass
    def _apply_decision(self, decision, playback_status) -> None:
        action_key = (decision.action.value, decision.reason)
        should_count = action_key != self._last_control_action_key
        self._last_control_action_key = action_key
        if decision.action.value == "hold":
            if playback_status.state != PlaybackState.HOLDING:
                self.player.submit_command(
                    PlayerCommand(cmd=PlayerCommandType.HOLD, reason=decision.reason)
                )
                if should_count:
                    self.metrics.observe_action("hold", decision.reason, time.monotonic())
        elif decision.action.value == "resume":
            if playback_status.state == PlaybackState.HOLDING:
                self.player.submit_command(
                    PlayerCommand(cmd=PlayerCommandType.RESUME, reason=decision.reason)
                )
                if should_count:
                    self.metrics.observe_action("resume", decision.reason, time.monotonic())
        elif decision.action.value == "seek" and decision.target_time_sec is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SEEK,
                    target_time_sec=float(decision.target_time_sec),
                    reason=decision.reason,
                )
            )
            if should_count:
                self.metrics.observe_action("seek", decision.reason, time.monotonic())
        elif decision.action.value == "soft_duck" and should_count:
            self.metrics.observe_action("soft_duck", decision.reason, time.monotonic())
        desired_gain = decision.target_gain
        if desired_gain is not None:
            if self._last_gain_sent is None or abs(float(desired_gain) - float(self._last_gain_sent)) >= 0.01:
                self.player.submit_command(
                    PlayerCommand(
                        cmd=PlayerCommandType.SET_GAIN,
                        gain=float(desired_gain),
                        reason=decision.reason,
                    )
                )
                self._last_gain_sent = float(desired_gain)
    def _run_auto_tuning(self, *, now_sec: float, progress, signal_snapshot) -> None:
        metrics_summary = self.metrics.summary_dict()
        latency_snapshot = self.latency_calibrator.snapshot()
        self.auto_tuner.maybe_tune(
            now_sec=now_sec,
            controller_policy=self.controller.policy,
            player=self.player,
            signal_monitor=self.signal_monitor,
            metrics_summary=metrics_summary,
            signal_quality=signal_snapshot,
            progress=progress,
            latency_snapshot=latency_snapshot,
            device_profile=asdict(self._device_profile) if self._device_profile is not None else {},
        )
    def _persist_session_profile(self) -> None:
        if self.profile_store is None or self._device_profile is None:
            return
        latency_snapshot = self.latency_calibrator.snapshot()
        self.profile_store.update_from_session(
            input_device_id=self._device_profile.input_device_id,
            output_device_id=self._device_profile.output_device_id,
            hostapi_name=self._device_profile.hostapi_name,
            capture_backend=self._device_profile.capture_backend,
            duplex_sample_rate=int(self._device_profile.input_sample_rate),
            bluetooth_mode=bool(self._device_profile.bluetooth_mode),
            device_profile=asdict(self._device_profile),
            metrics=self.metrics.summary_dict(),
            latency_calibration=(
                None
                if latency_snapshot is None
                else {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "runtime_input_drift_ms": latency_snapshot.runtime_input_drift_ms,
                    "runtime_output_drift_ms": latency_snapshot.runtime_output_drift_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                    "stable_target_lead_sec": (
                        0.35 if self._bluetooth_long_session_mode
                        else (0.28 if self._is_bluetooth_mode() else 0.15)
                    ),
                    "startup_target_lead_sec": (
                        0.28 if self._is_bluetooth_mode() else 0.15
                    ),
                }
            ),
        )
    def _persist_summary(self) -> None:
        raw_session_dir = str(self.device_context.get("session_dir", "")).strip()
        if not raw_session_dir:
            return
        session_dir = Path(raw_session_dir).expanduser().resolve()
        session_dir.mkdir(parents=True, exist_ok=True)
        latency_snapshot = self.latency_calibrator.snapshot()
        summary = {
            "lesson_id": self._lesson_id,
            "metrics": self.metrics.summary_dict(),
            "stats": asdict(self.stats),
            "device_profile": None if self._device_profile is None else asdict(self._device_profile),
            "device_context": dict(self.device_context),
            "latency_calibration": (
                None
                if latency_snapshot is None
                else {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "runtime_input_drift_ms": latency_snapshot.runtime_input_drift_ms,
                    "runtime_output_drift_ms": latency_snapshot.runtime_output_drift_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                    "baseline_target_lead_sec": latency_snapshot.baseline_target_lead_sec,
                }
            ),
            "controller_policy": asdict(self.controller.policy),
            "latest_audio_match": None if self._latest_audio_match is None else asdict(self._latest_audio_match),
            "latest_audio_behavior": None if self._latest_audio_behavior is None else asdict(self._latest_audio_behavior),
            "latest_fusion_evidence": None if self._latest_fusion_evidence is None else asdict(self._latest_fusion_evidence),
            "bluetooth_long_session_mode": self._bluetooth_long_session_mode,
            "stable_lead_samples_count": len(self._stable_lead_samples),
        }
        (session_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.event_logger is not None:
            self.event_logger.log(
                "session_summary",
                summary,
                ts_monotonic_sec=time.monotonic(),
                session_tick=self.stats.ticks,
            )
    def _log_event(
        self,
        *,
        progress,
        signal_snapshot,
        decision,
        sync_evidence,
        audio_match,
        audio_behavior,
        fusion_evidence,
    ) -> None:
        if self.event_logger is None:
            return
        now_sec = time.monotonic()
        self.event_logger.log(
            "signal_snapshot",
            {
                "rms": signal_snapshot.rms,
                "peak": signal_snapshot.peak,
                "vad_active": signal_snapshot.vad_active,
                "speaking_likelihood": signal_snapshot.speaking_likelihood,
                "quality_score": signal_snapshot.quality_score,
                "dropout_detected": signal_snapshot.dropout_detected,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )
        if progress is not None:
            self.event_logger.log(
                "progress_snapshot",
                {
                    "estimated_ref_idx": progress.estimated_ref_idx,
                    "estimated_ref_time_sec": progress.estimated_ref_time_sec,
                    "progress_age_sec": progress.progress_age_sec,
                    "tracking_mode": progress.tracking_mode.value,
                    "tracking_quality": progress.tracking_quality,
                    "confidence": progress.confidence,
                    "joint_confidence": progress.joint_confidence,
                    "audio_confidence": progress.audio_confidence,
                    "position_source": progress.position_source,
                    "active_speaking": progress.active_speaking,
                    "recently_progressed": progress.recently_progressed,
                    "user_state": progress.user_state.value,
                },
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        self.event_logger.log(
            "sync_evidence",
            {
                "speech_state": sync_evidence.speech_state.value,
                "tracking_state": sync_evidence.tracking_state.value,
                "sync_state": sync_evidence.sync_state.value,
                "speech_confidence": sync_evidence.speech_confidence,
                "tracking_confidence": sync_evidence.tracking_confidence,
                "sync_confidence": sync_evidence.sync_confidence,
                "allow_latency_observation": sync_evidence.allow_latency_observation,
                "allow_seek": sync_evidence.allow_seek,
                "startup_mode": sync_evidence.startup_mode,
                "bluetooth_mode": sync_evidence.bluetooth_mode,
                "bluetooth_long_session_mode": sync_evidence.bluetooth_long_session_mode,
                "audio_confidence": sync_evidence.audio_confidence,
                "still_following_likelihood": sync_evidence.still_following_likelihood,
                "reentry_likelihood": sync_evidence.reentry_likelihood,
                "repeated_likelihood": sync_evidence.repeated_likelihood,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )
        if audio_match is not None:
            self.event_logger.log(
                "audio_match_snapshot",
                asdict(audio_match),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        if audio_behavior is not None:
            self.event_logger.log(
                "audio_behavior_snapshot",
                asdict(audio_behavior),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        if fusion_evidence is not None:
            self.event_logger.log(
                "fusion_evidence",
                asdict(fusion_evidence),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        self.event_logger.log(
            "control_decision",
            {
                "action": decision.action.value,
                "reason": decision.reason,
                "target_time_sec": decision.target_time_sec,
                "lead_sec": decision.lead_sec,
                "target_gain": decision.target_gain,
                "confidence": decision.confidence,
                "aggressiveness": decision.aggressiveness,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )
    def _build_initial_device_profile(self, output_sr: int) -> DeviceProfile:
        input_device_name = str(self.device_context.get("input_device_name", "unknown") or "unknown")
        output_device_name = str(self.device_context.get("output_device_name", "unknown") or "unknown")
        hostapi_name = str(self.device_context.get("hostapi_name", "") or "").strip()
        capture_backend = str(self.device_context.get("capture_backend", "") or "").strip().lower()
        input_device_id = str(self.device_context.get("input_device_id", "") or "").strip()
        output_device_id = str(self.device_context.get("output_device_id", "") or "").strip()
        input_sample_rate = self._safe_int(self.device_context.get("input_sample_rate", 16000), 16000)
        noise_floor_rms = self._safe_float(self.device_context.get("noise_floor_rms", 0.0025), 0.0025)
        return build_device_profile(
            input_device_name=input_device_name,
            output_device_name=output_device_name,
            input_sample_rate=input_sample_rate,
            output_sample_rate=int(output_sr),
            noise_floor_rms=noise_floor_rms,
            hostapi_name=hostapi_name,
            capture_backend=capture_backend,
            input_device_id=input_device_id or None,
            output_device_id=output_device_id or None,
        )
    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)
    def _safe_float(self, value: Any, default: float) -> float:
        try:
            out = float(value)
        except Exception:
            return float(default)
        if out != out:
            return float(default)
        return float(out)
    def _is_bluetooth_mode(self) -> bool:
        profile = self._device_profile
        if profile is None:
            return False
        return bool(profile.bluetooth_mode)
    def _is_bluetooth_long_session_mode(self) -> bool:
        return bool(self._bluetooth_long_session_mode)
    def _safe_close_startup_resources(self) -> None:
        try:
            self.recorder.stop()
        except Exception:
            pass
        try:
            self.recorder.close()
        except Exception:
            pass
        try:
            self.asr.close()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.player.close()
        except Exception:
            pass
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/chunk_queue.py`

```python
from __future__ import annotations
from bisect import bisect_right
import numpy as np
from shadowing.types import AudioChunk
class ChunkQueue:
    def __init__(self) -> None:
        self._chunks: list[AudioChunk] = []
        self._chunk_start_times: list[float] = []
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0
        self._sample_rate = 0
        self._total_duration_sec = 0.0
    def load(self, chunks: list[AudioChunk]) -> None:
        self._chunks = chunks
        self._chunk_start_times = [c.start_time_sec for c in chunks]
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0
        self._sample_rate = chunks[0].sample_rate if chunks else 0
        if chunks and any(c.sample_rate != self._sample_rate for c in chunks):
            raise ValueError("All playback chunks must share the same sample rate.")
        if chunks:
            last = chunks[-1]
            self._total_duration_sec = last.start_time_sec + last.duration_sec
        else:
            self._total_duration_sec = 0.0
    @property
    def current_chunk_id(self) -> int:
        if not self._chunks:
            return -1
        if self._current_chunk_idx >= len(self._chunks):
            return self._chunks[-1].chunk_id
        return self._chunks[self._current_chunk_idx].chunk_id
    @property
    def current_frame_index(self) -> int:
        return self._frame_offset_in_chunk
    def is_finished(self) -> bool:
        return bool(self._chunks) and self._current_chunk_idx >= len(self._chunks)
    def seek(self, target_time_sec: float) -> None:
        if not self._chunks:
            return
        idx = bisect_right(self._chunk_start_times, target_time_sec) - 1
        idx = max(0, min(idx, len(self._chunks) - 1))
        chunk = self._chunks[idx]
        local_time = max(0.0, target_time_sec - chunk.start_time_sec)
        local_frame = int(local_time * chunk.sample_rate)
        local_frame = min(local_frame, chunk.samples.shape[0])
        self._current_chunk_idx = idx
        self._frame_offset_in_chunk = local_frame
    def get_content_time_sec(self) -> float:
        if not self._chunks:
            return 0.0
        if self._current_chunk_idx >= len(self._chunks):
            return self._total_duration_sec
        chunk = self._chunks[self._current_chunk_idx]
        return chunk.start_time_sec + (self._frame_offset_in_chunk / chunk.sample_rate)
    def read_frames(self, frames: int, channels: int = 1) -> np.ndarray:
        out = np.zeros((frames, channels), dtype=np.float32)
        if not self._chunks or self.is_finished():
            return out
        written = 0
        while written < frames and self._current_chunk_idx < len(self._chunks):
            chunk = self._chunks[self._current_chunk_idx]
            remain = chunk.samples.shape[0] - self._frame_offset_in_chunk
            take = min(remain, frames - written)
            if take > 0:
                data = chunk.samples[self._frame_offset_in_chunk : self._frame_offset_in_chunk + take]
                if data.ndim == 1:
                    out[written : written + take, 0] = data
                else:
                    out[written : written + take, : data.shape[1]] = data
                self._frame_offset_in_chunk += take
                written += take
            if self._frame_offset_in_chunk >= chunk.samples.shape[0]:
                self._current_chunk_idx += 1
                self._frame_offset_in_chunk = 0
        return out
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/command_queue.py`

```python
from __future__ import annotations
import queue
from dataclasses import dataclass
from shadowing.types import PlayerCommand, PlayerCommandType
@dataclass(slots=True)
class MergedPlayerCommands:
    state_cmd: PlayerCommand | None = None
    seek_cmd: PlayerCommand | None = None
    gain_cmd: PlayerCommand | None = None
class PlayerCommandQueue:
    def __init__(self, maxsize: int = 64) -> None:
        self._queue: queue.Queue[PlayerCommand] = queue.Queue(maxsize=maxsize)
    def put(self, cmd: PlayerCommand) -> None:
        try:
            self._queue.put_nowait(cmd)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(cmd)
    def drain_merged(self) -> MergedPlayerCommands:
        merged = MergedPlayerCommands()
        while True:
            try:
                cmd = self._queue.get_nowait()
            except queue.Empty:
                break
            if cmd.cmd == PlayerCommandType.SET_GAIN:
                merged.gain_cmd = cmd
                continue
            if cmd.cmd == PlayerCommandType.SEEK:
                merged.seek_cmd = cmd
                continue
            if cmd.cmd == PlayerCommandType.STOP:
                merged.state_cmd = cmd
                continue
            if merged.state_cmd is None or merged.state_cmd.cmd != PlayerCommandType.STOP:
                merged.state_cmd = cmd
        return merged
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/playback_clock.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass(slots=True)
class PlaybackClockSnapshot:
    t_host_output_sec: float
    t_ref_block_start_content_sec: float
    t_ref_block_end_content_sec: float
    t_ref_emitted_content_sec: float
    t_ref_heard_content_sec: float
class PlaybackClock:
    def __init__(self, bluetooth_output_offset_sec: float = 0.0) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(bluetooth_output_offset_sec))
        self._last_emitted_content_sec = 0.0
        self._last_heard_content_sec = 0.0
        self._last_host_output_sec = 0.0
    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(offset_sec))
    def compute(
        self,
        output_buffer_dac_time_sec: float,
        block_start_content_sec: float,
        block_end_content_sec: float,
    ) -> PlaybackClockSnapshot:
        start_sec = float(block_start_content_sec)
        end_sec = float(block_end_content_sec)
        if end_sec < start_sec:
            end_sec = start_sec
        emitted_mid_sec = (start_sec + end_sec) * 0.5
        heard_mid_sec = emitted_mid_sec + self.bluetooth_output_offset_sec
        if output_buffer_dac_time_sec >= self._last_host_output_sec:
            emitted_mid_sec = max(emitted_mid_sec, self._last_emitted_content_sec)
            heard_mid_sec = max(heard_mid_sec, self._last_heard_content_sec)
        self._last_host_output_sec = float(output_buffer_dac_time_sec)
        self._last_emitted_content_sec = float(emitted_mid_sec)
        self._last_heard_content_sec = float(heard_mid_sec)
        return PlaybackClockSnapshot(
            t_host_output_sec=float(output_buffer_dac_time_sec),
            t_ref_block_start_content_sec=start_sec,
            t_ref_block_end_content_sec=end_sec,
            t_ref_emitted_content_sec=float(emitted_mid_sec),
            t_ref_heard_content_sec=float(heard_mid_sec),
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/sounddevice_player.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from math import gcd
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from shadowing.interfaces.player import Player
from shadowing.realtime.playback.chunk_queue import ChunkQueue
from shadowing.realtime.playback.command_queue import PlayerCommandQueue
from shadowing.realtime.playback.playback_clock import PlaybackClock
from shadowing.types import (
    AudioChunk,
    PlaybackState,
    PlaybackStatus,
    PlayerCommand,
    PlayerCommandType,
)
@dataclass(slots=True)
class PlaybackConfig:
    sample_rate: int
    channels: int
    device: int | str | None = None
    latency: str | float = "low"
    blocksize: int = 0
    bluetooth_output_offset_sec: float = 0.0
class _OutputResampler:
    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        g = gcd(self.src_rate, self.dst_rate)
        self.up = self.dst_rate // g
        self.down = self.src_rate // g
    def process(self, audio: np.ndarray) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2D audio array, got shape={arr.shape}")
        if self.src_rate == self.dst_rate or arr.shape[0] == 0:
            return arr.astype(np.float32, copy=False)
        channels = arr.shape[1]
        pieces: list[np.ndarray] = []
        for ch in range(channels):
            y = resample_poly(arr[:, ch], self.up, self.down).astype(
                np.float32,
                copy=False,
            )
            pieces.append(y)
        min_len = min(piece.shape[0] for piece in pieces)
        if min_len <= 0:
            return np.zeros((0, channels), dtype=np.float32)
        out = np.stack([piece[:min_len] for piece in pieces], axis=1)
        return out.astype(np.float32, copy=False)
class SoundDevicePlayer(Player):
    def __init__(self, config: PlaybackConfig) -> None:
        self.config = config
        self.clock = PlaybackClock(config.bluetooth_output_offset_sec)
        self.queue = ChunkQueue()
        self.command_queue = PlayerCommandQueue()
        self._stream: sd.OutputStream | None = None
        self._state = PlaybackState.STOPPED
        self._gain = 1.0
        self._generation = 0
        self._callback_count = 0
        self._content_sample_rate = int(config.sample_rate)
        self._opened_output_sample_rate = int(config.sample_rate)
        self._output_resampler: _OutputResampler | None = None
        self._resolved_output_device: int | None = None
        self._resolved_output_device_name = ""
        self._silent_branch_logged = False
        self._status_snapshot = PlaybackStatus(
            state=PlaybackState.STOPPED,
            chunk_id=-1,
            frame_index=0,
            gain=1.0,
            generation=0,
            t_host_output_sec=0.0,
            t_ref_block_start_content_sec=0.0,
            t_ref_block_end_content_sec=0.0,
            t_ref_emitted_content_sec=0.0,
            t_ref_heard_content_sec=0.0,
        )
    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.clock.set_output_offset_sec(offset_sec)
    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        if chunks and any(c.sample_rate != self.config.sample_rate for c in chunks):
            raise ValueError(
                "Chunk sample rate does not match player config sample rate."
            )
        self.queue.load(chunks)
        self._content_sample_rate = int(self.config.sample_rate)
    def start(self) -> None:
        if self._stream is not None:
            return
        actual_device = self._resolve_output_device(self.config.device)
        dev_info = sd.query_devices(actual_device, "output")
        opened_sr = self._pick_openable_output_samplerate(actual_device, dev_info)
        self._opened_output_sample_rate = int(opened_sr)
        self._output_resampler = (
            None
            if self._opened_output_sample_rate == self._content_sample_rate
            else _OutputResampler(
                src_rate=self._content_sample_rate,
                dst_rate=self._opened_output_sample_rate,
            )
        )
        self._resolved_output_device = int(actual_device)
        self._resolved_output_device_name = str(dev_info["name"])
        try:
            self._stream = sd.OutputStream(
                samplerate=self._opened_output_sample_rate,
                channels=self.config.channels,
                dtype="float32",
                callback=self._audio_callback,
                device=self._resolved_output_device,
                latency=self.config.latency,
                blocksize=self.config.blocksize,
            )
            self._state = PlaybackState.PLAYING
            self._silent_branch_logged = False
            self._stream.start()
        except Exception as e:
            self._state = PlaybackState.STOPPED
            raise RuntimeError(
                f"Failed to open output stream: device={self._resolved_output_device}, "
                f"sample_rate={self._opened_output_sample_rate}, channels={self.config.channels}, "
                f"latency={self.config.latency}, blocksize={self.config.blocksize}"
            ) from e
    def submit_command(self, command: PlayerCommand) -> None:
        self.command_queue.put(command)
    def get_status(self) -> PlaybackStatus:
        return self._status_snapshot
    def stop(self) -> None:
        self.submit_command(
            PlayerCommand(cmd=PlayerCommandType.STOP, reason="external_stop")
        )
    def close(self) -> None:
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self._state = PlaybackState.STOPPED
    def _apply_merged_commands(self) -> None:
        merged = self.command_queue.drain_merged()
        if merged.gain_cmd and merged.gain_cmd.gain is not None:
            self._gain = min(max(float(merged.gain_cmd.gain), 0.0), 1.0)
        hold_after_seek = False
        if merged.state_cmd is not None:
            if merged.state_cmd.cmd == PlayerCommandType.HOLD:
                hold_after_seek = True
            elif merged.state_cmd.cmd == PlayerCommandType.RESUME:
                self._state = PlaybackState.PLAYING
                self._silent_branch_logged = False
            elif merged.state_cmd.cmd == PlayerCommandType.STOP:
                self._state = PlaybackState.STOPPED
            elif merged.state_cmd.cmd == PlayerCommandType.START:
                self._state = PlaybackState.PLAYING
                self._silent_branch_logged = False
        if merged.seek_cmd is not None and merged.seek_cmd.target_time_sec is not None:
            self._state = PlaybackState.SEEKING
            self.queue.seek(float(merged.seek_cmd.target_time_sec))
            self._generation += 1
            self._state = PlaybackState.HOLDING if hold_after_seek else PlaybackState.PLAYING
            if self._state == PlaybackState.PLAYING:
                self._silent_branch_logged = False
        elif hold_after_seek:
            self._state = PlaybackState.HOLDING
    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        _ = status
        self._callback_count += 1
        self._apply_merged_commands()
        block_start = self.queue.get_content_time_sec()
        if self._state in (
            PlaybackState.STOPPED,
            PlaybackState.HOLDING,
            PlaybackState.FINISHED,
        ):
            outdata.fill(0.0)
            self._silent_branch_logged = True
        else:
            self._silent_branch_logged = False
            if self._output_resampler is None:
                block = self.queue.read_frames(
                    frames=frames,
                    channels=self.config.channels,
                )
            else:
                src_frames = self._estimate_source_frames(frames)
                source_block = self.queue.read_frames(
                    frames=src_frames,
                    channels=self.config.channels,
                )
                block = self._output_resampler.process(source_block)
                if block.shape[0] < frames:
                    padded = np.zeros((frames, self.config.channels), dtype=np.float32)
                    if block.shape[0] > 0:
                        padded[: block.shape[0], :] = block
                    block = padded
                elif block.shape[0] > frames:
                    block = block[:frames, :]
            outdata[:] = block * self._gain
            if self.queue.is_finished():
                self._state = PlaybackState.FINISHED
        block_end = self.queue.get_content_time_sec()
        snapshot = self.clock.compute(
            output_buffer_dac_time_sec=float(time_info.outputBufferDacTime),
            block_start_content_sec=block_start,
            block_end_content_sec=block_end,
        )
        self._status_snapshot = PlaybackStatus(
            state=self._state,
            chunk_id=self.queue.current_chunk_id,
            frame_index=self.queue.current_frame_index,
            gain=self._gain,
            generation=self._generation,
            t_host_output_sec=snapshot.t_host_output_sec,
            t_ref_block_start_content_sec=snapshot.t_ref_block_start_content_sec,
            t_ref_block_end_content_sec=snapshot.t_ref_block_end_content_sec,
            t_ref_emitted_content_sec=snapshot.t_ref_emitted_content_sec,
            t_ref_heard_content_sec=snapshot.t_ref_heard_content_sec,
        )
    def _resolve_output_device(self, requested_device: int | str | None) -> int:
        if isinstance(requested_device, int):
            dev_info = sd.query_devices(requested_device)
            if int(dev_info["max_output_channels"]) <= 0:
                raise ValueError(
                    f"Requested device is not an output device: "
                    f"device={requested_device}, name={dev_info['name']}"
                )
            return int(requested_device)
        if isinstance(requested_device, str):
            target = requested_device.strip().lower()
            if target:
                devices = sd.query_devices()
                for idx, dev in enumerate(devices):
                    if int(dev["max_output_channels"]) <= 0:
                        continue
                    if target in str(dev["name"]).lower():
                        return int(idx)
                candidates = [
                    f"[{idx}] {dev['name']}"
                    for idx, dev in enumerate(devices)
                    if int(dev["max_output_channels"]) > 0
                ]
                joined = "\n".join(candidates[:50])
                raise ValueError(
                    "Output device name not found: "
                    f"{requested_device!r}\nAvailable output devices:\n{joined}"
                )
        default_in, default_out = sd.default.device
        candidates: list[int] = []
        if default_out is not None and int(default_out) >= 0:
            candidates.append(int(default_out))
        if default_in is not None and int(default_in) >= 0 and int(default_in) not in candidates:
            candidates.append(int(default_in))
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev["max_output_channels"]) > 0 and idx not in candidates:
                candidates.append(idx)
        for idx in candidates:
            try:
                dev_info = sd.query_devices(idx)
                if int(dev_info["max_output_channels"]) > 0:
                    return int(idx)
            except Exception:
                continue
        raise RuntimeError("No valid output device available.")
    def _pick_openable_output_samplerate(self, device: int, dev_info) -> int:
        candidates: list[int] = []
        preferred = [
            self.config.sample_rate,
            int(float(dev_info["default_samplerate"])),
            48000,
            44100,
            16000,
        ]
        for sr in preferred:
            if sr > 0 and sr not in candidates:
                candidates.append(int(sr))
        last_error: Exception | None = None
        for sr in candidates:
            try:
                sd.check_output_settings(
                    device=device,
                    samplerate=sr,
                    channels=self.config.channels,
                    dtype="float32",
                )
                return int(sr)
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(
            f"Failed to find openable output samplerate for device={device}, "
            f"default_sr={float(dev_info['default_samplerate'])}, last_error={last_error}"
        )
    def _estimate_source_frames(self, output_frames: int) -> int:
        if self._opened_output_sample_rate <= 0 or self._content_sample_rate <= 0:
            return output_frames
        ratio = self._content_sample_rate / self._opened_output_sample_rate
        estimated = int(np.ceil(output_frames * ratio)) + 8
        return max(1, estimated)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/runtime.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any
@dataclass(slots=True)
class RealtimeRuntimeConfig:
    tick_sleep_sec: float = 0.03
class ShadowingRuntime:
    def __init__(
        self,
        *,
        orchestrator: Any,
        config: RealtimeRuntimeConfig | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config or RealtimeRuntimeConfig()
        self._running = False
    def run(self, lesson_id: str) -> None:
        self._running = True
        self.orchestrator.start_session(lesson_id)
        try:
            while self._running:
                self.orchestrator.tick()
                time.sleep(self.config.tick_sleep_sec)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self.orchestrator.stop_session()
    def stop(self) -> None:
        self._running = False
RealtimeRuntime = ShadowingRuntime
```

---
### 文件: `shadowing_app/src/shadowing/realtime/sync_evidence.py`

```python
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
```

---
### 文件: `shadowing_app/src/shadowing/session/session_metrics.py`

```python
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
_STARTUP_FALSE_HOLD_REASONS = {
    "no_progress_timeout",
    "reference_too_far_ahead",
}
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if out != out:
        return float(default)
    return float(out)
@dataclass(slots=True)
class SessionMetrics:
    lesson_id: str = ""
    session_started_at_sec: float = 0.0
    session_ended_at_sec: float = 0.0
    first_signal_active_time_sec: float | None = None
    first_asr_partial_time_sec: float | None = None
    first_reliable_progress_time_sec: float | None = None
    startup_false_hold_count: int = 0
    hold_count: int = 0
    resume_count: int = 0
    soft_duck_count: int = 0
    seek_count: int = 0
    lost_count: int = 0
    reacquire_count: int = 0
    max_tracking_quality: float = 0.0
    _tracking_quality_sum: float = 0.0
    total_progress_updates: int = 0
    tracking_total: int = 0
    tracking_stable_count: int = 0
    tracking_mode_counter: Counter[str] = field(default_factory=Counter)
    progress_recent_count: int = 0
    position_source_counter: Counter[str] = field(default_factory=Counter)
    joint_confidence_sum: float = 0.0
    signal_active_events: int = 0
    asr_partial_count: int = 0
    action_reason_counter: Counter[str] = field(default_factory=Counter)
    def mark_session_started(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = now_sec
        if self.session_ended_at_sec < self.session_started_at_sec:
            self.session_ended_at_sec = self.session_started_at_sec
    def mark_session_ended(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = now_sec
        self.session_ended_at_sec = max(now_sec, self.session_started_at_sec)
    def observe_signal_active(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        self.signal_active_events += 1
        if self.first_signal_active_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_signal_active_time_sec = max(0.0, now_sec - self.session_started_at_sec)
    def observe_asr_partial(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        self.asr_partial_count += 1
        if self.first_asr_partial_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_asr_partial_time_sec = max(0.0, now_sec - self.session_started_at_sec)
    def observe_progress(
        self,
        *,
        now_since_session_start_sec: float,
        recently_progressed: bool,
        joint_confidence: float,
        position_source: str,
        tracking_quality: float | None = None,
        is_reliable: bool | None = None,
    ) -> None:
        self.total_progress_updates += 1
        tq = _safe_float(tracking_quality, 0.0) if tracking_quality is not None else 0.0
        jc = max(0.0, min(1.0, _safe_float(joint_confidence, 0.0)))
        if tq > self.max_tracking_quality:
            self.max_tracking_quality = tq
        self._tracking_quality_sum += tq
        self.joint_confidence_sum += jc
        if recently_progressed:
            self.progress_recent_count += 1
        source = str(position_source or "unknown")
        self.position_source_counter[source] += 1
        if is_reliable and self.first_reliable_progress_time_sec is None:
            self.first_reliable_progress_time_sec = max(0.0, _safe_float(now_since_session_start_sec))
    def observe_tracking(
        self,
        *,
        tracking_mode: str,
        tracking_quality: float,
        stable: bool,
    ) -> None:
        self.tracking_total += 1
        mode = str(tracking_mode or "unknown")
        self.tracking_mode_counter[mode] += 1
        if stable:
            self.tracking_stable_count += 1
        tq = _safe_float(tracking_quality, 0.0)
        if tq > self.max_tracking_quality:
            self.max_tracking_quality = tq
        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1
    def observe_tracking_mode(self, mode: str) -> None:
        mode = str(mode or "unknown")
        self.tracking_mode_counter[mode] += 1
        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1
    def observe_control(
        self,
        *,
        action: str,
        now_since_session_start_sec: float,
        startup_grace_sec: float,
        reason: str | None = None,
    ) -> None:
        action = str(action or "unknown")
        reason = str(reason or "").strip()
        if action == "hold":
            self.hold_count += 1
            if now_since_session_start_sec <= max(0.0, _safe_float(startup_grace_sec)):
                if reason in _STARTUP_FALSE_HOLD_REASONS:
                    self.startup_false_hold_count += 1
        elif action == "resume":
            self.resume_count += 1
        elif action == "soft_duck":
            self.soft_duck_count += 1
        elif action == "seek":
            self.seek_count += 1
        if reason:
            self.action_reason_counter[f"{action}:{reason}"] += 1
    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        if self.session_started_at_sec > 0.0:
            since_start = max(0.0, _safe_float(now_sec) - self.session_started_at_sec)
        else:
            since_start = 0.0
        self.observe_control(
            action=action,
            now_since_session_start_sec=since_start,
            startup_grace_sec=5.0,
            reason=reason,
        )
    def mean_tracking_quality(self) -> float:
        if self.total_progress_updates <= 0:
            return 0.0
        return float(self._tracking_quality_sum / self.total_progress_updates)
    def summary_dict(self) -> dict[str, Any]:
        duration_sec = 0.0
        if self.session_started_at_sec > 0.0 and self.session_ended_at_sec >= self.session_started_at_sec:
            duration_sec = float(self.session_ended_at_sec - self.session_started_at_sec)
        mean_tracking_quality = self.mean_tracking_quality()
        return {
            "first_signal_active_time_sec": self.first_signal_active_time_sec,
            "first_asr_partial_time_sec": self.first_asr_partial_time_sec,
            "first_reliable_progress_time_sec": self.first_reliable_progress_time_sec,
            "startup_false_hold_count": self.startup_false_hold_count,
            "hold_count": self.hold_count,
            "resume_count": self.resume_count,
            "soft_duck_count": self.soft_duck_count,
            "seek_count": self.seek_count,
            "lost_count": self.lost_count,
            "reacquire_count": self.reacquire_count,
            "max_tracking_quality": self.max_tracking_quality,
            "mean_tracking_quality": mean_tracking_quality,
            "total_progress_updates": self.total_progress_updates,
            "lesson_id": self.lesson_id,
            "session_started_at_sec": self.session_started_at_sec,
            "session_ended_at_sec": self.session_ended_at_sec,
            "session_duration_sec": duration_sec,
            "signal_active_events": self.signal_active_events,
            "asr_partial_count": self.asr_partial_count,
            "tracking_total": self.tracking_total,
            "tracking_stable_count": self.tracking_stable_count,
            "progress_recent_count": self.progress_recent_count,
            "avg_joint_confidence": (
                float(self.joint_confidence_sum / self.total_progress_updates)
                if self.total_progress_updates > 0
                else 0.0
            ),
            "tracking_mode_counter": dict(self.tracking_mode_counter),
            "position_source_counter": dict(self.position_source_counter),
            "action_reason_counter": dict(self.action_reason_counter),
        }
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/event_logger.py`

```python
from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any
class EventLogger:
    def __init__(self, session_dir: str, enabled: bool = True) -> None:
        self.session_dir = Path(session_dir)
        self.enabled = bool(enabled)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.session_dir / "events.jsonl"
        self._lock = threading.Lock()
    def log(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        ts_monotonic_sec: float | None = None,
        session_tick: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        record = {
            "event_type": str(event_type),
            "ts_monotonic_sec": (
                float(ts_monotonic_sec) if ts_monotonic_sec is not None else None
            ),
            "session_tick": int(session_tick) if session_tick is not None else None,
            "payload": payload,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/metrics.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from shadowing.session.session_metrics import SessionMetrics
@dataclass(slots=True)
class SessionMetricsSummary:
    first_signal_active_time_sec: float | None
    first_asr_partial_time_sec: float | None
    first_reliable_progress_time_sec: float | None
    startup_false_hold_count: int
    hold_count: int
    resume_count: int
    soft_duck_count: int
    seek_count: int
    lost_count: int
    reacquire_count: int
    max_tracking_quality: float
    mean_tracking_quality: float
    total_progress_updates: int
class MetricsAggregator:
    def __init__(self, lesson_id: str = "") -> None:
        self._delegate = SessionMetrics(lesson_id=lesson_id)
    def mark_session_started(self, now_sec: float) -> None:
        self._delegate.mark_session_started(now_sec)
    def mark_session_ended(self, now_sec: float) -> None:
        self._delegate.mark_session_ended(now_sec)
    def observe_signal_active(self, now_sec: float) -> None:
        self._delegate.observe_signal_active(now_sec)
    def observe_asr_partial(self, now_sec: float) -> None:
        self._delegate.observe_asr_partial(now_sec)
    def observe_progress(self, now_sec: float, tracking_quality: float, is_reliable: bool) -> None:
        if self._delegate.session_started_at_sec > 0.0:
            since_start = max(0.0, float(now_sec) - self._delegate.session_started_at_sec)
        else:
            since_start = 0.0
        self._delegate.observe_progress(
            now_since_session_start_sec=since_start,
            recently_progressed=False,
            joint_confidence=float(tracking_quality),
            position_source="unknown",
            tracking_quality=float(tracking_quality),
            is_reliable=bool(is_reliable),
        )
    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        self._delegate.observe_action(action, reason, now_sec)
    def observe_tracking_mode(self, mode: str) -> None:
        self._delegate.observe_tracking_mode(mode)
    def summary(self) -> SessionMetricsSummary:
        d = self._delegate.summary_dict()
        return SessionMetricsSummary(
            first_signal_active_time_sec=d.get("first_signal_active_time_sec"),
            first_asr_partial_time_sec=d.get("first_asr_partial_time_sec"),
            first_reliable_progress_time_sec=d.get("first_reliable_progress_time_sec"),
            startup_false_hold_count=int(d.get("startup_false_hold_count", 0)),
            hold_count=int(d.get("hold_count", 0)),
            resume_count=int(d.get("resume_count", 0)),
            soft_duck_count=int(d.get("soft_duck_count", 0)),
            seek_count=int(d.get("seek_count", 0)),
            lost_count=int(d.get("lost_count", 0)),
            reacquire_count=int(d.get("reacquire_count", 0)),
            max_tracking_quality=float(d.get("max_tracking_quality", 0.0)),
            mean_tracking_quality=float(d.get("mean_tracking_quality", 0.0)),
            total_progress_updates=int(d.get("total_progress_updates", 0)),
        )
    def summary_dict(self) -> dict:
        return self._delegate.summary_dict()
    @property
    def session_metrics(self) -> SessionMetrics:
        return self._delegate
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/replay_loader.py`

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
@dataclass(slots=True)
class ReplayEvent:
    event_type: str
    ts_monotonic_sec: float | None
    session_tick: int | None
    payload: dict
class ReplayLoader:
    def __init__(self, events_file: str) -> None:
        self.events_file = Path(events_file)
    def __iter__(self) -> Iterator[ReplayEvent]:
        with self.events_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                yield ReplayEvent(
                    event_type=str(data.get("event_type", "")),
                    ts_monotonic_sec=(
                        float(data["ts_monotonic_sec"])
                        if data.get("ts_monotonic_sec") is not None
                        else None
                    ),
                    session_tick=(
                        int(data["session_tick"])
                        if data.get("session_tick") is not None
                        else None
                    ),
                    payload=dict(data.get("payload", {})),
                )
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/session_evaluator.py`

```python
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
from statistics import mean
from shadowing.telemetry.replay_loader import ReplayLoader
@dataclass(slots=True)
class SessionEvaluationSummary:
    session_dir: str
    hold_count: int = 0
    seek_count: int = 0
    soft_duck_count: int = 0
    false_hold_count: int = 0
    false_seek_count: int = 0
    reacquire_count: int = 0
    mean_reacquire_latency_sec: float = 0.0
    p95_reacquire_latency_sec: float = 0.0
    max_reacquire_latency_sec: float = 0.0
    startup_first_reliable_progress_time_sec: float | None = None
    mean_tracking_quality: float = 0.0
    max_tracking_quality: float = 0.0
    def to_dict(self) -> dict:
        return asdict(self)
class SessionEvaluator:
    def __init__(self, events_file: str, summary_file: str | None = None) -> None:
        self.events_file = Path(events_file)
        self.summary_file = Path(summary_file) if summary_file else self.events_file.with_name("summary.json")
    def evaluate(self) -> SessionEvaluationSummary:
        loader = ReplayLoader(str(self.events_file))
        out = SessionEvaluationSummary(session_dir=str(self.events_file.parent))
        tracking_scores: list[float] = []
        reacquire_started_at: float | None = None
        reacquire_latencies: list[float] = []
        recent_signal = 0.0
        recent_audio_follow = 0.0
        recent_audio_repeat = 0.0
        recent_progress_follow = False
        recent_progress_conf = 0.0
        seek_recovered_fast = False
        last_seek_ts: float | None = None
        for ev in loader:
            ts = float(ev.ts_monotonic_sec or 0.0)
            if ev.event_type == "signal_snapshot":
                recent_signal = max(float(ev.payload.get("speaking_likelihood", 0.0)), 0.75 if ev.payload.get("vad_active") else 0.0)
            elif ev.event_type == "audio_behavior_snapshot":
                recent_audio_follow = float(ev.payload.get("still_following_likelihood", 0.0))
                recent_audio_repeat = float(ev.payload.get("repeated_likelihood", 0.0))
            elif ev.event_type == "fusion_evidence":
                recent_audio_follow = max(recent_audio_follow, float(ev.payload.get("still_following_likelihood", 0.0)))
                recent_audio_repeat = max(recent_audio_repeat, float(ev.payload.get("repeated_likelihood", 0.0)))
            elif ev.event_type == "progress_snapshot":
                recent_progress_follow = bool(ev.payload.get("active_speaking", False) or ev.payload.get("recently_progressed", False))
                recent_progress_conf = float(ev.payload.get("confidence", 0.0))
                tq = float(ev.payload.get("tracking_quality", 0.0))
                tracking_scores.append(tq)
            elif ev.event_type == "tracking_snapshot":
                tracking_scores.append(float(ev.payload.get("overall_score", 0.0)))
                mode = str(ev.payload.get("tracking_mode", ""))
                if mode == "reacquiring" and reacquire_started_at is None:
                    reacquire_started_at = ts
                elif reacquire_started_at is not None and mode in {"locked", "weak_locked"} and float(ev.payload.get("overall_score", 0.0)) >= 0.58:
                    reacquire_latencies.append(max(0.0, ts - reacquire_started_at))
                    reacquire_started_at = None
            elif ev.event_type == "control_decision":
                action = str(ev.payload.get("action", ""))
                if action == "hold":
                    out.hold_count += 1
                    if recent_progress_follow or recent_progress_conf >= 0.64 or recent_audio_follow >= 0.68 or recent_signal >= 0.58:
                        out.false_hold_count += 1
                elif action == "seek":
                    out.seek_count += 1
                    last_seek_ts = ts
                    seek_recovered_fast = False
                    if recent_audio_repeat >= 0.62:
                        out.false_seek_count += 1
                elif action == "soft_duck":
                    out.soft_duck_count += 1
            elif ev.event_type == "session_summary":
                metrics = ev.payload.get("metrics", {})
                out.startup_first_reliable_progress_time_sec = metrics.get("first_reliable_progress_time_sec")
                out.mean_tracking_quality = float(metrics.get("mean_tracking_quality", out.mean_tracking_quality))
                out.max_tracking_quality = float(metrics.get("max_tracking_quality", out.max_tracking_quality))
            if last_seek_ts is not None and ts > 0.0 and (ts - last_seek_ts) <= 1.6 and recent_progress_conf >= 0.74:
                seek_recovered_fast = True
            if last_seek_ts is not None and ts > 0.0 and (ts - last_seek_ts) > 1.8:
                if not seek_recovered_fast and out.seek_count > 0:
                    out.false_seek_count += 1
                last_seek_ts = None
                seek_recovered_fast = False
        if self.summary_file.exists():
            try:
                data = json.loads(self.summary_file.read_text(encoding="utf-8"))
                metrics = data.get("metrics", {})
                out.startup_first_reliable_progress_time_sec = metrics.get("first_reliable_progress_time_sec", out.startup_first_reliable_progress_time_sec)
                out.mean_tracking_quality = float(metrics.get("mean_tracking_quality", out.mean_tracking_quality))
                out.max_tracking_quality = float(metrics.get("max_tracking_quality", out.max_tracking_quality))
            except Exception:
                pass
        if tracking_scores and out.mean_tracking_quality <= 0.0:
            out.mean_tracking_quality = float(mean(tracking_scores))
            out.max_tracking_quality = float(max(tracking_scores))
        out.reacquire_count = len(reacquire_latencies)
        if reacquire_latencies:
            vals = sorted(reacquire_latencies)
            out.mean_reacquire_latency_sec = float(mean(vals))
            out.max_reacquire_latency_sec = float(max(vals))
            p95_index = min(len(vals) - 1, max(0, int(round(0.95 * (len(vals) - 1)))))
            out.p95_reacquire_latency_sec = float(vals[p95_index])
        return out
```

---
### 文件: `shadowing_app/src/shadowing/tracking/anchor_manager.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from shadowing.types import TrackingSnapshot
@dataclass(slots=True)
class Anchor:
    ref_idx: int
    emitted_at_sec: float
    quality_score: float
    matched_text: str = ""
class AnchorManager:
    def __init__(
        self,
        strong_anchor_quality: float = 0.78,
        weak_anchor_quality: float = 0.64,
        max_anchor_gap: int = 24,
    ) -> None:
        self.strong_anchor_quality = float(strong_anchor_quality)
        self.weak_anchor_quality = float(weak_anchor_quality)
        self.max_anchor_gap = int(max_anchor_gap)
        self._strong_anchor: Anchor | None = None
        self._weak_anchor: Anchor | None = None
    def reset(self) -> None:
        self._strong_anchor = None
        self._weak_anchor = None
    def update(self, snapshot: TrackingSnapshot) -> None:
        q = snapshot.tracking_quality.overall_score
        text = snapshot.matched_text or ""
        if snapshot.stable and q >= self.strong_anchor_quality:
            self._strong_anchor = Anchor(
                ref_idx=int(snapshot.candidate_ref_idx),
                emitted_at_sec=float(snapshot.emitted_at_sec),
                quality_score=float(q),
                matched_text=text,
            )
            self._weak_anchor = Anchor(
                ref_idx=int(snapshot.candidate_ref_idx),
                emitted_at_sec=float(snapshot.emitted_at_sec),
                quality_score=float(q),
                matched_text=text,
            )
            return
        if q >= self.weak_anchor_quality:
            if self._strong_anchor is None:
                self._weak_anchor = Anchor(
                    ref_idx=int(snapshot.candidate_ref_idx),
                    emitted_at_sec=float(snapshot.emitted_at_sec),
                    quality_score=float(q),
                    matched_text=text,
                )
                return
            if abs(snapshot.candidate_ref_idx - self._strong_anchor.ref_idx) <= self.max_anchor_gap:
                self._weak_anchor = Anchor(
                    ref_idx=int(snapshot.candidate_ref_idx),
                    emitted_at_sec=float(snapshot.emitted_at_sec),
                    quality_score=float(q),
                    matched_text=text,
                )
    def current_anchor_idx(self) -> int:
        if self._strong_anchor is not None:
            return self._strong_anchor.ref_idx
        if self._weak_anchor is not None:
            return self._weak_anchor.ref_idx
        return 0
    def strong_anchor(self) -> Anchor | None:
        return self._strong_anchor
    def weak_anchor(self) -> Anchor | None:
        return self._weak_anchor
    def anchor_consistency(self, candidate_idx: int) -> float:
        anchor_idx = self.current_anchor_idx()
        dist = abs(int(candidate_idx) - int(anchor_idx))
        return 1.0 / (1.0 + (dist / 14.0))
```

---
### 文件: `shadowing_app/src/shadowing/tracking/loss_detector.py`

```python
from __future__ import annotations
from collections import deque
from statistics import pstdev
from shadowing.types import TrackingMode, TrackingSnapshot
class LossDetector:
    def __init__(
        self,
        jitter_window: int = 6,
        weak_quality_threshold: float = 0.56,
        lost_quality_threshold: float = 0.40,
        max_jitter_sigma: float = 8.0,
        lost_run_threshold: int = 4,
    ) -> None:
        self.jitter_window = int(jitter_window)
        self.weak_quality_threshold = float(weak_quality_threshold)
        self.lost_quality_threshold = float(lost_quality_threshold)
        self.max_jitter_sigma = float(max_jitter_sigma)
        self.lost_run_threshold = int(lost_run_threshold)
        self._recent_candidates: deque[int] = deque(maxlen=self.jitter_window)
        self._low_quality_run = 0
        self._good_quality_run = 0
        self._last_reliable_at_sec = 0.0
    def reset(self) -> None:
        self._recent_candidates.clear()
        self._low_quality_run = 0
        self._good_quality_run = 0
        self._last_reliable_at_sec = 0.0
    def update(
        self,
        snapshot: TrackingSnapshot,
        overall_score: float,
        is_reliable: bool,
    ) -> tuple[TrackingMode, float]:
        candidate_idx = int(snapshot.candidate_ref_idx)
        series = list(self._recent_candidates) + [candidate_idx]
        if len(series) <= 1:
            temporal_consistency = 0.72
        else:
            sigma = pstdev(series)
            temporal_consistency = max(0.0, 1.0 - min(1.0, sigma / self.max_jitter_sigma))
        if is_reliable:
            self._last_reliable_at_sec = float(snapshot.emitted_at_sec)
            self._good_quality_run += 1
            self._low_quality_run = 0
        else:
            self._low_quality_run += 1
            self._good_quality_run = 0
        if is_reliable and overall_score >= 0.78 and self._good_quality_run >= 1:
            mode = TrackingMode.LOCKED
        elif overall_score >= self.weak_quality_threshold and temporal_consistency >= 0.28:
            mode = TrackingMode.WEAK_LOCKED
        elif (
            self._last_reliable_at_sec > 0.0
            and (snapshot.emitted_at_sec - self._last_reliable_at_sec) <= 2.0
        ):
            mode = TrackingMode.REACQUIRING
        elif overall_score < self.lost_quality_threshold and self._low_quality_run >= self.lost_run_threshold:
            mode = TrackingMode.LOST
        else:
            mode = TrackingMode.REACQUIRING
        self._recent_candidates.append(candidate_idx)
        return mode, float(temporal_consistency)
```

---
### 文件: `shadowing_app/src/shadowing/tracking/partial_guard.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass
class PartialGuardConfig:
    backward_hits_to_reset: int = 2
    low_q_threshold: float = 0.45
    low_q_hold_sec: float = 0.80
    no_commit_sec: float = 1.20
    max_partial_chars: int = 48
    long_partial_low_trust_threshold: float = 0.55
@dataclass
class PartialGuardState:
    backward_hits: int = 0
    low_q_elapsed_sec: float = 0.0
    no_commit_elapsed_sec: float = 0.0
    partial_reset_recommended: bool = False
    reason: str = ""
class PartialGuard:
    def __init__(self, config: PartialGuardConfig | None = None) -> None:
        self.config = config or PartialGuardConfig()
        self._state = PartialGuardState()
    @property
    def state(self) -> PartialGuardState:
        return self._state
    def reset(self) -> None:
        self._state = PartialGuardState()
    def update(
        self,
        *,
        dt_sec: float,
        partial_text: str,
        committed_advanced: bool,
        backward: bool,
        tracking_quality: float,
        anchor_trust: float,
    ) -> PartialGuardState:
        s = self._state
        s.partial_reset_recommended = False
        s.reason = ""
        if backward:
            s.backward_hits += 1
        else:
            s.backward_hits = 0
        if tracking_quality < self.config.low_q_threshold:
            s.low_q_elapsed_sec += max(0.0, dt_sec)
        else:
            s.low_q_elapsed_sec = 0.0
        if committed_advanced:
            s.no_commit_elapsed_sec = 0.0
        else:
            s.no_commit_elapsed_sec += max(0.0, dt_sec)
        partial_len = len(partial_text or "")
        if s.backward_hits >= self.config.backward_hits_to_reset:
            s.partial_reset_recommended = True
            s.reason = f"backward_hits={s.backward_hits}"
            return s
        if s.low_q_elapsed_sec >= self.config.low_q_hold_sec:
            s.partial_reset_recommended = True
            s.reason = f"low_tracking_q_for={s.low_q_elapsed_sec:.3f}s"
            return s
        if s.no_commit_elapsed_sec >= self.config.no_commit_sec:
            s.partial_reset_recommended = True
            s.reason = f"no_commit_for={s.no_commit_elapsed_sec:.3f}s"
            return s
        if (
            partial_len >= self.config.max_partial_chars
            and anchor_trust < self.config.long_partial_low_trust_threshold
        ):
            s.partial_reset_recommended = True
            s.reason = f"long_partial_len={partial_len}_low_trust={anchor_trust:.3f}"
            return s
        return s
```

---
### 文件: `shadowing_app/src/shadowing/tracking/reacquirer.py`

```python
from __future__ import annotations
from shadowing.types import ReferenceMap, TrackingMode, TrackingSnapshot
class Reacquirer:
    def __init__(self, max_anchor_jump: int = 24, min_anchor_score: float = 0.52) -> None:
        self.max_anchor_jump = int(max_anchor_jump)
        self.min_anchor_score = float(min_anchor_score)
    def maybe_reanchor(self, *, snapshot: TrackingSnapshot, anchor_manager, ref_map: ReferenceMap) -> TrackingSnapshot:
        _ = ref_map
        anchor = anchor_manager.strong_anchor() or anchor_manager.weak_anchor()
        if anchor is None:
            return snapshot
        if snapshot.tracking_mode not in (TrackingMode.REACQUIRING, TrackingMode.LOST):
            return snapshot
        if snapshot.tracking_quality.anchor_score < self.min_anchor_score:
            return snapshot
        anchor_idx = int(anchor.ref_idx)
        cur_idx = int(snapshot.candidate_ref_idx)
        if abs(cur_idx - anchor_idx) > self.max_anchor_jump:
            return snapshot
        if snapshot.anchor_consistency < self.min_anchor_score:
            return snapshot
        return TrackingSnapshot(
            candidate_ref_idx=max(cur_idx, anchor_idx),
            committed_ref_idx=max(int(snapshot.committed_ref_idx), anchor_idx),
            candidate_ref_time_sec=float(snapshot.candidate_ref_time_sec),
            confidence=float(max(snapshot.confidence, min(0.88, anchor.quality_score))),
            stable=bool(snapshot.stable),
            local_match_ratio=float(snapshot.local_match_ratio),
            repeat_penalty=float(snapshot.repeat_penalty),
            monotonic_consistency=float(snapshot.monotonic_consistency),
            anchor_consistency=float(max(snapshot.anchor_consistency, 0.72)),
            emitted_at_sec=float(snapshot.emitted_at_sec),
            tracking_mode=TrackingMode.REACQUIRING,
            tracking_quality=snapshot.tracking_quality,
            matched_text=snapshot.matched_text,
        )
```

---
### 文件: `shadowing_app/src/shadowing/tracking/shadow_lag_estimator.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass
class ShadowLagEstimatorConfig:
    init_sec: float = 1.20
    min_sec: float = 0.35
    max_sec: float = 2.40
    ema_alpha: float = 0.18
    update_min_tracking_q: float = 0.78
    update_min_anchor_trust: float = 0.78
class ShadowLagEstimator:
    def __init__(self, config: ShadowLagEstimatorConfig | None = None) -> None:
        self.config = config or ShadowLagEstimatorConfig()
        self._offset_sec = float(self.config.init_sec)
    @property
    def offset_sec(self) -> float:
        return float(self._offset_sec)
    def reset(self) -> None:
        self._offset_sec = float(self.config.init_sec)
    def set_offset(self, value_sec: float) -> None:
        self._offset_sec = self._clamp(value_sec)
    def update_from_anchor(
        self,
        raw_lead_sec: float | None,
        *,
        stable_anchor: bool,
        tracking_quality: float,
        anchor_trust: float,
    ) -> float:
        if raw_lead_sec is None:
            return self.offset_sec
        if not stable_anchor:
            return self.offset_sec
        if tracking_quality < self.config.update_min_tracking_q:
            return self.offset_sec
        if anchor_trust < self.config.update_min_anchor_trust:
            return self.offset_sec
        alpha = self.config.ema_alpha
        target = self._clamp(raw_lead_sec)
        self._offset_sec = self._clamp((1.0 - alpha) * self._offset_sec + alpha * target)
        return self.offset_sec
    def effective_lead(self, raw_lead_sec: float | None) -> float | None:
        if raw_lead_sec is None:
            return None
        return float(raw_lead_sec) - self.offset_sec
    def _clamp(self, value_sec: float) -> float:
        return max(self.config.min_sec, min(self.config.max_sec, float(value_sec)))
```

---
### 文件: `shadowing_app/src/shadowing/tracking/stable_anchor.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass
class StableAnchorConfig:
    min_tracking_q: float = 0.78
    min_confidence: float = 0.78
    min_score: float = 0.0
    same_candidate_hits: int = 2
    backward_penalty: float = 0.35
    unstable_penalty: float = 0.20
@dataclass
class StableAnchorDecision:
    stable_anchor: bool
    anchor_trust: float
    same_candidate_hits: int
class StableAnchorTracker:
    def __init__(self, config: StableAnchorConfig | None = None) -> None:
        self.config = config or StableAnchorConfig()
        self._last_candidate_idx: int | None = None
        self._same_candidate_hits: int = 0
    def reset(self) -> None:
        self._last_candidate_idx = None
        self._same_candidate_hits = 0
    def update(
        self,
        *,
        candidate_idx: int | None,
        confidence: float,
        tracking_quality: float,
        score: float,
        backward: bool,
    ) -> StableAnchorDecision:
        if candidate_idx is None:
            self._last_candidate_idx = None
            self._same_candidate_hits = 0
            return StableAnchorDecision(
                stable_anchor=False,
                anchor_trust=0.0,
                same_candidate_hits=0,
            )
        if self._last_candidate_idx == candidate_idx:
            self._same_candidate_hits += 1
        else:
            self._last_candidate_idx = candidate_idx
            self._same_candidate_hits = 1
        anchor_trust = self._compute_anchor_trust(
            confidence=confidence,
            tracking_quality=tracking_quality,
            score=score,
            backward=backward,
            same_hits=self._same_candidate_hits,
        )
        stable_anchor = (
            not backward
            and tracking_quality >= self.config.min_tracking_q
            and confidence >= self.config.min_confidence
            and score >= self.config.min_score
            and self._same_candidate_hits >= self.config.same_candidate_hits
        )
        return StableAnchorDecision(
            stable_anchor=stable_anchor,
            anchor_trust=anchor_trust,
            same_candidate_hits=self._same_candidate_hits,
        )
    def _compute_anchor_trust(
        self,
        *,
        confidence: float,
        tracking_quality: float,
        score: float,
        backward: bool,
        same_hits: int,
    ) -> float:
        trust = 0.55 * float(confidence) + 0.35 * float(tracking_quality)
        if score >= 0:
            trust += min(0.10, score / 100.0)
        else:
            trust -= min(0.10, abs(score) / 50.0)
        trust += min(0.12, 0.04 * max(0, same_hits - 1))
        if backward:
            trust -= self.config.backward_penalty
        if same_hits < self.config.same_candidate_hits:
            trust -= self.config.unstable_penalty
        return max(0.0, min(1.0, trust))
```

---
### 文件: `shadowing_app/src/shadowing/tracking/tracking_engine.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.tracking.anchor_manager import AnchorManager
from shadowing.tracking.loss_detector import LossDetector
from shadowing.tracking.reacquirer import Reacquirer
from shadowing.types import AsrEvent, ReferenceMap, TrackingMode, TrackingQuality, TrackingSnapshot
@dataclass(slots=True)
class _TrackingContext:
    ref_map: ReferenceMap | None = None
    last_generation: int = 0
class TrackingEngine:
    def __init__(self, aligner: IncrementalAligner, debug: bool = False) -> None:
        self.aligner = aligner
        self.debug = bool(debug)
        self.anchor_manager = AnchorManager()
        self.loss_detector = LossDetector()
        self.reacquirer = Reacquirer()
        self._ctx = _TrackingContext()
    def reset(self, ref_map: ReferenceMap) -> None:
        self._ctx = _TrackingContext(ref_map=ref_map, last_generation=0)
        reference_text = "".join(token.char for token in ref_map.tokens)
        self.aligner.set_reference(reference_text)
        self.anchor_manager.reset()
        self.loss_detector.reset()
    def on_playback_generation_changed(self, generation: int) -> None:
        self._ctx.last_generation = int(generation)
        committed = self.aligner.get_committed_index()
        self.aligner.reset(committed=committed)
    def recenter_from_audio(
        self,
        *,
        ref_idx_hint: int,
        search_back: int = 12,
        search_ahead: int = 28,
        budget_events: int = 6,
    ) -> None:
        ref_map = self._ctx.ref_map
        if ref_map is None or not ref_map.tokens:
            return
        hint = max(0, min(int(ref_idx_hint), len(ref_map.tokens) - 1))
        self.aligner.force_recenter(
            committed_hint=hint,
            window_back=int(search_back),
            window_ahead=int(search_ahead),
            budget_events=int(budget_events),
        )
    def update(self, event: AsrEvent) -> TrackingSnapshot | None:
        ref_map = self._ctx.ref_map
        if ref_map is None or not ref_map.tokens:
            return None
        result = self.aligner.update(event.normalized_text)
        max_idx = len(ref_map.tokens) - 1
        candidate_idx = max(0, min(int(result.candidate), max_idx))
        committed_idx = max(0, min(int(result.committed), max_idx))
        observation_score = float(max(0.0, min(1.0, result.conf)))
        local_match = float(max(0.0, min(1.0, result.local_match)))
        monotonic_consistency = 1.0 if not result.backward else 0.0
        repeat_penalty = 0.12 if result.repeated_candidate else 0.0
        anchor_score = float(self.anchor_manager.anchor_consistency(candidate_idx))
        preliminary_overall = (
            0.60 * observation_score
            + 0.25 * local_match
            + 0.15 * monotonic_consistency
        )
        preliminary_reliable = bool(
            observation_score >= 0.60
            and local_match >= 0.58
            and not result.backward
        )
        provisional = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(ref_map.tokens[candidate_idx].t_start),
            confidence=float(result.conf),
            stable=bool(result.stable),
            local_match_ratio=local_match,
            repeat_penalty=repeat_penalty,
            monotonic_consistency=monotonic_consistency,
            anchor_consistency=anchor_score,
            emitted_at_sec=float(event.emitted_at_sec),
            tracking_mode=TrackingMode.BOOTSTRAP,
            tracking_quality=TrackingQuality(
                overall_score=float(preliminary_overall),
                observation_score=float(observation_score),
                temporal_consistency_score=0.72,
                anchor_score=float(anchor_score),
                mode=TrackingMode.BOOTSTRAP,
                is_reliable=preliminary_reliable,
            ),
            matched_text=event.normalized_text[: max(0, result.matched_n)],
        )
        mode, temporal_consistency = self.loss_detector.update(
            provisional,
            overall_score=preliminary_overall,
            is_reliable=preliminary_reliable,
        )
        overall_score = (
            0.50 * observation_score
            + 0.20 * local_match
            + 0.15 * float(temporal_consistency)
            + 0.15 * anchor_score
        )
        overall_score = float(max(0.0, min(1.0, overall_score)))
        is_reliable = bool(
            overall_score >= 0.60
            and observation_score >= 0.58
            and local_match >= 0.55
            and not result.backward
        )
        snapshot = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(ref_map.tokens[candidate_idx].t_start),
            confidence=float(result.conf),
            stable=bool(result.stable),
            local_match_ratio=local_match,
            repeat_penalty=repeat_penalty,
            monotonic_consistency=monotonic_consistency,
            anchor_consistency=anchor_score,
            emitted_at_sec=float(event.emitted_at_sec),
            tracking_mode=mode,
            tracking_quality=TrackingQuality(
                overall_score=overall_score,
                observation_score=float(observation_score),
                temporal_consistency_score=float(temporal_consistency),
                anchor_score=float(anchor_score),
                mode=mode,
                is_reliable=is_reliable,
            ),
            matched_text=event.normalized_text[: max(0, result.matched_n)],
        )
        self.anchor_manager.update(snapshot)
        snapshot = self.reacquirer.maybe_reanchor(
            snapshot=snapshot,
            anchor_manager=self.anchor_manager,
            ref_map=ref_map,
        )
        return snapshot
```

---
### 文件: `shadowing_app/src/shadowing/types.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re
import numpy as np
from numpy.typing import NDArray
from pypinyin import Style, lazy_pinyin
class PlaybackState(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    HOLDING = "holding"
    SEEKING = "seeking"
    FINISHED = "finished"
class ControlAction(str, Enum):
    NOOP = "noop"
    SOFT_DUCK = "soft_duck"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"
class AsrEventType(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"
    ENDPOINT = "endpoint"
class PlayerCommandType(str, Enum):
    START = "start"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"
    SET_GAIN = "set_gain"
class TrackingMode(str, Enum):
    BOOTSTRAP = "bootstrap"
    LOCKED = "locked"
    WEAK_LOCKED = "weak_locked"
    REACQUIRING = "reacquiring"
    LOST = "lost"
class UserReadState(str, Enum):
    NOT_STARTED = "not_started"
    WARMING_UP = "warming_up"
    FOLLOWING = "following"
    HESITATING = "hesitating"
    PAUSED = "paused"
    REPEATING = "repeating"
    SKIPPING = "skipping"
    REJOINING = "rejoining"
    LOST = "lost"
@dataclass(slots=True)
class PlayerCommand:
    cmd: PlayerCommandType
    target_time_sec: Optional[float] = None
    gain: Optional[float] = None
    reason: str = ""
@dataclass(slots=True)
class AudioChunk:
    chunk_id: int
    sample_rate: int
    channels: int
    samples: NDArray[np.float32]
    duration_sec: float
    start_time_sec: float
    path: Optional[str] = None
@dataclass(slots=True)
class RefToken:
    idx: int
    char: str
    pinyin: str
    t_start: float
    t_end: float
    sentence_id: int
    clause_id: int
@dataclass(slots=True)
class ReferenceMap:
    lesson_id: str
    tokens: list[RefToken]
    total_duration_sec: float
@dataclass(slots=True)
class LessonManifest:
    lesson_id: str
    lesson_text: str
    sample_rate_out: int
    chunk_paths: list[str]
    reference_map_path: str
    schema_version: int = 1
    provider_name: str = "elevenlabs"
    output_format: str = "mp3_44100_128"
@dataclass(slots=True)
class PlaybackStatus:
    state: PlaybackState
    chunk_id: int
    frame_index: int
    gain: float
    generation: int
    t_host_output_sec: float
    t_ref_block_start_content_sec: float
    t_ref_block_end_content_sec: float
    t_ref_emitted_content_sec: float
    t_ref_heard_content_sec: float
@dataclass(slots=True)
class RawAsrEvent:
    event_type: AsrEventType
    text: str
    emitted_at_sec: float
@dataclass(slots=True)
class AsrEvent:
    event_type: AsrEventType
    text: str
    normalized_text: str
    chars: list[str]
    pinyin_seq: list[str]
    emitted_at_sec: float
@dataclass(slots=True)
class HypToken:
    char: str
    pinyin: str
@dataclass(slots=True)
class CandidateAlignment:
    ref_start_idx: int
    ref_end_idx: int
    score: float
    confidence: float
    matched_ref_indices: list[int] = field(default_factory=list)
    backward_jump: bool = False
    mode: str = "normal"
@dataclass(slots=True)
class AlignResult:
    committed_ref_idx: int
    candidate_ref_idx: int
    ref_time_sec: float
    confidence: float
    stable: bool
    matched_text: str = ""
    matched_pinyin: list[str] = field(default_factory=list)
    window_start_idx: int = 0
    window_end_idx: int = 0
    alignment_mode: str = "normal"
    backward_jump_detected: bool = False
    debug_score: float = 0.0
    debug_stable_run: int = 0
    debug_backward_run: int = 0
    debug_matched_count: int = 0
    debug_hyp_length: int = 0
    local_match_ratio: float = 0.0
    repeat_penalty: float = 0.0
    emitted_at_sec: float = 0.0
@dataclass(slots=True)
class SignalQuality:
    observed_at_sec: float
    rms: float
    peak: float
    vad_active: bool
    speaking_likelihood: float
    silence_run_sec: float
    clipping_ratio: float
    dropout_detected: bool
    quality_score: float
@dataclass(slots=True)
class TrackingQuality:
    overall_score: float
    observation_score: float
    temporal_consistency_score: float
    anchor_score: float
    mode: TrackingMode
    is_reliable: bool
@dataclass(slots=True)
class TrackingSnapshot:
    candidate_ref_idx: int
    committed_ref_idx: int
    candidate_ref_time_sec: float
    confidence: float
    stable: bool
    local_match_ratio: float
    repeat_penalty: float
    monotonic_consistency: float
    anchor_consistency: float
    emitted_at_sec: float
    tracking_mode: TrackingMode
    tracking_quality: TrackingQuality
    matched_text: str = ""
@dataclass(slots=True)
class ProgressEstimate:
    estimated_ref_idx: int
    estimated_ref_time_sec: float
    progress_velocity_idx_per_sec: float
    event_emitted_at_sec: float
    last_progress_at_sec: float
    progress_age_sec: float
    source_candidate_ref_idx: int
    source_committed_ref_idx: int
    tracking_mode: TrackingMode
    tracking_quality: float
    stable: bool
    confidence: float
    active_speaking: bool
    recently_progressed: bool
    user_state: UserReadState
    audio_confidence: float = 0.0
    joint_confidence: float = 0.0
    position_source: str = "text"
    audio_support_strength: float = 0.0
@dataclass(slots=True)
class ControlDecision:
    action: ControlAction
    reason: str
    target_time_sec: Optional[float] = None
    lead_sec: Optional[float] = None
    target_gain: Optional[float] = None
    replay_lockin: bool = False
    confidence: float = 0.0
    aggressiveness: str = "low"
@dataclass(slots=True)
class DeviceProfileSnapshot:
    input_device_id: str
    output_device_id: str
    input_kind: str
    output_kind: str
    input_sample_rate: int
    output_sample_rate: int
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    noise_floor_rms: float
    input_gain_hint: str
    reliability_tier: str
@dataclass(slots=True)
class LatencyCalibrationSnapshot:
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    confidence: float
    calibrated: bool
@dataclass(slots=True)
class AudioMatchSnapshot:
    estimated_ref_time_sec: float
    estimated_ref_idx_hint: int
    confidence: float
    local_similarity: float
    envelope_alignment_score: float
    onset_alignment_score: float
    band_alignment_score: float
    rhythm_consistency_score: float
    repeated_pattern_score: float
    drift_sec: float
    mode: str
    emitted_at_sec: float
    dtw_cost: float = 0.0
    dtw_path_score: float = 0.0
    dtw_coverage: float = 0.0
    coarse_candidate_rank: int = 0
    time_offset_sec: float = 0.0
@dataclass(slots=True)
class AudioBehaviorSnapshot:
    still_following_likelihood: float
    repeated_likelihood: float
    reentry_likelihood: float
    paused_likelihood: float
    confidence: float
    emitted_at_sec: float
@dataclass(slots=True)
class FusionEvidence:
    estimated_ref_time_sec: float
    estimated_ref_idx_hint: int
    text_confidence: float
    audio_confidence: float
    fused_confidence: float
    still_following_likelihood: float
    repeated_likelihood: float
    reentry_likelihood: float
    should_prevent_hold: bool
    should_prevent_seek: bool
    should_widen_reacquire_window: bool
    should_recenter_aligner_window: bool
    emitted_at_sec: float
def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+", "", text)
    return text
@dataclass(slots=True)
class Wording:
    raw_text: str = ""
    normalized_text: str = ""
    pinyins: list[str] = field(default_factory=list)
    @classmethod
    def from_text(cls, text: str) -> "Wording":
        normalized_text = _normalize_text(text)
        pinyins = lazy_pinyin(normalized_text, style=Style.TONE3)
        return cls(raw_text=text, normalized_text=normalized_text, pinyins=pinyins)
    def __len__(self) -> int:
        return len(self.pinyins)
    def __getitem__(self, key: int | slice) -> list[str]:
        return self.pinyins[key]
```

---
### 文件: `shadowing_app/tools/_bootstrap.py`

```python
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
```

---
### 文件: `shadowing_app/tools/run_shadowing.py`

```python
from __future__ import annotations
import _bootstrap
import argparse
import json
import os
import re
from pathlib import Path
import sounddevice as sd
from shadowing.audio.bluetooth_preflight import (
    BluetoothPreflightConfig,
    run_bluetooth_duplex_preflight,
    should_run_bluetooth_preflight,
)
from shadowing.audio.device_profile import normalize_device_id
from shadowing.bootstrap import build_runtime
from shadowing.llm.qwen_hotwords import extract_hotwords_with_qwen
from shadowing.realtime.capture.device_utils import pick_working_input_config
def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"
def validate_lesson_assets(lesson_dir: Path) -> None:
    manifest = lesson_dir / "lesson_manifest.json"
    ref_map = lesson_dir / "reference_map.json"
    chunks_dir = lesson_dir / "chunks"
    missing: list[str] = []
    for p in (manifest, ref_map, chunks_dir):
        if not p.exists():
            missing.append(str(p))
    if missing:
        raise FileNotFoundError(
            "Lesson assets not found. Please run preprocess first.\n" + "\n".join(missing)
        )
def load_manifest(lesson_dir: Path) -> dict:
    return json.loads((lesson_dir / "lesson_manifest.json").read_text(encoding="utf-8"))
def collect_sherpa_paths() -> dict:
    return {
        "tokens": os.getenv("SHERPA_TOKENS", ""),
        "encoder": os.getenv("SHERPA_ENCODER", ""),
        "decoder": os.getenv("SHERPA_DECODER", ""),
        "joiner": os.getenv("SHERPA_JOINER", ""),
    }
def validate_sherpa_paths(paths: dict) -> None:
    missing_keys: list[str] = []
    missing_files: list[str] = []
    env_map = {
        "tokens": "SHERPA_TOKENS",
        "encoder": "SHERPA_ENCODER",
        "decoder": "SHERPA_DECODER",
        "joiner": "SHERPA_JOINER",
    }
    for key in ("tokens", "encoder", "decoder", "joiner"):
        value = (paths.get(key) or "").strip()
        if not value:
            missing_keys.append(env_map[key])
            continue
        if not Path(value).expanduser().exists():
            missing_files.append(f"{key}: {value}")
    if missing_keys or missing_files:
        parts: list[str] = []
        if missing_keys:
            parts.append("Missing sherpa env vars: " + ", ".join(missing_keys))
        if missing_files:
            parts.append("Non-existent sherpa files:\n" + "\n".join(missing_files))
        raise FileNotFoundError("Sherpa model configuration is invalid.\n" + "\n".join(parts))
def _parse_input_device_arg(raw_value: str | None) -> int | str | None:
    if raw_value is None:
        return None
    raw = str(raw_value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw
def _parse_output_device_arg(raw_value: str | None) -> int | str | None:
    if raw_value is None:
        return None
    raw = str(raw_value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw
def _query_input_device_info(device_value: int | str | None) -> dict[str, object]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    if device_value is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            return {
                "index": None,
                "name": "unknown",
                "hostapi_name": "",
                "device_id": "",
            }
        device_value = int(default_in)
    if isinstance(device_value, int):
        dev = sd.query_devices(int(device_value))
        hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
        name = str(dev["name"])
        return {
            "index": int(device_value),
            "name": name,
            "hostapi_name": hostapi_name,
            "device_id": normalize_device_id(
                device_name=name,
                hostapi_name=hostapi_name,
                device_index=int(device_value),
            ),
        }
    target = str(device_value).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
            name = str(dev["name"])
            return {
                "index": int(idx),
                "name": name,
                "hostapi_name": hostapi_name,
                "device_id": normalize_device_id(
                    device_name=name,
                    hostapi_name=hostapi_name,
                    device_index=int(idx),
                ),
            }
    return {
        "index": None,
        "name": str(device_value),
        "hostapi_name": "",
        "device_id": normalize_device_id(device_name=str(device_value), hostapi_name=""),
    }
def _query_output_device_info(device_value: int | str | None) -> dict[str, object]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    if device_value is None:
        _, default_out = sd.default.device
        if default_out is None or int(default_out) < 0:
            return {
                "index": None,
                "name": "unknown",
                "hostapi_name": "",
                "device_id": "",
            }
        device_value = int(default_out)
    if isinstance(device_value, int):
        dev = sd.query_devices(int(device_value))
        hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
        name = str(dev["name"])
        return {
            "index": int(device_value),
            "name": name,
            "hostapi_name": hostapi_name,
            "device_id": normalize_device_id(
                device_name=name,
                hostapi_name=hostapi_name,
                device_index=int(device_value),
            ),
        }
    target = str(device_value).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_output_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
            name = str(dev["name"])
            return {
                "index": int(idx),
                "name": name,
                "hostapi_name": hostapi_name,
                "device_id": normalize_device_id(
                    device_name=name,
                    hostapi_name=hostapi_name,
                    device_index=int(idx),
                ),
            }
    return {
        "index": None,
        "name": str(device_value),
        "hostapi_name": "",
        "device_id": normalize_device_id(device_name=str(device_value), hostapi_name=""),
    }
def _run_bluetooth_preflight_or_fail(
    *,
    input_device: int | str | None,
    output_device: int | str | None,
    input_samplerate: int,
    playback_sample_rate: int,
    preflight_duration_sec: float,
    skip_bluetooth_preflight: bool,
) -> tuple[int | str | None, int | str | None, dict[str, object]]:
    if skip_bluetooth_preflight:
        return input_device, output_device, {"ran": False}
    should_run = should_run_bluetooth_preflight(
        input_device=input_device,
        output_device=output_device,
    )
    if not should_run:
        return input_device, output_device, {"ran": False}
    result = run_bluetooth_duplex_preflight(
        BluetoothPreflightConfig(
            input_device=input_device,
            output_device=output_device,
            preferred_input_samplerate=int(input_samplerate),
            preferred_output_samplerate=int(playback_sample_rate),
            duration_sec=float(preflight_duration_sec),
        )
    )
    if not result.passed:
        notes = "\n".join(f"- {x}" for x in result.notes) if result.notes else ""
        raise RuntimeError(
            "Bluetooth headset duplex preflight failed.\n"
            f"Reason: {result.failure_reason}\n"
            f"Input: {result.input_device_name!r}\n"
            f"Output: {result.output_device_name!r}\n"
            f"{notes}"
        )
    return (
        result.input_device_index,
        result.output_device_index,
        {
            "ran": True,
            "input_device_name": result.input_device_name,
            "output_device_name": result.output_device_name,
            "input_hostapi_name": result.input_hostapi_name,
            "output_hostapi_name": result.output_hostapi_name,
            "input_family_key": result.input_device_family_key,
            "output_family_key": result.output_device_family_key,
            "samplerate": result.samplerate,
        },
    )
def _normalize_for_hotwords(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", text)
    return text
def _looks_like_bad_hotword(term: str) -> bool:
    if not term:
        return True
    n = len(term)
    if n < 4 or n > 24:
        return True
    if term[0] in "的了在和与及并就也又把被将呢啊吗呀":
        return True
    if term[-1] in "的了在和与及并就也又呢啊吗呀":
        return True
    if re.fullmatch(r"[A-Za-z]+", term):
        return True
    if re.search(r"[A-Za-z]", term):
        if not re.fullmatch(r"[A-Za-z0-9一-龥]+", term):
            return True
    return False
def _split_text_to_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;：:\n\r]+", text)
    return [p.strip() for p in parts if p.strip()]
def _split_sentence_to_clauses(text: str) -> list[str]:
    parts = re.split(r"[，,、]+", text)
    return [p.strip() for p in parts if p.strip()]
def _score_hotword(term: str, whole_sentence: str) -> float:
    score = 0.0
    n = len(term)
    if 5 <= n <= 14:
        score += 5.0
    elif 4 <= n <= 18:
        score += 3.0
    else:
        score += 1.0
    if term == whole_sentence:
        score += 0.8
    if any(k in term for k in ["华为", "座舱", "车机", "微信", "周杰伦", "支付宝", "PPT", "bug"]):
        score += 2.0
    if any(k in term for k in ["技术小组", "智能座舱", "原型车", "红尾灯", "语音助手", "晚高峰"]):
        score += 2.0
    if re.search(r"\d", term):
        score += 0.8
    if _looks_like_bad_hotword(term):
        score -= 10.0
    return score
def _dedupe_by_containment(terms: list[str], max_terms: int) -> list[str]:
    kept: list[str] = []
    for term in terms:
        if any(term in existed for existed in kept if existed != term):
            continue
        kept.append(term)
        if len(kept) >= max_terms:
            break
    return kept
def _build_hotwords_from_lesson_text_local(
    lesson_text: str,
    *,
    max_terms: int = 20,
) -> list[str]:
    normalized_full = _normalize_for_hotwords(lesson_text)
    if not normalized_full:
        return []
    candidates: dict[str, float] = {}
    def add(term: str, whole_sentence: str = "") -> None:
        norm = _normalize_for_hotwords(term)
        if not norm or _looks_like_bad_hotword(norm):
            return
        score = _score_hotword(norm, _normalize_for_hotwords(whole_sentence or norm))
        old = candidates.get(norm)
        if old is None or score > old:
            candidates[norm] = score
    sentences = _split_text_to_sentences(lesson_text)
    for sent in sentences:
        sent_norm = _normalize_for_hotwords(sent)
        if not sent_norm:
            continue
        if 6 <= len(sent_norm) <= 20:
            add(sent_norm, sent_norm)
        clauses = _split_sentence_to_clauses(sent)
        for clause in clauses:
            clause_norm = _normalize_for_hotwords(clause)
            if 4 <= len(clause_norm) <= 16:
                add(clause_norm, sent_norm)
    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    ranked_terms = [k for k, _ in ranked]
    ranked_terms = _dedupe_by_containment(ranked_terms, max_terms=max_terms)
    return ranked_terms[:max_terms]
def _merge_hotwords(
    auto_terms: list[str],
    user_terms_raw: str,
    *,
    max_terms: int = 32,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    def add(term: str) -> None:
        norm = _normalize_for_hotwords(term)
        if not norm or _looks_like_bad_hotword(norm) or norm in seen:
            return
        seen.add(norm)
        merged.append(norm)
    for term in auto_terms:
        add(term)
    if user_terms_raw.strip():
        for term in re.split(r"[,，;\n]+", user_terms_raw):
            add(term)
    merged = sorted(merged, key=lambda x: (-len(x), x))
    merged = _dedupe_by_containment(merged, max_terms=max_terms)
    return merged[:max_terms]
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run shadowing realtime pipeline")
    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")
    parser.add_argument("--asr", type=str, default="sherpa", choices=["fake", "sherpa"])
    parser.add_argument("--output-device", type=str, default=None)
    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--input-samplerate", type=int, default=None)
    parser.add_argument(
        "--capture-backend",
        type=str,
        default="sounddevice",
        choices=["sounddevice", "soundcard"],
    )
    parser.add_argument("--bluetooth-offset-sec", type=float, default=0.28)
    parser.add_argument("--playback-latency", type=str, default="low")
    parser.add_argument("--playback-blocksize", type=int, default=512)
    parser.add_argument("--aligner-debug", action="store_true")
    parser.add_argument("--asr-debug-feed", action="store_true")
    parser.add_argument("--asr-debug-feed-every", type=int, default=20)
    parser.add_argument("--skip-bluetooth-preflight", action="store_true")
    parser.add_argument("--preflight-duration-sec", type=float, default=6.0)
    parser.add_argument("--tick-sleep-sec", type=float, default=0.02)
    parser.add_argument("--profile-path", type=str, default="runtime/device_profiles.json")
    parser.add_argument("--session-dir", type=str, default="runtime/latest_session")
    parser.add_argument("--event-logging", action="store_true")
    parser.add_argument("--startup-grace-sec", type=float, default=3.2)
    parser.add_argument("--low-confidence-hold-sec", type=float, default=2.2)
    parser.add_argument("--hotwords", type=str, default="")
    parser.add_argument("--hotwords-score", type=float, default=1.8)
    parser.add_argument("--disable-auto-hotwords", action="store_true")
    parser.add_argument("--print-hotwords", action="store_true")
    parser.add_argument(
        "--hotwords-source",
        type=str,
        default="qwen",
        choices=["qwen", "local", "none"],
        help="热词来源：qwen / local / none",
    )
    parser.add_argument(
        "--qwen-api-key",
        type=str,
        default=os.getenv("DASHSCOPE_API_KEY", ""),
        help="DashScope API Key，默认读环境变量 DASHSCOPE_API_KEY",
    )
    parser.add_argument(
        "--qwen-model",
        type=str,
        default=os.getenv("QWEN_CHAT_MODEL", "qwen-plus"),
        help="Qwen 模型名，默认 qwen-plus",
    )
    parser.add_argument("--qwen-max-hotwords", type=int, default=24, help="Qwen 提取热词最大数量")
    parser.add_argument("--force-bluetooth-long-session-mode", action="store_true")
    return parser
def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")
    lesson_text = text_path.read_text(encoding="utf-8").strip()
    if not lesson_text:
        raise ValueError(f"Text file is empty: {text_path}")
    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    lesson_dir = lesson_base_dir / lesson_id
    validate_lesson_assets(lesson_dir)
    manifest = load_manifest(lesson_dir)
    playback_sample_rate = int(manifest["sample_rate_out"])
    parsed_input_device = _parse_input_device_arg(args.input_device)
    parsed_output_device = _parse_output_device_arg(args.output_device)
    rec_cfg = pick_working_input_config(
        preferred_device=parsed_input_device if isinstance(parsed_input_device, int) else None,
        preferred_name_substring=parsed_input_device if isinstance(parsed_input_device, str) else None,
        preferred_rates=(
            [args.input_samplerate, 48000, 44100, 16000]
            if args.input_samplerate is not None
            else [48000, 44100, 16000]
        ),
    ) or {
        "device": parsed_input_device,
        "samplerate": args.input_samplerate or 48000,
    }
    if args.input_samplerate is not None:
        rec_cfg["samplerate"] = args.input_samplerate
    effective_input_device = rec_cfg["device"]
    effective_input_samplerate = int(rec_cfg["samplerate"])
    sherpa_paths = collect_sherpa_paths()
    if args.asr == "sherpa":
        validate_sherpa_paths(sherpa_paths)
    effective_input_device, effective_output_device, preflight_meta = _run_bluetooth_preflight_or_fail(
        input_device=effective_input_device,
        output_device=parsed_output_device,
        input_samplerate=effective_input_samplerate,
        playback_sample_rate=playback_sample_rate,
        preflight_duration_sec=float(args.preflight_duration_sec),
        skip_bluetooth_preflight=bool(args.skip_bluetooth_preflight),
    )
    input_info = _query_input_device_info(effective_input_device)
    output_info = _query_output_device_info(effective_output_device)
    if bool(preflight_meta.get("ran", False)):
        if str(preflight_meta.get("input_device_name", "")).strip():
            input_info["name"] = str(preflight_meta["input_device_name"])
        if str(preflight_meta.get("output_device_name", "")).strip():
            output_info["name"] = str(preflight_meta["output_device_name"])
        preflight_hostapi = str(preflight_meta.get("input_hostapi_name", "")).strip()
        if preflight_hostapi:
            input_info["hostapi_name"] = preflight_hostapi
            if not str(output_info.get("hostapi_name", "")).strip():
                output_info["hostapi_name"] = preflight_hostapi
    input_device_name = str(input_info.get("name", "unknown"))
    output_device_name = str(output_info.get("name", "unknown"))
    hostapi_name = str(input_info.get("hostapi_name", "") or output_info.get("hostapi_name", "") or "").strip()
    input_device_id = str(input_info.get("device_id", "")).strip()
    output_device_id = str(output_info.get("device_id", "")).strip()
    bluetooth_mode = bool(
        should_run_bluetooth_preflight(
            input_device=effective_input_device,
            output_device=effective_output_device,
        )
    )
    auto_hotwords: list[str] = []
    if not args.disable_auto_hotwords and args.hotwords_source != "none":
        if args.hotwords_source == "qwen":
            if args.qwen_api_key.strip():
                auto_hotwords = extract_hotwords_with_qwen(
                    lesson_text=lesson_text,
                    api_key=args.qwen_api_key.strip(),
                    model=args.qwen_model.strip(),
                    max_terms=int(args.qwen_max_hotwords),
                )
                if not auto_hotwords:
                    auto_hotwords = _build_hotwords_from_lesson_text_local(
                        lesson_text,
                        max_terms=min(20, int(args.qwen_max_hotwords)),
                    )
            else:
                auto_hotwords = _build_hotwords_from_lesson_text_local(
                    lesson_text,
                    max_terms=min(20, int(args.qwen_max_hotwords)),
                )
        elif args.hotwords_source == "local":
            auto_hotwords = _build_hotwords_from_lesson_text_local(
                lesson_text,
                max_terms=min(20, int(args.qwen_max_hotwords)),
            )
    merged_hotwords = _merge_hotwords(
        auto_terms=auto_hotwords,
        user_terms_raw=str(args.hotwords or ""),
        max_terms=max(16, min(32, int(args.qwen_max_hotwords))),
    )
    hotwords_str = "\n".join(merged_hotwords)
    if args.print_hotwords and merged_hotwords:
        for term in merged_hotwords:
    runtime = build_runtime(
        {
            "lesson_base_dir": str(lesson_base_dir),
            "playback": {
                "sample_rate": playback_sample_rate,
                "channels": 1,
                "device": effective_output_device,
                "latency": args.playback_latency,
                "blocksize": int(args.playback_blocksize),
                "bluetooth_output_offset_sec": float(args.bluetooth_offset_sec),
            },
            "capture": {
                "backend": str(args.capture_backend),
                "device_sample_rate": effective_input_samplerate,
                "target_sample_rate": 16000,
                "channels": 1,
                "device": effective_input_device,
                "dtype": "float32",
                "blocksize": 0,
                "latency": "low",
            },
            "asr": {
                "mode": args.asr,
                "tokens": sherpa_paths.get("tokens", ""),
                "encoder": sherpa_paths.get("encoder", ""),
                "decoder": sherpa_paths.get("decoder", ""),
                "joiner": sherpa_paths.get("joiner", ""),
                "sample_rate": 16000,
                "emit_partial_interval_sec": 0.08,
                "enable_endpoint": True,
                "debug_feed": bool(args.asr_debug_feed),
                "debug_feed_every_n_chunks": int(args.asr_debug_feed_every),
                "num_threads": 2,
                "provider": "cpu",
                "feature_dim": 80,
                "decoding_method": "greedy_search",
                "rule1_min_trailing_silence": 1.2,
                "rule2_min_trailing_silence": 0.8,
                "rule3_min_utterance_length": 12.0,
                "hotwords": hotwords_str,
                "hotwords_score": float(args.hotwords_score),
                "min_meaningful_text_len": 2,
                "endpoint_min_interval_sec": 0.35,
                "reset_on_empty_endpoint": False,
                "preserve_stream_on_partial_only": True,
                "force_reset_after_empty_endpoints": 999999999,
                "info_logging": True,
                "log_hotwords_on_start": True,
                "log_hotwords_preview_on_start": True,
                "hotwords_preview_limit": 12,
            },
            "alignment": {
                "window_back": 8,
                "window_ahead": 40,
                "stable_hits": 2,
                "min_confidence": 0.60,
                "debug": bool(args.aligner_debug),
            },
            "control": {
                "target_lead_sec": 0.18,
                "hold_if_lead_sec": 1.05,
                "resume_if_lead_sec": 0.36,
                "seek_if_lag_sec": -2.60,
                "min_confidence": 0.70,
                "seek_cooldown_sec": 2.20,
                "gain_following": 0.52,
                "gain_transition": 0.72,
                "gain_soft_duck": 0.36,
                "startup_grace_sec": float(args.startup_grace_sec),
                "low_confidence_hold_sec": float(args.low_confidence_hold_sec),
                "guide_play_sec": 3.20,
                "no_progress_hold_min_play_sec": 5.80,
                "progress_stale_sec": 1.45,
                "hold_trend_sec": 1.00,
                "tracking_quality_hold_min": 0.60,
                "tracking_quality_seek_min": 0.84,
                "resume_from_hold_speaking_lead_slack_sec": 0.72,
                "disable_seek": False,
                "bluetooth_long_session_target_lead_sec": 0.38,
                "bluetooth_long_session_hold_if_lead_sec": 1.35,
                "bluetooth_long_session_resume_if_lead_sec": 0.30,
                "bluetooth_long_session_seek_if_lag_sec": -3.20,
                "bluetooth_long_session_seek_cooldown_sec": 3.20,
                "bluetooth_long_session_progress_stale_sec": 1.75,
                "bluetooth_long_session_hold_trend_sec": 1.15,
                "bluetooth_long_session_tracking_quality_hold_min": 0.58,
                "bluetooth_long_session_tracking_quality_seek_min": 0.88,
                "bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec": 0.82,
                "bluetooth_long_session_gain_following": 0.50,
                "bluetooth_long_session_gain_transition": 0.66,
                "bluetooth_long_session_gain_soft_duck": 0.32,
            },
            "runtime": {
                "audio_queue_maxsize": 150,
                "asr_event_queue_maxsize": 64,
                "loop_interval_sec": float(args.tick_sleep_sec),
            },
            "signal": {
                "min_vad_rms": 0.006,
                "vad_noise_multiplier": 2.8,
            },
            "adaptation": {
                "profile_path": str(Path(args.profile_path).expanduser().resolve()),
            },
            "session": {
                "session_dir": str(Path(args.session_dir).expanduser().resolve()),
                "event_logging": bool(args.event_logging),
            },
            "device_context": {
                "input_device_name": input_device_name,
                "output_device_name": output_device_name,
                "input_device_id": input_device_id,
                "output_device_id": output_device_id,
                "hostapi_name": hostapi_name,
                "input_sample_rate": int(effective_input_samplerate),
                "output_sample_rate": int(playback_sample_rate),
                "noise_floor_rms": 0.0025,
                "bluetooth_mode": bluetooth_mode,
                "bluetooth_long_session_mode": bool(args.force_bluetooth_long_session_mode),
                "preflight_ran": bool(preflight_meta.get("ran", False)),
            },
            "debug": {
                "enabled": False,
            },
        }
    )
    runtime.run(lesson_id)
if __name__ == "__main__":
    main()
```

