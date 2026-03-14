from __future__ import annotations

import queue
import threading
import time

from shadowing.interfaces.aligner import Aligner
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.repository import LessonRepository
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.realtime.asr.partial_adapter import RawPartialAdapter
from shadowing.types import AlignResult, AsrEvent, ControlAction, PlayerCommand, PlayerCommandType


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner: Aligner,
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

        self.audio_frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=audio_queue_maxsize)
        self.asr_event_queue: queue.Queue[AsrEvent] = queue.Queue(maxsize=asr_event_queue_maxsize)

        self.loop_interval_sec = float(loop_interval_sec)
        self._running = False
        self._asr_thread: threading.Thread | None = None
        self._last_alignment: AlignResult | None = None
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

    def configure_runtime(self, runtime_cfg: dict) -> None:
        self._pure_playback = bool(runtime_cfg.get("pure_playback", False))
        self._use_partial_adapter = bool(runtime_cfg.get("use_partial_adapter", True))

    def configure_debug(self, debug_cfg: dict) -> None:
        self._debug_enabled = bool(debug_cfg.get("enabled", False))
        self.partial_adapter.debug = bool(debug_cfg.get("adapter_debug", False))

        if hasattr(self.aligner, "debug"):
            try:
                self.aligner.debug = bool(debug_cfg.get("aligner_debug", False))
            except Exception:
                pass

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        if hasattr(self.controller, "total_duration_sec"):
            self.controller.total_duration_sec = ref_map.total_duration_sec

        self.aligner.reset(ref_map)
        self.player.load_chunks(chunks)

        self._running = True
        self._last_seen_generation = 0
        self._last_alignment = None
        self._audio_frames_enqueued = 0
        self._audio_frames_dropped = 0
        self._audio_queue_high_watermark = 0
        self._asr_events_emitted = 0
        self._asr_events_dropped = 0
        self._asr_poll_iterations = 0

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

        self.player.start()

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
        self._last_alignment = None

        while True:
            try:
                _ = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

        self.aligner.on_playback_generation_changed(status.generation)

    def _control_tick(self) -> None:
        status = self.player.get_status()
        self._handle_generation_change_if_needed(status)

        latest_alignment = self._last_alignment
        while not self._pure_playback:
            try:
                event = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

            latest_alignment = self.aligner.update(event)
            if latest_alignment is not None:
                self._last_alignment = latest_alignment

        status = self.player.get_status()

        if status.state.value == "finished":
            self._running = False
            return

        if self._pure_playback:
            return

        decision = self.controller.decide(status, latest_alignment)

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