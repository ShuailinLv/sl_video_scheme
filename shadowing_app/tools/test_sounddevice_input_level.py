from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd


@dataclass(slots=True)
class LevelStats:
    mean_rms: float
    max_peak: float
    nonzero_ratio: float
    voiced_frame_ratio: float
    total_callbacks: int
    status_events: int
    resolved_device_index: int
    resolved_device_name: str
    samplerate: int
    channels: int


def resolve_input_device(device: int | str | None) -> tuple[int, str]:
    devices = sd.query_devices()

    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Device is not an input device: idx={device}, name={dev['name']}")
        return int(device), str(dev["name"])

    if device is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            raise RuntimeError("No default input device available.")
        dev = sd.query_devices(int(default_in))
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Default device is not input-capable: idx={default_in}, name={dev['name']}")
        return int(default_in), str(dev["name"])

    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return int(idx), str(dev["name"])

    raise RuntimeError(f"No matching input device found: {device!r}")


def pick_samplerate(device_index: int, requested_sr: int | None, channels: int, dtype: str) -> int:
    dev = sd.query_devices(device_index, "input")
    candidates: list[int] = []

    for sr in (
        requested_sr or 0,
        int(float(dev["default_samplerate"])),
        48000,
        44100,
        32000,
        24000,
        16000,
    ):
        if sr > 0 and sr not in candidates:
            candidates.append(int(sr))

    last_error: Exception | None = None
    for sr in candidates:
        try:
            sd.check_input_settings(
                device=device_index,
                samplerate=sr,
                channels=channels,
                dtype=dtype,
            )
            return int(sr)
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        f"Failed to find openable samplerate for input device idx={device_index}, "
        f"name={dev['name']}, last_error={last_error}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure sounddevice input RMS/peak/voice activity.")
    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--samplerate", type=int, default=None)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--dtype", type=str, default="float32")
    parser.add_argument("--duration-sec", type=float, default=4.0)
    parser.add_argument("--blocksize", type=int, default=0)
    parser.add_argument("--vad-rms-threshold", type=float, default=0.006)
    parser.add_argument("--vad-peak-threshold", type=float, default=0.020)
    args = parser.parse_args()

    raw_input_device = args.input_device
    parsed_input_device: int | str | None
    if raw_input_device is None or str(raw_input_device).strip() == "":
        parsed_input_device = None
    elif str(raw_input_device).strip().isdigit():
        parsed_input_device = int(str(raw_input_device).strip())
    else:
        parsed_input_device = str(raw_input_device).strip()

    device_index, device_name = resolve_input_device(parsed_input_device)
    samplerate = pick_samplerate(
        device_index=device_index,
        requested_sr=args.samplerate,
        channels=int(args.channels),
        dtype=str(args.dtype),
    )

    rms_values: list[float] = []
    peak_values: list[float] = []
    nonzero_ratios: list[float] = []
    voiced_flags: list[int] = []
    status_events = 0
    callback_count = 0
    started_at = time.monotonic()

    def callback(indata, frames, time_info, status) -> None:
        nonlocal status_events, callback_count
        callback_count += 1

        if status:
            status_events += 1
            print(f"[INPUT-STATUS] {status}")

        audio = np.asarray(indata, dtype=np.float32)
        if audio.ndim == 2:
            mono = np.mean(audio, axis=1).astype(np.float32, copy=False)
        else:
            mono = audio.reshape(-1).astype(np.float32, copy=False)

        rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
        peak = float(np.max(np.abs(mono))) if mono.size else 0.0
        nonzero_ratio = float(np.mean(np.abs(mono) > 1e-4)) if mono.size else 0.0
        voiced = 1 if (rms >= float(args.vad_rms_threshold) or peak >= float(args.vad_peak_threshold)) else 0

        rms_values.append(rms)
        peak_values.append(peak)
        nonzero_ratios.append(nonzero_ratio)
        voiced_flags.append(voiced)

        if callback_count <= 5 or callback_count % 20 == 0:
            elapsed = time.monotonic() - started_at
            print(
                f"[INPUT-LEVEL] t={elapsed:.2f}s "
                f"rms={rms:.6f} peak={peak:.6f} nonzero_ratio={nonzero_ratio:.6f} voiced={voiced}"
            )

    print(
        "[INPUT-TEST] start "
        f"device_index={device_index} "
        f"device_name={device_name!r} "
        f"samplerate={samplerate} channels={int(args.channels)} "
        f"duration_sec={float(args.duration_sec)} blocksize={int(args.blocksize)}"
    )
    print("[INPUT-TEST] 请在测试期间持续说话。")

    with sd.InputStream(
        samplerate=samplerate,
        blocksize=int(args.blocksize),
        device=device_index,
        channels=int(args.channels),
        dtype=str(args.dtype),
        latency="low",
        callback=callback,
    ):
        time.sleep(float(args.duration_sec))

    stats = LevelStats(
        mean_rms=float(np.mean(rms_values)) if rms_values else 0.0,
        max_peak=float(np.max(peak_values)) if peak_values else 0.0,
        nonzero_ratio=float(np.mean(nonzero_ratios)) if nonzero_ratios else 0.0,
        voiced_frame_ratio=float(np.mean(voiced_flags)) if voiced_flags else 0.0,
        total_callbacks=int(callback_count),
        status_events=int(status_events),
        resolved_device_index=int(device_index),
        resolved_device_name=str(device_name),
        samplerate=int(samplerate),
        channels=int(args.channels),
    )

    print()
    print("=== Input Level Summary ===")
    print(f"device_index: {stats.resolved_device_index}")
    print(f"device_name: {stats.resolved_device_name}")
    print(f"samplerate: {stats.samplerate}")
    print(f"channels: {stats.channels}")
    print(f"total_callbacks: {stats.total_callbacks}")
    print(f"status_events: {stats.status_events}")
    print(f"mean_rms: {stats.mean_rms:.6f}")
    print(f"max_peak: {stats.max_peak:.6f}")
    print(f"nonzero_ratio: {stats.nonzero_ratio:.6f}")
    print(f"voiced_frame_ratio: {stats.voiced_frame_ratio:.6f}")

    if stats.mean_rms < 0.003 and stats.max_peak < 0.02:
        print("[INPUT-TEST] 结论：输入几乎静音。")
    elif stats.voiced_frame_ratio < 0.08:
        print("[INPUT-TEST] 结论：能量很弱或几乎没有稳定语音活动。")
    else:
        print("[INPUT-TEST] 结论：输入链路基本可用。")


if __name__ == "__main__":
    main()