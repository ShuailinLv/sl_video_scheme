from __future__ import annotations

import _bootstrap  # noqa: F401

import sounddevice as sd


def main() -> None:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    print("=== Output devices ===")
    found = False
    for idx, dev in enumerate(devices):
        max_out = int(dev["max_output_channels"])
        if max_out <= 0:
            continue
        found = True
        hostapi_name = hostapis[int(dev["hostapi"])]["name"]
        print(
            f"[{idx}] {dev['name']} | hostapi={hostapi_name} | "
            f"max_out={max_out} | default_sr={float(dev['default_samplerate'])}"
        )

    if not found:
        print("No output devices found.")

    default_in, default_out = sd.default.device
    print()
    print(f"Default input device: {default_in}")
    print(f"Default output device: {default_out}")


if __name__ == "__main__":
    main()