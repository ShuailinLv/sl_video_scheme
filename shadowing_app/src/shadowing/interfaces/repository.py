from __future__ import annotations

from abc import ABC, abstractmethod
from shadowing.types import LessonManifest, ReferenceMap, AudioChunk


class LessonRepository(ABC):
    @abstractmethod
    def save_manifest(self, manifest: LessonManifest) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_manifest(self, lesson_id: str) -> LessonManifest:
        raise NotImplementedError

    @abstractmethod
    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str:
        raise NotImplementedError

    @abstractmethod
    def load_reference_map(self, lesson_id: str) -> ReferenceMap:
        raise NotImplementedError

    @abstractmethod
    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]:
        raise NotImplementedError