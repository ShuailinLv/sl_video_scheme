from __future__ import annotations
import _bootstrap
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
    first_tick = None
    last_tick = None
    first_ts = None
    last_ts = None
    for ev in loader:
        counts[ev.event_type] += 1
        if ev.session_tick is not None:
            if first_tick is None:
                first_tick = ev.session_tick
            last_tick = ev.session_tick
        if ev.ts_monotonic_sec is not None:
            if first_ts is None:
                first_ts = ev.ts_monotonic_sec
            last_ts = ev.ts_monotonic_sec
        if ev.event_type == "tracking_snapshot":
            mode = ev.payload.get("tracking_mode")
            tq = float(ev.payload.get("overall_score", 0.0))
            max_tracking_quality = max(max_tracking_quality, tq)
            last_tracking_mode = mode
        elif ev.event_type == "progress_snapshot":
            last_user_state = ev.payload.get("user_state")
        elif ev.event_type == "signal_snapshot":
            max_signal = max(max_signal, float(ev.payload.get("speaking_likelihood", 0.0)))
    print(f"events={sum(counts.values())} unique_types={len(counts)}")
    print(f"tick_range={first_tick}..{last_tick}")
    print(f"time_range={first_ts}..{last_ts}")
    print(f"last_tracking_mode={last_tracking_mode}")
    print(f"last_user_state={last_user_state}")
    print(f"max_tracking_quality={max_tracking_quality:.3f}")
    print(f"max_signal={max_signal:.3f}")
    for k in sorted(counts):
        print(f"{k}: {counts[k]}")


if __name__ == "__main__":
    main()
