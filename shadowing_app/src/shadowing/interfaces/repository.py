from __future__ import annotations

from abc import ABC, abstractmethod

from shadowing.types import AudioChunk, LessonManifest, ReferenceMap


class LessonRepository(ABC):
    @abstractmethod
    def save_manifest(self, manifest: LessonManifest) -> None: ...

    @abstractmethod
    def load_manifest(self, lesson_id: str) -> LessonManifest: ...

    @abstractmethod
    def save_reference_map(self, lesson_id: str, ref_map: ReferenceMap) -> str: ...

    @abstractmethod
    def load_reference_map(self, lesson_id: str) -> ReferenceMap: ...

    @abstractmethod
    def load_audio_chunks(self, lesson_id: str) -> list[AudioChunk]: ...