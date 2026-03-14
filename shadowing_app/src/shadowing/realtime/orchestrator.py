from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from shadowing.adaptation.profile_store import ProfileStore
from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner
from shadowing.audio.device_profile import build_device_profile
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.repository import LessonRepository
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.commercial_progress_estimator import CommercialProgressEstimator
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.realtime.asr.partial_adapter import RawPartialAdapter
from shadowing.telemetry.event_logger import EventLogger
from shadowing.telemetry.metrics import MetricsAggregator
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.types import AsrEvent, ControlAction, PlayerCommand, PlayerCommandType


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner,
        controller: Controller,
        audio_queue_maxsize: int = 150,
        asr_event_queue_maxsize: int = 64,
        loop_interval_sec: float = 0.03,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller

        self.normalizer = TextNormalizer()
        self.partial_adapter = RawPartialAdapter()
        self.signal_monitor = SignalQualityMonitor()
        self.tracking_engine = TrackingEngine(aligner=self.aligner)
        self.progress_estimator = CommercialProgressEstimator()
        self.latency_calibrator = LatencyCalibrator()

        self.audio_frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=audio_queue_maxsize)
        self.asr_event_queue: queue.Queue[AsrEvent] = queue.Queue(maxsize=asr_event_queue_maxsize)

        self.loop_interval_sec = float(loop_interval_sec)
        self._running = False
        self._asr_thread: threading.Thread | None = None
        self._last_progress = None
        self._pure_playback = False
        self._debug_enabled = False
        self._last_seen_generation = 0
        self._use_partial_adapter = True

        self._audio_frames_enqueued = 0
        self._audio_frames_dropped = 0
        self._audio_queue_high_watermark = 0
        self._asr_events_emitted = 0
        self._asr_events_dropped = 0
        self._asr_poll_iterations = 0

        self._telemetry_enabled = True
        self._session_artifacts_dir = Path("artifacts/runtime_sessions")
        self._event_logger: EventLogger | None = None
        self._metrics = MetricsAggregator()

        self._device_profile = None

        self._profile_store_enabled = True
        self._profile_store_path = Path("artifacts/adaptation/profile_store.json")
        self._profile_store: ProfileStore | None = None
        self._auto_tuner = RuntimeAutoTuner()
        self._warm_start_meta: dict = {}

    def configure_runtime(self, runtime_cfg: dict) -> None:
        self._pure_playback = bool(runtime_cfg.get("pure_playback", False))
        self._use_partial_adapter = bool(runtime_cfg.get("use_partial_adapter", True))
        self._telemetry_enabled = bool(runtime_cfg.get("telemetry_enabled", True))
        self._session_artifacts_dir = Path(runtime_cfg.get("session_artifacts_dir", "artifacts/runtime_sessions"))

        self._profile_store_enabled = bool(runtime_cfg.get("profile_store_enabled", True))
        self._profile_store_path = Path(runtime_cfg.get("profile_store_path", "artifacts/adaptation/profile_store.json"))
        self._profile_store = ProfileStore(str(self._profile_store_path))

    def configure_debug(self, debug_cfg: dict) -> None:
        self._debug_enabled = bool(debug_cfg.get("enabled", False))
        self.partial_adapter.debug = bool(debug_cfg.get("adapter_debug", False))

        if hasattr(self.aligner, "debug"):
            try:
                self.aligner.debug = bool(debug_cfg.get("aligner_debug", False))
            except Exception:
                pass

        try:
            self.tracking_engine.debug = bool(debug_cfg.get("tracking_debug", False))
        except Exception:
            pass

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        if hasattr(self.controller, "total_duration_sec"):
            self.controller.total_duration_sec = ref_map.total_duration_sec

        now_sec = time.monotonic()
        self._metrics = MetricsAggregator()
        self._metrics.mark_session_started(now_sec)

        session_dir = self._session_artifacts_dir / lesson_id / time.strftime("%Y%m%d_%H%M%S")
        self._event_logger = EventLogger(str(session_dir), enabled=self._telemetry_enabled)

        self._device_profile = build_device_profile(
            input_device_name=getattr(self.recorder, "device", None),
            output_device_name=getattr(self.player.config, "device", None) if hasattr(self.player, "config") else None,
            input_sample_rate=int(getattr(self.recorder, "target_sample_rate", getattr(self.recorder, "sample_rate_in", 16000))),
            output_sample_rate=int(getattr(self.player.config, "sample_rate", 44100)) if hasattr(self.player, "config") else 44100,
            noise_floor_rms=0.0025,
        )
        self.latency_calibrator.reset(self._device_profile)

        warm_start = {}
        if self._profile_store_enabled and self._profile_store is not None:
            warm_start = self._profile_store.load_warm_start(
                input_device_id=self._device_profile.input_device_id,
                output_device_id=self._device_profile.output_device_id,
            )
            self._warm_start_meta = dict(warm_start.get("meta", {}))
        else:
            self._warm_start_meta = {}

        self._auto_tuner.reset(self._device_profile.reliability_tier)
        self._auto_tuner.apply_warm_start(
            controller_policy=self.controller.policy,
            player=self.player,
            signal_monitor=self.signal_monitor,
            warm_start=warm_start,
        )

        self._event_logger.log(
            "session_started",
            {
                "lesson_id": lesson_id,
                "lesson_text_length": len(manifest.lesson_text),
                "sample_rate_out": manifest.sample_rate_out,
                "chunk_count": len(chunks),
                "ref_token_count": len(ref_map.tokens),
                "total_duration_sec": ref_map.total_duration_sec,
                "device_profile": {
                    "input_device_id": self._device_profile.input_device_id,
                    "output_device_id": self._device_profile.output_device_id,
                    "input_kind": self._device_profile.input_kind,
                    "output_kind": self._device_profile.output_kind,
                    "input_sample_rate": self._device_profile.input_sample_rate,
                    "output_sample_rate": self._device_profile.output_sample_rate,
                    "estimated_input_latency_ms": self._device_profile.estimated_input_latency_ms,
                    "estimated_output_latency_ms": self._device_profile.estimated_output_latency_ms,
                    "noise_floor_rms": self._device_profile.noise_floor_rms,
                    "input_gain_hint": self._device_profile.input_gain_hint,
                    "reliability_tier": self._device_profile.reliability_tier,
                },
                "warm_start_meta": self._warm_start_meta,
                "policy_after_warm_start": self._policy_snapshot(),
            },
        )

        self.tracking_engine.reset(ref_map)
        self.progress_estimator.reset(ref_map, start_idx=0)
        self.player.load_chunks(chunks)

        self._running = True
        self._last_seen_generation = 0
        self._last_progress = None
        self._audio_frames_enqueued = 0
        self._audio_frames_dropped = 0
        self._audio_queue_high_watermark = 0
        self._asr_events_emitted = 0
        self._asr_events_dropped = 0
        self._asr_poll_iterations = 0

        self.player.start()

        if not self._pure_playback:
            if hasattr(self.asr, "hotwords"):
                try:
                    self.asr.hotwords = manifest.lesson_text
                except Exception:
                    pass

            self.partial_adapter.reset()
            self.asr.start()
            self._asr_thread = threading.Thread(target=self._asr_worker, daemon=True)
            self._asr_thread.start()
            self.recorder.start(self._on_audio_frame)

        while self._running:
            self._control_tick()
            time.sleep(self.loop_interval_sec)

    def stop_session(self) -> None:
        self._running = False

        if not self._pure_playback:
            try:
                self.recorder.stop()
            except Exception:
                pass

            try:
                self.asr.close()
            except Exception:
                pass

            if self._asr_thread is not None and self._asr_thread.is_alive():
                self._asr_thread.join(timeout=1.0)
            self._asr_thread = None

        try:
            self.player.stop()
            self.player.close()
        except Exception:
            pass

        latency_snapshot = self.latency_calibrator.snapshot()
        metrics_dict = self._metrics.summary_dict()

        if self._profile_store_enabled and self._profile_store is not None and self._device_profile is not None:
            self._profile_store.update_from_session(
                input_device_id=self._device_profile.input_device_id,
                output_device_id=self._device_profile.output_device_id,
                device_profile={
                    "input_device_id": self._device_profile.input_device_id,
                    "output_device_id": self._device_profile.output_device_id,
                    "input_kind": self._device_profile.input_kind,
                    "output_kind": self._device_profile.output_kind,
                    "input_sample_rate": self._device_profile.input_sample_rate,
                    "output_sample_rate": self._device_profile.output_sample_rate,
                    "estimated_input_latency_ms": self._device_profile.estimated_input_latency_ms,
                    "estimated_output_latency_ms": self._device_profile.estimated_output_latency_ms,
                    "noise_floor_rms": self._device_profile.noise_floor_rms,
                    "input_gain_hint": self._device_profile.input_gain_hint,
                    "reliability_tier": self._device_profile.reliability_tier,
                },
                metrics=metrics_dict,
                latency_calibration=(
                    {
                        "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                        "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                        "confidence": latency_snapshot.confidence,
                        "calibrated": latency_snapshot.calibrated,
                    }
                    if latency_snapshot is not None
                    else None
                ),
            )

        if self._event_logger is not None:
            self._event_logger.log(
                "session_summary",
                {
                    "metrics": metrics_dict,
                    "latency_calibration": (
                        {
                            "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                            "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                            "confidence": latency_snapshot.confidence,
                            "calibrated": latency_snapshot.calibrated,
                        }
                        if latency_snapshot is not None
                        else None
                    ),
                    "final_policy": self._policy_snapshot(),
                    "orchestrator_stats": {
                        "audio_enqueued": self._audio_frames_enqueued,
                        "audio_dropped": self._audio_frames_dropped,
                        "audio_q_high_watermark": self._audio_queue_high_watermark,
                        "asr_events_emitted": self._asr_events_emitted,
                        "asr_events_dropped": self._asr_events_dropped,
                        "asr_poll_iterations": self._asr_poll_iterations,
                        "use_partial_adapter": self._use_partial_adapter,
                    },
                },
            )

            summary_path = self._event_logger.session_dir / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "metrics": metrics_dict,
                        "latency_calibration": (
                            {
                                "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                                "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                                "confidence": latency_snapshot.confidence,
                                "calibrated": latency_snapshot.calibrated,
                            }
                            if latency_snapshot is not None
                            else None
                        ),
                        "final_policy": self._policy_snapshot(),
                        "orchestrator_stats": {
                            "audio_enqueued": self._audio_frames_enqueued,
                            "audio_dropped": self._audio_frames_dropped,
                            "audio_q_high_watermark": self._audio_queue_high_watermark,
                            "asr_events_emitted": self._asr_events_emitted,
                            "asr_events_dropped": self._asr_events_dropped,
                            "asr_poll_iterations": self._asr_poll_iterations,
                            "use_partial_adapter": self._use_partial_adapter,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        if self._debug_enabled:
            print(
                "[ORCH-STATS] "
                f"audio_enqueued={self._audio_frames_enqueued} "
                f"audio_dropped={self._audio_frames_dropped} "
                f"audio_q_high_watermark={self._audio_queue_high_watermark}/{self.audio_frame_queue.maxsize} "
                f"asr_events_emitted={self._asr_events_emitted} "
                f"asr_events_dropped={self._asr_events_dropped} "
                f"asr_poll_iterations={self._asr_poll_iterations} "
                f"use_partial_adapter={self._use_partial_adapter}"
            )

    def _on_audio_frame(self, pcm: bytes) -> None:
        now_sec = time.monotonic()
        self.signal_monitor.feed_pcm16(pcm, observed_at_sec=now_sec)

        signal_snapshot = self.signal_monitor.snapshot(now_sec)
        self.latency_calibrator.observe_signal(signal_snapshot)

        if self._device_profile is not None:
            self._device_profile.noise_floor_rms = (
                signal_snapshot.rms
                if signal_snapshot.rms < 0.004
                else self._device_profile.noise_floor_rms
            )

        if signal_snapshot.vad_active or signal_snapshot.speaking_likelihood >= 0.48:
            self._metrics.observe_signal_active(now_sec)

        try:
            self.audio_frame_queue.put_nowait(pcm)
            self._audio_frames_enqueued += 1
            current_qsize = self.audio_frame_queue.qsize()
            if current_qsize > self._audio_queue_high_watermark:
                self._audio_queue_high_watermark = current_qsize
        except queue.Full:
            self._audio_frames_dropped += 1
            try:
                _ = self.audio_frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_frame_queue.put_nowait(pcm)
                self._audio_frames_enqueued += 1
                current_qsize = self.audio_frame_queue.qsize()
                if current_qsize > self._audio_queue_high_watermark:
                    self._audio_queue_high_watermark = current_qsize
            except queue.Full:
                self._audio_frames_dropped += 1

    def _asr_worker(self) -> None:
        while self._running and not self._pure_playback:
            try:
                pcm = self.audio_frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            self._asr_poll_iterations += 1
            self.asr.feed_pcm16(pcm)
            raw_events = self.asr.poll_raw_events()

            for raw in raw_events:
                candidate = raw
                if self._use_partial_adapter:
                    candidate = self.partial_adapter.adapt(raw)
                    if candidate is None:
                        continue

                normalized = self.normalizer.normalize_raw_event(candidate)
                if normalized is None:
                    continue

                if normalized.event_type.value == "partial":
                    self._metrics.observe_asr_partial(time.monotonic())

                if self._event_logger is not None:
                    self._event_logger.log(
                        "asr_event",
                        {
                            "event_type": normalized.event_type.value,
                            "text": normalized.text,
                            "normalized_text": normalized.normalized_text,
                            "chars_len": len(normalized.chars),
                            "emitted_at_sec": normalized.emitted_at_sec,
                        },
                    )

                try:
                    self.asr_event_queue.put_nowait(normalized)
                    self._asr_events_emitted += 1
                except queue.Full:
                    self._asr_events_dropped += 1
                    try:
                        _ = self.asr_event_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.asr_event_queue.put_nowait(normalized)
                        self._asr_events_emitted += 1
                    except queue.Full:
                        self._asr_events_dropped += 1

    def _handle_generation_change_if_needed(self, status) -> None:
        if status.generation == self._last_seen_generation:
            return

        if self._debug_enabled:
            print(f"[SYNC] playback generation changed {self._last_seen_generation} -> {status.generation}")

        self._last_seen_generation = status.generation
        self._last_progress = None

        while True:
            try:
                _ = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

        now_sec = time.monotonic()
        self.tracking_engine.on_playback_generation_changed(status.generation)
        self.progress_estimator.on_playback_generation_changed(now_sec)

        if self._event_logger is not None:
            self._event_logger.log(
                "playback_generation_changed",
                {
                    "generation": status.generation,
                    "observed_at_sec": now_sec,
                },
            )

    def _control_tick(self) -> None:
        status = self.player.get_status()
        self._handle_generation_change_if_needed(status)

        now_sec = time.monotonic()
        signal_snapshot = self.signal_monitor.snapshot(now_sec)

        if self._event_logger is not None:
            self._event_logger.log(
                "signal_snapshot",
                {
                    "observed_at_sec": signal_snapshot.observed_at_sec,
                    "rms": signal_snapshot.rms,
                    "peak": signal_snapshot.peak,
                    "vad_active": signal_snapshot.vad_active,
                    "speaking_likelihood": signal_snapshot.speaking_likelihood,
                    "silence_run_sec": signal_snapshot.silence_run_sec,
                    "quality_score": signal_snapshot.quality_score,
                },
            )

        while not self._pure_playback:
            try:
                event = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

            tracking_snapshot = self.tracking_engine.update(event)
            if tracking_snapshot is not None:
                self._metrics.observe_tracking_mode(tracking_snapshot.tracking_mode.value)

                if self._event_logger is not None:
                    self._event_logger.log(
                        "tracking_snapshot",
                        {
                            "candidate_ref_idx": tracking_snapshot.candidate_ref_idx,
                            "committed_ref_idx": tracking_snapshot.committed_ref_idx,
                            "candidate_ref_time_sec": tracking_snapshot.candidate_ref_time_sec,
                            "confidence": tracking_snapshot.confidence,
                            "stable": tracking_snapshot.stable,
                            "local_match_ratio": tracking_snapshot.local_match_ratio,
                            "repeat_penalty": tracking_snapshot.repeat_penalty,
                            "monotonic_consistency": tracking_snapshot.monotonic_consistency,
                            "anchor_consistency": tracking_snapshot.anchor_consistency,
                            "tracking_mode": tracking_snapshot.tracking_mode.value,
                            "tracking_quality": {
                                "overall_score": tracking_snapshot.tracking_quality.overall_score,
                                "observation_score": tracking_snapshot.tracking_quality.observation_score,
                                "temporal_consistency_score": tracking_snapshot.tracking_quality.temporal_consistency_score,
                                "anchor_score": tracking_snapshot.tracking_quality.anchor_score,
                                "is_reliable": tracking_snapshot.tracking_quality.is_reliable,
                            },
                            "matched_text": tracking_snapshot.matched_text,
                            "emitted_at_sec": tracking_snapshot.emitted_at_sec,
                        },
                    )

                self.latency_calibrator.observe_progress(float(tracking_snapshot.emitted_at_sec))

                self._last_progress = self.progress_estimator.update(
                    tracking_snapshot,
                    signal_snapshot,
                    now_sec,
                )

                if self._last_progress is not None:
                    self._metrics.observe_progress(
                        now_sec=now_sec,
                        tracking_quality=self._last_progress.tracking_quality,
                        is_reliable=self._last_progress.tracking_quality >= 0.66,
                    )

        status = self.player.get_status()

        if status.state.value == "finished":
            self._running = False
            return

        if self._pure_playback:
            return

        latest_progress = self.progress_estimator.snapshot(now_sec, signal_snapshot)
        self._last_progress = latest_progress

        if latest_progress is not None and self._event_logger is not None:
            self._event_logger.log(
                "progress_snapshot",
                {
                    "estimated_ref_idx": latest_progress.estimated_ref_idx,
                    "estimated_ref_time_sec": latest_progress.estimated_ref_time_sec,
                    "progress_velocity_idx_per_sec": latest_progress.progress_velocity_idx_per_sec,
                    "progress_age_sec": latest_progress.progress_age_sec,
                    "source_candidate_ref_idx": latest_progress.source_candidate_ref_idx,
                    "source_committed_ref_idx": latest_progress.source_committed_ref_idx,
                    "tracking_mode": latest_progress.tracking_mode.value,
                    "tracking_quality": latest_progress.tracking_quality,
                    "stable": latest_progress.stable,
                    "confidence": latest_progress.confidence,
                    "active_speaking": latest_progress.active_speaking,
                    "recently_progressed": latest_progress.recently_progressed,
                    "user_state": latest_progress.user_state.value,
                    "event_emitted_at_sec": latest_progress.event_emitted_at_sec,
                    "last_progress_at_sec": latest_progress.last_progress_at_sec,
                },
            )

        latency_snapshot = self.latency_calibrator.snapshot()
        if latency_snapshot is not None and self._event_logger is not None:
            self._event_logger.log(
                "latency_calibration",
                {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                },
            )

        tuning_updates = self._auto_tuner.maybe_tune(
            now_sec=now_sec,
            controller_policy=self.controller.policy,
            player=self.player,
            signal_monitor=self.signal_monitor,
            metrics_summary=self._metrics.summary_dict(),
            signal_quality=signal_snapshot,
            progress=latest_progress,
            latency_snapshot=latency_snapshot,
            device_profile=self._device_profile,
        )
        if tuning_updates and self._event_logger is not None:
            self._event_logger.log(
                "auto_tuning_update",
                {
                    "updates": tuning_updates,
                    "policy_after_update": self._policy_snapshot(),
                },
            )

        decision = self.controller.decide(status, latest_progress, signal_snapshot)
        self._metrics.observe_action(
            action=decision.action.value,
            reason=decision.reason,
            now_sec=now_sec,
        )

        if self._event_logger is not None:
            self._event_logger.log(
                "control_decision",
                {
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "target_time_sec": decision.target_time_sec,
                    "lead_sec": decision.lead_sec,
                    "target_gain": decision.target_gain,
                    "confidence": decision.confidence,
                    "aggressiveness": decision.aggressiveness,
                    "playback_state": status.state.value,
                    "playback_generation": status.generation,
                    "t_ref_heard_content_sec": status.t_ref_heard_content_sec,
                    "t_ref_emitted_content_sec": status.t_ref_emitted_content_sec,
                },
            )

        if decision.target_gain is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SET_GAIN,
                    gain=decision.target_gain,
                    reason="adaptive_ducking",
                )
            )

        if decision.action == ControlAction.HOLD:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.HOLD, reason=decision.reason)
            )
        elif decision.action == ControlAction.RESUME:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.RESUME, reason=decision.reason)
            )
        elif decision.action == ControlAction.SEEK and decision.target_time_sec is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SEEK,
                    target_time_sec=decision.target_time_sec,
                    reason=decision.reason,
                )
            )
        elif decision.action == ControlAction.STOP:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.STOP, reason=decision.reason)
            )
            self._running = False

    def _policy_snapshot(self) -> dict:
        p = self.controller.policy
        return {
            "guide_play_sec": p.guide_play_sec,
            "no_progress_hold_min_play_sec": p.no_progress_hold_min_play_sec,
            "progress_stale_sec": p.progress_stale_sec,
            "hold_trend_sec": p.hold_trend_sec,
            "tracking_quality_hold_min": p.tracking_quality_hold_min,
            "tracking_quality_seek_min": p.tracking_quality_seek_min,
            "resume_from_hold_speaking_lead_slack_sec": p.resume_from_hold_speaking_lead_slack_sec,
            "gain_soft_duck": p.gain_soft_duck,
        }