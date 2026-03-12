from __future__ import annotations

from pathlib import Path
from shadowing.interfaces.tts import TTSProvider
from shadowing.types import LessonManifest, ReferenceMap


class ElevenLabsTTSProvider(TTSProvider):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    def synthesize_lesson(
        self,
        lesson_id: str,
        text: str,
        output_dir: str,
    ) -> tuple[LessonManifest, ReferenceMap]:
        """
        TODO:
        1. 切分 text -> clauses
        2. 调 ElevenLabs with timestamps
        3. 保存 chunk wav
        4. 汇总 reference map
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        raise NotImplementedError