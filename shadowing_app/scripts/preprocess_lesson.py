from __future__ import annotations

from pathlib import Path
from shadowing.preprocess.pipeline import LessonPreprocessPipeline
from shadowing.preprocess.providers.elevenlabs_tts import ElevenLabsTTSProvider
from shadowing.infrastructure.lesson_repo import FileLessonRepository


def main() -> None:
    lesson_id = "demo_lesson"
    text = Path("assets/lessons/demo_lesson/source.txt").read_text(encoding="utf-8")

    tts = ElevenLabsTTSProvider(
        api_key="YOUR_API_KEY",
        voice_id="YOUR_VOICE_ID",
        model_id="eleven_multilingual_v2",
    )
    repo = FileLessonRepository("assets/lessons")
    pipeline = LessonPreprocessPipeline(tts_provider=tts, repo=repo)
    pipeline.run(lesson_id=lesson_id, text=text, output_dir=f"assets/lessons/{lesson_id}")


if __name__ == "__main__":
    main()