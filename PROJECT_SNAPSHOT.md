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

import platform

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.realtime.playback.sounddevice_player import SoundDevicePlayer
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.capture.soundcard_recorder import SoundCardRecorder
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.control.adaptive_controller import AdaptiveController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.runtime import ShadowingRuntime


def build_runtime(config: dict) -> ShadowingRuntime:
    repo = FileLessonRepository(config["lesson_base_dir"])

    player = SoundDevicePlayer(
        sample_rate=config["playback"]["sample_rate"],
        channels=1,
        device=config["playback"].get("device"),
        bluetooth_output_offset_sec=config["playback"].get(
            "bluetooth_output_offset_sec", 0.0
        ),
    )

    capture_cfg = config["capture"]
    use_soundcard_on_windows = False # bool(capture_cfg.get("prefer_soundcard_on_windows", True)    )

    if platform.system().lower() == "windows" and use_soundcard_on_windows:
        recorder = SoundCardRecorder(
            sample_rate_in=capture_cfg["device_sample_rate"],
            target_sample_rate=capture_cfg["target_sample_rate"],
            channels=1,
            device=capture_cfg.get("device"),
            block_frames=int(capture_cfg.get("block_frames", 1024)),
            include_loopback=bool(capture_cfg.get("include_loopback", False)),
        )
    else:
        recorder = SoundDeviceRecorder(
            sample_rate_in=capture_cfg["device_sample_rate"],
            target_sample_rate=capture_cfg["target_sample_rate"],
            channels=1,
            device=capture_cfg.get("device"),
        )

    asr = SherpaStreamingProvider(
        model_config=config["asr"],
        hotwords=config["asr"].get("hotwords", ""),
    )

    aligner = IncrementalAligner()

    control_cfg = config.get("control", {})
    controller = AdaptiveController(
        ducking_only=bool(control_cfg.get("ducking_only", False)),
        disable_seek=bool(control_cfg.get("disable_seek", False)),
        disable_hold=bool(control_cfg.get("disable_hold", False)),
    )

    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
    )

    if "runtime" in config and hasattr(orchestrator, "configure_runtime"):
        orchestrator.configure_runtime(config["runtime"])

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
from dataclasses import asdict
from pathlib import Path

import soundfile as sf

from shadowing.interfaces.repository import LessonRepository
from shadowing.types import AudioChunk, LessonManifest, RefToken, ReferenceMap


