from __future__ import annotations
import _bootstrap  # noqa: F401

import argparse
import json
import os
import re
from pathlib import Path

from shadowing.bootstrap import build_runtime
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider


DEFAULT_TEXT_FILE = r"D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"


def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r'[\\/:\*\?"<>\|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def validate_lesson_assets(lesson_dir: Path) -> None:
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

    if missing:
        msg = "\n".join(missing)
        raise FileNotFoundError(
            "Lesson assets not found. Please run preprocess first.\n"
            f"Missing:\n{msg}"
        )


def load_manifest(lesson_dir: Path) -> dict:
    manifest_path = lesson_dir / "lesson_manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_recording_config(
    manual_device: int | None,
    manual_samplerate: int | None,
) -> dict:
    """
    录音设备选择策略：
    1. 如果用户显式传了 --input-device，则优先使用该设备
    2. 否则走自动探测 pick_working_input_config()
    """
    from shadowing.realtime.capture.device_utils import pick_working_input_config

    if manual_device is not None:
        return {
            "device": manual_device,
            "samplerate": int(manual_samplerate or 48000),
            "channels": 1,
            "dtype": "float32",
        }

    rec_cfg = pick_working_input_config()
    if rec_cfg is None:
        raise RuntimeError(
            "No working input device config found. "
            "Try specifying --input-device manually, e.g. --input-device 9"
        )

    if manual_samplerate is not None:
        rec_cfg["samplerate"] = int(manual_samplerate)

    return rec_cfg


def collect_sherpa_paths() -> dict:
    return {
        "tokens": os.getenv("SHERPA_TOKENS", ""),
        "encoder": os.getenv("SHERPA_ENCODER", ""),
        "decoder": os.getenv("SHERPA_DECODER", ""),
        "joiner": os.getenv("SHERPA_JOINER", ""),
    }


def validate_sherpa_paths(paths: dict) -> None:
    missing_keys: list[str] = []
    missing_files: list[str] = []

    for key in ("tokens", "encoder", "decoder", "joiner"):
        value = (paths.get(key) or "").strip()
        if not value:
            missing_keys.append(key)
            continue
        if not Path(value).expanduser().exists():
            missing_files.append(f"{key}: {value}")

    if missing_keys or missing_files:
        parts: list[str] = []
        if missing_keys:
            parts.append(
                "Missing sherpa env vars: "
                + ", ".join(
                    {
                        "tokens": "SHERPA_TOKENS",
                        "encoder": "SHERPA_ENCODER",
                        "decoder": "SHERPA_DECODER",
                        "joiner": "SHERPA_JOINER",
                    }[k]
                    for k in missing_keys
                )
            )
        if missing_files:
            parts.append("Non-existent sherpa files:\n" + "\n".join(missing_files))

        raise FileNotFoundError(
            "Sherpa model configuration is invalid.\n" + "\n".join(parts)
        )


