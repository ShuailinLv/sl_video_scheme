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
    模式优先级：
    1. scripted_steps 非空 -> scripted timeline 模式
    2. reference_text 非空 -> progressive 模式
    """
    scripted_steps: list[FakeAsrStep] = field(default_factory=list)

    reference_text: str = ""
    chars_per_sec: float = 4.0
    emit_partial_interval_sec: float = 0.12
    emit_final_on_endpoint: bool = True

    sample_rate: int = 16000
    bytes_per_sample: int = 2
    channels: int = 1


class FakeASRProvider(ASRProvider):
    """
    可运行的假 ASR，用于联调整条控制闭环。

    模式 A: scripted
        按预设时间输出 partial/final。适合同步控制调试。

    模式 B: progressive
        根据 feed_pcm16 收到的音频字节数，逐步“假装识别”更多文本。
        适合测试 recorder -> queue -> asr_worker 链路。
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
        """
        生成更适合同步调试的 scripted timeline。

        关键改动：
        - 使用“前缀增长型 partial”
        - 每一步给出从开头到当前位置的前缀，而不是滑动窗口切片

        参数说明：
        - chars_per_step: 每一步前进多少字
        - step_interval_sec: 每一步间隔
        - lag_sec: 相对播放器的“假想用户滞后”
        - pause_at_step/pause_extra_sec: 在某步制造停顿
        - jump_to_char/jump_at_step: 在某一步制造跳读
        """
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

        # progressive 模式也改成前缀增长型
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