class FileLessonRepository(LessonRepository):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def save_manifest(self, manifest: LessonManifest) -> None:
        lesson_dir = self.base_dir / manifest.lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)

        path = lesson_dir / "lesson_manifest.json"
        path.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_manifest(self, lesson_id: str) -> LessonManifest:
        path = self.base_dir / lesson_id / "lesson_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return LessonManifest(**data)

    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str:
        lesson_dir = self.base_dir / lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)

        path = lesson_dir / "reference_map.json"
        path.write_text(
            json.dumps(asdict(ref_map), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)

    def load_reference_map(self, lesson_id: str) -> ReferenceMap:
        path = self.base_dir / lesson_id / "reference_map.json"
        data = json.loads(path.read_text(encoding="utf-8"))

        tokens = [RefToken(**token_data) for token_data in data["tokens"]]
        return ReferenceMap(
            lesson_id=data["lesson_id"],
            tokens=tokens,
            total_duration_sec=data["total_duration_sec"],
        )

    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]:
        manifest = self.load_manifest(lesson_id)

        chunks: list[AudioChunk] = []
        current_start_time = 0.0

        for idx, chunk_path_str in enumerate(manifest.chunk_paths):
            chunk_path = Path(chunk_path_str)

            if not chunk_path.is_absolute():
                chunk_path = (self.base_dir / lesson_id / chunk_path).resolve()

            samples, sr = sf.read(str(chunk_path), dtype="float32", always_2d=False)

            if samples.ndim == 1:
                channels = 1
                duration_sec = len(samples) / sr
            else:
                channels = samples.shape[1]
                duration_sec = samples.shape[0] / sr

            chunks.append(
                AudioChunk(
                    chunk_id=idx,
                    sample_rate=sr,
                    channels=channels,
                    samples=samples,
                    duration_sec=duration_sec,
                    start_time_sec=current_start_time,
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
from shadowing.types import AudioChunk, PlaybackStatus, PlayerCommand


class Player(ABC):
    @abstractmethod
    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def submit_command(self, command: PlayerCommand) -> None:
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

import base64
import re
from pathlib import Path

import httpx
from pypinyin import lazy_pinyin

from shadowing.interfaces.tts import TTSProvider
from shadowing.preprocess.reference_builder import ReferenceBuilder
from shadowing.types import LessonManifest, ReferenceMap


class ElevenLabsTTSProvider(TTSProvider):

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
        output_format: str = "mp3_44100_128",
        timeout_sec: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.timeout_sec = timeout_sec

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

        clauses = self._split_text(text)
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
        sentence_id = 0

        with httpx.Client(timeout=self.timeout_sec) as client:
            for clause_id, clause_text in enumerate(clauses):
                resp = self._request_tts_with_timestamps(client, clause_text)
                audio_bytes = base64.b64decode(resp["audio_base64"])

                chunk_file = chunks_dir / f"{clause_id:04d}.mp3"
                chunk_file.write_bytes(audio_bytes)
                chunk_paths.append(str(chunk_file))

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

                pinyins = []
                for ch in chars:
                    if ch.strip():
                        py_list = lazy_pinyin(ch)
                        pinyins.append(py_list[0] if py_list else ch)
                    else:
                        pinyins.append("")

                for ch, py, ts, te in zip(chars, pinyins, starts, ends, strict=True):
                    all_chars.append(ch)
                    all_pinyins.append(py)
                    all_starts.append(global_time_offset + float(ts))
                    all_ends.append(global_time_offset + float(te))
                    all_sentence_ids.append(sentence_id)
                    all_clause_ids.append(clause_id)

                if ends:
                    global_time_offset += float(ends[-1])

                if clause_text and clause_text[-1] in "。！？!?":
                    sentence_id += 1

        ref_map = self.reference_builder.build(
            lesson_id=lesson_id,
            chars=all_chars,
            pinyins=all_pinyins,
            starts=all_starts,
            ends=all_ends,
            sentence_ids=all_sentence_ids,
            clause_ids=all_clause_ids,
        )

        manifest = LessonManifest(
            lesson_id=lesson_id,
            lesson_text=text,
            sample_rate_out=44100,
            chunk_paths=chunk_paths,
            reference_map_path=str(output_path / "reference_map.json"),
        )

        return manifest, ref_map

    def _request_tts_with_timestamps(self, client: httpx.Client, text: str) -> dict:
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

    def _split_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []

        parts = re.split(r"(?<=[。！？!?])", text)
        parts = [p.strip() for p in parts if p.strip()]

        clauses: list[str] = []
        for part in parts:
            if len(part) <= 120:
                clauses.append(part)
                continue

            subparts = re.split(r"(?<=[，、；,;])", part)
            buf = ""
            for sp in subparts:
                sp = sp.strip()
                if not sp:
                    continue
                if len(buf) + len(sp) <= 120:
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
### 文件: `shadowing_app/src/shadowing/preprocess/reference_builder.py`

```python
from __future__ import annotations

from shadowing.types import ReferenceMap, RefToken


class ReferenceBuilder:

    _DROP_CHARS = set(
        [
            " ", "\t", "\n", "\r", "\u3000",
            "，", "。", "！", "？", "；", "：", "、",
            ",", ".", "!", "?", ";", ":", "\"", "'", "“", "”", "‘", "’",
            "（", "）", "(", ")", "[", "]", "【", "】", "<", ">", "《", "》",
            "-", "—", "…", "|", "/", "\\",
        ]
    )

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

        filtered_idx = 0
        for ch, py, ts, te, sid, cid in zip(
            chars, pinyins, starts, ends, sentence_ids, clause_ids, strict=True
        ):
            if not ch:
                continue
            if ch in self._DROP_CHARS:
                continue
            if ch.strip() == "":
                continue

            tokens.append(
                RefToken(
                    idx=filtered_idx,
                    char=ch,
                    pinyin=py,
                    t_start=ts,
                    t_end=te,
                    sentence_id=sid,
                    clause_id=cid,
                )
            )
            filtered_idx += 1

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

from dataclasses import dataclass
from typing import Sequence

from shadowing.interfaces.aligner import Aligner
from shadowing.types import AsrEvent, AsrEventType, AlignResult


@dataclass
class _RefTokenView:
    idx: int
    char: str
    pinyin: str
    t0: float


class IncrementalAligner(Aligner):

    def __init__(
        self,
        search_backoff_tokens: int = 12,
        search_ahead_tokens: int = 48,
        stable_min_advance: int = 2,
        fuzzy_missing_tolerance: int = 2,
        replay_head_tokens: int = 48,
        replay_trigger_max_chars: int = 12,
        replay_min_prefix_chars: int = 2,
        replay_min_committed_idx: int = 8,
        replay_lockin_min_run: int = 3,
        replay_lockin_confidence: float = 0.90,
    ) -> None:
        self.search_backoff_tokens = int(search_backoff_tokens)
        self.search_ahead_tokens = int(search_ahead_tokens)
        self.stable_min_advance = int(stable_min_advance)
        self.fuzzy_missing_tolerance = int(fuzzy_missing_tolerance)

        self.replay_head_tokens = int(replay_head_tokens)
        self.replay_trigger_max_chars = int(replay_trigger_max_chars)
        self.replay_min_prefix_chars = int(replay_min_prefix_chars)

        self.replay_min_committed_idx = int(replay_min_committed_idx)
        self.replay_lockin_min_run = int(replay_lockin_min_run)
        self.replay_lockin_confidence = float(replay_lockin_confidence)

        self.ref_map = None
        self.ref_tokens: list[_RefTokenView] = []

        self._committed_idx = 0
        self._candidate_idx = 0
        self._last_candidate_idx = 0
        self._last_candidate_run = 0

        self._head_norm = ""

        self._replay_active = False
        self._replay_run_len = 0
        self._replay_last_candidate = -1

    def reset(self, ref_map) -> None:
        self.ref_map = ref_map
        self.ref_tokens = []

        for i, tok in enumerate(ref_map.tokens):
            self.ref_tokens.append(
                _RefTokenView(
                    idx=i,
                    char=str(getattr(tok, "char", "")),
                    pinyin=str(getattr(tok, "pinyin", "")),
                    t0=self._extract_token_time(tok, fallback_index=i),
                )
            )

        self._committed_idx = 0
        self._candidate_idx = 0
        self._last_candidate_idx = 0
        self._last_candidate_run = 0

        self._replay_active = False
        self._replay_run_len = 0
        self._replay_last_candidate = -1

        self._head_norm = "".join(t.char for t in self.ref_tokens[: self.replay_head_tokens])

    def update(self, event: AsrEvent) -> AlignResult | None:
        if self.ref_map is None or not self.ref_tokens:
            return None

        if event.event_type not in (AsrEventType.PARTIAL, AsrEventType.FINAL):
            return None

        norm = event.normalized_text or ""
        py = event.pinyin_seq or []

        if not norm and not py:
            return None

        cand_idx, confidence, matched_text, replay_mode = self._locate_candidate(norm, py)

        stable = False

        if event.event_type == AsrEventType.FINAL:
            self._clear_replay_if_needed(finalizing=True)
            if cand_idx >= self._committed_idx:
                self._committed_idx = cand_idx
                stable = True

        else:
            if replay_mode and cand_idx < self._committed_idx:
                self._update_replay_state(cand_idx, confidence)

                if self._should_lockin_replay(cand_idx, confidence):
                    self._replay_active = True
                    self._committed_idx = cand_idx
                    stable = True
            else:
                if cand_idx >= self._committed_idx:
                    self._clear_replay_if_needed(finalizing=False)

                if cand_idx > self._last_candidate_idx:
                    self._last_candidate_run += 1
                elif cand_idx == self._last_candidate_idx:
                    self._last_candidate_run += 1
                else:
                    self._last_candidate_run = 0

                if cand_idx >= self._committed_idx:
                    if confidence >= 0.70 and (cand_idx - self._committed_idx) >= self.stable_min_advance:
                        self._committed_idx = cand_idx
                        stable = True
                    elif confidence >= 0.90 and cand_idx > self._committed_idx:
                        self._committed_idx = cand_idx
                        stable = True
                    elif self._last_candidate_run >= 2 and confidence >= 0.80 and cand_idx >= self._committed_idx:
                        self._committed_idx = cand_idx
                        stable = True

        self._candidate_idx = cand_idx
        self._last_candidate_idx = cand_idx

        ref_time_sec = self._token_time(cand_idx)

        return AlignResult(
            committed_ref_idx=self._committed_idx,
            candidate_ref_idx=self._candidate_idx,
            ref_time_sec=ref_time_sec,
            confidence=confidence,
            stable=stable,
            matched_text=matched_text,
        )

    def _locate_candidate(self, norm: str, py: Sequence[str]) -> tuple[int, float, str, bool]:
        replay_mode = self._should_replay_search(norm, py)

        if replay_mode:
            start = 0
            end = min(len(self.ref_tokens) - 1, self.replay_head_tokens)
        else:
            start = max(0, self._committed_idx - self.search_backoff_tokens)
            end = min(len(self.ref_tokens) - 1, self._committed_idx + self.search_ahead_tokens)

        best_idx = self._committed_idx
        best_score = -1.0
        best_text = ""

        for i in range(start, end + 1):
            score, matched = self._score_at(i, norm, py)
            if score > best_score:
                best_score = score
                best_idx = i
                best_text = matched

        conf = max(0.0, min(1.0, best_score))
        return best_idx, conf, best_text, replay_mode

    def _should_replay_search(self, norm: str, py: Sequence[str]) -> bool:
        if not norm:
            return False

        if self._committed_idx < self.replay_min_committed_idx:
            return False

        if len(norm) > self.replay_trigger_max_chars:
            return False

        head_prefix = self._head_norm[: max(self.replay_min_prefix_chars, min(len(norm), 8))]
        if head_prefix and norm.startswith(head_prefix[: min(len(head_prefix), len(norm))]):
            return True

        score = self._ordered_subsequence_score(norm, self._head_norm[: max(len(norm) + 4, 8)])
        return score >= 0.75

    def _update_replay_state(self, cand_idx: int, confidence: float) -> None:
        if cand_idx < 0:
            self._replay_run_len = 0
            self._replay_last_candidate = -1
            return

        if confidence < self.replay_lockin_confidence:
            self._replay_run_len = 0
            self._replay_last_candidate = cand_idx
            return

        if self._replay_last_candidate < 0:
            self._replay_run_len = 1
        elif cand_idx > self._replay_last_candidate:
            self._replay_run_len += 1
        elif cand_idx == self._replay_last_candidate:
            self._replay_run_len += 1
        else:
            self._replay_run_len = 1

        self._replay_last_candidate = cand_idx

    def _should_lockin_replay(self, cand_idx: int, confidence: float) -> bool:
        if cand_idx < 0:
            return False
        if cand_idx >= self._committed_idx:
            return False
        if confidence < self.replay_lockin_confidence:
            return False
        if self._replay_run_len < self.replay_lockin_min_run:
            return False
        return True

    def _clear_replay_if_needed(self, finalizing: bool) -> None:
        self._replay_active = False
        self._replay_run_len = 0
        self._replay_last_candidate = -1
        if finalizing:
            self._last_candidate_run = 0

    def _score_at(self, end_idx: int, norm: str, py: Sequence[str]) -> tuple[float, str]:
        if end_idx < 0 or end_idx >= len(self.ref_tokens):
            return 0.0, ""

        norm_len = len(norm)
        py_len = len(py)

        ref_window_len = max(norm_len, py_len, 1) + self.fuzzy_missing_tolerance
        start_idx = max(0, end_idx - ref_window_len + 1)
        ref_slice = self.ref_tokens[start_idx : end_idx + 1]

        ref_chars = "".join(tok.char for tok in ref_slice)
        ref_py = [tok.pinyin for tok in ref_slice]

        char_score, matched_chars = self._char_fuzzy_score(norm, ref_chars)
        py_score = self._pinyin_fuzzy_score(py, ref_py)

        if norm and py:
            score = 0.75 * char_score + 0.25 * py_score
        elif norm:
            score = char_score
        else:
            score = py_score

        return score, matched_chars

    def _char_fuzzy_score(self, user_norm: str, ref_chars: str) -> tuple[float, str]:
        if not user_norm or not ref_chars:
            return 0.0, ""

        best_score = 0.0
        best_match = ""

        min_len = max(1, len(user_norm) - self.fuzzy_missing_tolerance)
        max_len = min(len(ref_chars), len(user_norm) + self.fuzzy_missing_tolerance)

        for L in range(min_len, max_len + 1):
            cand = ref_chars[-L:]
            score = self._ordered_subsequence_score(user_norm, cand)
            if score > best_score:
                best_score = score
                best_match = cand

        return best_score, best_match

    def _pinyin_fuzzy_score(self, user_py: Sequence[str], ref_py: Sequence[str]) -> float:
        if not user_py or not ref_py:
            return 0.0

        min_len = max(1, len(user_py) - self.fuzzy_missing_tolerance)
        max_len = min(len(ref_py), len(user_py) + self.fuzzy_missing_tolerance)

        best_score = 0.0
        for L in range(min_len, max_len + 1):
            cand = ref_py[-L:]
            score = self._ordered_subsequence_score(list(user_py), list(cand))
            if score > best_score:
                best_score = score

        return best_score

    def _ordered_subsequence_score(self, a, b) -> float:
        if not a or not b:
            return 0.0

        i = 0
        j = 0
        matched = 0

        while i < len(a) and j < len(b):
            if a[i] == b[j]:
                matched += 1
                i += 1
                j += 1
            else:
                j += 1

        return matched / max(1, len(a))

    def _token_time(self, idx: int) -> float:
        idx = max(0, min(idx, len(self.ref_tokens) - 1))
        return self.ref_tokens[idx].t0

    def _extract_token_time(self, tok, fallback_index: int = 0) -> float:
        for name in ("t0", "start_sec", "time_sec", "t_ref_sec", "start", "ts"):
            if hasattr(tok, name):
                try:
                    return float(getattr(tok, name))
                except Exception:
                    pass

        return float(fallback_index) * 0.08
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/scoring.py`

```python
from __future__ import annotations

from rapidfuzz import fuzz


class AlignmentScorer:

    def score_token_pair(
        self,
        ref_char: str,
        ref_py: str,
        hyp_char: str,
        hyp_py: str,
    ) -> float:
        if ref_char == hyp_char:
            return 3.0

        if ref_py == hyp_py:
            return 2.0

        py_sim = fuzz.ratio(ref_py, hyp_py)
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

from shadowing.types import ReferenceMap, RefToken


class WindowSelector:
    def __init__(self, look_back: int = 3, look_ahead: int = 18) -> None:
        self.look_back = look_back
        self.look_ahead = look_ahead

    def select(self, ref_map: ReferenceMap, committed_idx: int) -> tuple[list[RefToken], int, int]:
        start = max(0, committed_idx - self.look_back)
        end = min(len(ref_map.tokens), committed_idx + self.look_ahead)
        return ref_map.tokens[start:end], start, end
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/fake_asr_provider.py`

```python
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from shadowing.interfaces.asr import ASRProvider
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.types import AsrEvent, AsrEventType


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


class FakeASRProvider(ASRProvider):

    def __init__(self, config: FakeAsrConfig) -> None:
        self.config = config
        self.normalizer = TextNormalizer()

        self._running = False
        self._start_at = 0.0

        self._script_index = 0
        self._last_emit_at = 0.0

        self._bytes_received = 0
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
        pause_at_step: int | None = None,
        pause_extra_sec: float = 0.0,
        jump_to_char: int | None = None,
        jump_at_step: int | None = None,
    ) -> "FakeASRProvider":
        clean = reference_text.strip()
        steps: list[FakeAsrStep] = []

        if not clean:
            return cls(FakeAsrConfig(scripted_steps=[]))

        t = lag_sec
        cursor = 0
        step_idx = 0

        while cursor < len(clean):
            if jump_at_step is not None and jump_to_char is not None and step_idx == jump_at_step:
                cursor = max(0, min(jump_to_char, len(clean)))

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

            if pause_at_step is not None and step_idx == pause_at_step:
                t += pause_extra_sec

            step_idx += 1

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
        self._last_progress_text = ""
        self._last_final_text = ""

    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running:
            return
        self._bytes_received += len(pcm_bytes)

    def poll_events(self) -> list[AsrEvent]:
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

    def _poll_scripted(self) -> list[AsrEvent]:
        now = time.monotonic()
        elapsed = now - self._start_at
        events: list[AsrEvent] = []

        while self._script_index < len(self.config.scripted_steps):
            step = self.config.scripted_steps[self._script_index]
            if elapsed < step.offset_sec:
                break

            normalized = self.normalizer.normalize_text(step.text)
            pinyin_seq = self.normalizer.to_pinyin_seq(step.text)

            if normalized:
                events.append(
                    AsrEvent(
                        event_type=step.event_type,
                        text=step.text,
                        normalized_text=normalized,
                        pinyin_seq=pinyin_seq,
                        emitted_at_sec=now,
                    )
                )

            self._script_index += 1

        return events

    def _poll_progressive(self) -> list[AsrEvent]:
        now = time.monotonic()
        events: list[AsrEvent] = []

        if (now - self._last_emit_at) < self.config.emit_partial_interval_sec:
            return events

        total_audio_sec = self._bytes_to_seconds(self._bytes_received)
        n_chars = int(math.floor(total_audio_sec * self.config.chars_per_sec))
        n_chars = max(0, min(n_chars, len(self.config.reference_text)))

        current_text = self.config.reference_text[:n_chars]

        if current_text and current_text != self._last_progress_text:
            normalized = self.normalizer.normalize_text(current_text)
            pinyin_seq = self.normalizer.to_pinyin_seq(current_text)

            if normalized:
                events.append(
                    AsrEvent(
                        event_type=AsrEventType.PARTIAL,
                        text=current_text,
                        normalized_text=normalized,
                        pinyin_seq=pinyin_seq,
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
            final_text = self.config.reference_text
            normalized = self.normalizer.normalize_text(final_text)
            pinyin_seq = self.normalizer.to_pinyin_seq(final_text)

            if normalized:
                events.append(
                    AsrEvent(
                        event_type=AsrEventType.FINAL,
                        text=final_text,
                        normalized_text=normalized,
                        pinyin_seq=pinyin_seq,
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
        if bytes_per_sec <= 0:
            return 0.0
        return n_bytes / bytes_per_sec
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/normalizer.py`

```python
from __future__ import annotations

import re

from pypinyin import lazy_pinyin


class TextNormalizer:
    _drop_pattern = re.compile(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+")

    def normalize_text(self, text: str) -> str:
        if not text:
            return ""

        text = text.strip()
        text = text.replace("\u3000", " ")
        text = self._drop_pattern.sub("", text)
        return text

    def to_pinyin_seq(self, text: str) -> list[str]:
        norm = self.normalize_text(text)
        if not norm:
            return []
        return lazy_pinyin(norm)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/sherpa_streaming_provider.py`

```python
from __future__ import annotations

import time
from typing import Any

import numpy as np

from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEvent, AsrEventType
from shadowing.realtime.asr.normalizer import TextNormalizer


class SherpaStreamingProvider(ASRProvider):

    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
        sample_rate: int = 16000,
        emit_partial_interval_sec: float = 0.08,
        enable_endpoint: bool = True,
        debug_feed: bool = True,
        debug_feed_every_n_chunks: int = 20,
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.reference_text = model_config.get("reference_text", "")
        self.sample_rate = sample_rate
        self.emit_partial_interval_sec = emit_partial_interval_sec
        self.enable_endpoint = enable_endpoint

        self.debug_feed = bool(debug_feed)
        self.debug_feed_every_n_chunks = max(1, int(debug_feed_every_n_chunks))

        self.normalizer = TextNormalizer()

        self._recognizer: Any | None = None
        self._stream: Any | None = None
        self._running = False

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

        self._feed_counter = 0
        self._decode_counter = 0

        self._last_partial_normalized = ""
        self._last_emitted_normalized = ""

        self._reference_norm = ""
        self._anchor_candidates: list[str] = []

        self._last_trim_source_norm = ""
        self._last_trim_tail_norm = ""
        self._last_trim_kind = ""

        self._suffix_overlap_max = int(self.model_config.get("suffix_overlap_max", 24))
        self._tail_trim_min_len = int(self.model_config.get("tail_trim_min_len", 2))
        self._anchor_min_len = int(self.model_config.get("anchor_min_len", 3))
        self._anchor_max_len = int(self.model_config.get("anchor_max_len", 6))

    def start(self) -> None:
        self._recognizer = self._build_recognizer()
        self._stream = self._recognizer.create_stream()
        self._running = True

        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0

        self._feed_counter = 0
        self._decode_counter = 0

        self._last_partial_normalized = ""
        self._last_emitted_normalized = ""

        self._last_trim_source_norm = ""
        self._last_trim_tail_norm = ""
        self._last_trim_kind = ""

        self._build_reference_anchors()

    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running or self._recognizer is None or self._stream is None:
            return

        if not pcm_bytes:
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
                f"[ASR-FEED] chunks={self._feed_counter} "
                f"samples={audio_f32.size} abs_mean={abs_mean:.5f} peak={peak:.5f}"
            )

        self._stream.accept_waveform(self.sample_rate, audio_f32)

        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1

        if self.debug_feed and self._feed_counter % self.debug_feed_every_n_chunks == 0:
            print(f"[ASR-FEED] decode_counter={self._decode_counter}")

    def poll_events(self) -> list[AsrEvent]:
        if not self._running or self._recognizer is None or self._stream is None:
            return []

        now = time.monotonic()
        events: list[AsrEvent] = []

        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1

        raw_partial_text = self._get_partial_text()
        processed_text = self._postprocess_partial_text(raw_partial_text) if raw_partial_text else ""

        if (
            processed_text
            and processed_text != self._last_partial_text
            and (now - self._last_emit_at) >= self.emit_partial_interval_sec
        ):
            normalized = self.normalizer.normalize_text(processed_text)
            pinyin_seq = self.normalizer.to_pinyin_seq(processed_text)

            if normalized:
                events.append(
                    AsrEvent(
                        event_type=AsrEventType.PARTIAL,
                        text=processed_text,
                        normalized_text=normalized,
                        pinyin_seq=pinyin_seq,
                        emitted_at_sec=now,
                    )
                )
                self._last_partial_text = processed_text
                self._last_partial_normalized = normalized
                self._last_emit_at = now

        if self.enable_endpoint and self._is_endpoint():
            final_text = self._get_final_text()
            if final_text and final_text != self._last_final_text:
                normalized = self.normalizer.normalize_text(final_text)
                pinyin_seq = self.normalizer.to_pinyin_seq(final_text)

                if normalized:
                    events.append(
                        AsrEvent(
                            event_type=AsrEventType.FINAL,
                            text=final_text,
                            normalized_text=normalized,
                            pinyin_seq=pinyin_seq,
                            emitted_at_sec=now,
                        )
                    )
                    self._last_final_text = final_text

            self._reset_stream_state_only()

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

        self._last_partial_normalized = ""
        self._last_emitted_normalized = ""

        self._last_trim_source_norm = ""
        self._last_trim_tail_norm = ""
        self._last_trim_kind = ""

        self._build_reference_anchors()

    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None

    def _build_reference_anchors(self) -> None:
        self._reference_norm = self.normalizer.normalize_text(self.reference_text or "")
        self._anchor_candidates = []

        if not self._reference_norm:
            return

        max_len = min(self._anchor_max_len, len(self._reference_norm))
        min_len = min(self._anchor_min_len, max_len)

        for n in range(max_len, min_len - 1, -1):
            anchor = self._reference_norm[:n]
            if anchor and anchor not in self._anchor_candidates:
                self._anchor_candidates.append(anchor)

    def _postprocess_partial_text(self, raw_partial_text: str) -> str:
        current_norm = self.normalizer.normalize_text(raw_partial_text)
        if not current_norm:
            return raw_partial_text

        prev_emit_norm = self._last_emitted_normalized
        prev_partial_norm = self._last_partial_normalized

        if current_norm == prev_partial_norm:
            return raw_partial_text

        forced_tail = self._extract_forced_last_anchor_tail(current_norm)
        if forced_tail:
            return self._commit_trim(
                kind="forced_anchor_tail",
                source_norm=current_norm,
                tail_norm=forced_tail,
                prev_emit_norm=prev_emit_norm,
            )

        if prev_emit_norm and current_norm.startswith(prev_emit_norm):
            appended = current_norm[len(prev_emit_norm):]
            self._last_emitted_normalized = current_norm
            return current_norm if appended else raw_partial_text

        overlap = self._max_suffix_prefix_overlap(prev_emit_norm, current_norm)
        if overlap > 0:
            new_tail = current_norm[overlap:]
            if len(new_tail) >= self._tail_trim_min_len:
                return self._commit_trim(
                    kind="overlap",
                    source_norm=current_norm,
                    tail_norm=new_tail,
                    prev_emit_norm=prev_emit_norm,
                    extra=f"overlap={overlap}",
                )

        self._last_emitted_normalized = current_norm
        return current_norm

    def _commit_trim(
        self,
        kind: str,
        source_norm: str,
        tail_norm: str,
        prev_emit_norm: str,
        extra: str = "",
    ) -> str:
        if (
            source_norm == self._last_trim_source_norm
            and tail_norm == self._last_trim_tail_norm
            and kind == self._last_trim_kind
        ):
            self._last_emitted_normalized = tail_norm
            return tail_norm

        self._last_trim_source_norm = source_norm
        self._last_trim_tail_norm = tail_norm
        self._last_trim_kind = kind
        self._last_emitted_normalized = tail_norm

        msg = (
            f"[ASR-TRIM] {kind}, "
            f"prev_emit_norm={prev_emit_norm!r}, "
            f"current_norm={source_norm!r}, "
            f"tail={tail_norm!r}"
        )
        if extra:
            msg = f"[ASR-TRIM] {extra}, " + msg[len("[ASR-TRIM] ") :]
        print(msg)
        return tail_norm

    def _extract_forced_last_anchor_tail(self, current_norm: str) -> str:
        if not current_norm or not self._anchor_candidates:
            return ""

        best_tail = ""
        best_pos = -1

        for anchor in self._anchor_candidates:
            first_pos = current_norm.find(anchor)
            last_pos = current_norm.rfind(anchor)
            if first_pos == -1 or last_pos == -1:
                continue
            if last_pos <= first_pos:
                continue

            tail = current_norm[last_pos:]
            if len(tail) < self._tail_trim_min_len:
                continue

            if last_pos > best_pos:
                best_pos = last_pos
                best_tail = tail

        return best_tail

    def _max_suffix_prefix_overlap(self, prev_norm: str, current_norm: str) -> int:
        if not prev_norm or not current_norm:
            return 0

        max_len = min(len(prev_norm), len(current_norm), self._suffix_overlap_max)
        for k in range(max_len, 0, -1):
            if prev_norm[-k:] == current_norm[:k]:
                return k
        return 0

    def _get_partial_text(self) -> str:
        result = self._recognizer.get_result(self._stream)

        if isinstance(result, str):
            return result.strip()

        if hasattr(result, "text"):
            return (result.text or "").strip()

        if isinstance(result, dict):
            return str(result.get("text", "")).strip()

        return ""

    def _get_final_text(self) -> str:
        result = self._recognizer.get_result(self._stream)

        if isinstance(result, str):
            return result.strip()

        if hasattr(result, "text"):
            return (result.text or "").strip()

        if isinstance(result, dict):
            return str(result.get("text", "")).strip()

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

    def _build_recognizer(self):
        import sherpa_onnx

        cfg = self.model_config

        tokens = cfg.get("tokens", "")
        encoder = cfg.get("encoder", "")
        decoder = cfg.get("decoder", "")
        joiner = cfg.get("joiner", "")

        missing = []
        if not tokens:
            missing.append("tokens")
        if not encoder:
            missing.append("encoder")
        if not decoder:
            missing.append("decoder")
        if not joiner:
            missing.append("joiner")

        if missing:
            raise ValueError(
                "Missing sherpa model paths in config: "
                + ", ".join(missing)
                + ". Please set SHERPA_TOKENS / SHERPA_ENCODER / SHERPA_DECODER / SHERPA_JOINER."
            )

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
            pass

        try:
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **endpoint_kwargs,
            )
        except TypeError:
            pass

        try:
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
            )
        except TypeError as e:
            raise RuntimeError(
                "Failed to build sherpa recognizer. "
                "Your installed sherpa-onnx version uses a different "
                "OnlineRecognizer.from_transducer() signature. "
                "Please inspect the local sherpa_onnx Python API."
            ) from e
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

        hostapi_idx = int(dev["hostapi"])
        hostapi_name = hostapis[hostapi_idx]["name"]

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
    devices = list_input_devices()
    if not devices:
        print("No input devices found.")
        return

    print("Available input devices:")
    for d in devices:
        print(
            f"[{d.index}] {d.name} | "
            f"hostapi={d.hostapi_name} | "
            f"max_in={d.max_input_channels} | "
            f"default_sr={d.default_samplerate}"
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
        keyword = preferred_name_substring.lower()
        for d in devices:
            if keyword in d.name.lower():
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
    preferred_rates: list[int] | None = None,
    channels: int = 1,
    dtype: str = "float32",
) -> dict[str, Any] | None:
    if preferred_rates is None:
        preferred_rates = [48000, 44100, 16000]

    device = choose_input_device(preferred_index=preferred_device)
    if device is None:
        return None

    for sr in preferred_rates:
        if check_input_settings(device=device, samplerate=sr, channels=channels, dtype=dtype):
            return {
                "device": device,
                "samplerate": sr,
                "channels": channels,
                "dtype": dtype,
            }

    try:
        dev = sd.query_devices(device)
        default_sr = int(float(dev["default_samplerate"]))
        if check_input_settings(device=device, samplerate=default_sr, channels=channels, dtype=dtype):
            return {
                "device": device,
                "samplerate": default_sr,
                "channels": channels,
                "dtype": dtype,
            }
    except Exception:
        pass

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
        self.src_rate = src_rate
        self.dst_rate = dst_rate

        g = gcd(src_rate, dst_rate)
        self.up = dst_rate // g
        self.down = src_rate // g

    def float_to_pcm16_bytes(self, audio: np.ndarray) -> bytes:
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio with shape (n,), got {audio.shape}")

        clipped = np.clip(audio, -1.0, 1.0)
        pcm16 = (clipped * 32767.0).astype(np.int16)
        return pcm16.tobytes()

    def process_float_mono(self, audio: np.ndarray) -> bytes:
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio with shape (n,), got {audio.shape}")

        if self.src_rate == self.dst_rate:
            return self.float_to_pcm16_bytes(audio)

        y = resample_poly(audio, self.up, self.down)
        y = y.astype(np.float32, copy=False)
        return self.float_to_pcm16_bytes(y)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/soundcard_recorder.py`

```python
from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np
import pythoncom
import soundcard as sc

from shadowing.interfaces.recorder import Recorder


class SoundCardRecorder(Recorder):

    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        block_frames: int = 1024,
        include_loopback: bool = False,
        debug_level_meter: bool = True,
        debug_level_every_n_blocks: int = 20,
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.block_frames = int(block_frames)
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
                    _ = rec.record(numframes=min(self.block_frames, 256))

                self._opened_samplerate = sr
                self._opened_channels = ch
                print(
                    f"[REC-SC] opened mic={self._mic.name!r} "
                    f"samplerate={sr} channels={ch}"
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

                    if self.debug_level_meter:
                        self._debug_counter += 1
                        if self._debug_counter % self.debug_level_every_n_blocks == 0:
                            rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                            peak = float(np.max(np.abs(mono))) if mono.size else 0.0
                            print(f"[REC-SC] rms={rms:.5f} peak={peak:.5f}")

                    src_sr = self._opened_samplerate
                    if src_sr != self.target_sample_rate:
                        mono = self._resample_linear(mono, src_sr, self.target_sample_rate)

                    pcm16 = np.clip(mono, -1.0, 1.0)
                    pcm16 = (pcm16 * 32767.0).astype(np.int16)

                    self._callback(pcm16.tobytes())
        except Exception as e:
            print(f"[REC-SC] capture loop stopped due to error: {e}")
        finally:
            pythoncom.CoUninitialize()
            self._running = False

    def _build_open_candidates(self) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int]] = []

        candidate_srs: list[int] = []
        for sr in [self.sample_rate_in, 48000, 44100]:
            if sr > 0 and sr not in candidate_srs:
                candidate_srs.append(sr)

        candidate_channels: list[int] = []
        for ch in [1, 2, self.channels]:
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
                print(f"[REC-SC] using microphone index={device}: {mics[device].name!r}")
                return mics[device]
            raise ValueError(f"Microphone index out of range for soundcard: {device}")

        key = str(device).strip().lower()
        for mic in mics:
            if key in mic.name.lower():
                print(f"[REC-SC] matched microphone {device!r} -> {mic.name!r}")
                return mic

        raise ValueError(f"No matching microphone found for {device!r}")

    @staticmethod
    def _resample_linear(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr or x.size == 0:
            return x.astype(np.float32, copy=False)

        duration = x.shape[0] / float(src_sr)
        dst_n = max(1, int(round(duration * dst_sr)))

        src_idx = np.linspace(0, x.shape[0] - 1, num=x.shape[0], dtype=np.float32)
        dst_idx = np.linspace(0, x.shape[0] - 1, num=dst_n, dtype=np.float32)

        y = np.interp(dst_idx, src_idx, x).astype(np.float32)
        return y
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/sounddevice_recorder.py`

```python
from __future__ import annotations

import threading
import time
from typing import Callable, Any

import numpy as np
import sounddevice as sd

from shadowing.interfaces.recorder import Recorder


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
        probe_duration_sec: float = 0.45,
        probe_rms_threshold: float = 1e-4,
        probe_peak_threshold: float = 8e-4,
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.dtype = dtype
        self.blocksize = blocksize
        self.latency = latency

        self.probe_duration_sec = float(probe_duration_sec)
        self.probe_rms_threshold = float(probe_rms_threshold)
        self.probe_peak_threshold = float(probe_peak_threshold)

        self._stream: sd.InputStream | None = None
        self._callback: Callable[[bytes], None] | None = None

        self._opened_channels: int | None = None
        self._opened_samplerate: int | None = None
        self._resolved_input_device: int | None = None

    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._stream is not None:
            return

        self._callback = on_audio_frame

        input_device_index = self._resolve_input_device(self.device)
        self._resolved_input_device = input_device_index

        dev_info = sd.query_devices(input_device_index, "input")
        max_in = int(dev_info["max_input_channels"])
        default_sr = int(float(dev_info["default_samplerate"]))
        device_name = str(dev_info["name"])

        candidate_sample_rates: list[int] = []
        for sr in [self.sample_rate_in, default_sr, 48000, 44100]:
            if sr > 0 and sr not in candidate_sample_rates:
                candidate_sample_rates.append(sr)

        candidate_channels: list[int] = []
        for ch in [2, 1, max_in, self.channels]:
            if ch > 0 and ch <= max_in and ch not in candidate_channels:
                candidate_channels.append(ch)

        last_error: Exception | None = None
        best_silent_candidate: tuple[int, int, float, float] | None = None

        for sr in candidate_sample_rates:
            for ch in candidate_channels:
                try:
                    print(
                        f"[REC] probing raw_device={input_device_index} "
                        f"name={device_name!r} samplerate={sr} channels={ch} dtype={self.dtype}"
                    )

                    ok, rms, peak = self._probe_candidate(
                        device=input_device_index,
                        samplerate=sr,
                        channels=ch,
                    )

                    print(
                        f"[REC] probe_result raw_device={input_device_index} "
                        f"samplerate={sr} channels={ch} "
                        f"rms={rms:.6f} peak={peak:.6f} ok={ok}"
                    )

                    if ok:
                        self._stream = sd.InputStream(
                            samplerate=sr,
                            blocksize=self.blocksize,
                            device=input_device_index,
                            channels=ch,
                            dtype=self.dtype,
                            latency=self.latency,
                            callback=self._audio_callback,
                        )
                        self._stream.start()

                        self._opened_channels = ch
                        self._opened_samplerate = sr

                        print(
                            f"[REC] opened raw_device={input_device_index} "
                            f"name={device_name!r} samplerate={sr} channels={ch}"
                        )
                        return

                    if best_silent_candidate is None or (peak > best_silent_candidate[3]):
                        best_silent_candidate = (sr, ch, rms, peak)

                except Exception as e:
                    last_error = e
                    self._stream = None
                    print(
                        f"[REC] probe/open failed raw_device={input_device_index} "
                        f"samplerate={sr} channels={ch} -> {e}"
                    )

        extra = ""
        if best_silent_candidate is not None:
            sr, ch, rms, peak = best_silent_candidate
            extra = (
                f" Best silent candidate: samplerate={sr}, channels={ch}, "
                f"rms={rms:.6f}, peak={peak:.6f}."
            )

        raise RuntimeError(
            "Failed to find a recording config with real input signal. "
            f"raw_device={input_device_index}, name={device_name!r}, "
            f"max_input_channels={max_in}, default_samplerate={default_sr}. "
            f"Last error: {last_error}.{extra}"
        )

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

        audio = np.asarray(indata)

        if audio.ndim == 1:
            audio = audio[:, None]

        if audio.shape[1] > 1:
            audio = np.mean(audio, axis=1, keepdims=True)

        mono = np.squeeze(audio, axis=1).astype(np.float32, copy=False)

        src_sr = self._opened_samplerate or self.sample_rate_in
        if src_sr != self.target_sample_rate:
            mono = self._resample_linear(mono, src_sr, self.target_sample_rate)

        pcm16 = np.clip(mono, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16)

        self._callback(pcm16.tobytes())

    def _probe_candidate(
        self,
        device: int,
        samplerate: int,
        channels: int,
    ) -> tuple[bool, float, float]:
        captured: list[np.ndarray] = []
        done = threading.Event()

        def _probe_callback(indata, frames, time_info, status) -> None:
            if status:
                print(f"[REC] probe callback status: {status}")

            x = np.asarray(indata, dtype=np.float32)

            if x.ndim == 1:
                x = x[:, None]

            if x.shape[1] > 1:
                x = np.mean(x, axis=1, keepdims=True)

            mono = np.squeeze(x, axis=1).astype(np.float32, copy=False)
            captured.append(mono.copy())

            total_samples = sum(arr.size for arr in captured)
            if total_samples >= int(samplerate * self.probe_duration_sec):
                done.set()

        stream: sd.InputStream | None = None
        try:
            stream = sd.InputStream(
                samplerate=samplerate,
                blocksize=self.blocksize,
                device=device,
                channels=channels,
                dtype=self.dtype,
                latency=self.latency,
                callback=_probe_callback,
            )
            stream.start()

            done.wait(timeout=max(0.8, self.probe_duration_sec + 0.4))
        finally:
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()

        if not captured:
            return False, 0.0, 0.0

        mono = np.concatenate(captured, axis=0)
        if mono.size == 0:
            return False, 0.0, 0.0

        rms = float(np.sqrt(np.mean(np.square(mono))))
        peak = float(np.max(np.abs(mono)))

        ok = (rms >= self.probe_rms_threshold) or (peak >= self.probe_peak_threshold)
        return ok, rms, peak

    def _resolve_input_device(self, device: int | str | None) -> int:
        all_devices = sd.query_devices()
        input_devices = [
            (idx, dev)
            for idx, dev in enumerate(all_devices)
            if int(dev["max_input_channels"]) > 0
        ]

        self._print_input_device_map(input_devices)

        if device is None:
            default_input, _default_output = sd.default.device
            if default_input is None or default_input < 0:
                raise RuntimeError("No default input device available.")
            dev = all_devices[default_input]
            if int(dev["max_input_channels"]) <= 0:
                raise RuntimeError(f"Default input device is not valid: {dev}")
            print(f"[REC] using default input raw_device={default_input} name={dev['name']!r}")
            return int(default_input)

        if isinstance(device, int):
            if 0 <= device < len(all_devices):
                dev = all_devices[device]
                if int(dev["max_input_channels"]) > 0:
                    print(f"[REC] using raw input device index={device} name={dev['name']!r}")
                    return int(device)

            if 0 <= device < len(input_devices):
                raw_idx, dev = input_devices[device]
                print(
                    f"[REC] input device {device} is not a valid raw input index; "
                    f"fallback to input-list ordinal -> raw_device={raw_idx}, name={dev['name']!r}"
                )
                return int(raw_idx)

            raise ValueError(
                f"Input device {device} is neither a valid raw input device index "
                f"nor a valid ordinal in the filtered input-device list."
            )

        target = str(device).strip().lower()
        candidates: list[tuple[int, Any]] = []
        for idx, dev in input_devices:
            name = str(dev["name"]).lower()
            if target == name or target in name:
                candidates.append((idx, dev))

        if not candidates:
            raise ValueError(f"No matching input device found for: {device!r}")

        raw_idx, dev = candidates[0]
        print(f"[REC] matched input device name {device!r} -> raw_device={raw_idx}, name={dev['name']!r}")
        return int(raw_idx)

    @staticmethod
    def _print_input_device_map(input_devices: list[tuple[int, Any]]) -> None:
        print("[REC] available input devices (ordinal -> raw index):")
        for ordinal, (raw_idx, dev) in enumerate(input_devices):
            print(
                f"  [{ordinal}] raw={raw_idx} "
                f"name={dev['name']!r} "
                f"max_in={int(dev['max_input_channels'])} "
                f"default_sr={int(float(dev['default_samplerate']))}"
            )

    @staticmethod
    def _resample_linear(
        x: np.ndarray,
        src_sr: int,
        dst_sr: int,
    ) -> np.ndarray:
        if src_sr == dst_sr or x.size == 0:
            return x.astype(np.float32, copy=False)

        duration = x.shape[0] / float(src_sr)
        dst_n = max(1, int(round(duration * dst_sr)))

        src_idx = np.linspace(0, x.shape[0] - 1, num=x.shape[0], dtype=np.float32)
        dst_idx = np.linspace(0, x.shape[0] - 1, num=dst_n, dtype=np.float32)

        y = np.interp(dst_idx, src_idx, x).astype(np.float32)
        return y
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/adaptive_controller.py`

```python
from __future__ import annotations

import time
from dataclasses import dataclass

from shadowing.interfaces.controller import Controller
from shadowing.types import ControlAction, ControlDecision


@dataclass
class _ReplayState:
    active: bool = False
    last_trigger_at_sec: float = 0.0
    last_committed_idx: int = 0


class AdaptiveController(Controller):

    def __init__(
        self,
        target_lead_sec: float = 0.35,
        max_catchup_lead_sec: float = 1.20,
        hold_lead_sec: float = 1.40,
        replay_drop_tokens: int = 3,
        replay_cooldown_sec: float = 1.2,
        replay_seek_lead_sec: float = 0.20,
        ducking_gain_speaking: float = 0.55,
        ducking_gain_transition: float = 0.75,
        base_gain: float = 1.00,
        ducking_only: bool = False,
        disable_seek: bool = False,
        disable_hold: bool = False,
    ) -> None:
        self.target_lead_sec = float(target_lead_sec)
        self.max_catchup_lead_sec = float(max_catchup_lead_sec)
        self.hold_lead_sec = float(hold_lead_sec)

        self.replay_drop_tokens = int(replay_drop_tokens)
        self.replay_cooldown_sec = float(replay_cooldown_sec)
        self.replay_seek_lead_sec = float(replay_seek_lead_sec)

        self.ducking_gain_speaking = float(ducking_gain_speaking)
        self.ducking_gain_transition = float(ducking_gain_transition)
        self.base_gain = float(base_gain)

        self.ducking_only = bool(ducking_only)
        self.disable_seek = bool(disable_seek)
        self.disable_hold = bool(disable_hold)

        self._replay = _ReplayState()
        self._last_asr_event_at_sec = 0.0

    def note_asr_event(self, event) -> None:
        try:
            self._last_asr_event_at_sec = float(event.emitted_at_sec)
        except Exception:
            self._last_asr_event_at_sec = time.monotonic()

    def note_hold(self) -> None:
        pass

    def decide(self, status, alignment):
        now = time.monotonic()

        target_gain = self.base_gain

        if alignment is None:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="no_alignment",
                target_gain=None,
            )
        lead = status.t_ref_heard_sec - alignment.ref_time_sec

        if alignment.stable:
            target_gain = self.ducking_gain_speaking
        else:
            target_gain = self.ducking_gain_transition

        replay_detected = self._detect_replay_lockin(alignment, now)

        if replay_detected:
            if not self.disable_seek and not self.ducking_only:
                target_time = max(0.0, alignment.ref_time_sec + self.replay_seek_lead_sec)
                return ControlDecision(
                    action=ControlAction.SEEK,
                    reason="replay_lockin_seek",
                    target_time_sec=target_time,
                    target_gain=target_gain,
                    replay_lockin=True,
                )

            if not self.disable_hold and not self.ducking_only:
                return ControlDecision(
                    action=ControlAction.HOLD,
                    reason="replay_lockin_hold",
                    target_gain=target_gain,
                    replay_lockin=True,
                )

            return ControlDecision(
                action=ControlAction.NOOP,
                reason="replay_lockin_ducking_only",
                target_gain=target_gain,
                replay_lockin=True,
            )

        if self.ducking_only:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="ducking_only",
                target_gain=target_gain,
            )

        if lead > self.hold_lead_sec and not self.disable_hold:
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="lead_too_large_hold",
                target_gain=target_gain,
            )

        if lead < -self.max_catchup_lead_sec and not self.disable_seek:
            target_time = max(0.0, alignment.ref_time_sec + self.target_lead_sec)
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="user_ahead_seek",
                target_time_sec=target_time,
                target_gain=target_gain,
            )

        if status.state.value == "holding" and lead <= self.target_lead_sec:
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="within_band_resume",
                target_gain=target_gain,
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            target_gain=target_gain,
        )

    def _detect_replay_lockin(self, alignment, now_sec: float) -> bool:
        current_committed = int(alignment.committed_ref_idx)
        last_committed = int(self._replay.last_committed_idx)

        detected = False

        if alignment.stable:
            dropped = last_committed - current_committed
            if (
                last_committed >= self.replay_drop_tokens + 2
                and dropped >= self.replay_drop_tokens
                and (now_sec - self._replay.last_trigger_at_sec) >= self.replay_cooldown_sec
            ):
                detected = True
                self._replay.active = True
                self._replay.last_trigger_at_sec = now_sec

        self._replay.last_committed_idx = current_committed
        return detected
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
    seek_cooldown_sec: float = 0.40
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/state_estimator.py`

```python
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from shadowing.types import AlignResult, AsrEvent, ControlFeatures, PlaybackStatus


@dataclass(slots=True)
class StateEstimatorConfig:
    lead_ema_alpha: float = 0.35

    speaking_window_sec: float = 0.6
    partial_rate_window_sec: float = 2.0

    min_target_lead_sec: float = 0.08
    base_target_lead_sec: float = 0.15
    max_target_lead_sec: float = 0.35

    gain_normal: float = 1.0
    gain_soft: float = 0.75
    gain_following: float = 0.55

    duck_hold_sec: float = 0.45


class ControlStateEstimator:

    def __init__(self, config: StateEstimatorConfig | None = None) -> None:
        self.config = config or StateEstimatorConfig()

        self._lead_ema: float | None = None
        self._last_lead_ema: float | None = None

        self._partial_times: deque[float] = deque()
        self._hold_times: deque[float] = deque()

        self._last_asr_event_at: float | None = None

        self._last_following_at: float | None = None

    def note_asr_event(self, event: AsrEvent) -> None:
        now = time.monotonic()
        self._last_asr_event_at = now

        if event.event_type.value == "partial":
            self._partial_times.append(now)
            self._trim_deque(self._partial_times, now, self.config.partial_rate_window_sec)

    def note_hold(self) -> None:
        now = time.monotonic()
        self._hold_times.append(now)
        self._trim_deque(self._hold_times, now, 5.0)

    def update(
        self,
        playback: PlaybackStatus,
        alignment: AlignResult | None,
    ) -> ControlFeatures:
        now = time.monotonic()

        lead_raw: float | None = None
        alignment_conf = 0.0
        alignment_stable = False

        if alignment is not None:
            lead_raw = playback.t_ref_heard_sec - alignment.ref_time_sec
            alignment_conf = alignment.confidence
            alignment_stable = alignment.stable

        if lead_raw is not None:
            if self._lead_ema is None:
                self._lead_ema = lead_raw
            else:
                self._lead_ema = (
                    self.config.lead_ema_alpha * lead_raw
                    + (1.0 - self.config.lead_ema_alpha) * self._lead_ema
                )

        lead_slope: float | None = None
        if self._lead_ema is not None and self._last_lead_ema is not None:
            lead_slope = self._lead_ema - self._last_lead_ema
        self._last_lead_ema = self._lead_ema

        self._trim_deque(self._partial_times, now, self.config.partial_rate_window_sec)
        self._trim_deque(self._hold_times, now, 5.0)

        recent_partial_rate = len(self._partial_times) / max(self.config.partial_rate_window_sec, 1e-6)
        recent_hold_count = len(self._hold_times)

        user_speaking = False
        if self._last_asr_event_at is not None:
            user_speaking = (now - self._last_asr_event_at) <= self.config.speaking_window_sec

        dynamic_target_lead = self._compute_dynamic_target_lead(
            alignment_conf=alignment_conf,
            alignment_stable=alignment_stable,
            recent_hold_count=recent_hold_count,
        )

        suggested_gain = self._compute_suggested_gain(
            now=now,
            user_speaking=user_speaking,
            alignment_stable=alignment_stable,
            alignment_conf=alignment_conf,
        )

        return ControlFeatures(
            lead_raw=lead_raw,
            lead_ema=self._lead_ema,
            lead_slope=lead_slope,
            alignment_conf=alignment_conf,
            alignment_stable=alignment_stable,
            user_speaking=user_speaking,
            recent_partial_rate=recent_partial_rate,
            recent_hold_count=recent_hold_count,
            dynamic_target_lead=dynamic_target_lead,
            suggested_gain=suggested_gain,
            playback_state=playback.state.value,
        )

    def _compute_dynamic_target_lead(
        self,
        alignment_conf: float,
        alignment_stable: bool,
        recent_hold_count: int,
    ) -> float:
        target = self.config.base_target_lead_sec

        if alignment_stable and alignment_conf >= 0.85:
            target += 0.05

        if recent_hold_count >= 2:
            target -= 0.06

        target = min(max(target, self.config.min_target_lead_sec), self.config.max_target_lead_sec)
        return target

    def _compute_suggested_gain(
        self,
        now: float,
        user_speaking: bool,
        alignment_stable: bool,
        alignment_conf: float,
    ) -> float:
        if user_speaking and alignment_stable and alignment_conf >= 0.75:
            self._last_following_at = now
            return self.config.gain_following

        if self._last_following_at is not None:
            if (now - self._last_following_at) <= self.config.duck_hold_sec:
                return self.config.gain_following

        if user_speaking:
            return self.config.gain_soft

        return self.config.gain_normal

    @staticmethod
    def _trim_deque(dq: deque[float], now: float, window_sec: float) -> None:
        while dq and (now - dq[0]) > window_sec:
            dq.popleft()
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/state_machine_controller.py`

```python
from __future__ import annotations

import time

from shadowing.interfaces.controller import Controller
from shadowing.types import AlignResult, ControlAction, ControlDecision, PlaybackStatus
from shadowing.realtime.control.policy import ControlPolicy


class StateMachineController(Controller):
    def __init__(
        self,
        policy: ControlPolicy | None = None,
        total_duration_sec: float | None = None,
    ) -> None:
        self.policy = policy or ControlPolicy()
        self.total_duration_sec = total_duration_sec
        self._last_seek_at = 0.0

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

        now = time.monotonic()
        if (
            alignment.stable
            and lead < self.policy.seek_if_lag_sec
            and (now - self._last_seek_at) >= self.policy.seek_cooldown_sec
        ):
            target_time = alignment.ref_time_sec + self.policy.target_lead_sec
            if self.total_duration_sec is not None:
                target_time = min(max(0.0, target_time), self.total_duration_sec)
            else:
                target_time = max(0.0, target_time)

            self._last_seek_at = now
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="user_skipped_forward",
                target_time_sec=target_time,
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

import queue
import threading
import time

from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.aligner import Aligner
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import (
    AsrEvent,
    ControlAction,
    PlayerCommand,
    PlayerCommandType,
)


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner: Aligner,
        controller: Controller,
        audio_queue_maxsize: int = 6,
        asr_event_queue_maxsize: int = 32,
        loop_interval_sec: float = 0.03,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller

        self.audio_frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=audio_queue_maxsize)
        self.asr_event_queue: queue.Queue[AsrEvent] = queue.Queue(maxsize=asr_event_queue_maxsize)

        self.loop_interval_sec = loop_interval_sec
        self._running = False
        self._asr_thread: threading.Thread | None = None
        self._last_alignment = None

        self._debug_enabled = False
        self._debug_heartbeat_sec = 1.0
        self._debug_print_asr = True
        self._debug_print_alignment = True
        self._debug_print_decision = True
        self._debug_print_player_status = True
        self._debug_print_reference_head = True
        self._last_heartbeat_at = 0.0

        self._pure_playback = False

    def configure_debug(self, debug_cfg: dict) -> None:
        self._debug_enabled = bool(debug_cfg.get("enabled", False))
        self._debug_heartbeat_sec = float(debug_cfg.get("heartbeat_sec", 1.0))
        self._debug_print_asr = bool(debug_cfg.get("print_asr", True))
        self._debug_print_alignment = bool(debug_cfg.get("print_alignment", True))
        self._debug_print_decision = bool(debug_cfg.get("print_decision", True))
        self._debug_print_player_status = bool(debug_cfg.get("print_player_status", True))
        self._debug_print_reference_head = bool(debug_cfg.get("print_reference_head", True))

    def configure_runtime(self, runtime_cfg: dict) -> None:
        self._pure_playback = bool(runtime_cfg.get("pure_playback", False))

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        if hasattr(self.controller, "total_duration_sec"):
            try:
                self.controller.total_duration_sec = ref_map.total_duration_sec
            except Exception:
                pass

        if hasattr(self.player, "sample_rate"):
            try:
                self.player.sample_rate = int(manifest.sample_rate_out)
            except Exception:
                pass

        self.aligner.reset(ref_map)

        if self._debug_enabled and self._debug_print_reference_head:
            head = "".join(tok.char for tok in ref_map.tokens[:20])
            head_py = [tok.pinyin for tok in ref_map.tokens[:10]]
            print(f"[REF] total_tokens={len(ref_map.tokens)} total_duration={ref_map.total_duration_sec:.3f}")
            print(f"[REF] head_chars={head!r}")
            print(f"[REF] head_pinyin={head_py}")

        self.player.load_chunks(chunks)

        self._running = True

        if not self._pure_playback:
            hotwords = manifest.lesson_text

            if hasattr(self.asr, "hotwords"):
                try:
                    self.asr.hotwords = hotwords
                except Exception:
                    pass

            if hasattr(self.asr, "reference_text"):
                try:
                    self.asr.reference_text = manifest.lesson_text
                except Exception:
                    pass

            self.asr.start()
            self._asr_thread = threading.Thread(target=self._asr_worker, daemon=True)
            self._asr_thread.start()
            self.recorder.start(self._on_audio_frame)

        self.player.start()

        if self._pure_playback:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SET_GAIN,
                    gain=1.0,
                    reason="pure_playback_gain",
                )
            )

        self._last_heartbeat_at = time.monotonic()

        while self._running:
            self._control_tick()
            self._debug_heartbeat()
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

        try:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.STOP, reason="session_stop")
            )
            self.player.stop()
        except Exception:
            pass

    def _on_audio_frame(self, pcm: bytes) -> None:
        try:
            self.audio_frame_queue.put_nowait(pcm)
        except queue.Full:
            try:
                _ = self.audio_frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_frame_queue.put_nowait(pcm)
            except queue.Full:
                pass

    def _asr_worker(self) -> None:
        while self._running and not self._pure_playback:
            try:
                pcm = self.audio_frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            self.asr.feed_pcm16(pcm)
            events = self.asr.poll_events()

            for event in events:
                try:
                    self.asr_event_queue.put_nowait(event)
                except queue.Full:
                    try:
                        _ = self.asr_event_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.asr_event_queue.put_nowait(event)
                    except queue.Full:
                        pass

    def _control_tick(self) -> None:
        latest_alignment = self._last_alignment

        if self._debug_enabled:
            print(
                f"[DBG] tick_start "
                f"cached_alignment={type(self._last_alignment).__name__} "
                f"value={self._last_alignment}"
            )

        while not self._pure_playback:
            try:
                event = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

            if hasattr(self.controller, "note_asr_event"):
                try:
                    self.controller.note_asr_event(event)
                except Exception:
                    pass

            if self._debug_enabled and self._debug_print_asr:
                self._debug_print_asr_event(event)

            latest_alignment = self.aligner.update(event)

            if self._debug_enabled:
                print(
                    f"[DBG] aligner_return "
                    f"type={type(latest_alignment).__name__} "
                    f"value={latest_alignment}"
                )

            if latest_alignment is not None:
                self._last_alignment = latest_alignment
                if self._debug_enabled:
                    print(
                        f"[DBG] cache_alignment_updated "
                        f"type={type(self._last_alignment).__name__} "
                        f"value={self._last_alignment}"
                    )

            if self._debug_enabled and self._debug_print_alignment and latest_alignment is not None:
                self._debug_print_alignment_result(latest_alignment)

        status = self.player.get_status()

        if self._debug_enabled:
            print(
                f"[DBG] before_decide "
                f"latest_alignment_type={type(latest_alignment).__name__} "
                f"latest_alignment={latest_alignment}"
            )

        if status.state.value == "finished":
            if self._debug_enabled:
                print("[SYSTEM] player finished, stopping orchestrator.")
            self._running = False
            return

        if self._pure_playback:
            if self._debug_enabled and self._debug_print_decision:
                print(
                    "[CTRL] action=noop "
                    "reason=pure_playback "
                    "lead=None target=None gain=1.00 "
                    f"player_state={status.state.value}"
                )
            return

        decision = self.controller.decide(status, latest_alignment)

        if decision.target_gain is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SET_GAIN,
                    gain=decision.target_gain,
                    reason="adaptive_ducking",
                )
            )

        if self._debug_enabled and self._debug_print_decision:
            self._debug_print_decision_result(status, latest_alignment, decision)

        if decision.action == ControlAction.HOLD:
            if hasattr(self.controller, "note_hold"):
                try:
                    self.controller.note_hold()
                except Exception:
                    pass

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
            

    def _debug_heartbeat(self) -> None:
        if not self._debug_enabled or not self._debug_print_player_status:
            return

        now = time.monotonic()
        if (now - self._last_heartbeat_at) < self._debug_heartbeat_sec:
            return

        status = self.player.get_status()
        print(
            "[PLAYER] "
            f"state={status.state.value} "
            f"chunk={status.chunk_id} "
            f"frame={status.frame_index} "
            f"t_sched={status.t_ref_sched_sec:.3f} "
            f"t_heard={status.t_ref_heard_sec:.3f}"
        )
        self._last_heartbeat_at = now

    def _debug_print_asr_event(self, event: AsrEvent) -> None:
        print(
            "[ASR] "
            f"type={event.event_type.value} "
            f"text={event.text!r} "
            f"norm={event.normalized_text!r} "
            f"py={event.pinyin_seq}"
        )

    def _debug_print_alignment_result(self, alignment) -> None:
        print(
            "[ALIGN] "
            f"committed={alignment.committed_ref_idx} "
            f"candidate={alignment.candidate_ref_idx} "
            f"t_user={alignment.ref_time_sec:.3f} "
            f"conf={alignment.confidence:.3f} "
            f"stable={alignment.stable} "
            f"matched={alignment.matched_text!r}"
        )

    def _debug_print_decision_result(self, status, alignment, decision) -> None:
        lead = None
        if alignment is not None:
            lead = status.t_ref_heard_sec - alignment.ref_time_sec

        lead_str = "None" if lead is None else f"{lead:.3f}"
        target_str = "None" if decision.target_time_sec is None else f"{decision.target_time_sec:.3f}"
        gain_str = "None" if decision.target_gain is None else f"{decision.target_gain:.2f}"

        print(
            "[CTRL] "
            f"action={decision.action.value} "
            f"reason={decision.reason} "
            f"lead={lead_str} "
            f"target={target_str} "
            f"gain={gain_str} "
            f"player_state={status.state.value}"
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

        self._current_chunk_idx: int = 0
        self._frame_offset_in_chunk: int = 0
        self._sample_rate: int = 0
        self._total_duration_sec: float = 0.0

    def load(self, chunks: list[AudioChunk]) -> None:
        self._chunks = chunks
        self._chunk_start_times = [c.start_time_sec for c in chunks]
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0
        self._sample_rate = chunks[0].sample_rate if chunks else 0

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

    def is_empty(self) -> bool:
        return not self._chunks

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
        local_frame = min(local_frame, len(chunk.samples))

        self._current_chunk_idx = idx
        self._frame_offset_in_chunk = local_frame

    def get_scheduled_time_sec(self) -> float:
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
            remain_in_chunk = len(chunk.samples) - self._frame_offset_in_chunk
            need = frames - written
            take = min(remain_in_chunk, need)

            if take > 0:
                data = chunk.samples[
                    self._frame_offset_in_chunk : self._frame_offset_in_chunk + take
                ]

                if data.ndim == 1:
                    out[written : written + take, 0] = data
                else:
                    out[written : written + take, : data.shape[1]] = data

                self._frame_offset_in_chunk += take
                written += take

            if self._frame_offset_in_chunk >= len(chunk.samples):
                self._current_chunk_idx += 1
                self._frame_offset_in_chunk = 0

                if self._current_chunk_idx >= len(self._chunks):
                    break

        return out
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/command_slot.py`

```python
from __future__ import annotations

from shadowing.types import PlayerCommand


class CommandSlot:
    def __init__(self) -> None:
        self._cmd: PlayerCommand | None = None

    def put(self, cmd: PlayerCommand) -> None:
        self._cmd = cmd

    def pop(self) -> PlayerCommand | None:
        cmd = self._cmd
        self._cmd = None
        return cmd
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

import sounddevice as sd

from shadowing.interfaces.player import Player
from shadowing.types import (
    AudioChunk,
    PlaybackState,
    PlaybackStatus,
    PlayerCommand,
    PlayerCommandType,
)
from shadowing.realtime.playback.chunk_queue import ChunkQueue
from shadowing.realtime.playback.playback_clock import PlaybackClock
from shadowing.realtime.playback.command_slot import CommandSlot


class SoundDevicePlayer(Player):
    def __init__(
        self,
        sample_rate: int,
        channels: int,
        device: int | None = None,
        bluetooth_output_offset_sec: float = 0.0,
        latency: str | float = "low",
        blocksize: int = 0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.latency = latency
        self.blocksize = blocksize

        self.clock = PlaybackClock(bluetooth_output_offset_sec)
        self.queue = ChunkQueue()
        self.command_slot = CommandSlot()

        self._stream: sd.OutputStream | None = None
        self._state = PlaybackState.STOPPED

        self._current_chunk_id = -1
        self._frame_index = 0
        self._t_host_output_sec = 0.0
        self._t_ref_sched_sec = 0.0
        self._t_ref_heard_sec = 0.0

        self._gain = 1.0

    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        self.queue.load(chunks)
        if chunks:
            self._current_chunk_id = chunks[0].chunk_id
            self._frame_index = 0

    def start(self) -> None:
        if self._stream is not None:
            return

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._audio_callback,
            device=self.device,
            latency=self.latency,
            blocksize=self.blocksize,
        )
        self._stream.start()
        self._state = PlaybackState.PLAYING

    def submit_command(self, command: PlayerCommand) -> None:
        self.command_slot.put(command)

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
        self.submit_command(PlayerCommand(cmd=PlayerCommandType.STOP, reason="external_stop"))

    def close(self) -> None:
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self._state = PlaybackState.STOPPED

    def _apply_command_if_any(self) -> None:
        cmd = self.command_slot.pop()
        if cmd is None:
            return

        if cmd.cmd == PlayerCommandType.HOLD:
            self._state = PlaybackState.HOLDING

        elif cmd.cmd == PlayerCommandType.RESUME:
            self._state = PlaybackState.PLAYING

        elif cmd.cmd == PlayerCommandType.SEEK:
            self._state = PlaybackState.SEEKING
            if cmd.target_time_sec is not None:
                self.queue.seek(cmd.target_time_sec)
            self._state = PlaybackState.PLAYING

        elif cmd.cmd == PlayerCommandType.STOP:
            self._state = PlaybackState.STOPPED

        elif cmd.cmd == PlayerCommandType.START:
            self._state = PlaybackState.PLAYING

        elif cmd.cmd == PlayerCommandType.SET_GAIN:
            if cmd.gain is not None:
                self._gain = min(max(cmd.gain, 0.0), 1.0)

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        self._apply_command_if_any()

        if self._state in (PlaybackState.STOPPED, PlaybackState.HOLDING, PlaybackState.FINISHED):
            outdata.fill(0.0)
        else:
            block = self.queue.read_frames(frames=frames, channels=self.channels)

            outdata[:] = block * self._gain

            if self.queue.is_finished():
                self._state = PlaybackState.FINISHED

            self._current_chunk_id = self.queue.current_chunk_id
            self._frame_index = self.queue.current_frame_index

        scheduled_ref_time = self.queue.get_scheduled_time_sec()
        clock_snapshot = self.clock.compute(
            output_buffer_dac_time_sec=time_info.outputBufferDacTime,
            scheduled_ref_time_sec=scheduled_ref_time,
        )
        self._t_host_output_sec = clock_snapshot.t_host_output_sec
        self._t_ref_sched_sec = clock_snapshot.t_ref_sched_sec
        self._t_ref_heard_sec = clock_snapshot.t_ref_heard_sec
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


class PlayerCommandType(str, Enum):
    START = "start"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"
    SET_GAIN = "set_gain"


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
    samples: "object"
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
    target_gain: Optional[float] = None
    replay_lockin: bool = False


@dataclass(slots=True)
class ControlFeatures:
    lead_raw: Optional[float]
    lead_ema: Optional[float]
    lead_slope: Optional[float]
    alignment_conf: float
    alignment_stable: bool
    user_speaking: bool
    recent_partial_rate: float
    recent_hold_count: int
    dynamic_target_lead: float
    suggested_gain: float
    playback_state: str
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
### 文件: `shadowing_app/tools/list_recording_devices.py`

```python
import _bootstrap  # noqa: F401

from shadowing.realtime.capture.device_utils import (
    print_input_devices,
    get_default_input_device_index,
    pick_working_input_config,
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


DEFAULT_TEXT_FILE = r"D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"

DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r"[\\/:\*\?\"<>\|]+", "_", stem)
    stem = re.sub(r"\s+", "_", stem)
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
    if not source_path.exists():
        return False

    cached_text = source_path.read_text(encoding="utf-8").strip()
    return cached_text == current_text.strip()


def print_cache_status(
    lesson_dir: Path,
    assets_ok: bool,
    same_text: bool,
    force: bool,
) -> None:
    print("=== Cache check ===")
    print(f"lesson dir         : {lesson_dir}")
    print(f"assets complete    : {assets_ok}")
    print(f"source text same   : {same_text}")
    print(f"force rebuild      : {force}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess a local txt speech file into lesson assets using ElevenLabs."
    )
    parser.add_argument(
        "--text-file",
        type=str,
        default=DEFAULT_TEXT_FILE,
        help="Path to local txt file. Default points to a fake placeholder path; change it locally.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.getenv("ELEVENLABS_API_KEY", ""),
        help="ElevenLabs API key. Defaults to env ELEVENLABS_API_KEY.",
    )
    parser.add_argument(
        "--voice-id",
        type=str,
        default=DEFAULT_VOICE_ID,
        help="ElevenLabs voice id.",
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default=DEFAULT_MODEL_ID,
        help="ElevenLabs model id.",
    )
    parser.add_argument(
        "--lesson-base-dir",
        type=str,
        default="assets/lessons",
        help="Base output dir for generated lessons.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if local cached assets already exist.",
    )

    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")

    if text_path.suffix.lower() != ".txt":
        raise ValueError(f"Expected a .txt file, got: {text_path}")

    lesson_text = text_path.read_text(encoding="utf-8").strip()
    if not lesson_text:
        raise ValueError(f"Text file is empty: {text_path}")

    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    output_dir = lesson_base_dir / lesson_id
    output_dir.mkdir(parents=True, exist_ok=True)

    assets_ok, missing = lesson_assets_exist(output_dir)
    text_same = same_source_text(output_dir, lesson_text)

    print("=== Preprocess config ===")
    print(f"text file : {text_path}")
    print(f"lesson id : {lesson_id}")
    print(f"output dir: {output_dir}")
    print(f"voice id  : {args.voice_id}")
    print(f"model id  : {args.model_id}")
    print()

    print_cache_status(
        lesson_dir=output_dir,
        assets_ok=assets_ok,
        same_text=text_same,
        force=args.force,
    )

    if assets_ok and text_same and not args.force:
        print("Local lesson assets already exist and source text is unchanged.")
        print("Skip ElevenLabs preprocessing.")
        print()
        print("Next step:")
        print(f'python tools\\run_shadowing.py --text-file "{text_path}"')
        return

    if not args.api_key:
        raise ValueError(
            "Missing ElevenLabs API key. Pass --api-key or set ELEVENLABS_API_KEY."
        )

    if not assets_ok:
        print("Cache miss: lesson assets are incomplete.")
        if missing:
            print("Missing:")
            for item in missing:
                print(f"  - {item}")
        print()
    elif not text_same:
        print("Cache invalidated: source text has changed.")
        print()

    if args.force:
        print("Force rebuild enabled. ElevenLabs preprocessing will run.")
        print()

    source_copy_path = output_dir / "source.txt"
    if source_copy_path.resolve() != text_path:
        shutil.copyfile(text_path, source_copy_path)

    tts = ElevenLabsTTSProvider(
        api_key=args.api_key,
        voice_id=args.voice_id,
        model_id=args.model_id,
    )
    repo = FileLessonRepository(str(lesson_base_dir))
    pipeline = LessonPreprocessPipeline(tts_provider=tts, repo=repo)

    pipeline.run(
        lesson_id=lesson_id,
        text=lesson_text,
        output_dir=str(output_dir),
    )

    print("Preprocess completed.")
    print(f"Generated lesson assets under: {output_dir}")
    print()
    print("Next step:")
    print(f'python tools\\run_shadowing.py --text-file "{text_path}"')


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
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider


DEFAULT_TEXT_FILE = r"D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"


def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r'[\\/:\*\?"<>\|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def validate_lesson_assets(lesson_dir: Path) -> None:
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

    if missing:
        msg = "\n".join(missing)
        raise FileNotFoundError(
            "Lesson assets not found. Please run preprocess first.\n"
            f"Missing:\n{msg}"
        )


def load_manifest(lesson_dir: Path) -> dict:
    manifest_path = lesson_dir / "lesson_manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_recording_config(
    manual_device: int | None,
    manual_samplerate: int | None,
) -> dict:
    from shadowing.realtime.capture.device_utils import pick_working_input_config

    if manual_device is not None:
        return {
            "device": manual_device,
            "samplerate": int(manual_samplerate or 48000),
            "channels": 1,
            "dtype": "float32",
        }

    rec_cfg = pick_working_input_config()
    if rec_cfg is None:
        raise RuntimeError(
            "No working input device config found. "
            "Try specifying --input-device manually, e.g. --input-device 9"
        )

    if manual_samplerate is not None:
        rec_cfg["samplerate"] = int(manual_samplerate)

    return rec_cfg


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

    for key in ("tokens", "encoder", "decoder", "joiner"):
        value = (paths.get(key) or "").strip()
        if not value:
            missing_keys.append(key)
            continue
        if not Path(value).expanduser().exists():
            missing_files.append(f"{key}: {value}")

    if missing_keys or missing_files:
        parts: list[str] = []
        if missing_keys:
            parts.append(
                "Missing sherpa env vars: "
                + ", ".join(
                    {
                        "tokens": "SHERPA_TOKENS",
                        "encoder": "SHERPA_ENCODER",
                        "decoder": "SHERPA_DECODER",
                        "joiner": "SHERPA_JOINER",
                    }[k]
                    for k in missing_keys
                )
            )
        if missing_files:
            parts.append("Non-existent sherpa files:\n" + "\n".join(missing_files))

        raise FileNotFoundError(
            "Sherpa model configuration is invalid.\n" + "\n".join(parts)
        )


def build_config(
    lesson_base_dir: str,
    input_device: int | None,
    input_samplerate: int,
    asr_mode: str,
    bluetooth_offset_sec: float,
    debug: bool,
    playback_sample_rate: int,
    pure_playback: bool,
    ducking_only: bool,
    disable_seek: bool,
    disable_hold: bool,
    sherpa_paths: dict,
) -> dict:
    return {
        "lesson_base_dir": lesson_base_dir,
        "playback": {
            "sample_rate": playback_sample_rate,
            "device": None,
            "bluetooth_output_offset_sec": bluetooth_offset_sec,
        },
        "capture": {
            "device_sample_rate": input_samplerate,
            "target_sample_rate": 16000,
            "device": input_device,
        },
        "asr": {
            "mode": asr_mode,
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
        },
        "debug": {
            "enabled": debug,
            "heartbeat_sec": 1.0,
            "print_asr": True,
            "print_alignment": True,
            "print_decision": True,
            "print_player_status": True,
            "print_reference_head": True,
        },
        "runtime": {
            "pure_playback": pure_playback,
        },
        "control": {
            "ducking_only": ducking_only,
            "disable_seek": disable_seek,
            "disable_hold": disable_hold,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the shadowing app for a local txt speech lesson."
    )
    parser.add_argument(
        "--text-file",
        type=str,
        default=DEFAULT_TEXT_FILE,
        help="Path to the original txt file. Lesson id is derived from the file name.",
    )
    parser.add_argument(
        "--lesson-base-dir",
        type=str,
        default="assets/lessons",
        help="Base dir where preprocessed lesson assets are stored.",
    )
    parser.add_argument(
        "--asr",
        type=str,
        default="fake",
        choices=["fake", "sherpa"],
        help="ASR mode.",
    )
    parser.add_argument(
        "--bluetooth-offset-sec",
        type=float,
        default=0.18,
        help="Estimated Bluetooth playback offset.",
    )
    parser.add_argument(
        "--input-device",
        type=int,
        default=None,
        help="Manually specify recording input device index. "
             "Recommended on Windows when auto-picked device fails.",
    )
    parser.add_argument(
        "--input-samplerate",
        type=int,
        default=None,
        help="Override recording input sample rate. "
             "Useful if a device fails at its default rate.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable runtime debug logs.",
    )
    parser.add_argument(
        "--pure-playback",
        action="store_true",
        help="Pure playback debug mode: disable controller intervention and force gain=1.0.",
    )
    parser.add_argument(
        "--ducking-only",
        action="store_true",
        help="Only apply ducking/gain control. Disable resume/hold/seek actions.",
    )
    parser.add_argument(
        "--disable-seek",
        action="store_true",
        help="Disable SEEK decisions.",
    )
    parser.add_argument(
        "--disable-hold",
        action="store_true",
        help="Disable HOLD decisions.",
    )

    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")

    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    lesson_dir = lesson_base_dir / lesson_id

    validate_lesson_assets(lesson_dir)
    manifest = load_manifest(lesson_dir)
    playback_sample_rate = int(manifest["sample_rate_out"])

    rec_cfg = resolve_recording_config(
        manual_device=args.input_device,
        manual_samplerate=args.input_samplerate,
    )

    sherpa_paths = collect_sherpa_paths()

    if args.asr == "sherpa" and not args.pure_playback:
        validate_sherpa_paths(sherpa_paths)

    config = build_config(
        lesson_base_dir=str(lesson_base_dir),
        input_device=rec_cfg["device"],
        input_samplerate=int(rec_cfg["samplerate"]),
        asr_mode=args.asr,
        bluetooth_offset_sec=args.bluetooth_offset_sec,
        debug=args.debug,
        playback_sample_rate=playback_sample_rate,
        pure_playback=args.pure_playback,
        ducking_only=args.ducking_only,
        disable_seek=args.disable_seek,
        disable_hold=args.disable_hold,
        sherpa_paths=sherpa_paths,
    )

    print("=== Run config ===")
    print(f"text file       : {text_path}")
    print(f"lesson id       : {lesson_id}")
    print(f"lesson dir      : {lesson_dir}")
    print(f"input device    : {rec_cfg['device']}")
    print(f"input sr        : {rec_cfg['samplerate']}")
    print(f"playback sr     : {playback_sample_rate}")
    print(f"asr mode        : {args.asr}")
    print(f"bt offset sec   : {args.bluetooth_offset_sec}")
    print(f"debug           : {args.debug}")
    print(f"pure playback   : {args.pure_playback}")
    print(f"ducking only    : {args.ducking_only}")
    print(f"disable seek    : {args.disable_seek}")
    print(f"disable hold    : {args.disable_hold}")
    print()

    runtime = build_runtime(config)

    if args.asr == "fake" and not args.pure_playback:
        lesson_text = text_path.read_text(encoding="utf-8").strip()
        runtime.orchestrator.asr = FakeASRProvider.from_reference_text(
            reference_text=lesson_text,
            chars_per_step=4,
            step_interval_sec=0.25,
            lag_sec=0.4,
            tail_final=True,
        )

    if hasattr(runtime.orchestrator, "configure_debug"):
        runtime.orchestrator.configure_debug(config["debug"])

    print("Starting shadowing runtime...")
    print("Press Ctrl+C to stop.")
    print()

    try:
        runtime.run(lesson_id)
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
```

---
### 文件: `shadowing_app/tools/test_fake_asr_with_recorder.py`

```python
import queue
import threading
import time
import _bootstrap  # noqa: F401

from shadowing.realtime.capture.device_utils import (
    print_input_devices,
    get_default_input_device_index,
    pick_working_input_config,
)
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig
from shadowing.realtime.capture.device_utils import pick_working_input_config
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder


def main() -> None:
    q: queue.Queue[bytes] = queue.Queue(maxsize=8)
    running = True

    rec_cfg = pick_working_input_config()
    if rec_cfg is None:
        raise RuntimeError("No working input device config found.")

    recorder = SoundDeviceRecorder(
        sample_rate_in=rec_cfg["samplerate"],
        target_sample_rate=16000,
        channels=rec_cfg["channels"],
        device=rec_cfg["device"],
        dtype=rec_cfg["dtype"],
    )

    asr = FakeASRProvider(
        FakeAsrConfig(
            reference_text="今天天气真好我们一起练习中文",
            chars_per_sec=4.5,
            emit_partial_interval_sec=0.10,
            sample_rate=16000,
        )
    )
    asr.start()

    def on_audio_frame(pcm: bytes) -> None:
        try:
            q.put_nowait(pcm)
        except queue.Full:
            try:
                _ = q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(pcm)
            except queue.Full:
                pass

    def worker() -> None:
        while running:
            try:
                pcm = q.get(timeout=0.05)
            except queue.Empty:
                continue

            asr.feed_pcm16(pcm)
            events = asr.poll_events()
            for e in events:
                print(f"[{e.event_type}] text={e.text} norm={e.normalized_text} py={e.pinyin_seq}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    recorder.start(on_audio_frame)
    print("Recording... speak something. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop()
        recorder.close()
        asr.close()


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
        print(f"\n[{ordinal}] raw={raw_idx} name={name!r} max_in={max_in} default_sr={default_sr}")

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

