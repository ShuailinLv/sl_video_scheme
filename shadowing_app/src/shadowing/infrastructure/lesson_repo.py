from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import soundfile as sf

from shadowing.interfaces.repository import LessonRepository
from shadowing.types import AudioChunk, LessonManifest, RefToken, ReferenceMap


class FileLessonRepository(LessonRepository):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def save_manifest(self, manifest: LessonManifest) -> None:
        lesson_dir = self.base_dir / manifest.lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)

        path = lesson_dir / "lesson_manifest.json"
        path.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_manifest(self, lesson_id: str) -> LessonManifest:
        path = self.base_dir / lesson_id / "lesson_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return LessonManifest(**data)

    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str:
        lesson_dir = self.base_dir / lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)

        path = lesson_dir / "reference_map.json"
        path.write_text(
            json.dumps(asdict(ref_map), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)

    def load_reference_map(self, lesson_id: str) -> ReferenceMap:
        path = self.base_dir / lesson_id / "reference_map.json"
        data = json.loads(path.read_text(encoding="utf-8"))

        tokens = [RefToken(**token_data) for token_data in data["tokens"]]
        return ReferenceMap(
            lesson_id=data["lesson_id"],
            tokens=tokens,
            total_duration_sec=data["total_duration_sec"],
        )

    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]:
        manifest = self.load_manifest(lesson_id)

        chunks: list[AudioChunk] = []
        current_start_time = 0.0

        for idx, chunk_path_str in enumerate(manifest.chunk_paths):
            chunk_path = Path(chunk_path_str)

            if not chunk_path.is_absolute():
                chunk_path = (self.base_dir / lesson_id / chunk_path).resolve()

            samples, sr = sf.read(str(chunk_path), dtype="float32", always_2d=False)

            if samples.ndim == 1:
                channels = 1
                duration_sec = len(samples) / sr
            else:
                channels = samples.shape[1]
                duration_sec = samples.shape[0] / sr

            chunks.append(
                AudioChunk(
                    chunk_id=idx,
                    sample_rate=sr,
                    channels=channels,
                    samples=samples,
                    duration_sec=duration_sec,
                    start_time_sec=current_start_time,
                    path=str(chunk_path),
                )
            )

            current_start_time += duration_sec

        return chunks