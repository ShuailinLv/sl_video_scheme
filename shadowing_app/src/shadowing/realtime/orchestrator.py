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

        self.aligner.reset(ref_map)
        self.player.load_chunks(chunks)
        self.asr.start()

        self._running = True
        self._asr_thread = threading.Thread(target=self._asr_worker, daemon=True)
        self._asr_thread.start()

        self.recorder.start(self._on_audio_frame)
        self.player.start()

        while self._running:
            self._control_tick()
            time.sleep(self.loop_interval_sec)

    def stop_session(self) -> None:
        self._running = False

        try:
            self.recorder.stop()
        except Exception:
            pass

        try:
            self.player.submit_command(PlayerCommand(cmd=PlayerCommandType.STOP, reason="session_stop"))
            self.player.stop()
        except Exception:
            pass

        try:
            self.asr.close()
        except Exception:
            pass

    def _on_audio_frame(self, pcm: bytes) -> None:
        """
        录音 callback 线程调用。
        绝不阻塞。
        队列满时丢最旧帧，保实时性。
        """
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
        """
        单独线程：
        - 消费录音 PCM
        - 喂给 ASR
        - 拉取 ASR 事件
        - 放入 asr_event_queue
        """
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
        """
        主控制循环：
        - 尽量清空当前轮 ASR 事件
        - 用最后一个较新的对齐结果做决策
        """
        latest_alignment = None

        while True:
            try:
                event = self.asr_event_queue.get_nowait()
            except queue.Empty:
                break

            latest_alignment = self.aligner.update(event)

        status = self.player.get_status()
        decision = self.controller.decide(status, latest_alignment)

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