from __future__ import annotations
import numpy as np
from shadowing.audio.frame_feature_extractor import FrameFeatureExtractor
from shadowing.audio.reference_audio_features import (
    ReferenceAudioFeatures,
    ReferenceAudioFrameFeatures,
    ReferenceBoundaryHint,
    ReferenceTokenAcousticTemplate,
)


class ReferenceAudioAnalyzer:
    def __init__(self, frame_size_sec: float = 0.025, hop_sec: float = 0.010, n_bands: int = 6) -> None:
        self.frame_size_sec = float(frame_size_sec)
        self.hop_sec = float(hop_sec)
        self.n_bands = int(n_bands)

    def analyze(self, *, lesson_id: str, chunks: list, reference_map) -> ReferenceAudioFeatures:
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
        boundaries: list[ReferenceBoundaryHint] = []
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
                        boundaries.append(ReferenceBoundaryHint(time_sec=float(frames[idx].time_sec), kind="peak", weight=0.7))
        boundaries.sort(key=lambda x: (x.time_sec, x.kind))
        token_time_hints_sec = [float(getattr(t, "t_start", 0.0)) for t in getattr(reference_map, "tokens", [])]
        token_templates = self._build_token_templates(frames, reference_map)
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

    def _build_token_templates(self, frames: list[ReferenceAudioFrameFeatures], reference_map) -> list[ReferenceTokenAcousticTemplate]:
        if not frames:
            return []
        frame_times = np.asarray([f.time_sec for f in frames], dtype=np.float32)
        embeddings = np.asarray([f.embedding for f in frames], dtype=np.float32) if frames[0].embedding else np.zeros((len(frames), 0), dtype=np.float32)
        if embeddings.size == 0:
            return []
        templates: list[ReferenceTokenAcousticTemplate] = []
        for token in getattr(reference_map, "tokens", []):
            t0 = float(getattr(token, "t_start", 0.0)) - 0.03
            t1 = float(getattr(token, "t_end", t0 + 0.06)) + 0.03
            mask = np.where((frame_times >= t0) & (frame_times <= t1))[0]
            if mask.size == 0:
                idx = int(np.argmin(np.abs(frame_times - float(getattr(token, "t_start", 0.0)))))
                mask = np.asarray([idx], dtype=np.int32)
            emb = np.mean(embeddings[mask], axis=0)
            norm = float(np.linalg.norm(emb))
            if norm > 1e-6:
                emb = emb / norm
            templates.append(
                ReferenceTokenAcousticTemplate(
                    token_idx=int(getattr(token, "idx", len(templates))),
                    time_sec=float(getattr(token, "t_start", 0.0)),
                    embedding=emb.astype(np.float32, copy=False).tolist(),
                )
            )
        return templates
