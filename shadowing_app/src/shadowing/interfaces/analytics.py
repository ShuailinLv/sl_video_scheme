from __future__ import annotations

from abc import ABC, abstractmethod


class AnalyticsProvider(ABC):
    @abstractmethod
    def analyze_session(
        self,
        lesson_text: str,
        audio_path: str,
        output_dir: str,
    ) -> dict:
        raise NotImplementedError