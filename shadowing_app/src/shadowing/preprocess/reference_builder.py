from __future__ import annotations

from shadowing.types import RefToken, ReferenceMap


class ReferenceBuilder:
    _DROP_CHARS = {
        " ", "\t", "\n", "\r", "\u3000",
        "，", "。", "！", "？", "；", "：", "、",
        ",", ".", "!", "?", ";", ":", '"', "'", "“", "”", "‘", "’",
        "（", "）", "(", ")", "[", "]", "【", "】", "<", ">", "《", "》",
        "-", "—", "…", "|", "/", "\\",
    }

    def build(
        self,
        lesson_id: str,
        chars: list[str],
        pinyins: list[str],
        starts: list[float],
        ends: list[float],
        sentence_ids: list[int],
        clause_ids: list[int],
        total_duration_sec: float,
    ) -> ReferenceMap:
        tokens: list[RefToken] = []
        next_idx = 0
        for ch, py, ts, te, sid, cid in zip(
            chars, pinyins, starts, ends, sentence_ids, clause_ids, strict=True
        ):
            if not ch or ch in self._DROP_CHARS or not ch.strip():
                continue
            tokens.append(
                RefToken(
                    idx=next_idx,
                    char=ch,
                    pinyin=py,
                    t_start=float(ts),
                    t_end=float(te),
                    sentence_id=int(sid),
                    clause_id=int(cid),
                )
            )
            next_idx += 1
        return ReferenceMap(
            lesson_id=lesson_id,
            tokens=tokens,
            total_duration_sec=float(total_duration_sec),
        )