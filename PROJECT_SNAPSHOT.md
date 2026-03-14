# 项目快照

自动生成的项目代码快照。已移除 Python 注释与文档字符串。

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
### 文件: `shadowing_app/src/shadowing/audio/device_profile.py`

```python
from __future__ import annotations

from dataclasses import dataclass


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


def classify_input_device(device_name: str | None) -> str:
    name = (device_name or "").strip().lower()
    if not name:
        return "unknown"
    if "bluetooth" in name or "耳机" in name or "headset" in name:
        return "bluetooth_headset"
    if "usb" in name or "麦克风" in name or "microphone" in name:
        return "usb_mic"
    if "阵列" in name or "array" in name or "realtek" in name:
        return "builtin_mic"
    return "unknown"


def classify_output_device(device_name: str | None) -> str:
    name = (device_name or "").strip().lower()
    if not name:
        return "unknown"
    if "bluetooth" in name or "耳机" in name or "headset" in name:
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
    input_device_name: str | None,
    output_device_name: str | None,
    input_sample_rate: int,
    output_sample_rate: int,
    noise_floor_rms: float,
) -> DeviceProfile:
    input_kind = classify_input_device(input_device_name)
    output_kind = classify_output_device(output_device_name)

    return DeviceProfile(
        input_device_id=str(input_device_name or "unknown"),
        output_device_id=str(output_device_name or "unknown"),
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
        input_latency_adapt_ms: float = 12.0,
        output_latency_adapt_ms: float = 18.0,
    ) -> None:
        self.input_latency_adapt_ms = float(input_latency_adapt_ms)
        self.output_latency_adapt_ms = float(output_latency_adapt_ms)

        self._state: LatencyCalibrationState | None = None
        self._last_active_at_sec = 0.0
        self._first_signal_active_at_sec = 0.0
        self._first_progress_at_sec = 0.0

    def reset(self, device_profile: DeviceProfile) -> None:
        self._state = LatencyCalibrationState(
            estimated_input_latency_ms=float(device_profile.estimated_input_latency_ms),
            estimated_output_latency_ms=float(device_profile.estimated_output_latency_ms),
            confidence=0.20,
            calibrated=False,
        )
        self._last_active_at_sec = 0.0
        self._first_signal_active_at_sec = 0.0
        self._first_progress_at_sec = 0.0

    def observe_signal(self, signal_quality: SignalQuality) -> None:
        if self._state is None:
            return
        if signal_quality.vad_active or signal_quality.speaking_likelihood >= 0.48:
            self._last_active_at_sec = signal_quality.observed_at_sec
            if self._first_signal_active_at_sec <= 0.0:
                self._first_signal_active_at_sec = signal_quality.observed_at_sec

    def observe_progress(self, progress_event_at_sec: float) -> None:
        if self._state is None:
            return
        if progress_event_at_sec <= 0.0:
            return

        if self._first_progress_at_sec <= 0.0:
            self._first_progress_at_sec = progress_event_at_sec

        if self._first_signal_active_at_sec > 0.0:
            delta_ms = max(0.0, (progress_event_at_sec - self._first_signal_active_at_sec) * 1000.0)

            adapted_input = min(
                260.0,
                max(10.0, self._state.estimated_input_latency_ms * 0.82 + delta_ms * 0.18),
            )
            self._state.estimated_input_latency_ms = adapted_input

            if delta_ms > 120.0:
                self._state.estimated_output_latency_ms = min(
                    280.0,
                    self._state.estimated_output_latency_ms + self.output_latency_adapt_ms * 0.10,
                )

            self._state.confidence = min(0.92, self._state.confidence + 0.12)
            self._state.calibrated = self._state.confidence >= 0.55

    def snapshot(self) -> LatencyCalibrationState | None:
        return self._state
```

---
### 文件: `shadowing_app/src/shadowing/bootstrap.py`

```python
from __future__ import annotations

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig, FakeAsrStep
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.capture.soundcard_recorder import SoundCardRecorder
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.playback.sounddevice_player import PlaybackConfig, SoundDevicePlayer
from shadowing.realtime.runtime import ShadowingRuntime
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
        if event_type_raw == "final":
            event_type = AsrEventType.FINAL
        else:
            event_type = AsrEventType.PARTIAL

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
    )

    controller = StateMachineController(
        policy=policy,
        disable_seek=bool(control_cfg.get("disable_seek", False)),
    )

    runtime_cfg = config.get("runtime", {})
    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
        audio_queue_maxsize=int(runtime_cfg.get("audio_queue_maxsize", 150)),
        asr_event_queue_maxsize=int(runtime_cfg.get("asr_event_queue_maxsize", 64)),
        loop_interval_sec=float(runtime_cfg.get("loop_interval_sec", 0.03)),
    )

    if "runtime" in config:
        orchestrator.configure_runtime(config["runtime"])
    if "debug" in config:
        orchestrator.configure_debug(config["debug"])

    return ShadowingRuntime(orchestrator)
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


class SignalQualityMonitor:
    def __init__(
        self,
        min_vad_rms: float = 0.006,
        vad_noise_multiplier: float = 2.8,
        speaking_decay: float = 0.92,
        speaking_rise: float = 0.22,
        clipping_threshold: float = 0.98,
    ) -> None:
        self.min_vad_rms = float(min_vad_rms)
        self.vad_noise_multiplier = float(vad_noise_multiplier)
        self.speaking_decay = float(speaking_decay)
        self.speaking_rise = float(speaking_rise)
        self.clipping_threshold = float(clipping_threshold)
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

        if rms < max(self.min_vad_rms * 0.7, dynamic_threshold * 0.8):
            self.state.noise_floor_rms = 0.96 * noise_floor + 0.04 * rms
        else:
            self.state.noise_floor_rms = 0.995 * noise_floor + 0.005 * rms

        self.state.last_observed_at_sec = observed_at_sec
        self.state.last_rms = rms
        self.state.last_peak = peak
        self.state.clipping_ratio = clipping_ratio
        self.state.dropout_detected = rms <= 1e-5 and peak <= 1e-5

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
        if self.state.dropout_detected:
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
        self.window_selector = WindowSelector(look_back=window_back, look_ahead=window_ahead)
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
        window_tokens, window_start, window_end = self.window_selector.select(
            self.ref_map,
            self.state.committed_idx,
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
                f"mode={candidate.mode}"
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

    def select(self, ref_map: ReferenceMap, committed_idx: int) -> tuple[list[RefToken], int, int]:
        start = max(0, committed_idx - self.look_back)
        end = min(len(ref_map.tokens), committed_idx + self.look_ahead + 1)
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
### 文件: `shadowing_app/src/shadowing/realtime/asr/partial_adapter.py`

```python
from __future__ import annotations

from dataclasses import dataclass

from shadowing.types import AsrEventType, RawAsrEvent


