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