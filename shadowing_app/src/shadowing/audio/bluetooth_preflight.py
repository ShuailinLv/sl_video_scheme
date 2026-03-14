from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd


@dataclass(slots=True)
class ResolvedDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    hostapi_name: str


@dataclass(slots=True)
class BluetoothPreflightConfig:
    input_device: int | str | None
    output_device: int | str | None

    preferred_input_samplerate: int = 48000
    preferred_output_samplerate: int = 44100

    duration_sec: float = 4.0
    warmup_ignore_sec: float = 0.9
    blocksize: int = 0

    probe_tone_hz: float = 880.0
    probe_tone_amp: float = 0.05

    min_mean_rms: float = 0.0015
    min_peak: float = 0.0150
    min_nonzero_ratio: float = 0.010
    min_voiced_frame_ratio: float = 0.12

    strong_rms: float = 0.0060
    strong_peak: float = 0.0200
    strong_voiced_frame_ratio: float = 0.22

    max_status_events: int = 10


@dataclass(slots=True)
class BluetoothPreflightResult:
    should_run: bool
    passed: bool
    input_device_index: int | None = None
    input_device_name: str = ""
    output_device_index: int | None = None
    output_device_name: str = ""
    samplerate: int = 0

    mean_rms: float = 0.0
    max_peak: float = 0.0
    nonzero_ratio: float = 0.0
    voiced_frame_ratio: float = 0.0

    tail_mean_rms: float = 0.0
    tail_max_peak: float = 0.0
    tail_nonzero_ratio: float = 0.0
    tail_voiced_frame_ratio: float = 0.0

    status_events: int = 0
    failure_reason: str = ""
    notes: list[str] = field(default_factory=list)


_BLUETOOTH_KEYWORDS = (
    "bluetooth",
    "headset",
    "hands-free",
    "hands free",
    "airpods",
    "buds",
    "earbuds",
    "zero air",
    "耳机",
    "蓝牙",
)


def _looks_like_bluetooth(name: str | None) -> bool:
    text = str(name or "").strip().lower()
    if not text:
        return False
    return any(k in text for k in _BLUETOOTH_KEYWORDS)


def _device_family_key(name: str | None) -> str:
    text = str(name or "").strip().lower()
    if not text:
        return ""

    normalized = (
        text.replace("hands-free", "handsfree")
        .replace("hands free", "handsfree")
        .replace("(", " ")
        .replace(")", " ")
        .replace("[", " ")
        .replace("]", " ")
        .replace("-", " ")
        .replace("_", " ")
    )

    for token in (
        "zero air",
        "airpods",
        "earbuds",
        "buds",
        "handsfree",
        "headset",
        "耳机",
        "蓝牙",
    ):
        if token in normalized:
            return token

    return normalized


def _resolve_hostapi_name(dev: dict) -> str:
    hostapis = sd.query_hostapis()
    return str(hostapis[int(dev["hostapi"])]["name"])


