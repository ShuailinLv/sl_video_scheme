# 项目快照

自动生成的项目代码快照。已移除 Python 注释与文档字符串。

---
### 文件: `shadowing_app/scripts/preprocess_lesson.py`

```python
from __future__ import annotations

from pathlib import Path
from shadowing.preprocess.pipeline import LessonPreprocessPipeline
from shadowing.preprocess.providers.elevenlabs_tts import ElevenLabsTTSProvider
from shadowing.infrastructure.lesson_repo import FileLessonRepository


def main() -> None:
    lesson_id = "demo_lesson"
    text = Path("assets/lessons/demo_lesson/source.txt").read_text(encoding="utf-8")

    tts = ElevenLabsTTSProvider(
        api_key="YOUR_API_KEY",
        voice_id="YOUR_VOICE_ID",
        model_id="eleven_multilingual_v2",
    )
    repo = FileLessonRepository("assets/lessons")
    pipeline = LessonPreprocessPipeline(tts_provider=tts, repo=repo)
    pipeline.run(lesson_id=lesson_id, text=text, output_dir=f"assets/lessons/{lesson_id}")


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/scripts/run_shadowing.py`

```python
from __future__ import annotations

from shadowing.bootstrap import build_runtime


def main() -> None:
    config = {
        "lesson_base_dir": "assets/lessons",
        "playback": {
            "sample_rate": 48000,
            "device": None,
            "bluetooth_output_offset_sec": 0.18,
        },
        "capture": {
            "device_sample_rate": 48000,
            "target_sample_rate": 16000,
            "device": None,
        },
        "asr": {
            "hotwords": "",
        },
    }

    runtime = build_runtime(config)
    runtime.run("demo_lesson")


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/src/shadowing/analytics/pipeline.py`

```python
from __future__ import annotations

from shadowing.interfaces.analytics import AnalyticsProvider


class SessionAnalyticsPipeline:
    def __init__(self, provider: AnalyticsProvider) -> None:
        self.provider = provider

    def run(
        self,
        lesson_text: str,
        user_audio_path: str,
        output_dir: str,
    ) -> dict:
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

    def analyze_session(
        self,
        lesson_text: str,
        audio_path: str,
        output_dir: str,
    ) -> dict:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/bootstrap.py`

```python
from __future__ import annotations

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.realtime.playback.sounddevice_player import SoundDevicePlayer
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.runtime import ShadowingRuntime


def build_runtime(config: dict) -> ShadowingRuntime:
    repo = FileLessonRepository(config["lesson_base_dir"])

    player = SoundDevicePlayer(
        sample_rate=config["playback"]["sample_rate"],
        channels=1,
        device=config["playback"].get("device"),
        bluetooth_output_offset_sec=config["playback"].get("bluetooth_output_offset_sec", 0.0),
    )

    recorder = SoundDeviceRecorder(
        sample_rate_in=config["capture"]["device_sample_rate"],
        target_sample_rate=config["capture"]["target_sample_rate"],
        channels=1,
        device=config["capture"].get("device"),
    )

    asr = SherpaStreamingProvider(
        model_config=config["asr"],
        hotwords=config["asr"].get("hotwords", ""),
    )

    aligner = IncrementalAligner()
    controller = StateMachineController()

    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
    )
    return ShadowingRuntime(orchestrator)
```

---
### 文件: `shadowing_app/src/shadowing/domain/commands.py`

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StartSession:
    lesson_id: str


@dataclass(slots=True)
class StopSession:
    reason: str = "user_requested"


@dataclass(slots=True)
class HoldPlayback:
    reason: str


@dataclass(slots=True)
class ResumePlayback:
    reason: str


@dataclass(slots=True)
class SeekPlayback:
    target_time_sec: float
    reason: str
```

---
### 文件: `shadowing_app/src/shadowing/domain/events.py`

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SessionStarted:
    lesson_id: str


@dataclass(slots=True)
class SessionStopped:
    lesson_id: str
    reason: str


@dataclass(slots=True)
class PlaybackHeld:
    reason: str


@dataclass(slots=True)
class PlaybackResumed:
    reason: str


@dataclass(slots=True)
class PlaybackSeeked:
    target_time_sec: float
    reason: str
```

