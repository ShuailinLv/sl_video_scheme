from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from shadowing.preprocess.reference_builder import SegmentTimelineRecord
from shadowing.types import AudioChunk


@dataclass(slots=True)
class AssembledReferenceBundle:
    audio_chunk: AudioChunk
    segment_records: list[SegmentTimelineRecord]
    assembled_audio_path: str
    segments_manifest_path: str


class AssembledReferenceLoader:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def exists(self, lesson_id: str) -> bool:
        lesson_dir = self.base_dir / lesson_id
        assembled_audio = lesson_dir / "assembled_reference.wav"
        segments_manifest = lesson_dir / "segments_manifest.json"
        return assembled_audio.exists() and segments_manifest.exists()

    def load(self, lesson_id: str) -> AssembledReferenceBundle:
        lesson_dir = self.base_dir / lesson_id
        assembled_audio = lesson_dir / "assembled_reference.wav"
        segments_manifest = lesson_dir / "segments_manifest.json"

        if not assembled_audio.exists():
            raise FileNotFoundError(f"assembled_reference.wav not found: {assembled_audio}")
        if not segments_manifest.exists():
            raise FileNotFoundError(f"segments_manifest.json not found: {segments_manifest}")

        data = json.loads(segments_manifest.read_text(encoding="utf-8"))
        raw_segments = data.get("segments", [])
        segment_records = [self._coerce_segment_record(x, i) for i, x in enumerate(raw_segments)]

        samples, sr = sf.read(str(assembled_audio), dtype="float32", always_2d=False)
        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim == 1:
            channels = 1
            duration_sec = float(arr.shape[0]) / float(sr)
        else:
            channels = int(arr.shape[1])
            duration_sec = float(arr.shape[0]) / float(sr)

        audio_chunk = AudioChunk(
            chunk_id=0,
            sample_rate=int(sr),
            channels=channels,
            samples=arr,
            duration_sec=float(duration_sec),
            start_time_sec=0.0,
            path=str(assembled_audio),
        )

        return AssembledReferenceBundle(
            audio_chunk=audio_chunk,
            segment_records=segment_records,
            assembled_audio_path=str(assembled_audio),
            segments_manifest_path=str(segments_manifest),
        )

    def _coerce_segment_record(self, raw: dict, fallback_idx: int) -> SegmentTimelineRecord:
        chars = raw.get("chars", [])
        pinyins = raw.get("pinyins", [])
        local_starts = raw.get("local_starts", [])
        local_ends = raw.get("local_ends", [])

        return SegmentTimelineRecord(
            segment_id=int(raw.get("segment_id", fallback_idx)),
            text=str(raw.get("text", "")),
            chars=[str(x) for x in chars],
            pinyins=[str(x or "") for x in pinyins],
            local_starts=[float(x) for x in local_starts],
            local_ends=[float(x) for x in local_ends],
            global_start_sec=float(raw.get("global_start_sec", 0.0)),
            sentence_id=int(raw.get("sentence_id", 0)),
            clause_id=int(raw.get("clause_id", fallback_idx)),
            trim_head_sec=float(raw.get("trim_head_sec", 0.0) or 0.0),
            trim_tail_sec=float(raw.get("trim_tail_sec", 0.0) or 0.0),
            assembled_start_sec=(
                None if raw.get("assembled_start_sec") is None else float(raw.get("assembled_start_sec"))
            ),
            assembled_end_sec=(
                None if raw.get("assembled_end_sec") is None else float(raw.get("assembled_end_sec"))
            ),
        )