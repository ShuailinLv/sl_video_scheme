from __future__ import annotations

from dataclasses import dataclass
import re


_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？!?；;])")
_CLAUSE_SPLIT_PATTERN = re.compile(r"(?<=[，、：,:])")


@dataclass(slots=True)
class ShadowingSegment:
    segment_id: int
    text: str
    sentence_id: int
    clause_id: int
    kind: str
    prev_context_text: str = ""
    next_context_text: str = ""


class ShadowingSegmenter:
    def __init__(
        self,
        *,
        target_chars_per_segment: int = 28,
        hard_max_chars_per_segment: int = 54,
        min_chars_per_segment: int = 6,
        context_window_segments: int = 2,
        context_max_chars: int = 100,
    ) -> None:
        self.target_chars_per_segment = max(8, int(target_chars_per_segment))
        self.hard_max_chars_per_segment = max(
            self.target_chars_per_segment + 4,
            int(hard_max_chars_per_segment),
        )
        self.min_chars_per_segment = max(2, int(min_chars_per_segment))
        self.context_window_segments = max(1, int(context_window_segments))
        self.context_max_chars = max(20, int(context_max_chars))

    def segment_text(self, text: str) -> list[ShadowingSegment]:
        raw = str(text or "").strip()
        if not raw:
            return []

        sentences = self._split_sentences(raw)
        base_units: list[tuple[str, int, int, str]] = []
        global_clause_id = 0

        for sentence_id, sent in enumerate(sentences):
            clauses = self._split_sentence_to_clauses(sent)
            followable = self._build_followable_segments_from_clauses(clauses)
            for local_idx, seg_text in enumerate(followable):
                kind = "sentence" if len(followable) == 1 else ("clause" if local_idx < len(followable) - 1 else "tail")
                base_units.append(
                    (
                        seg_text,
                        sentence_id,
                        global_clause_id,
                        kind,
                    )
                )
                global_clause_id += 1

        merged_units = self._merge_too_short_units(base_units)

        segments: list[ShadowingSegment] = []
        for idx, (seg_text, sentence_id, clause_id, kind) in enumerate(merged_units):
            segments.append(
                ShadowingSegment(
                    segment_id=idx,
                    text=seg_text,
                    sentence_id=sentence_id,
                    clause_id=clause_id,
                    kind=kind,
                )
            )

        self._attach_contexts(segments)
        return segments

    def _split_sentences(self, text: str) -> list[str]:
        parts = _SENTENCE_SPLIT_PATTERN.split(text)
        out: list[str] = []
        for part in parts:
            item = str(part).strip()
            if item:
                out.append(item)
        return out

    def _split_sentence_to_clauses(self, sentence: str) -> list[str]:
        if len(sentence) <= self.hard_max_chars_per_segment:
            return [sentence]

        parts = _CLAUSE_SPLIT_PATTERN.split(sentence)
        clauses = [p.strip() for p in parts if p and p.strip()]
        if not clauses:
            return [sentence]

        out: list[str] = []
        buf = ""
        for clause in clauses:
            if not buf:
                buf = clause
                continue
            if len(self._normalize_visible_text(buf + clause)) <= self.target_chars_per_segment:
                buf += clause
            else:
                out.append(buf)
                buf = clause
        if buf:
            out.append(buf)
        return out

    def _build_followable_segments_from_clauses(self, clauses: list[str]) -> list[str]:
        if not clauses:
            return []
        provisional: list[str] = []
        buf = ""

        for clause in clauses:
            clean_clause = clause.strip()
            if not clean_clause:
                continue

            if not buf:
                if len(self._normalize_visible_text(clean_clause)) > self.hard_max_chars_per_segment:
                    provisional.extend(self._force_split_long_text(clean_clause))
                else:
                    buf = clean_clause
                continue

            merged = buf + clean_clause
            merged_len = len(self._normalize_visible_text(merged))
            if merged_len <= self.target_chars_per_segment:
                buf = merged
                continue

            provisional.append(buf)
            if len(self._normalize_visible_text(clean_clause)) > self.hard_max_chars_per_segment:
                provisional.extend(self._force_split_long_text(clean_clause))
                buf = ""
            else:
                buf = clean_clause

        if buf:
            provisional.append(buf)

        final_segments: list[str] = []
        for item in provisional:
            if len(self._normalize_visible_text(item)) > self.hard_max_chars_per_segment:
                final_segments.extend(self._force_split_long_text(item))
            else:
                final_segments.append(item)

        return final_segments

    def _force_split_long_text(self, text: str) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        normalized_len = len(self._normalize_visible_text(raw))
        if normalized_len <= self.hard_max_chars_per_segment:
            return [raw]

        pieces: list[str] = []
        buf = ""

        for ch in raw:
            trial = buf + ch
            if len(self._normalize_visible_text(trial)) <= self.target_chars_per_segment:
                buf = trial
                continue
            if buf:
                pieces.append(buf)
            buf = ch

        if buf:
            pieces.append(buf)

        merged: list[str] = []
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if merged and len(self._normalize_visible_text(piece)) < self.min_chars_per_segment:
                merged[-1] += piece
            else:
                merged.append(piece)

        if len(merged) >= 2 and len(self._normalize_visible_text(merged[-1])) < self.min_chars_per_segment:
            merged[-2] += merged[-1]
            merged.pop()

        return merged or [raw]

    def _merge_too_short_units(
        self,
        units: list[tuple[str, int, int, str]],
    ) -> list[tuple[str, int, int, str]]:
        if not units:
            return []

        out: list[tuple[str, int, int, str]] = []
        i = 0
        while i < len(units):
            text, sentence_id, clause_id, kind = units[i]
            cur_len = len(self._normalize_visible_text(text))

            if cur_len >= self.min_chars_per_segment or not out:
                out.append((text, sentence_id, clause_id, kind))
                i += 1
                continue

            prev_text, prev_sid, prev_cid, prev_kind = out[-1]
            merged_prev = prev_text + text
            if len(self._normalize_visible_text(merged_prev)) <= self.hard_max_chars_per_segment:
                out[-1] = (merged_prev, prev_sid, prev_cid, "merged")
                i += 1
                continue

            if i + 1 < len(units):
                next_text, next_sid, next_cid, next_kind = units[i + 1]
                merged_next = text + next_text
                out.append((merged_next, sentence_id, clause_id, "merged"))
                i += 2
                continue

            out[-1] = (prev_text + text, prev_sid, prev_cid, "merged")
            i += 1

        return out

    def _attach_contexts(self, segments: list[ShadowingSegment]) -> None:
        if not segments:
            return

        for i, seg in enumerate(segments):
            prev_parts: list[str] = []
            next_parts: list[str] = []

            for j in range(max(0, i - self.context_window_segments), i):
                prev_parts.append(segments[j].text)
            for j in range(i + 1, min(len(segments), i + 1 + self.context_window_segments)):
                next_parts.append(segments[j].text)

            seg.prev_context_text = self._trim_context("".join(prev_parts), from_left=True)
            seg.next_context_text = self._trim_context("".join(next_parts), from_left=False)

    def _trim_context(self, text: str, *, from_left: bool) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if len(raw) <= self.context_max_chars:
            return raw
        if from_left:
            return raw[-self.context_max_chars :]
        return raw[: self.context_max_chars]

    def _normalize_visible_text(self, text: str) -> str:
        raw = str(text or "")
        raw = raw.replace("\u3000", " ")
        raw = re.sub(r"\s+", "", raw)
        return raw