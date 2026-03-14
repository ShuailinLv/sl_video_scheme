from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DeviceProfile:
    input_device_id: str
    output_device_id: str
    input_kind: str
    output_kind: str
    input_sample_rate: int
    output_sample_rate: int
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    noise_floor_rms: float
    input_gain_hint: str
    reliability_tier: str


def _normalize_device_name(device_name: int | str | None) -> str:
    if device_name is None:
        return ""
    return str(device_name).strip().lower()


def classify_input_device(device_name: int | str | None) -> str:
    name = _normalize_device_name(device_name)
    if not name:
        return "unknown"
    if "bluetooth" in name or "耳机" in name or "headset" in name:
        return "bluetooth_headset"
    if "usb" in name or "麦克风" in name or "microphone" in name:
        return "usb_mic"
    if "阵列" in name or "array" in name or "realtek" in name:
        return "builtin_mic"
    return "unknown"


def classify_output_device(device_name: int | str | None) -> str:
    name = _normalize_device_name(device_name)
    if not name:
        return "unknown"
    if "bluetooth" in name or "耳机" in name or "headset" in name:
        return "bluetooth_headset"
    if "speaker" in name or "扬声器" in name:
        return "speaker"
    if "usb" in name:
        return "wired_headset"
    return "unknown"


def infer_input_gain_hint(noise_floor_rms: float) -> str:
    if noise_floor_rms < 0.0015:
        return "high"
    if noise_floor_rms < 0.004:
        return "normal"
    return "low"


def infer_reliability_tier(input_kind: str, output_kind: str) -> str:
    if input_kind == "bluetooth_headset" or output_kind == "bluetooth_headset":
        return "low"
    if input_kind == "unknown" or output_kind == "unknown":
        return "medium"
    return "high"


def default_input_latency_ms(input_kind: str) -> float:
    if input_kind == "bluetooth_headset":
        return 140.0
    if input_kind == "usb_mic":
        return 35.0
    if input_kind == "builtin_mic":
        return 28.0
    return 50.0


def default_output_latency_ms(output_kind: str) -> float:
    if output_kind == "bluetooth_headset":
        return 180.0
    if output_kind == "wired_headset":
        return 40.0
    if output_kind == "speaker":
        return 35.0
    return 60.0


def build_device_profile(
    input_device_name: int | str | None,
    output_device_name: int | str | None,
    input_sample_rate: int,
    output_sample_rate: int,
    noise_floor_rms: float,
) -> DeviceProfile:
    input_kind = classify_input_device(input_device_name)
    output_kind = classify_output_device(output_device_name)

    return DeviceProfile(
        input_device_id=str(input_device_name if input_device_name is not None else "unknown"),
        output_device_id=str(output_device_name if output_device_name is not None else "unknown"),
        input_kind=input_kind,
        output_kind=output_kind,
        input_sample_rate=int(input_sample_rate),
        output_sample_rate=int(output_sample_rate),
        estimated_input_latency_ms=float(default_input_latency_ms(input_kind)),
        estimated_output_latency_ms=float(default_output_latency_ms(output_kind)),
        noise_floor_rms=float(noise_floor_rms),
        input_gain_hint=infer_input_gain_hint(noise_floor_rms),
        reliability_tier=infer_reliability_tier(input_kind, output_kind),
    )