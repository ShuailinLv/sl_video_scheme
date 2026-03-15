from __future__ import annotations

import _bootstrap
import argparse
import json
import os
import re
from pathlib import Path

import sounddevice as sd

from shadowing.audio.bluetooth_preflight import (
    BluetoothPreflightConfig,
    run_bluetooth_duplex_preflight,
    should_run_bluetooth_preflight,
)
from shadowing.bootstrap import build_runtime
from shadowing.llm.qwen_hotwords import extract_hotwords_with_qwen
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


def _parse_input_device_arg(raw_value: str | None) -> int | str | None:
    if raw_value is None:
        return None
    raw = str(raw_value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw


def _resolve_output_device_name(device_index: int | None) -> str:
    if device_index is None:
        _, default_out = sd.default.device
        if default_out is None or int(default_out) < 0:
            return "unknown"
        device_index = int(default_out)

    dev = sd.query_devices(device_index)
    return str(dev["name"])


def _resolve_input_device_name(device_value: int | str | None) -> str:
    if device_value is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            return "unknown"
        return str(sd.query_devices(int(default_in))["name"])

    if isinstance(device_value, int):
        return str(sd.query_devices(device_value)["name"])

    target = str(device_value).strip().lower()
    for _, dev in enumerate(sd.query_devices()):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return str(dev["name"])

    return str(device_value)


def _run_bluetooth_preflight_or_fail(
    *,
    input_device: int | str | None,
    output_device: int | str | None,
    input_samplerate: int,
    playback_sample_rate: int,
    preflight_duration_sec: float,
    skip_bluetooth_preflight: bool,
) -> tuple[int | str | None, int | None]:
    if skip_bluetooth_preflight:
        print("[BT-PREFLIGHT] skipped by user.")
        return input_device, output_device if isinstance(output_device, int) else None

    should_run = should_run_bluetooth_preflight(
        input_device=input_device,
        output_device=output_device,
    )
    if not should_run:
        print("[BT-PREFLIGHT] not a bluetooth-headset session, skip.")
        return input_device, output_device if isinstance(output_device, int) else None

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


def _normalize_for_hotwords(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", text)
    return text


def _looks_like_bad_hotword(term: str) -> bool:
    if not term:
        return True
    n = len(term)
    if n < 4 or n > 24:
        return True
    if term[0] in "的了在和与及并就也又把被将呢啊吗呀":
        return True
    if term[-1] in "的了在和与及并就也又呢啊吗呀":
        return True
    if re.fullmatch(r"[A-Za-z]+", term):
        return True
    if re.search(r"[A-Za-z]", term):
        if not re.fullmatch(r"[A-Za-z0-9一-龥]+", term):
            return True
    return False


def _split_text_to_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;：:\n\r]+", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentence_to_clauses(text: str) -> list[str]:
    parts = re.split(r"[，,、]+", text)
    return [p.strip() for p in parts if p.strip()]


def _score_hotword(term: str, whole_sentence: str) -> float:
    score = 0.0
    n = len(term)

    if 5 <= n <= 14:
        score += 5.0
    elif 4 <= n <= 18:
        score += 3.0
    else:
        score += 1.0

    if term == whole_sentence:
        score += 0.8

    if any(k in term for k in ["华为", "座舱", "车机", "微信", "周杰伦", "支付宝", "PPT", "bug"]):
        score += 2.0

    if any(k in term for k in ["技术小组", "智能座舱", "原型车", "红尾灯", "语音助手", "晚高峰"]):
        score += 2.0

    if re.search(r"\d", term):
        score += 0.8

    if _looks_like_bad_hotword(term):
        score -= 10.0

    return score


def _dedupe_by_containment(terms: list[str], max_terms: int) -> list[str]:
    kept: list[str] = []
    for term in terms:
        if any(term in existed for existed in kept if existed != term):
            continue
        kept.append(term)
        if len(kept) >= max_terms:
            break
    return kept


def _build_hotwords_from_lesson_text_local(
    lesson_text: str,
    *,
    max_terms: int = 20,
) -> list[str]:
    normalized_full = _normalize_for_hotwords(lesson_text)
    if not normalized_full:
        return []

    candidates: dict[str, float] = {}

    def add(term: str, whole_sentence: str = "") -> None:
        norm = _normalize_for_hotwords(term)
        if not norm:
            return
        if _looks_like_bad_hotword(norm):
            return
        score = _score_hotword(norm, _normalize_for_hotwords(whole_sentence or norm))
        old = candidates.get(norm)
        if old is None or score > old:
            candidates[norm] = score

    sentences = _split_text_to_sentences(lesson_text)
    for sent in sentences:
        sent_norm = _normalize_for_hotwords(sent)
        if not sent_norm:
            continue

        if 6 <= len(sent_norm) <= 20:
            add(sent_norm, sent_norm)

        clauses = _split_sentence_to_clauses(sent)
        for clause in clauses:
            clause_norm = _normalize_for_hotwords(clause)
            if 4 <= len(clause_norm) <= 16:
                add(clause_norm, sent_norm)

    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    ranked_terms = [k for k, _ in ranked]
    ranked_terms = _dedupe_by_containment(ranked_terms, max_terms=max_terms)
    return ranked_terms[:max_terms]


def _merge_hotwords(
    auto_terms: list[str],
    user_terms_raw: str,
    *,
    max_terms: int = 32,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        norm = _normalize_for_hotwords(term)
        if not norm:
            return
        if _looks_like_bad_hotword(norm):
            return
        if norm in seen:
            return
        seen.add(norm)
        merged.append(norm)

    for term in auto_terms:
        add(term)

    if user_terms_raw.strip():
        for term in re.split(r"[,，;\n]+", user_terms_raw):
            add(term)

    merged = sorted(merged, key=lambda x: (-len(x), x))
    merged = _dedupe_by_containment(merged, max_terms=max_terms)
    return merged[:max_terms]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run shadowing realtime pipeline")

    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")

    parser.add_argument("--asr", type=str, default="sherpa", choices=["fake", "sherpa"])
    parser.add_argument("--output-device", type=int, default=None)
    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--input-samplerate", type=int, default=None)
    parser.add_argument("--capture-backend", type=str, default="sounddevice", choices=["sounddevice", "soundcard"])

    parser.add_argument("--bluetooth-offset-sec", type=float, default=0.18)
    parser.add_argument("--playback-latency", type=str, default="high")
    parser.add_argument("--playback-blocksize", type=int, default=4096)

    parser.add_argument("--aligner-debug", action="store_true")
    parser.add_argument("--asr-debug-feed", action="store_true")
    parser.add_argument("--asr-debug-feed-every", type=int, default=20)

    parser.add_argument("--skip-bluetooth-preflight", action="store_true")
    parser.add_argument("--preflight-duration-sec", type=float, default=3.5)

    parser.add_argument("--tick-sleep-sec", type=float, default=0.03)
    parser.add_argument("--profile-path", type=str, default="runtime/device_profiles.json")
    parser.add_argument("--session-dir", type=str, default="runtime/latest_session")
    parser.add_argument("--event-logging", action="store_true")

    parser.add_argument("--startup-grace-sec", type=float, default=2.0)
    parser.add_argument("--low-confidence-hold-sec", type=float, default=1.5)

    parser.add_argument("--hotwords", type=str, default="")
    parser.add_argument("--hotwords-score", type=float, default=1.8)
    parser.add_argument("--disable-auto-hotwords", action="store_true")
    parser.add_argument("--print-hotwords", action="store_true")

    parser.add_argument(
        "--hotwords-source",
        type=str,
        default="qwen",
        choices=["qwen", "local", "none"],
        help="热词来源：qwen / local / none",
    )
    parser.add_argument(
        "--qwen-api-key",
        type=str,
        default=os.getenv("DASHSCOPE_API_KEY", ""),
        help="DashScope API Key，默认读环境变量 DASHSCOPE_API_KEY",
    )
    parser.add_argument(
        "--qwen-model",
        type=str,
        default=os.getenv("QWEN_CHAT_MODEL", "qwen-plus"),
        help="Qwen 模型名，默认 qwen-plus",
    )
    parser.add_argument(
        "--qwen-max-hotwords",
        type=int,
        default=24,
        help="Qwen 提取热词最大数量",
    )

    return parser


def main() -> None:
    parser = build_arg_parser()
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

    sherpa_paths = collect_sherpa_paths()
    if args.asr == "sherpa":
        validate_sherpa_paths(sherpa_paths)

    effective_input_device, effective_output_device = _run_bluetooth_preflight_or_fail(
        input_device=effective_input_device,
        output_device=args.output_device,
        input_samplerate=effective_input_samplerate,
        playback_sample_rate=playback_sample_rate,
        preflight_duration_sec=float(args.preflight_duration_sec),
        skip_bluetooth_preflight=bool(args.skip_bluetooth_preflight),
    )

    input_device_name = _resolve_input_device_name(effective_input_device)
    output_device_name = _resolve_output_device_name(effective_output_device)

    auto_hotwords: list[str] = []
    if not args.disable_auto_hotwords and args.hotwords_source != "none":
        if args.hotwords_source == "qwen":
            if args.qwen_api_key.strip():
                auto_hotwords = extract_hotwords_with_qwen(
                    lesson_text=lesson_text,
                    api_key=args.qwen_api_key.strip(),
                    model=args.qwen_model.strip(),
                    max_terms=int(args.qwen_max_hotwords),
                )
                if not auto_hotwords:
                    auto_hotwords = _build_hotwords_from_lesson_text_local(
                        lesson_text,
                        max_terms=min(20, int(args.qwen_max_hotwords)),
                    )
            else:
                auto_hotwords = _build_hotwords_from_lesson_text_local(
                    lesson_text,
                    max_terms=min(20, int(args.qwen_max_hotwords)),
                )
        elif args.hotwords_source == "local":
            auto_hotwords = _build_hotwords_from_lesson_text_local(
                lesson_text,
                max_terms=min(20, int(args.qwen_max_hotwords)),
            )

    merged_hotwords = _merge_hotwords(
        auto_hotwords,
        str(args.hotwords or ""),
        max_terms=max(16, min(32, int(args.qwen_max_hotwords))),
    )
    hotwords_str = "\n".join(merged_hotwords)

    print(
        "[RUN-CONFIG] "
        f"lesson_id={lesson_id} "
        f"capture_backend={args.capture_backend!r} "
        f"input_device={effective_input_device!r} "
        f"input_name={input_device_name!r} "
        f"input_samplerate={effective_input_samplerate} "
        f"output_device={effective_output_device!r} "
        f"output_name={output_device_name!r} "
        f"playback_sr={playback_sample_rate} "
        f"playback_latency={args.playback_latency} "
        f"playback_blocksize={int(args.playback_blocksize)} "
        f"aligner_debug={bool(args.aligner_debug)}"
    )

    print(
        "[HOTWORDS] "
        f"count={len(merged_hotwords)} "
        f"score={float(args.hotwords_score):.2f} "
        f"auto_enabled={not bool(args.disable_auto_hotwords)} "
        f"source={args.hotwords_source}"
    )
    if merged_hotwords:
        preview = merged_hotwords[:20]
        print("[HOTWORDS-PREVIEW] " + " | ".join(preview))
    else:
        print("[HOTWORDS-PREVIEW] <empty>")

    if args.print_hotwords and merged_hotwords:
        print("=== HOTWORDS FULL LIST BEGIN ===")
        for term in merged_hotwords:
            print(term)
        print("=== HOTWORDS FULL LIST END ===")

    runtime = build_runtime(
        {
            "lesson_base_dir": str(lesson_base_dir),
            "playback": {
                "sample_rate": playback_sample_rate,
                "channels": 1,
                "device": effective_output_device,
                "latency": args.playback_latency,
                "blocksize": int(args.playback_blocksize),
                "bluetooth_output_offset_sec": float(args.bluetooth_offset_sec),
            },
            "capture": {
                "backend": str(args.capture_backend),
                "device_sample_rate": effective_input_samplerate,
                "target_sample_rate": 16000,
                "channels": 1,
                "device": effective_input_device,
                "dtype": "float32",
                "blocksize": 0,
                "latency": "low",
            },
            "asr": {
                "mode": args.asr,
                "tokens": sherpa_paths.get("tokens", ""),
                "encoder": sherpa_paths.get("encoder", ""),
                "decoder": sherpa_paths.get("decoder", ""),
                "joiner": sherpa_paths.get("joiner", ""),
                "sample_rate": 16000,
                "emit_partial_interval_sec": 0.08,
                "enable_endpoint": True,
                "debug_feed": bool(args.asr_debug_feed),
                "debug_feed_every_n_chunks": int(args.asr_debug_feed_every),
                "num_threads": 2,
                "provider": "cpu",
                "feature_dim": 80,
                "decoding_method": "greedy_search",
                "rule1_min_trailing_silence": 1.2,
                "rule2_min_trailing_silence": 0.8,
                "rule3_min_utterance_length": 12.0,
                "hotwords": hotwords_str,
                "hotwords_score": float(args.hotwords_score),
                "min_meaningful_text_len": 2,
                "endpoint_min_interval_sec": 0.35,
                "reset_on_empty_endpoint": False,
                "preserve_stream_on_partial_only": True,
                "force_reset_after_empty_endpoints": 999999999,
            },
            "alignment": {
                "window_back": 8,
                "window_ahead": 40,
                "stable_frames": 2,
                "min_confidence": 0.60,
                "backward_lock_frames": 3,
                "clause_boundary_bonus": 0.15,
                "cross_clause_backward_extra_penalty": 0.20,
                "debug": bool(args.aligner_debug),
                "max_hyp_tokens": 16,
                "weak_commit_min_conf": 0.82,
                "weak_commit_min_local_match": 0.80,
                "weak_commit_min_advance": 3,
            },
            "control": {
                "target_lead_sec": 0.15,
                "hold_if_lead_sec": 0.90,
                "resume_if_lead_sec": 0.28,
                "seek_if_lag_sec": -1.80,
                "min_confidence": 0.72,
                "seek_cooldown_sec": 1.20,
                "gain_following": 0.55,
                "gain_transition": 0.80,
                "gain_soft_duck": 0.42,
                "startup_grace_sec": float(args.startup_grace_sec),
                "low_confidence_hold_sec": float(args.low_confidence_hold_sec),
                "guide_play_sec": 2.20,
                "no_progress_hold_min_play_sec": 4.00,
                "progress_stale_sec": 1.10,
                "hold_trend_sec": 0.75,
                "tracking_quality_hold_min": 0.56,
                "tracking_quality_seek_min": 0.68,
                "resume_from_hold_speaking_lead_slack_sec": 0.45,
                "disable_seek": False,
            },
            "runtime": {
                "audio_queue_maxsize": 150,
                "asr_event_queue_maxsize": 64,
                "loop_interval_sec": float(args.tick_sleep_sec),
            },
            "signal": {
                "min_vad_rms": 0.006,
                "vad_noise_multiplier": 2.8,
            },
            "adaptation": {
                "profile_path": str(Path(args.profile_path).expanduser().resolve()),
            },
            "session": {
                "session_dir": str(Path(args.session_dir).expanduser().resolve()),
                "event_logging": bool(args.event_logging),
            },
            "device_context": {
                "input_device_name": input_device_name,
                "output_device_name": output_device_name,
                "input_sample_rate": effective_input_samplerate,
                "noise_floor_rms": 0.0025,
            },
            "debug": {
                "enabled": False,
            },
        }
    )

    runtime.run(lesson_id)


if __name__ == "__main__":
    main()