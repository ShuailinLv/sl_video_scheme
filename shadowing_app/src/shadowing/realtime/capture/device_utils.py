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
        hostapi_name = hostapis[int(dev["hostapi"])]["name"]
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
    for d in list_input_devices():
        print(
            f"[{d.index}] {d.name} | hostapi={d.hostapi_name} | max_in={d.max_input_channels} | default_sr={d.default_samplerate}"
        )


def get_default_input_device_index() -> int | None:
    default_input, _ = sd.default.device
    if default_input is None or default_input < 0:
        return None
    return int(default_input)


def choose_input_device(preferred_index: int | None = None, preferred_name_substring: str | None = None) -> int | None:
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


def check_input_settings(device: int | None, samplerate: int, channels: int = 1, dtype: str = "float32") -> bool:
    try:
        sd.check_input_settings(device=device, samplerate=samplerate, channels=channels, dtype=dtype)
        return True
    except Exception:
        return False


def pick_working_input_config(
    preferred_device: int | None = None,
    preferred_rates: list[int] | None = None,
    channels: int = 1,
    dtype: str = "float32",
) -> dict[str, Any] | None:
    preferred_rates = preferred_rates or [48000, 44100, 16000]
    device = choose_input_device(preferred_index=preferred_device)
    if device is None:
        return None
    for sr in preferred_rates:
        if check_input_settings(device=device, samplerate=sr, channels=channels, dtype=dtype):
            return {"device": device, "samplerate": sr, "channels": channels, "dtype": dtype}
    return None