def build_config(
    lesson_base_dir: str,
    input_device: int | None,
    input_samplerate: int,
    asr_mode: str,
    bluetooth_offset_sec: float,
    debug: bool,
    playback_sample_rate: int,
    pure_playback: bool,
    ducking_only: bool,
    disable_seek: bool,
    disable_hold: bool,
    sherpa_paths: dict,
) -> dict:
    return {
        "lesson_base_dir": lesson_base_dir,
        "playback": {
            "sample_rate": playback_sample_rate,
            "device": None,
            "bluetooth_output_offset_sec": bluetooth_offset_sec,
        },
        "capture": {
            "device_sample_rate": input_samplerate,
            "target_sample_rate": 16000,
            "device": input_device,
            "prefer_soundcard_on_windows": True,
        },
        "asr": {
            "mode": asr_mode,
            "hotwords": "",
            "tokens": sherpa_paths["tokens"],
            "encoder": sherpa_paths["encoder"],
            "decoder": sherpa_paths["decoder"],
            "joiner": sherpa_paths["joiner"],
            "num_threads": 2,
            "provider": "cpu",
            "feature_dim": 80,
            "decoding_method": "greedy_search",
            "hotwords_score": 1.5,
            "rule1_min_trailing_silence": 10.0,
            "rule2_min_trailing_silence": 10.0,
            "rule3_min_utterance_length": 60.0,
        },
        "debug": {
            "enabled": debug,
            "heartbeat_sec": 1.0,
            "print_asr": True,
            "print_alignment": True,
            "print_decision": True,
            "print_player_status": True,
            "print_reference_head": True,
        },
        "runtime": {
            "pure_playback": pure_playback,
        },
        "control": {
            "ducking_only": ducking_only,
            "disable_seek": disable_seek,
            "disable_hold": disable_hold,
        },
    }


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
        help="ASR mode.",
    )
    parser.add_argument(
        "--bluetooth-offset-sec",
        type=float,
        default=0.18,
        help="Estimated Bluetooth playback offset.",
    )
    parser.add_argument(
        "--input-device",
        type=int,
        default=None,
        help="Manually specify recording input device index. "
             "Recommended on Windows when auto-picked device fails.",
    )
    parser.add_argument(
        "--input-samplerate",
        type=int,
        default=None,
        help="Override recording input sample rate. "
             "Useful if a device fails at its default rate.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable runtime debug logs.",
    )
    parser.add_argument(
        "--pure-playback",
        action="store_true",
        help="Pure playback debug mode: disable controller intervention and force gain=1.0.",
    )
    parser.add_argument(
        "--ducking-only",
        action="store_true",
        help="Only apply ducking/gain control. Disable resume/hold/seek actions.",
    )
    parser.add_argument(
        "--disable-seek",
        action="store_true",
        help="Disable SEEK decisions.",
    )
    parser.add_argument(
        "--disable-hold",
        action="store_true",
        help="Disable HOLD decisions.",
    )

    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")

    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    lesson_dir = lesson_base_dir / lesson_id

    validate_lesson_assets(lesson_dir)
    manifest = load_manifest(lesson_dir)
    playback_sample_rate = int(manifest["sample_rate_out"])

    rec_cfg = resolve_recording_config(
        manual_device=args.input_device,
        manual_samplerate=args.input_samplerate,
    )

    sherpa_paths = collect_sherpa_paths()

    # 纯播放模式不需要 recorder / sherpa 真的工作
    if args.asr == "sherpa" and not args.pure_playback:
        validate_sherpa_paths(sherpa_paths)

    config = build_config(
        lesson_base_dir=str(lesson_base_dir),
        input_device=rec_cfg["device"],
        input_samplerate=int(rec_cfg["samplerate"]),
        asr_mode=args.asr,
        bluetooth_offset_sec=args.bluetooth_offset_sec,
        debug=args.debug,
        playback_sample_rate=playback_sample_rate,
        pure_playback=args.pure_playback,
        ducking_only=args.ducking_only,
        disable_seek=args.disable_seek,
        disable_hold=args.disable_hold,
        sherpa_paths=sherpa_paths,
    )

    print("=== Run config ===")
    print(f"text file       : {text_path}")
    print(f"lesson id       : {lesson_id}")
    print(f"lesson dir      : {lesson_dir}")
    print(f"input device    : {rec_cfg['device']}")
    print(f"input sr        : {rec_cfg['samplerate']}")
    print(f"playback sr     : {playback_sample_rate}")
    print(f"asr mode        : {args.asr}")
    print(f"bt offset sec   : {args.bluetooth_offset_sec}")
    print(f"debug           : {args.debug}")
    print(f"pure playback   : {args.pure_playback}")
    print(f"ducking only    : {args.ducking_only}")
    print(f"disable seek    : {args.disable_seek}")
    print(f"disable hold    : {args.disable_hold}")
    print()

    runtime = build_runtime(config)

    if args.asr == "fake" and not args.pure_playback:
        lesson_text = text_path.read_text(encoding="utf-8").strip()
        runtime.orchestrator.asr = FakeASRProvider.from_reference_text(
            reference_text=lesson_text,
            chars_per_step=4,
            step_interval_sec=0.25,
            lag_sec=0.4,
            tail_final=True,
        )

    if hasattr(runtime.orchestrator, "configure_debug"):
        runtime.orchestrator.configure_debug(config["debug"])

    print("Starting shadowing runtime...")
    print("Press Ctrl+C to stop.")
    print()

    try:
        runtime.run(lesson_id)
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()