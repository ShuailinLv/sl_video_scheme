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