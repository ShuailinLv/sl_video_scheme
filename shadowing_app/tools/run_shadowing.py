from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import os
import re
from pathlib import Path

from shadowing.audio.bluetooth_preflight import (
    BluetoothPreflightConfig,
    run_bluetooth_duplex_preflight,
    should_run_bluetooth_preflight,
)
from shadowing.bootstrap import build_runtime
from shadowing.realtime.capture.device_utils import pick_working_input_config


def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"


def validate_lesson_assets(lesson_dir: Path) -> None:
    manifest = lesson_dir / "lesson_manifest.json"
    ref_map = lesson_dir / "reference_map.json"
    chunks_dir = lesson_dir / "chunks"

    missing: list[str] = []
    for p in (manifest, ref_map, chunks_dir):
        if not p.exists():
            missing.append(str(p))

    if missing:
        raise FileNotFoundError(
            "Lesson assets not found. Please run preprocess first.\n" + "\n".join(missing)
        )


def load_manifest(lesson_dir: Path) -> dict:
    return json.loads((lesson_dir / "lesson_manifest.json").read_text(encoding="utf-8"))


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
    env_map = {
        "tokens": "SHERPA_TOKENS",
        "encoder": "SHERPA_ENCODER",
        "decoder": "SHERPA_DECODER",
        "joiner": "SHERPA_JOINER",
    }

    for key in ("tokens", "encoder", "decoder", "joiner"):
        value = (paths.get(key) or "").strip()
        if not value:
            missing_keys.append(env_map[key])
            continue
        if not Path(value).expanduser().exists():
            missing_files.append(f"{key}: {value}")

    if missing_keys or missing_files:
        parts: list[str] = []
        if missing_keys:
            parts.append("Missing sherpa env vars: " + ", ".join(missing_keys))
        if missing_files:
            parts.append("Non-existent sherpa files:\n" + "\n".join(missing_files))
        raise FileNotFoundError("Sherpa model configuration is invalid.\n" + "\n".join(parts))


