from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sounddevice as sd


@dataclass(slots=True)
class InputDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float
    hostapi_name: str


def list_input_devices() -> list[InputDeviceInfo]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    results: list[InputDeviceInfo] = []
    for idx, dev in enumerate(devices):
        max_in = int(dev["max_input_channels"])
        if max_in <= 0:
            continue

        hostapi_idx = int(dev["hostapi"])
        hostapi_name = hostapis[hostapi_idx]["name"]

        results.append(
            InputDeviceInfo(
                index=idx,
                name=str(dev["name"]),
                max_input_channels=max_in,
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=str(hostapi_name),
            )
        )
    return results


def print_input_devices() -> None:
    devices = list_input_devices()
    if not devices:
        print("No input devices found.")
        return

    print("Available input devices:")
    for d in devices:
        print(
            f"[{d.index}] {d.name} | "
            f"hostapi={d.hostapi_name} | "
            f"max_in={d.max_input_channels} | "
            f"default_sr={d.default_samplerate}"
        )


def get_default_input_device_index() -> int | None:
    """
    返回当前 sounddevice 默认输入设备索引。
    """
    default_input, _ = sd.default.device
    if default_input is None or default_input < 0:
        return None
    return int(default_input)


def choose_input_device(
    preferred_index: int | None = None,
    preferred_name_substring: str | None = None,
) -> int | None:
    """
    选择输入设备优先级：
    1. preferred_index
    2. 名称模糊匹配
    3. 系统默认输入设备
    4. 第一个可用输入设备
    """
    devices = list_input_devices()
    if not devices:
        return None

    if preferred_index is not None:
        for d in devices:
            if d.index == preferred_index:
                return d.index

    if preferred_name_substring:
        keyword = preferred_name_substring.lower()
        for d in devices:
            if keyword in d.name.lower():
                return d.index

    default_idx = get_default_input_device_index()
    if default_idx is not None:
        return default_idx

    return devices[0].index


def check_input_settings(
    device: int | None,
    samplerate: int,
    channels: int = 1,
    dtype: str = "float32",
) -> bool:
    """
    检查给定录音参数是否可用。
    """
    try:
        sd.check_input_settings(
            device=device,
            samplerate=samplerate,
            channels=channels,
            dtype=dtype,
        )
        return True
    except Exception:
        return False


def pick_working_input_config(
    preferred_device: int | None = None,
    preferred_rates: list[int] | None = None,
    channels: int = 1,
    dtype: str = "float32",
) -> dict[str, Any] | None:
    """
    返回一个可用输入配置：
    {
        "device": 1,
        "samplerate": 48000,
        "channels": 1,
        "dtype": "float32",
    }
    """
    if preferred_rates is None:
        preferred_rates = [48000, 44100, 16000]

    device = choose_input_device(preferred_index=preferred_device)
    if device is None:
        return None

    for sr in preferred_rates:
        if check_input_settings(device=device, samplerate=sr, channels=channels, dtype=dtype):
            return {
                "device": device,
                "samplerate": sr,
                "channels": channels,
                "dtype": dtype,
            }

    # 退回设备默认采样率
    try:
        dev = sd.query_devices(device)
        default_sr = int(float(dev["default_samplerate"]))
        if check_input_settings(device=device, samplerate=default_sr, channels=channels, dtype=dtype):
            return {
                "device": device,
                "samplerate": default_sr,
                "channels": channels,
                "dtype": dtype,
            }
    except Exception:
        pass

    return None