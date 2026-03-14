from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import os
import re
import shutil
from pathlib import Path

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.preprocess.pipeline import LessonPreprocessPipeline
from shadowing.preprocess.providers.elevenlabs_tts import ElevenLabsTTSProvider


DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "pcm_44100"


def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r'[\\/:\\*\\?"<>\\|]+', "_", stem)
    stem = re.sub(r"\\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def lesson_assets_exist(lesson_dir: Path) -> tuple[bool, list[str]]:
    manifest = lesson_dir / "lesson_manifest.json"
    ref_map = lesson_dir / "reference_map.json"
    chunks_dir = lesson_dir / "chunks"
    missing: list[str] = []
    if not manifest.exists():
        missing.append(str(manifest))
    if not ref_map.exists():
        missing.append(str(ref_map))
    if not chunks_dir.exists():
        missing.append(str(chunks_dir))
    else:
        has_audio = any(chunks_dir.glob("*.wav")) or any(chunks_dir.glob("*.mp3"))
        if not has_audio:
            missing.append(f"{chunks_dir} (no audio files found)")
    return len(missing) == 0, missing


def same_source_text(lesson_dir: Path, current_text: str) -> bool:
    source_path = lesson_dir / "source.txt"
    return source_path.exists() and source_path.read_text(encoding="utf-8").strip() == current_text.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess a local txt speech file into lesson assets using ElevenLabs.")
    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--api-key", type=str, default=os.getenv("ELEVENLABS_API_KEY", ""))
    parser.add_argument("--voice-id", type=str, default=DEFAULT_VOICE_ID)
    parser.add_argument("--model-id", type=str, default=DEFAULT_MODEL_ID)
    parser.add_argument("--output-format", type=str, default=DEFAULT_OUTPUT_FORMAT)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    lesson_text = text_path.read_text(encoding="utf-8").strip()
    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    output_dir = lesson_base_dir / lesson_id
    output_dir.mkdir(parents=True, exist_ok=True)

    assets_ok, missing = lesson_assets_exist(output_dir)
    text_same = same_source_text(output_dir, lesson_text)
    if assets_ok and text_same and not args.force:
        print("Local lesson assets already exist and source text is unchanged. Skip ElevenLabs preprocessing.")
        return

    if not args.api_key:
        raise ValueError("Missing ElevenLabs API key. Pass --api-key or set ELEVENLABS_API_KEY.")

    source_copy_path = output_dir / "source.txt"
    if source_copy_path.resolve() != text_path:
        shutil.copyfile(text_path, source_copy_path)

    tts = ElevenLabsTTSProvider(
        api_key=args.api_key,
        voice_id=args.voice_id,
        model_id=args.model_id,
        output_format=args.output_format,
    )
    repo = FileLessonRepository(str(lesson_base_dir))
    LessonPreprocessPipeline(tts_provider=tts, repo=repo).run(
        lesson_id=lesson_id,
        text=lesson_text,
        output_dir=str(output_dir),
    )
    print(f"Preprocess completed: {output_dir}")
    if missing:
        print("Previous missing items:")
        for item in missing:
            print(f"  - {item}")


if __name__ == "__main__":
    main()