# 项目快照

自动生成的项目代码快照。已移除 Python 注释与文档字符串。

---
### 文件: `shadowing_app/src/shadowing/adaptation/profile_store.py`

```python
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
    startup_profile_decided: bool = False
    last_tuned_at_sec: float = 0.0
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
    }

    _HARD_BOUNDS = {
        "guide_play_sec": (1.4, 4.2),
        "no_progress_hold_min_play_sec": (2.5, 6.5),
        "progress_stale_sec": (0.8, 1.9),
        "hold_trend_sec": (0.45, 1.30),
        "tracking_quality_hold_min": (0.50, 0.82),
        "tracking_quality_seek_min": (0.64, 0.90),
        "resume_from_hold_speaking_lead_slack_sec": (0.25, 0.90),
        "gain_soft_duck": (0.28, 0.55),
    }

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

        if (now_sec - self.state.last_tuned_at_sec) < 1.2:
            return {}

        if (
            progress is not None
            and self.state.last_good_control
            and progress.tracking_quality < max(0.50, self.state.best_tracking_quality - 0.14)
            and progress.tracking_mode.value in ("reacquiring", "lost")
        ):
            self._restore_control(controller_policy, self.state.last_good_control)
            self.state.last_tuned_at_sec = float(now_sec)
            return dict(self.state.last_good_control)

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
                updates["guide_play_sec"] = controller_policy.guide_play_sec + 0.6
                updates["no_progress_hold_min_play_sec"] = controller_policy.no_progress_hold_min_play_sec + 0.8
                updates["progress_stale_sec"] = controller_policy.progress_stale_sec + 0.14
                updates["resume_from_hold_speaking_lead_slack_sec"] = (
                    controller_policy.resume_from_hold_speaking_lead_slack_sec + 0.12
                )
                updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min + 0.02

            elif speaker_style == "fast":
                updates["progress_stale_sec"] = controller_policy.progress_stale_sec - 0.10
                updates["hold_trend_sec"] = controller_policy.hold_trend_sec - 0.08
                updates["resume_from_hold_speaking_lead_slack_sec"] = (
                    controller_policy.resume_from_hold_speaking_lead_slack_sec + 0.08
                )

            if self.state.environment_style == "noisy":
                updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min + 0.04
                updates["tracking_quality_seek_min"] = controller_policy.tracking_quality_seek_min + 0.04
                signal_monitor.vad_noise_multiplier = min(4.2, signal_monitor.vad_noise_multiplier + 0.20)

        if startup_false_hold_count >= 1:
            updates["guide_play_sec"] = controller_policy.guide_play_sec + 0.25
            updates["no_progress_hold_min_play_sec"] = controller_policy.no_progress_hold_min_play_sec + 0.35
            updates["hold_trend_sec"] = controller_policy.hold_trend_sec + 0.05

        if progress is not None:
            if (
                progress.tracking_quality < 0.55
                and progress.active_speaking
                and progress.progress_age_sec < 1.2
            ):
                updates["gain_soft_duck"] = controller_policy.gain_soft_duck - 0.03
                updates["resume_from_hold_speaking_lead_slack_sec"] = (
                    controller_policy.resume_from_hold_speaking_lead_slack_sec + 0.04
                )

            if (
                progress.tracking_quality >= 0.80
                and progress.tracking_mode.value == "locked"
                and mean_tracking_quality >= 0.76
            ):
                updates["tracking_quality_seek_min"] = controller_policy.tracking_quality_seek_min - 0.01

        if lost_count >= 2 or reacquire_count >= 3:
            updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min + 0.03
            updates["tracking_quality_seek_min"] = controller_policy.tracking_quality_seek_min + 0.03
            updates["hold_trend_sec"] = controller_policy.hold_trend_sec + 0.05
            updates["progress_stale_sec"] = controller_policy.progress_stale_sec + 0.06

        if mean_tracking_quality >= 0.82 and startup_false_hold_count == 0 and lost_count == 0:
            updates["tracking_quality_hold_min"] = controller_policy.tracking_quality_hold_min - 0.01
            updates["hold_trend_sec"] = controller_policy.hold_trend_sec - 0.02

        if latency_snapshot is not None and hasattr(player, "set_output_offset_sec"):
            player.set_output_offset_sec(
                max(0.0, float(latency_snapshot.estimated_output_latency_ms) / 1000.0)
            )

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
### 文件: `shadowing_app/src/shadowing/audio/bluetooth_preflight.py`

```python
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd


@dataclass(slots=True)
class ResolvedDevice:
    index: int
    name: str
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
    output_device_index: int | None = None
    output_device_name: str = ""
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

    return normalized


def _resolve_hostapi_name(dev: dict) -> str:
    hostapis = sd.query_hostapis()
    return str(hostapis[int(dev["hostapi"])]["name"])


