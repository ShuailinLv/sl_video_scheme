from __future__ import annotations

from shadowing.types import ReferenceMap, RefToken


class ReferenceBuilder:
    """
    把 provider 返回的字符级时间戳转成统一内部结构。
    会过滤掉不参与对齐的字符：
    - 空白
    - 换行
    - 常见中英文标点
    """

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