---
### 文件: `shadowing_app/src/shadowing/infrastructure/lesson_repo.py`

```python
from __future__ import annotations

import json
from pathlib import Path
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import LessonManifest, ReferenceMap, AudioChunk


class FileLessonRepository(LessonRepository):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def save_manifest(self, manifest: LessonManifest) -> None:
        lesson_dir = self.base_dir / manifest.lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)
        path = lesson_dir / "lesson_manifest.json"
        path.write_text(json.dumps(manifest.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_manifest(self, lesson_id: str) -> LessonManifest:
        path = self.base_dir / lesson_id / "lesson_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return LessonManifest(**data)

    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str:
        lesson_dir = self.base_dir / lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)
        path = lesson_dir / "reference_map.json"

        payload = {
            "lesson_id": ref_map.lesson_id,
            "total_duration_sec": ref_map.total_duration_sec,
            "tokens": [token.__dict__ for token in ref_map.tokens],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def load_reference_map(self, lesson_id: str) -> ReferenceMap:
        raise NotImplementedError

    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/aligner.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AsrEvent, AlignResult, ReferenceMap


class Aligner(ABC):
    @abstractmethod
    def reset(self, reference_map: ReferenceMap) -> None:
        raise NotImplementedError

    @abstractmethod
    def update(self, event: AsrEvent) -> AlignResult | None:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/analytics.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod


class AnalyticsProvider(ABC):
    @abstractmethod
    def analyze_session(
        self,
        lesson_text: str,
        audio_path: str,
        output_dir: str,
    ) -> dict:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/asr.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AsrEvent


class ASRProvider(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def poll_events(self) -> list[AsrEvent]:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/controller.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AlignResult, ControlDecision, PlaybackStatus


class Controller(ABC):
    @abstractmethod
    def decide(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult | None,
    ) -> ControlDecision:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/player.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import AudioChunk, PlaybackStatus


class Player(ABC):
    @abstractmethod
    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def hold(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def resume(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def seek(self, target_time_sec: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> PlaybackStatus:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/recorder.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class Recorder(ABC):
    @abstractmethod
    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/repository.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import LessonManifest, ReferenceMap, AudioChunk


class LessonRepository(ABC):
    @abstractmethod
    def save_manifest(self, manifest: LessonManifest) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_manifest(self, lesson_id: str) -> LessonManifest:
        raise NotImplementedError

    @abstractmethod
    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str:
        raise NotImplementedError

    @abstractmethod
    def load_reference_map(self, lesson_id: str) -> ReferenceMap:
        raise NotImplementedError

    @abstractmethod
    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/interfaces/tts.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import LessonManifest, ReferenceMap


class TTSProvider(ABC):
    @abstractmethod
    def synthesize_lesson(
        self,
        lesson_id: str,
        text: str,
        output_dir: str,
    ) -> tuple[LessonManifest, ReferenceMap]:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/chunker.py`

```python
from __future__ import annotations


class ClauseChunker:

    def split_text(self, text: str) -> list[str]:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/pipeline.py`

```python
from __future__ import annotations

from shadowing.interfaces.tts import TTSProvider
from shadowing.interfaces.repository import LessonRepository


class LessonPreprocessPipeline:
    def __init__(
        self,
        tts_provider: TTSProvider,
        repo: LessonRepository,
    ) -> None:
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

from pathlib import Path
from shadowing.interfaces.tts import TTSProvider
from shadowing.types import LessonManifest, ReferenceMap


class ElevenLabsTTSProvider(TTSProvider):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    def synthesize_lesson(
        self,
        lesson_id: str,
        text: str,
        output_dir: str,
    ) -> tuple[LessonManifest, ReferenceMap]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/preprocess/reference_builder.py`