def _resolve_input_device(device: int | str | None) -> ResolvedDevice:
    devices = sd.query_devices()

    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Resolved input device is not an input device: idx={device}, name={dev['name']}")
        return ResolvedDevice(
            index=int(device),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    if device is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            raise RuntimeError("No default input device available for bluetooth preflight.")
        dev = sd.query_devices(int(default_in))
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Default input device is invalid: idx={default_in}, name={dev['name']}")
        return ResolvedDevice(
            index=int(default_in),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return ResolvedDevice(
                index=int(idx),
                name=str(dev["name"]),
                max_input_channels=int(dev["max_input_channels"]),
                max_output_channels=int(dev["max_output_channels"]),
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=_resolve_hostapi_name(dev),
            )

    raise RuntimeError(f"No matching input device found for bluetooth preflight: {device!r}")


def _resolve_output_device(device: int | str | None) -> ResolvedDevice:
    devices = sd.query_devices()

    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_output_channels"]) <= 0:
            raise RuntimeError(f"Resolved output device is not an output device: idx={device}, name={dev['name']}")
        return ResolvedDevice(
            index=int(device),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    if device is None:
        _, default_out = sd.default.device
        if default_out is None or int(default_out) < 0:
            raise RuntimeError("No default output device available for bluetooth preflight.")
        dev = sd.query_devices(int(default_out))
        if int(dev["max_output_channels"]) <= 0:
            raise RuntimeError(f"Default output device is invalid: idx={default_out}, name={dev['name']}")
        return ResolvedDevice(
            index=int(default_out),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_output_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return ResolvedDevice(
                index=int(idx),
                name=str(dev["name"]),
                max_input_channels=int(dev["max_input_channels"]),
                max_output_channels=int(dev["max_output_channels"]),
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=_resolve_hostapi_name(dev),
            )

    raise RuntimeError(f"No matching output device found for bluetooth preflight: {device!r}")


def should_run_bluetooth_preflight(input_device: int | str | None, output_device: int | str | None) -> bool:
    try:
        input_resolved = _resolve_input_device(input_device)
        output_resolved = _resolve_output_device(output_device)
    except Exception:
        return False

    input_is_bt = _looks_like_bluetooth(input_resolved.name)
    output_is_bt = _looks_like_bluetooth(output_resolved.name)
    return bool(input_is_bt and output_is_bt)


def _pick_duplex_samplerate(
    input_dev: ResolvedDevice,
    output_dev: ResolvedDevice,
    preferred_input_sr: int,
    preferred_output_sr: int,
) -> int:
    candidates: list[int] = []

    for sr in (
        preferred_input_sr,
        48000,
        32000,
        24000,
        16000,
        preferred_output_sr,
        int(input_dev.default_samplerate),
        int(output_dev.default_samplerate),
        44100,
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


def run_bluetooth_duplex_preflight(config: BluetoothPreflightConfig) -> BluetoothPreflightResult:
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
        input_device_name=input_dev.name,
        output_device_index=output_dev.index,
        output_device_name=output_dev.name,
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

        now = time.monotonic()
        elapsed = now - started_at

        if status:
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
        tone = config.probe_tone_amp * np.sin(2.0 * np.pi * config.probe_tone_hz * t).astype(np.float32, copy=False)
        tone_phase += frames
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
            print(
                "[BT-PREFLIGHT] 已进入蓝牙耳机双工预检。"
                "请在接下来 4 秒内持续说话，同时确认耳机中能听到轻微提示音。"
            )
            done.wait(timeout=max(1.0, config.duration_sec + 1.5))
    except Exception as e:
        result.failure_reason = (
            "bluetooth_duplex_open_failed: "
            f"input={input_dev.name!r}, output={output_dev.name!r}, samplerate={samplerate}, error={e}"
        )
        return result

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

    if status_events > config.max_status_events:
        failure_reasons.append(
            f"status_events_too_many({status_events}>{config.max_status_events})"
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


def _looks_like_bluetooth(name: str) -> bool:
    text = (name or "").strip().lower()
    if not text:
        return False
    return any(k in text for k in _BLUETOOTH_KEYWORDS)
@dataclass(slots=True)
class DeviceProfile:
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


def _normalize_device_name(device_name: int | str | None) -> str:
    if device_name is None:
        return ""
    return str(device_name).strip().lower()


def classify_input_device(device_name: int | str | None) -> str:
    name = _normalize_device_name(device_name)
    if not name:
        return "unknown"
    if _looks_like_bluetooth(name):
        return "bluetooth_headset"
    if "usb" in name or "麦克风" in name or "microphone" in name:
        return "usb_mic"
    if "阵列" in name or "array" in name or "realtek" in name:
        return "builtin_mic"
    return "unknown"


def classify_output_device(device_name: int | str | None) -> str:
    name = _normalize_device_name(device_name)
    if not name:
        return "unknown"
    if _looks_like_bluetooth(name):
        return "bluetooth_headset"
    if "speaker" in name or "扬声器" in name:
        return "speaker"
    if "usb" in name:
        return "wired_headset"
    return "unknown"


def infer_input_gain_hint(noise_floor_rms: float) -> str:
    if noise_floor_rms < 0.0015:
        return "high"
    if noise_floor_rms < 0.004:
        return "normal"
    return "low"


def infer_reliability_tier(input_kind: str, output_kind: str) -> str:
    if input_kind == "bluetooth_headset" or output_kind == "bluetooth_headset":
        return "low"
    if input_kind == "unknown" or output_kind == "unknown":
        return "medium"
    return "high"


def default_input_latency_ms(input_kind: str) -> float:
    if input_kind == "bluetooth_headset":
        return 140.0
    if input_kind == "usb_mic":
        return 35.0
    if input_kind == "builtin_mic":
        return 28.0
    return 50.0


def default_output_latency_ms(output_kind: str) -> float:
    if output_kind == "bluetooth_headset":
        return 180.0
    if output_kind == "wired_headset":
        return 40.0
    if output_kind == "speaker":
        return 35.0
    return 60.0


def build_device_profile(
    input_device_name: int | str | None,
    output_device_name: int | str | None,
    input_sample_rate: int,
    output_sample_rate: int,
    noise_floor_rms: float,
) -> DeviceProfile:
    input_kind = classify_input_device(input_device_name)
    output_kind = classify_output_device(output_device_name)

    return DeviceProfile(
        input_device_id=str(input_device_name if input_device_name is not None else "unknown"),
        output_device_id=str(output_device_name if output_device_name is not None else "unknown"),
        input_kind=input_kind,
        output_kind=output_kind,
        input_sample_rate=int(input_sample_rate),
        output_sample_rate=int(output_sample_rate),
        estimated_input_latency_ms=float(default_input_latency_ms(input_kind)),
        estimated_output_latency_ms=float(default_output_latency_ms(output_kind)),
        noise_floor_rms=float(noise_floor_rms),
        input_gain_hint=infer_input_gain_hint(noise_floor_rms),
        reliability_tier=infer_reliability_tier(input_kind, output_kind),
    )
```

---
### 文件: `shadowing_app/src/shadowing/audio/latency_calibrator.py`

```python
from __future__ import annotations

from dataclasses import dataclass

from shadowing.audio.device_profile import DeviceProfile
from shadowing.types import SignalQuality


@dataclass(slots=True)
class LatencyCalibrationState:
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    confidence: float
    calibrated: bool


class LatencyCalibrator:
    def __init__(
        self,
        input_latency_adapt_ms: float = 8.0,
        output_latency_adapt_ms: float = 14.0,
        target_shadow_lead_sec: float = 0.15,
        min_tracking_quality: float = 0.82,
        min_sync_hits_before_update: int = 3,
    ) -> None:
        self.input_latency_adapt_ms = float(input_latency_adapt_ms)
        self.output_latency_adapt_ms = float(output_latency_adapt_ms)
        self.target_shadow_lead_sec = float(target_shadow_lead_sec)
        self.min_tracking_quality = float(min_tracking_quality)
        self.min_sync_hits_before_update = max(1, int(min_sync_hits_before_update))

        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._reliable_sync_hits = 0

    def reset(self, device_profile: DeviceProfile) -> None:
        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            confidence=0.20,
            calibrated=False,
        )
        self._last_active_at_sec = 0.0
        self._reliable_sync_hits = 0

    def observe_signal(self, signal_quality: SignalQuality) -> None:
        if self._state is None:
            return
        if signal_quality.vad_active or signal_quality.speaking_likelihood >= 0.48:
            self._last_active_at_sec = float(signal_quality.observed_at_sec)

    def observe_sync(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        user_ref_time_sec: float,
        tracking_quality: float,
        stable: bool,
        active_speaking: bool,
    ) -> None:
        if self._state is None:
            return
        if not stable:
            self._reliable_sync_hits = 0
            return
        if tracking_quality < self.min_tracking_quality:
            self._reliable_sync_hits = 0
            return
        if not active_speaking:
            self._reliable_sync_hits = 0
            return
        if self._last_active_at_sec <= 0.0:
            self._reliable_sync_hits = 0
            return
        if (float(now_sec) - self._last_active_at_sec) > 0.80:
            self._reliable_sync_hits = 0
            return

        lead_sec = float(playback_ref_time_sec) - float(user_ref_time_sec)
        if abs(lead_sec) > 3.0:
            self._reliable_sync_hits = 0
            return

        self._reliable_sync_hits += 1
        if self._reliable_sync_hits < self.min_sync_hits_before_update:
            return

        lead_error_sec = lead_sec - self.target_shadow_lead_sec
        lead_error_ms = lead_error_sec * 1000.0

        if lead_error_ms > 20.0:
            self._state.estimated_output_latency_ms = min(
                320.0,
                self._state.estimated_output_latency_ms + min(
                    self.output_latency_adapt_ms,
                    lead_error_ms * 0.10,
                ),
            )
        elif lead_error_ms < -20.0:
            self._state.estimated_output_latency_ms = max(
                10.0,
                self._state.estimated_output_latency_ms - min(
                    self.output_latency_adapt_ms,
                    abs(lead_error_ms) * 0.10,
                ),
            )

        if self._reliable_sync_hits >= (self.min_sync_hits_before_update + 3) and abs(lead_error_ms) > 60.0:
            direction = 1.0 if lead_error_ms > 0 else -1.0
            self._state.estimated_input_latency_ms = min(
                260.0,
                max(
                    10.0,
                    self._state.estimated_input_latency_ms + (self.input_latency_adapt_ms * direction * 0.18),
                ),
            )

        self._state.confidence = min(0.95, self._state.confidence + 0.035)
        self._state.calibrated = self._state.confidence >= 0.60

    def snapshot(self) -> LatencyCalibrationState | None:
        return self._state
```

---
### 文件: `shadowing_app/src/shadowing/bootstrap.py`

```python
from __future__ import annotations

from shadowing.adaptation.profile_store import ProfileStore
from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig, FakeAsrStep
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.capture.soundcard_recorder import SoundCardRecorder
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.playback.sounddevice_player import PlaybackConfig, SoundDevicePlayer
from shadowing.realtime.runtime import RealtimeRuntimeConfig, ShadowingRuntime
from shadowing.telemetry.event_logger import EventLogger
from shadowing.types import AsrEventType


def _build_fake_asr_config(asr_cfg: dict) -> FakeAsrConfig:
    scripted_steps_raw = asr_cfg.get("scripted_steps", [])
    scripted_steps: list[FakeAsrStep] = []

    for item in scripted_steps_raw:
        if isinstance(item, FakeAsrStep):
            scripted_steps.append(item)
            continue

        if not isinstance(item, dict):
            raise ValueError(f"Invalid fake ASR scripted step: {item!r}")

        event_type_raw = str(item.get("event_type", "partial")).lower()
        event_type = AsrEventType.FINAL if event_type_raw == "final" else AsrEventType.PARTIAL

        scripted_steps.append(
            FakeAsrStep(
                offset_sec=float(item.get("offset_sec", 0.0)),
                text=str(item.get("text", "")),
                event_type=event_type,
            )
        )

    return FakeAsrConfig(
        scripted_steps=scripted_steps,
        reference_text=str(asr_cfg.get("reference_text", "")),
        chars_per_sec=float(asr_cfg.get("chars_per_sec", 4.0)),
        emit_partial_interval_sec=float(asr_cfg.get("emit_partial_interval_sec", 0.10)),
        emit_final_on_endpoint=bool(asr_cfg.get("emit_final_on_endpoint", True)),
        sample_rate=int(asr_cfg.get("sample_rate", 16000)),
        bytes_per_sample=int(asr_cfg.get("bytes_per_sample", 2)),
        channels=int(asr_cfg.get("channels", 1)),
        vad_rms_threshold=float(asr_cfg.get("vad_rms_threshold", 0.01)),
        vad_min_active_ms=float(asr_cfg.get("vad_min_active_ms", 30.0)),
    )


def build_runtime(config: dict) -> ShadowingRuntime:
    repo = FileLessonRepository(config["lesson_base_dir"])

    playback_cfg = config["playback"]
    player = SoundDevicePlayer(
        PlaybackConfig(
            sample_rate=int(playback_cfg["sample_rate"]),
            channels=int(playback_cfg.get("channels", 1)),
            device=playback_cfg.get("device"),
            latency=playback_cfg.get("latency", "low"),
            blocksize=int(playback_cfg.get("blocksize", 0)),
            bluetooth_output_offset_sec=float(playback_cfg.get("bluetooth_output_offset_sec", 0.0)),
        )
    )

    capture_cfg = config["capture"]
    capture_backend = str(capture_cfg.get("backend", "sounddevice")).strip().lower()
    if capture_backend == "soundcard":
        recorder = SoundCardRecorder(
            sample_rate_in=int(capture_cfg["device_sample_rate"]),
            target_sample_rate=int(capture_cfg["target_sample_rate"]),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            block_frames=int(capture_cfg.get("block_frames", capture_cfg.get("blocksize", 1440))),
            include_loopback=bool(capture_cfg.get("include_loopback", False)),
            debug_level_meter=bool(capture_cfg.get("debug_level_meter", False)),
            debug_level_every_n_blocks=int(capture_cfg.get("debug_level_every_n_blocks", 20)),
        )
    else:
        recorder = SoundDeviceRecorder(
            sample_rate_in=int(capture_cfg["device_sample_rate"]),
            target_sample_rate=int(capture_cfg["target_sample_rate"]),
            channels=int(capture_cfg.get("channels", 1)),
            device=capture_cfg.get("device"),
            dtype=capture_cfg.get("dtype", "float32"),
            blocksize=int(capture_cfg.get("blocksize", 0)),
            latency=capture_cfg.get("latency", "low"),
        )

    asr_cfg = config["asr"]
    asr_mode = str(asr_cfg.get("mode", "sherpa")).lower()
    if asr_mode == "fake":
        asr = FakeASRProvider(_build_fake_asr_config(asr_cfg))
    else:
        asr = SherpaStreamingProvider(
            model_config=asr_cfg,
            hotwords=str(asr_cfg.get("hotwords", "")),
            sample_rate=int(asr_cfg.get("sample_rate", 16000)),
            emit_partial_interval_sec=float(asr_cfg.get("emit_partial_interval_sec", 0.08)),
            enable_endpoint=bool(asr_cfg.get("enable_endpoint", True)),
            debug_feed=bool(asr_cfg.get("debug_feed", False)),
            debug_feed_every_n_chunks=int(asr_cfg.get("debug_feed_every_n_chunks", 20)),
        )

    align_cfg = config.get("alignment", {})
    aligner = IncrementalAligner(
        window_back=int(align_cfg.get("window_back", 8)),
        window_ahead=int(align_cfg.get("window_ahead", 40)),
        stable_frames=int(align_cfg.get("stable_frames", 2)),
        min_confidence=float(align_cfg.get("min_confidence", 0.60)),
        backward_lock_frames=int(align_cfg.get("backward_lock_frames", 3)),
        clause_boundary_bonus=float(align_cfg.get("clause_boundary_bonus", 0.15)),
        cross_clause_backward_extra_penalty=float(
            align_cfg.get("cross_clause_backward_extra_penalty", 0.20)
        ),
        debug=bool(align_cfg.get("debug", False)),
        max_hyp_tokens=int(align_cfg.get("max_hyp_tokens", 16)),
    )

    control_cfg = config.get("control", {})
    policy = ControlPolicy(
        target_lead_sec=float(control_cfg.get("target_lead_sec", 0.15)),
        hold_if_lead_sec=float(control_cfg.get("hold_if_lead_sec", 0.90)),
        resume_if_lead_sec=float(control_cfg.get("resume_if_lead_sec", 0.28)),
        seek_if_lag_sec=float(control_cfg.get("seek_if_lag_sec", -1.80)),
        min_confidence=float(control_cfg.get("min_confidence", 0.75)),
        seek_cooldown_sec=float(control_cfg.get("seek_cooldown_sec", 1.20)),
        gain_following=float(control_cfg.get("gain_following", 0.55)),
        gain_transition=float(control_cfg.get("gain_transition", 0.80)),
        gain_soft_duck=float(control_cfg.get("gain_soft_duck", 0.42)),
        recover_after_seek_sec=float(control_cfg.get("recover_after_seek_sec", 0.60)),
        startup_grace_sec=float(control_cfg.get("startup_grace_sec", 0.80)),
        low_confidence_hold_sec=float(control_cfg.get("low_confidence_hold_sec", 0.60)),
        bootstrapping_sec=float(control_cfg.get("bootstrapping_sec", 1.80)),
        guide_play_sec=float(control_cfg.get("guide_play_sec", 2.20)),
        no_progress_hold_min_play_sec=float(control_cfg.get("no_progress_hold_min_play_sec", 4.00)),
        speaking_recent_sec=float(control_cfg.get("speaking_recent_sec", 0.90)),
        progress_stale_sec=float(control_cfg.get("progress_stale_sec", 1.10)),
        hold_trend_sec=float(control_cfg.get("hold_trend_sec", 0.75)),
        hold_extra_lead_sec=float(control_cfg.get("hold_extra_lead_sec", 0.18)),
        low_confidence_continue_sec=float(control_cfg.get("low_confidence_continue_sec", 1.40)),
        tracking_quality_hold_min=float(control_cfg.get("tracking_quality_hold_min", 0.60)),
        tracking_quality_seek_min=float(control_cfg.get("tracking_quality_seek_min", 0.72)),
        resume_from_hold_event_fresh_sec=float(control_cfg.get("resume_from_hold_event_fresh_sec", 0.45)),
        resume_from_hold_speaking_lead_slack_sec=float(
            control_cfg.get("resume_from_hold_speaking_lead_slack_sec", 0.45)
        ),
        reacquire_soft_duck_sec=float(control_cfg.get("reacquire_soft_duck_sec", 2.00)),
        disable_seek=bool(control_cfg.get("disable_seek", False)),
    )
    controller = StateMachineController(
        policy=policy,
        disable_seek=bool(control_cfg.get("disable_seek", False)),
    )

    runtime_cfg = config.get("runtime", {})
    adaptation_cfg = config.get("adaptation", {})
    session_cfg = config.get("session", {})

    profile_store = None
    if adaptation_cfg.get("profile_path"):
        profile_store = ProfileStore(str(adaptation_cfg["profile_path"]))

    event_logger = None
    session_dir = session_cfg.get("session_dir")
    if session_dir:
        event_logger = EventLogger(str(session_dir), enabled=bool(session_cfg.get("event_logging", True)))

    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
        device_context=dict(config.get("device_context", {})),
        signal_monitor=SignalQualityMonitor(
            min_vad_rms=float(config.get("signal", {}).get("min_vad_rms", 0.006)),
            vad_noise_multiplier=float(config.get("signal", {}).get("vad_noise_multiplier", 2.8)),
        ),
        latency_calibrator=LatencyCalibrator(),
        auto_tuner=RuntimeAutoTuner(),
        profile_store=profile_store,
        event_logger=event_logger,
        audio_queue_maxsize=int(runtime_cfg.get("audio_queue_maxsize", 150)),
        asr_event_queue_maxsize=int(runtime_cfg.get("asr_event_queue_maxsize", 64)),
        loop_interval_sec=float(runtime_cfg.get("loop_interval_sec", 0.03)),
        debug=bool(config.get("debug", {}).get("enabled", False)),
    )

    return ShadowingRuntime(
        orchestrator=orchestrator,
        config=RealtimeRuntimeConfig(
            tick_sleep_sec=float(runtime_cfg.get("loop_interval_sec", 0.03)),
        ),
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

from abc import ABC, abstractmethod

from shadowing.types import ControlDecision, PlaybackStatus, ProgressEstimate, SignalQuality


class Controller(ABC):
    @abstractmethod
    def decide(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> ControlDecision: ...
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
        speaking_decay: float = 0.92,
        speaking_rise: float = 0.22,
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
        if (
            self.state.last_observed_at_sec > 0.0
            and observed_at_sec >= self.state.last_observed_at_sec
        ):
            dt_sec = float(observed_at_sec - self.state.last_observed_at_sec)
            
        noise_floor = self.state.noise_floor_rms
        dynamic_threshold = max(self.min_vad_rms, noise_floor * self.vad_noise_multiplier)
        vad_active = rms >= dynamic_threshold and peak >= max(0.012, dynamic_threshold * 1.2)

        if vad_active:
            self.state.last_active_at_sec = observed_at_sec
            self.state.speaking_likelihood = min(
                1.0,
                self.state.speaking_likelihood * self.speaking_decay + self.speaking_rise + 0.10,
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
        silence_run = 9999.0 if self.state.last_active_at_sec <= 0.0 else max(
            0.0,
            now_sec - self.state.last_active_at_sec,
        )

        freshness_penalty = 0.0
        if last_seen > 0.0:
            freshness_penalty = min(0.35, max(0.0, now_sec - last_seen) * 0.30)

        base_quality = 0.50
        base_quality += min(0.20, self.state.last_peak * 0.6)
        base_quality += min(0.15, self.state.speaking_likelihood * 0.20)
        base_quality -= min(0.18, self.state.clipping_ratio * 2.0)
        base_quality -= freshness_penalty
        if self.state.dropout_detected and silence_run > 0.18:
            base_quality -= 0.20

        dynamic_threshold = max(self.min_vad_rms, self.state.noise_floor_rms * self.vad_noise_multiplier)
        vad_active = self.state.last_rms >= dynamic_threshold and self.state.last_peak >= max(
            0.012,
            dynamic_threshold * 1.2,
        )

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

from shadowing.interfaces.repository import LessonRepository
from shadowing.interfaces.tts import TTSProvider


class LessonPreprocessPipeline:
    def __init__(self, tts_provider: TTSProvider, repo: LessonRepository) -> None:
        self.tts_provider = tts_provider
        self.repo = repo

    def run(self, lesson_id: str, text: str, output_dir: str) -> None:
        manifest, ref_map = self.tts_provider.synthesize_lesson(
            lesson_id=lesson_id,
            text=text,
            output_dir=output_dir,
        )
        self.repo.save_manifest(manifest)
        self.repo.save_reference_map(lesson_id, ref_map)
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/providers/elevenlabs_tts.py`

```python
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
from pypinyin import lazy_pinyin

from shadowing.interfaces.tts import TTSProvider
from shadowing.preprocess.chunker import ClauseChunker
from shadowing.preprocess.reference_builder import ReferenceBuilder
from shadowing.types import LessonManifest, ReferenceMap


class ElevenLabsTTSProvider(TTSProvider):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
        output_format: str = "pcm_44100",
        timeout_sec: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.timeout_sec = float(timeout_sec)
        self.chunker = ClauseChunker(max_clause_chars=120)
        self.reference_builder = ReferenceBuilder()

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

        clauses = self.chunker.split_text(text)
        if not clauses:
            raise ValueError("No valid clauses found after splitting input text.")

        all_chars: list[str] = []
        all_pinyins: list[str] = []
        all_starts: list[float] = []
        all_ends: list[float] = []
        all_sentence_ids: list[int] = []
        all_clause_ids: list[int] = []

        chunk_paths: list[str] = []
        global_time_offset = 0.0
        total_audio_duration = 0.0
        sample_rate_out: int | None = None
        sentence_id = 0
        previous_text = ""

        with httpx.Client(timeout=self.timeout_sec) as client:
            for clause_id, clause_text in enumerate(clauses):
                next_text = clauses[clause_id + 1] if clause_id + 1 < len(clauses) else ""

                resp = self._request_tts_with_timestamps(
                    client=client,
                    text=clause_text,
                    previous_text=previous_text,
                    next_text=next_text,
                )

                audio_bytes = base64.b64decode(resp["audio_base64"])
                chunk_file, chunk_samplerate, chunk_duration = self._write_chunk_audio(
                    chunks_dir=chunks_dir,
                    clause_id=clause_id,
                    audio_bytes=audio_bytes,
                )
                chunk_paths.append(str(chunk_file))

                if sample_rate_out is None:
                    sample_rate_out = int(chunk_samplerate)
                elif sample_rate_out != int(chunk_samplerate):
                    raise ValueError(
                        f"Inconsistent chunk sample rate: {sample_rate_out} vs {chunk_samplerate}"
                    )

                alignment = resp.get("alignment") or resp.get("normalized_alignment")
                if not alignment:
                    raise ValueError(f"No alignment returned for clause {clause_id}: {clause_text!r}")

                chars = alignment["characters"]
                starts = alignment["character_start_times_seconds"]
                ends = alignment["character_end_times_seconds"]

                if not (len(chars) == len(starts) == len(ends)):
                    raise ValueError(
                        f"Alignment length mismatch in clause {clause_id}: "
                        f"{len(chars)=}, {len(starts)=}, {len(ends)=}"
                    )

                pinyins = [lazy_pinyin(ch)[0] if ch.strip() else "" for ch in chars]

                for ch, py, ts, te in zip(chars, pinyins, starts, ends, strict=True):
                    all_chars.append(ch)
                    all_pinyins.append(py)
                    all_starts.append(global_time_offset + float(ts))
                    all_ends.append(global_time_offset + float(te))
                    all_sentence_ids.append(sentence_id)
                    all_clause_ids.append(clause_id)

                alignment_end_sec = max((float(x) for x in ends), default=0.0)
                offset_advance_sec = alignment_end_sec if alignment_end_sec > 0.0 else chunk_duration
                global_time_offset += offset_advance_sec
                total_audio_duration = global_time_offset

                if clause_text and clause_text[-1] in "。！？!?":
                    sentence_id += 1

                previous_text = clause_text

        ref_map = self.reference_builder.build(
            lesson_id=lesson_id,
            chars=all_chars,
            pinyins=all_pinyins,
            starts=all_starts,
            ends=all_ends,
            sentence_ids=all_sentence_ids,
            clause_ids=all_clause_ids,
            total_duration_sec=total_audio_duration,
        )

        manifest = LessonManifest(
            lesson_id=lesson_id,
            lesson_text=text,
            sample_rate_out=sample_rate_out or 44100,
            chunk_paths=chunk_paths,
            reference_map_path=str(output_path / "reference_map.json"),
            provider_name="elevenlabs",
            output_format=self.output_format,
        )
        return manifest, ref_map

    def _write_chunk_audio(
        self,
        chunks_dir: Path,
        clause_id: int,
        audio_bytes: bytes,
    ) -> tuple[Path, int, float]:
        fmt = self.output_format.strip().lower()

        if fmt.startswith("pcm_"):
            return self._write_pcm_like_audio(chunks_dir, clause_id, audio_bytes, fmt)

        ext = self._infer_container_extension(fmt)
        chunk_file = chunks_dir / f"{clause_id:04d}.{ext}"
        chunk_file.write_bytes(audio_bytes)

        info = sf.info(str(chunk_file))
        duration_sec = float(info.duration)
        sample_rate = int(info.samplerate)
        return chunk_file, sample_rate, duration_sec

    def _write_pcm_like_audio(
        self,
        chunks_dir: Path,
        clause_id: int,
        audio_bytes: bytes,
        output_format: str,
    ) -> tuple[Path, int, float]:
        sample_rate = self._parse_pcm_sample_rate(output_format)
        chunk_file = chunks_dir / f"{clause_id:04d}.wav"

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
                f"cannot parse as int16 PCM. clause_id={clause_id}, "
                f"bytes={len(audio_bytes)}, head={head}"
            )

        pcm_i16 = np.frombuffer(audio_bytes, dtype="<i2")
        if pcm_i16.size == 0:
            raise ValueError(f"Empty PCM audio returned for clause {clause_id}.")

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
    ) -> dict:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
            "output_format": self.output_format,
        }

        if previous_text:
            payload["previous_text"] = previous_text
        if next_text:
            payload["next_text"] = next_text

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
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/reference_builder.py`

```python
from __future__ import annotations

from shadowing.types import RefToken, ReferenceMap


class ReferenceBuilder:
    _DROP_CHARS = {
        " ", "\t", "\n", "\r", "\u3000",
        "，", "。", "！", "？", "；", "：", "、",
        ",", ".", "!", "?", ";", ":", '"', "'", "“", "”", "‘", "’",
        "（", "）", "(", ")", "[", "]", "【", "】", "<", ">", "《", "》",
        "-", "—", "…", "|", "/", "\\",
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
        tokens: list[RefToken] = []
        next_idx = 0
        for ch, py, ts, te, sid, cid in zip(
            chars, pinyins, starts, ends, sentence_ids, clause_ids, strict=True
        ):
            if not ch or ch in self._DROP_CHARS or not ch.strip():
                continue
            tokens.append(
                RefToken(
                    idx=next_idx,
                    char=ch,
                    pinyin=py,
                    t_start=float(ts),
                    t_end=float(te),
                    sentence_id=int(sid),
                    clause_id=int(cid),
                )
            )
            next_idx += 1
        return ReferenceMap(
            lesson_id=lesson_id,
            tokens=tokens,
            total_duration_sec=float(total_duration_sec),
        )
```

---
### 文件: `shadowing_app/src/shadowing/progress/behavior_interpreter.py`

```python
from __future__ import annotations

from shadowing.types import SignalQuality, TrackingMode, TrackingSnapshot, UserReadState


class BehaviorInterpreter:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        strong_signal_threshold: float = 0.58,
        weak_signal_threshold: float = 0.42,
        repeat_penalty_threshold: float = 0.34,
        skip_forward_tokens: int = 8,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.strong_signal_threshold = float(strong_signal_threshold)
        self.weak_signal_threshold = float(weak_signal_threshold)
        self.repeat_penalty_threshold = float(repeat_penalty_threshold)
        self.skip_forward_tokens = int(skip_forward_tokens)

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
    ) -> UserReadState:
        signal_speaking = self._is_signal_speaking(signal_quality)
        signal_weak_speaking = self._is_signal_weak_speaking(signal_quality)

        if tracking_mode == TrackingMode.LOST:
            if signal_speaking:
                return UserReadState.REJOINING
            return UserReadState.LOST

        if tracking_mode == TrackingMode.REACQUIRING:
            if signal_speaking:
                return UserReadState.REJOINING
            return UserReadState.HESITATING

        repeat_penalty = tracking.repeat_penalty if tracking is not None else 0.0
        if repeat_penalty >= self.repeat_penalty_threshold and signal_speaking:
            return UserReadState.REPEATING

        if candidate_idx - estimated_idx >= self.skip_forward_tokens and tracking_quality >= 0.72:
            return UserReadState.SKIPPING

        if progress_age <= self.recent_progress_sec:
            if tracking_quality >= 0.60:
                return UserReadState.FOLLOWING
            if signal_speaking:
                return UserReadState.HESITATING
            return UserReadState.WARMING_UP

        if progress_age <= 1.80:
            if signal_speaking and tracking_quality >= 0.36:
                return UserReadState.HESITATING
            if signal_weak_speaking:
                return UserReadState.WARMING_UP

        if not signal_speaking and progress_age > 1.20:
            return UserReadState.PAUSED

        if signal_speaking:
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

raise RuntimeError(
    "shadowing.realtime.aligner is a legacy module and is no longer used. "
    "Use shadowing.realtime.alignment.incremental_aligner instead."
)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/incremental_aligner.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from math import exp

from shadowing.interfaces.aligner import Aligner
from shadowing.realtime.alignment.scoring import AlignmentScorer
from shadowing.realtime.alignment.window_selector import WindowSelector
from shadowing.types import (
    AlignResult,
    AsrEvent,
    AsrEventType,
    CandidateAlignment,
    HypToken,
    ReferenceMap,
)


@dataclass(slots=True)
class _RefTokenView:
    idx: int
    char: str
    pinyin: str
    t_start: float
    t_end: float
    sentence_id: int
    clause_id: int


@dataclass(slots=True)
class _CommitState:
    committed_idx: int = 0
    stable_run: int = 0
    backward_run: int = 0
    last_candidate_idx: int = 0
    generation: int = 0
    recovering_after_seek: bool = False


class IncrementalAligner(Aligner):
    def __init__(
        self,
        window_back: int = 8,
        window_ahead: int = 40,
        stable_frames: int = 2,
        min_confidence: float = 0.60,
        backward_lock_frames: int = 3,
        clause_boundary_bonus: float = 0.15,
        cross_clause_backward_extra_penalty: float = 0.20,
        debug: bool = False,
        max_hyp_tokens: int = 16,
    ) -> None:
        self.base_window_back = max(4, int(window_back))
        self.base_window_ahead = max(20, int(window_ahead))
        self.window_selector = WindowSelector(look_back=self.base_window_back, look_ahead=self.base_window_ahead)
        self.scorer = AlignmentScorer()
        self.stable_frames = int(stable_frames)
        self.min_confidence = float(min_confidence)
        self.backward_lock_frames = int(backward_lock_frames)
        self.clause_boundary_bonus = float(clause_boundary_bonus)
        self.cross_clause_backward_extra_penalty = float(cross_clause_backward_extra_penalty)
        self.debug = bool(debug)
        self.max_hyp_tokens = max(6, int(max_hyp_tokens))

        self.ref_map: ReferenceMap | None = None
        self.ref_tokens: list[_RefTokenView] = []
        self.state = _CommitState()

    def reset(self, reference_map: ReferenceMap) -> None:
        self.ref_map = reference_map
        self.ref_tokens = [
            _RefTokenView(
                idx=t.idx,
                char=t.char,
                pinyin=t.pinyin,
                t_start=t.t_start,
                t_end=t.t_end,
                sentence_id=t.sentence_id,
                clause_id=t.clause_id,
            )
            for t in reference_map.tokens
        ]
        self.state = _CommitState()

    def on_playback_generation_changed(self, generation: int) -> None:
        self.state.generation = int(generation)
        self.state.stable_run = 0
        self.state.backward_run = 0
        self.state.last_candidate_idx = self.state.committed_idx
        self.state.recovering_after_seek = True

    def update(self, event: AsrEvent) -> AlignResult | None:
        if self.ref_map is None or not self.ref_tokens:
            return None

        if event.event_type not in (AsrEventType.PARTIAL, AsrEventType.FINAL):
            return None

        raw_pairs = list(zip(event.chars, event.pinyin_seq, strict=False))
        hyp_pairs, repeat_penalty = self._prepare_hypothesis(raw_pairs)
        if not hyp_pairs:
            return None

        hyp_tokens = [HypToken(char=c, pinyin=py) for c, py in hyp_pairs]

        dyn_back, dyn_ahead = self._select_window_params()
        window_tokens, window_start, window_end = self.window_selector.select(
            self.ref_map,
            self.state.committed_idx,
            look_back=dyn_back,
            look_ahead=dyn_ahead,
        )

        candidate, local_match_ratio = self._align_window(
            hyp_tokens=hyp_tokens,
            ref_tokens=window_tokens,
            ref_offset=window_start,
            repeat_penalty=repeat_penalty,
        )
        stable = self._observe_candidate(candidate, event.event_type)

        ref_time = self.ref_tokens[candidate.ref_end_idx].t_start
        matched_text = "".join(
            self.ref_tokens[i].char
            for i in candidate.matched_ref_indices
            if 0 <= i < len(self.ref_tokens)
        )
        matched_pinyin = [
            self.ref_tokens[i].pinyin
            for i in candidate.matched_ref_indices
            if 0 <= i < len(self.ref_tokens)
        ]

        if self.debug:
            print(
                "[ALIGN] "
                f"committed={self.state.committed_idx} "
                f"candidate={candidate.ref_end_idx} "
                f"score={candidate.score:.3f} "
                f"conf={candidate.confidence:.3f} "
                f"stable={stable} "
                f"backward={candidate.backward_jump} "
                f"matched_n={len(candidate.matched_ref_indices)} "
                f"hyp_n={len(hyp_tokens)} "
                f"mode={candidate.mode} "
                f"window=({window_start},{max(window_start, window_end - 1)})"
            )

        return AlignResult(
            committed_ref_idx=self.state.committed_idx,
            candidate_ref_idx=candidate.ref_end_idx,
            ref_time_sec=ref_time,
            confidence=candidate.confidence,
            stable=stable,
            matched_text=matched_text,
            matched_pinyin=matched_pinyin,
            window_start_idx=window_start,
            window_end_idx=max(window_start, window_end - 1),
            alignment_mode=candidate.mode,
            backward_jump_detected=candidate.backward_jump,
            debug_score=candidate.score,
            debug_stable_run=self.state.stable_run,
            debug_backward_run=self.state.backward_run,
            debug_matched_count=len(candidate.matched_ref_indices),
            debug_hyp_length=len(hyp_tokens),
            local_match_ratio=local_match_ratio,
            repeat_penalty=repeat_penalty,
            emitted_at_sec=event.emitted_at_sec,
        )

    def _select_window_params(self) -> tuple[int, int]:
        look_back = self.base_window_back
        look_ahead = self.base_window_ahead

        if self.state.recovering_after_seek:
            look_back += 8
            look_ahead += 28
        elif self.state.backward_run > 0:
            look_back += 6
            look_ahead += 18
        elif self.state.stable_run >= max(2, self.stable_frames):
            look_back = max(6, self.base_window_back - 2)
            look_ahead = max(28, self.base_window_ahead - 8)

        return look_back, look_ahead

    def _observe_candidate(self, candidate: CandidateAlignment, event_type: AsrEventType) -> bool:
        stable = False

        if self.state.recovering_after_seek:
            if not candidate.backward_jump and candidate.confidence >= self.min_confidence:
                self.state.recovering_after_seek = False
            else:
                return False

        if candidate.backward_jump:
            self.state.backward_run += 1
        else:
            self.state.backward_run = 0

        if candidate.ref_end_idx == self.state.last_candidate_idx:
            self.state.stable_run += 1
        else:
            self.state.stable_run = 1

        self.state.last_candidate_idx = candidate.ref_end_idx

        if event_type == AsrEventType.FINAL:
            if candidate.backward_jump:
                if candidate.confidence >= 0.90 and self.state.backward_run >= self.backward_lock_frames:
                    self.state.committed_idx = candidate.ref_end_idx
                    self.state.stable_run = 0
                    self.state.backward_run = 0
                    return True
                return False

            if candidate.confidence >= self.min_confidence and candidate.ref_end_idx >= self.state.committed_idx:
                self.state.committed_idx = candidate.ref_end_idx
                self.state.stable_run = 0
                self.state.backward_run = 0
                return True
            return False

        if candidate.backward_jump:
            if candidate.confidence >= 0.90 and self.state.backward_run >= self.backward_lock_frames:
                self.state.committed_idx = candidate.ref_end_idx
                stable = True
            return stable

        if candidate.confidence < self.min_confidence:
            return False

        if candidate.ref_end_idx < self.state.committed_idx:
            return False

        if self.state.stable_run >= self.stable_frames:
            self.state.committed_idx = candidate.ref_end_idx
            stable = True

        return stable

    def _prepare_hypothesis(
        self,
        raw_pairs: list[tuple[str, str]],
    ) -> tuple[list[tuple[str, str]], float]:
        if not raw_pairs:
            return [], 0.0

        compacted: list[tuple[str, str]] = []
        same_run = 0
        prev_char = ""

        for ch, py in raw_pairs:
            if ch == prev_char:
                same_run += 1
            else:
                same_run = 1
                prev_char = ch

            if same_run > 2:
                continue

            compacted.append((ch, py))

        if len(compacted) > self.max_hyp_tokens:
            compacted = compacted[-self.max_hyp_tokens :]

        repeat_hits = 0
        for i in range(1, len(compacted)):
            if compacted[i][0] == compacted[i - 1][0]:
                repeat_hits += 1

        repeat_penalty = repeat_hits / max(1, len(compacted) - 1)
        return compacted, repeat_penalty

    def _align_window(
        self,
        hyp_tokens: list[HypToken],
        ref_tokens: list[_RefTokenView],
        ref_offset: int,
        repeat_penalty: float,
    ) -> tuple[CandidateAlignment, float]:
        m = len(hyp_tokens)
        n = len(ref_tokens)

        if m == 0 or n == 0:
            committed = self.state.committed_idx
            return (
                CandidateAlignment(
                    ref_start_idx=committed,
                    ref_end_idx=committed,
                    score=0.0,
                    confidence=0.0,
                ),
                0.0,
            )

        dp = [[0.0] * (n + 1) for _ in range(m + 1)]
        trace = [["S"] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            dp[i][0] = dp[i - 1][0] + self.scorer.insertion_penalty()
            trace[i][0] = "I"

        current_clause = (
            self.ref_tokens[min(self.state.committed_idx, len(self.ref_tokens) - 1)].clause_id
            if self.ref_tokens
            else 0
        )

        for j in range(1, n + 1):
            penalty = self.scorer.deletion_penalty()
            global_idx = ref_offset + (j - 1)

            if global_idx < self.state.committed_idx:
                penalty += self.scorer.backward_penalty()
                if self.ref_tokens[global_idx].clause_id != current_clause:
                    penalty -= self.cross_clause_backward_extra_penalty

            dp[0][j] = dp[0][j - 1] + penalty
            trace[0][j] = "D"

        best_j = 1
        best_score = float("-inf")

        for i in range(1, m + 1):
            hyp = hyp_tokens[i - 1]
            for j in range(1, n + 1):
                ref = ref_tokens[j - 1]

                match_score = self.scorer.score_token_pair(ref.char, ref.pinyin, hyp.char, hyp.pinyin)
                if ref.idx == self.state.committed_idx + 1:
                    match_score += self.clause_boundary_bonus * 0.25

                diag = dp[i - 1][j - 1] + match_score
                ins = dp[i - 1][j] + self.scorer.insertion_penalty()

                delete_penalty = self.scorer.deletion_penalty()
                if ref.idx < self.state.committed_idx:
                    delete_penalty += self.scorer.backward_penalty()
                    if ref.clause_id != current_clause:
                        delete_penalty -= self.cross_clause_backward_extra_penalty

                dele = dp[i][j - 1] + delete_penalty

                best = max(diag, ins, dele)
                dp[i][j] = best
                trace[i][j] = "M" if best == diag else ("I" if best == ins else "D")

                if i == m and best > best_score:
                    best_score = best
                    best_j = j

        matched_indices: list[int] = []
        positive_match_count = 0

        i = m
        j = best_j
        while i > 0 and j > 0:
            op = trace[i][j]
            if op == "M":
                ref_global_idx = ref_offset + j - 1
                matched_indices.append(ref_global_idx)

                ref = ref_tokens[j - 1]
                hyp = hyp_tokens[i - 1]
                pair_score = self.scorer.score_token_pair(ref.char, ref.pinyin, hyp.char, hyp.pinyin)
                if pair_score > 0:
                    positive_match_count += 1

                i -= 1
                j -= 1
            elif op == "I":
                i -= 1
            else:
                j -= 1

        matched_indices.reverse()

        ref_end_idx = ref_offset + best_j - 1
        ref_end_idx = max(0, min(ref_end_idx, len(self.ref_tokens) - 1))
        ref_start_idx = matched_indices[0] if matched_indices else max(ref_offset, ref_end_idx)
        backward_jump = ref_end_idx < self.state.committed_idx
        norm_score = best_score / max(1, len(hyp_tokens))
        base_conf = 1.0 / (1.0 + exp(-1.20 * norm_score))

        local_match_ratio = positive_match_count / max(1, len(hyp_tokens))
        forward_bonus = 0.06 if ref_end_idx >= self.state.committed_idx else -0.08
        confidence = (
            0.62 * base_conf
            + 0.30 * local_match_ratio
            + forward_bonus
            - 0.22 * repeat_penalty
        )
        mode = "backward" if backward_jump else "normal"

        return (
            CandidateAlignment(
                ref_start_idx=ref_start_idx,
                ref_end_idx=ref_end_idx,
                score=best_score,
                confidence=max(0.0, min(1.0, confidence)),
                matched_ref_indices=matched_indices,
                backward_jump=backward_jump,
                mode=mode,
            ),
            local_match_ratio,
        )
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

import time
from typing import Any

import numpy as np

from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEventType, RawAsrEvent


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
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0

        self._last_partial_log_text = ""
        self._last_summary_log_at = 0.0
        self._summary_interval_sec = 2.5
        self._last_ready_state = False
        self._last_endpoint_state = False

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
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False

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
            print(
                f"[ASR-FEED] chunks={self._feed_counter} samples={audio_f32.size} "
                f"abs_mean={abs_mean:.5f} peak={peak:.5f}"
            )

        self._stream.accept_waveform(self.sample_rate, audio_f32)

        ready_before = self._recognizer.is_ready(self._stream)
        if self.debug_feed and ready_before and not self._last_ready_state:
            print(f"[ASR-READY] stream became ready at feed_chunks={self._feed_counter}")
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

        partial_text = self._get_result_text().strip()

        if self.debug_feed and partial_text and partial_text != self._last_partial_log_text:
            print(f"[ASR-PARTIAL-RAW] {partial_text!r}")
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
            print(
                f"[ASR-ENDPOINT-HIT] count_next={self._endpoint_count + 1} "
                f"partial_len={len(partial_text)} preview={preview!r}"
            )
        self._last_endpoint_state = bool(endpoint_hit)

        if endpoint_hit:
            self._endpoint_count += 1
            self._last_endpoint_at = now
            final_text = self._get_result_text().strip()

            if self.debug_feed and final_text and final_text != self._last_final_text:
                print(f"[ASR-FINAL-RAW] {final_text!r}")

            if final_text and final_text != self._last_final_text:
                events.append(
                    RawAsrEvent(
                        event_type=AsrEventType.FINAL,
                        text=final_text,
                        emitted_at_sec=now,
                    )
                )
                self._last_final_text = final_text
                self._final_emit_count += 1

            self._reset_stream_state_only()
            self._last_partial_text = ""
            self._last_partial_log_text = ""
            self._last_ready_state = False
            self._last_endpoint_state = False

            if self.debug_feed:
                print(
                    f"[ASR-ENDPOINT] count={self._endpoint_count} "
                    f"final_count={self._final_emit_count} "
                    f"last_endpoint_at={self._last_endpoint_at:.3f}"
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
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False

    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None

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

    def _maybe_log_summary(self) -> None:
        if not self.debug_feed:
            return

        now = time.monotonic()
        if (now - self._last_summary_log_at) < self._summary_interval_sec:
            return

        current_text = self._get_result_text().strip() if self._recognizer is not None and self._stream is not None else ""
        preview = current_text[:32]
        print(
            f"[ASR-SUMMARY] feeds={self._feed_counter} decodes={self._decode_counter} "
            f"partials_len={len(self._last_partial_text)} finals={self._final_emit_count} "
            f"endpoints={self._endpoint_count} preview={preview!r}"
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
            hotwords=self.hotwords or cfg.get("hotwords", ""),
            hotwords_score=cfg.get("hotwords_score", 1.5),
        )
        endpoint_kwargs = dict(
            enable_endpoint_detection=self.enable_endpoint,
            rule1_min_trailing_silence=cfg.get("rule1_min_trailing_silence", 10.0),
            rule2_min_trailing_silence=cfg.get("rule2_min_trailing_silence", 10.0),
            rule3_min_utterance_length=cfg.get("rule3_min_utterance_length", 60.0),
        )

        try:
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **hotword_kwargs,
                **endpoint_kwargs,
            )
        except TypeError:
            try:
                return sherpa_onnx.OnlineRecognizer.from_transducer(
                    **base_kwargs,
                    **endpoint_kwargs,
                )
            except TypeError:
                return sherpa_onnx.OnlineRecognizer.from_transducer(**base_kwargs)
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
                index=idx,
                name=str(dev["name"]),
                max_input_channels=max_in,
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=str(hostapi_name),
            )
        )
    return results


def print_input_devices() -> None:
    for d in list_input_devices():
        print(
            f"[{d.index}] {d.name} | hostapi={d.hostapi_name} | "
            f"max_in={d.max_input_channels} | default_sr={d.default_samplerate}"
        )


def get_default_input_device_index() -> int | None:
    default_input, _ = sd.default.device
    if default_input is None or default_input < 0:
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
            samplerate=samplerate,
            channels=channels,
            dtype=dtype,
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
        if check_input_settings(
            device=device,
            samplerate=sr,
            channels=channels,
            dtype=dtype,
        ):
            return {
                "device": device,
                "samplerate": sr,
                "channels": channels,
                "dtype": dtype,
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

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._running:
            return

        self._callback = on_audio_frame
        self._mic = self._resolve_microphone(self.device, self.include_loopback)

        open_candidates = self._build_open_candidates()

        last_error: Exception | None = None
        for sr, ch in open_candidates:
            try:
                print(
                    f"[REC-SC] trying mic={self._mic.name!r} "
                    f"samplerate={sr} channels={ch}"
                )
                with self._mic.recorder(samplerate=sr, channels=ch) as rec:
                    pilot = rec.record(numframes=min(self.block_frames, 256))

                pilot_audio = np.asarray(pilot, dtype=np.float32).reshape(-1)
                pilot_rms = float(np.sqrt(np.mean(np.square(pilot_audio)))) if pilot_audio.size else 0.0
                pilot_peak = float(np.max(np.abs(pilot_audio))) if pilot_audio.size else 0.0

                self._opened_samplerate = int(sr)
                self._opened_channels = int(ch)
                self._resampler = AudioResampler(
                    src_rate=self._opened_samplerate,
                    dst_rate=self.target_sample_rate,
                )

                print(
                    f"[REC-SC] opened mic={self._mic.name!r} "
                    f"samplerate={self._opened_samplerate} channels={self._opened_channels} "
                    f"pilot_rms={pilot_rms:.5f} pilot_peak={pilot_peak:.5f}"
                )
                last_error = None
                break
            except Exception as e:
                last_error = e

        if last_error is not None or self._opened_samplerate is None or self._opened_channels is None:
            msg = str(last_error)
            if "0x80070005" in msg:
                raise RuntimeError(
                    "Failed to open microphone with soundcard: access denied (0x80070005). "
                    "Please enable Windows microphone privacy permissions and close apps using the mic."
                )
            raise RuntimeError(
                "Failed to open microphone with soundcard. "
                f"device={self.device!r}, last_error={last_error}"
            )

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
            print(
                f"[REC-SC] capture_loop started mic={self._mic.name!r} "
                f"samplerate={self._opened_samplerate} channels={self._opened_channels} "
                f"block_frames={self.block_frames}"
            )

            with self._mic.recorder(
                samplerate=self._opened_samplerate,
                channels=self._opened_channels,
            ) as rec:
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
                    if self.debug_level_meter:
                        if self._debug_counter <= 3 or self._debug_counter % self.debug_level_every_n_blocks == 0:
                            rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                            peak = float(np.max(np.abs(mono))) if mono.size else 0.0
                            print(
                                f"[REC-SC] rms={rms:.5f} peak={peak:.5f} "
                                f"frames={mono.shape[0]}"
                            )

                    if self._resampler is None:
                        raise RuntimeError("SoundCardRecorder resampler is not initialized.")

                    pcm16_bytes = self._resampler.process_float_mono(mono)
                    self._callback(pcm16_bytes)
        except Exception as e:
            print(f"[REC-SC] capture loop stopped due to error: {e}")
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
                candidates.append((sr, ch))

        return candidates

    def _resolve_microphone(self, device: int | str | None, include_loopback: bool):
        mics = list(sc.all_microphones(include_loopback=include_loopback))
        if not mics:
            raise RuntimeError("No microphones found via soundcard.")

        print("[REC-SC] available microphones:")
        for idx, mic in enumerate(mics):
            print(f"  [{idx}] {mic.name!r}")

        if device is None:
            default_mic = sc.default_microphone()
            if default_mic is None:
                raise RuntimeError("No default microphone found via soundcard.")
            print(f"[REC-SC] using default microphone: {default_mic.name!r}")
            return default_mic

        if isinstance(device, int):
            if 0 <= device < len(mics):
                print(f"[REC-SC] using soundcard microphone index={device}: {mics[device].name!r}")
                return mics[device]
            raise ValueError(
                f"Soundcard microphone index out of range: {device}. "
                f"Valid range is 0..{len(mics) - 1}. "
                "Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )

        key = str(device).strip().lower()

        if key.isdigit():
            idx = int(key)
            if 0 <= idx < len(mics):
                print(f"[REC-SC] using soundcard microphone index={idx}: {mics[idx].name!r}")
                return mics[idx]
            raise ValueError(
                f"Soundcard microphone index out of range: {idx}. "
                f"Valid range is 0..{len(mics) - 1}. "
                "Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )

        for mic in mics:
            if key in mic.name.lower():
                print(f"[REC-SC] matched microphone {device!r} -> {mic.name!r}")
                return mic

        raise ValueError(
            f"No matching microphone found for {device!r}. "
            "For soundcard backend, pass either a soundcard microphone list index or a device name substring."
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/sounddevice_recorder.py`

```python
from __future__ import annotations

from typing import Any, Callable

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
        if status:
            print(f"[REC] callback status: {status}")
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
                sd.check_input_settings(device=device, samplerate=sr, channels=opened_channels, dtype=self.dtype)
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
    target_lead_sec: float = 0.15
    hold_if_lead_sec: float = 0.90
    resume_if_lead_sec: float = 0.28
    seek_if_lag_sec: float = -1.80

    min_confidence: float = 0.75
    seek_cooldown_sec: float = 1.20

    gain_following: float = 0.55
    gain_transition: float = 0.80
    gain_soft_duck: float = 0.42

    recover_after_seek_sec: float = 0.60
    startup_grace_sec: float = 0.80
    low_confidence_hold_sec: float = 0.60
    bootstrapping_sec: float = 1.80

    guide_play_sec: float = 2.20
    no_progress_hold_min_play_sec: float = 4.00
    speaking_recent_sec: float = 0.90
    progress_stale_sec: float = 1.10
    hold_trend_sec: float = 0.75
    hold_extra_lead_sec: float = 0.18
    low_confidence_continue_sec: float = 1.40

    tracking_quality_hold_min: float = 0.60
    tracking_quality_seek_min: float = 0.72

    resume_from_hold_event_fresh_sec: float = 0.45
    resume_from_hold_speaking_lead_slack_sec: float = 0.45
    reacquire_soft_duck_sec: float = 2.00

    disable_seek: bool = False
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/state_machine_controller.py`

```python
from __future__ import annotations

import time

from shadowing.interfaces.controller import Controller
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.types import (
    ControlAction,
    ControlDecision,
    PlaybackState,
    PlaybackStatus,
    ProgressEstimate,
    SignalQuality,
    TrackingMode,
)


class StateMachineController(Controller):
    def __init__(self, policy: ControlPolicy, disable_seek: bool = False) -> None:
        self.policy = policy
        self.disable_seek = bool(disable_seek or policy.disable_seek)
        self._session_started_at_sec = 0.0
        self._last_seek_at_sec = 0.0

        self._hold_candidate_since_sec = 0.0
        self._resume_candidate_since_sec = 0.0
        self._seek_candidate_since_sec = 0.0

        self._hold_hysteresis_sec = 0.18
        self._resume_hysteresis_sec = 0.22
        self._seek_hysteresis_sec = 0.28

    def reset(self) -> None:
        self._session_started_at_sec = 0.0
        self._last_seek_at_sec = 0.0
        self._hold_candidate_since_sec = 0.0
        self._resume_candidate_since_sec = 0.0
        self._seek_candidate_since_sec = 0.0

    def decide(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> ControlDecision:
        now_sec = time.monotonic()
        if self._session_started_at_sec <= 0.0:
            self._session_started_at_sec = now_sec

        speaking = self._is_speaking(signal_quality)
        session_age = max(0.0, now_sec - self._session_started_at_sec)

        if progress is None:
            self._reset_resume_candidate()
            self._reset_seek_candidate()

            if speaking and session_age <= self.policy.guide_play_sec:
                self._reset_hold_candidate()
                return ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="startup_guiding_soft_duck",
                    target_gain=self.policy.gain_soft_duck,
                    confidence=0.0,
                    aggressiveness="low",
                )

            if (
                session_age >= self.policy.no_progress_hold_min_play_sec
                and playback.state == PlaybackState.PLAYING
            ):
                if self._hold_ready(now_sec):
                    return ControlDecision(
                        action=ControlAction.HOLD,
                        reason="no_progress_timeout",
                        target_gain=0.0,
                        confidence=0.0,
                        aggressiveness="medium",
                    )
            else:
                self._reset_hold_candidate()

            return ControlDecision(
                action=ControlAction.NOOP,
                reason="waiting_for_progress",
                target_gain=self.policy.gain_following,
                confidence=0.0,
                aggressiveness="low",
            )

        lead_sec = playback.t_ref_heard_content_sec - progress.estimated_ref_time_sec
        tracking_good = (
            progress.confidence >= self.policy.min_confidence
            and progress.tracking_quality >= self.policy.tracking_quality_hold_min
        )

        if progress.tracking_mode in (TrackingMode.LOST, TrackingMode.REACQUIRING):
            self._reset_hold_candidate()
            self._reset_resume_candidate()
            self._reset_seek_candidate()

            if speaking:
                return ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="reacquire_soft_duck",
                    lead_sec=lead_sec,
                    target_gain=self.policy.gain_soft_duck,
                    confidence=progress.confidence,
                    aggressiveness="low",
                )
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="reacquire_keep_playing",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_following,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        if not tracking_good:
            self._reset_resume_candidate()
            self._reset_seek_candidate()

            should_hold = (
                lead_sec >= self.policy.hold_if_lead_sec + 0.15
                and progress.progress_age_sec >= self.policy.low_confidence_hold_sec
                and playback.state == PlaybackState.PLAYING
            )
            if should_hold:
                if self._hold_ready(now_sec):
                    return ControlDecision(
                        action=ControlAction.HOLD,
                        reason="low_confidence_ahead_hold",
                        lead_sec=lead_sec,
                        target_gain=0.0,
                        confidence=progress.confidence,
                        aggressiveness="medium",
                    )
            else:
                self._reset_hold_candidate()

            return ControlDecision(
                action=ControlAction.SOFT_DUCK if speaking else ControlAction.NOOP,
                reason="low_confidence_soft_follow" if speaking else "low_confidence_keep_playing",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_soft_duck if speaking else self.policy.gain_following,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        can_seek = (
            not self.disable_seek
            and progress.tracking_mode == TrackingMode.LOCKED
            and progress.recently_progressed
            and progress.active_speaking
            and progress.stable
            and progress.tracking_quality >= self.policy.tracking_quality_seek_min
            and progress.confidence >= self.policy.min_confidence
            and lead_sec <= self.policy.seek_if_lag_sec
            and (now_sec - self._last_seek_at_sec) >= self.policy.seek_cooldown_sec
        )
        if can_seek:
            if self._seek_ready(now_sec):
                self._last_seek_at_sec = now_sec
                self._reset_hold_candidate()
                self._reset_resume_candidate()
                target_time_sec = max(0.0, progress.estimated_ref_time_sec + self.policy.target_lead_sec)
                return ControlDecision(
                    action=ControlAction.SEEK,
                    reason="lagging_seek_forward",
                    target_time_sec=target_time_sec,
                    lead_sec=lead_sec,
                    target_gain=self.policy.gain_transition,
                    confidence=progress.confidence,
                    aggressiveness="high",
                )
        else:
            self._reset_seek_candidate()

        hold_threshold = self.policy.hold_if_lead_sec
        if progress.active_speaking:
            hold_threshold += self.policy.hold_extra_lead_sec

        if playback.state == PlaybackState.HOLDING:
            hold_tracking_ok = (
                progress.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED)
                and progress.confidence >= max(0.58, self.policy.min_confidence - 0.08)
                and progress.tracking_quality >= max(0.54, self.policy.tracking_quality_hold_min - 0.04)
            )
            resume_condition = (
                (lead_sec <= self.policy.resume_if_lead_sec and hold_tracking_ok)
                or (
                    progress.active_speaking
                    and hold_tracking_ok
                    and lead_sec <= (
                        self.policy.resume_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec
                    )
                )
            )

            self._reset_hold_candidate()
            if resume_condition:
                if self._resume_ready(now_sec):
                    return ControlDecision(
                        action=ControlAction.RESUME,
                        reason="lead_recovered_resume" if lead_sec <= self.policy.resume_if_lead_sec else "speaking_resume_slack",
                        lead_sec=lead_sec,
                        target_gain=self.policy.gain_following,
                        confidence=progress.confidence,
                        aggressiveness="medium",
                    )
            else:
                self._reset_resume_candidate()

            return ControlDecision(
                action=ControlAction.NOOP,
                reason="holding_wait_for_resume_window",
                lead_sec=lead_sec,
                target_gain=0.0,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        self._reset_resume_candidate()

        should_hold = (
            lead_sec >= hold_threshold
            and playback.state == PlaybackState.PLAYING
            and progress.tracking_quality >= self.policy.tracking_quality_hold_min
        )
        if should_hold:
            if self._hold_ready(now_sec):
                return ControlDecision(
                    action=ControlAction.HOLD,
                    reason="reference_too_far_ahead",
                    lead_sec=lead_sec,
                    target_gain=0.0,
                    confidence=progress.confidence,
                    aggressiveness="medium",
                )
        else:
            self._reset_hold_candidate()

        if lead_sec >= max(self.policy.target_lead_sec + 0.10, 0.35):
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="ahead_soft_duck",
                lead_sec=lead_sec,
                target_gain=self.policy.gain_soft_duck,
                confidence=progress.confidence,
                aggressiveness="low",
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="within_follow_band",
            lead_sec=lead_sec,
            target_gain=self.policy.gain_following,
            confidence=progress.confidence,
            aggressiveness="low",
        )

    def _is_speaking(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= 0.50
        )

    def _hold_ready(self, now_sec: float) -> bool:
        if self._hold_candidate_since_sec <= 0.0:
            self._hold_candidate_since_sec = now_sec
            return False
        return (now_sec - self._hold_candidate_since_sec) >= self._hold_hysteresis_sec

    def _resume_ready(self, now_sec: float) -> bool:
        if self._resume_candidate_since_sec <= 0.0:
            self._resume_candidate_since_sec = now_sec
            return False
        return (now_sec - self._resume_candidate_since_sec) >= self._resume_hysteresis_sec

    def _seek_ready(self, now_sec: float) -> bool:
        if self._seek_candidate_since_sec <= 0.0:
            self._seek_candidate_since_sec = now_sec
            return False
        return (now_sec - self._seek_candidate_since_sec) >= self._seek_hysteresis_sec

    def _reset_hold_candidate(self) -> None:
        self._hold_candidate_since_sec = 0.0

    def _reset_resume_candidate(self) -> None:
        self._resume_candidate_since_sec = 0.0

    def _reset_seek_candidate(self) -> None:
        self._seek_candidate_since_sec = 0.0
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
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.commercial_progress_estimator import CommercialProgressEstimator
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.telemetry.event_logger import EventLogger
from shadowing.telemetry.metrics import MetricsAggregator
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.types import (
    AsrEventType,
    DeviceProfileSnapshot,
    LatencyCalibrationSnapshot,
    PlayerCommand,
    PlayerCommandType,
    PlaybackState,
    ReferenceMap,
)


@dataclass(slots=True)
class OrchestratorStats:
    audio_enqueued: int = 0
    audio_dropped: int = 0
    audio_q_high_watermark: int = 0
    raw_asr_events: int = 0
    normalized_asr_events: int = 0
    ticks: int = 0


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

        self.audio_queue: queue.Queue[tuple[float, bytes]] = queue.Queue(maxsize=max(16, int(audio_queue_maxsize)))
        self.loop_interval_sec = float(loop_interval_sec)
        self.debug = bool(debug)

        self.normalizer = TextNormalizer()
        self.tracking_engine = TrackingEngine(self.aligner, debug=debug)
        self.progress_estimator = CommercialProgressEstimator()
        self.metrics = MetricsAggregator()

        self.stats = OrchestratorStats()

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

    def configure_runtime(self, runtime_cfg: dict[str, Any]) -> None:
        if "loop_interval_sec" in runtime_cfg:
            self.loop_interval_sec = float(runtime_cfg["loop_interval_sec"])

    def configure_debug(self, debug_cfg: dict[str, Any]) -> None:
        self.debug = bool(debug_cfg.get("enabled", self.debug))

    def start_session(self, lesson_id: str) -> None:
        self._lesson_id = lesson_id
        self._ref_map = self.repo.load_reference_map(lesson_id)

        self.tracking_engine.reset(self._ref_map)
        self.progress_estimator.reset(self._ref_map, start_idx=0)
        self.controller.reset()

        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        chunks = self.repo.load_audio_chunks(lesson_id)
        self.player.load_chunks(chunks)

        self._session_started_at_sec = time.monotonic()
        self.metrics.mark_session_started(self._session_started_at_sec)
        self._last_generation = -1
        self._last_tracking_mode = None
        self._last_gain_sent = None
        self._last_control_action_key = None

        output_sr = chunks[0].sample_rate if chunks else 44100
        self._device_profile = self._build_initial_device_profile(output_sr)
        self.latency_calibrator.reset(self._device_profile)
        self.auto_tuner.reset(self._device_profile.reliability_tier)

        if self.profile_store is not None and self._device_profile is not None:
            self._warm_start = self.profile_store.load_warm_start(
                input_device_id=self._device_profile.input_device_id,
                output_device_id=self._device_profile.output_device_id,
            )
            self.auto_tuner.apply_warm_start(
                controller_policy=self.controller.policy,
                player=self.player,
                signal_monitor=self.signal_monitor,
                warm_start=self._warm_start,
            )

        self.asr.start()
        self.recorder.start(self._on_audio_frame)
        self.player.start()

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

        if signal_snapshot.vad_active or signal_snapshot.speaking_likelihood >= 0.48:
            self.metrics.observe_signal_active(now_sec)

        playback_status = self.player.get_status()
        if playback_status.generation != self._last_generation:
            self._last_generation = playback_status.generation
            self.tracking_engine.on_playback_generation_changed(playback_status.generation)
            self.progress_estimator.on_playback_generation_changed(now_sec)

        raw_events = self.asr.poll_raw_events()
        self.stats.raw_asr_events += len(raw_events)

        progress = None
        for raw_event in raw_events:
            if raw_event.event_type == AsrEventType.PARTIAL:
                self.metrics.observe_asr_partial(raw_event.emitted_at_sec)

            event = self.normalizer.normalize_raw_event(raw_event)
            if event is None:
                continue

            self.stats.normalized_asr_events += 1
            tracking = self.tracking_engine.update(event)
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
                        "playback_generation": playback_status.generation,
                    },
                    ts_monotonic_sec=time.monotonic(),
                    session_tick=self.stats.ticks,
                )

            progress = self.progress_estimator.update(
                tracking=tracking,
                signal_quality=signal_snapshot,
                now_sec=event.emitted_at_sec,
            )

            if progress is not None:
                is_reliable = (
                    progress.confidence >= self.controller.policy.min_confidence
                    and progress.tracking_quality >= self.controller.policy.tracking_quality_hold_min
                )
                self.metrics.observe_progress(
                    now_sec=event.emitted_at_sec,
                    tracking_quality=progress.tracking_quality,
                    is_reliable=is_reliable,
                )

                playback_status = self.player.get_status()
                self.latency_calibrator.observe_sync(
                    now_sec=event.emitted_at_sec,
                    playback_ref_time_sec=playback_status.t_ref_heard_content_sec,
                    user_ref_time_sec=progress.estimated_ref_time_sec,
                    tracking_quality=progress.tracking_quality,
                    stable=progress.stable,
                    active_speaking=progress.active_speaking,
                )
        if progress is None:
            progress = self.progress_estimator.snapshot(
                now_sec=now_sec,
                signal_quality=signal_snapshot,
            )

        playback_status = self.player.get_status()
        decision = self.controller.decide(
            playback=playback_status,
            progress=progress,
            signal_quality=signal_snapshot,
        )

        self._apply_decision(decision, playback_status)
        self._run_auto_tuning(
            now_sec=now_sec,
            progress=progress,
            signal_snapshot=signal_snapshot,
            playback_status=playback_status,
        )
        self._log_event(progress=progress, signal_snapshot=signal_snapshot, decision=decision)

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
            self.asr.feed_pcm16(pcm_bytes)

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
            if self._last_gain_sent is None or abs(float(desired_gain) - float(self._last_gain_sent)) >= 0.015:
                self.player.submit_command(
                    PlayerCommand(
                        cmd=PlayerCommandType.SET_GAIN,
                        gain=float(desired_gain),
                        reason=decision.reason,
                    )
                )
                self._last_gain_sent = float(desired_gain)

    def _run_auto_tuning(
        self,
        *,
        now_sec: float,
        progress,
        signal_snapshot,
        playback_status,
    ) -> None:
        if self._device_profile is None:
            return

        updates = self.auto_tuner.maybe_tune(
            now_sec=now_sec,
            controller_policy=self.controller.policy,
            player=self.player,
            signal_monitor=self.signal_monitor,
            metrics_summary=self.metrics.summary_dict(),
            signal_quality=signal_snapshot,
            progress=progress,
            latency_snapshot=self.latency_calibrator.snapshot(),
            device_profile=asdict(self._device_profile),
        )

        if self.event_logger is not None and updates:
            self.event_logger.log(
                "auto_tune_update",
                {
                    "updates": updates,
                    "best_tracking_quality": self.auto_tuner.state.best_tracking_quality,
                    "speaker_style": self.auto_tuner.state.speaker_style,
                    "environment_style": self.auto_tuner.state.environment_style,
                    "playback_generation": playback_status.generation,
                },
                ts_monotonic_sec=time.monotonic(),
                session_tick=self.stats.ticks,
            )

    def _build_initial_device_profile(self, output_sample_rate: int) -> DeviceProfile:
        input_device_name = str(self.device_context.get("input_device_name", "unknown"))
        output_device_name = str(self.device_context.get("output_device_name", "unknown"))
        input_sample_rate = int(self.device_context.get("input_sample_rate", 48000))
        noise_floor_rms = float(self.device_context.get("noise_floor_rms", 0.0025))

        return build_device_profile(
            input_device_name=input_device_name,
            output_device_name=output_device_name,
            input_sample_rate=input_sample_rate,
            output_sample_rate=output_sample_rate,
            noise_floor_rms=noise_floor_rms,
        )

    def _persist_session_profile(self) -> None:
        if self.profile_store is None or self._device_profile is None:
            return

        latency_snapshot = self.latency_calibrator.snapshot()

        updated_profile = DeviceProfileSnapshot(
            input_device_id=self._device_profile.input_device_id,
            output_device_id=self._device_profile.output_device_id,
            input_kind=self._device_profile.input_kind,
            output_kind=self._device_profile.output_kind,
            input_sample_rate=self._device_profile.input_sample_rate,
            output_sample_rate=self._device_profile.output_sample_rate,
            estimated_input_latency_ms=(
                latency_snapshot.estimated_input_latency_ms
                if latency_snapshot is not None
                else self._device_profile.estimated_input_latency_ms
            ),
            estimated_output_latency_ms=(
                latency_snapshot.estimated_output_latency_ms
                if latency_snapshot is not None
                else self._device_profile.estimated_output_latency_ms
            ),
            noise_floor_rms=float(self.signal_monitor.state.noise_floor_rms),
            input_gain_hint=self._device_profile.input_gain_hint,
            reliability_tier=self._device_profile.reliability_tier,
        )

        latency_dict = None
        if latency_snapshot is not None:
            latency_dict = asdict(
                LatencyCalibrationSnapshot(
                    estimated_input_latency_ms=latency_snapshot.estimated_input_latency_ms,
                    estimated_output_latency_ms=latency_snapshot.estimated_output_latency_ms,
                    confidence=latency_snapshot.confidence,
                    calibrated=latency_snapshot.calibrated,
                )
            )

        self.profile_store.update_from_session(
            input_device_id=updated_profile.input_device_id,
            output_device_id=updated_profile.output_device_id,
            device_profile=asdict(updated_profile),
            metrics=self.metrics.summary_dict(),
            latency_calibration=latency_dict,
        )

    def _persist_summary(self) -> None:
        if self.event_logger is None:
            return

        latency_snapshot = self.latency_calibrator.snapshot()
        summary = {
            "lesson_id": self._lesson_id,
            "metrics": self.metrics.summary_dict(),
            "latency_calibration": (
                asdict(
                    LatencyCalibrationSnapshot(
                        estimated_input_latency_ms=latency_snapshot.estimated_input_latency_ms,
                        estimated_output_latency_ms=latency_snapshot.estimated_output_latency_ms,
                        confidence=latency_snapshot.confidence,
                        calibrated=latency_snapshot.calibrated,
                    )
                )
                if latency_snapshot is not None
                else {}
            ),
            "device_profile": asdict(
                DeviceProfileSnapshot(
                    input_device_id=self._device_profile.input_device_id,
                    output_device_id=self._device_profile.output_device_id,
                    input_kind=self._device_profile.input_kind,
                    output_kind=self._device_profile.output_kind,
                    input_sample_rate=self._device_profile.input_sample_rate,
                    output_sample_rate=self._device_profile.output_sample_rate,
                    estimated_input_latency_ms=self._device_profile.estimated_input_latency_ms,
                    estimated_output_latency_ms=self._device_profile.estimated_output_latency_ms,
                    noise_floor_rms=float(self.signal_monitor.state.noise_floor_rms),
                    input_gain_hint=self._device_profile.input_gain_hint,
                    reliability_tier=self._device_profile.reliability_tier,
                )
            ) if self._device_profile is not None else {},
            "stats": asdict(self.stats),
        }

        summary_path = Path(self.event_logger.session_dir) / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.event_logger.log(
            "session_summary",
            summary,
            ts_monotonic_sec=time.monotonic(),
            session_tick=self.stats.ticks,
        )

    def _log_event(self, *, progress, signal_snapshot, decision) -> None:
        if self.event_logger is None:
            return

        self.event_logger.log(
            "signal_snapshot",
            {
                "observed_at_sec": signal_snapshot.observed_at_sec,
                "rms": signal_snapshot.rms,
                "peak": signal_snapshot.peak,
                "vad_active": signal_snapshot.vad_active,
                "speaking_likelihood": signal_snapshot.speaking_likelihood,
                "quality_score": signal_snapshot.quality_score,
                "dropout_detected": signal_snapshot.dropout_detected,
                "silence_run_sec": signal_snapshot.silence_run_sec,
            },
            ts_monotonic_sec=time.monotonic(),
            session_tick=self.stats.ticks,
        )

        if progress is not None:
            self.event_logger.log(
                "progress_snapshot",
                {
                    "estimated_ref_idx": progress.estimated_ref_idx,
                    "estimated_ref_time_sec": progress.estimated_ref_time_sec,
                    "tracking_mode": progress.tracking_mode.value,
                    "tracking_quality": progress.tracking_quality,
                    "confidence": progress.confidence,
                    "active_speaking": progress.active_speaking,
                    "user_state": progress.user_state.value,
                    "progress_age_sec": progress.progress_age_sec,
                    "recently_progressed": progress.recently_progressed,
                    "playback_generation": self.player.get_status().generation,
                },
                ts_monotonic_sec=time.monotonic(),
                session_tick=self.stats.ticks,
            )

        self.event_logger.log(
            "control_decision",
            {
                "action": decision.action.value,
                "reason": decision.reason,
                "lead_sec": decision.lead_sec,
                "target_time_sec": decision.target_time_sec,
                "target_gain": decision.target_gain,
                "confidence": decision.confidence,
                "playback_generation": self.player.get_status().generation,
            },
            ts_monotonic_sec=time.monotonic(),
            session_tick=self.stats.ticks,
        )
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
        self.bluetooth_output_offset_sec = float(bluetooth_output_offset_sec)

    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(offset_sec))

    def compute(
        self,
        output_buffer_dac_time_sec: float,
        block_start_content_sec: float,
        block_end_content_sec: float,
    ) -> PlaybackClockSnapshot:
        emitted = block_start_content_sec
        heard = max(0.0, emitted - self.bluetooth_output_offset_sec)
        return PlaybackClockSnapshot(
            t_host_output_sec=float(output_buffer_dac_time_sec),
            t_ref_block_start_content_sec=float(block_start_content_sec),
            t_ref_block_end_content_sec=float(block_end_content_sec),
            t_ref_emitted_content_sec=float(emitted),
            t_ref_heard_content_sec=float(heard),
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
from shadowing.types import AudioChunk, PlaybackState, PlaybackStatus, PlayerCommand, PlayerCommandType


@dataclass(slots=True)
class PlaybackConfig:
    sample_rate: int
    channels: int
    device: int | None = None
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
            y = resample_poly(arr[:, ch], self.up, self.down).astype(np.float32, copy=False)
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
            raise ValueError("Chunk sample rate does not match player config sample rate.")
        self.queue.load(chunks)
        self._content_sample_rate = int(self.config.sample_rate)
        total_duration = chunks[-1].start_time_sec + chunks[-1].duration_sec if chunks else 0.0
        print(
            f"[PLAYER] loaded_chunks={len(chunks)} sample_rate={self.config.sample_rate} "
            f"channels={self.config.channels} total_duration_sec={total_duration:.3f}"
        )

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

        print(
            f"[PLAYER-START] requested_device={self.config.device} "
            f"resolved_device={self._resolved_output_device} "
            f"name={self._resolved_output_device_name} "
            f"latency={self.config.latency} blocksize={self.config.blocksize}"
        )

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

            print(
                f"[PLAYER] opened_output device={self._resolved_output_device} "
                f"name={dev_info['name']} default_sr={float(dev_info['default_samplerate'])} "
                f"content_sr={self._content_sample_rate} stream_sr={self._opened_output_sample_rate} "
                f"channels={self.config.channels}"
            )
            if self._opened_output_sample_rate != self._content_sample_rate:
                print(
                    f"[PLAYER] output_resample enabled "
                    f"{self._content_sample_rate} -> {self._opened_output_sample_rate}"
                )
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
        self.submit_command(PlayerCommand(cmd=PlayerCommandType.STOP, reason="external_stop"))

    def close(self) -> None:
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self._state = PlaybackState.STOPPED

    def _apply_merged_commands(self) -> None:
        merged = self.command_queue.drain_merged()

        if merged.gain_cmd and merged.gain_cmd.gain is not None:
            self._gain = min(max(merged.gain_cmd.gain, 0.0), 1.0)

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
            self.queue.seek(merged.seek_cmd.target_time_sec)
            self._generation += 1
            self._state = PlaybackState.HOLDING if hold_after_seek else PlaybackState.PLAYING
            if self._state == PlaybackState.PLAYING:
                self._silent_branch_logged = False
        elif hold_after_seek:
            self._state = PlaybackState.HOLDING

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        self._callback_count += 1
        self._apply_merged_commands()
        block_start = self.queue.get_content_time_sec()

        if self._state in (PlaybackState.STOPPED, PlaybackState.HOLDING, PlaybackState.FINISHED):
            outdata.fill(0.0)
            if not self._silent_branch_logged:
                print(
                    f"[PLAYER-SILENT] callback active but state={self._state.value} "
                    f"device={self._resolved_output_device} frames={frames}"
                )
                self._silent_branch_logged = True
        else:
            self._silent_branch_logged = False

            if self._output_resampler is None:
                block = self.queue.read_frames(frames=frames, channels=self.config.channels)
            else:
                src_frames = self._estimate_source_frames(frames)
                source_block = self.queue.read_frames(frames=src_frames, channels=self.config.channels)
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

            if self._callback_count <= 5 or self._callback_count % 50 == 0:
                peak = float(np.max(np.abs(outdata))) if outdata.size else 0.0
                print(
                    f"[PLAYER-CB] n={self._callback_count} frames={frames} "
                    f"state={self._state.value} chunk_id={self.queue.current_chunk_id} "
                    f"frame_index={self.queue.current_frame_index} peak={peak:.6f}"
                )

        if status:
            print(f"[PLAYER-CB-STATUS] {status}")

        block_end = self.queue.get_content_time_sec()
        snapshot = self.clock.compute(
            output_buffer_dac_time_sec=time_info.outputBufferDacTime,
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

        if self._callback_count <= 3 or self._callback_count % 200 == 0:
            peak_now = float(np.max(np.abs(outdata))) if outdata.size else 0.0
            print(
                f"[PLAYER-CB-HEARTBEAT] n={self._callback_count} "
                f"state={self._state.value} frames={frames} peak={peak_now:.6f}"
            )

    def _resolve_output_device(self, requested_device: int | None) -> int:
        if requested_device is not None:
            dev_info = sd.query_devices(requested_device)
            if int(dev_info["max_output_channels"]) <= 0:
                raise ValueError(
                    f"Requested device is not an output device: "
                    f"device={requested_device}, name={dev_info['name']}"
                )
            return int(requested_device)

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
            print("\nStopped by user.")
        finally:
            self._running = False
            self.orchestrator.stop_session()

    def stop(self) -> None:
        self._running = False


RealtimeRuntime = ShadowingRuntime
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
_STARTUP_FALSE_HOLD_REASONS = {
    "no_progress_timeout",
    "reference_too_far_ahead",
}

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
    def __init__(self) -> None:
        self.session_started_at_sec = 0.0

        self.first_signal_active_time_sec: float | None = None
        self.first_asr_partial_time_sec: float | None = None
        self.first_reliable_progress_time_sec: float | None = None

        self.startup_false_hold_count = 0
        self.hold_count = 0
        self.resume_count = 0
        self.soft_duck_count = 0
        self.seek_count = 0
        self.lost_count = 0
        self.reacquire_count = 0

        self.max_tracking_quality = 0.0
        self._tracking_quality_sum = 0.0
        self.total_progress_updates = 0

    def mark_session_started(self, now_sec: float) -> None:
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = float(now_sec)

    def observe_signal_active(self, now_sec: float) -> None:
        if self.first_signal_active_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_signal_active_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_asr_partial(self, now_sec: float) -> None:
        if self.first_asr_partial_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_asr_partial_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_progress(self, now_sec: float, tracking_quality: float, is_reliable: bool) -> None:
        self.total_progress_updates += 1
        self.max_tracking_quality = max(self.max_tracking_quality, float(tracking_quality))
        self._tracking_quality_sum += float(tracking_quality)

        if is_reliable and self.first_reliable_progress_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_reliable_progress_time_sec = max(0.0, now_sec - self.session_started_at_sec)

    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        if action == "hold":
            self.hold_count += 1
            if self.session_started_at_sec > 0.0 and (now_sec - self.session_started_at_sec) <= 5.0:
                if reason in _STARTUP_FALSE_HOLD_REASONS:
                    self.startup_false_hold_count += 1
        elif action == "resume":
            self.resume_count += 1
        elif action == "soft_duck":
            self.soft_duck_count += 1
        elif action == "seek":
            self.seek_count += 1

    def observe_tracking_mode(self, mode: str) -> None:
        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1

    def summary(self) -> SessionMetricsSummary:
        mean_tracking_quality = (
            self._tracking_quality_sum / self.total_progress_updates
            if self.total_progress_updates > 0
            else 0.0
        )
        return SessionMetricsSummary(
            first_signal_active_time_sec=self.first_signal_active_time_sec,
            first_asr_partial_time_sec=self.first_asr_partial_time_sec,
            first_reliable_progress_time_sec=self.first_reliable_progress_time_sec,
            startup_false_hold_count=self.startup_false_hold_count,
            hold_count=self.hold_count,
            resume_count=self.resume_count,
            soft_duck_count=self.soft_duck_count,
            seek_count=self.seek_count,
            lost_count=self.lost_count,
            reacquire_count=self.reacquire_count,
            max_tracking_quality=self.max_tracking_quality,
            mean_tracking_quality=float(mean_tracking_quality),
            total_progress_updates=self.total_progress_updates,
        )

    def summary_dict(self) -> dict:
        s = self.summary()
        return {
            "first_signal_active_time_sec": s.first_signal_active_time_sec,
            "first_asr_partial_time_sec": s.first_asr_partial_time_sec,
            "first_reliable_progress_time_sec": s.first_reliable_progress_time_sec,
            "startup_false_hold_count": s.startup_false_hold_count,
            "hold_count": s.hold_count,
            "resume_count": s.resume_count,
            "soft_duck_count": s.soft_duck_count,
            "seek_count": s.seek_count,
            "lost_count": s.lost_count,
            "reacquire_count": s.reacquire_count,
            "max_tracking_quality": s.max_tracking_quality,
            "mean_tracking_quality": s.mean_tracking_quality,
            "total_progress_updates": s.total_progress_updates,
        }
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

from shadowing.tracking.anchor_manager import AnchorManager
from shadowing.types import TrackingMode, TrackingSnapshot


class Reacquirer:
    def __init__(
        self,
        max_reanchor_distance: int = 18,
        min_quality_for_reanchor: float = 0.66,
    ) -> None:
        self.max_reanchor_distance = int(max_reanchor_distance)
        self.min_quality_for_reanchor = float(min_quality_for_reanchor)

    def maybe_reanchor(
        self,
        snapshot: TrackingSnapshot,
        anchor_manager: AnchorManager,
    ) -> TrackingSnapshot:
        if snapshot.tracking_mode not in (TrackingMode.REACQUIRING, TrackingMode.LOST):
            return snapshot

        strong = anchor_manager.strong_anchor()
        weak = anchor_manager.weak_anchor()
        anchor = strong if strong is not None else weak
        if anchor is None:
            return snapshot

        if snapshot.tracking_quality.overall_score < self.min_quality_for_reanchor:
            return snapshot

        if abs(snapshot.candidate_ref_idx - anchor.ref_idx) > self.max_reanchor_distance:
            return snapshot

        repaired_mode = TrackingMode.WEAK_LOCKED
        repaired_quality = snapshot.tracking_quality
        repaired_quality.mode = repaired_mode
        repaired_quality.is_reliable = repaired_quality.overall_score >= 0.60

        return TrackingSnapshot(
            candidate_ref_idx=int(snapshot.candidate_ref_idx),
            committed_ref_idx=max(int(snapshot.committed_ref_idx), int(anchor.ref_idx)),
            candidate_ref_time_sec=float(snapshot.candidate_ref_time_sec),
            confidence=float(snapshot.confidence),
            stable=bool(snapshot.stable),
            local_match_ratio=float(snapshot.local_match_ratio),
            repeat_penalty=float(snapshot.repeat_penalty),
            monotonic_consistency=float(snapshot.monotonic_consistency),
            anchor_consistency=float(snapshot.anchor_consistency),
            emitted_at_sec=float(snapshot.emitted_at_sec),
            tracking_mode=repaired_mode,
            tracking_quality=repaired_quality,
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

from shadowing.interfaces.aligner import Aligner
from shadowing.tracking.anchor_manager import AnchorManager
from shadowing.tracking.loss_detector import LossDetector
from shadowing.tracking.reacquirer import Reacquirer
from shadowing.types import ReferenceMap, AsrEvent, TrackingMode, TrackingQuality, TrackingSnapshot


class TrackingEngine:
    def __init__(self, aligner: Aligner, debug: bool = False) -> None:
        self.aligner = aligner
        self.debug = bool(debug)

        self.ref_map: ReferenceMap | None = None
        self.anchor_manager = AnchorManager()
        self.loss_detector = LossDetector()
        self.reacquirer = Reacquirer()

        self._last_candidate_idx = 0
        self._last_snapshot: TrackingSnapshot | None = None

        self._smoothed_mode = TrackingMode.BOOTSTRAP
        self._lock_recovery_run = 0
        self._lost_escalation_run = 0
        self._rejoin_run = 0

    def reset(self, reference_map: ReferenceMap) -> None:
        self.ref_map = reference_map
        self._last_candidate_idx = 0
        self._last_snapshot = None
        self.anchor_manager.reset()
        self.loss_detector.reset()
        self.aligner.reset(reference_map)
        self._smoothed_mode = TrackingMode.BOOTSTRAP
        self._lock_recovery_run = 0
        self._lost_escalation_run = 0
        self._rejoin_run = 0

    def on_playback_generation_changed(self, generation: int) -> None:
        self.aligner.on_playback_generation_changed(generation)
        self.loss_detector.reset()
        self._smoothed_mode = TrackingMode.REACQUIRING
        self._lock_recovery_run = 0
        self._lost_escalation_run = 0
        self._rejoin_run = 0

    def update(self, event: AsrEvent) -> TrackingSnapshot | None:
        if self.ref_map is None:
            return None

        alignment = self.aligner.update(event)
        if alignment is None:
            return self._last_snapshot

        candidate_idx = int(alignment.candidate_ref_idx)
        committed_idx = int(alignment.committed_ref_idx)

        monotonic_consistency = self._compute_monotonic_consistency(candidate_idx)
        anchor_consistency = self.anchor_manager.anchor_consistency(candidate_idx)

        observation_score = (
            0.58 * alignment.confidence
            + 0.24 * alignment.local_match_ratio
            + 0.12 * (1.0 - alignment.repeat_penalty)
            + 0.06 * (1.0 if alignment.stable else 0.0)
        )
        observation_score = max(0.0, min(1.0, observation_score))

        seed_quality = (
            0.62 * observation_score
            + 0.22 * anchor_consistency
            + 0.16 * monotonic_consistency
        )
        seed_quality = max(0.0, min(1.0, seed_quality))
        is_reliable = seed_quality >= 0.66 and alignment.confidence >= 0.62

        provisional_quality = TrackingQuality(
            overall_score=float(seed_quality),
            observation_score=float(observation_score),
            temporal_consistency_score=0.72,
            anchor_score=float(anchor_consistency),
            mode=TrackingMode.BOOTSTRAP,
            is_reliable=bool(is_reliable),
        )

        snapshot = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(alignment.ref_time_sec),
            confidence=float(alignment.confidence),
            stable=bool(alignment.stable),
            local_match_ratio=float(alignment.local_match_ratio),
            repeat_penalty=float(alignment.repeat_penalty),
            monotonic_consistency=float(monotonic_consistency),
            anchor_consistency=float(anchor_consistency),
            emitted_at_sec=float(alignment.emitted_at_sec),
            tracking_mode=TrackingMode.BOOTSTRAP,
            tracking_quality=provisional_quality,
            matched_text=alignment.matched_text,
        )

        raw_mode, temporal_consistency = self.loss_detector.update(
            snapshot=snapshot,
            overall_score=seed_quality,
            is_reliable=is_reliable,
        )

        overall_score = (
            0.48 * observation_score
            + 0.22 * temporal_consistency
            + 0.18 * anchor_consistency
            + 0.12 * monotonic_consistency
        )
        overall_score = max(0.0, min(1.0, overall_score))

        smoothed_mode = self._smooth_mode(
            raw_mode=raw_mode,
            overall_score=overall_score,
            alignment_confidence=alignment.confidence,
        )

        quality = TrackingQuality(
            overall_score=float(overall_score),
            observation_score=float(observation_score),
            temporal_consistency_score=float(temporal_consistency),
            anchor_score=float(anchor_consistency),
            mode=smoothed_mode,
            is_reliable=bool(overall_score >= 0.66 and alignment.confidence >= 0.62),
        )

        snapshot = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(alignment.ref_time_sec),
            confidence=float(alignment.confidence),
            stable=bool(alignment.stable),
            local_match_ratio=float(alignment.local_match_ratio),
            repeat_penalty=float(alignment.repeat_penalty),
            monotonic_consistency=float(monotonic_consistency),
            anchor_consistency=float(anchor_consistency),
            emitted_at_sec=float(alignment.emitted_at_sec),
            tracking_mode=smoothed_mode,
            tracking_quality=quality,
            matched_text=alignment.matched_text,
        )

        snapshot = self.reacquirer.maybe_reanchor(snapshot, self.anchor_manager)
        self.anchor_manager.update(snapshot)

        self._last_candidate_idx = candidate_idx
        self._last_snapshot = snapshot

        if self.debug:
            print(
                "[TRACK] "
                f"mode={snapshot.tracking_mode.value} "
                f"cand={snapshot.candidate_ref_idx} "
                f"committed={snapshot.committed_ref_idx} "
                f"overall={snapshot.tracking_quality.overall_score:.3f} "
                f"obs={snapshot.tracking_quality.observation_score:.3f} "
                f"temp={snapshot.tracking_quality.temporal_consistency_score:.3f} "
                f"anchor={snapshot.tracking_quality.anchor_score:.3f}"
            )

        return snapshot

    def snapshot(self) -> TrackingSnapshot | None:
        return self._last_snapshot

    def _compute_monotonic_consistency(self, candidate_idx: int) -> float:
        delta = candidate_idx - self._last_candidate_idx
        if delta >= 0:
            return 1.0
        return max(0.0, 1.0 - min(1.0, abs(delta) / 8.0))

    def _smooth_mode(
        self,
        *,
        raw_mode: TrackingMode,
        overall_score: float,
        alignment_confidence: float,
    ) -> TrackingMode:
        current = self._smoothed_mode

        if raw_mode == TrackingMode.LOCKED:
            if overall_score >= 0.74 and alignment_confidence >= 0.68:
                self._lock_recovery_run += 1
            else:
                self._lock_recovery_run = 0
        else:
            self._lock_recovery_run = 0

        if raw_mode == TrackingMode.LOST and overall_score < 0.42:
            self._lost_escalation_run += 1
        else:
            self._lost_escalation_run = 0

        if raw_mode in (TrackingMode.REACQUIRING, TrackingMode.WEAK_LOCKED):
            self._rejoin_run += 1
        else:
            self._rejoin_run = 0

        if current == TrackingMode.LOCKED:
            if raw_mode == TrackingMode.LOCKED:
                return TrackingMode.LOCKED
            if raw_mode in (TrackingMode.REACQUIRING, TrackingMode.LOST):
                self._smoothed_mode = TrackingMode.REACQUIRING
                return self._smoothed_mode
            if raw_mode == TrackingMode.WEAK_LOCKED:
                self._smoothed_mode = TrackingMode.WEAK_LOCKED
                return self._smoothed_mode

        if current == TrackingMode.REACQUIRING:
            if raw_mode == TrackingMode.LOCKED and self._lock_recovery_run >= 2:
                self._smoothed_mode = TrackingMode.LOCKED
                return self._smoothed_mode
            if raw_mode == TrackingMode.LOST and self._lost_escalation_run >= 2:
                self._smoothed_mode = TrackingMode.LOST
                return self._smoothed_mode
            if raw_mode == TrackingMode.WEAK_LOCKED and overall_score >= 0.60:
                self._smoothed_mode = TrackingMode.WEAK_LOCKED
                return self._smoothed_mode
            return TrackingMode.REACQUIRING

        if current == TrackingMode.LOST:
            if raw_mode == TrackingMode.LOCKED and self._lock_recovery_run >= 2:
                self._smoothed_mode = TrackingMode.LOCKED
                return self._smoothed_mode
            if raw_mode in (TrackingMode.REACQUIRING, TrackingMode.WEAK_LOCKED) and self._rejoin_run >= 2:
                self._smoothed_mode = TrackingMode.REACQUIRING
                return self._smoothed_mode
            return TrackingMode.LOST

        if current == TrackingMode.WEAK_LOCKED:
            if raw_mode == TrackingMode.LOCKED and self._lock_recovery_run >= 2:
                self._smoothed_mode = TrackingMode.LOCKED
                return self._smoothed_mode
            if raw_mode == TrackingMode.LOST and self._lost_escalation_run >= 2:
                self._smoothed_mode = TrackingMode.REACQUIRING
                return self._smoothed_mode
            if raw_mode == TrackingMode.REACQUIRING:
                self._smoothed_mode = TrackingMode.REACQUIRING
                return self._smoothed_mode
            return TrackingMode.WEAK_LOCKED

        self._smoothed_mode = raw_mode
        return self._smoothed_mode
```

---
### 文件: `shadowing_app/src/shadowing/types.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
from numpy.typing import NDArray


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
### 文件: `shadowing_app/tools/ab_compare_sessions.py`

```python
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
from pathlib import Path


def load_summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def print_metric_diff(name: str, a, b) -> None:
    if a is None or b is None:
        print(f"{name}: A={a} | B={b}")
        return
    try:
        diff = float(b) - float(a)
        print(f"{name}: A={a} | B={b} | delta={diff:+.4f}")
    except Exception:
        print(f"{name}: A={a} | B={b}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two session summary.json files")
    parser.add_argument("--a", type=str, required=True)
    parser.add_argument("--b", type=str, required=True)
    args = parser.parse_args()

    a = load_summary(Path(args.a))
    b = load_summary(Path(args.b))

    ma = a.get("metrics", {})
    mb = b.get("metrics", {})

    print("=== A/B Session Compare ===")
    for key in [
        "first_signal_active_time_sec",
        "first_asr_partial_time_sec",
        "first_reliable_progress_time_sec",
        "startup_false_hold_count",
        "hold_count",
        "resume_count",
        "soft_duck_count",
        "seek_count",
        "lost_count",
        "reacquire_count",
        "max_tracking_quality",
        "mean_tracking_quality",
        "total_progress_updates",
    ]:
        print_metric_diff(key, ma.get(key), mb.get(key))

    la = a.get("latency_calibration", {})
    lb = b.get("latency_calibration", {})
    print()
    print("=== Latency Calibration Compare ===")
    for key in [
        "estimated_input_latency_ms",
        "estimated_output_latency_ms",
        "confidence",
    ]:
        print_metric_diff(key, la.get(key), lb.get(key))
```

---
### 文件: `shadowing_app/tools/batch_session_report.py`

```python
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
from pathlib import Path


def load_summary(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate session summary.json files under a runtime session root")
    parser.add_argument("--root", type=str, required=True)
    args = parser.parse_args()

    root = Path(args.root)
    summaries = list(root.rglob("summary.json"))

    if not summaries:
        print("No summary.json files found.")
        return

    n = 0
    hold_count = 0
    resume_count = 0
    soft_duck_count = 0
    seek_count = 0
    lost_count = 0
    startup_false_hold_count = 0
    mean_tracking_quality_sum = 0.0
    first_reliable_progress_sum = 0.0
    first_reliable_progress_n = 0

    for path in summaries:
        data = load_summary(path)
        if data is None:
            continue

        metrics = data.get("metrics", {})
        n += 1
        hold_count += int(metrics.get("hold_count", 0))
        resume_count += int(metrics.get("resume_count", 0))
        soft_duck_count += int(metrics.get("soft_duck_count", 0))
        seek_count += int(metrics.get("seek_count", 0))
        lost_count += int(metrics.get("lost_count", 0))
        startup_false_hold_count += int(metrics.get("startup_false_hold_count", 0))
        mean_tracking_quality_sum += float(metrics.get("mean_tracking_quality", 0.0))

        frp = metrics.get("first_reliable_progress_time_sec")
        if frp is not None:
            first_reliable_progress_sum += float(frp)
            first_reliable_progress_n += 1

    print("=== Batch Session Report ===")
    print(f"session_count: {n}")
    print(f"hold_count_total: {hold_count}")
    print(f"resume_count_total: {resume_count}")
    print(f"soft_duck_count_total: {soft_duck_count}")
    print(f"seek_count_total: {seek_count}")
    print(f"lost_count_total: {lost_count}")
    print(f"startup_false_hold_count_total: {startup_false_hold_count}")
    print(f"mean_tracking_quality_avg: {mean_tracking_quality_sum / max(1, n):.4f}")
    if first_reliable_progress_n > 0:
        print(f"first_reliable_progress_time_avg_sec: {first_reliable_progress_sum / first_reliable_progress_n:.4f}")
    else:
        print("first_reliable_progress_time_avg_sec: N/A")
```

---
### 文件: `shadowing_app/tools/list_playback_devices.py`

```python
import _bootstrap  # noqa: F401

import sounddevice as sd


def main() -> None:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    print("=== Output devices ===")
    for idx, dev in enumerate(devices):
        max_out = int(dev["max_output_channels"])
        if max_out <= 0:
            continue
        hostapi_name = hostapis[int(dev["hostapi"])]["name"]
        print(
            f"[{idx}] {dev['name']} | hostapi={hostapi_name} | "
            f"max_out={max_out} | default_sr={float(dev['default_samplerate'])}"
        )

    default_in, default_out = sd.default.device
    print()
    print(f"Default output device: {default_out}")


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/tools/list_recording_devices.py`

```python
import _bootstrap  # noqa: F401

from shadowing.realtime.capture.device_utils import (
    get_default_input_device_index,
    pick_working_input_config,
    print_input_devices,
)


def main() -> None:
    print_input_devices()

    default_idx = get_default_input_device_index()
    print()
    print(f"Default input device: {default_idx}")

    config = pick_working_input_config()
    print()
    print("Suggested recording config:")
    print(config)


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/tools/preprocess_lesson.py`

```python
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import os
import re
import shutil
from pathlib import Path

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.preprocess.pipeline import LessonPreprocessPipeline
from shadowing.preprocess.providers.elevenlabs_tts import ElevenLabsTTSProvider


DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "pcm_44100"


def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r'[\\/:\\*\\?"<>\\|]+', "_", stem)
    stem = re.sub(r"\\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def lesson_assets_exist(lesson_dir: Path) -> tuple[bool, list[str]]:
    manifest = lesson_dir / "lesson_manifest.json"
    ref_map = lesson_dir / "reference_map.json"
    chunks_dir = lesson_dir / "chunks"
    missing: list[str] = []
    if not manifest.exists():
        missing.append(str(manifest))
    if not ref_map.exists():
        missing.append(str(ref_map))
    if not chunks_dir.exists():
        missing.append(str(chunks_dir))
    else:
        has_audio = any(chunks_dir.glob("*.wav")) or any(chunks_dir.glob("*.mp3"))
        if not has_audio:
            missing.append(f"{chunks_dir} (no audio files found)")
    return len(missing) == 0, missing


def same_source_text(lesson_dir: Path, current_text: str) -> bool:
    source_path = lesson_dir / "source.txt"
    return source_path.exists() and source_path.read_text(encoding="utf-8").strip() == current_text.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess a local txt speech file into lesson assets using ElevenLabs.")
    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--api-key", type=str, default=os.getenv("ELEVENLABS_API_KEY", ""))
    parser.add_argument("--voice-id", type=str, default=DEFAULT_VOICE_ID)
    parser.add_argument("--model-id", type=str, default=DEFAULT_MODEL_ID)
    parser.add_argument("--output-format", type=str, default=DEFAULT_OUTPUT_FORMAT)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    lesson_text = text_path.read_text(encoding="utf-8").strip()
    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    output_dir = lesson_base_dir / lesson_id
    output_dir.mkdir(parents=True, exist_ok=True)

    assets_ok, missing = lesson_assets_exist(output_dir)
    text_same = same_source_text(output_dir, lesson_text)
    if assets_ok and text_same and not args.force:
        print("Local lesson assets already exist and source text is unchanged. Skip ElevenLabs preprocessing.")
        return

    if not args.api_key:
        raise ValueError("Missing ElevenLabs API key. Pass --api-key or set ELEVENLABS_API_KEY.")

    source_copy_path = output_dir / "source.txt"
    if source_copy_path.resolve() != text_path:
        shutil.copyfile(text_path, source_copy_path)

    tts = ElevenLabsTTSProvider(
        api_key=args.api_key,
        voice_id=args.voice_id,
        model_id=args.model_id,
        output_format=args.output_format,
    )
    repo = FileLessonRepository(str(lesson_base_dir))
    LessonPreprocessPipeline(tts_provider=tts, repo=repo).run(
        lesson_id=lesson_id,
        text=lesson_text,
        output_dir=str(output_dir),
    )
    print(f"Preprocess completed: {output_dir}")
    if missing:
        print("Previous missing items:")
        for item in missing:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/tools/replay_session.py`

```python
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
from collections import Counter

from shadowing.telemetry.replay_loader import ReplayLoader


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay and summarize a recorded runtime session events.jsonl")
    parser.add_argument("--events-file", type=str, required=True)
    args = parser.parse_args()

    loader = ReplayLoader(args.events_file)

    counts = Counter()
    last_tracking_mode = None
    last_user_state = None
    max_tracking_quality = 0.0
    max_signal = 0.0

    first_tick = None
    last_tick = None
    first_ts = None
    last_ts = None

    for ev in loader:
        counts[ev.event_type] += 1

        if ev.session_tick is not None:
            if first_tick is None:
                first_tick = ev.session_tick
            last_tick = ev.session_tick

        if ev.ts_monotonic_sec is not None:
            if first_ts is None:
                first_ts = ev.ts_monotonic_sec
            last_ts = ev.ts_monotonic_sec

        if ev.event_type == "tracking_snapshot":
            mode = ev.payload.get("tracking_mode")
            tq = float(ev.payload.get("overall_score", 0.0))
            max_tracking_quality = max(max_tracking_quality, tq)
            last_tracking_mode = mode

        elif ev.event_type == "progress_snapshot":
            last_user_state = ev.payload.get("user_state")

        elif ev.event_type == "signal_snapshot":
            max_signal = max(max_signal, float(ev.payload.get("speaking_likelihood", 0.0)))

        elif ev.event_type == "session_summary":
            print("=== Session Summary (recorded) ===")
            print(ev.payload)

    print()
    print("=== Replay Counters ===")
    for k in sorted(counts):
        print(f"{k}: {counts[k]}")

    print()
    print("=== Replay Timeline ===")
    print(f"first_tick: {first_tick}")
    print(f"last_tick: {last_tick}")
    print(f"first_ts_monotonic_sec: {first_ts}")
    print(f"last_ts_monotonic_sec: {last_ts}")

    print()
    print(f"Last tracking mode: {last_tracking_mode}")
    print(f"Last user state: {last_user_state}")
    print(f"Max tracking quality: {max_tracking_quality:.3f}")
    print(f"Max speaking likelihood: {max_signal:.3f}")


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/tools/run_shadowing.py`

```python
from __future__ import annotations

import _bootstrap  # noqa: F401
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
from shadowing.bootstrap import build_runtime
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


def _resolve_output_device_name(device_index: int | None) -> str:
    if device_index is None:
        _, default_out = sd.default.device
        if default_out is None or int(default_out) < 0:
            return "unknown"
        device_index = int(default_out)

    dev = sd.query_devices(device_index)
    return str(dev["name"])


def _resolve_input_device_name(device_value: int | str | None) -> str:
    if device_value is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            return "unknown"
        return str(sd.query_devices(int(default_in))["name"])

    if isinstance(device_value, int):
        return str(sd.query_devices(device_value)["name"])

    target = str(device_value).strip().lower()
    for _, dev in enumerate(sd.query_devices()):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return str(dev["name"])

    return str(device_value)


def _run_bluetooth_preflight_or_fail(
    *,
    input_device: int | str | None,
    output_device: int | str | None,
    input_samplerate: int,
    playback_sample_rate: int,
    preflight_duration_sec: float,
    skip_bluetooth_preflight: bool,
) -> tuple[int | str | None, int | None]:
    if skip_bluetooth_preflight:
        print("[BT-PREFLIGHT] skipped by user.")
        return input_device, output_device if isinstance(output_device, int) else None

    should_run = should_run_bluetooth_preflight(
        input_device=input_device,
        output_device=output_device,
    )
    if not should_run:
        print("[BT-PREFLIGHT] not a bluetooth-headset session, skip.")
        return input_device, output_device if isinstance(output_device, int) else None

    result = run_bluetooth_duplex_preflight(
        BluetoothPreflightConfig(
            input_device=input_device,
            output_device=output_device,
            preferred_input_samplerate=int(input_samplerate),
            preferred_output_samplerate=int(playback_sample_rate),
            duration_sec=float(preflight_duration_sec),
        )
    )

    print(
        "[BT-PREFLIGHT] "
        f"input={result.input_device_name!r} "
        f"output={result.output_device_name!r} "
        f"sr={result.samplerate} "
        f"mean_rms={result.mean_rms:.6f} "
        f"max_peak={result.max_peak:.6f} "
        f"nonzero_ratio={result.nonzero_ratio:.6f} "
        f"voiced_frame_ratio={result.voiced_frame_ratio:.6f} "
        f"status_events={result.status_events} "
        f"passed={result.passed}"
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

    return result.input_device_index, result.output_device_index


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run shadowing realtime pipeline")

    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")

    parser.add_argument("--asr", type=str, default="sherpa", choices=["fake", "sherpa"])
    parser.add_argument("--output-device", type=int, default=None)
    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--input-samplerate", type=int, default=None)

    parser.add_argument("--bluetooth-offset-sec", type=float, default=0.18)
    parser.add_argument("--playback-latency", type=str, default="high")
    parser.add_argument("--playback-blocksize", type=int, default=2048)

    parser.add_argument("--asr-debug-feed", action="store_true")
    parser.add_argument("--asr-debug-feed-every", type=int, default=20)

    parser.add_argument("--skip-bluetooth-preflight", action="store_true")
    parser.add_argument("--preflight-duration-sec", type=float, default=3.5)

    parser.add_argument("--tick-sleep-sec", type=float, default=0.03)
    parser.add_argument("--profile-path", type=str, default="runtime/device_profiles.json")
    parser.add_argument("--session-dir", type=str, default="runtime/latest_session")
    parser.add_argument("--event-logging", action="store_true")

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

    effective_input_device, effective_output_device = _run_bluetooth_preflight_or_fail(
        input_device=effective_input_device,
        output_device=args.output_device,
        input_samplerate=effective_input_samplerate,
        playback_sample_rate=playback_sample_rate,
        preflight_duration_sec=float(args.preflight_duration_sec),
        skip_bluetooth_preflight=bool(args.skip_bluetooth_preflight),
    )

    input_device_name = _resolve_input_device_name(effective_input_device)
    output_device_name = _resolve_output_device_name(effective_output_device)

    print(
        "[RUN-CONFIG] "
        f"lesson_id={lesson_id} "
        f"input_device={effective_input_device!r} "
        f"input_name={input_device_name!r} "
        f"input_samplerate={effective_input_samplerate} "
        f"output_device={effective_output_device!r} "
        f"output_name={output_device_name!r} "
        f"playback_sr={playback_sample_rate} "
        f"playback_latency={args.playback_latency} "
        f"playback_blocksize={int(args.playback_blocksize)}"
    )

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
                "backend": "sounddevice",
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
            },
            "alignment": {
                "window_back": 8,
                "window_ahead": 40,
                "stable_frames": 2,
                "min_confidence": 0.60,
                "backward_lock_frames": 3,
                "clause_boundary_bonus": 0.15,
                "cross_clause_backward_extra_penalty": 0.20,
                "debug": False,
                "max_hyp_tokens": 16,
            },
            "control": {
                "target_lead_sec": 0.15,
                "hold_if_lead_sec": 0.90,
                "resume_if_lead_sec": 0.28,
                "seek_if_lag_sec": -1.80,
                "min_confidence": 0.75,
                "seek_cooldown_sec": 1.20,
                "gain_following": 0.55,
                "gain_transition": 0.80,
                "gain_soft_duck": 0.42,
                "guide_play_sec": 2.20,
                "no_progress_hold_min_play_sec": 4.00,
                "progress_stale_sec": 1.10,
                "hold_trend_sec": 0.75,
                "tracking_quality_hold_min": 0.60,
                "tracking_quality_seek_min": 0.72,
                "resume_from_hold_speaking_lead_slack_sec": 0.45,
                "disable_seek": False,
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
                "input_sample_rate": effective_input_samplerate,
                "noise_floor_rms": 0.0025,
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

---
### 文件: `shadowing_app/tools/test_open_input_devices.py`

```python
from __future__ import annotations
import _bootstrap  # noqa: F401

import sounddevice as sd


def main() -> None:
    devices = sd.query_devices()
    input_devices = [
        (idx, dev)
        for idx, dev in enumerate(devices)
        if int(dev["max_input_channels"]) > 0
    ]

    print("=== Input device probe ===")
    for ordinal, (raw_idx, dev) in enumerate(input_devices):
        name = str(dev["name"])
        max_in = int(dev["max_input_channels"])
        default_sr = int(float(dev["default_samplerate"]))
        print(f"\\n[{ordinal}] raw={raw_idx} name={name!r} max_in={max_in} default_sr={default_sr}")

        candidate_sample_rates = []
        for sr in [48000, 44100, default_sr]:
            if sr > 0 and sr not in candidate_sample_rates:
                candidate_sample_rates.append(sr)

        candidate_channels = []
        for ch in [1, 2, max_in]:
            if ch > 0 and ch <= max_in and ch not in candidate_channels:
                candidate_channels.append(ch)

        opened = False
        for sr in candidate_sample_rates:
            for ch in candidate_channels:
                try:
                    stream = sd.InputStream(
                        samplerate=sr,
                        device=raw_idx,
                        channels=ch,
                        dtype="float32",
                        latency="low",
                        blocksize=0,
                    )
                    stream.start()
                    stream.stop()
                    stream.close()
                    print(f"  OK   samplerate={sr} channels={ch}")
                    opened = True
                except Exception as e:
                    print(f"  FAIL samplerate={sr} channels={ch} -> {e}")

        if not opened:
            print("  No working combination found for this device.")


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/tools/test_soundcard_mic.py`

```python
import time
import numpy as np
import pythoncom
import soundcard as sc


def main():
    pythoncom.CoInitialize()
    try:
        mics = list(sc.all_microphones(include_loopback=False))
        print("available microphones:")
        for i, mic in enumerate(mics):
            print(f"  [{i}] {mic.name!r}")

        mic = mics[0]
        print(f"\\nusing: {mic.name!r}")

        with mic.recorder(samplerate=48000, channels=1) as rec:
            print("start recording... speak now")
            for i in range(20):
                data = rec.record(numframes=1024)
                audio = np.asarray(data, dtype=np.float32).reshape(-1)
                rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
                peak = float(np.max(np.abs(audio))) if audio.size else 0.0
                print(f"[{i:02d}] shape={audio.shape} rms={rms:.6f} peak={peak:.6f}")
                time.sleep(0.1)
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/tools/test_sounddevice_input_level.py`

```python
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd


@dataclass(slots=True)
class LevelStats:
    mean_rms: float
    max_peak: float
    nonzero_ratio: float
    voiced_frame_ratio: float
    total_callbacks: int
    status_events: int
    resolved_device_index: int
    resolved_device_name: str
    samplerate: int
    channels: int


def resolve_input_device(device: int | str | None) -> tuple[int, str]:
    devices = sd.query_devices()

    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Device is not an input device: idx={device}, name={dev['name']}")
        return int(device), str(dev["name"])

    if device is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            raise RuntimeError("No default input device available.")
        dev = sd.query_devices(int(default_in))
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Default device is not input-capable: idx={default_in}, name={dev['name']}")
        return int(default_in), str(dev["name"])

    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return int(idx), str(dev["name"])

    raise RuntimeError(f"No matching input device found: {device!r}")


def pick_samplerate(device_index: int, requested_sr: int | None, channels: int, dtype: str) -> int:
    dev = sd.query_devices(device_index, "input")
    candidates: list[int] = []

    for sr in (
        requested_sr or 0,
        int(float(dev["default_samplerate"])),
        48000,
        44100,
        32000,
        24000,
        16000,
    ):
        if sr > 0 and sr not in candidates:
            candidates.append(int(sr))

    last_error: Exception | None = None
    for sr in candidates:
        try:
            sd.check_input_settings(
                device=device_index,
                samplerate=sr,
                channels=channels,
                dtype=dtype,
            )
            return int(sr)
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        f"Failed to find openable samplerate for input device idx={device_index}, "
        f"name={dev['name']}, last_error={last_error}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure sounddevice input RMS/peak/voice activity.")
    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--samplerate", type=int, default=None)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--dtype", type=str, default="float32")
    parser.add_argument("--duration-sec", type=float, default=4.0)
    parser.add_argument("--blocksize", type=int, default=0)
    parser.add_argument("--vad-rms-threshold", type=float, default=0.006)
    parser.add_argument("--vad-peak-threshold", type=float, default=0.020)
    args = parser.parse_args()

    raw_input_device = args.input_device
    parsed_input_device: int | str | None
    if raw_input_device is None or str(raw_input_device).strip() == "":
        parsed_input_device = None
    elif str(raw_input_device).strip().isdigit():
        parsed_input_device = int(str(raw_input_device).strip())
    else:
        parsed_input_device = str(raw_input_device).strip()

    device_index, device_name = resolve_input_device(parsed_input_device)
    samplerate = pick_samplerate(
        device_index=device_index,
        requested_sr=args.samplerate,
        channels=int(args.channels),
        dtype=str(args.dtype),
    )

    rms_values: list[float] = []
    peak_values: list[float] = []
    nonzero_ratios: list[float] = []
    voiced_flags: list[int] = []
    status_events = 0
    callback_count = 0
    started_at = time.monotonic()

    def callback(indata, frames, time_info, status) -> None:
        nonlocal status_events, callback_count
        callback_count += 1

        if status:
            status_events += 1
            print(f"[INPUT-STATUS] {status}")

        audio = np.asarray(indata, dtype=np.float32)
        if audio.ndim == 2:
            mono = np.mean(audio, axis=1).astype(np.float32, copy=False)
        else:
            mono = audio.reshape(-1).astype(np.float32, copy=False)

        rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
        peak = float(np.max(np.abs(mono))) if mono.size else 0.0
        nonzero_ratio = float(np.mean(np.abs(mono) > 1e-4)) if mono.size else 0.0
        voiced = 1 if (rms >= float(args.vad_rms_threshold) or peak >= float(args.vad_peak_threshold)) else 0

        rms_values.append(rms)
        peak_values.append(peak)
        nonzero_ratios.append(nonzero_ratio)
        voiced_flags.append(voiced)

        if callback_count <= 5 or callback_count % 20 == 0:
            elapsed = time.monotonic() - started_at
            print(
                f"[INPUT-LEVEL] t={elapsed:.2f}s "
                f"rms={rms:.6f} peak={peak:.6f} nonzero_ratio={nonzero_ratio:.6f} voiced={voiced}"
            )

    print(
        "[INPUT-TEST] start "
        f"device_index={device_index} "
        f"device_name={device_name!r} "
        f"samplerate={samplerate} channels={int(args.channels)} "
        f"duration_sec={float(args.duration_sec)} blocksize={int(args.blocksize)}"
    )
    print("[INPUT-TEST] 请在测试期间持续说话。")

    with sd.InputStream(
        samplerate=samplerate,
        blocksize=int(args.blocksize),
        device=device_index,
        channels=int(args.channels),
        dtype=str(args.dtype),
        latency="low",
        callback=callback,
    ):
        time.sleep(float(args.duration_sec))

    stats = LevelStats(
        mean_rms=float(np.mean(rms_values)) if rms_values else 0.0,
        max_peak=float(np.max(peak_values)) if peak_values else 0.0,
        nonzero_ratio=float(np.mean(nonzero_ratios)) if nonzero_ratios else 0.0,
        voiced_frame_ratio=float(np.mean(voiced_flags)) if voiced_flags else 0.0,
        total_callbacks=int(callback_count),
        status_events=int(status_events),
        resolved_device_index=int(device_index),
        resolved_device_name=str(device_name),
        samplerate=int(samplerate),
        channels=int(args.channels),
    )

    print()
    print("=== Input Level Summary ===")
    print(f"device_index: {stats.resolved_device_index}")
    print(f"device_name: {stats.resolved_device_name}")
    print(f"samplerate: {stats.samplerate}")
    print(f"channels: {stats.channels}")
    print(f"total_callbacks: {stats.total_callbacks}")
    print(f"status_events: {stats.status_events}")
    print(f"mean_rms: {stats.mean_rms:.6f}")
    print(f"max_peak: {stats.max_peak:.6f}")
    print(f"nonzero_ratio: {stats.nonzero_ratio:.6f}")
    print(f"voiced_frame_ratio: {stats.voiced_frame_ratio:.6f}")

    if stats.mean_rms < 0.003 and stats.max_peak < 0.02:
        print("[INPUT-TEST] 结论：输入几乎静音。")
    elif stats.voiced_frame_ratio < 0.08:
        print("[INPUT-TEST] 结论：能量很弱或几乎没有稳定语音活动。")
    else:
        print("[INPUT-TEST] 结论：输入链路基本可用。")


if __name__ == "__main__":
    main()
```

---
### 文件: `sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/gitattributes`

```text
*.7z filter=lfs diff=lfs merge=lfs -text
*.arrow filter=lfs diff=lfs merge=lfs -text
*.bin filter=lfs diff=lfs merge=lfs -text
*.bz2 filter=lfs diff=lfs merge=lfs -text
*.ckpt filter=lfs diff=lfs merge=lfs -text
*.ftz filter=lfs diff=lfs merge=lfs -text
*.gz filter=lfs diff=lfs merge=lfs -text
*.h5 filter=lfs diff=lfs merge=lfs -text
*.joblib filter=lfs diff=lfs merge=lfs -text
*.lfs.* filter=lfs diff=lfs merge=lfs -text
*.mlmodel filter=lfs diff=lfs merge=lfs -text
*.model filter=lfs diff=lfs merge=lfs -text
*.msgpack filter=lfs diff=lfs merge=lfs -text
*.npy filter=lfs diff=lfs merge=lfs -text
*.npz filter=lfs diff=lfs merge=lfs -text
*.onnx filter=lfs diff=lfs merge=lfs -text
*.ot filter=lfs diff=lfs merge=lfs -text
*.parquet filter=lfs diff=lfs merge=lfs -text
*.pb filter=lfs diff=lfs merge=lfs -text
*.pickle filter=lfs diff=lfs merge=lfs -text
*.pkl filter=lfs diff=lfs merge=lfs -text
*.pt filter=lfs diff=lfs merge=lfs -text
*.pth filter=lfs diff=lfs merge=lfs -text
*.rar filter=lfs diff=lfs merge=lfs -text
*.safetensors filter=lfs diff=lfs merge=lfs -text
saved_model/**/* filter=lfs diff=lfs merge=lfs -text
*.tar.* filter=lfs diff=lfs merge=lfs -text
*.tar filter=lfs diff=lfs merge=lfs -text
*.tflite filter=lfs diff=lfs merge=lfs -text
*.tgz filter=lfs diff=lfs merge=lfs -text
*.wasm filter=lfs diff=lfs merge=lfs -text
*.xz filter=lfs diff=lfs merge=lfs -text
*.zip filter=lfs diff=lfs merge=lfs -text
*.zst filter=lfs diff=lfs merge=lfs -text
*tfevents* filter=lfs diff=lfs merge=lfs -text
```

