from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from shadowing.audio.reference_audio_features import (
    ReferenceAudioFeatures,
    ReferenceAudioFrameFeatures,
    ReferenceBoundaryHint,
    ReferenceTokenAcousticTemplate,
)


class ReferenceAudioStore:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def _path_for(self, lesson_id: str) -> Path:
        return self.base_dir / lesson_id / "reference_audio_features.json"

    def save(self, lesson_id: str, features: ReferenceAudioFeatures) -> str:
        path = self._path_for(lesson_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(features), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def exists(self, lesson_id: str) -> bool:
        return self._path_for(lesson_id).exists()

    def load(self, lesson_id: str) -> ReferenceAudioFeatures:
        path = self._path_for(lesson_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        frames = [ReferenceAudioFrameFeatures(**item) for item in data.get("frames", [])]
        boundaries = [ReferenceBoundaryHint(**item) for item in data.get("boundaries", [])]
        token_templates = [ReferenceTokenAcousticTemplate(**item) for item in data.get("token_acoustic_templates", [])]
        return ReferenceAudioFeatures(
            lesson_id=str(data["lesson_id"]),
            frame_hop_sec=float(data.get("frame_hop_sec", 0.010)),
            frame_size_sec=float(data.get("frame_size_sec", 0.025)),
            sample_rate=int(data.get("sample_rate", 16000)),
            frames=frames,
            boundaries=boundaries,
            token_time_hints_sec=[float(x) for x in data.get("token_time_hints_sec", [])],
            token_acoustic_templates=token_templates,
            total_duration_sec=float(data.get("total_duration_sec", 0.0)),
        )
