from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
from statistics import mean
from shadowing.telemetry.replay_loader import ReplayLoader


@dataclass(slots=True)
class SessionEvaluationSummary:
    session_dir: str
    hold_count: int = 0
    seek_count: int = 0
    soft_duck_count: int = 0
    false_hold_count: int = 0
    false_seek_count: int = 0
    reacquire_count: int = 0
    mean_reacquire_latency_sec: float = 0.0
    p95_reacquire_latency_sec: float = 0.0
    max_reacquire_latency_sec: float = 0.0
    startup_first_reliable_progress_time_sec: float | None = None
    mean_tracking_quality: float = 0.0
    max_tracking_quality: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class SessionEvaluator:
    def __init__(self, events_file: str, summary_file: str | None = None) -> None:
        self.events_file = Path(events_file)
        self.summary_file = Path(summary_file) if summary_file else self.events_file.with_name("summary.json")

    def evaluate(self) -> SessionEvaluationSummary:
        loader = ReplayLoader(str(self.events_file))
        out = SessionEvaluationSummary(session_dir=str(self.events_file.parent))
        tracking_scores: list[float] = []
        reacquire_started_at: float | None = None
        reacquire_latencies: list[float] = []
        recent_signal = 0.0
        recent_audio_follow = 0.0
        recent_audio_repeat = 0.0
        recent_progress_follow = False
        recent_progress_conf = 0.0
        seek_recovered_fast = False
        last_seek_ts: float | None = None
        for ev in loader:
            ts = float(ev.ts_monotonic_sec or 0.0)
            if ev.event_type == "signal_snapshot":
                recent_signal = max(float(ev.payload.get("speaking_likelihood", 0.0)), 0.75 if ev.payload.get("vad_active") else 0.0)
            elif ev.event_type == "audio_behavior_snapshot":
                recent_audio_follow = float(ev.payload.get("still_following_likelihood", 0.0))
                recent_audio_repeat = float(ev.payload.get("repeated_likelihood", 0.0))
            elif ev.event_type == "fusion_evidence":
                recent_audio_follow = max(recent_audio_follow, float(ev.payload.get("still_following_likelihood", 0.0)))
                recent_audio_repeat = max(recent_audio_repeat, float(ev.payload.get("repeated_likelihood", 0.0)))
            elif ev.event_type == "progress_snapshot":
                recent_progress_follow = bool(ev.payload.get("active_speaking", False) or ev.payload.get("recently_progressed", False))
                recent_progress_conf = float(ev.payload.get("confidence", 0.0))
                tq = float(ev.payload.get("tracking_quality", 0.0))
                tracking_scores.append(tq)
            elif ev.event_type == "tracking_snapshot":
                tracking_scores.append(float(ev.payload.get("overall_score", 0.0)))
                mode = str(ev.payload.get("tracking_mode", ""))
                if mode == "reacquiring" and reacquire_started_at is None:
                    reacquire_started_at = ts
                elif reacquire_started_at is not None and mode in {"locked", "weak_locked"} and float(ev.payload.get("overall_score", 0.0)) >= 0.58:
                    reacquire_latencies.append(max(0.0, ts - reacquire_started_at))
                    reacquire_started_at = None
            elif ev.event_type == "control_decision":
                action = str(ev.payload.get("action", ""))
                if action == "hold":
                    out.hold_count += 1
                    if recent_progress_follow or recent_progress_conf >= 0.64 or recent_audio_follow >= 0.68 or recent_signal >= 0.58:
                        out.false_hold_count += 1
                elif action == "seek":
                    out.seek_count += 1
                    last_seek_ts = ts
                    seek_recovered_fast = False
                    if recent_audio_repeat >= 0.62:
                        out.false_seek_count += 1
                elif action == "soft_duck":
                    out.soft_duck_count += 1
            elif ev.event_type == "session_summary":
                metrics = ev.payload.get("metrics", {})
                out.startup_first_reliable_progress_time_sec = metrics.get("first_reliable_progress_time_sec")
                out.mean_tracking_quality = float(metrics.get("mean_tracking_quality", out.mean_tracking_quality))
                out.max_tracking_quality = float(metrics.get("max_tracking_quality", out.max_tracking_quality))
            if last_seek_ts is not None and ts > 0.0 and (ts - last_seek_ts) <= 1.6 and recent_progress_conf >= 0.74:
                seek_recovered_fast = True
            if last_seek_ts is not None and ts > 0.0 and (ts - last_seek_ts) > 1.8:
                if not seek_recovered_fast and out.seek_count > 0:
                    out.false_seek_count += 1
                last_seek_ts = None
                seek_recovered_fast = False
        if self.summary_file.exists():
            try:
                data = json.loads(self.summary_file.read_text(encoding="utf-8"))
                metrics = data.get("metrics", {})
                out.startup_first_reliable_progress_time_sec = metrics.get("first_reliable_progress_time_sec", out.startup_first_reliable_progress_time_sec)
                out.mean_tracking_quality = float(metrics.get("mean_tracking_quality", out.mean_tracking_quality))
                out.max_tracking_quality = float(metrics.get("max_tracking_quality", out.max_tracking_quality))
            except Exception:
                pass
        if tracking_scores and out.mean_tracking_quality <= 0.0:
            out.mean_tracking_quality = float(mean(tracking_scores))
            out.max_tracking_quality = float(max(tracking_scores))
        out.reacquire_count = len(reacquire_latencies)
        if reacquire_latencies:
            vals = sorted(reacquire_latencies)
            out.mean_reacquire_latency_sec = float(mean(vals))
            out.max_reacquire_latency_sec = float(max(vals))
            p95_index = min(len(vals) - 1, max(0, int(round(0.95 * (len(vals) - 1)))))
            out.p95_reacquire_latency_sec = float(vals[p95_index])
        return out