def build_config(
    lesson_base_dir: str,
    input_device: int | str | None,
    input_samplerate: int,
    asr_mode: str,
    bluetooth_offset_sec: float,
    playback_sample_rate: int,
    sherpa_paths: dict,
    pure_playback: bool,
    lesson_text_for_fake: str,
    startup_grace_sec: float,
    low_confidence_hold_sec: float,
    use_partial_adapter: bool,
    audio_queue_maxsize: int,
    asr_event_queue_maxsize: int,
    output_device: int | None,
    playback_latency: str,
    playback_blocksize: int,
    capture_backend: str,
    capture_latency: str,
    capture_blocksize: int,
    capture_include_loopback: bool,
    capture_debug_level_meter: bool,
    capture_debug_level_every_n_blocks: int,
    asr_debug_feed: bool,
    asr_debug_feed_every_n_chunks: int,
) -> dict:
    return {
        "lesson_base_dir": lesson_base_dir,
        "playback": {
            "sample_rate": playback_sample_rate,
            "channels": 1,
            "device": output_device,
            "bluetooth_output_offset_sec": bluetooth_offset_sec,
            "latency": playback_latency,
            "blocksize": playback_blocksize,
        },
        "capture": {
            "backend": capture_backend,
            "device_sample_rate": input_samplerate,
            "target_sample_rate": 16000,
            "channels": 1,
            "device": input_device,
            "dtype": "float32",
            "blocksize": capture_blocksize,
            "block_frames": capture_blocksize if capture_blocksize > 0 else 1440,
            "latency": capture_latency,
            "include_loopback": capture_include_loopback,
            "debug_level_meter": capture_debug_level_meter,
            "debug_level_every_n_blocks": capture_debug_level_every_n_blocks,
        },
        "asr": {
            "mode": asr_mode,
            "sample_rate": 16000,
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
            "emit_partial_interval_sec": 0.08,
            "enable_endpoint": True,
            "debug_feed": asr_debug_feed,
            "debug_feed_every_n_chunks": asr_debug_feed_every_n_chunks,
            "reference_text": lesson_text_for_fake if asr_mode == "fake" else "",
            "chars_per_sec": 4.0,
            "emit_final_on_endpoint": True,
            "bytes_per_sample": 2,
            "channels": 1,
            "vad_rms_threshold": 0.01,
            "vad_min_active_ms": 30.0,
            "scripted_steps": [],
        },
        "alignment": {
            "window_back": 8,
            "window_ahead": 40,
            "stable_frames": 2,
            "min_confidence": 0.60,
            "backward_lock_frames": 3,
            "clause_boundary_bonus": 0.15,
            "cross_clause_backward_extra_penalty": 0.20,
            "debug": False,
            "max_hyp_tokens": 16,
        },
        "control": {
            "target_lead_sec": 0.15,
            "hold_if_lead_sec": 0.90,
            "resume_if_lead_sec": 0.28,
            "seek_if_lag_sec": -1.80,
            "min_confidence": 0.75,
            "seek_cooldown_sec": 1.20,
            "gain_following": 0.55,
            "gain_transition": 0.80,
            "gain_soft_duck": 0.42,
            "recover_after_seek_sec": 0.60,
            "startup_grace_sec": startup_grace_sec,
            "low_confidence_hold_sec": low_confidence_hold_sec,
            "disable_seek": False,
            "bootstrapping_sec": 1.80,
            "guide_play_sec": 2.20,
            "no_progress_hold_min_play_sec": 4.00,
            "speaking_recent_sec": 0.90,
            "progress_stale_sec": 1.10,
            "hold_trend_sec": 0.75,
            "hold_extra_lead_sec": 0.18,
            "low_confidence_continue_sec": 1.40,
            "tracking_quality_hold_min": 0.60,
            "tracking_quality_seek_min": 0.72,
            "resume_from_hold_event_fresh_sec": 0.45,
            "resume_from_hold_speaking_lead_slack_sec": 0.45,
            "reacquire_soft_duck_sec": 2.00,
        },
        "runtime": {
            "pure_playback": pure_playback,
            "use_partial_adapter": use_partial_adapter,
            "audio_queue_maxsize": audio_queue_maxsize,
            "asr_event_queue_maxsize": asr_event_queue_maxsize,
            "loop_interval_sec": 0.03,
            "telemetry_enabled": True,
            "session_artifacts_dir": "artifacts/runtime_sessions",
        },
        "debug": {
            "enabled": False,
            "adapter_debug": False,
            "aligner_debug": False,
            "tracking_debug": False,
        },
    }


