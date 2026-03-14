from __future__ import annotations

from abc import ABC, abstractmethod

from shadowing.types import LessonManifest, ReferenceMap


class TTSProvider(ABC):
    @abstractmethod
    def synthesize_lesson(self, lesson_id: str, text: str, output_dir: str) -> tuple[LessonManifest, ReferenceMap]: ...