```python
from __future__ import annotations

from shadowing.types import ReferenceMap, RefToken


class ReferenceBuilder:

    def build(
        self,
        lesson_id: str,
        chars: list[str],
        pinyins: list[str],
        starts: list[float],
        ends: list[float],
        sentence_ids: list[int],
        clause_ids: list[int],
    ) -> ReferenceMap:
        tokens: list[RefToken] = []

        for idx, (ch, py, ts, te, sid, cid) in enumerate(
            zip(chars, pinyins, starts, ends, sentence_ids, clause_ids, strict=True)
        ):
            tokens.append(
                RefToken(
                    idx=idx,
                    char=ch,
                    pinyin=py,
                    t_start=ts,
                    t_end=te,
                    sentence_id=sid,
                    clause_id=cid,
                )
            )

        total_duration = ends[-1] if ends else 0.0
        return ReferenceMap(
            lesson_id=lesson_id,
            tokens=tokens,
            total_duration_sec=total_duration,
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/incremental_aligner.py`

```python
from __future__ import annotations

from shadowing.interfaces.aligner import Aligner
from shadowing.types import AlignResult, AsrEvent, ReferenceMap
from shadowing.realtime.alignment.scoring import AlignmentScorer
from shadowing.realtime.alignment.window_selector import WindowSelector


class IncrementalAligner(Aligner):
    def __init__(self) -> None:
        self.ref_map: ReferenceMap | None = None
        self.committed_idx: int = 0
        self.last_candidate_idx: int = 0
        self.stable_count: int = 0
        self.scorer = AlignmentScorer()
        self.window_selector = WindowSelector()

    def reset(self, reference_map: ReferenceMap) -> None:
        self.ref_map = reference_map
        self.committed_idx = 0
        self.last_candidate_idx = 0
        self.stable_count = 0

    def update(self, event: AsrEvent) -> AlignResult | None:
        if self.ref_map is None:
            return None

        if not event.normalized_text:
            return None

        window, start, _ = self.window_selector.select(self.ref_map, self.committed_idx)

        candidate_idx = min(start + len(event.pinyin_seq), len(self.ref_map.tokens) - 1)

        if candidate_idx == self.last_candidate_idx:
            self.stable_count += 1
        else:
            self.stable_count = 1
            self.last_candidate_idx = candidate_idx

        stable = self.stable_count >= 2
        if stable and candidate_idx > self.committed_idx:
            self.committed_idx = candidate_idx

        token = self.ref_map.tokens[self.committed_idx]
        return AlignResult(
            committed_ref_idx=self.committed_idx,
            candidate_ref_idx=candidate_idx,
            ref_time_sec=token.t_end,
            confidence=0.75,
            stable=stable,
            matched_text=event.normalized_text,
            matched_pinyin=event.pinyin_seq,
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/scoring.py`

```python
from __future__ import annotations


class AlignmentScorer:

    def score_token_pair(
        self,
        ref_char: str,
        ref_py: str,
        hyp_char: str,
        hyp_py: str,
    ) -> float:
        if ref_char == hyp_char:
            return 2.0
        if ref_py == hyp_py:
            return 1.2
        return -0.8
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/window_selector.py`

```python
from __future__ import annotations

from shadowing.types import ReferenceMap


class WindowSelector:
    def __init__(self, look_back: int = 3, look_ahead: int = 18) -> None:
        self.look_back = look_back
        self.look_ahead = look_ahead

    def select(self, ref_map: ReferenceMap, committed_idx: int):
        start = max(0, committed_idx - self.look_back)
        end = min(len(ref_map.tokens), committed_idx + self.look_ahead)
        return ref_map.tokens[start:end], start, end
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/normalizer.py`

```python
from __future__ import annotations

from pypinyin import lazy_pinyin


class TextNormalizer:
    def normalize_text(self, text: str) -> str:
        return text.strip()

    def to_pinyin_seq(self, text: str) -> list[str]:
        norm = self.normalize_text(text)
        return lazy_pinyin(norm)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/sherpa_streaming_provider.py`

```python
from __future__ import annotations

import time
from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEvent, AsrEventType
from shadowing.realtime.asr.normalizer import TextNormalizer


class SherpaStreamingProvider(ASRProvider):
    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.normalizer = TextNormalizer()
        self._running = False

    def start(self) -> None:
        self._running = True

    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        pass

    def poll_events(self) -> list[AsrEvent]:
        fake_text = ""
        if not fake_text:
            return []

        normalized = self.normalizer.normalize_text(fake_text)
        pinyin_seq = self.normalizer.to_pinyin_seq(fake_text)

        return [
            AsrEvent(
                event_type=AsrEventType.PARTIAL,
                text=fake_text,
                normalized_text=normalized,
                pinyin_seq=pinyin_seq,
                emitted_at_sec=time.monotonic(),
            )
        ]

    def reset(self) -> None:
        pass

    def close(self) -> None:
        self._running = False
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/sounddevice_recorder.py`