def _parse_input_device_arg(raw_value: str | None) -> int | str | None:
    if raw_value is None:
        return None
    raw = str(raw_value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw


def _run_bluetooth_preflight_or_fail(
    *,
    capture_backend: str,
    input_device: int | str | None,
    output_device: int | str | None,
    input_samplerate: int,
    playback_sample_rate: int,
    preflight_duration_sec: float,
    skip_bluetooth_preflight: bool,
) -> tuple[int | str | None, int | None]:
    if skip_bluetooth_preflight:
        print("[BT-PREFLIGHT] skipped by user.")
        return input_device, output_device

    should_run = should_run_bluetooth_preflight(
        input_device=input_device,
        output_device=output_device,
    )
    if not should_run:
        print("[BT-PREFLIGHT] not a bluetooth-headset session, skip.")
        return input_device, output_device

    if capture_backend != "sounddevice":
        raise RuntimeError(
            "Bluetooth headset commercial mode requires --capture-backend sounddevice, "
            "because startup preflight must validate duplex with the same device stack."
        )

    result = run_bluetooth_duplex_preflight(
        BluetoothPreflightConfig(
            input_device=input_device,
            output_device=output_device,
            preferred_input_samplerate=int(input_samplerate),
            preferred_output_samplerate=int(playback_sample_rate),
            duration_sec=float(preflight_duration_sec),
        )
    )

    print(
        "[BT-PREFLIGHT] "
        f"input={result.input_device_name!r} "
        f"output={result.output_device_name!r} "
        f"sr={result.samplerate} "
        f"mean_rms={result.mean_rms:.6f} "
        f"max_peak={result.max_peak:.6f} "
        f"nonzero_ratio={result.nonzero_ratio:.6f} "
        f"voiced_frame_ratio={result.voiced_frame_ratio:.6f} "
        f"status_events={result.status_events} "
        f"passed={result.passed}"
    )

    if not result.passed:
        notes = "\n".join(f"- {x}" for x in result.notes) if result.notes else ""
        raise RuntimeError(
            "Bluetooth headset duplex preflight failed.\n"
            f"Reason: {result.failure_reason}\n"
            f"Input: {result.input_device_name!r}\n"
            f"Output: {result.output_device_name!r}\n"
            f"{notes}"
        )

    return result.input_device_index, result.output_device_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the shadowing app for a local txt speech lesson.")
    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")
    parser.add_argument("--asr", type=str, default="fake", choices=["fake", "sherpa"])
    parser.add_argument("--bluetooth-offset-sec", type=float, default=0.18)

    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--input-samplerate", type=int, default=None)
    parser.add_argument("--output-device", type=int, default=None)

    parser.add_argument("--pure-playback", action="store_true")
    parser.add_argument("--adapter-debug", action="store_true")
    parser.add_argument("--aligner-debug", action="store_true")
    parser.add_argument("--tracking-debug", action="store_true")
    parser.add_argument("--disable-seek", action="store_true")
    parser.add_argument("--bypass-partial-adapter", action="store_true")

    parser.add_argument("--audio-queue-maxsize", type=int, default=150)
    parser.add_argument("--asr-event-queue-maxsize", type=int, default=64)
    parser.add_argument("--startup-grace-sec", type=float, default=0.80)
    parser.add_argument("--low-confidence-hold-sec", type=float, default=0.60)

    parser.add_argument("--playback-latency", type=str, default="high")
    parser.add_argument("--playback-blocksize", type=int, default=2048)

    parser.add_argument("--capture-backend", type=str, default="sounddevice", choices=["sounddevice", "soundcard"])
    parser.add_argument("--capture-latency", type=str, default="low")
    parser.add_argument("--capture-blocksize", type=int, default=0)
    parser.add_argument("--capture-include-loopback", action="store_true")
    parser.add_argument("--capture-debug-level-meter", action="store_true")
    parser.add_argument("--capture-debug-level-every", type=int, default=20)

    parser.add_argument("--asr-debug-feed", action="store_true")
    parser.add_argument("--asr-debug-feed-every", type=int, default=20)

    parser.add_argument("--skip-bluetooth-preflight", action="store_true")
    parser.add_argument("--preflight-duration-sec", type=float, default=3.5)

    args = parser.parse_args()

    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")

    lesson_text = text_path.read_text(encoding="utf-8").strip()
    if not lesson_text:
        raise ValueError(f"Text file is empty: {text_path}")

    lesson_id = slugify_filename_stem(text_path.stem)

    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    lesson_dir = lesson_base_dir / lesson_id
    validate_lesson_assets(lesson_dir)

    manifest = load_manifest(lesson_dir)
    playback_sample_rate = int(manifest["sample_rate_out"])

    parsed_input_device = _parse_input_device_arg(args.input_device)


    if args.capture_backend == "sounddevice":
        rec_cfg = pick_working_input_config(
            preferred_device=parsed_input_device if isinstance(parsed_input_device, int) else None,
            preferred_name_substring=parsed_input_device if isinstance(parsed_input_device, str) else None,
            preferred_rates=(
                [args.input_samplerate, 48000, 44100, 16000]
                if args.input_samplerate is not None
                else [48000, 44100, 16000]
            ),
        ) or {
            "device": parsed_input_device,
            "samplerate": args.input_samplerate or 48000,
        }

        if args.input_samplerate is not None:
            rec_cfg["samplerate"] = args.input_samplerate

        effective_input_device = rec_cfg["device"]
        effective_input_samplerate = int(rec_cfg["samplerate"])
    else:
        effective_input_device = parsed_input_device
        effective_input_samplerate = int(args.input_samplerate or 48000)

    sherpa_paths = collect_sherpa_paths()
    if args.asr == "sherpa" and not args.pure_playback:
        validate_sherpa_paths(sherpa_paths)

    if args.capture_backend == "soundcard" and isinstance(parsed_input_device, int):
        print(
            "[RUN-NOTE] soundcard backend uses soundcard microphone list index, "
            "not sounddevice raw device index."
        )

    effective_input_device, effective_output_device = _run_bluetooth_preflight_or_fail(
        capture_backend=args.capture_backend,
        input_device=effective_input_device,
        output_device=args.output_device,
        input_samplerate=effective_input_samplerate,
        playback_sample_rate=playback_sample_rate,
        preflight_duration_sec=float(args.preflight_duration_sec),
        skip_bluetooth_preflight=bool(args.skip_bluetooth_preflight),
    )

    print(
        f"[RUN-CONFIG] lesson_id={lesson_id} "
        f"capture_backend={args.capture_backend} "
        f"input_device={effective_input_device!r} "
        f"input_samplerate={effective_input_samplerate} "
        f"output_device={effective_output_device!r} "
        f"playback_sr={playback_sample_rate} "
        f"playback_latency={args.playback_latency} "
        f"playback_blocksize={int(args.playback_blocksize)} "
        f"capture_latency={args.capture_latency} "
        f"capture_blocksize={int(args.capture_blocksize)}"
    )

    config = build_config(
        lesson_base_dir=str(lesson_base_dir),
        input_device=effective_input_device,
        input_samplerate=effective_input_samplerate,
        asr_mode=args.asr,
        bluetooth_offset_sec=args.bluetooth_offset_sec,
        playback_sample_rate=playback_sample_rate,
        sherpa_paths=sherpa_paths,
        pure_playback=args.pure_playback,
        lesson_text_for_fake=lesson_text,
        startup_grace_sec=float(args.startup_grace_sec),
        low_confidence_hold_sec=float(args.low_confidence_hold_sec),
        use_partial_adapter=not bool(args.bypass_partial_adapter),
        audio_queue_maxsize=int(args.audio_queue_maxsize),
        asr_event_queue_maxsize=int(args.asr_event_queue_maxsize),
        output_device=effective_output_device,
        playback_latency=args.playback_latency,
        playback_blocksize=int(args.playback_blocksize),
        capture_backend=args.capture_backend,
        capture_latency=args.capture_latency,
        capture_blocksize=int(args.capture_blocksize),
        capture_include_loopback=bool(args.capture_include_loopback),
        capture_debug_level_meter=bool(args.capture_debug_level_meter),
        capture_debug_level_every_n_blocks=int(args.capture_debug_level_every),
        asr_debug_feed=bool(args.asr_debug_feed),
        asr_debug_feed_every_n_chunks=int(args.asr_debug_feed_every),
    )

    config["control"]["disable_seek"] = bool(args.disable_seek or args.asr == "fake")
    config["debug"]["enabled"] = bool(args.adapter_debug or args.aligner_debug or args.tracking_debug)
    config["debug"]["adapter_debug"] = bool(args.adapter_debug)
    config["debug"]["aligner_debug"] = bool(args.aligner_debug)
    config["debug"]["tracking_debug"] = bool(args.tracking_debug)
    config["alignment"]["debug"] = bool(args.aligner_debug)

    runtime = build_runtime(config)

    print("Starting shadowing runtime. Press Ctrl+C to stop.")
    try:
        runtime.run(lesson_id)
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()