from __future__ import annotations

import json
from pathlib import Path
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import LessonManifest, ReferenceMap, AudioChunk


class FileLessonRepository(LessonRepository):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def save_manifest(self, manifest: LessonManifest) -> None:
        lesson_dir = self.base_dir / manifest.lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)
        path = lesson_dir / "lesson_manifest.json"
        path.write_text(json.dumps(manifest.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_manifest(self, lesson_id: str) -> LessonManifest:
        path = self.base_dir / lesson_id / "lesson_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return LessonManifest(**data)

    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str:
        lesson_dir = self.base_dir / lesson_id
        lesson_dir.mkdir(parents=True, exist_ok=True)
        path = lesson_dir / "reference_map.json"

        payload = {
            "lesson_id": ref_map.lesson_id,
            "total_duration_sec": ref_map.total_duration_sec,
            "tokens": [token.__dict__ for token in ref_map.tokens],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def load_reference_map(self, lesson_id: str) -> ReferenceMap:
        # TODO: 从 json 反序列化
        raise NotImplementedError

    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]:
        # TODO: 从 chunks/*.wav 加载 numpy 数据
        raise NotImplementedError