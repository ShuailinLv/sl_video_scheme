from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from shadowing.interfaces.asr import ASRProvider
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.types import AsrEvent, AsrEventType


@dataclass(slots=True)
class FakeAsrStep:
    """
    在 offset_sec 时间点之后，发出一个事件。
    """
    offset_sec: float
    text: str
    event_type: AsrEventType = AsrEventType.PARTIAL


@dataclass(slots=True)
class FakeAsrConfig:
    """
    两种模式：
    1. scripted_steps 非空 -> 严格按步骤吐事件
    2. reference_text 非空 -> 根据喂入音频量逐步“假装识别”更多文本
    """
    scripted_steps: list[FakeAsrStep] = field(default_factory=list)

    reference_text: str = ""
    chars_per_sec: float = 4.0
    emit_partial_interval_sec: float = 0.12
    emit_final_on_endpoint: bool = True

    sample_rate: int = 16000
    bytes_per_sample: int = 2     # int16
    channels: int = 1


class FakeASRProvider(ASRProvider):
    """
    可运行的假 ASR，用于先联调整个控制闭环。

    模式 A: scripted
        按预设时间输出 partial/final

    模式 B: progressive
        根据 feed_pcm16 收到的音频字节数，按 chars_per_sec 推进参考文本
    """

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

    # ----------------------------
    # internal: scripted mode
    # ----------------------------
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

    # ----------------------------
    # internal: progressive mode
    # ----------------------------
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
            normalized = self.normalizer.normalize_text(self.config.reference_text)
            pinyin_seq = self.normalizer.to_pinyin_seq(self.config.reference_text)

            if normalized:
                events.append(
                    AsrEvent(
                        event_type=AsrEventType.FINAL,
                        text=self.config.reference_text,
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