@dataclass(slots=True)
class AdapterDebugInfo:
    branch: str
    raw_len: int
    adapted_len: int
    overlap: int


class RawPartialAdapter:
    def __init__(self, suffix_overlap_max: int = 24, max_tail_chars: int = 20, debug: bool = False) -> None:
        self.suffix_overlap_max = int(suffix_overlap_max)
        self.max_tail_chars = int(max_tail_chars)
        self.debug = bool(debug)
        self._last_text = ""

    def reset(self) -> None:
        self._last_text = ""

    def adapt(self, event: RawAsrEvent) -> RawAsrEvent | None:
        text = (event.text or "").strip()
        if not text:
            return None

        if event.event_type == AsrEventType.FINAL:
            self._last_text = text
            if self.debug:
                self._log(AdapterDebugInfo("final_passthrough", len(text), len(text), 0), text, text)
            return RawAsrEvent(
                event_type=event.event_type,
                text=text,
                emitted_at_sec=event.emitted_at_sec,
            )

        if text == self._last_text:
            return None

        prev = self._last_text
        self._last_text = text

        if not prev:
            tail = text[-self.max_tail_chars :]
            if self.debug:
                self._log(AdapterDebugInfo("first_tail", len(text), len(tail), 0), text, tail)
            return RawAsrEvent(
                event_type=event.event_type,
                text=tail,
                emitted_at_sec=event.emitted_at_sec,
            )

        if text.startswith(prev):
            delta = text[len(prev) :]
            if delta:
                tail = (prev[-min(len(prev), self.suffix_overlap_max) :] + delta)[-self.max_tail_chars :]
                if self.debug:
                    self._log(AdapterDebugInfo("prefix_growth", len(text), len(tail), len(prev)), text, tail)
                return RawAsrEvent(
                    event_type=event.event_type,
                    text=tail,
                    emitted_at_sec=event.emitted_at_sec,
                )

        overlap = self._max_suffix_prefix_overlap(prev, text)
        if overlap > 0:
            delta_tail = text[overlap:]
            if delta_tail:
                tail = text[max(0, overlap - self.suffix_overlap_max) :]
                tail = tail[-self.max_tail_chars :]
                if self.debug:
                    self._log(AdapterDebugInfo("overlap_tail", len(text), len(tail), overlap), text, tail)
                return RawAsrEvent(
                    event_type=event.event_type,
                    text=tail,
                    emitted_at_sec=event.emitted_at_sec,
                )

        tail = text[-self.max_tail_chars :]
        if self.debug:
            self._log(AdapterDebugInfo("fallback_tail", len(text), len(tail), 0), text, tail)
        return RawAsrEvent(
            event_type=event.event_type,
            text=tail,
            emitted_at_sec=event.emitted_at_sec,
        )

    def _max_suffix_prefix_overlap(self, prev: str, current: str) -> int:
        max_len = min(len(prev), len(current), self.suffix_overlap_max)
        for k in range(max_len, 0, -1):
            if prev[-k:] == current[:k]:
                return k
        return 0

    def _log(self, info: AdapterDebugInfo, raw_text: str, adapted_text: str) -> None:
        print(
            "[ADAPT] "
            f"branch={info.branch} raw_len={info.raw_len} adapted_len={info.adapted_len} overlap={info.overlap} "
            f"raw={raw_text!r} adapted={adapted_text!r}"
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
            f"[{d.index}] {d.name} | hostapi={d.hostapi_name} | max_in={d.max_input_channels} | default_sr={d.default_samplerate}"
        )


def get_default_input_device_index() -> int | None:
    default_input, _ = sd.default.device
    if default_input is None or default_input < 0:
        return None
    return int(default_input)


def choose_input_device(preferred_index: int | None = None, preferred_name_substring: str | None = None) -> int | None:
    devices = list_input_devices()
    if not devices:
        return None
    if preferred_index is not None:
        for d in devices:
            if d.index == preferred_index:
                return d.index
    if preferred_name_substring:
        keyword = preferred_name_substring.lower()
        for d in devices:
            if keyword in d.name.lower():
                return d.index
    default_idx = get_default_input_device_index()
    if default_idx is not None:
        return default_idx
    return devices[0].index


def check_input_settings(device: int | None, samplerate: int, channels: int = 1, dtype: str = "float32") -> bool:
    try:
        sd.check_input_settings(device=device, samplerate=samplerate, channels=channels, dtype=dtype)
        return True
    except Exception:
        return False


def pick_working_input_config(
    preferred_device: int | None = None,
    preferred_rates: list[int] | None = None,
    channels: int = 1,
    dtype: str = "float32",
) -> dict[str, Any] | None:
    preferred_rates = preferred_rates or [48000, 44100, 16000]
    device = choose_input_device(preferred_index=preferred_device)
    if device is None:
        return None
    for sr in preferred_rates:
        if check_input_settings(device=device, samplerate=sr, channels=channels, dtype=dtype):
            return {"device": device, "samplerate": sr, "channels": channels, "dtype": dtype}
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
    PlaybackStatus,
    ProgressEstimate,
    SignalQuality,
    TrackingMode,
    UserReadState,
)


