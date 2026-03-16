from __future__ import annotations

import numpy as np

from shadowing.audio.frame_feature_extractor import FrameFeatureExtractor
from shadowing.audio.reference_audio_features import (
    ReferenceAudioFeatures,
    ReferenceAudioFrameFeatures,
    ReferenceBoundaryHint,
    ReferenceTokenAcousticTemplate,
)
from shadowing.preprocess.reference_builder import SegmentTimelineRecord


class ReferenceAudioAnalyzer:
    def __init__(self, frame_size_sec: float = 0.025, hop_sec: float = 0.010, n_bands: int = 6) -> None:
        self.frame_size_sec = float(frame_size_sec)
        self.hop_sec = float(hop_sec)
        self.n_bands = int(n_bands)

    def analyze(
        self,
        *,
        lesson_id: str,
        chunks: list,
        reference_map,
        segment_records: list[SegmentTimelineRecord] | None = None,
    ) -> ReferenceAudioFeatures:
        if not chunks:
            return ReferenceAudioFeatures(
                lesson_id=lesson_id,
                frame_hop_sec=self.hop_sec,
                frame_size_sec=self.frame_size_sec,
                sample_rate=16000,
            )

        sample_rate = int(chunks[0].sample_rate)
        extractor = FrameFeatureExtractor(
            sample_rate=sample_rate,
            frame_size_sec=self.frame_size_sec,
            hop_sec=self.hop_sec,
            n_bands=self.n_bands,
        )

        frames: list[ReferenceAudioFrameFeatures] = []
        for chunk in chunks:
            samples = np.asarray(chunk.samples, dtype=np.float32)
            if samples.ndim == 2:
                samples = np.mean(samples, axis=1).astype(np.float32, copy=False)
            features = extractor.process_float_audio(samples, start_time_sec=float(chunk.start_time_sec))
            for item in features:
                frames.append(
                    ReferenceAudioFrameFeatures(
                        time_sec=float(item.observed_at_sec),
                        envelope=float(item.envelope),
                        onset_strength=float(item.onset_strength),
                        voiced_ratio=float(item.voiced_ratio),
                        band_energy=list(item.band_energy),
                        embedding=list(item.embedding),
                    )
                )
            extractor.reset()

        boundaries = self._build_boundaries(
            frames=frames,
            reference_map=reference_map,
            segment_records=segment_records,
        )

        token_time_hints_sec = self._build_token_time_hints(reference_map=reference_map)
        token_templates = self._build_token_templates(
            frames=frames,
            reference_map=reference_map,
            segment_records=segment_records,
        )
        total_duration_sec = float(getattr(reference_map, "total_duration_sec", 0.0))

        return ReferenceAudioFeatures(
            lesson_id=str(lesson_id),
            frame_hop_sec=self.hop_sec,
            frame_size_sec=self.frame_size_sec,
            sample_rate=sample_rate,
            frames=frames,
            boundaries=boundaries,
            token_time_hints_sec=token_time_hints_sec,
            token_acoustic_templates=token_templates,
            total_duration_sec=total_duration_sec,
        )

    def _build_boundaries(self, *, frames, reference_map, segment_records: list[SegmentTimelineRecord] | None) -> list[ReferenceBoundaryHint]:
        boundaries: list[ReferenceBoundaryHint] = []

        if segment_records:
            for seg in segment_records:
                start_sec = self._segment_effective_start(seg)
                end_sec = self._segment_effective_end(seg)
                boundaries.append(
                    ReferenceBoundaryHint(
                        time_sec=float(start_sec),
                        kind="segment_start",
                        weight=1.25,
                    )
                )
                if end_sec > start_sec:
                    boundaries.append(
                        ReferenceBoundaryHint(
                            time_sec=float(end_sec),
                            kind="segment_end",
                            weight=0.95,
                        )
                    )

        seen_clause_ids: set[int] = set()
        seen_sentence_ids: set[int] = set()
        for token in getattr(reference_map, "tokens", []):
            clause_id = int(getattr(token, "clause_id", -1))
            sentence_id = int(getattr(token, "sentence_id", -1))
            t_start = float(getattr(token, "t_start", 0.0))
            if clause_id >= 0 and clause_id not in seen_clause_ids:
                boundaries.append(ReferenceBoundaryHint(time_sec=t_start, kind="clause", weight=1.0))
                seen_clause_ids.add(clause_id)
            if sentence_id >= 0 and sentence_id not in seen_sentence_ids:
                boundaries.append(ReferenceBoundaryHint(time_sec=t_start, kind="sentence", weight=1.2))
                seen_sentence_ids.add(sentence_id)

        if frames:
            onset_values = np.asarray([x.onset_strength for x in frames], dtype=np.float32)
            if onset_values.size >= 5:
                threshold = float(np.percentile(onset_values, 85))
                for idx in range(1, len(frames) - 1):
                    cur = frames[idx].onset_strength
                    if cur >= threshold and cur >= frames[idx - 1].onset_strength and cur >= frames[idx + 1].onset_strength:
                        boundaries.append(
                            ReferenceBoundaryHint(
                                time_sec=float(frames[idx].time_sec),
                                kind="peak",
                                weight=0.7,
                            )
                        )

        boundaries.sort(key=lambda x: (float(x.time_sec), str(x.kind), -float(x.weight)))
        deduped: list[ReferenceBoundaryHint] = []
        for item in boundaries:
            if deduped and abs(float(item.time_sec) - float(deduped[-1].time_sec)) <= 0.008 and item.kind == deduped[-1].kind:
                if item.weight > deduped[-1].weight:
                    deduped[-1] = item
            else:
                deduped.append(item)
        return deduped

    def _build_token_time_hints(self, *, reference_map) -> list[float]:
        return [float(getattr(t, "t_start", 0.0)) for t in getattr(reference_map, "tokens", [])]

    def _build_token_templates(
        self,
        *,
        frames: list[ReferenceAudioFrameFeatures],
        reference_map,
        segment_records: list[SegmentTimelineRecord] | None,
    ) -> list[ReferenceTokenAcousticTemplate]:
        if not frames:
            return []

        frame_times = np.asarray([f.time_sec for f in frames], dtype=np.float32)
        embeddings = (
            np.asarray([f.embedding for f in frames], dtype=np.float32)
            if frames[0].embedding
            else np.zeros((len(frames), 0), dtype=np.float32)
        )
        if embeddings.size == 0:
            return []

        token_windows = None
        if segment_records:
            token_windows = self._build_token_windows_from_segments(segment_records)

        templates: list[ReferenceTokenAcousticTemplate] = []
        for token in getattr(reference_map, "tokens", []):
            token_idx = int(getattr(token, "idx", len(templates)))
            t0, t1 = self._resolve_token_window(
                token=token,
                token_idx=token_idx,
                token_windows=token_windows,
            )
            mask = np.where((frame_times >= t0) & (frame_times <= t1))[0]
            if mask.size == 0:
                ref_t = float(getattr(token, "t_start", 0.0))
                idx = int(np.argmin(np.abs(frame_times - ref_t)))
                mask = np.asarray([idx], dtype=np.int32)

            emb = np.mean(embeddings[mask], axis=0)
            norm = float(np.linalg.norm(emb))
            if norm > 1e-6:
                emb = emb / norm

            templates.append(
                ReferenceTokenAcousticTemplate(
                    token_idx=token_idx,
                    time_sec=float(getattr(token, "t_start", 0.0)),
                    embedding=emb.astype(np.float32, copy=False).tolist(),
                )
            )
        return templates

    def _build_token_windows_from_segments(
        self,
        segment_records: list[SegmentTimelineRecord],
    ) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for seg in segment_records:
            base_start = self._segment_effective_start(seg)
            local_starts = [float(x) for x in seg.local_starts]
            local_ends = [float(x) for x in seg.local_ends]
            trim_head = float(seg.trim_head_sec or 0.0)
            trim_tail = float(seg.trim_tail_sec or 0.0)
            effective_seg_end = self._segment_effective_end(seg)

            for ls, le in zip(local_starts, local_ends, strict=True):
                t0 = max(base_start, base_start + max(0.0, ls - trim_head))
                t1 = max(t0, base_start + max(0.0, le - trim_head))
                if effective_seg_end > 0.0:
                    t0 = min(t0, effective_seg_end)
                    t1 = min(t1, effective_seg_end)
                if trim_tail > 0.0 and effective_seg_end <= 0.0:
                    t1 = max(t0, t1 - trim_tail)
                out.append((float(t0), float(t1)))
        return out

    def _resolve_token_window(
        self,
        *,
        token,
        token_idx: int,
        token_windows: list[tuple[float, float]] | None,
    ) -> tuple[float, float]:
        if token_windows and 0 <= token_idx < len(token_windows):
            t0, t1 = token_windows[token_idx]
            if t1 >= t0:
                return float(t0 - 0.015), float(t1 + 0.020)

        t0 = float(getattr(token, "t_start", 0.0)) - 0.03
        t1 = float(getattr(token, "t_end", t0 + 0.06)) + 0.03
        return t0, t1

    def _segment_effective_start(self, seg: SegmentTimelineRecord) -> float:
        if seg.assembled_start_sec is not None:
            return float(seg.assembled_start_sec)
        return float(seg.global_start_sec)

    def _segment_effective_end(self, seg: SegmentTimelineRecord) -> float:
        if seg.assembled_end_sec is not None:
            return float(seg.assembled_end_sec)
        if seg.local_ends:
            return float(seg.global_start_sec + max(float(x) for x in seg.local_ends))
        return float(seg.global_start_sec)