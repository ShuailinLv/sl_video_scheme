from __future__ import annotations

from shadowing.progress.behavior_interpreter import BehaviorInterpreter
from shadowing.types import (
    ProgressEstimate,
    ReferenceMap,
    SignalQuality,
    TrackingMode,
    TrackingSnapshot,
    UserReadState,
)


class AudioAwareProgressEstimator:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        active_speaking_signal_min: float = 0.45,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.active_speaking_signal_min = float(active_speaking_signal_min)

        self._audio_takeover_conf = 0.70
        self._audio_assist_conf = 0.58
        self._max_audio_jump_sec = 1.20
        self._max_disagreement_for_joint_sec = 1.0

        self.behavior_interpreter = BehaviorInterpreter(recent_progress_sec=recent_progress_sec)

        self._ref_map: ReferenceMap | None = None
        self._ref_times: list[float] = []

        self._estimated_ref_time_sec_f = 0.0
        self._estimated_velocity_ref_sec_per_sec = 0.0
        self._last_update_now_sec = 0.0

        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_tracking: TrackingSnapshot | None = None
        self._last_snapshot: ProgressEstimate | None = None
        self._force_reacquire_until_sec = 0.0
        self._last_audio_progress_at_sec = 0.0

        self._text_stability_run = 0
        self._audio_stability_run = 0
        self._last_text_obs_time_sec: float | None = None
        self._last_audio_obs_time_sec: float | None = None

    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._ref_times = [float(t.t_start) for t in reference_map.tokens]
        start_time = self._ref_times[start_idx] if self._ref_times else 0.0

        self._estimated_ref_time_sec_f = float(start_time)
        self._estimated_velocity_ref_sec_per_sec = 0.0
        self._last_update_now_sec = 0.0

        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_tracking = None
        self._last_snapshot = None
        self._force_reacquire_until_sec = 0.0
        self._last_audio_progress_at_sec = 0.0

        self._text_stability_run = 0
        self._audio_stability_run = 0
        self._last_text_obs_time_sec = None
        self._last_audio_obs_time_sec = None

    def on_playback_generation_changed(self, now_sec: float) -> None:
        self._force_reacquire_until_sec = float(now_sec) + 0.80

    def update(
        self,
        *,
        tracking: TrackingSnapshot | None,
        audio_match,
        audio_behavior,
        signal_quality: SignalQuality | None,
        now_sec: float,
    ) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None

        if self._last_update_now_sec <= 0.0:
            dt = 0.0
        else:
            dt = max(0.0, min(0.35, float(now_sec) - self._last_update_now_sec))
        self._last_update_now_sec = float(now_sec)

        if tracking is not None:
            self._last_tracking = tracking
            self._last_event_at_sec = float(tracking.emitted_at_sec)

        # 1) 先做时间域预测
        self._predict_forward(dt=dt, signal_quality=signal_quality)

        # 2) 构造 text observation
        text_obs_time_sec = None
        text_obs_weight = 0.0
        text_candidate_idx = self._time_to_ref_idx(self._estimated_ref_time_sec_f)
        text_committed_idx = text_candidate_idx
        tracking_mode = TrackingMode.BOOTSTRAP
        text_quality = 0.0
        text_conf = 0.0
        stable = False

        if tracking is not None:
            text_candidate_idx = int(tracking.candidate_ref_idx)
            text_committed_idx = int(tracking.committed_ref_idx)
            tracking_mode = tracking.tracking_mode
            text_quality = float(tracking.tracking_quality.overall_score)
            text_conf = float(tracking.confidence)
            stable = bool(tracking.stable)

            base_idx = max(text_candidate_idx, text_committed_idx)
            text_obs_time_sec = self._idx_to_ref_time(base_idx)
            text_obs_weight = self._text_observation_weight(tracking)

            if tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
                if self._last_text_obs_time_sec is None or abs(text_obs_time_sec - self._last_text_obs_time_sec) <= 0.45:
                    self._text_stability_run += 1
                else:
                    self._text_stability_run = 1
                self._last_text_obs_time_sec = text_obs_time_sec
            else:
                self._text_stability_run = 0

        # 3) 构造 audio observation
        audio_obs_time_sec = None
        audio_obs_weight = 0.0
        audio_conf = 0.0
        repeated = 0.0
        reentry = 0.0
        still_following = 0.0
        paused = 0.0
        audio_mode = "tracking"

        if audio_match is not None:
            audio_obs_time_sec = float(getattr(audio_match, "estimated_ref_time_sec", self._estimated_ref_time_sec_f))
            audio_conf = float(getattr(audio_match, "confidence", 0.0))
            repeated = float(getattr(audio_match, "repeated_pattern_score", 0.0))
            audio_mode = str(getattr(audio_match, "mode", "tracking"))

        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.96)
            still_following = float(getattr(audio_behavior, "still_following_likelihood", 0.0))
            repeated = max(repeated, float(getattr(audio_behavior, "repeated_likelihood", 0.0)))
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            paused = float(getattr(audio_behavior, "paused_likelihood", 0.0))

        if audio_obs_time_sec is not None:
            audio_obs_weight = self._audio_observation_weight(
                audio_conf=audio_conf,
                text_quality=text_quality,
                repeated=repeated,
                reentry=reentry,
                still_following=still_following,
                paused=paused,
                audio_mode=audio_mode,
            )
            if self._last_audio_obs_time_sec is None or abs(audio_obs_time_sec - self._last_audio_obs_time_sec) <= 0.55:
                self._audio_stability_run += 1
            else:
                self._audio_stability_run = 1
            self._last_audio_obs_time_sec = audio_obs_time_sec

        # 4) 行为守门：repeat / reentry / pause
        position_source = "text"
        est_before = float(self._estimated_ref_time_sec_f)

        if repeated >= 0.68:
            # 重复时：不允许主进度后退，也不允许音频强推向前
            audio_obs_weight *= 0.18
            text_obs_weight *= 0.90
        elif paused >= 0.72 and still_following < 0.58:
            audio_obs_weight *= 0.35
            text_obs_weight *= 0.70
        elif reentry >= 0.64:
            audio_obs_weight = max(audio_obs_weight, 0.72)
        elif still_following >= 0.72 and text_quality < 0.56:
            audio_obs_weight = max(audio_obs_weight, 0.58)

        # 5) 时间域连续融合
        if text_obs_time_sec is not None and audio_obs_time_sec is not None:
            disagreement = abs(audio_obs_time_sec - text_obs_time_sec)

            if disagreement <= self._max_disagreement_for_joint_sec:
                fused_obs = (
                    text_obs_weight * text_obs_time_sec + audio_obs_weight * audio_obs_time_sec
                ) / max(1e-6, text_obs_weight + audio_obs_weight)
                fused_weight = max(text_obs_weight, audio_obs_weight, 0.18)
                self._pull_toward_observation(fused_obs, fused_weight)
                position_source = "joint"
            elif audio_obs_weight >= 0.76 and text_obs_weight < 0.42 and reentry >= 0.56:
                self._pull_toward_observation(audio_obs_time_sec, audio_obs_weight)
                position_source = "audio"
            else:
                self._pull_toward_observation(text_obs_time_sec, text_obs_weight)
                position_source = "text"
        elif text_obs_time_sec is not None:
            self._pull_toward_observation(text_obs_time_sec, text_obs_weight)
            position_source = "text"
        elif audio_obs_time_sec is not None:
            if audio_obs_weight >= self._audio_assist_conf:
                self._pull_toward_observation(audio_obs_time_sec, audio_obs_weight)
                position_source = "audio" if audio_obs_weight >= self._audio_takeover_conf else "joint"

        # 6) 单调约束与局部限速
        self._apply_monotonic_constraints(
            prev_est_ref_time_sec=est_before,
            text_obs_time_sec=text_obs_time_sec,
            audio_obs_time_sec=audio_obs_time_sec,
            repeated=repeated,
            reentry=reentry,
            paused=paused,
            now_sec=now_sec,
        )

        progressed = self._estimated_ref_time_sec_f > est_before + 1e-4
        if progressed:
            self._last_progress_at_sec = float(now_sec)
            if audio_obs_weight >= self._audio_assist_conf:
                self._last_audio_progress_at_sec = float(now_sec)

        self._last_snapshot = self._render_snapshot(
            now_sec=now_sec,
            signal_quality=signal_quality,
            tracking_mode=tracking_mode,
            tracking_quality=text_quality,
            confidence=text_conf,
            stable=stable,
            source_candidate_ref_idx=text_candidate_idx,
            source_committed_ref_idx=text_committed_idx,
            audio_conf=audio_conf,
            still_following=still_following,
            reentry=reentry,
            position_source=position_source,
        )
        return self._last_snapshot

    def snapshot(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        audio_match=None,
        audio_behavior=None,
    ) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None

        audio_conf = 0.0
        still_following = 0.0
        reentry = 0.0
        position_source = "text"

        if audio_match is not None:
            audio_conf = float(getattr(audio_match, "confidence", 0.0))
            still_following = max(still_following, audio_conf * 0.80)
        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.96)
            still_following = max(still_following, float(getattr(audio_behavior, "still_following_likelihood", 0.0)))
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            if audio_conf >= self._audio_assist_conf:
                position_source = "joint"

        tracking = self._last_tracking
        tracking_mode = TrackingMode.BOOTSTRAP
        tracking_quality = 0.0
        confidence = 0.0
        stable = False
        source_candidate_ref_idx = self._time_to_ref_idx(self._estimated_ref_time_sec_f)
        source_committed_ref_idx = source_candidate_ref_idx
        if tracking is not None:
            tracking_mode = tracking.tracking_mode
            tracking_quality = tracking.tracking_quality.overall_score
            confidence = tracking.confidence
            stable = tracking.stable
            source_candidate_ref_idx = tracking.candidate_ref_idx
            source_committed_ref_idx = tracking.committed_ref_idx

        self._last_snapshot = self._render_snapshot(
            now_sec=now_sec,
            signal_quality=signal_quality,
            tracking_mode=tracking_mode,
            tracking_quality=tracking_quality,
            confidence=confidence,
            stable=stable,
            source_candidate_ref_idx=source_candidate_ref_idx,
            source_committed_ref_idx=source_committed_ref_idx,
            audio_conf=audio_conf,
            still_following=still_following,
            reentry=reentry,
            position_source=position_source,
        )
        return self._last_snapshot

    def _predict_forward(self, *, dt: float, signal_quality: SignalQuality | None) -> None:
        if dt <= 0.0:
            return

        speaking = False
        if signal_quality is not None:
            speaking = bool(
                signal_quality.vad_active
                or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
            )

        vel = float(self._estimated_velocity_ref_sec_per_sec)
        if not speaking:
            vel *= 0.84
        else:
            vel = min(1.55, max(0.0, vel))

        advance = max(0.0, vel) * dt
        self._estimated_ref_time_sec_f += advance
        self._estimated_ref_time_sec_f = self._clamp_ref_time(self._estimated_ref_time_sec_f)
        self._estimated_velocity_ref_sec_per_sec = vel

    def _text_observation_weight(self, tracking: TrackingSnapshot) -> float:
        weight = 0.0
        weight += 0.46 * float(tracking.tracking_quality.overall_score)
        weight += 0.34 * float(tracking.confidence)
        weight += 0.12 * float(tracking.local_match_ratio)
        if tracking.stable:
            weight += 0.10
        if tracking.tracking_mode == TrackingMode.LOCKED:
            weight += 0.10
        elif tracking.tracking_mode == TrackingMode.WEAK_LOCKED:
            weight += 0.02
        elif tracking.tracking_mode in (TrackingMode.REACQUIRING, TrackingMode.LOST):
            weight -= 0.16
        if self._text_stability_run >= 2:
            weight += 0.08
        return max(0.0, min(1.0, weight))

    def _audio_observation_weight(
        self,
        *,
        audio_conf: float,
        text_quality: float,
        repeated: float,
        reentry: float,
        still_following: float,
        paused: float,
        audio_mode: str,
    ) -> float:
        weight = 0.0
        weight += 0.52 * float(audio_conf)
        weight += 0.22 * float(still_following)
        weight += 0.08 * float(reentry)
        if self._audio_stability_run >= 2:
            weight += 0.10
        if text_quality < 0.54:
            weight += 0.10
        if audio_mode in {"reentry", "recovery"}:
            weight += 0.08
        if paused >= 0.70:
            weight -= 0.16
        if repeated >= 0.68:
            weight -= 0.28
        return max(0.0, min(1.0, weight))

    def _pull_toward_observation(self, obs_ref_time_sec: float, obs_weight: float) -> None:
        cur = float(self._estimated_ref_time_sec_f)
        obs = self._clamp_ref_time(float(obs_ref_time_sec))

        err = obs - cur
        if err <= 0.0:
            beta = 0.10 * max(0.0, min(1.0, obs_weight))
        else:
            beta = 0.16 + 0.44 * max(0.0, min(1.0, obs_weight))

        beta = max(0.04, min(0.78, beta))
        new_val = cur + beta * err

        # 速度估计随校正更新
        delta = new_val - cur
        self._estimated_velocity_ref_sec_per_sec = 0.78 * self._estimated_velocity_ref_sec_per_sec + 0.22 * max(0.0, delta / 0.03)

        self._estimated_ref_time_sec_f = self._clamp_ref_time(new_val)

    def _apply_monotonic_constraints(
        self,
        *,
        prev_est_ref_time_sec: float,
        text_obs_time_sec: float | None,
        audio_obs_time_sec: float | None,
        repeated: float,
        reentry: float,
        paused: float,
        now_sec: float,
    ) -> None:
        cur = float(self._estimated_ref_time_sec_f)

        # 主进度不后退
        cur = max(cur, prev_est_ref_time_sec)

        # repeat 时冻结快进
        if repeated >= 0.68:
            cur = min(cur, prev_est_ref_time_sec + 0.06)

        # pause 时只能很慢动
        if paused >= 0.72:
            cur = min(cur, prev_est_ref_time_sec + 0.04)

        # reentry 时允许有限快速贴近
        if reentry >= 0.64 and audio_obs_time_sec is not None:
            target = max(prev_est_ref_time_sec, min(audio_obs_time_sec, prev_est_ref_time_sec + self._max_audio_jump_sec))
            cur = max(cur, target * 0.65 + cur * 0.35)

        # generation 切换后的短时重获窗口
        if now_sec <= self._force_reacquire_until_sec:
            if text_obs_time_sec is not None:
                cur = max(cur, min(text_obs_time_sec, prev_est_ref_time_sec + 0.35))

        self._estimated_ref_time_sec_f = self._clamp_ref_time(cur)

    def _render_snapshot(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        tracking_mode: TrackingMode,
        tracking_quality: float,
        confidence: float,
        stable: bool,
        source_candidate_ref_idx: int,
        source_committed_ref_idx: int,
        audio_conf: float,
        still_following: float,
        reentry: float,
        position_source: str,
    ) -> ProgressEstimate:
        assert self._ref_map is not None

        estimated_idx = self._time_to_ref_idx(self._estimated_ref_time_sec_f)
        estimated_ref_time_sec = self._idx_to_ref_time(estimated_idx)

        progress_age = 9999.0
        if self._last_progress_at_sec > 0.0:
            progress_age = max(0.0, now_sec - self._last_progress_at_sec)
        if self._last_audio_progress_at_sec > 0.0 and audio_conf >= self._audio_assist_conf:
            progress_age = min(progress_age, max(0.0, now_sec - self._last_audio_progress_at_sec))

        recently_progressed = progress_age <= self.recent_progress_sec

        signal_speaking = False
        if signal_quality is not None:
            signal_speaking = bool(
                signal_quality.vad_active
                or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
            )

        effective_tracking_mode = tracking_mode
        effective_tracking_quality = float(tracking_quality)
        if now_sec <= self._force_reacquire_until_sec:
            effective_tracking_mode = TrackingMode.REACQUIRING
            effective_tracking_quality = min(effective_tracking_quality, 0.55)

        active_speaking = False
        if recently_progressed:
            active_speaking = True
        elif signal_speaking and effective_tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
            active_speaking = True
        elif signal_speaking and effective_tracking_quality >= 0.70:
            active_speaking = True
        elif audio_conf >= self._audio_assist_conf and (still_following >= 0.62 or reentry >= 0.58):
            active_speaking = True

        joint_conf = max(
            confidence,
            0.56 * confidence + 0.44 * audio_conf,
            0.52 * effective_tracking_quality + 0.48 * audio_conf,
        )
        if position_source == "audio":
            joint_conf = max(joint_conf, audio_conf * 0.92)
        elif position_source == "joint":
            joint_conf = max(joint_conf, 0.58 * joint_conf + 0.42 * max(audio_conf, still_following))

        user_state = self.behavior_interpreter.infer(
            progress_age=progress_age,
            signal_quality=signal_quality,
            tracking=self._last_tracking,
            tracking_mode=effective_tracking_mode,
            tracking_quality=max(effective_tracking_quality, audio_conf * 0.82),
            candidate_idx=max(source_candidate_ref_idx, estimated_idx),
            estimated_idx=estimated_idx,
        )
        if audio_conf >= self._audio_takeover_conf and still_following >= 0.64 and user_state in (
            UserReadState.NOT_STARTED,
            UserReadState.PAUSED,
        ):
            user_state = UserReadState.FOLLOWING
        if reentry >= 0.62:
            user_state = UserReadState.REJOINING

        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=float(estimated_ref_time_sec),
            progress_velocity_idx_per_sec=float(self._estimated_velocity_ref_sec_per_sec),
            event_emitted_at_sec=float(self._last_event_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_age_sec=float(progress_age),
            source_candidate_ref_idx=int(source_candidate_ref_idx),
            source_committed_ref_idx=int(source_committed_ref_idx),
            tracking_mode=effective_tracking_mode,
            tracking_quality=float(max(effective_tracking_quality, audio_conf * 0.72 if position_source != "text" else effective_tracking_quality)),
            stable=bool(stable),
            confidence=float(max(confidence, audio_conf * 0.82 if position_source == "audio" else confidence)),
            active_speaking=bool(active_speaking),
            recently_progressed=bool(recently_progressed),
            user_state=user_state,
            audio_confidence=float(audio_conf),
            joint_confidence=float(max(0.0, min(1.0, joint_conf))),
            position_source=str(position_source),
            audio_support_strength=float(max(still_following, reentry, audio_conf)),
        )

    def _time_to_ref_idx(self, ref_time_sec: float) -> int:
        if not self._ref_times:
            return 0
        t = float(ref_time_sec)
        lo = 0
        hi = len(self._ref_times) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._ref_times[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return max(0, min(lo, len(self._ref_times) - 1))

    def _idx_to_ref_time(self, idx: int) -> float:
        if not self._ref_times:
            return 0.0
        i = max(0, min(int(idx), len(self._ref_times) - 1))
        return float(self._ref_times[i])

    def _clamp_ref_time(self, value: float) -> float:
        if not self._ref_times:
            return max(0.0, float(value))
        return max(0.0, min(float(value), float(self._ref_times[-1])))