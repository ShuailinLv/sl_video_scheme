import _bootstrap  # noqa: F401

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path

from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.preprocess.pipeline import LessonPreprocessPipeline
from shadowing.preprocess.providers.elevenlabs_tts import ElevenLabsTTSProvider


# 你本地改这个默认路径即可
DEFAULT_TEXT_FILE = r"D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"

# 你也可以放进环境变量 ELEVENLABS_API_KEY
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


def slugify_filename_stem(stem: str) -> str:
    """
    把文件名转成安全目录名。
    中文会保留，空格和特殊字符会处理掉。
    """
    stem = stem.strip()
    stem = re.sub(r"[\\/:\*\?\"<>\|]+", "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def lesson_assets_exist(lesson_dir: Path) -> tuple[bool, list[str]]:
    """
    检查 lesson 资产是否完整。
    返回:
        (是否完整, 缺失项列表)
    """
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
    """
    比较当前 txt 内容是否与已缓存 source.txt 一致。
    """
    source_path = lesson_dir / "source.txt"
    if not source_path.exists():
        return False

    cached_text = source_path.read_text(encoding="utf-8").strip()
    return cached_text == current_text.strip()


def print_cache_status(
    lesson_dir: Path,
    assets_ok: bool,
    same_text: bool,
    force: bool,
) -> None:
    print("=== Cache check ===")
    print(f"lesson dir         : {lesson_dir}")
    print(f"assets complete    : {assets_ok}")
    print(f"source text same   : {same_text}")
    print(f"force rebuild      : {force}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess a local txt speech file into lesson assets using ElevenLabs."
    )
    parser.add_argument(
        "--text-file",
        type=str,
        default=DEFAULT_TEXT_FILE,
        help="Path to local txt file. Default points to a fake placeholder path; change it locally.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.getenv("ELEVENLABS_API_KEY", ""),
        help="ElevenLabs API key. Defaults to env ELEVENLABS_API_KEY.",
    )
    parser.add_argument(
        "--voice-id",
        type=str,
        default=DEFAULT_VOICE_ID,
        help="ElevenLabs voice id.",
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default=DEFAULT_MODEL_ID,
        help="ElevenLabs model id.",
    )
    parser.add_argument(
        "--lesson-base-dir",
        type=str,
        default="assets/lessons",
        help="Base output dir for generated lessons.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if local cached assets already exist.",
    )

    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")

    if text_path.suffix.lower() != ".txt":
        raise ValueError(f"Expected a .txt file, got: {text_path}")

    lesson_text = text_path.read_text(encoding="utf-8").strip()
    if not lesson_text:
        raise ValueError(f"Text file is empty: {text_path}")

    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    output_dir = lesson_base_dir / lesson_id
    output_dir.mkdir(parents=True, exist_ok=True)

    assets_ok, missing = lesson_assets_exist(output_dir)
    text_same = same_source_text(output_dir, lesson_text)

    print("=== Preprocess config ===")
    print(f"text file : {text_path}")
    print(f"lesson id : {lesson_id}")
    print(f"output dir: {output_dir}")
    print(f"voice id  : {args.voice_id}")
    print(f"model id  : {args.model_id}")
    print()

    print_cache_status(
        lesson_dir=output_dir,
        assets_ok=assets_ok,
        same_text=text_same,
        force=args.force,
    )

    if assets_ok and text_same and not args.force:
        print("Local lesson assets already exist and source text is unchanged.")
        print("Skip ElevenLabs preprocessing.")
        print()
        print("Next step:")
        print(f'python tools\\run_shadowing.py --text-file "{text_path}"')
        return

    if not args.api_key:
        raise ValueError(
            "Missing ElevenLabs API key. Pass --api-key or set ELEVENLABS_API_KEY."
        )

    if not assets_ok:
        print("Cache miss: lesson assets are incomplete.")
        if missing:
            print("Missing:")
            for item in missing:
                print(f"  - {item}")
        print()
    elif not text_same:
        print("Cache invalidated: source text has changed.")
        print()

    if args.force:
        print("Force rebuild enabled. ElevenLabs preprocessing will run.")
        print()

    # 先把当前 source.txt 更新到 lesson 目录，便于后续比较
    source_copy_path = output_dir / "source.txt"
    if source_copy_path.resolve() != text_path:
        shutil.copyfile(text_path, source_copy_path)

    tts = ElevenLabsTTSProvider(
        api_key=args.api_key,
        voice_id=args.voice_id,
        model_id=args.model_id,
    )
    repo = FileLessonRepository(str(lesson_base_dir))
    pipeline = LessonPreprocessPipeline(tts_provider=tts, repo=repo)

    pipeline.run(
        lesson_id=lesson_id,
        text=lesson_text,
        output_dir=str(output_dir),
    )

    print("Preprocess completed.")
    print(f"Generated lesson assets under: {output_dir}")
    print()
    print("Next step:")
    print(f'python tools\\run_shadowing.py --text-file "{text_path}"')


if __name__ == "__main__":
    main()