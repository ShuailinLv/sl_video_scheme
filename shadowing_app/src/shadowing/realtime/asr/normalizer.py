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