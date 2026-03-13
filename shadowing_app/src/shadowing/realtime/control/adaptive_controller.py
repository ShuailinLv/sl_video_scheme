from __future__ import annotations

import time
from dataclasses import dataclass

from shadowing.interfaces.controller import Controller
from shadowing.types import ControlAction, ControlDecision


@dataclass
class _ReplayState:
    active: bool = False
    last_trigger_at_sec: float = 0.0
    last_committed_idx: int = 0


class AdaptiveController(Controller):
    """
    控制器骨架：
    - ducking
    - 普通 lead 控制
    - replay lock-in 检测后自动 SEEK / HOLD
    """

    def __init__(
        self,
        target_lead_sec: float = 0.35,
        max_catchup_lead_sec: float = 1.20,
        hold_lead_sec: float = 1.40,
        replay_drop_tokens: int = 3,
        replay_cooldown_sec: float = 1.2,
        replay_seek_lead_sec: float = 0.20,
        ducking_gain_speaking: float = 0.55,
        ducking_gain_transition: float = 0.75,
        base_gain: float = 1.00,
        ducking_only: bool = False,
        disable_seek: bool = False,
        disable_hold: bool = False,
    ) -> None:
        self.target_lead_sec = float(target_lead_sec)
        self.max_catchup_lead_sec = float(max_catchup_lead_sec)
        self.hold_lead_sec = float(hold_lead_sec)

        self.replay_drop_tokens = int(replay_drop_tokens)
        self.replay_cooldown_sec = float(replay_cooldown_sec)
        self.replay_seek_lead_sec = float(replay_seek_lead_sec)

        self.ducking_gain_speaking = float(ducking_gain_speaking)
        self.ducking_gain_transition = float(ducking_gain_transition)
        self.base_gain = float(base_gain)

        self.ducking_only = bool(ducking_only)
        self.disable_seek = bool(disable_seek)
        self.disable_hold = bool(disable_hold)

        self._replay = _ReplayState()
        self._last_asr_event_at_sec = 0.0

    # 如果 orchestrator 会调用 note_asr_event，就保留它
    def note_asr_event(self, event) -> None:
        try:
            self._last_asr_event_at_sec = float(event.emitted_at_sec)
        except Exception:
            self._last_asr_event_at_sec = time.monotonic()

    def note_hold(self) -> None:
        pass

    def decide(self, status, alignment):
        now = time.monotonic()

        # 默认先给一个 gain 决策
        target_gain = self.base_gain

        if alignment is None:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="no_alignment",
                target_gain=None,
            )
        lead = status.t_ref_heard_sec - alignment.ref_time_sec

        # 1) 先做 ducking
        if alignment.stable:
            target_gain = self.ducking_gain_speaking
        else:
            target_gain = self.ducking_gain_transition

        # 2) 检测 replay lock-in
        replay_detected = self._detect_replay_lockin(alignment, now)

        if replay_detected:
            # 优先 seek
            if not self.disable_seek and not self.ducking_only:
                target_time = max(0.0, alignment.ref_time_sec + self.replay_seek_lead_sec)
                return ControlDecision(
                    action=ControlAction.SEEK,
                    reason="replay_lockin_seek",
                    target_time_sec=target_time,
                    target_gain=target_gain,
                    replay_lockin=True,
                )

            # seek 禁用时退化成 hold
            if not self.disable_hold and not self.ducking_only:
                return ControlDecision(
                    action=ControlAction.HOLD,
                    reason="replay_lockin_hold",
                    target_gain=target_gain,
                    replay_lockin=True,
                )

            # 只 ducking 模式下，不做 transport 控制
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="replay_lockin_ducking_only",
                target_gain=target_gain,
                replay_lockin=True,
            )

        # 3) ducking only 模式直接返回
        if self.ducking_only:
            return ControlDecision(
                action=ControlAction.NOOP,
                reason="ducking_only",
                target_gain=target_gain,
            )

        # 4) 普通 lead 控制骨架
        # 用户明显落后：hold
        if lead > self.hold_lead_sec and not self.disable_hold:
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="lead_too_large_hold",
                target_gain=target_gain,
            )

        # 用户明显跑到前面：seek 追上
        if lead < -self.max_catchup_lead_sec and not self.disable_seek:
            target_time = max(0.0, alignment.ref_time_sec + self.target_lead_sec)
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="user_ahead_seek",
                target_time_sec=target_time,
                target_gain=target_gain,
            )

        # 在舒适带内：resume / noop
        if status.state.value == "holding" and lead <= self.target_lead_sec:
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="within_band_resume",
                target_gain=target_gain,
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="within_band",
            target_gain=target_gain,
        )

    def _detect_replay_lockin(self, alignment, now_sec: float) -> bool:
        """
        replay lock-in 判定：
        - 这次 alignment 必须 stable
        - 当前 committed 比上一轮 committed 明显回退
        - 距离上次 replay 触发超过 cooldown
        """
        current_committed = int(alignment.committed_ref_idx)
        last_committed = int(self._replay.last_committed_idx)

        detected = False

        if alignment.stable:
            dropped = last_committed - current_committed
            if (
                last_committed >= self.replay_drop_tokens + 2
                and dropped >= self.replay_drop_tokens
                and (now_sec - self._replay.last_trigger_at_sec) >= self.replay_cooldown_sec
            ):
                detected = True
                self._replay.active = True
                self._replay.last_trigger_at_sec = now_sec

        self._replay.last_committed_idx = current_committed
        return detected