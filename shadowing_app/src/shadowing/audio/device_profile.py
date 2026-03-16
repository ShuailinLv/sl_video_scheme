from __future__ import annotations

from dataclasses import dataclass
import re


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

_USB_KEYWORDS = (
    "usb",
    "type-c",
    "type c",
    "dongle",
)

_INPUT_MIC_KEYWORDS = (
    "microphone",
    "mic",
    "麦克风",
    "话筒",
)

_BUILTIN_MIC_KEYWORDS = (
    "array",
    "阵列",
    "realtek",
    "internal",
    "built-in",
    "builtin",
    "内置",
)

_SPEAKER_KEYWORDS = (
    "speaker",
    "speakers",
    "扬声器",
    "喇叭",
)

_WIRED_HEADSET_KEYWORDS = (
    "headphone",
    "headphones",
    "headset",
    "耳麦",
    "耳机",
    "3.5mm",
    "line out",
    "line-out",
)


def _normalize_text(value: int | str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_compact_text(value: int | str | None) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = (
        text.replace("hands-free", "handsfree")
        .replace("hands free", "handsfree")
        .replace("built-in", "builtin")
        .replace("line-out", "lineout")
        .replace("type-c", "typec")
        .replace("type c", "typec")
    )
    text = re.sub(r"[\[\]{}()<>]", " ", text)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    if not text:
        return False
    return any(k in text for k in keywords)


def _looks_like_bluetooth(name: str | None) -> bool:
    text = _normalize_text(name)
    if not text:
        return False
    return _contains_any(text, _BLUETOOTH_KEYWORDS)


def _device_family_key(name: str | None) -> str:
    text = _normalize_compact_text(name)
    if not text:
        return ""

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
        if token in text:
            return token

    return " ".join(text.split())


def normalize_device_name(device_name: int | str | None) -> str:
    text = _normalize_text(device_name)
    return text if text else "unknown"


def normalize_device_id(
    *,
    device_name: int | str | None,
    hostapi_name: str | None = None,
    device_index: int | None = None,
) -> str:
    """
    用于 profile / session 维度的稳定设备 ID。

    设计原则：
    - 优先使用 hostapi + 规范化 name
    - 若有 device_index，则作为附加信息保留，但不作为唯一锚点
    - 尽量避免仅使用 index，因为不同机器 / 重启 / 驱动状态下 index 可能漂移
    """
    norm_name = normalize_device_name(device_name)
    norm_hostapi = _normalize_text(hostapi_name) or "unknown"

    parts = [f"hostapi={norm_hostapi}", f"name={norm_name}"]
    if device_index is not None:
        try:
            parts.append(f"idx={int(device_index)}")
        except Exception:
            pass
    return " | ".join(parts)


@dataclass(slots=True)
class DeviceProfile:
    input_device_id: str
    output_device_id: str

    input_device_name: str
    output_device_name: str

    input_family_key: str
    output_family_key: str

    input_kind: str
    output_kind: str

    input_sample_rate: int
    output_sample_rate: int

    estimated_input_latency_ms: float
    estimated_output_latency_ms: float

    noise_floor_rms: float
    input_gain_hint: str
    reliability_tier: str

    bluetooth_mode: bool = False
    hostapi_name: str = ""
    capture_backend: str = ""


def classify_input_device(device_name: int | str | None) -> str:
    name = _normalize_text(device_name)
    if not name:
        return "unknown"

    if _looks_like_bluetooth(name):
        return "bluetooth_headset"

    if _contains_any(name, _USB_KEYWORDS) and (
        _contains_any(name, _INPUT_MIC_KEYWORDS) or "audio" in name
    ):
        return "usb_mic"

    if _contains_any(name, _BUILTIN_MIC_KEYWORDS):
        return "builtin_mic"

    if _contains_any(name, _INPUT_MIC_KEYWORDS):
        return "mic"

    return "unknown"


def classify_output_device(device_name: int | str | None) -> str:
    name = _normalize_text(device_name)
    if not name:
        return "unknown"

    if _looks_like_bluetooth(name):
        return "bluetooth_headset"

    if _contains_any(name, _SPEAKER_KEYWORDS):
        return "speaker"

    if _contains_any(name, _USB_KEYWORDS) and (
        _contains_any(name, _WIRED_HEADSET_KEYWORDS) or "audio" in name
    ):
        return "wired_headset"

    if _contains_any(name, _WIRED_HEADSET_KEYWORDS):
        return "wired_headset"

    return "unknown"


def infer_input_gain_hint(noise_floor_rms: float) -> str:
    value = max(0.0, float(noise_floor_rms))
    if value < 0.0015:
        return "high"
    if value < 0.0040:
        return "normal"
    return "low"


def infer_reliability_tier(input_kind: str, output_kind: str) -> str:
    input_kind = str(input_kind or "unknown")
    output_kind = str(output_kind or "unknown")

    if input_kind == "bluetooth_headset" or output_kind == "bluetooth_headset":
        return "low"

    if input_kind == "unknown" or output_kind == "unknown":
        return "medium"

    if input_kind in {"builtin_mic", "mic"} and output_kind == "speaker":
        return "medium"

    return "high"


def default_input_latency_ms(input_kind: str) -> float:
    kind = str(input_kind or "unknown")
    if kind == "bluetooth_headset":
        return 140.0
    if kind == "usb_mic":
        return 35.0
    if kind == "builtin_mic":
        return 28.0
    if kind == "mic":
        return 40.0
    return 50.0


def default_output_latency_ms(output_kind: str) -> float:
    kind = str(output_kind or "unknown")
    if kind == "bluetooth_headset":
        return 180.0
    if kind == "wired_headset":
        return 40.0
    if kind == "speaker":
        return 35.0
    return 60.0


def build_device_profile(
    input_device_name: int | str | None,
    output_device_name: int | str | None,
    input_sample_rate: int,
    output_sample_rate: int,
    noise_floor_rms: float,
    *,
    hostapi_name: str = "",
    capture_backend: str = "",
    input_device_id: str | None = None,
    output_device_id: str | None = None,
) -> DeviceProfile:
    normalized_input_name = normalize_device_name(input_device_name)
    normalized_output_name = normalize_device_name(output_device_name)

    input_kind = classify_input_device(normalized_input_name)
    output_kind = classify_output_device(normalized_output_name)

    normalized_noise_floor = max(0.0, float(noise_floor_rms))
    bluetooth_mode = bool(
        input_kind == "bluetooth_headset" or output_kind == "bluetooth_headset"
    )

    resolved_input_device_id = (
        str(input_device_id).strip()
        if str(input_device_id or "").strip()
        else normalize_device_id(
            device_name=normalized_input_name,
            hostapi_name=hostapi_name,
        )
    )
    resolved_output_device_id = (
        str(output_device_id).strip()
        if str(output_device_id or "").strip()
        else normalize_device_id(
            device_name=normalized_output_name,
            hostapi_name=hostapi_name,
        )
    )

    return DeviceProfile(
        input_device_id=resolved_input_device_id,
        output_device_id=resolved_output_device_id,
        input_device_name=normalized_input_name,
        output_device_name=normalized_output_name,
        input_family_key=_device_family_key(normalized_input_name),
        output_family_key=_device_family_key(normalized_output_name),
        input_kind=input_kind,
        output_kind=output_kind,
        input_sample_rate=max(0, int(input_sample_rate)),
        output_sample_rate=max(0, int(output_sample_rate)),
        estimated_input_latency_ms=float(default_input_latency_ms(input_kind)),
        estimated_output_latency_ms=float(default_output_latency_ms(output_kind)),
        noise_floor_rms=normalized_noise_floor,
        input_gain_hint=infer_input_gain_hint(normalized_noise_floor),
        reliability_tier=infer_reliability_tier(input_kind, output_kind),
        bluetooth_mode=bluetooth_mode,
        hostapi_name=str(hostapi_name or ""),
        capture_backend=str(capture_backend or ""),
    )