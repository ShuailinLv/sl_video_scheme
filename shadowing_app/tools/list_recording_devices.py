import _bootstrap  # noqa: F401

from shadowing.realtime.capture.device_utils import (
    print_input_devices,
    get_default_input_device_index,
    pick_working_input_config,
)



def main() -> None:
    print_input_devices()

    default_idx = get_default_input_device_index()
    print()
    print(f"Default input device: {default_idx}")

    config = pick_working_input_config()
    print()
    print("Suggested recording config:")
    print(config)


if __name__ == "__main__":
    main()