```python
from __future__ import annotations

from collections.abc import Callable
from shadowing.interfaces.recorder import Recorder


class SoundDeviceRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | None = None,
    ) -> None:
        self.sample_rate_in = sample_rate_in
        self.target_sample_rate = target_sample_rate
        self.channels = channels
        self.device = device
        self._on_audio_frame: Callable[[bytes], None] | None = None

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        self._on_audio_frame = on_audio_frame
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/bluetooth_offset.py`

```python
from __future__ import annotations


class BluetoothOffsetCalibrator:

    def estimate_offset_sec(self) -> float:
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/policy.py`

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ControlPolicy:
    target_lead_sec: float = 0.15
    hold_if_lead_sec: float = 0.45
    resume_if_lead_sec: float = 0.18
    seek_if_lag_sec: float = -0.90
    min_confidence: float = 0.60
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/state_machine_controller.py`

```python
from __future__ import annotations

from shadowing.interfaces.controller import Controller
from shadowing.types import AlignResult, ControlAction, ControlDecision, PlaybackStatus
from shadowing.realtime.control.policy import ControlPolicy


class StateMachineController(Controller):
    def __init__(self, policy: ControlPolicy | None = None) -> None:
        self.policy = policy or ControlPolicy()

    def decide(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult | None,
    ) -> ControlDecision:
        if alignment is None:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="no_alignment",
            )

        if alignment.confidence < self.policy.min_confidence:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="low_confidence",
            )

        lead = playback.t_ref_heard_sec - alignment.ref_time_sec

        if lead > self.policy.hold_if_lead_sec:
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="reference_too_far_ahead",
                lead_sec=lead,
            )

        if lead <= self.policy.resume_if_lead_sec:
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="user_caught_up",
                lead_sec=lead,
            )

        if lead < self.policy.seek_if_lag_sec:
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="user_skipped_forward",
                target_time_sec=alignment.ref_time_sec,
                lead_sec=lead,
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            lead_sec=lead,
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/orchestrator.py`

```python
from __future__ import annotations

import time
from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.aligner import Aligner
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import ControlAction


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner: Aligner,
        controller: Controller,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller
        self._running = False

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        self.aligner.reset(ref_map)
        self.player.load_chunks(chunks)
        self.asr.start()

        self.recorder.start(self.asr.feed_pcm16)
        self.player.start()
        self._running = True

        while self._running:
            events = self.asr.poll_events()

            for event in events:
                alignment = self.aligner.update(event)
                status = self.player.get_status()
                decision = self.controller.decide(status, alignment)

                if decision.action == ControlAction.HOLD:
                    self.player.hold()
                elif decision.action == ControlAction.RESUME:
                    self.player.resume()
                elif decision.action == ControlAction.SEEK and decision.target_time_sec is not None:
                    self.player.seek(decision.target_time_sec)

            time.sleep(0.03)

    def stop_session(self) -> None:
        self._running = False
        self.recorder.stop()
        self.player.stop()
        self.asr.close()
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/chunk_queue.py`

```python
from __future__ import annotations

from shadowing.types import AudioChunk