def _resolve_input_device(device: int | str | None) -> ResolvedDevice:
    devices = sd.query_devices()

    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Resolved input device is not an input device: idx={device}, name={dev['name']}")
        return ResolvedDevice(
            index=int(device),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    if device is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            raise RuntimeError("No default input device available for bluetooth preflight.")
        dev = sd.query_devices(int(default_in))
        if int(dev["max_input_channels"]) <= 0:
            raise RuntimeError(f"Default input device is invalid: idx={default_in}, name={dev['name']}")
        return ResolvedDevice(
            index=int(default_in),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return ResolvedDevice(
                index=int(idx),
                name=str(dev["name"]),
                max_input_channels=int(dev["max_input_channels"]),
                max_output_channels=int(dev["max_output_channels"]),
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=_resolve_hostapi_name(dev),
            )

    raise RuntimeError(f"No matching input device found for bluetooth preflight: {device!r}")


def _resolve_output_device(device: int | str | None) -> ResolvedDevice:
    devices = sd.query_devices()

    if isinstance(device, int):
        dev = sd.query_devices(device)
        if int(dev["max_output_channels"]) <= 0:
            raise RuntimeError(f"Resolved output device is not an output device: idx={device}, name={dev['name']}")
        return ResolvedDevice(
            index=int(device),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    if device is None:
        _, default_out = sd.default.device
        if default_out is None or int(default_out) < 0:
            raise RuntimeError("No default output device available for bluetooth preflight.")
        dev = sd.query_devices(int(default_out))
        if int(dev["max_output_channels"]) <= 0:
            raise RuntimeError(f"Default output device is invalid: idx={default_out}, name={dev['name']}")
        return ResolvedDevice(
            index=int(default_out),
            name=str(dev["name"]),
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            hostapi_name=_resolve_hostapi_name(dev),
        )

    target = str(device).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_output_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            return ResolvedDevice(
                index=int(idx),
                name=str(dev["name"]),
                max_input_channels=int(dev["max_input_channels"]),
                max_output_channels=int(dev["max_output_channels"]),
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=_resolve_hostapi_name(dev),
            )

    raise RuntimeError(f"No matching output device found for bluetooth preflight: {device!r}")


def should_run_bluetooth_preflight(input_device: int | str | None, output_device: int | str | None) -> bool:
    try:
        input_resolved = _resolve_input_device(input_device)
        output_resolved = _resolve_output_device(output_device)
    except Exception:
        return False

    input_is_bt = _looks_like_bluetooth(input_resolved.name)
    output_is_bt = _looks_like_bluetooth(output_resolved.name)
    return bool(input_is_bt and output_is_bt)


def _pick_duplex_samplerate(
    input_dev: ResolvedDevice,
    output_dev: ResolvedDevice,
    preferred_input_sr: int,
    preferred_output_sr: int,
) -> int:
    candidates: list[int] = []

    for sr in (
        preferred_input_sr,
        48000,
        32000,
        24000,
        16000,
        preferred_output_sr,
        int(input_dev.default_samplerate),
        int(output_dev.default_samplerate),
        44100,
    ):
        if sr > 0 and sr not in candidates:
            candidates.append(int(sr))

    last_error: Exception | None = None
    for sr in candidates:
        try:
            sd.check_input_settings(
                device=input_dev.index,
                samplerate=sr,
                channels=1,
                dtype="float32",
            )
            sd.check_output_settings(
                device=output_dev.index,
                samplerate=sr,
                channels=1,
                dtype="float32",
            )
            return int(sr)
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        "No common duplex samplerate available for bluetooth preflight. "
        f"input={input_dev.name!r}, output={output_dev.name!r}, last_error={last_error}"
    )


def _safe_mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def _safe_max(values: list[float]) -> float:
    return float(np.max(values)) if values else 0.0


def run_bluetooth_duplex_preflight(config: BluetoothPreflightConfig) -> BluetoothPreflightResult:
    input_dev = _resolve_input_device(config.input_device)
    output_dev = _resolve_output_device(config.output_device)

    samplerate = _pick_duplex_samplerate(
        input_dev=input_dev,
        output_dev=output_dev,
        preferred_input_sr=config.preferred_input_samplerate,
        preferred_output_sr=config.preferred_output_samplerate,
    )

    result = BluetoothPreflightResult(
        should_run=True,
        passed=False,
        input_device_index=input_dev.index,
        input_device_name=input_dev.name,
        output_device_index=output_dev.index,
        output_device_name=output_dev.name,
        samplerate=samplerate,
    )

    rms_values: list[float] = []
    peak_values: list[float] = []
    nonzero_ratios: list[float] = []
    voiced_flags: list[int] = []

    tail_rms_values: list[float] = []
    tail_peak_values: list[float] = []
    tail_nonzero_ratios: list[float] = []
    tail_voiced_flags: list[int] = []

    status_events = 0
    done = threading.Event()
    started_at = time.monotonic()
    tone_phase = 0.0
    lock = threading.Lock()

    def callback(indata, outdata, frames, time_info, status) -> None:
        nonlocal status_events, tone_phase

        now = time.monotonic()
        elapsed = now - started_at

        if status:
            status_events += 1

        audio = np.asarray(indata, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        nonzero_ratio = float(np.mean(np.abs(audio) > 1e-4)) if audio.size else 0.0
        voiced = 1 if (rms >= config.strong_rms or peak >= config.strong_peak) else 0

        with lock:
            rms_values.append(rms)
            peak_values.append(peak)
            nonzero_ratios.append(nonzero_ratio)
            voiced_flags.append(voiced)

            if elapsed >= config.warmup_ignore_sec:
                tail_rms_values.append(rms)
                tail_peak_values.append(peak)
                tail_nonzero_ratios.append(nonzero_ratio)
                tail_voiced_flags.append(voiced)

        t = (np.arange(frames, dtype=np.float32) + tone_phase) / float(samplerate)
        tone = config.probe_tone_amp * np.sin(2.0 * np.pi * config.probe_tone_hz * t).astype(np.float32, copy=False)
        tone_phase += frames
        outdata[:, 0] = tone

        if elapsed >= config.duration_sec:
            done.set()
            outdata.fill(0.0)

    try:
        with sd.Stream(
            samplerate=samplerate,
            blocksize=int(config.blocksize),
            dtype="float32",
            channels=(1, 1),
            callback=callback,
            device=(input_dev.index, output_dev.index),
            latency="low",
        ):
            print(
                "[BT-PREFLIGHT] 已进入蓝牙耳机双工预检。"
                "请在接下来 4 秒内持续说话，同时确认耳机中能听到轻微提示音。"
            )
            done.wait(timeout=max(1.0, config.duration_sec + 1.5))
    except Exception as e:
        result.failure_reason = (
            "bluetooth_duplex_open_failed: "
            f"input={input_dev.name!r}, output={output_dev.name!r}, samplerate={samplerate}, error={e}"
        )
        return result

    result.mean_rms = _safe_mean(rms_values)
    result.max_peak = _safe_max(peak_values)
    result.nonzero_ratio = _safe_mean(nonzero_ratios)
    result.voiced_frame_ratio = _safe_mean(voiced_flags)

    result.tail_mean_rms = _safe_mean(tail_rms_values)
    result.tail_max_peak = _safe_max(tail_peak_values)
    result.tail_nonzero_ratio = _safe_mean(tail_nonzero_ratios)
    result.tail_voiced_frame_ratio = _safe_mean(tail_voiced_flags)

    result.status_events = int(status_events)

    failure_reasons: list[str] = []

    if status_events > config.max_status_events:
        failure_reasons.append(
            f"status_events_too_many({status_events}>{config.max_status_events})"
        )

    strong_pass = (
        result.tail_max_peak >= config.strong_peak
        and result.tail_voiced_frame_ratio >= config.strong_voiced_frame_ratio
    )

    weak_pass = (
        result.tail_max_peak >= config.min_peak
        and result.tail_voiced_frame_ratio >= config.min_voiced_frame_ratio
        and (
            result.tail_nonzero_ratio >= config.min_nonzero_ratio
            or result.tail_mean_rms >= config.min_mean_rms
        )
    )

    if not strong_pass and not weak_pass:
        if result.tail_max_peak < config.min_peak:
            failure_reasons.append(
                f"tail_peak_too_low(tail_max_peak={result.tail_max_peak:.6f})"
            )

        if result.tail_voiced_frame_ratio < config.min_voiced_frame_ratio:
            failure_reasons.append(
                "tail_voice_activity_too_low("
                f"tail_voiced_frame_ratio={result.tail_voiced_frame_ratio:.6f})"
            )

        if (
            result.tail_nonzero_ratio < config.min_nonzero_ratio
            and result.tail_mean_rms < config.min_mean_rms
        ):
            failure_reasons.append(
                "tail_input_too_weak("
                f"tail_mean_rms={result.tail_mean_rms:.6f}, "
                f"tail_nonzero_ratio={result.tail_nonzero_ratio:.6f})"
            )

    if failure_reasons:
        result.failure_reason = "; ".join(failure_reasons)
        result.notes.append("蓝牙耳机双工链路未通过启动前检测。")
        result.notes.append("这通常表示系统未切到稳定通话模式，或当前输入链路在实时采集下过弱。")
        result.notes.append("对这类耳机，建议固定 input samplerate=48000。")
        result.notes.append("如果你刚才一直在持续说话但仍失败，当前系统蓝牙双工状态不适合直接启动实时跟读。")
        return result

    result.passed = True
    result.notes.append("蓝牙耳机双工预检通过。")
    result.notes.append("本次结果已按该耳机前段迟滞特性进行容忍。")
    return result