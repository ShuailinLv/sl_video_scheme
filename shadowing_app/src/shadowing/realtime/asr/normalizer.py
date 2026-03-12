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