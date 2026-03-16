from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from shadowing.types import RefToken, ReferenceMap


@dataclass(slots=True)
class SegmentAlignedChar:
    char: str
    pinyin: str
    t_start: float
    t_end: float
    sentence_id: int
    clause_id: int


@dataclass(slots=True)
class SegmentTimelineRecord:
    segment_id: int
    text: str
    chars: list[str]
    pinyins: list[str]
    local_starts: list[float]
    local_ends: list[float]
    global_start_sec: float
    sentence_id: int
    clause_id: int
    trim_head_sec: float = 0.0
    trim_tail_sec: float = 0.0
    assembled_start_sec: float | None = None
    assembled_end_sec: float | None = None


class ReferenceBuilder:
    _DROP_CHARS = {
        " ",
        "\t",
        "\n",
        "\r",
        "\u3000",
        "，",
        "。",
        "！",
        "？",
        "；",
        "：",
        "、",
        ",",
        ".",
        "!",
        "?",
        ";",
        ":",
        '"',
        "'",
        "“",
        "”",
        "‘",
        "’",
        "（",
        "）",
        "(",
        ")",
        "[",
        "]",
        "【",
        "】",
        "<",
        ">",
        "《",
        "》",
        "-",
        "—",
        "…",
        "|",
        "/",
        "\\",
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
        self._validate_parallel_lists(
            chars=chars,
            pinyins=pinyins,
            starts=starts,
            ends=ends,
            sentence_ids=sentence_ids,
            clause_ids=clause_ids,
        )

        aligned_chars = [
            SegmentAlignedChar(
                char=str(ch),
                pinyin=str(py or ""),
                t_start=float(ts),
                t_end=float(te),
                sentence_id=int(sid),
                clause_id=int(cid),
            )
            for ch, py, ts, te, sid, cid in zip(
                chars,
                pinyins,
                starts,
                ends,
                sentence_ids,
                clause_ids,
                strict=True,
            )
        ]
        return self._build_from_aligned_chars(
            lesson_id=lesson_id,
            aligned_chars=aligned_chars,
            total_duration_sec=total_duration_sec,
        )

    def build_from_segment_records(
        self,
        lesson_id: str,
        segment_records: Sequence[SegmentTimelineRecord | dict],
        total_duration_sec: float | None = None,
    ) -> ReferenceMap:
        aligned_chars: list[SegmentAlignedChar] = []
        max_end_sec = 0.0

        for i, raw in enumerate(segment_records):
            record = self._coerce_segment_record(raw, fallback_segment_id=i)

            self._validate_segment_record(record)

            base_start_sec = (
                float(record.assembled_start_sec)
                if record.assembled_start_sec is not None
                else float(record.global_start_sec)
            )
            trim_head_sec = max(0.0, float(record.trim_head_sec))
            trim_tail_sec = max(0.0, float(record.trim_tail_sec))

            segment_effective_end_sec = (
                float(record.assembled_end_sec)
                if record.assembled_end_sec is not None
                else None
            )

            for ch, py, local_start, local_end in zip(
                record.chars,
                record.pinyins,
                record.local_starts,
                record.local_ends,
                strict=True,
            ):
                raw_global_start = base_start_sec + max(0.0, float(local_start) - trim_head_sec)
                raw_global_end = base_start_sec + max(0.0, float(local_end) - trim_head_sec)

                if segment_effective_end_sec is not None:
                    raw_global_start = min(raw_global_start, segment_effective_end_sec)
                    raw_global_end = min(raw_global_end, segment_effective_end_sec)

                if trim_tail_sec > 0.0 and segment_effective_end_sec is None:
                    raw_global_end = max(raw_global_start, raw_global_end - trim_tail_sec)

                t_start = max(0.0, raw_global_start)
                t_end = max(t_start, raw_global_end)

                aligned_chars.append(
                    SegmentAlignedChar(
                        char=str(ch),
                        pinyin=str(py or ""),
                        t_start=float(t_start),
                        t_end=float(t_end),
                        sentence_id=int(record.sentence_id),
                        clause_id=int(record.clause_id),
                    )
                )
                max_end_sec = max(max_end_sec, t_end)

        resolved_total_duration = (
            float(total_duration_sec)
            if total_duration_sec is not None
            else float(max_end_sec)
        )

        return self._build_from_aligned_chars(
            lesson_id=lesson_id,
            aligned_chars=aligned_chars,
            total_duration_sec=resolved_total_duration,
        )

    def _build_from_aligned_chars(
        self,
        *,
        lesson_id: str,
        aligned_chars: Iterable[SegmentAlignedChar],
        total_duration_sec: float,
    ) -> ReferenceMap:
        tokens: list[RefToken] = []
        next_idx = 0

        for item in aligned_chars:
            ch = str(item.char or "")
            if not ch or ch in self._DROP_CHARS or not ch.strip():
                continue

            t_start = max(0.0, float(item.t_start))
            t_end = max(t_start, float(item.t_end))

            tokens.append(
                RefToken(
                    idx=next_idx,
                    char=ch,
                    pinyin=str(item.pinyin or ""),
                    t_start=t_start,
                    t_end=t_end,
                    sentence_id=int(item.sentence_id),
                    clause_id=int(item.clause_id),
                )
            )
            next_idx += 1

        inferred_total = max(
            [float(total_duration_sec)] + [float(t.t_end) for t in tokens] if tokens else [float(total_duration_sec)]
        )

        return ReferenceMap(
            lesson_id=lesson_id,
            tokens=tokens,
            total_duration_sec=float(inferred_total),
        )

    def _validate_parallel_lists(
        self,
        *,
        chars: Sequence[str],
        pinyins: Sequence[str],
        starts: Sequence[float],
        ends: Sequence[float],
        sentence_ids: Sequence[int],
        clause_ids: Sequence[int],
    ) -> None:
        n = len(chars)
        sizes = {
            "chars": len(chars),
            "pinyins": len(pinyins),
            "starts": len(starts),
            "ends": len(ends),
            "sentence_ids": len(sentence_ids),
            "clause_ids": len(clause_ids),
        }
        if any(size != n for size in sizes.values()):
            raise ValueError(f"ReferenceBuilder input length mismatch: {sizes}")

    def _coerce_segment_record(
        self,
        raw: SegmentTimelineRecord | dict,
        *,
        fallback_segment_id: int,
    ) -> SegmentTimelineRecord:
        if isinstance(raw, SegmentTimelineRecord):
            return raw

        if not isinstance(raw, dict):
            raise TypeError(f"Unsupported segment record type: {type(raw)!r}")

        chars = raw.get("chars")
        if chars is None:
            alignment = raw.get("alignment", {})
            chars = alignment.get("characters", [])

        pinyins = raw.get("pinyins")
        if pinyins is None:
            pinyins = [""] * len(chars)

        local_starts = raw.get("local_starts")
        if local_starts is None:
            alignment = raw.get("alignment", {})
            local_starts = alignment.get("character_start_times_seconds", [])

        local_ends = raw.get("local_ends")
        if local_ends is None:
            alignment = raw.get("alignment", {})
            local_ends = alignment.get("character_end_times_seconds", [])

        return SegmentTimelineRecord(
            segment_id=int(raw.get("segment_id", fallback_segment_id)),
            text=str(raw.get("text", "")),
            chars=[str(x) for x in chars],
            pinyins=[str(x or "") for x in pinyins],
            local_starts=[float(x) for x in local_starts],
            local_ends=[float(x) for x in local_ends],
            global_start_sec=float(raw.get("global_start_sec", 0.0)),
            sentence_id=int(raw.get("sentence_id", 0)),
            clause_id=int(raw.get("clause_id", fallback_segment_id)),
            trim_head_sec=float(raw.get("trim_head_sec", 0.0) or 0.0),
            trim_tail_sec=float(raw.get("trim_tail_sec", 0.0) or 0.0),
            assembled_start_sec=(
                None
                if raw.get("assembled_start_sec") is None
                else float(raw.get("assembled_start_sec"))
            ),
            assembled_end_sec=(
                None
                if raw.get("assembled_end_sec") is None
                else float(raw.get("assembled_end_sec"))
            ),
        )

    def _validate_segment_record(self, record: SegmentTimelineRecord) -> None:
        sizes = {
            "chars": len(record.chars),
            "pinyins": len(record.pinyins),
            "local_starts": len(record.local_starts),
            "local_ends": len(record.local_ends),
        }
        n = sizes["chars"]
        if any(size != n for size in sizes.values()):
            raise ValueError(
                f"SegmentTimelineRecord length mismatch: segment_id={record.segment_id}, sizes={sizes}"
            )