class StateMachineController(Controller):
    def __init__(
        self,
        policy: ControlPolicy | None = None,
        total_duration_sec: float | None = None,
        disable_seek: bool = False,
    ) -> None:
        self.policy = policy or ControlPolicy()
        self.total_duration_sec = total_duration_sec
        self.disable_seek = bool(disable_seek)

        self._last_seek_at = 0.0
        self._session_started_at = time.monotonic()

        self._phase = "bootstrapping"
        self._hold_condition_started_at = 0.0
        self._last_good_progress_at = 0.0

        self._last_decision_log_at = 0.0
        self._last_decision_signature = ""
        self._decision_log_interval_sec = 1.20

    def decide(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> ControlDecision:
        now = time.monotonic()

        if playback.state.value == "playing" and playback.t_ref_emitted_content_sec <= 0.05:
            self._session_started_at = now

        if progress is not None and progress.tracking_quality >= self.policy.tracking_quality_hold_min:
            self._last_good_progress_at = now

        self._update_phase(now, progress, signal_quality)

        if progress is None:
            decision = self._decide_without_progress(playback, signal_quality, now)
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        lead = playback.t_ref_heard_content_sec - progress.estimated_ref_time_sec

        if self._is_in_seek_recovery(now):
            decision = ControlDecision(
                action=ControlAction.NOOP,
                reason="recover_after_seek",
                lead_sec=lead,
                target_gain=self.policy.gain_transition,
                confidence=progress.tracking_quality,
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if playback.state.value == "holding":
            if self._should_resume_from_hold(lead, progress, signal_quality, now):
                decision = ControlDecision(
                    action=ControlAction.RESUME,
                    reason="rejoin_resume",
                    lead_sec=lead,
                    target_gain=self.policy.gain_following,
                    confidence=progress.tracking_quality,
                    aggressiveness="medium",
                )
                self._hold_condition_started_at = 0.0
                self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
                return decision

            decision = ControlDecision(
                action=ControlAction.NOOP,
                reason="holding_wait",
                lead_sec=lead,
                target_gain=self.policy.gain_following,
                confidence=progress.tracking_quality,
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._phase in ("bootstrapping", "guiding"):
            if self._signal_active(signal_quality):
                decision = ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="guide_soft_duck",
                    lead_sec=lead,
                    target_gain=self.policy.gain_soft_duck,
                    confidence=progress.tracking_quality,
                    aggressiveness="low",
                )
            else:
                decision = ControlDecision(
                    action=ControlAction.NOOP,
                    reason="guide_play",
                    lead_sec=lead,
                    target_gain=self.policy.gain_transition,
                    confidence=progress.tracking_quality,
                )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._phase in ("uncertain_follow", "reacquiring"):
            if lead > (self.policy.hold_if_lead_sec + self.policy.hold_extra_lead_sec):
                decision = ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="reacquire_soft_duck",
                    lead_sec=lead,
                    target_gain=self.policy.gain_soft_duck,
                    confidence=progress.tracking_quality,
                    aggressiveness="low",
                )
            else:
                decision = ControlDecision(
                    action=ControlAction.NOOP,
                    reason="uncertain_follow_keep_playing",
                    lead_sec=lead,
                    target_gain=self.policy.gain_transition,
                    confidence=progress.tracking_quality,
                )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._should_hold(playback, progress, signal_quality, lead, now):
            decision = ControlDecision(
                action=ControlAction.HOLD,
                reason="reference_too_far_ahead",
                lead_sec=lead,
                target_gain=self.policy.gain_following,
                confidence=progress.tracking_quality,
                aggressiveness="medium",
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        if self._should_seek(progress, lead, now):
            target_time = progress.estimated_ref_time_sec + self.policy.target_lead_sec
            if self.total_duration_sec is not None:
                target_time = min(max(0.0, target_time), self.total_duration_sec)
            else:
                target_time = max(0.0, target_time)

            self._last_seek_at = now
            decision = ControlDecision(
                action=ControlAction.SEEK,
                reason="user_skipped_forward",
                target_time_sec=target_time,
                lead_sec=lead,
                target_gain=self.policy.gain_following,
                confidence=progress.tracking_quality,
                aggressiveness="high",
            )
            self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
            return decision

        decision = ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            lead_sec=lead,
            target_gain=self.policy.gain_following,
            confidence=progress.tracking_quality,
        )
        self._log_decision_if_needed(playback, progress, signal_quality, decision, now)
        return decision

    def _update_phase(
        self,
        now: float,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
    ) -> None:
        elapsed = now - self._session_started_at

        if progress is None:
            if elapsed < self.policy.bootstrapping_sec:
                self._phase = "bootstrapping"
                return
            if elapsed < self.policy.no_progress_hold_min_play_sec:
                self._phase = "guiding"
                return
            self._phase = "waiting"
            return

        if progress.tracking_mode == TrackingMode.LOST:
            self._phase = "reacquiring"
            return

        if progress.tracking_mode == TrackingMode.REACQUIRING:
            self._phase = "reacquiring"
            return

        if elapsed < self.policy.bootstrapping_sec:
            self._phase = "bootstrapping"
            return

        if elapsed < self.policy.guide_play_sec and progress.user_state in (
            UserReadState.WARMING_UP,
            UserReadState.HESITATING,
            UserReadState.NOT_STARTED,
        ):
            self._phase = "guiding"
            return

        if progress.user_state in (UserReadState.REJOINING, UserReadState.SKIPPING):
            self._phase = "reacquiring"
            return

        if progress.user_state == UserReadState.FOLLOWING and progress.tracking_quality >= self.policy.tracking_quality_hold_min:
            self._phase = "following"
            return

        if progress.user_state in (
            UserReadState.WARMING_UP,
            UserReadState.HESITATING,
            UserReadState.REPEATING,
        ):
            self._phase = "uncertain_follow"
            return

        if progress.user_state in (
            UserReadState.PAUSED,
            UserReadState.NOT_STARTED,
        ):
            self._phase = "waiting"
            return

        if self._signal_active(signal_quality):
            self._phase = "uncertain_follow"
            return

        self._phase = "waiting"

    def _decide_without_progress(
        self,
        playback: PlaybackStatus,
        signal_quality: SignalQuality | None,
        now: float,
    ) -> ControlDecision:
        elapsed = now - self._session_started_at

        if elapsed < self.policy.bootstrapping_sec:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="bootstrapping",
                target_gain=self.policy.gain_transition,
                aggressiveness="low",
            )

        if elapsed < self.policy.no_progress_hold_min_play_sec:
            if self._signal_active(signal_quality):
                return ControlDecision(
                    action=ControlAction.SOFT_DUCK,
                    reason="guiding_soft_duck_no_progress",
                    target_gain=self.policy.gain_soft_duck,
                    aggressiveness="low",
                )
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="guiding_no_progress",
                target_gain=self.policy.gain_transition,
            )

        stale_good = self._stale_good_progress_sec(now)

        if playback.state.value == "holding":
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="waiting_for_progress",
                target_gain=self.policy.gain_following,
            )

        if self._signal_active(signal_quality):
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="no_progress_but_signal_active",
                target_gain=self.policy.gain_soft_duck,
                aggressiveness="low",
            )

        if stale_good < self.policy.low_confidence_continue_sec:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="keep_playing_recent_good_progress",
                target_gain=self.policy.gain_transition,
            )

        if playback.t_ref_heard_content_sec > (self.policy.hold_if_lead_sec + self.policy.hold_extra_lead_sec):
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="no_progress_timeout",
                target_gain=self.policy.gain_following,
                aggressiveness="medium",
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="wait_progress_soft",
            target_gain=self.policy.gain_transition,
        )

    def _should_resume_from_hold(
        self,
        lead: float,
        progress: ProgressEstimate,
        signal_quality: SignalQuality | None,
        now: float,
    ) -> bool:
        if lead <= self.policy.resume_if_lead_sec:
            return True

        signal_active = self._signal_active(signal_quality)
        event_fresh = (now - progress.event_emitted_at_sec) <= self.policy.resume_from_hold_event_fresh_sec

        if progress.user_state in (UserReadState.REJOINING, UserReadState.FOLLOWING):
            if event_fresh and signal_active:
                if lead <= (self.policy.hold_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec):
                    return True

        if progress.active_speaking and event_fresh:
            if lead <= (self.policy.hold_if_lead_sec + self.policy.resume_from_hold_speaking_lead_slack_sec):
                return True

        if progress.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
            if progress.recently_progressed and lead <= (self.policy.resume_if_lead_sec + 0.18):
                return True

        return False

    def _should_hold(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate,
        signal_quality: SignalQuality | None,
        lead: float,
        now: float,
    ) -> bool:
        if self._phase not in ("following", "waiting"):
            self._hold_condition_started_at = 0.0
            return False

        if progress.tracking_quality < self.policy.tracking_quality_hold_min:
            self._hold_condition_started_at = 0.0
            return False

        if progress.active_speaking or self._signal_active(signal_quality):
            self._hold_condition_started_at = 0.0
            return False

        hold_threshold = self.policy.hold_if_lead_sec
        if progress.confidence < self.policy.min_confidence:
            hold_threshold += self.policy.hold_extra_lead_sec

        if lead <= hold_threshold:
            self._hold_condition_started_at = 0.0
            return False

        if progress.progress_age_sec < self.policy.progress_stale_sec:
            self._hold_condition_started_at = 0.0
            return False

        if self._hold_condition_started_at <= 0.0:
            self._hold_condition_started_at = now
            return False

        if (now - self._hold_condition_started_at) < self.policy.hold_trend_sec:
            return False

        return True

    def _should_seek(self, progress: ProgressEstimate, lead: float, now: float) -> bool:
        if self.disable_seek:
            return False
        if progress.tracking_mode != TrackingMode.LOCKED:
            return False
        if progress.tracking_quality < self.policy.tracking_quality_seek_min:
            return False
        if not progress.stable:
            return False
        if lead >= self.policy.seek_if_lag_sec:
            return False
        if (now - self._last_seek_at) < self.policy.seek_cooldown_sec:
            return False
        return True

    def _signal_active(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= 0.48
        )

    def _stale_good_progress_sec(self, now: float) -> float:
        if self._last_good_progress_at <= 0:
            return float("inf")
        return now - self._last_good_progress_at

    def _is_in_seek_recovery(self, now_sec: float) -> bool:
        return (now_sec - self._last_seek_at) < self.policy.recover_after_seek_sec

    def _log_decision_if_needed(
        self,
        playback: PlaybackStatus,
        progress: ProgressEstimate | None,
        signal_quality: SignalQuality | None,
        decision: ControlDecision,
        now: float,
    ) -> None:
        lead_str = "None" if decision.lead_sec is None else f"{decision.lead_sec:.3f}"
        conf_str = "None" if progress is None else f"{progress.confidence:.3f}"
        tq_str = "None" if progress is None else f"{progress.tracking_quality:.3f}"
        est_idx_str = "None" if progress is None else str(progress.estimated_ref_idx)
        mode_str = "None" if progress is None else progress.tracking_mode.value
        user_state_str = "None" if progress is None else progress.user_state.value
        signal_str = "None" if signal_quality is None else f"{signal_quality.speaking_likelihood:.2f}"

        signature = (
            f"{self._phase}|{playback.state.value}|{decision.action.value}|{decision.reason}|"
            f"{lead_str}|{conf_str}|{tq_str}|{est_idx_str}|{mode_str}|{user_state_str}|{signal_str}"
        )

        should_log = False
        if signature != self._last_decision_signature:
            should_log = True
        elif decision.action in (
            ControlAction.HOLD,
            ControlAction.RESUME,
            ControlAction.SEEK,
            ControlAction.SOFT_DUCK,
        ):
            should_log = True
        elif (now - self._last_decision_log_at) >= self._decision_log_interval_sec:
            should_log = True

        if not should_log:
            return

        print(
            "[CTRL] "
            f"phase={self._phase} "
            f"playback={playback.state.value} "
            f"action={decision.action.value} "
            f"reason={decision.reason} "
            f"lead={lead_str} "
            f"progress_conf={conf_str} "
            f"tracking_q={tq_str} "
            f"mode={mode_str} "
            f"user_state={user_state_str} "
            f"signal={signal_str} "
            f"estimated={est_idx_str}"
        )

        self._last_decision_signature = signature
        self._last_decision_log_at = now