class ChunkQueue:
    def __init__(self) -> None:
        self._chunks: list[AudioChunk] = []
        self._current_chunk_idx: int = 0
        self._frame_offset_in_chunk: int = 0

    def load(self, chunks: list[AudioChunk]) -> None:
        self._chunks = chunks
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0

    def seek(self, target_time_sec: float) -> None:
        raise NotImplementedError

    def read_frames(self, frames: int):
        raise NotImplementedError
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/playback_clock.py`

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackClockSnapshot:
    t_host_output_sec: float
    t_ref_sched_sec: float
    t_ref_heard_sec: float


class PlaybackClock:
    def __init__(self, bluetooth_output_offset_sec: float = 0.0) -> None:
        self.bluetooth_output_offset_sec = bluetooth_output_offset_sec

    def compute(
        self,
        output_buffer_dac_time_sec: float,
        scheduled_ref_time_sec: float,
    ) -> PlaybackClockSnapshot:
        heard = scheduled_ref_time_sec - self.bluetooth_output_offset_sec
        return PlaybackClockSnapshot(
            t_host_output_sec=output_buffer_dac_time_sec,
            t_ref_sched_sec=scheduled_ref_time_sec,
            t_ref_heard_sec=max(0.0, heard),
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/sounddevice_player.py`

```python
from __future__ import annotations

import threading
from shadowing.interfaces.player import Player
from shadowing.types import AudioChunk, PlaybackState, PlaybackStatus
from shadowing.realtime.playback.chunk_queue import ChunkQueue
from shadowing.realtime.playback.playback_clock import PlaybackClock


class SoundDevicePlayer(Player):
    def __init__(
        self,
        sample_rate: int,
        channels: int,
        device: int | None = None,
        bluetooth_output_offset_sec: float = 0.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.clock = PlaybackClock(bluetooth_output_offset_sec)
        self.queue = ChunkQueue()

        self._state = PlaybackState.STOPPED
        self._lock = threading.Lock()

        self._current_chunk_id = 0
        self._frame_index = 0
        self._t_host_output_sec = 0.0
        self._t_ref_sched_sec = 0.0
        self._t_ref_heard_sec = 0.0

        self._pending_seek_sec: float | None = None

    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        self.queue.load(chunks)

    def start(self) -> None:
        self._state = PlaybackState.PLAYING

    def hold(self) -> None:
        with self._lock:
            self._state = PlaybackState.HOLDING

    def resume(self) -> None:
        with self._lock:
            self._state = PlaybackState.PLAYING

    def seek(self, target_time_sec: float) -> None:
        with self._lock:
            self._pending_seek_sec = target_time_sec
            self._state = PlaybackState.SEEKING

    def get_status(self) -> PlaybackStatus:
        return PlaybackStatus(
            state=self._state,
            chunk_id=self._current_chunk_id,
            frame_index=self._frame_index,
            t_host_output_sec=self._t_host_output_sec,
            t_ref_sched_sec=self._t_ref_sched_sec,
            t_ref_heard_sec=self._t_ref_heard_sec,
        )

    def stop(self) -> None:
        self._state = PlaybackState.STOPPED

    def close(self) -> None:
        self._state = PlaybackState.STOPPED

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        raise NotImplementedError
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
### 文件: `shadowing_app/src/shadowing/types.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class PlaybackState(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    HOLDING = "holding"
    SEEKING = "seeking"
    FINISHED = "finished"


class ControlAction(str, Enum):
    NOOP = "noop"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"


class AsrEventType(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"
    ENDPOINT = "endpoint"


@dataclass(slots=True)
class AudioChunk:
    chunk_id: int
    sample_rate: int
    channels: int
    samples: "object"   # numpy.ndarray
    duration_sec: float
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
    tokens: List[RefToken]
    total_duration_sec: float


@dataclass(slots=True)
class LessonManifest:
    lesson_id: str
    lesson_text: str
    sample_rate_out: int
    chunk_paths: List[str]
    reference_map_path: str


@dataclass(slots=True)
class PlaybackStatus:
    state: PlaybackState
    chunk_id: int
    frame_index: int
    t_host_output_sec: float
    t_ref_sched_sec: float
    t_ref_heard_sec: float


@dataclass(slots=True)
class AsrEvent:
    event_type: AsrEventType
    text: str
    normalized_text: str
    pinyin_seq: List[str]
    emitted_at_sec: float


@dataclass(slots=True)
class AlignResult:
    committed_ref_idx: int
    candidate_ref_idx: int
    ref_time_sec: float
    confidence: float
    stable: bool
    matched_text: str = ""
    matched_pinyin: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ControlDecision:
    action: ControlAction
    reason: str
    target_time_sec: Optional[float] = None
    lead_sec: Optional[float] = None
```

