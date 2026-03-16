from __future__ import annotations

import _bootstrap
import argparse
import json
import os
import re
from pathlib import Path

from shadowing.audio.reference_audio_analyzer import ReferenceAudioAnalyzer
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.infrastructure.lesson_repo import FileLessonRepository
from shadowing.preprocess.pipeline import LessonPreprocessPipeline
from shadowing.preprocess.providers.elevenlabs_tts import ElevenLabsTTSProvider
from shadowing.preprocess.reference_audio_pipeline import ReferenceAudioFeaturePipeline


def slugify_filename_stem(stem: str) -> str:
    stem = str(stem or "").strip()
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def read_text_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Text file is empty: {path}")
    return text


def validate_elevenlabs_args(args) -> None:
    if not str(args.elevenlabs_api_key or "").strip():
        raise ValueError(
            "Missing ElevenLabs API key. "
            "Please provide --elevenlabs-api-key or set ELEVENLABS_API_KEY."
        )
    if not str(args.voice_id or "").strip():
        raise ValueError(
            "Missing ElevenLabs voice_id. "
            "Please provide --voice-id or set ELEVENLABS_VOICE_ID."
        )
    if not str(args.model_id or "").strip():
        raise ValueError(
            "Missing ElevenLabs model_id. "
            "Please provide --model-id or set ELEVENLABS_MODEL_ID."
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preprocess a lesson into runtime-ready shadowing assets."
    )

    parser.add_argument(
        "--text-file",
        type=str,
        required=True,
        help="Path to lesson text file.",
    )
    parser.add_argument(
        "--lesson-id",
        type=str,
        default="",
        help="Optional explicit lesson_id. Defaults to slugified text filename stem.",
    )
    parser.add_argument(
        "--lesson-base-dir",
        type=str,
        default="assets/lessons",
        help="Base directory for lesson assets.",
    )

    parser.add_argument(
        "--elevenlabs-api-key",
        type=str,
        default=os.getenv("ELEVENLABS_API_KEY", ""),
        help="ElevenLabs API key, default from ELEVENLABS_API_KEY.",
    )
    parser.add_argument(
        "--voice-id",
        type=str,
        default=os.getenv("ELEVENLABS_VOICE_ID", ""),
        help="ElevenLabs voice_id, default from ELEVENLABS_VOICE_ID.",
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default=os.getenv("ELEVENLABS_MODEL_ID", ""),
        help="ElevenLabs model_id, default from ELEVENLABS_MODEL_ID.",
    )
    parser.add_argument(
        "--output-format",
        type=str,
        default=os.getenv("ELEVENLABS_OUTPUT_FORMAT", "pcm_44100"),
        help="ElevenLabs output format, e.g. pcm_44100.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=120.0,
        help="HTTP timeout for ElevenLabs requests.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2025,
        help="Seed for ElevenLabs generation consistency.",
    )

    parser.add_argument(
        "--target-chars-per-segment",
        type=int,
        default=28,
        help="Preferred chars per segment.",
    )
    parser.add_argument(
        "--hard-max-chars-per-segment",
        type=int,
        default=54,
        help="Hard max chars per segment.",
    )
    parser.add_argument(
        "--min-chars-per-segment",
        type=int,
        default=6,
        help="Min chars per segment.",
    )
    parser.add_argument(
        "--context-window-segments",
        type=int,
        default=2,
        help="Neighbor segment count used for continuity context.",
    )
    parser.add_argument(
        "--continuity-context-chars-prev",
        type=int,
        default=100,
        help="Previous context max chars passed into TTS.",
    )
    parser.add_argument(
        "--continuity-context-chars-next",
        type=int,
        default=100,
        help="Next context max chars passed into TTS.",
    )
    parser.add_argument(
        "--max-retries-per-segment",
        type=int,
        default=2,
        help="Max retries per segment for ElevenLabs requests.",
    )

    parser.add_argument(
        "--disable-assembler",
        action="store_true",
        help="Disable audio assembler. Not recommended.",
    )
    parser.add_argument(
        "--assembled-reference-filename",
        type=str,
        default="assembled_reference.wav",
        help="Filename for assembled reference audio.",
    )
    parser.add_argument(
        "--silence-rms-threshold",
        type=float,
        default=0.0035,
        help="Silence threshold for segment trim.",
    )
    parser.add_argument(
        "--min-silence-keep-sec",
        type=float,
        default=0.035,
        help="Keep a little silence at segment boundaries.",
    )
    parser.add_argument(
        "--max-trim-head-sec",
        type=float,
        default=0.180,
        help="Max head trim per segment.",
    )
    parser.add_argument(
        "--max-trim-tail-sec",
        type=float,
        default=0.220,
        help="Max tail trim per segment.",
    )
    parser.add_argument(
        "--crossfade-sec",
        type=float,
        default=0.025,
        help="Crossfade between adjacent segments.",
    )
    parser.add_argument(
        "--write-trimmed-segment-files",
        action="store_true",
        help="Write per-segment trimmed wavs for inspection.",
    )
    parser.add_argument(
        "--trimmed-segments-dirname",
        type=str,
        default="assembled_segments",
        help="Dir name for optional trimmed segment wavs.",
    )

    parser.add_argument(
        "--reference-frame-size-sec",
        type=float,
        default=0.025,
        help="Reference feature frame size.",
    )
    parser.add_argument(
        "--reference-hop-sec",
        type=float,
        default=0.010,
        help="Reference feature hop size.",
    )
    parser.add_argument(
        "--reference-n-bands",
        type=int,
        default=6,
        help="Reference feature band count.",
    )

    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print a short JSON summary at the end.",
    )

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    validate_elevenlabs_args(args)

    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")

    lesson_text = read_text_file(text_path)

    lesson_id = str(args.lesson_id or "").strip()
    if not lesson_id:
        lesson_id = slugify_filename_stem(text_path.stem)

    lesson_base_dir = Path(args.lesson_base_dir).expanduser().resolve()
    lesson_output_dir = lesson_base_dir / lesson_id
    lesson_output_dir.mkdir(parents=True, exist_ok=True)

    repo = FileLessonRepository(str(lesson_base_dir))

    tts_provider = ElevenLabsTTSProvider(
        api_key=str(args.elevenlabs_api_key).strip(),
        voice_id=str(args.voice_id).strip(),
        model_id=str(args.model_id).strip(),
        output_format=str(args.output_format).strip(),
        timeout_sec=float(args.timeout_sec),
        seed=int(args.seed),
        continuity_context_chars_prev=int(args.continuity_context_chars_prev),
        continuity_context_chars_next=int(args.continuity_context_chars_next),
        target_chars_per_segment=int(args.target_chars_per_segment),
        hard_max_chars_per_segment=int(args.hard_max_chars_per_segment),
        min_chars_per_segment=int(args.min_chars_per_segment),
        context_window_segments=int(args.context_window_segments),
        max_retries_per_segment=int(args.max_retries_per_segment),
        assemble_reference_audio=not bool(args.disable_assembler),
        assembled_reference_filename=str(args.assembled_reference_filename),
        silence_rms_threshold=float(args.silence_rms_threshold),
        min_silence_keep_sec=float(args.min_silence_keep_sec),
        max_trim_head_sec=float(args.max_trim_head_sec),
        max_trim_tail_sec=float(args.max_trim_tail_sec),
        crossfade_sec=float(args.crossfade_sec),
        write_trimmed_segment_files=bool(args.write_trimmed_segment_files),
        trimmed_segments_dirname=str(args.trimmed_segments_dirname),
    )

    preprocess_pipeline = LessonPreprocessPipeline(
        tts_provider=tts_provider,
        repo=repo,
    )
    preprocess_pipeline.run(
        lesson_id=lesson_id,
        text=lesson_text,
        output_dir=str(lesson_output_dir),
    )

    feature_store = ReferenceAudioStore(str(lesson_base_dir))
    analyzer = ReferenceAudioAnalyzer(
        frame_size_sec=float(args.reference_frame_size_sec),
        hop_sec=float(args.reference_hop_sec),
        n_bands=int(args.reference_n_bands),
    )
    reference_audio_pipeline = ReferenceAudioFeaturePipeline(
        repo=repo,
        feature_store=feature_store,
        analyzer=analyzer,
    )
    feature_path = reference_audio_pipeline.run(lesson_id)

    if args.print_summary:
        summary = {
            "lesson_id": lesson_id,
            "lesson_dir": str(lesson_output_dir),
            "lesson_manifest": str(lesson_output_dir / "lesson_manifest.json"),
            "reference_map": str(lesson_output_dir / "reference_map.json"),
            "segments_manifest": str(lesson_output_dir / "segments_manifest.json"),
            "assembled_reference": str(lesson_output_dir / str(args.assembled_reference_filename)),
            "reference_audio_features": str(feature_path),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()