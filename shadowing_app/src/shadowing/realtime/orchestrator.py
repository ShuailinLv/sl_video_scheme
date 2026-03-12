from __future__ import annotations

import queue
import threading
import time

from shadowing.interfaces.player import Player
from shadowing.interfaces.recorder import Recorder
from shadowing.interfaces.asr import ASRProvider
from shadowing.interfaces.aligner import Aligner
from shadowing.interfaces.controller import Controller
from shadowing.interfaces.repository import LessonRepository
from shadowing.types import (
    AsrEvent,
    ControlAction,
    PlayerCommand,
    PlayerCommandType,
)


class ShadowingOrchestrator:
    def __init__(
        self,
        repo: LessonRepository,
        player: Player,
        recorder: Recorder,
        asr: ASRProvider,
        aligner: Aligner,
        controller: Controller,
        audio_queue_maxsize: int = 6,
        asr_event_queue_maxsize: int = 32,
        loop_interval_sec: float = 0.03,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller

        self.audio_frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=audio_queue_maxsize)
        self.asr_event_queue: queue.Queue[AsrEvent] = queue.Queue(maxsize=asr_event_queue_maxsize)

        self.loop_interval_sec = loop_interval_sec
        self._running = False
        self._asr_thread: threading.Thread | None = None

        self._debug_enabled = False
        self._debug_heartbeat_sec = 1.0
        self._debug_print_asr = True
        self._debug_print_alignment = True
        self._debug_print_decision = True
        self._debug_print_player_status = True
        self._debug_print_reference_head = True
        self._last_heartbeat_at = 0.0

    def configure_debug(self, debug_cfg: dict) -> None:
        self._debug_enabled = bool(debug_cfg.get("enabled", False))
        self._debug_heartbeat_sec = float(debug_cfg.get("heartbeat_sec", 1.0))
        self._debug_print_asr = bool(debug_cfg.get("print_asr", True))
        self._debug_print_alignment = bool(debug_cfg.get("print_alignment", True))
        self._debug_print_decision = bool(debug_cfg.get("print_decision", True))
        self._debug_print_player_status = bool(debug_cfg.get("print_player_status", True))
        self._debug_print_reference_head = bool(debug_cfg.get("print_reference_head", True))

    def start_session(self, lesson_id: str) -> None:
        manifest = self.repo.load_manifest(lesson_id)
        ref_map = self.repo.load_reference_map(lesson_id)
        chunks = self.repo.load_audio_chunks(lesson_id)

        hotwords = manifest.lesson_text
        if hasattr(self.asr, "hotwords"):
            try:
                self.asr.hotwords = hotwords
            except Exception:
                pass

        if hasattr(self.controller, "total_duration_sec"):
            try:
                self.controller.total_duration_sec = ref_map.total_duration_sec
            except Exception:
                pass

        self.aligner.reset(ref_map)

        if self._debug_enabled and self._debug_print_reference_head:
            self._debug_print_reference_info(ref_map)

        self.player.load_chunks(chunks)
        self.asr.start()

        self._running = True
        self._asr_thread = threading.Thread(target=self._asr_worker, daemon=True)
        self._asr_thread.start()

        self.recorder.start(self._on_audio_frame)
        self.player.start()

        self._last_heartbeat_at = time.monotonic()

        while self._running:
            self._control_tick()
            self._debug_heartbeat()
            time.sleep(self.loop_interval_sec)

    def stop_session(self) -> None:
        self._running = False

        try:
            self.recorder.stop()
        except Exception:
            pass

        try:
            self.player.submit_command(
                PlayerCommand(cmd=PlayerCommandType.STOP, reason="session_stop")
            )
            self.player.stop()
        except Exception:
            pass

        try:
            self.asr.close()
        except Exception:
            pass

    def _on_audio_frame(self, pcm: bytes) -> None:
        try:
            self.audio_frame_queue.put_nowait(pcm)
        except queue.Full:
            try:
                _ = self.audio_frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_frame_queue.put_nowait(pcm)
            except queue.Full:
                pass

    def _asr_worker(self) -> None:
        while self._running:
            try:
                pcm = self.audio_frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            self.asr.feed_pcm16(pcm)
            events = self.asr.poll_events()

            for event in events:
                try:
                    self.asr_event_queue.put_nowait(event)
                except queue.Full:
                    try:
                        _ = self.asr_event_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.asr_event_queue.put_nowait(event)
                    except queue.Full:
                        pass

    def _control_tick(self) -> None:
        latest_alignment = None

        while True:
            try:
                event = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

            if self._debug_enabled and self._debug_print_asr:
                self._debug_print_asr_event(event)

            latest_alignment = self.aligner.update(event)

            if (
                self._debug_enabled
                and self._debug_print_alignment
                and latest_alignment is not None
            ):
                self._debug_print_alignment_result(latest_alignment)

        status = self.player.get_status()

        # 关键修复：播放结束后自动停机，避免 finished 后继续刷日志
        if status.state.value == "finished":
            if self._debug_enabled:
                print("[SYSTEM] player finished, stopping orchestrator.")
            self._running = False
            return

        decision = self.controller.decide(status, latest_alignment)

        if self._debug_enabled and self._debug_print_decision:
            self._debug_print_decision_result(status, latest_alignment, decision)

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

    def _debug_heartbeat(self) -> None:
        if not self._debug_enabled or not self._debug_print_player_status:
            return

        now = time.monotonic()
        if (now - self._last_heartbeat_at) < self._debug_heartbeat_sec:
            return

        status = self.player.get_status()
        print(
            "[PLAYER] "
            f"state={status.state.value} "
            f"chunk={status.chunk_id} "
            f"frame={status.frame_index} "
            f"t_sched={status.t_ref_sched_sec:.3f} "
            f"t_heard={status.t_ref_heard_sec:.3f}"
        )
        self._last_heartbeat_at = now

    def _debug_print_reference_info(self, ref_map) -> None:
        head_chars = "".join(tok.char for tok in ref_map.tokens[:20])
        head_pinyin = [tok.pinyin for tok in ref_map.tokens[:10]]
        print(f"[REF] total_tokens={len(ref_map.tokens)} total_duration={ref_map.total_duration_sec:.3f}")
        print(f"[REF] head_chars={head_chars!r}")
        print(f"[REF] head_pinyin={head_pinyin}")

    def _debug_print_asr_event(self, event: AsrEvent) -> None:
        print(
            "[ASR] "
            f"type={event.event_type.value} "
            f"text={event.text!r} "
            f"norm={event.normalized_text!r} "
            f"py={event.pinyin_seq}"
        )

    def _debug_print_alignment_result(self, alignment) -> None:
        print(
            "[ALIGN] "
            f"committed={alignment.committed_ref_idx} "
            f"candidate={alignment.candidate_ref_idx} "
            f"t_user={alignment.ref_time_sec:.3f} "
            f"conf={alignment.confidence:.3f} "
            f"stable={alignment.stable} "
            f"matched={alignment.matched_text!r}"
        )

    def _debug_print_decision_result(self, status, alignment, decision) -> None:
        lead = None
        if alignment is not None:
            lead = status.t_ref_heard_sec - alignment.ref_time_sec

        lead_str = "None" if lead is None else f"{lead:.3f}"
        target_str = (
            "None"
            if decision.target_time_sec is None
            else f"{decision.target_time_sec:.3f}"
        )

        print(
            "[CTRL] "
            f"action={decision.action.value} "
            f"reason={decision.reason} "
            f"lead={lead_str} "
            f"target={target_str} "
            f"player_state={status.state.value}"
        )