```

---
### 文件: `shadowing_app/src/shadowing/realtime/orchestrator.py`

```python
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from shadowing.audio.device_profile import build_device_profile
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.repository import LessonRepository
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.commercial_progress_estimator import CommercialProgressEstimator
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.realtime.asr.partial_adapter import RawPartialAdapter
from shadowing.telemetry.event_logger import EventLogger
from shadowing.telemetry.metrics import MetricsAggregator
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.types import AsrEvent, ControlAction, PlayerCommand, PlayerCommandType


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner,
        controller: Controller,
        audio_queue_maxsize: int = 150,
        asr_event_queue_maxsize: int = 64,
        loop_interval_sec: float = 0.03,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller

        self.normalizer = TextNormalizer()
        self.partial_adapter = RawPartialAdapter()
        self.signal_monitor = SignalQualityMonitor()
        self.tracking_engine = TrackingEngine(aligner=self.aligner)
        self.progress_estimator = CommercialProgressEstimator()
        self.latency_calibrator = LatencyCalibrator()

        self.audio_frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=audio_queue_maxsize)
        self.asr_event_queue: queue.Queue[AsrEvent] = queue.Queue(maxsize=asr_event_queue_maxsize)

        self.loop_interval_sec = float(loop_interval_sec)
        self._running = False
        self._asr_thread: threading.Thread | None = None
        self._last_progress = None
        self._pure_playback = False
        self._debug_enabled = False
        self._last_seen_generation = 0
        self._use_partial_adapter = True

        self._audio_frames_enqueued = 0
        self._audio_frames_dropped = 0
        self._audio_queue_high_watermark = 0
        self._asr_events_emitted = 0
        self._asr_events_dropped = 0
        self._asr_poll_iterations = 0

        self._telemetry_enabled = True
        self._session_artifacts_dir = Path("artifacts/runtime_sessions")
        self._event_logger: EventLogger | None = None
        self._metrics = MetricsAggregator()

        self._device_profile = None

    def configure_runtime(self, runtime_cfg: dict) -> None:
        self._pure_playback = bool(runtime_cfg.get("pure_playback", False))
        self._use_partial_adapter = bool(runtime_cfg.get("use_partial_adapter", True))
        self._telemetry_enabled = bool(runtime_cfg.get("telemetry_enabled", True))
        self._session_artifacts_dir = Path(runtime_cfg.get("session_artifacts_dir", "artifacts/runtime_sessions"))

    def configure_debug(self, debug_cfg: dict) -> None:
        self._debug_enabled = bool(debug_cfg.get("enabled", False))
        self.partial_adapter.debug = bool(debug_cfg.get("adapter_debug", False))

        if hasattr(self.aligner, "debug"):
            try:
                self.aligner.debug = bool(debug_cfg.get("aligner_debug", False))
            except Exception:
                pass

        try:
            self.tracking_engine.debug = bool(debug_cfg.get("tracking_debug", False))
        except Exception:
            pass

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        if hasattr(self.controller, "total_duration_sec"):
            self.controller.total_duration_sec = ref_map.total_duration_sec

        now_sec = time.monotonic()
        self._metrics = MetricsAggregator()
        self._metrics.mark_session_started(now_sec)

        session_dir = self._session_artifacts_dir / lesson_id / time.strftime("%Y%m%d_%H%M%S")
        self._event_logger = EventLogger(str(session_dir), enabled=self._telemetry_enabled)

        self._device_profile = build_device_profile(
            input_device_name=getattr(self.recorder, "device", None),
            output_device_name=getattr(self.player.config, "device", None) if hasattr(self.player, "config") else None,
            input_sample_rate=int(getattr(self.recorder, "target_sample_rate", getattr(self.recorder, "sample_rate_in", 16000))),
            output_sample_rate=int(getattr(self.player.config, "sample_rate", 44100)) if hasattr(self.player, "config") else 44100,
            noise_floor_rms=0.0025,
        )
        self.latency_calibrator.reset(self._device_profile)

        self._event_logger.log(
            "session_started",
            {
                "lesson_id": lesson_id,
                "lesson_text_length": len(manifest.lesson_text),
                "sample_rate_out": manifest.sample_rate_out,
                "chunk_count": len(chunks),
                "ref_token_count": len(ref_map.tokens),
                "total_duration_sec": ref_map.total_duration_sec,
                "device_profile": {
                    "input_device_id": self._device_profile.input_device_id,
                    "output_device_id": self._device_profile.output_device_id,
                    "input_kind": self._device_profile.input_kind,
                    "output_kind": self._device_profile.output_kind,
                    "input_sample_rate": self._device_profile.input_sample_rate,
                    "output_sample_rate": self._device_profile.output_sample_rate,
                    "estimated_input_latency_ms": self._device_profile.estimated_input_latency_ms,
                    "estimated_output_latency_ms": self._device_profile.estimated_output_latency_ms,
                    "noise_floor_rms": self._device_profile.noise_floor_rms,
                    "input_gain_hint": self._device_profile.input_gain_hint,
                    "reliability_tier": self._device_profile.reliability_tier,
                },
            },
        )

        self.tracking_engine.reset(ref_map)
        self.progress_estimator.reset(ref_map, start_idx=0)
        self.player.load_chunks(chunks)

        self._running = True
        self._last_seen_generation = 0
        self._last_progress = None
        self._audio_frames_enqueued = 0
        self._audio_frames_dropped = 0
        self._audio_queue_high_watermark = 0
        self._asr_events_emitted = 0
        self._asr_events_dropped = 0
        self._asr_poll_iterations = 0

        self.player.start()

        if not self._pure_playback:
            if hasattr(self.asr, "hotwords"):
                try:
                    self.asr.hotwords = manifest.lesson_text
                except Exception:
                    pass

            self.partial_adapter.reset()
            self.asr.start()
            self._asr_thread = threading.Thread(target=self._asr_worker, daemon=True)
            self._asr_thread.start()
            self.recorder.start(self._on_audio_frame)

        while self._running:
            self._control_tick()
            time.sleep(self.loop_interval_sec)

    def stop_session(self) -> None:
        self._running = False

        if not self._pure_playback:
            try:
                self.recorder.stop()
            except Exception:
                pass

            try:
                self.asr.close()
            except Exception:
                pass

            if self._asr_thread is not None and self._asr_thread.is_alive():
                self._asr_thread.join(timeout=1.0)
            self._asr_thread = None

        try:
            self.player.stop()
            self.player.close()
        except Exception:
            pass

        latency_snapshot = self.latency_calibrator.snapshot()

        if self._event_logger is not None:
            self._event_logger.log(
                "session_summary",
                {
                    "metrics": self._metrics.summary_dict(),
                    "latency_calibration": (
                        {
                            "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                            "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                            "confidence": latency_snapshot.confidence,
                            "calibrated": latency_snapshot.calibrated,
                        }
                        if latency_snapshot is not None
                        else None
                    ),
                    "orchestrator_stats": {
                        "audio_enqueued": self._audio_frames_enqueued,
                        "audio_dropped": self._audio_frames_dropped,
                        "audio_q_high_watermark": self._audio_queue_high_watermark,
                        "asr_events_emitted": self._asr_events_emitted,
                        "asr_events_dropped": self._asr_events_dropped,
                        "asr_poll_iterations": self._asr_poll_iterations,
                        "use_partial_adapter": self._use_partial_adapter,
                    },
                },
            )

            summary_path = self._event_logger.session_dir / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "metrics": self._metrics.summary_dict(),
                        "latency_calibration": (
                            {
                                "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                                "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                                "confidence": latency_snapshot.confidence,
                                "calibrated": latency_snapshot.calibrated,
                            }
                            if latency_snapshot is not None
                            else None
                        ),
                        "orchestrator_stats": {
                            "audio_enqueued": self._audio_frames_enqueued,
                            "audio_dropped": self._audio_frames_dropped,
                            "audio_q_high_watermark": self._audio_queue_high_watermark,
                            "asr_events_emitted": self._asr_events_emitted,
                            "asr_events_dropped": self._asr_events_dropped,
                            "asr_poll_iterations": self._asr_poll_iterations,
                            "use_partial_adapter": self._use_partial_adapter,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        if self._debug_enabled:
            print(
                "[ORCH-STATS] "
                f"audio_enqueued={self._audio_frames_enqueued} "
                f"audio_dropped={self._audio_frames_dropped} "
                f"audio_q_high_watermark={self._audio_queue_high_watermark}/{self.audio_frame_queue.maxsize} "
                f"asr_events_emitted={self._asr_events_emitted} "
                f"asr_events_dropped={self._asr_events_dropped} "
                f"asr_poll_iterations={self._asr_poll_iterations} "
                f"use_partial_adapter={self._use_partial_adapter}"
            )

    def _on_audio_frame(self, pcm: bytes) -> None:
        now_sec = time.monotonic()
        self.signal_monitor.feed_pcm16(pcm, observed_at_sec=now_sec)

        signal_snapshot = self.signal_monitor.snapshot(now_sec)
        self.latency_calibrator.observe_signal(signal_snapshot)

        if self._device_profile is not None:
            self._device_profile.noise_floor_rms = signal_snapshot.rms if signal_snapshot.rms < 0.004 else self._device_profile.noise_floor_rms

        if signal_snapshot.vad_active or signal_snapshot.speaking_likelihood >= 0.48:
            self._metrics.observe_signal_active(now_sec)

        try:
            self.audio_frame_queue.put_nowait(pcm)
            self._audio_frames_enqueued += 1
            current_qsize = self.audio_frame_queue.qsize()
            if current_qsize > self._audio_queue_high_watermark:
                self._audio_queue_high_watermark = current_qsize
        except queue.Full:
            self._audio_frames_dropped += 1
            try:
                _ = self.audio_frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_frame_queue.put_nowait(pcm)
                self._audio_frames_enqueued += 1
                current_qsize = self.audio_frame_queue.qsize()
                if current_qsize > self._audio_queue_high_watermark:
                    self._audio_queue_high_watermark = current_qsize
            except queue.Full:
                self._audio_frames_dropped += 1

    def _asr_worker(self) -> None:
        while self._running and not self._pure_playback:
            try:
                pcm = self.audio_frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            self._asr_poll_iterations += 1
            self.asr.feed_pcm16(pcm)
            raw_events = self.asr.poll_raw_events()

            for raw in raw_events:
                candidate = raw
                if self._use_partial_adapter:
                    candidate = self.partial_adapter.adapt(raw)
                    if candidate is None:
                        continue

                normalized = self.normalizer.normalize_raw_event(candidate)
                if normalized is None:
                    continue

                if normalized.event_type.value == "partial":
                    self._metrics.observe_asr_partial(time.monotonic())

                if self._event_logger is not None:
                    self._event_logger.log(
                        "asr_event",
                        {
                            "event_type": normalized.event_type.value,
                            "text": normalized.text,
                            "normalized_text": normalized.normalized_text,
                            "chars_len": len(normalized.chars),
                            "emitted_at_sec": normalized.emitted_at_sec,
                        },
                    )

                try:
                    self.asr_event_queue.put_nowait(normalized)
                    self._asr_events_emitted += 1
                except queue.Full:
                    self._asr_events_dropped += 1
                    try:
                        _ = self.asr_event_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.asr_event_queue.put_nowait(normalized)
                        self._asr_events_emitted += 1
                    except queue.Full:
                        self._asr_events_dropped += 1

    def _handle_generation_change_if_needed(self, status) -> None:
        if status.generation == self._last_seen_generation:
            return

        if self._debug_enabled:
            print(f"[SYNC] playback generation changed {self._last_seen_generation} -> {status.generation}")

        self._last_seen_generation = status.generation
        self._last_progress = None

        while True:
            try:
                _ = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

        now_sec = time.monotonic()
        self.tracking_engine.on_playback_generation_changed(status.generation)
        self.progress_estimator.on_playback_generation_changed(now_sec)

        if self._event_logger is not None:
            self._event_logger.log(
                "playback_generation_changed",
                {
                    "generation": status.generation,
                    "observed_at_sec": now_sec,
                },
            )

    def _control_tick(self) -> None:
        status = self.player.get_status()
        self._handle_generation_change_if_needed(status)

        now_sec = time.monotonic()
        signal_snapshot = self.signal_monitor.snapshot(now_sec)

        if self._event_logger is not None:
            self._event_logger.log(
                "signal_snapshot",
                {
                    "observed_at_sec": signal_snapshot.observed_at_sec,
                    "rms": signal_snapshot.rms,
                    "peak": signal_snapshot.peak,
                    "vad_active": signal_snapshot.vad_active,
                    "speaking_likelihood": signal_snapshot.speaking_likelihood,
                    "silence_run_sec": signal_snapshot.silence_run_sec,
                    "quality_score": signal_snapshot.quality_score,
                },
            )

        while not self._pure_playback:
            try:
                event = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

            tracking_snapshot = self.tracking_engine.update(event)
            if tracking_snapshot is not None:
                self._metrics.observe_tracking_mode(tracking_snapshot.tracking_mode.value)

                if self._event_logger is not None:
                    self._event_logger.log(
                        "tracking_snapshot",
                        {
                            "candidate_ref_idx": tracking_snapshot.candidate_ref_idx,
                            "committed_ref_idx": tracking_snapshot.committed_ref_idx,
                            "candidate_ref_time_sec": tracking_snapshot.candidate_ref_time_sec,
                            "confidence": tracking_snapshot.confidence,
                            "stable": tracking_snapshot.stable,
                            "local_match_ratio": tracking_snapshot.local_match_ratio,
                            "repeat_penalty": tracking_snapshot.repeat_penalty,
                            "monotonic_consistency": tracking_snapshot.monotonic_consistency,
                            "anchor_consistency": tracking_snapshot.anchor_consistency,
                            "tracking_mode": tracking_snapshot.tracking_mode.value,
                            "tracking_quality": {
                                "overall_score": tracking_snapshot.tracking_quality.overall_score,
                                "observation_score": tracking_snapshot.tracking_quality.observation_score,
                                "temporal_consistency_score": tracking_snapshot.tracking_quality.temporal_consistency_score,
                                "anchor_score": tracking_snapshot.tracking_quality.anchor_score,
                                "is_reliable": tracking_snapshot.tracking_quality.is_reliable,
                            },
                            "matched_text": tracking_snapshot.matched_text,
                            "emitted_at_sec": tracking_snapshot.emitted_at_sec,
                        },
                    )

                self.latency_calibrator.observe_progress(float(tracking_snapshot.emitted_at_sec))

                self._last_progress = self.progress_estimator.update(
                    tracking_snapshot,
                    signal_snapshot,
                    now_sec,
                )

                if self._last_progress is not None:
                    self._metrics.observe_progress(
                        now_sec=now_sec,
                        tracking_quality=self._last_progress.tracking_quality,
                        is_reliable=self._last_progress.tracking_quality >= 0.66,
                    )

        status = self.player.get_status()

        if status.state.value == "finished":
            self._running = False
            return

        if self._pure_playback:
            return

        latest_progress = self.progress_estimator.snapshot(now_sec, signal_snapshot)
        self._last_progress = latest_progress

        if latest_progress is not None and self._event_logger is not None:
            self._event_logger.log(
                "progress_snapshot",
                {
                    "estimated_ref_idx": latest_progress.estimated_ref_idx,
                    "estimated_ref_time_sec": latest_progress.estimated_ref_time_sec,
                    "progress_velocity_idx_per_sec": latest_progress.progress_velocity_idx_per_sec,
                    "progress_age_sec": latest_progress.progress_age_sec,
                    "source_candidate_ref_idx": latest_progress.source_candidate_ref_idx,
                    "source_committed_ref_idx": latest_progress.source_committed_ref_idx,
                    "tracking_mode": latest_progress.tracking_mode.value,
                    "tracking_quality": latest_progress.tracking_quality,
                    "stable": latest_progress.stable,
                    "confidence": latest_progress.confidence,
                    "active_speaking": latest_progress.active_speaking,
                    "recently_progressed": latest_progress.recently_progressed,
                    "user_state": latest_progress.user_state.value,
                    "event_emitted_at_sec": latest_progress.event_emitted_at_sec,
                    "last_progress_at_sec": latest_progress.last_progress_at_sec,
                },
            )

        latency_snapshot = self.latency_calibrator.snapshot()
        if latency_snapshot is not None and self._event_logger is not None:
            self._event_logger.log(
                "latency_calibration",
                {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                },
            )

        decision = self.controller.decide(status, latest_progress, signal_snapshot)
        self._metrics.observe_action(
            action=decision.action.value,
            reason=decision.reason,
            now_sec=now_sec,
        )

        if self._event_logger is not None:
            self._event_logger.log(
                "control_decision",
                {
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "target_time_sec": decision.target_time_sec,
                    "lead_sec": decision.lead_sec,
                    "target_gain": decision.target_gain,
                    "confidence": decision.confidence,
                    "aggressiveness": decision.aggressiveness,
                    "playback_state": status.state.value,
                    "playback_generation": status.generation,
                    "t_ref_heard_content_sec": status.t_ref_heard_content_sec,
                    "t_ref_emitted_content_sec": status.t_ref_emitted_content_sec,
                },
            )

        if decision.target_gain is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SET_GAIN,
                    gain=decision.target_gain,
                    reason="adaptive_ducking",
                )
            )

        if decision.action == ControlAction.HOLD:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.HOLD, reason=decision.reason)
            )
        elif decision.action == ControlAction.RESUME:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.RESUME, reason=decision.reason)
            )
        elif decision.action == ControlAction.SEEK and decision.target_time_sec is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SEEK,
                    target_time_sec=decision.target_time_sec,
                    reason=decision.reason,
                )
            )
        elif decision.action == ControlAction.STOP:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.STOP, reason=decision.reason)
            )
            self._running = False
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
### 文件: `shadowing_app/src/shadowing/realtime/progress/behavior_interpreter.py`

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
### 文件: `shadowing_app/src/shadowing/realtime/progress/commercial_progress_estimator.py`

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
### 文件: `shadowing_app/src/shadowing/realtime/progress/monotonic_estimator.py`

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
### 文件: `shadowing_app/src/shadowing/realtime/runtime.py`

