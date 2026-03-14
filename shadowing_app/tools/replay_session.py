from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
from collections import Counter

from shadowing.telemetry.replay_loader import ReplayLoader


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay and summarize a recorded runtime session events.jsonl")
    parser.add_argument("--events-file", type=str, required=True)
    args = parser.parse_args()

    loader = ReplayLoader(args.events_file)

    counts = Counter()
    last_tracking_mode = None
    last_user_state = None
    max_tracking_quality = 0.0
    max_signal = 0.0

    for ev in loader:
        counts[ev.event_type] += 1

        if ev.event_type == "tracking_snapshot":
            mode = ev.payload.get("tracking_mode")
            tq = float(ev.payload.get("tracking_quality", {}).get("overall_score", 0.0))
            max_tracking_quality = max(max_tracking_quality, tq)
            last_tracking_mode = mode

        elif ev.event_type == "progress_snapshot":
            last_user_state = ev.payload.get("user_state")

        elif ev.event_type == "signal_snapshot":
            max_signal = max(max_signal, float(ev.payload.get("speaking_likelihood", 0.0)))

        elif ev.event_type == "session_summary":
            print("=== Session Summary (recorded) ===")
            print(ev.payload)

    print()
    print("=== Replay Counters ===")
    for k in sorted(counts):
        print(f"{k}: {counts[k]}")

    print()
    print(f"Last tracking mode: {last_tracking_mode}")
    print(f"Last user state: {last_user_state}")
    print(f"Max tracking quality: {max_tracking_quality:.3f}")
    print(f"Max speaking likelihood: {max_signal:.3f}")


if __name__ == "__main__":
    main()