from __future__ import annotations

from pypinyin import lazy_pinyin


class TextNormalizer:
    def normalize_text(self, text: str) -> str:
        # TODO: 去标点、全半角、数字口语化、空白统一
        return text.strip()

    def to_pinyin_seq(self, text: str) -> list[str]:
        norm = self.normalize_text(text)
        return lazy_pinyin(norm)