```python
from __future__ import annotations

from shadowing.realtime.orchestrator import ShadowingOrchestrator


class ShadowingRuntime:
    def __init__(self, orchestrator: ShadowingOrchestrator) -> None:
        self.orchestrator = orchestrator

    def run(self, lesson_id: str) -> None:
        try:
            self.orchestrator.start_session(lesson_id)
        finally:
            self.orchestrator.stop_session()
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

    def log(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return

        record = {
            "event_type": str(event_type),
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
                if reason in ("no_progress_timeout", "reference_too_far_ahead"):
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

    def reset(self, reference_map: ReferenceMap) -> None:
        self.ref_map = reference_map
        self._last_candidate_idx = 0
        self._last_snapshot = None
        self.anchor_manager.reset()
        self.loss_detector.reset()
        self.aligner.reset(reference_map)

    def on_playback_generation_changed(self, generation: int) -> None:
        self.aligner.on_playback_generation_changed(generation)
        self.loss_detector.reset()

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

        mode, temporal_consistency = self.loss_detector.update(
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

        quality = TrackingQuality(
            overall_score=float(overall_score),
            observation_score=float(observation_score),
            temporal_consistency_score=float(temporal_consistency),
            anchor_score=float(anchor_consistency),
            mode=mode,
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
            tracking_mode=mode,
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

    for ev in loader:
        counts[ev.event_type] += 1

        if ev.event_type == "tracking_snapshot":
            mode = ev.payload.get("tracking_mode")
            tq = float(ev.payload.get("tracking_quality", {}).get("overall_score", 0.0))
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


def build_config(
    lesson_base_dir: str,
    input_device: int | str | None,
    input_samplerate: int,
    asr_mode: str,
    bluetooth_offset_sec: float,
    playback_sample_rate: int,
    sherpa_paths: dict,
    pure_playback: bool,
    lesson_text_for_fake: str,
    startup_grace_sec: float,
    low_confidence_hold_sec: float,
    use_partial_adapter: bool,
    audio_queue_maxsize: int,
    asr_event_queue_maxsize: int,
    output_device: int | None,
    playback_latency: str,
    playback_blocksize: int,
    capture_backend: str,
    capture_latency: str,
    capture_blocksize: int,
    capture_include_loopback: bool,
    capture_debug_level_meter: bool,
    capture_debug_level_every_n_blocks: int,
    asr_debug_feed: bool,
    asr_debug_feed_every_n_chunks: int,
) -> dict:
    return {
        "lesson_base_dir": lesson_base_dir,
        "playback": {
            "sample_rate": playback_sample_rate,
            "channels": 1,
            "device": output_device,
            "bluetooth_output_offset_sec": bluetooth_offset_sec,
            "latency": playback_latency,
            "blocksize": playback_blocksize,
        },
        "capture": {
            "backend": capture_backend,
            "device_sample_rate": input_samplerate,
            "target_sample_rate": 16000,
            "channels": 1,
            "device": input_device,
            "dtype": "float32",
            "blocksize": capture_blocksize,
            "block_frames": capture_blocksize if capture_blocksize > 0 else 1440,
            "latency": capture_latency,
            "include_loopback": capture_include_loopback,
            "debug_level_meter": capture_debug_level_meter,
            "debug_level_every_n_blocks": capture_debug_level_every_n_blocks,
        },
        "asr": {
            "mode": asr_mode,
            "sample_rate": 16000,
            "hotwords": "",
            "tokens": sherpa_paths["tokens"],
            "encoder": sherpa_paths["encoder"],
            "decoder": sherpa_paths["decoder"],
            "joiner": sherpa_paths["joiner"],
            "num_threads": 2,
            "provider": "cpu",
            "feature_dim": 80,
            "decoding_method": "greedy_search",
            "hotwords_score": 1.5,
            "rule1_min_trailing_silence": 10.0,
            "rule2_min_trailing_silence": 10.0,
            "rule3_min_utterance_length": 60.0,
            "emit_partial_interval_sec": 0.08,
            "enable_endpoint": True,
            "debug_feed": asr_debug_feed,
            "debug_feed_every_n_chunks": asr_debug_feed_every_n_chunks,
            "reference_text": lesson_text_for_fake if asr_mode == "fake" else "",
            "chars_per_sec": 4.0,
            "emit_final_on_endpoint": True,
            "bytes_per_sample": 2,
            "channels": 1,
            "vad_rms_threshold": 0.01,
            "vad_min_active_ms": 30.0,
            "scripted_steps": [],
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
            "recover_after_seek_sec": 0.60,
            "startup_grace_sec": startup_grace_sec,
            "low_confidence_hold_sec": low_confidence_hold_sec,
            "disable_seek": False,
            "bootstrapping_sec": 1.80,
            "guide_play_sec": 2.20,
            "no_progress_hold_min_play_sec": 4.00,
            "speaking_recent_sec": 0.90,
            "progress_stale_sec": 1.10,
            "hold_trend_sec": 0.75,
            "hold_extra_lead_sec": 0.18,
            "low_confidence_continue_sec": 1.40,
            "tracking_quality_hold_min": 0.60,
            "tracking_quality_seek_min": 0.72,
            "resume_from_hold_event_fresh_sec": 0.45,
            "resume_from_hold_speaking_lead_slack_sec": 0.45,
            "reacquire_soft_duck_sec": 2.00,
        },
        "runtime": {
            "pure_playback": pure_playback,
            "use_partial_adapter": use_partial_adapter,
            "audio_queue_maxsize": audio_queue_maxsize,
            "asr_event_queue_maxsize": asr_event_queue_maxsize,
            "loop_interval_sec": 0.03,
            "telemetry_enabled": True,
            "session_artifacts_dir": "artifacts/runtime_sessions",
        },
        "debug": {
            "enabled": False,
            "adapter_debug": False,
            "aligner_debug": False,
            "tracking_debug": False,
        },
    }


def _parse_input_device_arg(raw_value: str | None) -> int | str | None:
    if raw_value is None:
        return None
    raw = str(raw_value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the shadowing app for a local txt speech lesson.")
    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")
    parser.add_argument("--asr", type=str, default="fake", choices=["fake", "sherpa"])
    parser.add_argument("--bluetooth-offset-sec", type=float, default=0.18)

    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--input-samplerate", type=int, default=None)
    parser.add_argument("--output-device", type=int, default=None)

    parser.add_argument("--pure-playback", action="store_true")
    parser.add_argument("--adapter-debug", action="store_true")
    parser.add_argument("--aligner-debug", action="store_true")
    parser.add_argument("--tracking-debug", action="store_true")
    parser.add_argument("--disable-seek", action="store_true")
    parser.add_argument("--bypass-partial-adapter", action="store_true")

    parser.add_argument("--audio-queue-maxsize", type=int, default=150)
    parser.add_argument("--asr-event-queue-maxsize", type=int, default=64)
    parser.add_argument("--startup-grace-sec", type=float, default=0.80)
    parser.add_argument("--low-confidence-hold-sec", type=float, default=0.60)

    parser.add_argument("--playback-latency", type=str, default="high")
    parser.add_argument("--playback-blocksize", type=int, default=2048)

    parser.add_argument("--capture-backend", type=str, default="sounddevice", choices=["sounddevice", "soundcard"])
    parser.add_argument("--capture-latency", type=str, default="low")
    parser.add_argument("--capture-blocksize", type=int, default=0)
    parser.add_argument("--capture-include-loopback", action="store_true")
    parser.add_argument("--capture-debug-level-meter", action="store_true")
    parser.add_argument("--capture-debug-level-every", type=int, default=20)

    parser.add_argument("--asr-debug-feed", action="store_true")
    parser.add_argument("--asr-debug-feed-every", type=int, default=20)

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

    if args.capture_backend == "sounddevice":
        rec_cfg = pick_working_input_config(
            preferred_device=parsed_input_device if isinstance(parsed_input_device, int) else None
        ) or {
            "device": parsed_input_device,
            "samplerate": args.input_samplerate or 48000,
        }
        if args.input_samplerate is not None:
            rec_cfg["samplerate"] = args.input_samplerate
        effective_input_device: int | str | None = rec_cfg["device"]
        effective_input_samplerate = int(rec_cfg["samplerate"])
    else:
        effective_input_device = parsed_input_device
        effective_input_samplerate = int(args.input_samplerate or 48000)

    sherpa_paths = collect_sherpa_paths()
    if args.asr == "sherpa" and not args.pure_playback:
        validate_sherpa_paths(sherpa_paths)

    if args.capture_backend == "soundcard" and isinstance(parsed_input_device, int):
        print(
            "[RUN-NOTE] soundcard backend uses soundcard microphone list index, "
            "not sounddevice raw device index."
        )

    print(
        f"[RUN-CONFIG] lesson_id={lesson_id} "
        f"capture_backend={args.capture_backend} "
        f"input_device={effective_input_device!r} "
        f"input_samplerate={effective_input_samplerate} "
        f"output_device={args.output_device!r} "
        f"playback_sr={playback_sample_rate} "
        f"playback_latency={args.playback_latency} "
        f"playback_blocksize={int(args.playback_blocksize)} "
        f"capture_latency={args.capture_latency} "
        f"capture_blocksize={int(args.capture_blocksize)}"
    )

    config = build_config(
        lesson_base_dir=str(lesson_base_dir),
        input_device=effective_input_device,
        input_samplerate=effective_input_samplerate,
        asr_mode=args.asr,
        bluetooth_offset_sec=args.bluetooth_offset_sec,
        playback_sample_rate=playback_sample_rate,
        sherpa_paths=sherpa_paths,
        pure_playback=args.pure_playback,
        lesson_text_for_fake=lesson_text,
        startup_grace_sec=float(args.startup_grace_sec),
        low_confidence_hold_sec=float(args.low_confidence_hold_sec),
        use_partial_adapter=not bool(args.bypass_partial_adapter),
        audio_queue_maxsize=int(args.audio_queue_maxsize),
        asr_event_queue_maxsize=int(args.asr_event_queue_maxsize),
        output_device=args.output_device,
        playback_latency=args.playback_latency,
        playback_blocksize=int(args.playback_blocksize),
        capture_backend=args.capture_backend,
        capture_latency=args.capture_latency,
        capture_blocksize=int(args.capture_blocksize),
        capture_include_loopback=bool(args.capture_include_loopback),
        capture_debug_level_meter=bool(args.capture_debug_level_meter),
        capture_debug_level_every_n_blocks=int(args.capture_debug_level_every),
        asr_debug_feed=bool(args.asr_debug_feed),
        asr_debug_feed_every_n_chunks=int(args.asr_debug_feed_every),
    )

    config["control"]["disable_seek"] = bool(args.disable_seek or args.asr == "fake")
    config["debug"]["enabled"] = bool(args.adapter_debug or args.aligner_debug or args.tracking_debug)
    config["debug"]["adapter_debug"] = bool(args.adapter_debug)
    config["debug"]["aligner_debug"] = bool(args.aligner_debug)
    config["debug"]["tracking_debug"] = bool(args.tracking_debug)
    config["alignment"]["debug"] = bool(args.aligner_debug)

    runtime = build_runtime(config)

    print("Starting shadowing runtime. Press Ctrl+C to stop.")
    try:
        runtime.run(lesson_id)
    except KeyboardInterrupt:
        print("\nStopped by user.")


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

