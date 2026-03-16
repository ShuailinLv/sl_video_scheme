from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
from pathlib import Path


def load_summary(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate session summary.json files under a runtime session root")
    parser.add_argument("--root", type=str, required=True, help="Root directory to scan")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"root not found: {root}")

    summaries = sorted(root.rglob("summary.json"))
    if not summaries:
        print("No summary.json files found.")
        return

    n = 0
    hold_count = 0
    resume_count = 0
    soft_duck_count = 0
    seek_count = 0
    lost_count = 0
    reacquire_count = 0
    startup_false_hold_count = 0
    mean_tracking_quality_sum = 0.0
    max_tracking_quality_sum = 0.0
    first_reliable_progress_sum = 0.0
    first_reliable_progress_n = 0

    for path in summaries:
        data = load_summary(path)
        if data is None:
            continue

        metrics = data.get("metrics", {}) or {}
        n += 1
        hold_count += int(metrics.get("hold_count", 0))
        resume_count += int(metrics.get("resume_count", 0))
        soft_duck_count += int(metrics.get("soft_duck_count", 0))
        seek_count += int(metrics.get("seek_count", 0))
        lost_count += int(metrics.get("lost_count", 0))
        reacquire_count += int(metrics.get("reacquire_count", 0))
        startup_false_hold_count += int(metrics.get("startup_false_hold_count", 0))
        mean_tracking_quality_sum += float(metrics.get("mean_tracking_quality", 0.0))
        max_tracking_quality_sum += float(metrics.get("max_tracking_quality", 0.0))

        frp = metrics.get("first_reliable_progress_time_sec")
        if frp is not None:
            first_reliable_progress_sum += float(frp)
            first_reliable_progress_n += 1

    print("=== Batch Session Report ===")
    print(f"root: {root}")
    print(f"session_count: {n}")
    print(f"hold_count_total: {hold_count}")
    print(f"resume_count_total: {resume_count}")
    print(f"soft_duck_count_total: {soft_duck_count}")
    print(f"seek_count_total: {seek_count}")
    print(f"lost_count_total: {lost_count}")
    print(f"reacquire_count_total: {reacquire_count}")
    print(f"startup_false_hold_count_total: {startup_false_hold_count}")
    print(f"mean_tracking_quality_avg: {mean_tracking_quality_sum / max(1, n):.4f}")
    print(f"max_tracking_quality_avg: {max_tracking_quality_sum / max(1, n):.4f}")

    if first_reliable_progress_n > 0:
        print(f"first_reliable_progress_time_avg_sec: {first_reliable_progress_sum / first_reliable_progress_n:.4f}")
    else:
        print("first_reliable_progress_time_avg_sec: N/A")


if __name__ == "__main__":
    main()