from __future__ import annotations

from shadowing.interfaces.analytics import AnalyticsProvider


class ElevenLabsScribeProvider(AnalyticsProvider):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def analyze_session(self, lesson_text: str, audio_path: str, output_dir: str) -> dict:
        raise NotImplementedError("Wire your preferred ElevenLabs Scribe batch endpoint here.")