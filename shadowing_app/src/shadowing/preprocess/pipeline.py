from __future__ import annotations

from pathlib import Path

from shadowing.interfaces.repository import LessonRepository
from shadowing.interfaces.tts import TTSProvider


class LessonPreprocessPipeline:
    def __init__(self, tts_provider: TTSProvider, repo: LessonRepository) -> None:
        self.tts_provider = tts_provider
        self.repo = repo

    def run(self, lesson_id: str, text: str, output_dir: str) -> None:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        manifest, ref_map = self.tts_provider.synthesize_lesson(
            lesson_id=lesson_id,
            text=text,
            output_dir=str(output_path),
        )

        self.repo.save_manifest(manifest)
        self.repo.save_reference_map(lesson_id, ref_map)