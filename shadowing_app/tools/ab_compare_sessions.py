from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
from pathlib import Path


def load_summary(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"summary file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def print_metric_diff(name: str, a, b) -> None:
    if a is None or b is None:
        print(f"{name}: A={a} | B={b}")
        return

    try:
        diff = float(b) - float(a)
        print(f"{name}: A={a} | B={b} | delta={diff:+.4f}")
    except Exception:
        print(f"{name}: A={a} | B={b}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two session summary.json files")
    parser.add_argument("--a", type=str, required=True, help="Path to A summary.json")
    parser.add_argument("--b", type=str, required=True, help="Path to B summary.json")
    args = parser.parse_args()

    a_path = Path(args.a).expanduser().resolve()
    b_path = Path(args.b).expanduser().resolve()

    a = load_summary(a_path)
    b = load_summary(b_path)

    ma = a.get("metrics", {})
    mb = b.get("metrics", {})

    print("=== A/B Session Compare ===")
    print(f"A: {a_path}")
    print(f"B: {b_path}")
    print()

    for key in [
        "first_signal_active_time_sec",
        "first_asr_partial_time_sec",
        "first_reliable_progress_time_sec",
        "startup_false_hold_count",
        "hold_count",
        "resume_count",
        "soft_duck_count",
        "seek_count",
        "lost_count",
        "reacquire_count",
        "max_tracking_quality",
        "mean_tracking_quality",
        "total_progress_updates",
    ]:
        print_metric_diff(key, ma.get(key), mb.get(key))

    la = a.get("latency_calibration", {}) or {}
    lb = b.get("latency_calibration", {}) or {}

    print()
    print("=== Latency Calibration Compare ===")
    for key in [
        "estimated_input_latency_ms",
        "estimated_output_latency_ms",
        "runtime_input_drift_ms",
        "runtime_output_drift_ms",
        "confidence",
        "calibrated",
    ]:
        print_metric_diff(key, la.get(key), lb.get(key))


if __name__ == "__main__":
    main()