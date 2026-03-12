import _bootstrap  # noqa: F401

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from shadowing.bootstrap import build_runtime
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig
from shadowing.realtime.capture.device_utils import pick_working_input_config


# 你本地改这个默认路径即可
DEFAULT_TEXT_FILE = r"D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"


def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r"[\\/:\*\?\"<>\|]+", "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def build_config(
    lesson_base_dir: str,
    input_device: int | None,
    input_samplerate: int,
    asr_mode: str,
) -> dict:
    """
    这里统一生成 runtime 配置。
    默认 playback 先用 48k，capture 转 16k。
    """
    config = {
        "lesson_base_dir": lesson_base_dir,
        "playback": {
            "sample_rate": 48000,
            "device": None,  # 输出设备后面你可以再单独做选择器
            "bluetooth_output_offset_sec": 0.18,
        },
        "capture": {
            "device_sample_rate": input_samplerate,
            "target_sample_rate": 16000,
            "device": input_device,
        },
        "asr": {
            "mode": asr_mode,
            "hotwords": "",
            # sherpa 需要时再补
            "tokens": os.getenv("SHERPA_TOKENS", ""),
            "encoder": os.getenv("SHERPA_ENCODER", ""),
            "decoder": os.getenv("SHERPA_DECODER", ""),
            "joiner": os.getenv("SHERPA_JOINER", ""),
            "num_threads": 2,
            "provider": "cpu",
            "feature_dim": 80,
            "decoding_method": "greedy_search",
            "hotwords_score": 1.5,
            "rule1_min_trailing_silence": 10.0,
            "rule2_min_trailing_silence": 10.0,
            "rule3_min_utterance_length": 60.0,
        },
    }
    return config


def validate_lesson_assets(lesson_dir: Path) -> None:
    manifest = lesson_dir / "lesson_manifest.json"
    ref_map = lesson_dir / "reference_map.json"
    chunks_dir = lesson_dir / "chunks"

    missing = []
    if not manifest.exists():
        missing.append(str(manifest))
    if not ref_map.exists():
        missing.append(str(ref_map))
    if not chunks_dir.exists():
        missing.append(str(chunks_dir))

    if missing:
        msg = "\n".join(missing)
        raise FileNotFoundError(
            "Lesson assets not found. Please run preprocess first.\n"
            f"Missing:\n{msg}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the shadowing app for a local txt speech lesson."
    )
    parser.add_argument(
        "--text-file",
        type=str,
        default=DEFAULT_TEXT_FILE,
        help="Path to the original txt file. Lesson id is derived from the file name.",
    )
    parser.add_argument(
        "--lesson-base-dir",
        type=str,
        default="assets/lessons",
        help="Base dir where preprocessed lesson assets are stored.",
    )
    parser.add_argument(
        "--asr",
        type=str,
        default="fake",
        choices=["fake", "sherpa"],
        help="ASR mode. Use fake first to smoke-test the whole pipeline; switch to sherpa later.",
    )
    parser.add_argument(
        "--fake-chars-per-sec",
        type=float,
        default=4.5,
        help="Only used in fake ASR mode.",
    )
    parser.add_argument(
        "--bluetooth-offset-sec",
        type=float,
        default=0.18,
        help="Estimated Bluetooth playback offset.",
    )

    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")

    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    lesson_dir = lesson_base_dir / lesson_id

    validate_lesson_assets(lesson_dir)

    rec_cfg = pick_working_input_config()
    if rec_cfg is None:
        raise RuntimeError("No working input device config found.")

    config = build_config(
        lesson_base_dir=str(lesson_base_dir),
        input_device=rec_cfg["device"],
        input_samplerate=rec_cfg["samplerate"],
        asr_mode=args.asr,
    )
    config["playback"]["bluetooth_output_offset_sec"] = args.bluetooth_offset_sec

    print("=== Run config ===")
    print(f"text file     : {text_path}")
    print(f"lesson id     : {lesson_id}")
    print(f"lesson dir    : {lesson_dir}")
    print(f"input device  : {rec_cfg['device']}")
    print(f"input sr      : {rec_cfg['samplerate']}")
    print(f"asr mode      : {args.asr}")
    print(f"bt offset sec : {args.bluetooth_offset_sec}")
    print()

    runtime = build_runtime(config)

    # 为了让你现在就能跑，默认用 FakeASR 替换掉 runtime 里的 asr
    if args.asr == "fake":
        lesson_text = text_path.read_text(encoding="utf-8").strip()
        runtime.orchestrator.asr = FakeASRProvider(
            FakeAsrConfig(
                reference_text=lesson_text,
                chars_per_sec=args.fake_chars_per_sec,
                emit_partial_interval_sec=0.10,
                sample_rate=16000,
            )
        )

    # 如果你指定 sherpa，但路径没配，会在 provider.start() 那里报更明确的错
    print("Starting shadowing runtime...")
    print("Press Ctrl+C to stop.")
    print()

    try:
        runtime.run(lesson_id)
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()