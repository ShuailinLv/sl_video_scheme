第二部分如下
---
### 文件: `shadowing_app/src/shadowing/progress/behavior_interpreter.py`

```python
from __future__ import annotations
from shadowing.types import SignalQuality, TrackingMode, TrackingSnapshot, UserReadState
class BehaviorInterpreter:
    def __init__(
        self,
        *,
        recent_progress_sec: float = 0.90,
        strong_signal_threshold: float = 0.58,
        weak_signal_threshold: float = 0.42,
        repeat_penalty_threshold: float = 0.34,
        skip_forward_tokens: int = 8,
        pause_silence_sec: float = 1.10,
        rejoin_signal_sec: float = 0.55,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.strong_signal_threshold = float(strong_signal_threshold)
        self.weak_signal_threshold = float(weak_signal_threshold)
        self.repeat_penalty_threshold = float(repeat_penalty_threshold)
        self.skip_forward_tokens = int(skip_forward_tokens)
        self.pause_silence_sec = float(pause_silence_sec)
        self.rejoin_signal_sec = float(rejoin_signal_sec)
    def infer(
        self,
        *,
        progress_age: float,
        signal_quality: SignalQuality | None,
        tracking: TrackingSnapshot | None,
        tracking_mode: TrackingMode,
        tracking_quality: float,
        candidate_idx: int,
        estimated_idx: int,
        audio_confidence: float = 0.0,
        audio_support_strength: float = 0.0,
        position_source: str = "text",
    ) -> UserReadState:
        signal_speaking = self._is_signal_speaking(signal_quality)
        signal_weak_speaking = self._is_signal_weak_speaking(signal_quality)
        silence_run = 9999.0 if signal_quality is None else float(signal_quality.silence_run_sec)
        repeat_penalty = tracking.repeat_penalty if tracking is not None else 0.0
        forward_delta = int(candidate_idx) - int(estimated_idx)
        if (
            silence_run >= self.pause_silence_sec
            and progress_age > min(1.15, self.recent_progress_sec + 0.15)
            and audio_support_strength < 0.52
        ):
            return UserReadState.PAUSED
        if tracking_mode == TrackingMode.LOST:
            if signal_speaking or audio_support_strength >= 0.60 or audio_confidence >= 0.62:
                return UserReadState.REJOINING
            return UserReadState.LOST
        if tracking_mode == TrackingMode.REACQUIRING:
            if signal_speaking or audio_support_strength >= 0.58 or audio_confidence >= 0.60:
                return UserReadState.REJOINING
            return UserReadState.HESITATING
        if (
            repeat_penalty >= self.repeat_penalty_threshold
            and (signal_speaking or audio_support_strength >= 0.58)
        ):
            return UserReadState.REPEATING
        if forward_delta >= self.skip_forward_tokens and tracking_quality >= 0.72:
            return UserReadState.SKIPPING
        if progress_age <= self.recent_progress_sec:
            if tracking_quality >= 0.60 or audio_support_strength >= 0.64:
                return UserReadState.FOLLOWING
            if signal_speaking or audio_confidence >= 0.58:
                return UserReadState.HESITATING
            return UserReadState.WARMING_UP
        if (
            silence_run <= self.rejoin_signal_sec
            and (signal_speaking or audio_support_strength >= 0.60 or audio_confidence >= 0.60)
            and tracking_quality >= 0.36
        ):
            return UserReadState.REJOINING
        if (
            (signal_speaking and tracking_quality >= 0.42)
            or audio_support_strength >= 0.64
            or (position_source != "text" and audio_confidence >= 0.58)
        ):
            return UserReadState.HESITATING
        if signal_weak_speaking or audio_support_strength >= 0.46 or audio_confidence >= 0.48:
            return UserReadState.WARMING_UP
        return UserReadState.NOT_STARTED
    def _is_signal_speaking(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= self.strong_signal_threshold
        )
    def _is_signal_weak_speaking(self, signal_quality: SignalQuality | None) -> bool:
        if signal_quality is None:
            return False
        return bool(
            signal_quality.vad_active
            or signal_quality.speaking_likelihood >= self.weak_signal_threshold
        )
```

---
### 文件: `shadowing_app/src/shadowing/progress/commercial_progress_estimator.py`

```python
from __future__ import annotations
from shadowing.progress.behavior_interpreter import BehaviorInterpreter
from shadowing.types import (
    ProgressEstimate,
    ReferenceMap,
    SignalQuality,
    TrackingMode,
    TrackingSnapshot,
)
class CommercialProgressEstimator:
    def __init__(
        self,
        recent_progress_sec: float = 0.90,
        active_speaking_signal_min: float = 0.45,
        min_tracking_for_follow: float = 0.58,
    ) -> None:
        self.recent_progress_sec = float(recent_progress_sec)
        self.active_speaking_signal_min = float(active_speaking_signal_min)
        self.min_tracking_for_follow = float(min_tracking_for_follow)
        self.behavior_interpreter = BehaviorInterpreter(
            recent_progress_sec=recent_progress_sec,
        )
        self._ref_map: ReferenceMap | None = None
        self._estimated_idx_f = 0.0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_velocity = 0.0
        self._last_estimated_idx_at_progress = 0.0
        self._last_tracking: TrackingSnapshot | None = None
        self._last_snapshot: ProgressEstimate | None = None
        self._force_reacquire_until_sec = 0.0
    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._estimated_idx_f = float(start_idx)
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_velocity = 0.0
        self._last_estimated_idx_at_progress = float(start_idx)
        self._last_tracking = None
        self._last_snapshot = None
        self._force_reacquire_until_sec = 0.0
    def on_playback_generation_changed(self, now_sec: float) -> None:
        self._force_reacquire_until_sec = float(now_sec) + 0.80
    def update(
        self,
        tracking: TrackingSnapshot | None,
        signal_quality: SignalQuality | None,
        now_sec: float,
    ) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if tracking is None:
            return self.snapshot(now_sec, signal_quality)
        self._last_tracking = tracking
        self._last_event_at_sec = float(tracking.emitted_at_sec)
        current_idx = int(round(self._estimated_idx_f))
        candidate_idx = int(tracking.candidate_ref_idx)
        committed_idx = int(tracking.committed_ref_idx)
        target_idx = float(max(current_idx, committed_idx, candidate_idx))
        weight = self._weight_for_tracking(tracking)
        updated_idx = max(
            self._estimated_idx_f,
            (1.0 - weight) * self._estimated_idx_f + weight * target_idx,
        )
        if (
            tracking.tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED)
            and tracking.local_match_ratio >= 0.68
            and candidate_idx > current_idx
        ):
            updated_idx = max(updated_idx, float(current_idx) + 0.60)
        estimated_idx = max(0, min(int(round(updated_idx)), len(self._ref_map.tokens) - 1))
        self._estimated_idx_f = float(estimated_idx)
        progressed = estimated_idx > current_idx
        if progressed:
            if self._last_progress_at_sec > 0.0 and tracking.emitted_at_sec > self._last_progress_at_sec:
                dt = max(1e-6, tracking.emitted_at_sec - self._last_progress_at_sec)
                self._last_velocity = (estimated_idx - self._last_estimated_idx_at_progress) / dt
            self._last_progress_at_sec = float(tracking.emitted_at_sec)
            self._last_estimated_idx_at_progress = float(estimated_idx)
        self._last_snapshot = self._render_snapshot(now_sec, signal_quality)
        return self._last_snapshot
    def snapshot(self, now_sec: float, signal_quality: SignalQuality | None) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if self._last_tracking is None and self._last_snapshot is None:
            return None
        self._last_snapshot = self._render_snapshot(now_sec, signal_quality)
        return self._last_snapshot
    def _weight_for_tracking(self, tracking: TrackingSnapshot) -> float:
        if tracking.tracking_mode == TrackingMode.LOCKED:
            return 0.82 if tracking.stable else 0.68
        if tracking.tracking_mode == TrackingMode.WEAK_LOCKED:
            return 0.42
        if tracking.tracking_mode == TrackingMode.REACQUIRING:
            return 0.16
        return 0.05
    def _render_snapshot(
        self,
        now_sec: float,
        signal_quality: SignalQuality | None,
    ) -> ProgressEstimate:
        assert self._ref_map is not None
        tracking = self._last_tracking
        estimated_idx = max(0, min(int(round(self._estimated_idx_f)), len(self._ref_map.tokens) - 1))
        estimated_ref_time_sec = float(self._ref_map.tokens[estimated_idx].t_start)
        progress_age = 9999.0
        if self._last_progress_at_sec > 0.0:
            progress_age = max(0.0, now_sec - self._last_progress_at_sec)
        recently_progressed = progress_age <= self.recent_progress_sec
        signal_speaking = False
        if signal_quality is not None:
            signal_speaking = (
                signal_quality.vad_active
                or signal_quality.speaking_likelihood >= self.active_speaking_signal_min
            )
        tracking_mode = TrackingMode.BOOTSTRAP
        tracking_quality = 0.0
        confidence = 0.0
        stable = False
        source_candidate_ref_idx = estimated_idx
        source_committed_ref_idx = estimated_idx
        event_emitted_at_sec = self._last_event_at_sec
        if tracking is not None:
            tracking_mode = tracking.tracking_mode
            tracking_quality = tracking.tracking_quality.overall_score
            confidence = tracking.confidence
            stable = tracking.stable
            source_candidate_ref_idx = tracking.candidate_ref_idx
            source_committed_ref_idx = tracking.committed_ref_idx
        if now_sec <= self._force_reacquire_until_sec:
            tracking_mode = TrackingMode.REACQUIRING
            tracking_quality = min(tracking_quality, 0.55)
        active_speaking = False
        if recently_progressed:
            active_speaking = True
        elif signal_speaking and tracking_mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED):
            active_speaking = True
        elif signal_speaking and tracking_quality >= 0.70:
            active_speaking = True
        user_state = self.behavior_interpreter.infer(
            progress_age=progress_age,
            signal_quality=signal_quality,
            tracking=tracking,
            tracking_mode=tracking_mode,
            tracking_quality=tracking_quality,
            candidate_idx=source_candidate_ref_idx,
            estimated_idx=estimated_idx,
        )
        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=estimated_ref_time_sec,
            progress_velocity_idx_per_sec=float(self._last_velocity),
            event_emitted_at_sec=float(event_emitted_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_age_sec=float(progress_age),
            source_candidate_ref_idx=int(source_candidate_ref_idx),
            source_committed_ref_idx=int(source_committed_ref_idx),
            tracking_mode=tracking_mode,
            tracking_quality=float(tracking_quality),
            stable=bool(stable),
            confidence=float(confidence),
            active_speaking=bool(active_speaking),
            recently_progressed=bool(recently_progressed),
            user_state=user_state,
        )
```

---
### 文件: `shadowing_app/src/shadowing/progress/monotonic_estimator.py`

```python
from __future__ import annotations
from shadowing.types import AlignResult, ProgressEstimate, ReferenceMap
class MonotonicProgressEstimator:
    def __init__(
        self,
        active_speaking_confidence: float = 0.68,
        recent_progress_sec: float = 0.90,
        speaking_event_fresh_sec: float = 0.45,
        local_match_for_speaking: float = 0.65,
    ) -> None:
        self.active_speaking_confidence = float(active_speaking_confidence)
        self.recent_progress_sec = float(recent_progress_sec)
        self.speaking_event_fresh_sec = float(speaking_event_fresh_sec)
        self.local_match_for_speaking = float(local_match_for_speaking)
        self._ref_map: ReferenceMap | None = None
        self._estimated_idx_f = 0.0
        self._last_source_candidate_idx = 0
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_estimated_idx_at_progress = 0.0
        self._last_velocity = 0.0
        self._last_alignment: AlignResult | None = None
        self._last_snapshot: ProgressEstimate | None = None
    def reset(self, reference_map: ReferenceMap, start_idx: int = 0) -> None:
        self._ref_map = reference_map
        start_idx = max(0, min(int(start_idx), max(0, len(reference_map.tokens) - 1)))
        self._estimated_idx_f = float(start_idx)
        self._last_source_candidate_idx = start_idx
        self._last_progress_at_sec = 0.0
        self._last_event_at_sec = 0.0
        self._last_estimated_idx_at_progress = float(start_idx)
        self._last_velocity = 0.0
        self._last_alignment = None
        self._last_snapshot = None
    def on_playback_generation_changed(self, start_idx: int | None = None) -> None:
        if self._ref_map is None:
            return
        idx = int(round(self._estimated_idx_f)) if start_idx is None else int(start_idx)
        self.reset(self._ref_map, start_idx=idx)
    def update(self, alignment: AlignResult | None) -> ProgressEstimate | None:
        if alignment is None or self._ref_map is None or not self._ref_map.tokens:
            return self._last_snapshot
        self._last_alignment = alignment
        event_time = float(alignment.emitted_at_sec)
        if event_time <= 0.0:
            event_time = self._last_event_at_sec
        candidate_idx = int(alignment.candidate_ref_idx)
        committed_idx = int(alignment.committed_ref_idx)
        current_estimated_idx = int(round(self._estimated_idx_f))
        target_idx = float(max(candidate_idx, committed_idx, current_estimated_idx))
        if alignment.stable:
            weight = 0.88
        elif alignment.confidence >= 0.90:
            weight = 0.72
        elif alignment.confidence >= 0.78:
            weight = 0.50
        else:
            weight = 0.26
        if candidate_idx < current_estimated_idx:
            target_idx = float(current_estimated_idx)
            weight = min(weight, 0.12)
        updated_idx = max(
            self._estimated_idx_f,
            (1.0 - weight) * self._estimated_idx_f + weight * target_idx,
        )
        if alignment.local_match_ratio >= 0.70 and candidate_idx > current_estimated_idx:
            updated_idx = max(updated_idx, float(current_estimated_idx) + 0.60)
        estimated_idx = max(0, min(int(round(updated_idx)), len(self._ref_map.tokens) - 1))
        self._estimated_idx_f = float(estimated_idx)
        progressed = estimated_idx > current_estimated_idx
        if progressed:
            if self._last_progress_at_sec > 0.0 and event_time > self._last_progress_at_sec:
                dt = max(1e-6, event_time - self._last_progress_at_sec)
                self._last_velocity = (estimated_idx - self._last_estimated_idx_at_progress) / dt
            self._last_progress_at_sec = event_time
            self._last_estimated_idx_at_progress = float(estimated_idx)
        self._last_source_candidate_idx = candidate_idx
        self._last_event_at_sec = event_time
        self._last_snapshot = self._render_snapshot(now_sec=event_time)
        return self._last_snapshot
    def snapshot(self, now_sec: float) -> ProgressEstimate | None:
        if self._ref_map is None or not self._ref_map.tokens:
            return None
        if self._last_alignment is None and self._last_snapshot is None:
            return None
        self._last_snapshot = self._render_snapshot(now_sec=now_sec)
        return self._last_snapshot
    def _render_snapshot(self, now_sec: float) -> ProgressEstimate:
        assert self._ref_map is not None
        alignment = self._last_alignment
        estimated_idx = max(0, min(int(round(self._estimated_idx_f)), len(self._ref_map.tokens) - 1))
        estimated_ref_time_sec = float(self._ref_map.tokens[estimated_idx].t_start)
        if self._last_progress_at_sec > 0.0 and now_sec >= self._last_progress_at_sec:
            last_progress_age = now_sec - self._last_progress_at_sec
        else:
            last_progress_age = 9999.0
        recently_progressed = last_progress_age <= self.recent_progress_sec
        active_speaking = False
        if alignment is not None:
            forward_delta = alignment.candidate_ref_idx - estimated_idx
            event_fresh = (
                (now_sec - self._last_event_at_sec) <= self.speaking_event_fresh_sec
                if self._last_event_at_sec > 0.0 and now_sec >= self._last_event_at_sec
                else False
            )
            if recently_progressed:
                active_speaking = True
            elif (
                event_fresh
                and alignment.stable
                and alignment.confidence >= self.active_speaking_confidence
                and forward_delta >= 0
            ):
                active_speaking = True
            elif (
                event_fresh
                and alignment.confidence >= max(self.active_speaking_confidence, 0.76)
                and alignment.local_match_ratio >= self.local_match_for_speaking
                and alignment.candidate_ref_idx > alignment.committed_ref_idx
            ):
                active_speaking = True
        return ProgressEstimate(
            estimated_ref_idx=estimated_idx,
            estimated_ref_time_sec=estimated_ref_time_sec,
            source_candidate_ref_idx=(
                int(alignment.candidate_ref_idx) if alignment is not None else int(self._last_source_candidate_idx)
            ),
            source_committed_ref_idx=(
                int(alignment.committed_ref_idx) if alignment is not None else estimated_idx
            ),
            confidence=float(alignment.confidence) if alignment is not None else 0.0,
            stable=bool(alignment.stable) if alignment is not None else False,
            event_emitted_at_sec=float(self._last_event_at_sec),
            last_progress_at_sec=float(self._last_progress_at_sec),
            progress_velocity_idx_per_sec=float(self._last_velocity),
            recently_progressed=recently_progressed,
            last_progress_age_sec=float(last_progress_age),
            active_speaking=active_speaking,
            phase_hint="follow" if active_speaking or recently_progressed else "wait",
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/aligner.py`

```python
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Any
logger = logging.getLogger(__name__)
def _normalize_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", text)
    return text
def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))
@dataclass(slots=True)
class AlignmentCandidate:
    ref_idx: int
    confidence: float
    local_match_ratio: float
    matched_chars: int
    source_text: str
@dataclass(slots=True)
class AlignmentTrackingQuality:
    local_score: float
    continuity_score: float
    confidence_score: float
    overall_score: float
@dataclass(slots=True)
class AlignmentSnapshot:
    candidate_ref_idx: int
    committed_ref_idx: int
    confidence: float
    stable: bool
    local_match_ratio: float
    repeat_penalty: float
    emitted_at_sec: float
    tracking_mode: str
    tracking_quality: AlignmentTrackingQuality
class RealtimeAligner:
    def __init__(
        self,
        *,
        window_back: int = 8,
        window_ahead: int = 40,
        stable_hits: int = 2,
        min_confidence: float = 0.60,
        debug: bool = False,
    ) -> None:
        self.window_back = max(0, int(window_back))
        self.window_ahead = max(1, int(window_ahead))
        self.stable_hits = max(1, int(stable_hits))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self.debug = bool(debug)
        self._tokens: list[dict[str, Any]] = []
        self._norm_tokens: list[str] = []
        self._committed_ref_idx = 0
        self._last_candidate_ref_idx = 0
        self._same_candidate_run = 0
        self._last_partial_text = ""
        self._last_emitted_at_sec = 0.0
    def reset(self, reference_tokens: list[dict[str, Any]]) -> None:
        self._tokens = list(reference_tokens or [])
        self._norm_tokens = [_normalize_text(x.get("text", "")) for x in self._tokens]
        self._committed_ref_idx = 0
        self._last_candidate_ref_idx = 0
        self._same_candidate_run = 0
        self._last_partial_text = ""
        self._last_emitted_at_sec = 0.0
    def update(
        self,
        *,
        partial_text: str,
        emitted_at_sec: float,
    ) -> AlignmentSnapshot | None:
        if not self._tokens:
            return None
        norm = _normalize_text(partial_text)
        if not norm:
            return self._build_snapshot(
                candidate_ref_idx=self._committed_ref_idx,
                confidence=0.0,
                local_match_ratio=0.0,
                matched_chars=0,
                source_text="",
                emitted_at_sec=emitted_at_sec,
            )
        search_start = max(0, self._committed_ref_idx - self.window_back)
        search_end = min(len(self._tokens), self._committed_ref_idx + self.window_ahead + 1)
        best = self._scan_candidates(
            norm_text=norm,
            search_start=search_start,
            search_end=search_end,
        )
        if best is None:
            return self._build_snapshot(
                candidate_ref_idx=self._committed_ref_idx,
                confidence=0.0,
                local_match_ratio=0.0,
                matched_chars=0,
                source_text=norm,
                emitted_at_sec=emitted_at_sec,
            )
        if best.ref_idx == self._last_candidate_ref_idx:
            self._same_candidate_run += 1
        else:
            self._same_candidate_run = 1
            self._last_candidate_ref_idx = best.ref_idx
        stable = (
            best.confidence >= self.min_confidence
            and self._same_candidate_run >= self.stable_hits
        )
        if stable and best.ref_idx >= self._committed_ref_idx:
            self._committed_ref_idx = best.ref_idx
        snapshot = self._build_snapshot(
            candidate_ref_idx=best.ref_idx,
            confidence=best.confidence,
            local_match_ratio=best.local_match_ratio,
            matched_chars=best.matched_chars,
            source_text=best.source_text,
            emitted_at_sec=emitted_at_sec,
        )
        if self.debug:
            logger.info(
                "align: partial=%r candidate=%s committed=%s conf=%.3f stable=%s ratio=%.3f",
                partial_text,
                snapshot.candidate_ref_idx,
                snapshot.committed_ref_idx,
                snapshot.confidence,
                snapshot.stable,
                snapshot.local_match_ratio,
            )
        self._last_partial_text = norm
        self._last_emitted_at_sec = float(emitted_at_sec)
        return snapshot
    def _scan_candidates(
        self,
        *,
        norm_text: str,
        search_start: int,
        search_end: int,
    ) -> AlignmentCandidate | None:
        best: AlignmentCandidate | None = None
        for idx in range(search_start, search_end):
            candidate = self._score_candidate(idx=idx, norm_text=norm_text)
            if candidate is None:
                continue
            if best is None:
                best = candidate
                continue
            if candidate.confidence > best.confidence + 1e-6:
                best = candidate
            elif abs(candidate.confidence - best.confidence) <= 1e-6:
                if candidate.ref_idx > best.ref_idx:
                    best = candidate
        return best
    def _score_candidate(self, *, idx: int, norm_text: str) -> AlignmentCandidate | None:
        if idx < 0 or idx >= len(self._norm_tokens):
            return None
        token_text = self._norm_tokens[idx]
        if not token_text:
            return None
        overlap = self._longest_common_subsequence_approx(norm_text, token_text)
        if overlap <= 0:
            return None
        local_match_ratio = overlap / max(1, len(token_text))
        source_cover_ratio = overlap / max(1, len(norm_text))
        continuity_bonus = 0.0
        if idx == self._committed_ref_idx:
            continuity_bonus += 0.08
        elif idx == self._committed_ref_idx + 1:
            continuity_bonus += 0.06
        elif idx > self._committed_ref_idx + 1:
            jump = idx - self._committed_ref_idx
            continuity_bonus -= min(0.14, 0.015 * jump)
        elif idx < self._committed_ref_idx:
            back = self._committed_ref_idx - idx
            continuity_bonus -= min(0.18, 0.03 * back)
        confidence = (
            0.58 * local_match_ratio
            + 0.26 * source_cover_ratio
            + continuity_bonus
        )
        confidence = max(0.0, min(1.0, confidence))
        return AlignmentCandidate(
            ref_idx=idx,
            confidence=confidence,
            local_match_ratio=max(0.0, min(1.0, local_match_ratio)),
            matched_chars=overlap,
            source_text=norm_text,
        )
    def _build_snapshot(
        self,
        *,
        candidate_ref_idx: int,
        confidence: float,
        local_match_ratio: float,
        matched_chars: int,
        source_text: str,
        emitted_at_sec: float,
    ) -> AlignmentSnapshot:
        candidate_ref_idx = _clamp(candidate_ref_idx, 0, max(0, len(self._tokens) - 1))
        committed_ref_idx = _clamp(self._committed_ref_idx, 0, max(0, len(self._tokens) - 1))
        stable = confidence >= self.min_confidence and self._same_candidate_run >= self.stable_hits
        repeat_penalty = 0.0
        if committed_ref_idx > candidate_ref_idx:
            repeat_penalty = min(1.0, 0.18 * (committed_ref_idx - candidate_ref_idx))
        elif candidate_ref_idx == committed_ref_idx and source_text == self._last_partial_text:
            repeat_penalty = min(1.0, 0.08 * self._same_candidate_run)
        continuity_score = 1.0
        if candidate_ref_idx < committed_ref_idx:
            continuity_score = max(0.0, 1.0 - 0.18 * (committed_ref_idx - candidate_ref_idx))
        elif candidate_ref_idx > committed_ref_idx:
            continuity_score = max(0.0, 1.0 - 0.04 * (candidate_ref_idx - committed_ref_idx))
        confidence_score = float(confidence)
        overall_score = (
            0.40 * float(local_match_ratio)
            + 0.30 * continuity_score
            + 0.30 * confidence_score
        )
        overall_score = max(0.0, min(1.0, overall_score))
        if confidence < 0.20:
            tracking_mode = "LOST"
        elif stable and confidence >= self.min_confidence:
            tracking_mode = "LOCKED"
        elif confidence >= max(0.35, self.min_confidence - 0.12):
            tracking_mode = "WEAK_LOCKED"
        else:
            tracking_mode = "REACQUIRING"
        return AlignmentSnapshot(
            candidate_ref_idx=int(candidate_ref_idx),
            committed_ref_idx=int(committed_ref_idx),
            confidence=float(max(0.0, min(1.0, confidence))),
            stable=bool(stable),
            local_match_ratio=float(max(0.0, min(1.0, local_match_ratio))),
            repeat_penalty=float(max(0.0, min(1.0, repeat_penalty))),
            emitted_at_sec=float(emitted_at_sec),
            tracking_mode=str(tracking_mode),
            tracking_quality=AlignmentTrackingQuality(
                local_score=float(max(0.0, min(1.0, local_match_ratio))),
                continuity_score=float(max(0.0, min(1.0, continuity_score))),
                confidence_score=float(max(0.0, min(1.0, confidence_score))),
                overall_score=float(max(0.0, min(1.0, overall_score))),
            ),
        )
    def _longest_common_subsequence_approx(self, a: str, b: str) -> int:
        if not a or not b:
            return 0
        longest_substring = self._longest_common_substring_len(a, b)
        prefix = 0
        for x, y in zip(a, b):
            if x != y:
                break
            prefix += 1
        suffix = 0
        for x, y in zip(a[::-1], b[::-1]):
            if x != y:
                break
            suffix += 1
        return max(longest_substring, prefix, suffix)
    def _longest_common_substring_len(self, a: str, b: str) -> int:
        if not a or not b:
            return 0
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        best = 0
        for win in range(len(shorter), 0, -1):
            if win <= best:
                break
            for i in range(0, len(shorter) - win + 1):
                sub = shorter[i : i + win]
                if sub in longer:
                    return win
        return best
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/incremental_aligner.py`

```python
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Sequence
def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+", "", text)
    return text
def _safe_ratio(a: int, b: int) -> float:
    if b <= 0:
        return 0.0
    return max(0.0, min(1.0, float(a) / float(b)))
@dataclass(slots=True)
class AlignmentResult:
    committed: int
    candidate: int
    score: float
    conf: float
    stable: bool
    backward: bool
    matched_n: int
    hyp_n: int
    mode: str
    window: tuple[int, int]
    local_match: float = 0.0
    soft_committed: bool = False
    accepted: bool = False
    raw_text: str = ""
    normalized_text: str = ""
    repeated_candidate: bool = False
    weak_forward: bool = False
    @property
    def advance(self) -> int:
        return max(0, self.candidate - self.committed)
class IncrementalAligner:
    def __init__(
        self,
        reference_text: str | Sequence[str] | None = None,
        *,
        window_back: int = 10,
        window_ahead: int = 48,
        stable_hits: int = 2,
        min_confidence: float = 0.62,
        debug: bool = False,
    ) -> None:
        self.window_back = int(window_back)
        self.window_ahead = int(window_ahead)
        self.stable_hits = max(1, int(stable_hits))
        self.min_confidence = float(min_confidence)
        self.debug = bool(debug)
        self.reference_text = ""
        self.reference_norm = ""
        self._committed = 0
        self._last_candidate = 0
        self._same_candidate_hits = 0
        self._same_zone_hits = 0
        self._last_zone_anchor = 0
        self._forced_center: int | None = None
        self._forced_budget = 0
        self._forced_window_back: int | None = None
        self._forced_window_ahead: int | None = None
        if reference_text is not None:
            self.set_reference(reference_text)
    @property
    def committed_index(self) -> int:
        return self._committed
    def get_committed_index(self) -> int:
        return self._committed
    def set_reference(self, reference_text: str | Sequence[str]) -> None:
        if isinstance(reference_text, (list, tuple)):
            reference_text = "".join(str(x) for x in reference_text)
        self.reference_text = reference_text or ""
        self.reference_norm = _normalize_text(self.reference_text)
        self.reset(committed=0)
    def reset(self, committed: int | None = None) -> None:
        if committed is None:
            self._committed = 0
        else:
            self._committed = max(0, min(int(committed), len(self.reference_norm)))
        self._last_candidate = self._committed
        self._same_candidate_hits = 0
        self._same_zone_hits = 0
        self._last_zone_anchor = (self._committed // 4) * 4
        self._forced_center = None
        self._forced_budget = 0
        self._forced_window_back = None
        self._forced_window_ahead = None
    def force_recenter(
        self,
        committed_hint: int,
        *,
        window_back: int | None = None,
        window_ahead: int | None = None,
        budget_events: int = 6,
    ) -> None:
        if not self.reference_norm:
            return
        hint = max(0, min(int(committed_hint), len(self.reference_norm)))
        self._forced_center = hint
        self._forced_window_back = int(window_back) if window_back is not None else max(16, self.window_back + 6)
        self._forced_window_ahead = int(window_ahead) if window_ahead is not None else max(32, self.window_ahead // 2)
        self._forced_budget = max(1, int(budget_events))
        self._committed = min(self._committed, hint)
    def update(self, hypothesis_text: str) -> AlignmentResult:
        return self.align(hypothesis_text)
    def align(self, hypothesis_text: str) -> AlignmentResult:
        hyp_raw = hypothesis_text or ""
        hyp = _normalize_text(hyp_raw)
        if not self.reference_norm:
            return AlignmentResult(
                committed=self._committed,
                candidate=self._committed,
                score=-1.0,
                conf=0.0,
                stable=False,
                backward=False,
                matched_n=0,
                hyp_n=len(hyp),
                mode="no_reference",
                window=(0, 0),
                raw_text=hyp_raw,
                normalized_text=hyp,
            )
        if not hyp:
            return AlignmentResult(
                committed=self._committed,
                candidate=self._committed,
                score=-1.0,
                conf=0.0,
                stable=False,
                backward=False,
                matched_n=0,
                hyp_n=0,
                mode="empty",
                window=(self._committed, self._committed),
                raw_text=hyp_raw,
                normalized_text=hyp,
            )
        candidate, matched_n, score, conf, backward, mode, window, local_match = self._search_best_candidate(hyp)
        repeated_candidate = candidate == self._last_candidate
        if repeated_candidate:
            self._same_candidate_hits += 1
        else:
            self._same_candidate_hits = 1
        zone_anchor = (candidate // 4) * 4
        if zone_anchor == self._last_zone_anchor and candidate >= self._committed:
            self._same_zone_hits += 1
        else:
            self._same_zone_hits = 1
        self._last_zone_anchor = zone_anchor
        advance = candidate - self._committed
        strong_accept = (
            not backward
            and advance >= 1
            and conf >= self.min_confidence
            and local_match >= 0.60
            and self._same_candidate_hits >= self.stable_hits
        )
        weak_forward = (
            not backward
            and advance >= 3
            and conf >= max(0.80, self.min_confidence + 0.16)
            and local_match >= 0.76
            and self._same_zone_hits >= 2
        )
        accepted = False
        soft_committed = False
        stable = False
        if strong_accept:
            self._committed = max(self._committed, candidate)
            accepted = True
            stable = True
        elif weak_forward:
            self._committed = max(self._committed, candidate)
            accepted = True
            soft_committed = True
        result = AlignmentResult(
            committed=self._committed,
            candidate=candidate,
            score=score,
            conf=conf,
            stable=stable,
            backward=backward,
            matched_n=matched_n,
            hyp_n=len(hyp),
            mode=mode,
            window=window,
            local_match=local_match,
            soft_committed=soft_committed,
            accepted=accepted,
            raw_text=hyp_raw,
            normalized_text=hyp,
            repeated_candidate=repeated_candidate,
            weak_forward=weak_forward,
        )
        self._last_candidate = candidate
        if self._forced_budget > 0:
            self._forced_budget -= 1
            if self._forced_budget <= 0:
                self._forced_center = None
                self._forced_window_back = None
                self._forced_window_ahead = None
        return result
    def _search_best_candidate(
        self,
        hyp: str,
    ) -> tuple[int, int, float, float, bool, str, tuple[int, int], float]:
        ref = self.reference_norm
        committed = self._committed
        start, end, mode = self._build_search_window(hyp)
        best_candidate = committed
        best_matched_n = 0
        best_score = -1e9
        best_conf = 0.0
        best_local_match = 0.0
        for cand in range(start, end + 1):
            seg = ref[cand : min(len(ref), cand + max(len(hyp) + 10, 18))]
            if not seg:
                continue
            sim, matched_n = self._substring_similarity(hyp, seg)
            prefix = self._prefix_match_ratio(hyp, seg)
            suffix = self._suffix_match_ratio(hyp, seg)
            bigram = self._bigram_overlap(hyp, seg)
            local_match = 0.45 * sim + 0.25 * prefix + 0.20 * suffix + 0.10 * bigram
            advance = cand - committed
            backward = advance < 0
            score = (
                10.0 * sim
                + 4.2 * prefix
                + 3.4 * suffix
                + 2.8 * bigram
                + 0.12 * matched_n
                - 0.14 * abs(advance)
                - (1.8 if backward else 0.0)
            )
            if not backward and matched_n >= min(4, len(hyp)):
                score += 0.8
            if not backward and suffix >= 0.68:
                score += 0.5
            if backward and sim < 0.62:
                score -= 1.2
            conf = max(
                0.0,
                min(
                    0.999,
                    0.55 * sim + 0.18 * prefix + 0.14 * suffix + 0.08 * bigram + 0.05 * (0.0 if backward else 1.0),
                ),
            )
            if score > best_score:
                best_score = score
                best_conf = conf
                best_local_match = local_match
                best_matched_n = matched_n
                best_candidate = min(len(ref), cand + max(matched_n, int(round(len(hyp) * max(sim, 0.35)))))
        backward = best_candidate < committed
        if backward and best_conf < 0.58:
            best_candidate = committed
            best_score = min(best_score, -0.8)
            mode = "backward_rejected"
        elif best_conf < 0.44 and mode == "normal":
            mode = "low_confidence"
        return (
            best_candidate,
            best_matched_n,
            float(best_score),
            float(best_conf),
            bool(backward),
            mode,
            (start, end),
            float(best_local_match),
        )
    def _build_search_window(self, hyp: str) -> tuple[int, int, str]:
        ref = self.reference_norm
        committed = self._committed
        if self._forced_center is not None and self._forced_budget > 0:
            center = max(committed, int(self._forced_center))
            back = int(self._forced_window_back or self.window_back)
            ahead = int(self._forced_window_ahead or self.window_ahead)
            return (
                max(0, center - back),
                min(len(ref), center + ahead),
                "forced_recenter",
            )
        long_partial = len(hyp) >= 12
        repeated_zone = self._same_zone_hits >= 3
        recovery_mode = long_partial or repeated_zone
        back = self.window_back + (6 if recovery_mode else 0)
        ahead = self.window_ahead + (10 if recovery_mode else 0)
        return (
            max(0, committed - back),
            min(len(ref), committed + ahead),
            "recovery" if recovery_mode else "normal",
        )
    def _substring_similarity(self, hyp: str, seg: str) -> tuple[float, int]:
        if not hyp or not seg:
            return 0.0, 0
        n = len(hyp)
        m = len(seg)
        best_sim = 0.0
        best_match = 0
        min_len = max(1, int(round(n * 0.70)))
        max_len = min(m, n + 6)
        for take in range(min_len, max_len + 1):
            ref_sub = seg[:take]
            dist = self._edit_distance_banded(hyp, ref_sub, band=max(2, abs(len(hyp) - len(ref_sub)) + 3))
            denom = max(len(hyp), len(ref_sub), 1)
            sim = max(0.0, 1.0 - dist / denom)
            matched = max(0, len(hyp) - dist)
            if sim > best_sim:
                best_sim = sim
                best_match = matched
        return best_sim, best_match
    def _edit_distance_banded(self, a: str, b: str, band: int) -> int:
        n = len(a)
        m = len(b)
        inf = 10**9
        prev = [inf] * (m + 1)
        prev[0] = 0
        for j in range(1, m + 1):
            prev[j] = j
        for i in range(1, n + 1):
            cur = [inf] * (m + 1)
            lo = max(1, i - band)
            hi = min(m, i + band)
            if lo == 1:
                cur[0] = i
            for j in range(lo, hi + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                cur[j] = min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            prev = cur
        return int(prev[m])
    def _prefix_match_ratio(self, a: str, b: str) -> float:
        n = min(len(a), len(b))
        if n <= 0:
            return 0.0
        hit = 0
        for i in range(n):
            if a[i] != b[i]:
                break
            hit += 1
        return _safe_ratio(hit, min(len(a), 10))
    def _suffix_match_ratio(self, a: str, b: str) -> float:
        n = min(len(a), len(b))
        if n <= 0:
            return 0.0
        hit = 0
        for i in range(1, n + 1):
            if a[-i] != b[-i]:
                break
            hit += 1
        return _safe_ratio(hit, min(len(a), 10))
    def _bigram_overlap(self, a: str, b: str) -> float:
        if len(a) < 2 or len(b) < 2:
            return 0.0
        aset = {a[i : i + 2] for i in range(len(a) - 1)}
        bset = {b[i : i + 2] for i in range(len(b) - 1)}
        if not aset:
            return 0.0
        return _safe_ratio(len(aset & bset), len(aset))
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/scoring.py`

```python
from __future__ import annotations
from rapidfuzz import fuzz
class AlignmentScorer:
    def score_token_pair(self, ref_char: str, ref_py: str, hyp_char: str, hyp_py: str) -> float:
        if ref_char == hyp_char:
            return 3.0
        if ref_py and ref_py == hyp_py:
            return 2.0
        py_sim = fuzz.ratio(ref_py, hyp_py) if ref_py and hyp_py else 0.0
        if py_sim >= 80:
            return 1.0
        return -1.5
    def insertion_penalty(self) -> float:
        return -0.7
    def deletion_penalty(self) -> float:
        return -0.9
    def backward_penalty(self) -> float:
        return -2.0
```

---
### 文件: `shadowing_app/src/shadowing/realtime/alignment/window_selector.py`

```python
from __future__ import annotations
from shadowing.types import RefToken, ReferenceMap
class WindowSelector:
    def __init__(self, look_back: int = 8, look_ahead: int = 40) -> None:
        self.look_back = int(look_back)
        self.look_ahead = int(look_ahead)
    def select(
        self,
        ref_map: ReferenceMap,
        committed_idx: int,
        *,
        look_back: int | None = None,
        look_ahead: int | None = None,
    ) -> tuple[list[RefToken], int, int]:
        back = self.look_back if look_back is None else max(1, int(look_back))
        ahead = self.look_ahead if look_ahead is None else max(1, int(look_ahead))
        start = max(0, committed_idx - back)
        end = min(len(ref_map.tokens), committed_idx + ahead + 1)
        return ref_map.tokens[start:end], start, end
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/fake_asr_provider.py`

```python
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
import numpy as np
from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEventType, RawAsrEvent
@dataclass(slots=True)
class FakeAsrStep:
    offset_sec: float
    text: str
    event_type: AsrEventType = AsrEventType.PARTIAL
@dataclass(slots=True)
class FakeAsrConfig:
    scripted_steps: list[FakeAsrStep] = field(default_factory=list)
    reference_text: str = ""
    chars_per_sec: float = 4.0
    emit_partial_interval_sec: float = 0.12
    emit_final_on_endpoint: bool = True
    sample_rate: int = 16000
    bytes_per_sample: int = 2
    channels: int = 1
    vad_rms_threshold: float = 0.01
    vad_min_active_ms: float = 30.0
class FakeASRProvider(ASRProvider):
    def __init__(self, config: FakeAsrConfig) -> None:
        self.config = config
        self._running = False
        self._start_at = 0.0
        self._script_index = 0
        self._last_emit_at = 0.0
        self._bytes_received = 0
        self._speech_bytes_received = 0
        self._last_progress_text = ""
        self._last_final_text = ""
    @classmethod
    def from_reference_text(
        cls,
        reference_text: str,
        chars_per_step: int = 6,
        step_interval_sec: float = 0.28,
        lag_sec: float = 0.5,
        tail_final: bool = True,
    ) -> "FakeASRProvider":
        clean = reference_text.strip()
        steps: list[FakeAsrStep] = []
        t = lag_sec
        cursor = 0
        while cursor < len(clean):
            cursor = min(cursor + chars_per_step, len(clean))
            text = clean[:cursor]
            if text:
                steps.append(
                    FakeAsrStep(
                        offset_sec=t,
                        text=text,
                        event_type=AsrEventType.PARTIAL,
                    )
                )
            t += step_interval_sec
        if tail_final:
            steps.append(
                FakeAsrStep(
                    offset_sec=t + 0.1,
                    text=clean,
                    event_type=AsrEventType.FINAL,
                )
            )
        return cls(FakeAsrConfig(scripted_steps=steps))
    def start(self) -> None:
        self._running = True
        self._start_at = time.monotonic()
        self._script_index = 0
        self._last_emit_at = 0.0
        self._bytes_received = 0
        self._speech_bytes_received = 0
        self._last_progress_text = ""
        self._last_final_text = ""
    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running or not pcm_bytes:
            return
        self._bytes_received += len(pcm_bytes)
        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return
        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio_f32)))) if audio_f32.size else 0.0
        frame_ms = (
            1000.0
            * audio_i16.size
            / max(1, self.config.sample_rate * self.config.channels)
        )
        if rms >= self.config.vad_rms_threshold and frame_ms >= self.config.vad_min_active_ms:
            self._speech_bytes_received += len(pcm_bytes)
    def poll_raw_events(self) -> list[RawAsrEvent]:
        if not self._running:
            return []
        if self.config.scripted_steps:
            return self._poll_scripted()
        if self.config.reference_text:
            return self._poll_progressive()
        return []
    def reset(self) -> None:
        self.start()
    def close(self) -> None:
        self._running = False
    def _poll_scripted(self) -> list[RawAsrEvent]:
        now = time.monotonic()
        elapsed = now - self._start_at
        events: list[RawAsrEvent] = []
        while self._script_index < len(self.config.scripted_steps):
            step = self.config.scripted_steps[self._script_index]
            if elapsed < step.offset_sec:
                break
            events.append(
                RawAsrEvent(
                    event_type=step.event_type,
                    text=step.text,
                    emitted_at_sec=now,
                )
            )
            self._script_index += 1
        return events
    def _poll_progressive(self) -> list[RawAsrEvent]:
        now = time.monotonic()
        if (now - self._last_emit_at) < self.config.emit_partial_interval_sec:
            return []
        total_speech_sec = self._bytes_to_seconds(self._speech_bytes_received)
        n_chars = int(math.floor(total_speech_sec * self.config.chars_per_sec))
        n_chars = max(0, min(n_chars, len(self.config.reference_text)))
        current_text = self.config.reference_text[:n_chars]
        events: list[RawAsrEvent] = []
        if current_text and current_text != self._last_progress_text:
            events.append(
                RawAsrEvent(
                    event_type=AsrEventType.PARTIAL,
                    text=current_text,
                    emitted_at_sec=now,
                )
            )
            self._last_progress_text = current_text
            self._last_emit_at = now
        if (
            self.config.emit_final_on_endpoint
            and n_chars >= len(self.config.reference_text)
            and self._last_final_text != self.config.reference_text
        ):
            events.append(
                RawAsrEvent(
                    event_type=AsrEventType.FINAL,
                    text=self.config.reference_text,
                    emitted_at_sec=now,
                )
            )
            self._last_final_text = self.config.reference_text
        return events
    def _bytes_to_seconds(self, n_bytes: int) -> float:
        bytes_per_sec = (
            self.config.sample_rate
            * self.config.bytes_per_sample
            * self.config.channels
        )
        return n_bytes / bytes_per_sec if bytes_per_sec > 0 else 0.0
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/normalizer.py`

```python
from __future__ import annotations
import re
from pypinyin import lazy_pinyin
from shadowing.types import AsrEvent, RawAsrEvent
class TextNormalizer:
    _drop_pattern = re.compile(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+")
    _digit_map = str.maketrans(
        {
            "0": "零",
            "1": "一",
            "2": "二",
            "3": "三",
            "4": "四",
            "5": "五",
            "6": "六",
            "7": "七",
            "8": "八",
            "9": "九",
        }
    )
    def normalize_text(self, text: str) -> str:
        text = (text or "").strip().replace("\u3000", " ")
        text = text.translate(self._digit_map)
        return self._drop_pattern.sub("", text)
    def to_chars_from_normalized(self, normalized_text: str) -> list[str]:
        return list(normalized_text) if normalized_text else []
    def to_pinyin_seq_from_normalized(self, normalized_text: str) -> list[str]:
        return lazy_pinyin(normalized_text) if normalized_text else []
    def normalize_raw_event(self, event: RawAsrEvent) -> AsrEvent | None:
        normalized = self.normalize_text(event.text)
        if not normalized:
            return None
        return AsrEvent(
            event_type=event.event_type,
            text=event.text,
            normalized_text=normalized,
            chars=self.to_chars_from_normalized(normalized),
            pinyin_seq=self.to_pinyin_seq_from_normalized(normalized),
            emitted_at_sec=event.emitted_at_sec,
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/asr/sherpa_streaming_provider.py`

```python
from __future__ import annotations
import logging
import time
from typing import Any
import numpy as np
from shadowing.interfaces.asr import ASRProvider
from shadowing.types import AsrEventType, RawAsrEvent
logger = logging.getLogger(__name__)
class SherpaStreamingProvider(ASRProvider):
    def __init__(
        self,
        model_config: dict,
        hotwords: str = "",
        sample_rate: int = 16000,
        emit_partial_interval_sec: float = 0.08,
        enable_endpoint: bool = True,
        debug_feed: bool = False,
        debug_feed_every_n_chunks: int = 20,
    ) -> None:
        self.model_config = model_config
        self.hotwords = hotwords
        self.sample_rate = int(sample_rate)
        self.emit_partial_interval_sec = float(emit_partial_interval_sec)
        self.enable_endpoint = bool(enable_endpoint)
        self.debug_feed = bool(debug_feed)
        self.debug_feed_every_n_chunks = max(1, int(debug_feed_every_n_chunks))
        self._recognizer: Any | None = None
        self._stream: Any | None = None
        self._running = False
        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0
        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = 0.0
        self._summary_interval_sec = 2.5
        self._last_ready_state = False
        self._last_endpoint_state = False
        self._min_meaningful_text_len = int(self.model_config.get("min_meaningful_text_len", 2))
        self._endpoint_min_interval_sec = float(self.model_config.get("endpoint_min_interval_sec", 0.35))
        self._force_reset_after_empty_endpoints = int(
            self.model_config.get("force_reset_after_empty_endpoints", 999999999)
        )
        self._reset_on_empty_endpoint = bool(self.model_config.get("reset_on_empty_endpoint", False))
        self._preserve_stream_on_partial_only = bool(
            self.model_config.get("preserve_stream_on_partial_only", True)
        )
        self._log_hotwords_on_start = bool(self.model_config.get("log_hotwords_on_start", True))
        self._log_hotwords_preview_on_start = bool(
            self.model_config.get("log_hotwords_preview_on_start", True)
        )
        self._hotwords_preview_limit = max(1, int(self.model_config.get("hotwords_preview_limit", 12)))
        self._info_logging = bool(self.model_config.get("info_logging", True))
    def start(self) -> None:
        self._recognizer = self._build_recognizer()
        self._stream = self._recognizer.create_stream()
        self._running = True
        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0
        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False
        hotword_lines = self._parse_hotword_lines(self.hotwords)
        preview = hotword_lines[: self._hotwords_preview_limit]
        if self._info_logging and self._log_hotwords_on_start:
            logger.info(
                "[ASR-HOTWORDS] count=%d score=%.2f",
                len(hotword_lines),
                float(self.model_config.get("hotwords_score", 1.5)),
            )
            if self._log_hotwords_preview_on_start:
                if preview:
                    logger.info("[ASR-HOTWORDS-PREVIEW] %s", " | ".join(preview))
                else:
                    logger.info("[ASR-HOTWORDS-PREVIEW] <empty>")
        if self.debug_feed:
            logger.debug(
                "[ASR-CONFIG] sample_rate=%d emit_partial_interval_sec=%.3f "
                "enable_endpoint=%s min_meaningful_text_len=%d "
                "endpoint_min_interval_sec=%.3f reset_on_empty_endpoint=%s "
                "preserve_stream_on_partial_only=%s",
                self.sample_rate,
                self.emit_partial_interval_sec,
                self.enable_endpoint,
                self._min_meaningful_text_len,
                self._endpoint_min_interval_sec,
                self._reset_on_empty_endpoint,
                self._preserve_stream_on_partial_only,
            )
    def feed_pcm16(self, pcm_bytes: bytes) -> None:
        if not self._running or self._recognizer is None or self._stream is None or not pcm_bytes:
            return
        audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        if audio_i16.size == 0:
            return
        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        self._feed_counter += 1
        if self.debug_feed and self._feed_counter % self.debug_feed_every_n_chunks == 0:
            abs_mean = float(np.mean(np.abs(audio_f32))) if audio_f32.size else 0.0
            peak = float(np.max(np.abs(audio_f32))) if audio_f32.size else 0.0
            logger.debug(
                "[ASR-FEED] chunks=%d samples=%d abs_mean=%.5f peak=%.5f",
                self._feed_counter,
                audio_f32.size,
                abs_mean,
                peak,
            )
        self._stream.accept_waveform(self.sample_rate, audio_f32)
        ready_before = self._recognizer.is_ready(self._stream)
        if self.debug_feed and ready_before and not self._last_ready_state:
            logger.debug("[ASR-READY] stream became ready at feed_chunks=%d", self._feed_counter)
        self._last_ready_state = bool(ready_before)
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1
        self._maybe_log_summary()
    def poll_raw_events(self) -> list[RawAsrEvent]:
        if not self._running or self._recognizer is None or self._stream is None:
            return []
        now = time.monotonic()
        events: list[RawAsrEvent] = []
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
            self._decode_counter += 1
        partial_text = self._normalize_text(self._get_result_text())
        if self.debug_feed and partial_text and partial_text != self._last_partial_log_text:
            logger.debug("[ASR-PARTIAL-RAW] %r", partial_text)
            self._last_partial_log_text = partial_text
        if (
            partial_text
            and partial_text != self._last_partial_text
            and (now - self._last_emit_at) >= self.emit_partial_interval_sec
        ):
            events.append(
                RawAsrEvent(
                    event_type=AsrEventType.PARTIAL,
                    text=partial_text,
                    emitted_at_sec=now,
                )
            )
            self._last_partial_text = partial_text
            self._last_emit_at = now
        endpoint_hit = self.enable_endpoint and self._is_endpoint()
        if self.debug_feed and endpoint_hit and not self._last_endpoint_state:
            preview = partial_text[:48]
            logger.debug(
                "[ASR-ENDPOINT-HIT] count_next=%d partial_len=%d preview=%r",
                self._endpoint_count + 1,
                len(partial_text),
                preview,
            )
        self._last_endpoint_state = bool(endpoint_hit)
        if endpoint_hit:
            if (now - self._last_endpoint_at) < self._endpoint_min_interval_sec:
                self._maybe_log_summary()
                return events
            self._endpoint_count += 1
            self._last_endpoint_at = now
            final_text = self._normalize_text(self._get_result_text())
            should_emit_final = self._is_meaningful_result(final_text)
            if self.debug_feed and final_text and final_text != self._last_final_text:
                logger.debug("[ASR-FINAL-RAW] %r", final_text)
            if should_emit_final and final_text != self._last_final_text:
                events.append(
                    RawAsrEvent(
                        event_type=AsrEventType.FINAL,
                        text=final_text,
                        emitted_at_sec=now,
                    )
                )
                self._last_final_text = final_text
                self._final_emit_count += 1
                self._empty_endpoint_count = 0
                self._reset_stream_state_only()
                self._last_partial_text = ""
                self._last_partial_log_text = ""
                self._last_ready_state = False
                self._last_endpoint_state = False
                if self.debug_feed:
                    logger.debug(
                        "[ASR-ENDPOINT] count=%d final_count=%d last_endpoint_at=%.3f "
                        "action=reset_after_final",
                        self._endpoint_count,
                        self._final_emit_count,
                        self._last_endpoint_at,
                    )
            else:
                self._empty_endpoint_count += 1
                if self.debug_feed:
                    logger.debug(
                        "[ASR-ENDPOINT-IGNORED] count=%d empty_count=%d partial_len=%d final_len=%d",
                        self._endpoint_count,
                        self._empty_endpoint_count,
                        len(partial_text),
                        len(final_text),
                    )
                if self._reset_on_empty_endpoint:
                    no_partial_context = not partial_text
                    no_final_context = not final_text
                    if self._preserve_stream_on_partial_only and partial_text and not final_text:
                        no_partial_context = False
                    if (
                        no_partial_context
                        and no_final_context
                        and self._empty_endpoint_count >= self._force_reset_after_empty_endpoints
                    ):
                        self._reset_stream_state_only()
                        self._last_partial_text = ""
                        self._last_partial_log_text = ""
                        self._last_ready_state = False
                        self._last_endpoint_state = False
                        self._empty_endpoint_count = 0
                        if self.debug_feed:
                            logger.debug(
                                "[ASR-ENDPOINT] count=%d final_count=%d last_endpoint_at=%.3f "
                                "action=reset_after_empty_endpoint",
                                self._endpoint_count,
                                self._final_emit_count,
                                self._last_endpoint_at,
                            )
        self._maybe_log_summary()
        return events
    def reset(self) -> None:
        if self._recognizer is None:
            return
        self._reset_stream_state_only()
        self._last_partial_text = ""
        self._last_final_text = ""
        self._last_emit_at = 0.0
        self._feed_counter = 0
        self._decode_counter = 0
        self._endpoint_count = 0
        self._empty_endpoint_count = 0
        self._last_endpoint_at = 0.0
        self._final_emit_count = 0
        self._last_partial_log_text = ""
        self._last_summary_log_at = time.monotonic()
        self._last_ready_state = False
        self._last_endpoint_state = False
        if self.debug_feed:
            logger.debug("[ASR-RESET] stream reset by external request")
    def close(self) -> None:
        self._running = False
        self._stream = None
        self._recognizer = None
    def _normalize_text(self, text: str) -> str:
        return str(text or "").strip()
    def _is_meaningful_result(self, text: str) -> bool:
        text = self._normalize_text(text)
        if not text:
            return False
        if len(text) < self._min_meaningful_text_len:
            return False
        return True
    def _get_result_text(self) -> str:
        result = self._recognizer.get_result(self._stream)
        if isinstance(result, str):
            return result
        if hasattr(result, "text"):
            return str(result.text or "")
        if isinstance(result, dict):
            return str(result.get("text", ""))
        return ""
    def _is_endpoint(self) -> bool:
        if self._recognizer is None or self._stream is None:
            return False
        if hasattr(self._recognizer, "is_endpoint"):
            try:
                return bool(self._recognizer.is_endpoint(self._stream))
            except TypeError:
                return False
        return False
    def _reset_stream_state_only(self) -> None:
        if self._recognizer is not None:
            self._stream = self._recognizer.create_stream()
    def _parse_hotword_lines(self, hotwords: str) -> list[str]:
        lines = [line.strip() for line in str(hotwords or "").splitlines() if line.strip()]
        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return deduped
    def _maybe_log_summary(self) -> None:
        if not self.debug_feed:
            return
        now = time.monotonic()
        if (now - self._last_summary_log_at) < self._summary_interval_sec:
            return
        current_text = ""
        if self._recognizer is not None and self._stream is not None:
            current_text = self._get_result_text().strip()
        preview = current_text[:32]
        logger.debug(
            "[ASR-SUMMARY] feeds=%d decodes=%d partials_len=%d finals=%d "
            "endpoints=%d empty_endpoints=%d preview=%r",
            self._feed_counter,
            self._decode_counter,
            len(self._last_partial_text),
            self._final_emit_count,
            self._endpoint_count,
            self._empty_endpoint_count,
            preview,
        )
        self._last_summary_log_at = now
    def _build_recognizer(self):
        import sherpa_onnx
        cfg = self.model_config
        tokens = cfg.get("tokens", "")
        encoder = cfg.get("encoder", "")
        decoder = cfg.get("decoder", "")
        joiner = cfg.get("joiner", "")
        missing = [
            name
            for name, value in (
                ("tokens", tokens),
                ("encoder", encoder),
                ("decoder", decoder),
                ("joiner", joiner),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing sherpa model paths in config: " + ", ".join(missing))
        hotwords = str(self.hotwords or cfg.get("hotwords", "")).strip()
        hotwords_score = float(cfg.get("hotwords_score", 1.5))
        if self.debug_feed:
            hotword_lines = self._parse_hotword_lines(hotwords)
            logger.debug(
                "[ASR-BUILD] hotwords_count=%d hotwords_score=%.2f provider=%s decoding_method=%s",
                len(hotword_lines),
                hotwords_score,
                cfg.get("provider", "cpu"),
                cfg.get("decoding_method", "greedy_search"),
            )
            if hotword_lines:
                logger.debug("[ASR-BUILD-HOTWORDS] %s", " | ".join(hotword_lines[:20]))
        base_kwargs = dict(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=cfg.get("num_threads", 2),
            sample_rate=self.sample_rate,
            feature_dim=cfg.get("feature_dim", 80),
            decoding_method=cfg.get("decoding_method", "greedy_search"),
            provider=cfg.get("provider", "cpu"),
        )
        hotword_kwargs = dict(
            hotwords=hotwords,
            hotwords_score=hotwords_score,
        )
        endpoint_kwargs = dict(
            enable_endpoint_detection=self.enable_endpoint,
            rule1_min_trailing_silence=cfg.get("rule1_min_trailing_silence", 10.0),
            rule2_min_trailing_silence=cfg.get("rule2_min_trailing_silence", 10.0),
            rule3_min_utterance_length=cfg.get("rule3_min_utterance_length", 60.0),
        )
        try:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **hotword_kwargs,
                **endpoint_kwargs,
            )
            if self.debug_feed:
                logger.debug("[ASR-BUILD] recognizer_created mode=transducer+hotwords+endpoint")
            return recognizer
        except TypeError as e1:
            if self.debug_feed:
                logger.debug("[ASR-BUILD] hotwords kwargs not accepted, fallback 1: %s", e1)
        try:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                **base_kwargs,
                **endpoint_kwargs,
            )
            if self.debug_feed:
                logger.debug("[ASR-BUILD] recognizer_created mode=transducer+endpoint")
            return recognizer
        except TypeError as e2:
            if self.debug_feed:
                logger.debug("[ASR-BUILD] endpoint kwargs not accepted, fallback 2: %s", e2)
        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**base_kwargs)
        if self.debug_feed:
            logger.debug("[ASR-BUILD] recognizer_created mode=transducer_basic")
        return recognizer
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/device_utils.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import sounddevice as sd
@dataclass(slots=True)
class InputDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float
    hostapi_name: str
def list_input_devices() -> list[InputDeviceInfo]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    results: list[InputDeviceInfo] = []
    for idx, dev in enumerate(devices):
        max_in = int(dev["max_input_channels"])
        if max_in <= 0:
            continue
        hostapi_name = hostapis[int(dev["hostapi"])]["name"]
        results.append(
            InputDeviceInfo(
                index=int(idx),
                name=str(dev["name"]),
                max_input_channels=max_in,
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=str(hostapi_name),
            )
        )
    return results
def print_input_devices() -> None:
    devices = list_input_devices()
    if not devices:
        return
    for d in devices:
def get_default_input_device_index() -> int | None:
    default_input, _ = sd.default.device
    if default_input is None or int(default_input) < 0:
        return None
    return int(default_input)
def choose_input_device(
    preferred_index: int | None = None,
    preferred_name_substring: str | None = None,
) -> int | None:
    devices = list_input_devices()
    if not devices:
        return None
    if preferred_index is not None:
        for d in devices:
            if d.index == preferred_index:
                return d.index
    if preferred_name_substring:
        keyword = preferred_name_substring.lower().strip()
        for d in devices:
            if keyword and keyword in d.name.lower():
                return d.index
    default_idx = get_default_input_device_index()
    if default_idx is not None:
        return default_idx
    return devices[0].index
def check_input_settings(
    device: int | None,
    samplerate: int,
    channels: int = 1,
    dtype: str = "float32",
) -> bool:
    try:
        sd.check_input_settings(
            device=device,
            samplerate=int(samplerate),
            channels=int(channels),
            dtype=str(dtype),
        )
        return True
    except Exception:
        return False
def pick_working_input_config(
    preferred_device: int | None = None,
    preferred_name_substring: str | None = None,
    preferred_rates: list[int] | None = None,
    channels: int = 1,
    dtype: str = "float32",
) -> dict[str, Any] | None:
    preferred_rates = preferred_rates or [48000, 44100, 16000]
    device = choose_input_device(
        preferred_index=preferred_device,
        preferred_name_substring=preferred_name_substring,
    )
    if device is None:
        return None
    for sr in preferred_rates:
        if int(sr) <= 0:
            continue
        if check_input_settings(
            device=device,
            samplerate=int(sr),
            channels=int(channels),
            dtype=str(dtype),
        ):
            return {
                "device": int(device),
                "samplerate": int(sr),
                "channels": int(channels),
                "dtype": str(dtype),
            }
    return None
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/resampler.py`

```python
from __future__ import annotations
from math import gcd
import numpy as np
from scipy.signal import resample_poly
class AudioResampler:
    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        g = gcd(self.src_rate, self.dst_rate)
        self.up = self.dst_rate // g
        self.down = self.src_rate // g
    def float_to_pcm16_bytes(self, audio: np.ndarray) -> bytes:
        clipped = np.clip(audio, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()
    def process_float_mono(self, audio: np.ndarray) -> bytes:
        if audio.ndim != 1:
            raise ValueError(f"Expected mono audio with shape (n,), got {audio.shape}")
        if self.src_rate == self.dst_rate:
            return self.float_to_pcm16_bytes(audio)
        y = resample_poly(audio, self.up, self.down).astype(np.float32, copy=False)
        return self.float_to_pcm16_bytes(y)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/soundcard_recorder.py`

```python
from __future__ import annotations
import threading
import time
from collections.abc import Callable
import numpy as np
import pythoncom
import soundcard as sc
from shadowing.interfaces.recorder import Recorder
from shadowing.realtime.capture.resampler import AudioResampler
class SoundCardRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        block_frames: int = 1440,
        include_loopback: bool = False,
        debug_level_meter: bool = False,
        debug_level_every_n_blocks: int = 20,
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.block_frames = max(128, int(block_frames))
        self.include_loopback = bool(include_loopback)
        self.debug_level_meter = bool(debug_level_meter)
        self.debug_level_every_n_blocks = max(1, int(debug_level_every_n_blocks))
        self._callback: Callable[[bytes], None] | None = None
        self._mic = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._opened_channels: int | None = None
        self._opened_samplerate: int | None = None
        self._debug_counter = 0
        self._resampler: AudioResampler | None = None
        self._last_error: Exception | None = None
    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._running:
            return
        self._callback = on_audio_frame
        self._mic = self._resolve_microphone(self.device, self.include_loopback)
        open_candidates = self._build_open_candidates()
        last_error: Exception | None = None
        for sr, ch in open_candidates:
            try:
                with self._mic.recorder(samplerate=sr, channels=ch) as rec:
                    _ = rec.record(numframes=min(self.block_frames, 256))
                self._opened_samplerate = int(sr)
                self._opened_channels = int(ch)
                self._resampler = AudioResampler(src_rate=self._opened_samplerate, dst_rate=self.target_sample_rate)
                last_error = None
                break
            except Exception as e:
                last_error = e
        if last_error is not None or self._opened_samplerate is None or self._opened_channels is None:
            msg = str(last_error)
            if "0x80070005" in msg:
                raise RuntimeError(
                    "Failed to open microphone with soundcard: access denied (0x80070005). Please enable Windows microphone privacy permissions and close apps using the mic."
                )
            raise RuntimeError(f"Failed to open microphone with soundcard. device={self.device!r}, last_error={last_error}")
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
    def stop(self) -> None:
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
    def close(self) -> None:
        self.stop()
    def _capture_loop(self) -> None:
        assert self._mic is not None
        assert self._callback is not None
        assert self._opened_samplerate is not None
        assert self._opened_channels is not None
        pythoncom.CoInitialize()
        try:
            with self._mic.recorder(samplerate=self._opened_samplerate, channels=self._opened_channels) as rec:
                while self._running:
                    data = rec.record(numframes=self.block_frames)
                    if data is None:
                        time.sleep(0.005)
                        continue
                    audio = np.asarray(data, dtype=np.float32)
                    if audio.ndim == 1:
                        audio = audio[:, None]
                    if audio.shape[1] > 1:
                        audio = np.mean(audio, axis=1, keepdims=True)
                    mono = np.squeeze(audio, axis=1).astype(np.float32, copy=False)
                    self._debug_counter += 1
                    if self.debug_level_meter and (self._debug_counter <= 3 or self._debug_counter % self.debug_level_every_n_blocks == 0):
                        _rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                        _peak = float(np.max(np.abs(mono))) if mono.size else 0.0
                    if self._resampler is None:
                        raise RuntimeError("SoundCardRecorder resampler is not initialized.")
                    pcm16_bytes = self._resampler.process_float_mono(mono)
                    self._callback(pcm16_bytes)
        except Exception as e:
            self._last_error = e
        finally:
            pythoncom.CoUninitialize()
            self._running = False
    def _build_open_candidates(self) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int]] = []
        candidate_srs: list[int] = []
        for sr in [self.sample_rate_in, 48000, 44100, 16000]:
            if sr > 0 and sr not in candidate_srs:
                candidate_srs.append(sr)
        candidate_channels: list[int] = []
        for ch in [1, self.channels, 2]:
            if ch > 0 and ch not in candidate_channels:
                candidate_channels.append(ch)
        for sr in candidate_srs:
            for ch in candidate_channels:
                candidates.append((int(sr), int(ch)))
        return candidates
    def _resolve_microphone(self, device: int | str | None, include_loopback: bool):
        mics = list(sc.all_microphones(include_loopback=include_loopback))
        if not mics:
            raise RuntimeError("No microphones found via soundcard.")
        if device is None:
            default_mic = sc.default_microphone()
            if default_mic is None:
                raise RuntimeError("No default microphone found via soundcard.")
            return default_mic
        if isinstance(device, int):
            if 0 <= device < len(mics):
                return mics[device]
            raise ValueError(
                f"Soundcard microphone index out of range: {device}. Valid range is 0..{len(mics) - 1}. Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )
        key = str(device).strip().lower()
        if key.isdigit():
            idx = int(key)
            if 0 <= idx < len(mics):
                return mics[idx]
            raise ValueError(
                f"Soundcard microphone index out of range: {idx}. Valid range is 0..{len(mics) - 1}. Note: soundcard backend uses its own microphone list index, not sounddevice raw device index."
            )
        for mic in mics:
            if key in mic.name.lower():
                return mic
        raise ValueError(
            f"No matching microphone found for {device!r}. For soundcard backend, pass either a soundcard microphone list index or a device name substring."
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/capture/sounddevice_recorder.py`

```python
from __future__ import annotations
from collections.abc import Callable
from typing import Any
import numpy as np
import sounddevice as sd
from shadowing.interfaces.recorder import Recorder
from shadowing.realtime.capture.resampler import AudioResampler
class SoundDeviceRecorder(Recorder):
    def __init__(
        self,
        sample_rate_in: int,
        target_sample_rate: int,
        channels: int = 1,
        device: int | str | None = None,
        dtype: str = "float32",
        blocksize: int = 0,
        latency: str | float = "low",
    ) -> None:
        self.sample_rate_in = int(sample_rate_in)
        self.target_sample_rate = int(target_sample_rate)
        self.channels = int(channels)
        self.device = device
        self.dtype = dtype
        self.blocksize = int(blocksize)
        self.latency = latency
        self._stream: sd.InputStream | None = None
        self._callback: Callable[[bytes], None] | None = None
        self._opened_samplerate: int | None = None
        self._opened_channels: int | None = None
        self._resampler: AudioResampler | None = None
    def start(self, on_audio_frame: Callable[[bytes], None]) -> None:
        if self._stream is not None:
            return
        self._callback = on_audio_frame
        device = self._resolve_input_device(self.device)
        dev_info = sd.query_devices(device, "input")
        max_in = int(dev_info["max_input_channels"])
        if max_in < 1:
            raise RuntimeError(f"Invalid input device: {dev_info}")
        opened_channels = max(1, min(self.channels, max_in))
        sr = self._pick_openable_samplerate(device, dev_info, opened_channels)
        self._opened_samplerate = sr
        self._opened_channels = opened_channels
        self._resampler = AudioResampler(src_rate=sr, dst_rate=self.target_sample_rate)
        self._stream = sd.InputStream(
            samplerate=sr,
            blocksize=self.blocksize,
            device=device,
            channels=opened_channels,
            dtype=self.dtype,
            latency=self.latency,
            callback=self._audio_callback,
        )
        self._stream.start()
    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
    def close(self) -> None:
        self.stop()
    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if self._callback is None:
            return
        audio = np.asarray(indata, dtype=np.float32)
        if audio.ndim == 1:
            mono = audio
        else:
            mono = np.mean(audio, axis=1).astype(np.float32, copy=False)
        if self._resampler is None:
            raise RuntimeError("Recorder resampler is not initialized.")
        self._callback(self._resampler.process_float_mono(mono))
    def _resolve_input_device(self, device: int | str | None) -> int | str | None:
        if device is None:
            return None
        if isinstance(device, int):
            return device
        target = str(device).strip().lower()
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev["max_input_channels"]) > 0 and target in str(dev["name"]).lower():
                return idx
        raise ValueError(f"No matching input device found for {device!r}")
    def _pick_openable_samplerate(self, device: int | str | None, dev_info: Any, opened_channels: int) -> int:
        candidates: list[int] = []
        for sr in [self.sample_rate_in, int(float(dev_info["default_samplerate"])), 48000, 44100, 16000]:
            if sr > 0 and sr not in candidates:
                candidates.append(sr)
        for sr in candidates:
            try:
                sd.check_input_settings(
                    device=device,
                    samplerate=sr,
                    channels=opened_channels,
                    dtype=self.dtype,
                )
                return sr
            except Exception:
                continue
        raise RuntimeError(f"Failed to find openable samplerate for input device: {dev_info}")
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/policy.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass(slots=True)
class ControlPolicy:
    target_lead_sec: float = 0.18
    hold_if_lead_sec: float = 1.05
    resume_if_lead_sec: float = 0.36
    seek_if_lag_sec: float = -2.60
    min_confidence: float = 0.70
    seek_cooldown_sec: float = 2.20
    gain_following: float = 0.52
    gain_transition: float = 0.72
    gain_soft_duck: float = 0.36
    recover_after_seek_sec: float = 0.80
    startup_grace_sec: float = 3.20
    low_confidence_hold_sec: float = 2.20
    bootstrapping_sec: float = 2.20
    guide_play_sec: float = 3.20
    no_progress_hold_min_play_sec: float = 5.80
    speaking_recent_sec: float = 1.10
    progress_stale_sec: float = 1.45
    hold_trend_sec: float = 1.00
    hold_extra_lead_sec: float = 0.22
    low_confidence_continue_sec: float = 1.80
    tracking_quality_hold_min: float = 0.60
    tracking_quality_seek_min: float = 0.84
    resume_from_hold_event_fresh_sec: float = 0.60
    resume_from_hold_speaking_lead_slack_sec: float = 0.72
    reacquire_soft_duck_sec: float = 2.40
    disable_seek: bool = False
    bluetooth_long_session_target_lead_sec: float = 0.38
    bluetooth_long_session_hold_if_lead_sec: float = 1.35
    bluetooth_long_session_resume_if_lead_sec: float = 0.30
    bluetooth_long_session_seek_if_lag_sec: float = -3.20
    bluetooth_long_session_seek_cooldown_sec: float = 3.20
    bluetooth_long_session_progress_stale_sec: float = 1.75
    bluetooth_long_session_hold_trend_sec: float = 1.15
    bluetooth_long_session_tracking_quality_hold_min: float = 0.58
    bluetooth_long_session_tracking_quality_seek_min: float = 0.88
    bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec: float = 0.82
    bluetooth_long_session_gain_following: float = 0.50
    bluetooth_long_session_gain_transition: float = 0.66
    bluetooth_long_session_gain_soft_duck: float = 0.32
```

---
### 文件: `shadowing_app/src/shadowing/realtime/control/state_machine_controller.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.sync_evidence import SyncEvidence, SyncState, TrackingState
from shadowing.types import ControlAction, ControlDecision, FusionEvidence, PlaybackState
@dataclass(slots=True)
class _PressureState:
    hold_pressure: float = 0.0
    resume_pressure: float = 0.0
    seek_pressure: float = 0.0
    soft_duck_pressure: float = 0.0
    lead_error_ema: float = 0.0
    lead_error_derivative_ema: float = 0.0
    tracking_quality_ema: float = 0.0
    confidence_ema: float = 0.0
    speech_confidence_ema: float = 0.0
    last_tick_at: float = 0.0
    last_lead_error: float = 0.0
class StateMachineController:
    def __init__(
        self,
        *,
        policy: ControlPolicy,
        disable_seek: bool = False,
        debug: bool = False,
    ) -> None:
        self.policy = policy
        self.disable_seek = bool(disable_seek)
        self.debug = bool(debug)
        now = time.monotonic()
        self._started_at = now
        self._last_resume_at = now
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_soft_duck_at = 0.0
        self._last_voice_like_at = now
        self._last_effective_idx = 0
        self._pressure = _PressureState(last_tick_at=now)
    def reset(self) -> None:
        now = time.monotonic()
        self._started_at = now
        self._last_resume_at = now
        self._last_hold_at = 0.0
        self._last_seek_at = 0.0
        self._last_soft_duck_at = 0.0
        self._last_voice_like_at = now
        self._last_effective_idx = 0
        self._pressure = _PressureState(last_tick_at=now)
    def decide(
        self,
        playback,
        progress,
        signal_quality,
        sync_evidence: SyncEvidence | None = None,
        fusion_evidence: FusionEvidence | None = None,
    ) -> ControlDecision:
        now = time.monotonic()
        fusion_still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        fusion_repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)
        fusion_reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)
        fusion_fused_conf = 0.0 if fusion_evidence is None else float(fusion_evidence.fused_confidence)
        if progress is None:
            if fusion_evidence is None or max(fusion_fused_conf, fusion_still_following, fusion_reentry) < 0.58:
                return ControlDecision(
                    action=ControlAction.NOOP,
                    reason="no_progress",
                    target_gain=self._gain_for_state(
                        playback.state,
                        following=False,
                        bluetooth_long_session_mode=False,
                    ),
                    confidence=0.0,
                )
            effective_idx = int(getattr(fusion_evidence, "estimated_ref_idx_hint", 0))
            tracking_quality = max(0.0, min(1.0, fusion_fused_conf * 0.84))
            confidence = fusion_fused_conf
            active_speaking = bool(fusion_still_following >= 0.60 or fusion_reentry >= 0.56)
            recently_progressed = False
            progress_age_sec = 9999.0
            estimated_ref_time_sec = float(fusion_evidence.estimated_ref_time_sec)
            stable = bool(fusion_fused_conf >= 0.72)
            position_source = "audio"
        else:
            effective_idx = int(getattr(progress, "estimated_ref_idx", 0))
            tracking_quality = float(getattr(progress, "tracking_quality", 0.0))
            confidence = float(getattr(progress, "confidence", 0.0))
            active_speaking = bool(getattr(progress, "active_speaking", False))
            recently_progressed = bool(getattr(progress, "recently_progressed", False))
            progress_age_sec = float(getattr(progress, "progress_age_sec", 9999.0))
            estimated_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
            stable = bool(getattr(progress, "stable", False))
            position_source = str(getattr(progress, "position_source", "text"))
        if active_speaking or recently_progressed or fusion_still_following >= 0.62 or fusion_reentry >= 0.56:
            self._last_voice_like_at = now
        if effective_idx > self._last_effective_idx:
            self._last_effective_idx = effective_idx
        speech_conf = 0.0
        tracking_state = TrackingState.NONE
        sync_state = SyncState.BOOTSTRAP
        allow_seek = False
        bluetooth_mode = False
        bluetooth_long_session_mode = False
        if sync_evidence is not None:
            speech_conf = float(sync_evidence.speech_confidence)
            tracking_state = sync_evidence.tracking_state
            sync_state = sync_evidence.sync_state
            allow_seek = bool(sync_evidence.allow_seek)
            bluetooth_mode = bool(sync_evidence.bluetooth_mode)
            bluetooth_long_session_mode = bool(sync_evidence.bluetooth_long_session_mode)
        target_lead_sec = (
            self.policy.bluetooth_long_session_target_lead_sec
            if bluetooth_long_session_mode
            else self.policy.target_lead_sec
        )
        hold_if_lead_sec = (
            self.policy.bluetooth_long_session_hold_if_lead_sec
            if bluetooth_long_session_mode
            else self.policy.hold_if_lead_sec
        )
        resume_if_lead_sec = (
            self.policy.bluetooth_long_session_resume_if_lead_sec
            if bluetooth_long_session_mode
            else self.policy.resume_if_lead_sec
        )
        seek_if_lag_sec = (
            self.policy.bluetooth_long_session_seek_if_lag_sec
            if bluetooth_long_session_mode
            else self.policy.seek_if_lag_sec
        )
        seek_cooldown_sec = (
            self.policy.bluetooth_long_session_seek_cooldown_sec
            if bluetooth_long_session_mode
            else self.policy.seek_cooldown_sec
        )
        progress_stale_threshold = (
            self.policy.bluetooth_long_session_progress_stale_sec
            if bluetooth_long_session_mode
            else self.policy.progress_stale_sec
        )
        tracking_quality_hold_min = (
            self.policy.bluetooth_long_session_tracking_quality_hold_min
            if bluetooth_long_session_mode
            else self.policy.tracking_quality_hold_min
        )
        tracking_quality_seek_min = (
            self.policy.bluetooth_long_session_tracking_quality_seek_min
            if bluetooth_long_session_mode
            else self.policy.tracking_quality_seek_min
        )
        resume_from_hold_speaking_lead_slack_sec = (
            self.policy.bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec
            if bluetooth_long_session_mode
            else self.policy.resume_from_hold_speaking_lead_slack_sec
        )
        in_startup_grace = (now - self._started_at) < (
            self.policy.startup_grace_sec + (1.2 if bluetooth_long_session_mode else 0.6)
        )
        in_resume_cooldown = (now - self._last_resume_at) < (0.70 if bluetooth_long_session_mode else 0.45)
        in_seek_cooldown = (now - self._last_seek_at) < seek_cooldown_sec
        in_soft_duck_cooldown = (now - self._last_soft_duck_at) < (0.45 if bluetooth_long_session_mode else 0.30)
        speaking_recent = (now - self._last_voice_like_at) <= (
            self.policy.speaking_recent_sec + (0.35 if bluetooth_long_session_mode else 0.15)
        )
        progress_stale = progress_age_sec >= progress_stale_threshold
        playback_ref = float(playback.t_ref_heard_content_sec)
        if fusion_evidence is not None and fusion_evidence.fused_confidence >= 0.60 and tracking_quality < 0.56:
            user_ref = float(fusion_evidence.estimated_ref_time_sec)
        else:
            user_ref = float(estimated_ref_time_sec)
        lead_sec = playback_ref - user_ref
        lead_error_sec = float(lead_sec - target_lead_sec)
        dt = max(0.01, now - self._pressure.last_tick_at)
        self._pressure.last_tick_at = now
        self._update_emas(
            dt=dt,
            lead_error_sec=lead_error_sec,
            tracking_quality=tracking_quality,
            confidence=confidence,
            speech_confidence=speech_conf,
        )
        engaged_recent = bool(
            speaking_recent
            or fusion_still_following >= 0.62
            or fusion_reentry >= 0.56
            or recently_progressed
            or (active_speaking and tracking_quality >= tracking_quality_hold_min - 0.08)
        )
        strong_resume_ok = bool(
            (
                recently_progressed
                or active_speaking
                or fusion_reentry >= 0.62
                or fusion_still_following >= 0.74
            )
            and tracking_quality >= tracking_quality_hold_min - 0.04
            and confidence >= self.policy.min_confidence - 0.14
            and lead_error_sec >= -resume_from_hold_speaking_lead_slack_sec
        )
        weak_resume_ok = bool(
            engaged_recent
            and tracking_quality >= tracking_quality_hold_min - 0.10
            and confidence >= max(0.48, self.policy.min_confidence - 0.22)
            and lead_error_sec >= -resume_from_hold_speaking_lead_slack_sec
        )
        following = bool(
            strong_resume_ok
            or weak_resume_ok
            or tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED)
            or fusion_still_following >= 0.72
        )
        self._update_pressures(
            dt=dt,
            playback_state=playback.state,
            lead_sec=lead_sec,
            lead_error_sec=lead_error_sec,
            progress_stale=progress_stale,
            tracking_quality=tracking_quality,
            confidence=confidence,
            stable=stable,
            speaking_recent=speaking_recent,
            engaged_recent=engaged_recent,
            in_startup_grace=in_startup_grace,
            strong_resume_ok=strong_resume_ok,
            weak_resume_ok=weak_resume_ok,
            in_resume_cooldown=in_resume_cooldown,
            in_seek_cooldown=in_seek_cooldown,
            allow_seek=allow_seek and (not self.disable_seek),
            tracking_state=tracking_state,
            sync_state=sync_state,
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=bluetooth_long_session_mode,
            hold_if_lead_sec=hold_if_lead_sec,
            resume_if_lead_sec=resume_if_lead_sec,
            seek_if_lag_sec=seek_if_lag_sec,
            tracking_quality_hold_min=tracking_quality_hold_min,
            tracking_quality_seek_min=tracking_quality_seek_min,
            fusion_evidence=fusion_evidence,
            position_source=position_source,
        )
        if fusion_evidence is not None:
            if fusion_evidence.should_prevent_hold:
                self._pressure.hold_pressure *= 0.12
            if fusion_evidence.should_prevent_seek:
                self._pressure.seek_pressure *= 0.08
            if playback.state == PlaybackState.HOLDING and (
                fusion_still_following >= 0.74 or fusion_reentry >= 0.60
            ):
                self._pressure.resume_pressure = max(
                    self._pressure.resume_pressure,
                    1.04 if bluetooth_long_session_mode else 1.02,
                )
        if playback.state == PlaybackState.HOLDING and self._pressure.resume_pressure >= 1.0:
            self._last_resume_at = now
            self._pressure.hold_pressure *= 0.25
            self._pressure.resume_pressure = 0.0
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="resume_on_engaged_user",
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.PLAYING,
                    following=True,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=max(confidence, fusion_still_following * 0.88, fusion_fused_conf * 0.84),
                aggressiveness="low",
            )
        if (
            playback.state == PlaybackState.PLAYING
            and self._pressure.soft_duck_pressure >= (0.58 if bluetooth_long_session_mode else 0.62)
            and not in_soft_duck_cooldown
        ):
            self._last_soft_duck_at = now
            return ControlDecision(
                action=ControlAction.SOFT_DUCK,
                reason="soft_duck_wait_for_user",
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.HOLDING,
                    following=False,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=max(confidence, fusion_still_following * 0.66, fusion_fused_conf * 0.60),
                aggressiveness="low",
            )
        if (
            playback.state == PlaybackState.PLAYING
            and self._pressure.hold_pressure >= 1.0
            and not engaged_recent
            and fusion_repeated < 0.60
            and fusion_reentry < 0.54
        ):
            self._last_hold_at = now
            return ControlDecision(
                action=ControlAction.HOLD,
                reason="hold_when_user_disengaged",
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.HOLDING,
                    following=False,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=confidence,
                aggressiveness="low",
            )
        if (
            playback.state in (PlaybackState.PLAYING, PlaybackState.HOLDING)
            and self._pressure.seek_pressure >= 1.0
            and not self.disable_seek
            and allow_seek
            and not bluetooth_mode
            and fusion_repeated < 0.42
            and fusion_reentry < 0.42
            and not engaged_recent
            and (fusion_evidence is None or not fusion_evidence.should_prevent_seek)
        ):
            self._last_seek_at = now
            self._pressure.seek_pressure = 0.0
            self._pressure.hold_pressure *= 0.3
            target_time_sec = max(0.0, user_ref - target_lead_sec)
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="seek_only_when_clearly_derailed",
                target_time_sec=target_time_sec,
                lead_sec=lead_sec,
                target_gain=self._gain_for_state(
                    PlaybackState.PLAYING,
                    following=False,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                confidence=max(confidence, 0.30 + 0.40 * fusion_still_following),
                aggressiveness="low",
            )
        return ControlDecision(
            action=ControlAction.NOOP,
            reason="follow_user_smoothly",
            lead_sec=lead_sec,
            target_gain=self._gain_for_state(
                playback.state,
                following=following,
                bluetooth_long_session_mode=bluetooth_long_session_mode,
            ),
            confidence=max(confidence, fusion_still_following * 0.56, fusion_fused_conf * 0.52),
            aggressiveness="low",
        )
    def _update_emas(
        self,
        *,
        dt: float,
        lead_error_sec: float,
        tracking_quality: float,
        confidence: float,
        speech_confidence: float,
    ) -> None:
        alpha = 0.22
        deriv = (float(lead_error_sec) - float(self._pressure.last_lead_error)) / max(0.01, float(dt))
        self._pressure.last_lead_error = float(lead_error_sec)
        self._pressure.lead_error_ema = (
            (1.0 - alpha) * self._pressure.lead_error_ema + alpha * float(lead_error_sec)
        )
        self._pressure.lead_error_derivative_ema = (
            (1.0 - alpha) * self._pressure.lead_error_derivative_ema + alpha * float(deriv)
        )
        self._pressure.tracking_quality_ema = (
            (1.0 - alpha) * self._pressure.tracking_quality_ema + alpha * float(tracking_quality)
        )
        self._pressure.confidence_ema = (
            (1.0 - alpha) * self._pressure.confidence_ema + alpha * float(confidence)
        )
        self._pressure.speech_confidence_ema = (
            (1.0 - alpha) * self._pressure.speech_confidence_ema + alpha * float(speech_confidence)
        )
    def _update_pressures(
        self,
        *,
        dt: float,
        playback_state,
        lead_sec: float,
        lead_error_sec: float,
        progress_stale: bool,
        tracking_quality: float,
        confidence: float,
        stable: bool,
        speaking_recent: bool,
        engaged_recent: bool,
        in_startup_grace: bool,
        strong_resume_ok: bool,
        weak_resume_ok: bool,
        in_resume_cooldown: bool,
        in_seek_cooldown: bool,
        allow_seek: bool,
        tracking_state: TrackingState,
        sync_state: SyncState,
        bluetooth_mode: bool,
        bluetooth_long_session_mode: bool,
        hold_if_lead_sec: float,
        resume_if_lead_sec: float,
        seek_if_lag_sec: float,
        tracking_quality_hold_min: float,
        tracking_quality_seek_min: float,
        fusion_evidence: FusionEvidence | None,
        position_source: str,
    ) -> None:
        decay = (0.88 if bluetooth_long_session_mode else 0.84) ** max(1.0, dt * 15.0)
        self._pressure.hold_pressure *= decay
        self._pressure.resume_pressure *= decay
        self._pressure.seek_pressure *= decay
        self._pressure.soft_duck_pressure *= decay
        fusion_still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        fusion_repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)
        fusion_reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)
        lead_err = float(self._pressure.lead_error_ema)
        lead_err_d = float(self._pressure.lead_error_derivative_ema)
        large_positive_error = lead_sec >= hold_if_lead_sec
        large_negative_error = lead_sec <= seek_if_lag_sec
        near_target = abs(lead_err) <= resume_if_lead_sec
        if playback_state == PlaybackState.PLAYING:
            if large_positive_error:
                self._pressure.soft_duck_pressure += 0.26 if bluetooth_long_session_mode else 0.30
                if (
                    lead_sec >= (hold_if_lead_sec + (0.28 if bluetooth_long_session_mode else 0.20))
                    and not engaged_recent
                    and not in_startup_grace
                ):
                    self._pressure.hold_pressure += 0.18 if bluetooth_long_session_mode else 0.24
            if lead_err > 0.12 and lead_err_d > 0.05 and not engaged_recent:
                self._pressure.soft_duck_pressure += 0.10
            if progress_stale and not engaged_recent and not in_startup_grace:
                self._pressure.soft_duck_pressure += 0.16 if bluetooth_long_session_mode else 0.20
                if tracking_quality < tracking_quality_hold_min - 0.04:
                    self._pressure.hold_pressure += 0.14 if bluetooth_long_session_mode else 0.18
            if tracking_state == TrackingState.WEAK or sync_state == SyncState.DEGRADED:
                if engaged_recent:
                    self._pressure.soft_duck_pressure += 0.10
                else:
                    self._pressure.soft_duck_pressure += 0.16 if bluetooth_long_session_mode else 0.20
            if confidence < max(0.50, self.policy.min_confidence - 0.18) and not engaged_recent:
                self._pressure.soft_duck_pressure += 0.08
            if stable and tracking_quality >= 0.78 and near_target:
                self._pressure.hold_pressure *= 0.90
                self._pressure.soft_duck_pressure *= 0.88
        if playback_state == PlaybackState.HOLDING and not in_resume_cooldown:
            if strong_resume_ok and near_target:
                self._pressure.resume_pressure += 0.44 if bluetooth_long_session_mode else 0.50
            elif strong_resume_ok:
                self._pressure.resume_pressure += 0.30
            elif weak_resume_ok and lead_err >= -0.16:
                self._pressure.resume_pressure += 0.24 if bluetooth_long_session_mode else 0.30
            if fusion_reentry >= 0.60:
                self._pressure.resume_pressure += 0.24
            elif fusion_still_following >= 0.74:
                self._pressure.resume_pressure += 0.18
            if near_target and speaking_recent:
                self._pressure.resume_pressure += 0.12
        seek_trigger = bool(
            allow_seek
            and not in_seek_cooldown
            and playback_state == PlaybackState.PLAYING
            and large_negative_error
            and tracking_quality >= tracking_quality_seek_min
            and confidence >= max(0.74, self.policy.min_confidence)
            and tracking_state == TrackingState.LOCKED
            and sync_state == SyncState.STABLE
            and fusion_repeated < 0.40
            and fusion_reentry < 0.40
            and position_source != "audio"
            and not engaged_recent
            and not bluetooth_mode
            and (fusion_evidence is None or not fusion_evidence.should_prevent_seek)
        )
        if seek_trigger:
            self._pressure.seek_pressure += 0.18
        self._pressure.hold_pressure = max(0.0, min(1.4, self._pressure.hold_pressure))
        self._pressure.resume_pressure = max(0.0, min(1.4, self._pressure.resume_pressure))
        self._pressure.seek_pressure = max(0.0, min(1.4, self._pressure.seek_pressure))
        self._pressure.soft_duck_pressure = max(0.0, min(1.2, self._pressure.soft_duck_pressure))
    def _gain_for_state(self, state, *, following: bool, bluetooth_long_session_mode: bool) -> float:
        if bluetooth_long_session_mode:
            if state == PlaybackState.HOLDING:
                return self.policy.bluetooth_long_session_gain_soft_duck
            if following:
                return self.policy.bluetooth_long_session_gain_following
            return self.policy.bluetooth_long_session_gain_transition
        if state == PlaybackState.HOLDING:
            return self.policy.gain_soft_duck
        if following:
            return self.policy.gain_following
        return self.policy.gain_transition
```

---
### 文件: `shadowing_app/src/shadowing/realtime/controller.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
def _f(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)
def _b(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
@dataclass(slots=True)
class ControlDecision:
    action: str
    reason: str
    target_gain: float
    seek_to_ref_time_sec: float | None = None
class PlaybackController:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self.target_lead_sec = _f(config.get("target_lead_sec"), 0.18)
        self.hold_if_lead_sec = _f(config.get("hold_if_lead_sec"), 1.05)
        self.resume_if_lead_sec = _f(config.get("resume_if_lead_sec"), 0.36)
        self.seek_if_lag_sec = _f(config.get("seek_if_lag_sec"), -2.60)
        self.min_confidence = _f(config.get("min_confidence"), 0.70)
        self.seek_cooldown_sec = _f(config.get("seek_cooldown_sec"), 2.20)
        self.gain_following = _f(config.get("gain_following"), 0.52)
        self.gain_transition = _f(config.get("gain_transition"), 0.72)
        self.gain_soft_duck = _f(config.get("gain_soft_duck"), 0.36)
        self.startup_grace_sec = _f(config.get("startup_grace_sec"), 3.2)
        self.low_confidence_hold_sec = _f(config.get("low_confidence_hold_sec"), 2.2)
        self.guide_play_sec = _f(config.get("guide_play_sec"), 3.20)
        self.no_progress_hold_min_play_sec = _f(config.get("no_progress_hold_min_play_sec"), 5.80)
        self.progress_stale_sec = _f(config.get("progress_stale_sec"), 1.45)
        self.hold_trend_sec = _f(config.get("hold_trend_sec"), 1.00)
        self.tracking_quality_hold_min = _f(config.get("tracking_quality_hold_min"), 0.60)
        self.tracking_quality_seek_min = _f(config.get("tracking_quality_seek_min"), 0.84)
        self.resume_from_hold_speaking_lead_slack_sec = _f(
            config.get("resume_from_hold_speaking_lead_slack_sec"),
            0.72,
        )
        self.disable_seek = _b(config.get("disable_seek"), False)
        self._started_at_sec = 0.0
        self._last_seek_at_sec = -999999.0
        self._hold_started_at_sec = 0.0
        self._is_holding = False
    def reset(self, *, started_at_sec: float) -> None:
        self._started_at_sec = float(started_at_sec)
        self._last_seek_at_sec = -999999.0
        self._hold_started_at_sec = 0.0
        self._is_holding = False
    def decide(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        progress_estimate,
        latency_state=None,
    ) -> ControlDecision:
        if progress_estimate is None:
            return ControlDecision(
                action="guide",
                reason="no_progress_estimate",
                target_gain=self.gain_transition,
            )
        est_ref_time_sec = _f(getattr(progress_estimate, "estimated_ref_time_sec", 0.0), 0.0)
        progress_age_sec = _f(getattr(progress_estimate, "progress_age_sec", 9999.0), 9999.0)
        joint_confidence = _f(getattr(progress_estimate, "joint_confidence", 0.0), 0.0)
        tracking_quality = _f(getattr(progress_estimate, "tracking_quality", 0.0), 0.0)
        active_speaking = bool(getattr(progress_estimate, "active_speaking", False))
        recently_progressed = bool(getattr(progress_estimate, "recently_progressed", False))
        user_state = str(getattr(progress_estimate, "user_state", "UNKNOWN"))
        position_source = str(getattr(progress_estimate, "position_source", "text"))
        target_lead_sec = self.target_lead_sec
        if latency_state is not None:
            target_lead_sec = _f(
                getattr(latency_state, "baseline_target_lead_sec", self.target_lead_sec),
                self.target_lead_sec,
            )
        lead_sec = _f(playback_ref_time_sec, 0.0) - est_ref_time_sec - target_lead_sec
        session_age_sec = max(0.0, float(now_sec) - self._started_at_sec)
        if session_age_sec <= self.startup_grace_sec:
            return ControlDecision(
                action="guide",
                reason="startup_grace",
                target_gain=self.gain_transition,
            )
        if joint_confidence < self.min_confidence:
            if progress_age_sec >= self.low_confidence_hold_sec:
                self._enter_hold(now_sec)
                return ControlDecision(
                    action="hold",
                    reason="low_confidence",
                    target_gain=0.0,
                )
            return ControlDecision(
                action="duck",
                reason="confidence_recovering",
                target_gain=self.gain_soft_duck,
            )
        if progress_age_sec >= self.progress_stale_sec:
            if active_speaking:
                self._enter_hold(now_sec)
                return ControlDecision(
                    action="hold",
                    reason="speaking_but_no_progress",
                    target_gain=0.0,
                )
            return ControlDecision(
                action="duck",
                reason="no_recent_progress",
                target_gain=self.gain_soft_duck,
            )
        if tracking_quality < self.tracking_quality_hold_min and active_speaking:
            self._enter_hold(now_sec)
            return ControlDecision(
                action="hold",
                reason="weak_tracking_while_speaking",
                target_gain=0.0,
            )
        if lead_sec >= self.hold_if_lead_sec and active_speaking:
            self._enter_hold(now_sec)
            return ControlDecision(
                action="hold",
                reason="lead_too_large",
                target_gain=0.0,
            )
        if (
            not self.disable_seek
            and lead_sec <= self.seek_if_lag_sec
            and tracking_quality >= self.tracking_quality_seek_min
            and joint_confidence >= self.min_confidence
            and (now_sec - self._last_seek_at_sec) >= self.seek_cooldown_sec
        ):
            self._last_seek_at_sec = float(now_sec)
            self._leave_hold()
            return ControlDecision(
                action="seek",
                reason="lag_too_large",
                target_gain=self.gain_transition,
                seek_to_ref_time_sec=max(0.0, est_ref_time_sec + target_lead_sec),
            )
        if self._is_holding:
            if (
                lead_sec <= self.resume_if_lead_sec + (self.resume_from_hold_speaking_lead_slack_sec if active_speaking else 0.0)
                and recently_progressed
                and tracking_quality >= self.tracking_quality_hold_min
            ):
                self._leave_hold()
                return ControlDecision(
                    action="resume",
                    reason="hold_released",
                    target_gain=self.gain_transition,
                )
            return ControlDecision(
                action="hold",
                reason="holding",
                target_gain=0.0,
            )
        if user_state in {"REJOINING", "HESITATING"}:
            return ControlDecision(
                action="duck",
                reason=f"user_state_{user_state.lower()}",
                target_gain=self.gain_soft_duck,
            )
        if user_state in {"FOLLOWING", "SKIPPING"} or position_source in {"joint", "audio"}:
            return ControlDecision(
                action="follow",
                reason="tracking_ok",
                target_gain=self.gain_following,
            )
        return ControlDecision(
            action="guide",
            reason="fallback",
            target_gain=self.gain_transition,
        )
    def _enter_hold(self, now_sec: float) -> None:
        if not self._is_holding:
            self._is_holding = True
            self._hold_started_at_sec = float(now_sec)
    def _leave_hold(self) -> None:
        self._is_holding = False
        self._hold_started_at_sec = 0.0
```

---
### 文件: `shadowing_app/src/shadowing/realtime/controller_legacy_adapter.py`

```python
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from typing import Any
from shadowing.realtime.controller import ControlDecision, PlaybackController
def _to_plain_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    out: dict[str, Any] = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        out[name] = value
    return out
class LegacyControllerAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.controller = PlaybackController(config=config)
    def reset(self, *, started_at_sec: float) -> None:
        self.controller.reset(started_at_sec=started_at_sec)
    def decide(
        self,
        *,
        now_sec: float,
        playback_ref_time_sec: float,
        progress_estimate,
        latency_state=None,
    ) -> dict[str, Any]:
        decision: ControlDecision = self.controller.decide(
            now_sec=now_sec,
            playback_ref_time_sec=playback_ref_time_sec,
            progress_estimate=progress_estimate,
            latency_state=latency_state,
        )
        payload = _to_plain_dict(decision)
        payload.setdefault("action", decision.action)
        payload.setdefault("reason", decision.reason)
        payload.setdefault("target_gain", decision.target_gain)
        payload.setdefault("seek_to_ref_time_sec", decision.seek_to_ref_time_sec)
        return payload
```

---
### 文件: `shadowing_app/src/shadowing/realtime/orchestrator.py`

```python
from __future__ import annotations
import json
import queue
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from shadowing.adaptation.profile_store import ProfileStore
from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner
from shadowing.audio.device_profile import DeviceProfile, build_device_profile
from shadowing.audio.frame_feature_extractor import FrameFeatureExtractor
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.audio_aware_progress_estimator import AudioAwareProgressEstimator
from shadowing.realtime.asr.normalizer import TextNormalizer
from shadowing.realtime.sync_evidence import SyncEvidenceBuilder
from shadowing.telemetry.event_logger import EventLogger
from shadowing.telemetry.metrics import MetricsAggregator
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.types import AsrEventType, PlaybackState, PlayerCommand, PlayerCommandType, ReferenceMap
@dataclass(slots=True)
class OrchestratorStats:
    audio_enqueued: int = 0
    audio_dropped: int = 0
    audio_q_high_watermark: int = 0
    raw_asr_events: int = 0
    normalized_asr_events: int = 0
    ticks: int = 0
    asr_frames_fed: int = 0
    asr_frames_skipped: int = 0
    asr_gate_open_count: int = 0
    asr_gate_close_count: int = 0
    asr_resets_from_silence: int = 0
class ShadowingOrchestrator:
    def __init__(
        self,
        *,
        repo,
        player,
        recorder,
        asr,
        aligner,
        controller,
        device_context: dict[str, Any] | None = None,
        signal_monitor: SignalQualityMonitor | None = None,
        latency_calibrator: LatencyCalibrator | None = None,
        auto_tuner: RuntimeAutoTuner | None = None,
        profile_store: ProfileStore | None = None,
        event_logger: EventLogger | None = None,
        reference_audio_store: ReferenceAudioStore | None = None,
        live_audio_matcher=None,
        audio_behavior_classifier=None,
        evidence_fuser=None,
        audio_queue_maxsize: int = 150,
        asr_event_queue_maxsize: int = 64,
        loop_interval_sec: float = 0.03,
        debug: bool = False,
    ) -> None:
        self.repo = repo
        self.player = player
        self.recorder = recorder
        self.asr = asr
        self.aligner = aligner
        self.controller = controller
        self.device_context = dict(device_context or {})
        self.signal_monitor = signal_monitor or SignalQualityMonitor()
        self.latency_calibrator = latency_calibrator or LatencyCalibrator()
        self.auto_tuner = auto_tuner or RuntimeAutoTuner()
        self.profile_store = profile_store
        self.event_logger = event_logger
        self.reference_audio_store = reference_audio_store
        self.live_audio_matcher = live_audio_matcher
        self.audio_behavior_classifier = audio_behavior_classifier
        self.evidence_fuser = evidence_fuser
        self.audio_queue: queue.Queue[tuple[float, bytes]] = queue.Queue(
            maxsize=max(16, int(audio_queue_maxsize))
        )
        self.loop_interval_sec = float(loop_interval_sec)
        self.debug = bool(debug)
        self.normalizer = TextNormalizer()
        self.tracking_engine = TrackingEngine(self.aligner, debug=debug)
        self.progress_estimator = AudioAwareProgressEstimator()
        self.metrics = MetricsAggregator()
        self.stats = OrchestratorStats()
        self.sync_builder = SyncEvidenceBuilder()
        self._lesson_id: str | None = None
        self._ref_map: ReferenceMap | None = None
        self._running = False
        self._last_generation = -1
        self._last_tracking_mode = None
        self._last_gain_sent: float | None = None
        self._last_control_action_key: tuple[str, str] | None = None
        self._device_profile: DeviceProfile | None = None
        self._warm_start: dict[str, Any] = {}
        self._session_started_at_sec = 0.0
        self._asr_gate_open = False
        self._asr_gate_last_open_at_sec = 0.0
        self._asr_gate_last_close_at_sec = 0.0
        self._last_human_voice_like_at_sec = 0.0
        self._last_asr_reset_at_sec = 0.0
        self._speech_open_rms = 0.0085
        self._speech_keep_rms = 0.0052
        self._speech_open_peak = 0.022
        self._speech_keep_peak = 0.014
        self._speech_open_likelihood = 0.50
        self._speech_keep_likelihood = 0.34
        self._speech_tail_hold_sec = 0.70
        self._asr_reset_after_silence_sec = 2.80
        self._asr_reset_cooldown_sec = 1.80
        self._reference_audio_features = None
        self._latest_audio_match = None
        self._latest_audio_behavior = None
        self._latest_fusion_evidence = None
        self._last_audio_recentering_at_sec = 0.0
        self._bluetooth_long_session_mode = False
        self._stable_lead_samples: list[float] = []
        self._last_stable_lead_rebaseline_at_sec = 0.0
        target_sr = 16000
        try:
            target_sr = int(getattr(self.asr, "sample_rate", 16000))
        except Exception:
            pass
        self._audio_feature_extractor = FrameFeatureExtractor(sample_rate=target_sr)
        _ = asr_event_queue_maxsize
    def configure_runtime(self, runtime_cfg: dict[str, Any]) -> None:
        if "loop_interval_sec" in runtime_cfg:
            self.loop_interval_sec = float(runtime_cfg["loop_interval_sec"])
    def configure_debug(self, debug_cfg: dict[str, Any]) -> None:
        self.debug = bool(debug_cfg.get("enabled", self.debug))
        self.tracking_engine.debug = self.debug
    def start_session(self, lesson_id: str) -> None:
        self._lesson_id = lesson_id
        self._ref_map = self.repo.load_reference_map(lesson_id)
        self.metrics = MetricsAggregator()
        self.stats = OrchestratorStats()
        self._warm_start = {}
        self.tracking_engine.reset(self._ref_map)
        self.progress_estimator.reset(self._ref_map, start_idx=0)
        self.controller.reset()
        self._audio_feature_extractor.reset()
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        chunks = self.repo.load_audio_chunks(lesson_id)
        self.player.load_chunks(chunks)
        self._session_started_at_sec = time.monotonic()
        self.sync_builder.reset(self._session_started_at_sec)
        self.metrics.mark_session_started(self._session_started_at_sec)
        self._last_generation = -1
        self._last_tracking_mode = None
        self._last_gain_sent = None
        self._last_control_action_key = None
        self._asr_gate_open = False
        self._asr_gate_last_open_at_sec = 0.0
        self._asr_gate_last_close_at_sec = self._session_started_at_sec
        self._last_human_voice_like_at_sec = 0.0
        self._last_asr_reset_at_sec = 0.0
        self._latest_audio_match = None
        self._latest_audio_behavior = None
        self._latest_fusion_evidence = None
        self._last_audio_recentering_at_sec = 0.0
        self._stable_lead_samples = []
        self._last_stable_lead_rebaseline_at_sec = self._session_started_at_sec
        output_sr = chunks[0].sample_rate if chunks else int(self.device_context.get("output_sample_rate", 44100))
        self._device_profile = self._build_initial_device_profile(output_sr)
        bluetooth_mode = bool(self._device_profile.bluetooth_mode) if self._device_profile is not None else False
        total_duration_sec = float(getattr(self._ref_map, "total_duration_sec", 0.0))
        manual_long_session_flag = bool(self.device_context.get("bluetooth_long_session_mode", False))
        self._bluetooth_long_session_mode = bool(
            bluetooth_mode and (manual_long_session_flag or total_duration_sec >= 1800.0)
        )
        if bluetooth_mode:
            self._speech_open_rms = 0.0072
            self._speech_keep_rms = 0.0045
            self._speech_open_peak = 0.018
            self._speech_keep_peak = 0.011
            self._speech_open_likelihood = 0.42
            self._speech_keep_likelihood = 0.28
            self._speech_tail_hold_sec = 1.20
            self._asr_reset_after_silence_sec = 4.20
            self._asr_reset_cooldown_sec = 2.60
        else:
            self._speech_open_rms = 0.0085
            self._speech_keep_rms = 0.0052
            self._speech_open_peak = 0.022
            self._speech_keep_peak = 0.014
            self._speech_open_likelihood = 0.50
            self._speech_keep_likelihood = 0.34
            self._speech_tail_hold_sec = 0.70
            self._asr_reset_after_silence_sec = 2.80
            self._asr_reset_cooldown_sec = 1.80
        self.latency_calibrator.reset(
            self._device_profile,
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=self._bluetooth_long_session_mode,
            now_sec=self._session_started_at_sec,
        )
        self.auto_tuner.reset(
            self._device_profile.reliability_tier,
            bluetooth_mode=bluetooth_mode,
        )
        if self.profile_store is not None and self._device_profile is not None:
            self._warm_start = self.profile_store.load_warm_start(
                input_device_id=self._device_profile.input_device_id,
                output_device_id=self._device_profile.output_device_id,
                hostapi_name=self._device_profile.hostapi_name,
                capture_backend=self._device_profile.capture_backend,
                duplex_sample_rate=int(self._device_profile.input_sample_rate),
                reliability_tier=self._device_profile.reliability_tier,
                bluetooth_mode=bluetooth_mode,
            )
            self.auto_tuner.apply_warm_start(
                controller_policy=self.controller.policy,
                player=self.player,
                signal_monitor=self.signal_monitor,
                warm_start=self._warm_start,
            )
            self._apply_latency_warm_start(self._warm_start)
        if self.reference_audio_store is not None and self.live_audio_matcher is not None:
            try:
                self._reference_audio_features = self.reference_audio_store.load(lesson_id)
            except Exception:
                self._reference_audio_features = None
            if self._reference_audio_features is not None:
                self.live_audio_matcher.reset(self._reference_audio_features, self._ref_map)
        if self.audio_behavior_classifier is not None:
            self.audio_behavior_classifier.reset()
        if self.evidence_fuser is not None:
            self.evidence_fuser.reset()
        try:
            self.asr.start()
            self.recorder.start(self._on_audio_frame)
            self.player.start()
        except Exception:
            self._safe_close_startup_resources()
            raise
        self._running = True
    def stop_session(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self.recorder.stop()
        except Exception:
            pass
        try:
            self.asr.close()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        self._persist_session_profile()
        self._persist_summary()
        try:
            self.player.close()
        except Exception:
            pass
        try:
            self.recorder.close()
        except Exception:
            pass
    def tick(self) -> None:
        if not self._running:
            return
        self.stats.ticks += 1
        self._drain_audio_queue()
        now_sec = time.monotonic()
        signal_snapshot = self.signal_monitor.snapshot(now_sec)
        if signal_snapshot.vad_active or signal_snapshot.speaking_likelihood >= 0.46:
            self.metrics.observe_signal_active(now_sec)
        playback_status = self.player.get_status()
        if playback_status.generation != self._last_generation:
            self._last_generation = playback_status.generation
            self.tracking_engine.on_playback_generation_changed(playback_status.generation)
            self.progress_estimator.on_playback_generation_changed(now_sec)
        raw_events = self.asr.poll_raw_events()
        self.stats.raw_asr_events += len(raw_events)
        last_tracking = None
        for raw_event in raw_events:
            if raw_event.event_type == AsrEventType.PARTIAL:
                self.metrics.observe_asr_partial(raw_event.emitted_at_sec)
            event = self.normalizer.normalize_raw_event(raw_event)
            if event is None:
                continue
            self.stats.normalized_asr_events += 1
            tracking = self.tracking_engine.update(event)
            last_tracking = tracking
            if tracking is None:
                continue
            if self._last_tracking_mode != tracking.tracking_mode:
                self.metrics.observe_tracking_mode(tracking.tracking_mode.value)
                self._last_tracking_mode = tracking.tracking_mode
            if self.event_logger is not None:
                self.event_logger.log(
                    "tracking_snapshot",
                    {
                        "candidate_ref_idx": tracking.candidate_ref_idx,
                        "committed_ref_idx": tracking.committed_ref_idx,
                        "candidate_ref_time_sec": tracking.candidate_ref_time_sec,
                        "tracking_mode": tracking.tracking_mode.value,
                        "overall_score": tracking.tracking_quality.overall_score,
                        "observation_score": tracking.tracking_quality.observation_score,
                        "temporal_consistency_score": tracking.tracking_quality.temporal_consistency_score,
                        "anchor_score": tracking.tracking_quality.anchor_score,
                        "is_reliable": tracking.tracking_quality.is_reliable,
                        "confidence": tracking.confidence,
                        "stable": tracking.stable,
                        "local_match_ratio": tracking.local_match_ratio,
                        "repeat_penalty": tracking.repeat_penalty,
                        "monotonic_consistency": tracking.monotonic_consistency,
                        "anchor_consistency": tracking.anchor_consistency,
                        "matched_text": tracking.matched_text,
                        "emitted_at_sec": tracking.emitted_at_sec,
                    },
                    ts_monotonic_sec=tracking.emitted_at_sec,
                    session_tick=self.stats.ticks,
                )
        audio_match = None
        if self.live_audio_matcher is not None:
            progress_hint = (
                None
                if self.progress_estimator._last_snapshot is None
                else float(self.progress_estimator._last_snapshot.estimated_ref_time_sec)
            )
            text_conf = (
                0.0
                if self.progress_estimator._last_snapshot is None
                else float(self.progress_estimator._last_snapshot.tracking_quality)
            )
            audio_match = self.live_audio_matcher.snapshot(
                now_sec=now_sec,
                progress_hint_ref_time_sec=progress_hint,
                playback_ref_time_sec=float(playback_status.t_ref_heard_content_sec),
                text_tracking_confidence=text_conf,
            )
            self._latest_audio_match = audio_match
        audio_behavior = None
        if self.audio_behavior_classifier is not None:
            audio_behavior = self.audio_behavior_classifier.update(
                audio_match=audio_match,
                signal_quality=signal_snapshot,
                progress=self.progress_estimator._last_snapshot,
                playback_status=playback_status,
            )
            self._latest_audio_behavior = audio_behavior
        progress = self.progress_estimator.update(
            tracking=last_tracking,
            audio_match=audio_match,
            audio_behavior=audio_behavior,
            signal_quality=signal_snapshot,
            now_sec=now_sec,
        )
        if progress is None:
            progress = self.progress_estimator.snapshot(
                now_sec=now_sec,
                signal_quality=signal_snapshot,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
            )
        if progress is not None:
            is_reliable = bool(
                progress.joint_confidence >= self.controller.policy.min_confidence
                and progress.tracking_quality >= self.controller.policy.tracking_quality_hold_min
            )
            self.metrics.observe_progress(
                now_sec=now_sec,
                tracking_quality=progress.tracking_quality,
                is_reliable=is_reliable,
            )
        fusion_evidence = None
        if self.evidence_fuser is not None:
            fusion_evidence = self.evidence_fuser.fuse(
                now_sec=now_sec,
                tracking=last_tracking,
                progress=progress,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
                signal_quality=signal_snapshot,
                playback_status=playback_status,
            )
            self._latest_fusion_evidence = fusion_evidence
        self._maybe_recenter_from_audio(now_sec=now_sec, fusion_evidence=fusion_evidence)
        sync_evidence = self.sync_builder.build(
            now_sec=now_sec,
            signal_quality=signal_snapshot,
            progress=progress,
            fusion_evidence=fusion_evidence,
            bluetooth_mode=self._is_bluetooth_mode(),
            bluetooth_long_session_mode=self._is_bluetooth_long_session_mode(),
        )
        if progress is not None:
            source_mode = str(getattr(progress, "position_source", "text"))
            source_is_text_dominant = source_mode == "text"
            audio_text_disagreement_sec = None
            if audio_match is not None:
                audio_text_disagreement_sec = float(
                    audio_match.estimated_ref_time_sec - progress.estimated_ref_time_sec
                )
            self.latency_calibrator.observe_sync(
                playback_ref_time_sec=playback_status.t_ref_heard_content_sec,
                user_ref_time_sec=progress.estimated_ref_time_sec,
                tracking_quality=progress.tracking_quality,
                stable=progress.stable,
                active_speaking=progress.active_speaking,
                allow_observation=sync_evidence.allow_latency_observation,
                source_is_text_dominant=source_is_text_dominant,
                source_mode=source_mode,
                audio_text_disagreement_sec=audio_text_disagreement_sec,
            )
        self._collect_stable_lead_samples(
            now_sec=now_sec,
            playback_status=playback_status,
            progress=progress,
            sync_evidence=sync_evidence,
        )
        self._maybe_rebaseline_output_offset(now_sec=now_sec)
        playback_status = self.player.get_status()
        decision = self.controller.decide(
            playback=playback_status,
            progress=progress,
            signal_quality=signal_snapshot,
            sync_evidence=sync_evidence,
            fusion_evidence=fusion_evidence,
        )
        self._apply_decision(decision, playback_status)
        self._run_auto_tuning(
            now_sec=now_sec,
            progress=progress,
            signal_snapshot=signal_snapshot,
        )
        self._log_event(
            progress=progress,
            signal_snapshot=signal_snapshot,
            decision=decision,
            sync_evidence=sync_evidence,
            audio_match=audio_match,
            audio_behavior=audio_behavior,
            fusion_evidence=fusion_evidence,
        )
    def _apply_latency_warm_start(self, warm_start: dict[str, Any]) -> None:
        latency = dict(warm_start.get("latency", {}))
        if not latency:
            return
        snap = self.latency_calibrator.snapshot()
        if snap is None:
            return
        stable_target_lead_sec = latency.get("stable_target_lead_sec")
        startup_target_lead_sec = latency.get("startup_target_lead_sec")
        if stable_target_lead_sec is not None:
            try:
                snap.baseline_target_lead_sec = float(stable_target_lead_sec)
            except Exception:
                pass
        if "estimated_output_latency_ms" in latency:
            try:
                snap.estimated_output_latency_ms = float(latency["estimated_output_latency_ms"])
            except Exception:
                pass
        if "estimated_input_latency_ms" in latency:
            try:
                snap.estimated_input_latency_ms = float(latency["estimated_input_latency_ms"])
            except Exception:
                pass
        if startup_target_lead_sec is not None and self._is_bluetooth_mode():
            try:
                self.latency_calibrator.target_shadow_lead_sec = float(startup_target_lead_sec)
            except Exception:
                pass
    def _collect_stable_lead_samples(self, *, now_sec: float, playback_status, progress, sync_evidence) -> None:
        if progress is None:
            return
        if not sync_evidence.allow_latency_observation:
            return
        if not progress.active_speaking:
            return
        if progress.tracking_quality < (0.70 if self._is_bluetooth_mode() else 0.76):
            return
        lead_sec = float(playback_status.t_ref_heard_content_sec) - float(progress.estimated_ref_time_sec)
        if abs(lead_sec) > 2.2:
            return
        self._stable_lead_samples.append(float(lead_sec))
        if len(self._stable_lead_samples) > 240:
            self._stable_lead_samples = self._stable_lead_samples[-240:]
    def _maybe_rebaseline_output_offset(self, *, now_sec: float) -> None:
        if self._is_bluetooth_long_session_mode():
            refresh_gap = 180.0
            need_n = 24
            desired = 0.35
        elif self._is_bluetooth_mode():
            refresh_gap = 120.0
            need_n = 20
            desired = 0.28
        else:
            refresh_gap = 240.0
            need_n = 28
            desired = 0.15
        if (now_sec - self._last_stable_lead_rebaseline_at_sec) < refresh_gap:
            return
        if len(self._stable_lead_samples) < need_n:
            return
        vals = sorted(self._stable_lead_samples)
        mid = vals[len(vals) // 2]
        error_sec = float(mid - desired)
        if abs(error_sec) < 0.040:
            self._last_stable_lead_rebaseline_at_sec = now_sec
            self._stable_lead_samples.clear()
            return
        snap = self.latency_calibrator.snapshot()
        if snap is None:
            return
        new_output_offset_sec = max(
            0.0,
            (
                snap.estimated_output_latency_ms
                + snap.runtime_output_drift_ms
                - error_sec * 1000.0
            )
            / 1000.0,
        )
        if hasattr(self.player, "set_output_offset_sec"):
            self.player.set_output_offset_sec(new_output_offset_sec)
        self._last_stable_lead_rebaseline_at_sec = now_sec
        self._stable_lead_samples.clear()
    def _maybe_recenter_from_audio(self, *, now_sec: float, fusion_evidence) -> None:
        if fusion_evidence is None:
            return
        if (now_sec - self._last_audio_recentering_at_sec) < 0.45:
            return
        if not (
            fusion_evidence.should_recenter_aligner_window
            or fusion_evidence.should_widen_reacquire_window
        ):
            return
        ref_idx_hint = int(getattr(fusion_evidence, "estimated_ref_idx_hint", 0))
        if fusion_evidence.should_widen_reacquire_window:
            back, ahead, budget = 18, 40, 8
        else:
            back, ahead, budget = 10, 24, 6
        self.tracking_engine.recenter_from_audio(
            ref_idx_hint=ref_idx_hint,
            search_back=back,
            search_ahead=ahead,
            budget_events=budget,
        )
        self._last_audio_recentering_at_sec = float(now_sec)
        if self.event_logger is not None:
            self.event_logger.log(
                "audio_recentering",
                {
                    "estimated_ref_idx_hint": ref_idx_hint,
                    "estimated_ref_time_sec": float(
                        getattr(fusion_evidence, "estimated_ref_time_sec", 0.0)
                    ),
                    "audio_confidence": float(getattr(fusion_evidence, "audio_confidence", 0.0)),
                    "fused_confidence": float(getattr(fusion_evidence, "fused_confidence", 0.0)),
                    "should_recenter_aligner_window": bool(
                        getattr(fusion_evidence, "should_recenter_aligner_window", False)
                    ),
                    "should_widen_reacquire_window": bool(
                        getattr(fusion_evidence, "should_widen_reacquire_window", False)
                    ),
                },
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
    def _on_audio_frame(self, pcm_bytes: bytes) -> None:
        item = (time.monotonic(), pcm_bytes)
        try:
            self.audio_queue.put_nowait(item)
            self.stats.audio_enqueued += 1
            self.stats.audio_q_high_watermark = max(
                self.stats.audio_q_high_watermark,
                self.audio_queue.qsize(),
            )
        except queue.Full:
            try:
                _ = self.audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_queue.put_nowait(item)
            except queue.Full:
                pass
            self.stats.audio_dropped += 1
    def _drain_audio_queue(self) -> None:
        while True:
            try:
                observed_at_sec, pcm_bytes = self.audio_queue.get_nowait()
            except queue.Empty:
                break
            self.signal_monitor.feed_pcm16(pcm_bytes, observed_at_sec)
            signal_snapshot = self.signal_monitor.snapshot(observed_at_sec)
            self.latency_calibrator.observe_signal(signal_snapshot)
            if self.live_audio_matcher is not None:
                feat_frames = self._audio_feature_extractor.process_pcm16(
                    pcm_bytes,
                    observed_at_sec=observed_at_sec,
                )
                self.live_audio_matcher.feed_features(feat_frames)
            bootstrap_mode = (observed_at_sec - self._session_started_at_sec) <= 4.0
            bluetooth_mode = self._is_bluetooth_mode()
            should_feed_asr = self._should_feed_asr(
                signal_snapshot=signal_snapshot,
                now_sec=observed_at_sec,
                bootstrap_mode=bootstrap_mode,
                bluetooth_mode=bluetooth_mode,
            )
            if should_feed_asr:
                self.asr.feed_pcm16(pcm_bytes)
                self.stats.asr_frames_fed += 1
            else:
                self.stats.asr_frames_skipped += 1
                self._maybe_reset_asr_for_silence(
                    signal_snapshot=signal_snapshot,
                    now_sec=observed_at_sec,
                    bootstrap_mode=bootstrap_mode,
                    bluetooth_mode=bluetooth_mode,
                )
    def _should_feed_asr(
        self,
        *,
        signal_snapshot,
        now_sec: float,
        bootstrap_mode: bool,
        bluetooth_mode: bool,
    ) -> bool:
        open_rms = 0.0070 if bluetooth_mode else (0.0078 if bootstrap_mode else self._speech_open_rms)
        open_peak = 0.017 if bluetooth_mode else (0.020 if bootstrap_mode else self._speech_open_peak)
        open_likelihood = 0.40 if bluetooth_mode else (0.44 if bootstrap_mode else self._speech_open_likelihood)
        strong_voice = bool(
            signal_snapshot.vad_active
            and signal_snapshot.rms >= open_rms
            and signal_snapshot.peak >= open_peak
        )
        likely_voice = bool(
            signal_snapshot.speaking_likelihood >= open_likelihood
            and signal_snapshot.rms >= self._speech_keep_rms
        )
        keep_voice = bool(
            signal_snapshot.vad_active
            and signal_snapshot.rms >= self._speech_keep_rms
            and signal_snapshot.peak >= self._speech_keep_peak
        ) or bool(
            signal_snapshot.speaking_likelihood >= self._speech_keep_likelihood
            and signal_snapshot.peak >= self._speech_keep_peak
        )
        if strong_voice or likely_voice:
            self._last_human_voice_like_at_sec = float(now_sec)
        gate_should_open = strong_voice or likely_voice
        gate_tail_sec = 1.25 if bluetooth_mode else (0.95 if bootstrap_mode else self._speech_tail_hold_sec)
        gate_should_keep = False
        if self._asr_gate_open and self._last_human_voice_like_at_sec > 0.0:
            gate_should_keep = keep_voice or (
                (now_sec - self._last_human_voice_like_at_sec) <= gate_tail_sec
            )
        new_gate_state = gate_should_open or gate_should_keep
        if new_gate_state and not self._asr_gate_open:
            self._asr_gate_open = True
            self._asr_gate_last_open_at_sec = float(now_sec)
            self.stats.asr_gate_open_count += 1
        elif (not new_gate_state) and self._asr_gate_open:
            self._asr_gate_open = False
            self._asr_gate_last_close_at_sec = float(now_sec)
            self.stats.asr_gate_close_count += 1
        return self._asr_gate_open
    def _maybe_reset_asr_for_silence(
        self,
        *,
        signal_snapshot,
        now_sec: float,
        bootstrap_mode: bool,
        bluetooth_mode: bool,
    ) -> None:
        if self._asr_gate_open or bootstrap_mode or bluetooth_mode:
            return
        recently_had_voice = (
            self._last_human_voice_like_at_sec > 0.0
            and (now_sec - self._last_human_voice_like_at_sec) <= self._asr_reset_after_silence_sec
        )
        if recently_had_voice:
            return
        recently_reset = (
            self._last_asr_reset_at_sec > 0.0
            and (now_sec - self._last_asr_reset_at_sec) <= self._asr_reset_cooldown_sec
        )
        if recently_reset:
            return
        very_quiet = bool(
            signal_snapshot.rms <= self._speech_keep_rms
            and signal_snapshot.peak <= self._speech_keep_peak
            and signal_snapshot.speaking_likelihood <= 0.18
        )
        if not very_quiet:
            return
        try:
            self.asr.reset()
            self._last_asr_reset_at_sec = float(now_sec)
            self.stats.asr_resets_from_silence += 1
        except Exception:
            pass
    def _apply_decision(self, decision, playback_status) -> None:
        action_key = (decision.action.value, decision.reason)
        should_count = action_key != self._last_control_action_key
        self._last_control_action_key = action_key
        if decision.action.value == "hold":
            if playback_status.state != PlaybackState.HOLDING:
                self.player.submit_command(
                    PlayerCommand(cmd=PlayerCommandType.HOLD, reason=decision.reason)
                )
                if should_count:
                    self.metrics.observe_action("hold", decision.reason, time.monotonic())
        elif decision.action.value == "resume":
            if playback_status.state == PlaybackState.HOLDING:
                self.player.submit_command(
                    PlayerCommand(cmd=PlayerCommandType.RESUME, reason=decision.reason)
                )
                if should_count:
                    self.metrics.observe_action("resume", decision.reason, time.monotonic())
        elif decision.action.value == "seek" and decision.target_time_sec is not None:
            self.player.submit_command(
                PlayerCommand(
                    cmd=PlayerCommandType.SEEK,
                    target_time_sec=float(decision.target_time_sec),
                    reason=decision.reason,
                )
            )
            if should_count:
                self.metrics.observe_action("seek", decision.reason, time.monotonic())
        elif decision.action.value == "soft_duck" and should_count:
            self.metrics.observe_action("soft_duck", decision.reason, time.monotonic())
        desired_gain = decision.target_gain
        if desired_gain is not None:
            if self._last_gain_sent is None or abs(float(desired_gain) - float(self._last_gain_sent)) >= 0.01:
                self.player.submit_command(
                    PlayerCommand(
                        cmd=PlayerCommandType.SET_GAIN,
                        gain=float(desired_gain),
                        reason=decision.reason,
                    )
                )
                self._last_gain_sent = float(desired_gain)
    def _run_auto_tuning(self, *, now_sec: float, progress, signal_snapshot) -> None:
        metrics_summary = self.metrics.summary_dict()
        latency_snapshot = self.latency_calibrator.snapshot()
        self.auto_tuner.maybe_tune(
            now_sec=now_sec,
            controller_policy=self.controller.policy,
            player=self.player,
            signal_monitor=self.signal_monitor,
            metrics_summary=metrics_summary,
            signal_quality=signal_snapshot,
            progress=progress,
            latency_snapshot=latency_snapshot,
            device_profile=asdict(self._device_profile) if self._device_profile is not None else {},
        )
    def _persist_session_profile(self) -> None:
        if self.profile_store is None or self._device_profile is None:
            return
        latency_snapshot = self.latency_calibrator.snapshot()
        self.profile_store.update_from_session(
            input_device_id=self._device_profile.input_device_id,
            output_device_id=self._device_profile.output_device_id,
            hostapi_name=self._device_profile.hostapi_name,
            capture_backend=self._device_profile.capture_backend,
            duplex_sample_rate=int(self._device_profile.input_sample_rate),
            bluetooth_mode=bool(self._device_profile.bluetooth_mode),
            device_profile=asdict(self._device_profile),
            metrics=self.metrics.summary_dict(),
            latency_calibration=(
                None
                if latency_snapshot is None
                else {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "runtime_input_drift_ms": latency_snapshot.runtime_input_drift_ms,
                    "runtime_output_drift_ms": latency_snapshot.runtime_output_drift_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                    "stable_target_lead_sec": (
                        0.35 if self._bluetooth_long_session_mode
                        else (0.28 if self._is_bluetooth_mode() else 0.15)
                    ),
                    "startup_target_lead_sec": (
                        0.28 if self._is_bluetooth_mode() else 0.15
                    ),
                }
            ),
        )
    def _persist_summary(self) -> None:
        raw_session_dir = str(self.device_context.get("session_dir", "")).strip()
        if not raw_session_dir:
            return
        session_dir = Path(raw_session_dir).expanduser().resolve()
        session_dir.mkdir(parents=True, exist_ok=True)
        latency_snapshot = self.latency_calibrator.snapshot()
        summary = {
            "lesson_id": self._lesson_id,
            "metrics": self.metrics.summary_dict(),
            "stats": asdict(self.stats),
            "device_profile": None if self._device_profile is None else asdict(self._device_profile),
            "device_context": dict(self.device_context),
            "latency_calibration": (
                None
                if latency_snapshot is None
                else {
                    "estimated_input_latency_ms": latency_snapshot.estimated_input_latency_ms,
                    "estimated_output_latency_ms": latency_snapshot.estimated_output_latency_ms,
                    "runtime_input_drift_ms": latency_snapshot.runtime_input_drift_ms,
                    "runtime_output_drift_ms": latency_snapshot.runtime_output_drift_ms,
                    "confidence": latency_snapshot.confidence,
                    "calibrated": latency_snapshot.calibrated,
                    "baseline_target_lead_sec": latency_snapshot.baseline_target_lead_sec,
                }
            ),
            "controller_policy": asdict(self.controller.policy),
            "latest_audio_match": None if self._latest_audio_match is None else asdict(self._latest_audio_match),
            "latest_audio_behavior": None if self._latest_audio_behavior is None else asdict(self._latest_audio_behavior),
            "latest_fusion_evidence": None if self._latest_fusion_evidence is None else asdict(self._latest_fusion_evidence),
            "bluetooth_long_session_mode": self._bluetooth_long_session_mode,
            "stable_lead_samples_count": len(self._stable_lead_samples),
        }
        (session_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.event_logger is not None:
            self.event_logger.log(
                "session_summary",
                summary,
                ts_monotonic_sec=time.monotonic(),
                session_tick=self.stats.ticks,
            )
    def _log_event(
        self,
        *,
        progress,
        signal_snapshot,
        decision,
        sync_evidence,
        audio_match,
        audio_behavior,
        fusion_evidence,
    ) -> None:
        if self.event_logger is None:
            return
        now_sec = time.monotonic()
        self.event_logger.log(
            "signal_snapshot",
            {
                "rms": signal_snapshot.rms,
                "peak": signal_snapshot.peak,
                "vad_active": signal_snapshot.vad_active,
                "speaking_likelihood": signal_snapshot.speaking_likelihood,
                "quality_score": signal_snapshot.quality_score,
                "dropout_detected": signal_snapshot.dropout_detected,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )
        if progress is not None:
            self.event_logger.log(
                "progress_snapshot",
                {
                    "estimated_ref_idx": progress.estimated_ref_idx,
                    "estimated_ref_time_sec": progress.estimated_ref_time_sec,
                    "progress_age_sec": progress.progress_age_sec,
                    "tracking_mode": progress.tracking_mode.value,
                    "tracking_quality": progress.tracking_quality,
                    "confidence": progress.confidence,
                    "joint_confidence": progress.joint_confidence,
                    "audio_confidence": progress.audio_confidence,
                    "position_source": progress.position_source,
                    "active_speaking": progress.active_speaking,
                    "recently_progressed": progress.recently_progressed,
                    "user_state": progress.user_state.value,
                },
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        self.event_logger.log(
            "sync_evidence",
            {
                "speech_state": sync_evidence.speech_state.value,
                "tracking_state": sync_evidence.tracking_state.value,
                "sync_state": sync_evidence.sync_state.value,
                "speech_confidence": sync_evidence.speech_confidence,
                "tracking_confidence": sync_evidence.tracking_confidence,
                "sync_confidence": sync_evidence.sync_confidence,
                "allow_latency_observation": sync_evidence.allow_latency_observation,
                "allow_seek": sync_evidence.allow_seek,
                "startup_mode": sync_evidence.startup_mode,
                "bluetooth_mode": sync_evidence.bluetooth_mode,
                "bluetooth_long_session_mode": sync_evidence.bluetooth_long_session_mode,
                "audio_confidence": sync_evidence.audio_confidence,
                "still_following_likelihood": sync_evidence.still_following_likelihood,
                "reentry_likelihood": sync_evidence.reentry_likelihood,
                "repeated_likelihood": sync_evidence.repeated_likelihood,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )
        if audio_match is not None:
            self.event_logger.log(
                "audio_match_snapshot",
                asdict(audio_match),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        if audio_behavior is not None:
            self.event_logger.log(
                "audio_behavior_snapshot",
                asdict(audio_behavior),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        if fusion_evidence is not None:
            self.event_logger.log(
                "fusion_evidence",
                asdict(fusion_evidence),
                ts_monotonic_sec=now_sec,
                session_tick=self.stats.ticks,
            )
        self.event_logger.log(
            "control_decision",
            {
                "action": decision.action.value,
                "reason": decision.reason,
                "target_time_sec": decision.target_time_sec,
                "lead_sec": decision.lead_sec,
                "target_gain": decision.target_gain,
                "confidence": decision.confidence,
                "aggressiveness": decision.aggressiveness,
            },
            ts_monotonic_sec=now_sec,
            session_tick=self.stats.ticks,
        )
    def _build_initial_device_profile(self, output_sr: int) -> DeviceProfile:
        input_device_name = str(self.device_context.get("input_device_name", "unknown") or "unknown")
        output_device_name = str(self.device_context.get("output_device_name", "unknown") or "unknown")
        hostapi_name = str(self.device_context.get("hostapi_name", "") or "").strip()
        capture_backend = str(self.device_context.get("capture_backend", "") or "").strip().lower()
        input_device_id = str(self.device_context.get("input_device_id", "") or "").strip()
        output_device_id = str(self.device_context.get("output_device_id", "") or "").strip()
        input_sample_rate = self._safe_int(self.device_context.get("input_sample_rate", 16000), 16000)
        noise_floor_rms = self._safe_float(self.device_context.get("noise_floor_rms", 0.0025), 0.0025)
        return build_device_profile(
            input_device_name=input_device_name,
            output_device_name=output_device_name,
            input_sample_rate=input_sample_rate,
            output_sample_rate=int(output_sr),
            noise_floor_rms=noise_floor_rms,
            hostapi_name=hostapi_name,
            capture_backend=capture_backend,
            input_device_id=input_device_id or None,
            output_device_id=output_device_id or None,
        )
    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)
    def _safe_float(self, value: Any, default: float) -> float:
        try:
            out = float(value)
        except Exception:
            return float(default)
        if out != out:
            return float(default)
        return float(out)
    def _is_bluetooth_mode(self) -> bool:
        profile = self._device_profile
        if profile is None:
            return False
        return bool(profile.bluetooth_mode)
    def _is_bluetooth_long_session_mode(self) -> bool:
        return bool(self._bluetooth_long_session_mode)
    def _safe_close_startup_resources(self) -> None:
        try:
            self.recorder.stop()
        except Exception:
            pass
        try:
            self.recorder.close()
        except Exception:
            pass
        try:
            self.asr.close()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.player.close()
        except Exception:
            pass
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/chunk_queue.py`

```python
from __future__ import annotations
from bisect import bisect_right
import numpy as np
from shadowing.types import AudioChunk
class ChunkQueue:
    def __init__(self) -> None:
        self._chunks: list[AudioChunk] = []
        self._chunk_start_times: list[float] = []
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0
        self._sample_rate = 0
        self._total_duration_sec = 0.0
    def load(self, chunks: list[AudioChunk]) -> None:
        self._chunks = chunks
        self._chunk_start_times = [c.start_time_sec for c in chunks]
        self._current_chunk_idx = 0
        self._frame_offset_in_chunk = 0
        self._sample_rate = chunks[0].sample_rate if chunks else 0
        if chunks and any(c.sample_rate != self._sample_rate for c in chunks):
            raise ValueError("All playback chunks must share the same sample rate.")
        if chunks:
            last = chunks[-1]
            self._total_duration_sec = last.start_time_sec + last.duration_sec
        else:
            self._total_duration_sec = 0.0
    @property
    def current_chunk_id(self) -> int:
        if not self._chunks:
            return -1
        if self._current_chunk_idx >= len(self._chunks):
            return self._chunks[-1].chunk_id
        return self._chunks[self._current_chunk_idx].chunk_id
    @property
    def current_frame_index(self) -> int:
        return self._frame_offset_in_chunk
    def is_finished(self) -> bool:
        return bool(self._chunks) and self._current_chunk_idx >= len(self._chunks)
    def seek(self, target_time_sec: float) -> None:
        if not self._chunks:
            return
        idx = bisect_right(self._chunk_start_times, target_time_sec) - 1
        idx = max(0, min(idx, len(self._chunks) - 1))
        chunk = self._chunks[idx]
        local_time = max(0.0, target_time_sec - chunk.start_time_sec)
        local_frame = int(local_time * chunk.sample_rate)
        local_frame = min(local_frame, chunk.samples.shape[0])
        self._current_chunk_idx = idx
        self._frame_offset_in_chunk = local_frame
    def get_content_time_sec(self) -> float:
        if not self._chunks:
            return 0.0
        if self._current_chunk_idx >= len(self._chunks):
            return self._total_duration_sec
        chunk = self._chunks[self._current_chunk_idx]
        return chunk.start_time_sec + (self._frame_offset_in_chunk / chunk.sample_rate)
    def read_frames(self, frames: int, channels: int = 1) -> np.ndarray:
        out = np.zeros((frames, channels), dtype=np.float32)
        if not self._chunks or self.is_finished():
            return out
        written = 0
        while written < frames and self._current_chunk_idx < len(self._chunks):
            chunk = self._chunks[self._current_chunk_idx]
            remain = chunk.samples.shape[0] - self._frame_offset_in_chunk
            take = min(remain, frames - written)
            if take > 0:
                data = chunk.samples[self._frame_offset_in_chunk : self._frame_offset_in_chunk + take]
                if data.ndim == 1:
                    out[written : written + take, 0] = data
                else:
                    out[written : written + take, : data.shape[1]] = data
                self._frame_offset_in_chunk += take
                written += take
            if self._frame_offset_in_chunk >= chunk.samples.shape[0]:
                self._current_chunk_idx += 1
                self._frame_offset_in_chunk = 0
        return out
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/command_queue.py`

```python
from __future__ import annotations
import queue
from dataclasses import dataclass
from shadowing.types import PlayerCommand, PlayerCommandType
@dataclass(slots=True)
class MergedPlayerCommands:
    state_cmd: PlayerCommand | None = None
    seek_cmd: PlayerCommand | None = None
    gain_cmd: PlayerCommand | None = None
class PlayerCommandQueue:
    def __init__(self, maxsize: int = 64) -> None:
        self._queue: queue.Queue[PlayerCommand] = queue.Queue(maxsize=maxsize)
    def put(self, cmd: PlayerCommand) -> None:
        try:
            self._queue.put_nowait(cmd)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(cmd)
    def drain_merged(self) -> MergedPlayerCommands:
        merged = MergedPlayerCommands()
        while True:
            try:
                cmd = self._queue.get_nowait()
            except queue.Empty:
                break
            if cmd.cmd == PlayerCommandType.SET_GAIN:
                merged.gain_cmd = cmd
                continue
            if cmd.cmd == PlayerCommandType.SEEK:
                merged.seek_cmd = cmd
                continue
            if cmd.cmd == PlayerCommandType.STOP:
                merged.state_cmd = cmd
                continue
            if merged.state_cmd is None or merged.state_cmd.cmd != PlayerCommandType.STOP:
                merged.state_cmd = cmd
        return merged
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/playback_clock.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass(slots=True)
class PlaybackClockSnapshot:
    t_host_output_sec: float
    t_ref_block_start_content_sec: float
    t_ref_block_end_content_sec: float
    t_ref_emitted_content_sec: float
    t_ref_heard_content_sec: float
class PlaybackClock:
    def __init__(self, bluetooth_output_offset_sec: float = 0.0) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(bluetooth_output_offset_sec))
        self._last_emitted_content_sec = 0.0
        self._last_heard_content_sec = 0.0
        self._last_host_output_sec = 0.0
    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.bluetooth_output_offset_sec = max(0.0, float(offset_sec))
    def compute(
        self,
        output_buffer_dac_time_sec: float,
        block_start_content_sec: float,
        block_end_content_sec: float,
    ) -> PlaybackClockSnapshot:
        start_sec = float(block_start_content_sec)
        end_sec = float(block_end_content_sec)
        if end_sec < start_sec:
            end_sec = start_sec
        emitted_mid_sec = (start_sec + end_sec) * 0.5
        heard_mid_sec = emitted_mid_sec + self.bluetooth_output_offset_sec
        if output_buffer_dac_time_sec >= self._last_host_output_sec:
            emitted_mid_sec = max(emitted_mid_sec, self._last_emitted_content_sec)
            heard_mid_sec = max(heard_mid_sec, self._last_heard_content_sec)
        self._last_host_output_sec = float(output_buffer_dac_time_sec)
        self._last_emitted_content_sec = float(emitted_mid_sec)
        self._last_heard_content_sec = float(heard_mid_sec)
        return PlaybackClockSnapshot(
            t_host_output_sec=float(output_buffer_dac_time_sec),
            t_ref_block_start_content_sec=start_sec,
            t_ref_block_end_content_sec=end_sec,
            t_ref_emitted_content_sec=float(emitted_mid_sec),
            t_ref_heard_content_sec=float(heard_mid_sec),
        )
```

---
### 文件: `shadowing_app/src/shadowing/realtime/playback/sounddevice_player.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from math import gcd
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from shadowing.interfaces.player import Player
from shadowing.realtime.playback.chunk_queue import ChunkQueue
from shadowing.realtime.playback.command_queue import PlayerCommandQueue
from shadowing.realtime.playback.playback_clock import PlaybackClock
from shadowing.types import (
    AudioChunk,
    PlaybackState,
    PlaybackStatus,
    PlayerCommand,
    PlayerCommandType,
)
@dataclass(slots=True)
class PlaybackConfig:
    sample_rate: int
    channels: int
    device: int | str | None = None
    latency: str | float = "low"
    blocksize: int = 0
    bluetooth_output_offset_sec: float = 0.0
class _OutputResampler:
    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        g = gcd(self.src_rate, self.dst_rate)
        self.up = self.dst_rate // g
        self.down = self.src_rate // g
    def process(self, audio: np.ndarray) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2D audio array, got shape={arr.shape}")
        if self.src_rate == self.dst_rate or arr.shape[0] == 0:
            return arr.astype(np.float32, copy=False)
        channels = arr.shape[1]
        pieces: list[np.ndarray] = []
        for ch in range(channels):
            y = resample_poly(arr[:, ch], self.up, self.down).astype(
                np.float32,
                copy=False,
            )
            pieces.append(y)
        min_len = min(piece.shape[0] for piece in pieces)
        if min_len <= 0:
            return np.zeros((0, channels), dtype=np.float32)
        out = np.stack([piece[:min_len] for piece in pieces], axis=1)
        return out.astype(np.float32, copy=False)
class SoundDevicePlayer(Player):
    def __init__(self, config: PlaybackConfig) -> None:
        self.config = config
        self.clock = PlaybackClock(config.bluetooth_output_offset_sec)
        self.queue = ChunkQueue()
        self.command_queue = PlayerCommandQueue()
        self._stream: sd.OutputStream | None = None
        self._state = PlaybackState.STOPPED
        self._gain = 1.0
        self._generation = 0
        self._callback_count = 0
        self._content_sample_rate = int(config.sample_rate)
        self._opened_output_sample_rate = int(config.sample_rate)
        self._output_resampler: _OutputResampler | None = None
        self._resolved_output_device: int | None = None
        self._resolved_output_device_name = ""
        self._silent_branch_logged = False
        self._status_snapshot = PlaybackStatus(
            state=PlaybackState.STOPPED,
            chunk_id=-1,
            frame_index=0,
            gain=1.0,
            generation=0,
            t_host_output_sec=0.0,
            t_ref_block_start_content_sec=0.0,
            t_ref_block_end_content_sec=0.0,
            t_ref_emitted_content_sec=0.0,
            t_ref_heard_content_sec=0.0,
        )
    def set_output_offset_sec(self, offset_sec: float) -> None:
        self.clock.set_output_offset_sec(offset_sec)
    def load_chunks(self, chunks: list[AudioChunk]) -> None:
        if chunks and any(c.sample_rate != self.config.sample_rate for c in chunks):
            raise ValueError(
                "Chunk sample rate does not match player config sample rate."
            )
        self.queue.load(chunks)
        self._content_sample_rate = int(self.config.sample_rate)
    def start(self) -> None:
        if self._stream is not None:
            return
        actual_device = self._resolve_output_device(self.config.device)
        dev_info = sd.query_devices(actual_device, "output")
        opened_sr = self._pick_openable_output_samplerate(actual_device, dev_info)
        self._opened_output_sample_rate = int(opened_sr)
        self._output_resampler = (
            None
            if self._opened_output_sample_rate == self._content_sample_rate
            else _OutputResampler(
                src_rate=self._content_sample_rate,
                dst_rate=self._opened_output_sample_rate,
            )
        )
        self._resolved_output_device = int(actual_device)
        self._resolved_output_device_name = str(dev_info["name"])
        try:
            self._stream = sd.OutputStream(
                samplerate=self._opened_output_sample_rate,
                channels=self.config.channels,
                dtype="float32",
                callback=self._audio_callback,
                device=self._resolved_output_device,
                latency=self.config.latency,
                blocksize=self.config.blocksize,
            )
            self._state = PlaybackState.PLAYING
            self._silent_branch_logged = False
            self._stream.start()
        except Exception as e:
            self._state = PlaybackState.STOPPED
            raise RuntimeError(
                f"Failed to open output stream: device={self._resolved_output_device}, "
                f"sample_rate={self._opened_output_sample_rate}, channels={self.config.channels}, "
                f"latency={self.config.latency}, blocksize={self.config.blocksize}"
            ) from e
    def submit_command(self, command: PlayerCommand) -> None:
        self.command_queue.put(command)
    def get_status(self) -> PlaybackStatus:
        return self._status_snapshot
    def stop(self) -> None:
        self.submit_command(
            PlayerCommand(cmd=PlayerCommandType.STOP, reason="external_stop")
        )
    def close(self) -> None:
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self._state = PlaybackState.STOPPED
    def _apply_merged_commands(self) -> None:
        merged = self.command_queue.drain_merged()
        if merged.gain_cmd and merged.gain_cmd.gain is not None:
            self._gain = min(max(float(merged.gain_cmd.gain), 0.0), 1.0)
        hold_after_seek = False
        if merged.state_cmd is not None:
            if merged.state_cmd.cmd == PlayerCommandType.HOLD:
                hold_after_seek = True
            elif merged.state_cmd.cmd == PlayerCommandType.RESUME:
                self._state = PlaybackState.PLAYING
                self._silent_branch_logged = False
            elif merged.state_cmd.cmd == PlayerCommandType.STOP:
                self._state = PlaybackState.STOPPED
            elif merged.state_cmd.cmd == PlayerCommandType.START:
                self._state = PlaybackState.PLAYING
                self._silent_branch_logged = False
        if merged.seek_cmd is not None and merged.seek_cmd.target_time_sec is not None:
            self._state = PlaybackState.SEEKING
            self.queue.seek(float(merged.seek_cmd.target_time_sec))
            self._generation += 1
            self._state = PlaybackState.HOLDING if hold_after_seek else PlaybackState.PLAYING
            if self._state == PlaybackState.PLAYING:
                self._silent_branch_logged = False
        elif hold_after_seek:
            self._state = PlaybackState.HOLDING
    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        _ = status
        self._callback_count += 1
        self._apply_merged_commands()
        block_start = self.queue.get_content_time_sec()
        if self._state in (
            PlaybackState.STOPPED,
            PlaybackState.HOLDING,
            PlaybackState.FINISHED,
        ):
            outdata.fill(0.0)
            self._silent_branch_logged = True
        else:
            self._silent_branch_logged = False
            if self._output_resampler is None:
                block = self.queue.read_frames(
                    frames=frames,
                    channels=self.config.channels,
                )
            else:
                src_frames = self._estimate_source_frames(frames)
                source_block = self.queue.read_frames(
                    frames=src_frames,
                    channels=self.config.channels,
                )
                block = self._output_resampler.process(source_block)
                if block.shape[0] < frames:
                    padded = np.zeros((frames, self.config.channels), dtype=np.float32)
                    if block.shape[0] > 0:
                        padded[: block.shape[0], :] = block
                    block = padded
                elif block.shape[0] > frames:
                    block = block[:frames, :]
            outdata[:] = block * self._gain
            if self.queue.is_finished():
                self._state = PlaybackState.FINISHED
        block_end = self.queue.get_content_time_sec()
        snapshot = self.clock.compute(
            output_buffer_dac_time_sec=float(time_info.outputBufferDacTime),
            block_start_content_sec=block_start,
            block_end_content_sec=block_end,
        )
        self._status_snapshot = PlaybackStatus(
            state=self._state,
            chunk_id=self.queue.current_chunk_id,
            frame_index=self.queue.current_frame_index,
            gain=self._gain,
            generation=self._generation,
            t_host_output_sec=snapshot.t_host_output_sec,
            t_ref_block_start_content_sec=snapshot.t_ref_block_start_content_sec,
            t_ref_block_end_content_sec=snapshot.t_ref_block_end_content_sec,
            t_ref_emitted_content_sec=snapshot.t_ref_emitted_content_sec,
            t_ref_heard_content_sec=snapshot.t_ref_heard_content_sec,
        )
    def _resolve_output_device(self, requested_device: int | str | None) -> int:
        if isinstance(requested_device, int):
            dev_info = sd.query_devices(requested_device)
            if int(dev_info["max_output_channels"]) <= 0:
                raise ValueError(
                    f"Requested device is not an output device: "
                    f"device={requested_device}, name={dev_info['name']}"
                )
            return int(requested_device)
        if isinstance(requested_device, str):
            target = requested_device.strip().lower()
            if target:
                devices = sd.query_devices()
                for idx, dev in enumerate(devices):
                    if int(dev["max_output_channels"]) <= 0:
                        continue
                    if target in str(dev["name"]).lower():
                        return int(idx)
                candidates = [
                    f"[{idx}] {dev['name']}"
                    for idx, dev in enumerate(devices)
                    if int(dev["max_output_channels"]) > 0
                ]
                joined = "\n".join(candidates[:50])
                raise ValueError(
                    "Output device name not found: "
                    f"{requested_device!r}\nAvailable output devices:\n{joined}"
                )
        default_in, default_out = sd.default.device
        candidates: list[int] = []
        if default_out is not None and int(default_out) >= 0:
            candidates.append(int(default_out))
        if default_in is not None and int(default_in) >= 0 and int(default_in) not in candidates:
            candidates.append(int(default_in))
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev["max_output_channels"]) > 0 and idx not in candidates:
                candidates.append(idx)
        for idx in candidates:
            try:
                dev_info = sd.query_devices(idx)
                if int(dev_info["max_output_channels"]) > 0:
                    return int(idx)
            except Exception:
                continue
        raise RuntimeError("No valid output device available.")
    def _pick_openable_output_samplerate(self, device: int, dev_info) -> int:
        candidates: list[int] = []
        preferred = [
            self.config.sample_rate,
            int(float(dev_info["default_samplerate"])),
            48000,
            44100,
            16000,
        ]
        for sr in preferred:
            if sr > 0 and sr not in candidates:
                candidates.append(int(sr))
        last_error: Exception | None = None
        for sr in candidates:
            try:
                sd.check_output_settings(
                    device=device,
                    samplerate=sr,
                    channels=self.config.channels,
                    dtype="float32",
                )
                return int(sr)
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(
            f"Failed to find openable output samplerate for device={device}, "
            f"default_sr={float(dev_info['default_samplerate'])}, last_error={last_error}"
        )
    def _estimate_source_frames(self, output_frames: int) -> int:
        if self._opened_output_sample_rate <= 0 or self._content_sample_rate <= 0:
            return output_frames
        ratio = self._content_sample_rate / self._opened_output_sample_rate
        estimated = int(np.ceil(output_frames * ratio)) + 8
        return max(1, estimated)
```

---
### 文件: `shadowing_app/src/shadowing/realtime/runtime.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any
@dataclass(slots=True)
class RealtimeRuntimeConfig:
    tick_sleep_sec: float = 0.03
class ShadowingRuntime:
    def __init__(
        self,
        *,
        orchestrator: Any,
        config: RealtimeRuntimeConfig | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config or RealtimeRuntimeConfig()
        self._running = False
    def run(self, lesson_id: str) -> None:
        self._running = True
        self.orchestrator.start_session(lesson_id)
        try:
            while self._running:
                self.orchestrator.tick()
                time.sleep(self.config.tick_sleep_sec)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self.orchestrator.stop_session()
    def stop(self) -> None:
        self._running = False
RealtimeRuntime = ShadowingRuntime
```

---
### 文件: `shadowing_app/src/shadowing/realtime/sync_evidence.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from shadowing.types import FusionEvidence, ProgressEstimate, SignalQuality, TrackingMode
class SpeechState(str, Enum):
    NONE = "none"
    POSSIBLE = "possible"
    ACTIVE = "active"
    SUSTAINED = "sustained"
class TrackingState(str, Enum):
    NONE = "none"
    WEAK = "weak"
    RELIABLE = "reliable"
    LOCKED = "locked"
class SyncState(str, Enum):
    BOOTSTRAP = "bootstrap"
    CONVERGING = "converging"
    STABLE = "stable"
    DEGRADED = "degraded"
@dataclass(slots=True)
class SyncEvidence:
    speech_state: SpeechState
    tracking_state: TrackingState
    sync_state: SyncState
    speech_confidence: float
    tracking_confidence: float
    sync_confidence: float
    should_open_asr_gate: bool
    should_keep_asr_gate: bool
    allow_latency_observation: bool
    allow_seek: bool
    startup_mode: bool
    bluetooth_mode: bool
    bluetooth_long_session_mode: bool
    audio_confidence: float = 0.0
    still_following_likelihood: float = 0.0
    reentry_likelihood: float = 0.0
    repeated_likelihood: float = 0.0
class SyncEvidenceBuilder:
    def __init__(
        self,
        *,
        startup_window_sec: float = 4.0,
        seek_enable_after_sec: float = 8.0,
        sustained_speaking_sec: float = 0.65,
    ) -> None:
        self.startup_window_sec = float(startup_window_sec)
        self.seek_enable_after_sec = float(seek_enable_after_sec)
        self.sustained_speaking_sec = float(sustained_speaking_sec)
        self._session_started_at_sec = 0.0
        self._last_speech_like_at_sec = 0.0
        self._last_engaged_like_at_sec = 0.0
    def reset(self, now_sec: float) -> None:
        self._session_started_at_sec = float(now_sec)
        self._last_speech_like_at_sec = 0.0
        self._last_engaged_like_at_sec = 0.0
    def build(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        progress: ProgressEstimate | None,
        fusion_evidence: FusionEvidence | None,
        bluetooth_mode: bool,
        bluetooth_long_session_mode: bool = False,
    ) -> SyncEvidence:
        startup_window = self.startup_window_sec + (2.0 if bluetooth_mode else 0.0)
        startup_mode = (now_sec - self._session_started_at_sec) <= startup_window
        speech_conf = self._speech_confidence(signal_quality)
        if speech_conf >= 0.36:
            self._last_speech_like_at_sec = float(now_sec)
        speech_state = self._speech_state(
            now_sec=now_sec,
            signal_quality=signal_quality,
            speech_confidence=speech_conf,
        )
        tracking_conf = self._tracking_confidence(progress, fusion_evidence)
        tracking_state = self._tracking_state(progress, tracking_conf)
        audio_conf = 0.0 if fusion_evidence is None else float(fusion_evidence.audio_confidence)
        still_following = 0.0 if fusion_evidence is None else float(fusion_evidence.still_following_likelihood)
        reentry = 0.0 if fusion_evidence is None else float(fusion_evidence.reentry_likelihood)
        repeated = 0.0 if fusion_evidence is None else float(fusion_evidence.repeated_likelihood)
        progress_recent = False
        progress_active = False
        progress_conf = 0.0
        progress_quality = 0.0
        progress_stable = False
        progress_age = 9999.0
        if progress is not None:
            progress_recent = bool(getattr(progress, "recently_progressed", False))
            progress_active = bool(getattr(progress, "active_speaking", False))
            progress_conf = float(getattr(progress, "confidence", 0.0))
            progress_quality = float(getattr(progress, "tracking_quality", 0.0))
            progress_stable = bool(getattr(progress, "stable", False))
            progress_age = float(getattr(progress, "progress_age_sec", 9999.0))
        engaged_like = bool(
            progress_recent
            or progress_active
            or still_following >= 0.60
            or reentry >= 0.54
            or (speech_conf >= 0.46 and progress_quality >= 0.46)
        )
        if engaged_like:
            self._last_engaged_like_at_sec = float(now_sec)
        engaged_tail_sec = 1.70 if bluetooth_mode else 1.10
        engaged_recent = (
            self._last_engaged_like_at_sec > 0.0
            and (now_sec - self._last_engaged_like_at_sec) <= engaged_tail_sec
        )
        sync_conf = max(
            0.0,
            min(
                1.0,
                0.34 * speech_conf
                + 0.36 * tracking_conf
                + 0.20 * max(audio_conf, still_following)
                + 0.10 * (1.0 if engaged_recent else 0.0),
            ),
        )
        sync_state = self._sync_state(
            startup_mode=startup_mode,
            speech_state=speech_state,
            tracking_state=tracking_state,
            sync_confidence=sync_conf,
            fusion_evidence=fusion_evidence,
            engaged_recent=engaged_recent,
        )
        should_open_asr_gate = bool(
            speech_state in (SpeechState.POSSIBLE, SpeechState.ACTIVE, SpeechState.SUSTAINED)
            or (engaged_recent and still_following >= 0.52)
        )
        gate_tail_sec = 1.15 if bluetooth_mode else 0.65
        should_keep_asr_gate = bool(
            should_open_asr_gate
            or (
                self._last_speech_like_at_sec > 0.0
                and (now_sec - self._last_speech_like_at_sec) <= gate_tail_sec
            )
            or engaged_recent
        )
        allow_latency_observation = bool(
            not startup_mode
            and speech_state in (SpeechState.ACTIVE, SpeechState.SUSTAINED)
            and tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED)
            and sync_state in (SyncState.CONVERGING, SyncState.STABLE)
            and repeated < 0.50
            and reentry < 0.70
            and progress_age <= (1.10 if bluetooth_mode else 0.95)
            and progress_conf >= 0.52
            and (
                fusion_evidence is None
                or fusion_evidence.fused_confidence >= (0.54 if bluetooth_mode else 0.58)
            )
        )
        if bluetooth_mode:
            allow_seek = False
        else:
            allow_seek = bool(
                (now_sec - self._session_started_at_sec) >= self.seek_enable_after_sec
                and not startup_mode
                and tracking_state == TrackingState.LOCKED
                and sync_state == SyncState.STABLE
                and progress_stable
                and progress_quality >= 0.78
                and progress_conf >= 0.74
                and progress_age <= 0.85
                and repeated < 0.42
                and reentry < 0.42
                and still_following < 0.72
                and (
                    fusion_evidence is None
                    or not fusion_evidence.should_prevent_seek
                )
            )
        return SyncEvidence(
            speech_state=speech_state,
            tracking_state=tracking_state,
            sync_state=sync_state,
            speech_confidence=speech_conf,
            tracking_confidence=tracking_conf,
            sync_confidence=sync_conf,
            should_open_asr_gate=should_open_asr_gate,
            should_keep_asr_gate=should_keep_asr_gate,
            allow_latency_observation=allow_latency_observation,
            allow_seek=allow_seek,
            startup_mode=startup_mode,
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=bool(bluetooth_long_session_mode),
            audio_confidence=audio_conf,
            still_following_likelihood=still_following,
            reentry_likelihood=reentry,
            repeated_likelihood=repeated,
        )
    def _speech_confidence(self, signal_quality: SignalQuality | None) -> float:
        if signal_quality is None:
            return 0.0
        score = 0.0
        score += min(0.34, max(0.0, signal_quality.speaking_likelihood) * 0.46)
        score += min(0.30, max(0.0, signal_quality.rms) * 18.0)
        score += min(0.18, max(0.0, signal_quality.peak) * 2.0)
        if signal_quality.vad_active:
            score += 0.18
        if signal_quality.dropout_detected:
            score -= 0.16
        if signal_quality.clipping_ratio >= 0.05:
            score -= 0.08
        return max(0.0, min(1.0, score))
    def _speech_state(
        self,
        *,
        now_sec: float,
        signal_quality: SignalQuality | None,
        speech_confidence: float,
    ) -> SpeechState:
        if signal_quality is None:
            return SpeechState.NONE
        if speech_confidence < 0.16:
            return SpeechState.NONE
        if speech_confidence < 0.40:
            return SpeechState.POSSIBLE
        if self._last_speech_like_at_sec > 0.0 and (
            now_sec - self._last_speech_like_at_sec
        ) <= self.sustained_speaking_sec:
            return SpeechState.SUSTAINED
        return SpeechState.ACTIVE
    def _tracking_confidence(
        self,
        progress: ProgressEstimate | None,
        fusion_evidence: FusionEvidence | None,
    ) -> float:
        score = 0.0
        if progress is not None:
            score += min(0.42, float(progress.tracking_quality) * 0.50)
            score += min(0.28, float(progress.confidence) * 0.34)
            if progress.stable:
                score += 0.14
            if progress.recently_progressed:
                score += 0.10
            if progress.progress_age_sec > 1.5:
                score -= 0.10
        if fusion_evidence is not None and (progress is None or getattr(progress, "tracking_quality", 0.0) < 0.56):
            score += min(0.16, float(fusion_evidence.audio_confidence) * 0.20)
            score += min(0.14, float(fusion_evidence.still_following_likelihood) * 0.18)
        return max(0.0, min(1.0, score))
    def _tracking_state(
        self,
        progress: ProgressEstimate | None,
        tracking_confidence: float,
    ) -> TrackingState:
        if progress is None:
            return TrackingState.NONE
        mode = progress.tracking_mode
        if mode == TrackingMode.LOCKED and tracking_confidence >= 0.72:
            return TrackingState.LOCKED
        if mode in (TrackingMode.LOCKED, TrackingMode.WEAK_LOCKED) and tracking_confidence >= 0.52:
            return TrackingState.RELIABLE
        if tracking_confidence >= 0.30:
            return TrackingState.WEAK
        return TrackingState.NONE
    def _sync_state(
        self,
        *,
        startup_mode: bool,
        speech_state: SpeechState,
        tracking_state: TrackingState,
        sync_confidence: float,
        fusion_evidence: FusionEvidence | None,
        engaged_recent: bool,
    ) -> SyncState:
        if startup_mode:
            return SyncState.BOOTSTRAP
        if (
            speech_state in (SpeechState.ACTIVE, SpeechState.SUSTAINED)
            and tracking_state == TrackingState.LOCKED
            and sync_confidence >= 0.72
        ):
            return SyncState.STABLE
        if fusion_evidence is not None:
            if (
                fusion_evidence.still_following_likelihood >= 0.66
                or fusion_evidence.reentry_likelihood >= 0.54
            ) and sync_confidence >= 0.54:
                return SyncState.CONVERGING
        if engaged_recent and tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED):
            return SyncState.CONVERGING
        if speech_state != SpeechState.NONE and tracking_state in (TrackingState.RELIABLE, TrackingState.LOCKED):
            return SyncState.CONVERGING
        return SyncState.DEGRADED
```

---
### 文件: `shadowing_app/src/shadowing/session/session_metrics.py`

```python
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
_STARTUP_FALSE_HOLD_REASONS = {
    "no_progress_timeout",
    "reference_too_far_ahead",
}
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if out != out:
        return float(default)
    return float(out)
@dataclass(slots=True)
class SessionMetrics:
    lesson_id: str = ""
    session_started_at_sec: float = 0.0
    session_ended_at_sec: float = 0.0
    first_signal_active_time_sec: float | None = None
    first_asr_partial_time_sec: float | None = None
    first_reliable_progress_time_sec: float | None = None
    startup_false_hold_count: int = 0
    hold_count: int = 0
    resume_count: int = 0
    soft_duck_count: int = 0
    seek_count: int = 0
    lost_count: int = 0
    reacquire_count: int = 0
    max_tracking_quality: float = 0.0
    _tracking_quality_sum: float = 0.0
    total_progress_updates: int = 0
    tracking_total: int = 0
    tracking_stable_count: int = 0
    tracking_mode_counter: Counter[str] = field(default_factory=Counter)
    progress_recent_count: int = 0
    position_source_counter: Counter[str] = field(default_factory=Counter)
    joint_confidence_sum: float = 0.0
    signal_active_events: int = 0
    asr_partial_count: int = 0
    action_reason_counter: Counter[str] = field(default_factory=Counter)
    def mark_session_started(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = now_sec
        if self.session_ended_at_sec < self.session_started_at_sec:
            self.session_ended_at_sec = self.session_started_at_sec
    def mark_session_ended(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        if self.session_started_at_sec <= 0.0:
            self.session_started_at_sec = now_sec
        self.session_ended_at_sec = max(now_sec, self.session_started_at_sec)
    def observe_signal_active(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        self.signal_active_events += 1
        if self.first_signal_active_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_signal_active_time_sec = max(0.0, now_sec - self.session_started_at_sec)
    def observe_asr_partial(self, now_sec: float) -> None:
        now_sec = _safe_float(now_sec)
        self.asr_partial_count += 1
        if self.first_asr_partial_time_sec is None and self.session_started_at_sec > 0.0:
            self.first_asr_partial_time_sec = max(0.0, now_sec - self.session_started_at_sec)
    def observe_progress(
        self,
        *,
        now_since_session_start_sec: float,
        recently_progressed: bool,
        joint_confidence: float,
        position_source: str,
        tracking_quality: float | None = None,
        is_reliable: bool | None = None,
    ) -> None:
        self.total_progress_updates += 1
        tq = _safe_float(tracking_quality, 0.0) if tracking_quality is not None else 0.0
        jc = max(0.0, min(1.0, _safe_float(joint_confidence, 0.0)))
        if tq > self.max_tracking_quality:
            self.max_tracking_quality = tq
        self._tracking_quality_sum += tq
        self.joint_confidence_sum += jc
        if recently_progressed:
            self.progress_recent_count += 1
        source = str(position_source or "unknown")
        self.position_source_counter[source] += 1
        if is_reliable and self.first_reliable_progress_time_sec is None:
            self.first_reliable_progress_time_sec = max(0.0, _safe_float(now_since_session_start_sec))
    def observe_tracking(
        self,
        *,
        tracking_mode: str,
        tracking_quality: float,
        stable: bool,
    ) -> None:
        self.tracking_total += 1
        mode = str(tracking_mode or "unknown")
        self.tracking_mode_counter[mode] += 1
        if stable:
            self.tracking_stable_count += 1
        tq = _safe_float(tracking_quality, 0.0)
        if tq > self.max_tracking_quality:
            self.max_tracking_quality = tq
        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1
    def observe_tracking_mode(self, mode: str) -> None:
        mode = str(mode or "unknown")
        self.tracking_mode_counter[mode] += 1
        if mode == "lost":
            self.lost_count += 1
        elif mode == "reacquiring":
            self.reacquire_count += 1
    def observe_control(
        self,
        *,
        action: str,
        now_since_session_start_sec: float,
        startup_grace_sec: float,
        reason: str | None = None,
    ) -> None:
        action = str(action or "unknown")
        reason = str(reason or "").strip()
        if action == "hold":
            self.hold_count += 1
            if now_since_session_start_sec <= max(0.0, _safe_float(startup_grace_sec)):
                if reason in _STARTUP_FALSE_HOLD_REASONS:
                    self.startup_false_hold_count += 1
        elif action == "resume":
            self.resume_count += 1
        elif action == "soft_duck":
            self.soft_duck_count += 1
        elif action == "seek":
            self.seek_count += 1
        if reason:
            self.action_reason_counter[f"{action}:{reason}"] += 1
    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        if self.session_started_at_sec > 0.0:
            since_start = max(0.0, _safe_float(now_sec) - self.session_started_at_sec)
        else:
            since_start = 0.0
        self.observe_control(
            action=action,
            now_since_session_start_sec=since_start,
            startup_grace_sec=5.0,
            reason=reason,
        )
    def mean_tracking_quality(self) -> float:
        if self.total_progress_updates <= 0:
            return 0.0
        return float(self._tracking_quality_sum / self.total_progress_updates)
    def summary_dict(self) -> dict[str, Any]:
        duration_sec = 0.0
        if self.session_started_at_sec > 0.0 and self.session_ended_at_sec >= self.session_started_at_sec:
            duration_sec = float(self.session_ended_at_sec - self.session_started_at_sec)
        mean_tracking_quality = self.mean_tracking_quality()
        return {
            "first_signal_active_time_sec": self.first_signal_active_time_sec,
            "first_asr_partial_time_sec": self.first_asr_partial_time_sec,
            "first_reliable_progress_time_sec": self.first_reliable_progress_time_sec,
            "startup_false_hold_count": self.startup_false_hold_count,
            "hold_count": self.hold_count,
            "resume_count": self.resume_count,
            "soft_duck_count": self.soft_duck_count,
            "seek_count": self.seek_count,
            "lost_count": self.lost_count,
            "reacquire_count": self.reacquire_count,
            "max_tracking_quality": self.max_tracking_quality,
            "mean_tracking_quality": mean_tracking_quality,
            "total_progress_updates": self.total_progress_updates,
            "lesson_id": self.lesson_id,
            "session_started_at_sec": self.session_started_at_sec,
            "session_ended_at_sec": self.session_ended_at_sec,
            "session_duration_sec": duration_sec,
            "signal_active_events": self.signal_active_events,
            "asr_partial_count": self.asr_partial_count,
            "tracking_total": self.tracking_total,
            "tracking_stable_count": self.tracking_stable_count,
            "progress_recent_count": self.progress_recent_count,
            "avg_joint_confidence": (
                float(self.joint_confidence_sum / self.total_progress_updates)
                if self.total_progress_updates > 0
                else 0.0
            ),
            "tracking_mode_counter": dict(self.tracking_mode_counter),
            "position_source_counter": dict(self.position_source_counter),
            "action_reason_counter": dict(self.action_reason_counter),
        }
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/event_logger.py`

```python
from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any
class EventLogger:
    def __init__(self, session_dir: str, enabled: bool = True) -> None:
        self.session_dir = Path(session_dir)
        self.enabled = bool(enabled)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.session_dir / "events.jsonl"
        self._lock = threading.Lock()
    def log(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        ts_monotonic_sec: float | None = None,
        session_tick: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        record = {
            "event_type": str(event_type),
            "ts_monotonic_sec": (
                float(ts_monotonic_sec) if ts_monotonic_sec is not None else None
            ),
            "session_tick": int(session_tick) if session_tick is not None else None,
            "payload": payload,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/metrics.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from shadowing.session.session_metrics import SessionMetrics
@dataclass(slots=True)
class SessionMetricsSummary:
    first_signal_active_time_sec: float | None
    first_asr_partial_time_sec: float | None
    first_reliable_progress_time_sec: float | None
    startup_false_hold_count: int
    hold_count: int
    resume_count: int
    soft_duck_count: int
    seek_count: int
    lost_count: int
    reacquire_count: int
    max_tracking_quality: float
    mean_tracking_quality: float
    total_progress_updates: int
class MetricsAggregator:
    def __init__(self, lesson_id: str = "") -> None:
        self._delegate = SessionMetrics(lesson_id=lesson_id)
    def mark_session_started(self, now_sec: float) -> None:
        self._delegate.mark_session_started(now_sec)
    def mark_session_ended(self, now_sec: float) -> None:
        self._delegate.mark_session_ended(now_sec)
    def observe_signal_active(self, now_sec: float) -> None:
        self._delegate.observe_signal_active(now_sec)
    def observe_asr_partial(self, now_sec: float) -> None:
        self._delegate.observe_asr_partial(now_sec)
    def observe_progress(self, now_sec: float, tracking_quality: float, is_reliable: bool) -> None:
        if self._delegate.session_started_at_sec > 0.0:
            since_start = max(0.0, float(now_sec) - self._delegate.session_started_at_sec)
        else:
            since_start = 0.0
        self._delegate.observe_progress(
            now_since_session_start_sec=since_start,
            recently_progressed=False,
            joint_confidence=float(tracking_quality),
            position_source="unknown",
            tracking_quality=float(tracking_quality),
            is_reliable=bool(is_reliable),
        )
    def observe_action(self, action: str, reason: str, now_sec: float) -> None:
        self._delegate.observe_action(action, reason, now_sec)
    def observe_tracking_mode(self, mode: str) -> None:
        self._delegate.observe_tracking_mode(mode)
    def summary(self) -> SessionMetricsSummary:
        d = self._delegate.summary_dict()
        return SessionMetricsSummary(
            first_signal_active_time_sec=d.get("first_signal_active_time_sec"),
            first_asr_partial_time_sec=d.get("first_asr_partial_time_sec"),
            first_reliable_progress_time_sec=d.get("first_reliable_progress_time_sec"),
            startup_false_hold_count=int(d.get("startup_false_hold_count", 0)),
            hold_count=int(d.get("hold_count", 0)),
            resume_count=int(d.get("resume_count", 0)),
            soft_duck_count=int(d.get("soft_duck_count", 0)),
            seek_count=int(d.get("seek_count", 0)),
            lost_count=int(d.get("lost_count", 0)),
            reacquire_count=int(d.get("reacquire_count", 0)),
            max_tracking_quality=float(d.get("max_tracking_quality", 0.0)),
            mean_tracking_quality=float(d.get("mean_tracking_quality", 0.0)),
            total_progress_updates=int(d.get("total_progress_updates", 0)),
        )
    def summary_dict(self) -> dict:
        return self._delegate.summary_dict()
    @property
    def session_metrics(self) -> SessionMetrics:
        return self._delegate
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/replay_loader.py`

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
@dataclass(slots=True)
class ReplayEvent:
    event_type: str
    ts_monotonic_sec: float | None
    session_tick: int | None
    payload: dict
class ReplayLoader:
    def __init__(self, events_file: str) -> None:
        self.events_file = Path(events_file)
    def __iter__(self) -> Iterator[ReplayEvent]:
        with self.events_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                yield ReplayEvent(
                    event_type=str(data.get("event_type", "")),
                    ts_monotonic_sec=(
                        float(data["ts_monotonic_sec"])
                        if data.get("ts_monotonic_sec") is not None
                        else None
                    ),
                    session_tick=(
                        int(data["session_tick"])
                        if data.get("session_tick") is not None
                        else None
                    ),
                    payload=dict(data.get("payload", {})),
                )
```

---
### 文件: `shadowing_app/src/shadowing/telemetry/session_evaluator.py`

```python
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
```

---
### 文件: `shadowing_app/src/shadowing/tracking/anchor_manager.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from shadowing.types import TrackingSnapshot
@dataclass(slots=True)
class Anchor:
    ref_idx: int
    emitted_at_sec: float
    quality_score: float
    matched_text: str = ""
class AnchorManager:
    def __init__(
        self,
        strong_anchor_quality: float = 0.78,
        weak_anchor_quality: float = 0.64,
        max_anchor_gap: int = 24,
    ) -> None:
        self.strong_anchor_quality = float(strong_anchor_quality)
        self.weak_anchor_quality = float(weak_anchor_quality)
        self.max_anchor_gap = int(max_anchor_gap)
        self._strong_anchor: Anchor | None = None
        self._weak_anchor: Anchor | None = None
    def reset(self) -> None:
        self._strong_anchor = None
        self._weak_anchor = None
    def update(self, snapshot: TrackingSnapshot) -> None:
        q = snapshot.tracking_quality.overall_score
        text = snapshot.matched_text or ""
        if snapshot.stable and q >= self.strong_anchor_quality:
            self._strong_anchor = Anchor(
                ref_idx=int(snapshot.candidate_ref_idx),
                emitted_at_sec=float(snapshot.emitted_at_sec),
                quality_score=float(q),
                matched_text=text,
            )
            self._weak_anchor = Anchor(
                ref_idx=int(snapshot.candidate_ref_idx),
                emitted_at_sec=float(snapshot.emitted_at_sec),
                quality_score=float(q),
                matched_text=text,
            )
            return
        if q >= self.weak_anchor_quality:
            if self._strong_anchor is None:
                self._weak_anchor = Anchor(
                    ref_idx=int(snapshot.candidate_ref_idx),
                    emitted_at_sec=float(snapshot.emitted_at_sec),
                    quality_score=float(q),
                    matched_text=text,
                )
                return
            if abs(snapshot.candidate_ref_idx - self._strong_anchor.ref_idx) <= self.max_anchor_gap:
                self._weak_anchor = Anchor(
                    ref_idx=int(snapshot.candidate_ref_idx),
                    emitted_at_sec=float(snapshot.emitted_at_sec),
                    quality_score=float(q),
                    matched_text=text,
                )
    def current_anchor_idx(self) -> int:
        if self._strong_anchor is not None:
            return self._strong_anchor.ref_idx
        if self._weak_anchor is not None:
            return self._weak_anchor.ref_idx
        return 0
    def strong_anchor(self) -> Anchor | None:
        return self._strong_anchor
    def weak_anchor(self) -> Anchor | None:
        return self._weak_anchor
    def anchor_consistency(self, candidate_idx: int) -> float:
        anchor_idx = self.current_anchor_idx()
        dist = abs(int(candidate_idx) - int(anchor_idx))
        return 1.0 / (1.0 + (dist / 14.0))
```

---
### 文件: `shadowing_app/src/shadowing/tracking/loss_detector.py`

```python
from __future__ import annotations
from collections import deque
from statistics import pstdev
from shadowing.types import TrackingMode, TrackingSnapshot
class LossDetector:
    def __init__(
        self,
        jitter_window: int = 6,
        weak_quality_threshold: float = 0.56,
        lost_quality_threshold: float = 0.40,
        max_jitter_sigma: float = 8.0,
        lost_run_threshold: int = 4,
    ) -> None:
        self.jitter_window = int(jitter_window)
        self.weak_quality_threshold = float(weak_quality_threshold)
        self.lost_quality_threshold = float(lost_quality_threshold)
        self.max_jitter_sigma = float(max_jitter_sigma)
        self.lost_run_threshold = int(lost_run_threshold)
        self._recent_candidates: deque[int] = deque(maxlen=self.jitter_window)
        self._low_quality_run = 0
        self._good_quality_run = 0
        self._last_reliable_at_sec = 0.0
    def reset(self) -> None:
        self._recent_candidates.clear()
        self._low_quality_run = 0
        self._good_quality_run = 0
        self._last_reliable_at_sec = 0.0
    def update(
        self,
        snapshot: TrackingSnapshot,
        overall_score: float,
        is_reliable: bool,
    ) -> tuple[TrackingMode, float]:
        candidate_idx = int(snapshot.candidate_ref_idx)
        series = list(self._recent_candidates) + [candidate_idx]
        if len(series) <= 1:
            temporal_consistency = 0.72
        else:
            sigma = pstdev(series)
            temporal_consistency = max(0.0, 1.0 - min(1.0, sigma / self.max_jitter_sigma))
        if is_reliable:
            self._last_reliable_at_sec = float(snapshot.emitted_at_sec)
            self._good_quality_run += 1
            self._low_quality_run = 0
        else:
            self._low_quality_run += 1
            self._good_quality_run = 0
        if is_reliable and overall_score >= 0.78 and self._good_quality_run >= 1:
            mode = TrackingMode.LOCKED
        elif overall_score >= self.weak_quality_threshold and temporal_consistency >= 0.28:
            mode = TrackingMode.WEAK_LOCKED
        elif (
            self._last_reliable_at_sec > 0.0
            and (snapshot.emitted_at_sec - self._last_reliable_at_sec) <= 2.0
        ):
            mode = TrackingMode.REACQUIRING
        elif overall_score < self.lost_quality_threshold and self._low_quality_run >= self.lost_run_threshold:
            mode = TrackingMode.LOST
        else:
            mode = TrackingMode.REACQUIRING
        self._recent_candidates.append(candidate_idx)
        return mode, float(temporal_consistency)
```

---
### 文件: `shadowing_app/src/shadowing/tracking/partial_guard.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass
class PartialGuardConfig:
    backward_hits_to_reset: int = 2
    low_q_threshold: float = 0.45
    low_q_hold_sec: float = 0.80
    no_commit_sec: float = 1.20
    max_partial_chars: int = 48
    long_partial_low_trust_threshold: float = 0.55
@dataclass
class PartialGuardState:
    backward_hits: int = 0
    low_q_elapsed_sec: float = 0.0
    no_commit_elapsed_sec: float = 0.0
    partial_reset_recommended: bool = False
    reason: str = ""
class PartialGuard:
    def __init__(self, config: PartialGuardConfig | None = None) -> None:
        self.config = config or PartialGuardConfig()
        self._state = PartialGuardState()
    @property
    def state(self) -> PartialGuardState:
        return self._state
    def reset(self) -> None:
        self._state = PartialGuardState()
    def update(
        self,
        *,
        dt_sec: float,
        partial_text: str,
        committed_advanced: bool,
        backward: bool,
        tracking_quality: float,
        anchor_trust: float,
    ) -> PartialGuardState:
        s = self._state
        s.partial_reset_recommended = False
        s.reason = ""
        if backward:
            s.backward_hits += 1
        else:
            s.backward_hits = 0
        if tracking_quality < self.config.low_q_threshold:
            s.low_q_elapsed_sec += max(0.0, dt_sec)
        else:
            s.low_q_elapsed_sec = 0.0
        if committed_advanced:
            s.no_commit_elapsed_sec = 0.0
        else:
            s.no_commit_elapsed_sec += max(0.0, dt_sec)
        partial_len = len(partial_text or "")
        if s.backward_hits >= self.config.backward_hits_to_reset:
            s.partial_reset_recommended = True
            s.reason = f"backward_hits={s.backward_hits}"
            return s
        if s.low_q_elapsed_sec >= self.config.low_q_hold_sec:
            s.partial_reset_recommended = True
            s.reason = f"low_tracking_q_for={s.low_q_elapsed_sec:.3f}s"
            return s
        if s.no_commit_elapsed_sec >= self.config.no_commit_sec:
            s.partial_reset_recommended = True
            s.reason = f"no_commit_for={s.no_commit_elapsed_sec:.3f}s"
            return s
        if (
            partial_len >= self.config.max_partial_chars
            and anchor_trust < self.config.long_partial_low_trust_threshold
        ):
            s.partial_reset_recommended = True
            s.reason = f"long_partial_len={partial_len}_low_trust={anchor_trust:.3f}"
            return s
        return s
```

---
### 文件: `shadowing_app/src/shadowing/tracking/reacquirer.py`

```python
from __future__ import annotations
from shadowing.types import ReferenceMap, TrackingMode, TrackingSnapshot
class Reacquirer:
    def __init__(self, max_anchor_jump: int = 24, min_anchor_score: float = 0.52) -> None:
        self.max_anchor_jump = int(max_anchor_jump)
        self.min_anchor_score = float(min_anchor_score)
    def maybe_reanchor(self, *, snapshot: TrackingSnapshot, anchor_manager, ref_map: ReferenceMap) -> TrackingSnapshot:
        _ = ref_map
        anchor = anchor_manager.strong_anchor() or anchor_manager.weak_anchor()
        if anchor is None:
            return snapshot
        if snapshot.tracking_mode not in (TrackingMode.REACQUIRING, TrackingMode.LOST):
            return snapshot
        if snapshot.tracking_quality.anchor_score < self.min_anchor_score:
            return snapshot
        anchor_idx = int(anchor.ref_idx)
        cur_idx = int(snapshot.candidate_ref_idx)
        if abs(cur_idx - anchor_idx) > self.max_anchor_jump:
            return snapshot
        if snapshot.anchor_consistency < self.min_anchor_score:
            return snapshot
        return TrackingSnapshot(
            candidate_ref_idx=max(cur_idx, anchor_idx),
            committed_ref_idx=max(int(snapshot.committed_ref_idx), anchor_idx),
            candidate_ref_time_sec=float(snapshot.candidate_ref_time_sec),
            confidence=float(max(snapshot.confidence, min(0.88, anchor.quality_score))),
            stable=bool(snapshot.stable),
            local_match_ratio=float(snapshot.local_match_ratio),
            repeat_penalty=float(snapshot.repeat_penalty),
            monotonic_consistency=float(snapshot.monotonic_consistency),
            anchor_consistency=float(max(snapshot.anchor_consistency, 0.72)),
            emitted_at_sec=float(snapshot.emitted_at_sec),
            tracking_mode=TrackingMode.REACQUIRING,
            tracking_quality=snapshot.tracking_quality,
            matched_text=snapshot.matched_text,
        )
```

---
### 文件: `shadowing_app/src/shadowing/tracking/shadow_lag_estimator.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass
class ShadowLagEstimatorConfig:
    init_sec: float = 1.20
    min_sec: float = 0.35
    max_sec: float = 2.40
    ema_alpha: float = 0.18
    update_min_tracking_q: float = 0.78
    update_min_anchor_trust: float = 0.78
class ShadowLagEstimator:
    def __init__(self, config: ShadowLagEstimatorConfig | None = None) -> None:
        self.config = config or ShadowLagEstimatorConfig()
        self._offset_sec = float(self.config.init_sec)
    @property
    def offset_sec(self) -> float:
        return float(self._offset_sec)
    def reset(self) -> None:
        self._offset_sec = float(self.config.init_sec)
    def set_offset(self, value_sec: float) -> None:
        self._offset_sec = self._clamp(value_sec)
    def update_from_anchor(
        self,
        raw_lead_sec: float | None,
        *,
        stable_anchor: bool,
        tracking_quality: float,
        anchor_trust: float,
    ) -> float:
        if raw_lead_sec is None:
            return self.offset_sec
        if not stable_anchor:
            return self.offset_sec
        if tracking_quality < self.config.update_min_tracking_q:
            return self.offset_sec
        if anchor_trust < self.config.update_min_anchor_trust:
            return self.offset_sec
        alpha = self.config.ema_alpha
        target = self._clamp(raw_lead_sec)
        self._offset_sec = self._clamp((1.0 - alpha) * self._offset_sec + alpha * target)
        return self.offset_sec
    def effective_lead(self, raw_lead_sec: float | None) -> float | None:
        if raw_lead_sec is None:
            return None
        return float(raw_lead_sec) - self.offset_sec
    def _clamp(self, value_sec: float) -> float:
        return max(self.config.min_sec, min(self.config.max_sec, float(value_sec)))
```

---
### 文件: `shadowing_app/src/shadowing/tracking/stable_anchor.py`

```python
from __future__ import annotations
from dataclasses import dataclass
@dataclass
class StableAnchorConfig:
    min_tracking_q: float = 0.78
    min_confidence: float = 0.78
    min_score: float = 0.0
    same_candidate_hits: int = 2
    backward_penalty: float = 0.35
    unstable_penalty: float = 0.20
@dataclass
class StableAnchorDecision:
    stable_anchor: bool
    anchor_trust: float
    same_candidate_hits: int
class StableAnchorTracker:
    def __init__(self, config: StableAnchorConfig | None = None) -> None:
        self.config = config or StableAnchorConfig()
        self._last_candidate_idx: int | None = None
        self._same_candidate_hits: int = 0
    def reset(self) -> None:
        self._last_candidate_idx = None
        self._same_candidate_hits = 0
    def update(
        self,
        *,
        candidate_idx: int | None,
        confidence: float,
        tracking_quality: float,
        score: float,
        backward: bool,
    ) -> StableAnchorDecision:
        if candidate_idx is None:
            self._last_candidate_idx = None
            self._same_candidate_hits = 0
            return StableAnchorDecision(
                stable_anchor=False,
                anchor_trust=0.0,
                same_candidate_hits=0,
            )
        if self._last_candidate_idx == candidate_idx:
            self._same_candidate_hits += 1
        else:
            self._last_candidate_idx = candidate_idx
            self._same_candidate_hits = 1
        anchor_trust = self._compute_anchor_trust(
            confidence=confidence,
            tracking_quality=tracking_quality,
            score=score,
            backward=backward,
            same_hits=self._same_candidate_hits,
        )
        stable_anchor = (
            not backward
            and tracking_quality >= self.config.min_tracking_q
            and confidence >= self.config.min_confidence
            and score >= self.config.min_score
            and self._same_candidate_hits >= self.config.same_candidate_hits
        )
        return StableAnchorDecision(
            stable_anchor=stable_anchor,
            anchor_trust=anchor_trust,
            same_candidate_hits=self._same_candidate_hits,
        )
    def _compute_anchor_trust(
        self,
        *,
        confidence: float,
        tracking_quality: float,
        score: float,
        backward: bool,
        same_hits: int,
    ) -> float:
        trust = 0.55 * float(confidence) + 0.35 * float(tracking_quality)
        if score >= 0:
            trust += min(0.10, score / 100.0)
        else:
            trust -= min(0.10, abs(score) / 50.0)
        trust += min(0.12, 0.04 * max(0, same_hits - 1))
        if backward:
            trust -= self.config.backward_penalty
        if same_hits < self.config.same_candidate_hits:
            trust -= self.config.unstable_penalty
        return max(0.0, min(1.0, trust))
```

---
### 文件: `shadowing_app/src/shadowing/tracking/tracking_engine.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.tracking.anchor_manager import AnchorManager
from shadowing.tracking.loss_detector import LossDetector
from shadowing.tracking.reacquirer import Reacquirer
from shadowing.types import AsrEvent, ReferenceMap, TrackingMode, TrackingQuality, TrackingSnapshot
@dataclass(slots=True)
class _TrackingContext:
    ref_map: ReferenceMap | None = None
    last_generation: int = 0
class TrackingEngine:
    def __init__(self, aligner: IncrementalAligner, debug: bool = False) -> None:
        self.aligner = aligner
        self.debug = bool(debug)
        self.anchor_manager = AnchorManager()
        self.loss_detector = LossDetector()
        self.reacquirer = Reacquirer()
        self._ctx = _TrackingContext()
    def reset(self, ref_map: ReferenceMap) -> None:
        self._ctx = _TrackingContext(ref_map=ref_map, last_generation=0)
        reference_text = "".join(token.char for token in ref_map.tokens)
        self.aligner.set_reference(reference_text)
        self.anchor_manager.reset()
        self.loss_detector.reset()
    def on_playback_generation_changed(self, generation: int) -> None:
        self._ctx.last_generation = int(generation)
        committed = self.aligner.get_committed_index()
        self.aligner.reset(committed=committed)
    def recenter_from_audio(
        self,
        *,
        ref_idx_hint: int,
        search_back: int = 12,
        search_ahead: int = 28,
        budget_events: int = 6,
    ) -> None:
        ref_map = self._ctx.ref_map
        if ref_map is None or not ref_map.tokens:
            return
        hint = max(0, min(int(ref_idx_hint), len(ref_map.tokens) - 1))
        self.aligner.force_recenter(
            committed_hint=hint,
            window_back=int(search_back),
            window_ahead=int(search_ahead),
            budget_events=int(budget_events),
        )
    def update(self, event: AsrEvent) -> TrackingSnapshot | None:
        ref_map = self._ctx.ref_map
        if ref_map is None or not ref_map.tokens:
            return None
        result = self.aligner.update(event.normalized_text)
        max_idx = len(ref_map.tokens) - 1
        candidate_idx = max(0, min(int(result.candidate), max_idx))
        committed_idx = max(0, min(int(result.committed), max_idx))
        observation_score = float(max(0.0, min(1.0, result.conf)))
        local_match = float(max(0.0, min(1.0, result.local_match)))
        monotonic_consistency = 1.0 if not result.backward else 0.0
        repeat_penalty = 0.12 if result.repeated_candidate else 0.0
        anchor_score = float(self.anchor_manager.anchor_consistency(candidate_idx))
        preliminary_overall = (
            0.60 * observation_score
            + 0.25 * local_match
            + 0.15 * monotonic_consistency
        )
        preliminary_reliable = bool(
            observation_score >= 0.60
            and local_match >= 0.58
            and not result.backward
        )
        provisional = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(ref_map.tokens[candidate_idx].t_start),
            confidence=float(result.conf),
            stable=bool(result.stable),
            local_match_ratio=local_match,
            repeat_penalty=repeat_penalty,
            monotonic_consistency=monotonic_consistency,
            anchor_consistency=anchor_score,
            emitted_at_sec=float(event.emitted_at_sec),
            tracking_mode=TrackingMode.BOOTSTRAP,
            tracking_quality=TrackingQuality(
                overall_score=float(preliminary_overall),
                observation_score=float(observation_score),
                temporal_consistency_score=0.72,
                anchor_score=float(anchor_score),
                mode=TrackingMode.BOOTSTRAP,
                is_reliable=preliminary_reliable,
            ),
            matched_text=event.normalized_text[: max(0, result.matched_n)],
        )
        mode, temporal_consistency = self.loss_detector.update(
            provisional,
            overall_score=preliminary_overall,
            is_reliable=preliminary_reliable,
        )
        overall_score = (
            0.50 * observation_score
            + 0.20 * local_match
            + 0.15 * float(temporal_consistency)
            + 0.15 * anchor_score
        )
        overall_score = float(max(0.0, min(1.0, overall_score)))
        is_reliable = bool(
            overall_score >= 0.60
            and observation_score >= 0.58
            and local_match >= 0.55
            and not result.backward
        )
        snapshot = TrackingSnapshot(
            candidate_ref_idx=candidate_idx,
            committed_ref_idx=committed_idx,
            candidate_ref_time_sec=float(ref_map.tokens[candidate_idx].t_start),
            confidence=float(result.conf),
            stable=bool(result.stable),
            local_match_ratio=local_match,
            repeat_penalty=repeat_penalty,
            monotonic_consistency=monotonic_consistency,
            anchor_consistency=anchor_score,
            emitted_at_sec=float(event.emitted_at_sec),
            tracking_mode=mode,
            tracking_quality=TrackingQuality(
                overall_score=overall_score,
                observation_score=float(observation_score),
                temporal_consistency_score=float(temporal_consistency),
                anchor_score=float(anchor_score),
                mode=mode,
                is_reliable=is_reliable,
            ),
            matched_text=event.normalized_text[: max(0, result.matched_n)],
        )
        self.anchor_manager.update(snapshot)
        snapshot = self.reacquirer.maybe_reanchor(
            snapshot=snapshot,
            anchor_manager=self.anchor_manager,
            ref_map=ref_map,
        )
        return snapshot
```

---
### 文件: `shadowing_app/src/shadowing/types.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re
import numpy as np
from numpy.typing import NDArray
from pypinyin import Style, lazy_pinyin
class PlaybackState(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    HOLDING = "holding"
    SEEKING = "seeking"
    FINISHED = "finished"
class ControlAction(str, Enum):
    NOOP = "noop"
    SOFT_DUCK = "soft_duck"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"
class AsrEventType(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"
    ENDPOINT = "endpoint"
class PlayerCommandType(str, Enum):
    START = "start"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"
    SET_GAIN = "set_gain"
class TrackingMode(str, Enum):
    BOOTSTRAP = "bootstrap"
    LOCKED = "locked"
    WEAK_LOCKED = "weak_locked"
    REACQUIRING = "reacquiring"
    LOST = "lost"
class UserReadState(str, Enum):
    NOT_STARTED = "not_started"
    WARMING_UP = "warming_up"
    FOLLOWING = "following"
    HESITATING = "hesitating"
    PAUSED = "paused"
    REPEATING = "repeating"
    SKIPPING = "skipping"
    REJOINING = "rejoining"
    LOST = "lost"
@dataclass(slots=True)
class PlayerCommand:
    cmd: PlayerCommandType
    target_time_sec: Optional[float] = None
    gain: Optional[float] = None
    reason: str = ""
@dataclass(slots=True)
class AudioChunk:
    chunk_id: int
    sample_rate: int
    channels: int
    samples: NDArray[np.float32]
    duration_sec: float
    start_time_sec: float
    path: Optional[str] = None
@dataclass(slots=True)
class RefToken:
    idx: int
    char: str
    pinyin: str
    t_start: float
    t_end: float
    sentence_id: int
    clause_id: int
@dataclass(slots=True)
class ReferenceMap:
    lesson_id: str
    tokens: list[RefToken]
    total_duration_sec: float
@dataclass(slots=True)
class LessonManifest:
    lesson_id: str
    lesson_text: str
    sample_rate_out: int
    chunk_paths: list[str]
    reference_map_path: str
    schema_version: int = 1
    provider_name: str = "elevenlabs"
    output_format: str = "mp3_44100_128"
@dataclass(slots=True)
class PlaybackStatus:
    state: PlaybackState
    chunk_id: int
    frame_index: int
    gain: float
    generation: int
    t_host_output_sec: float
    t_ref_block_start_content_sec: float
    t_ref_block_end_content_sec: float
    t_ref_emitted_content_sec: float
    t_ref_heard_content_sec: float
@dataclass(slots=True)
class RawAsrEvent:
    event_type: AsrEventType
    text: str
    emitted_at_sec: float
@dataclass(slots=True)
class AsrEvent:
    event_type: AsrEventType
    text: str
    normalized_text: str
    chars: list[str]
    pinyin_seq: list[str]
    emitted_at_sec: float
@dataclass(slots=True)
class HypToken:
    char: str
    pinyin: str
@dataclass(slots=True)
class CandidateAlignment:
    ref_start_idx: int
    ref_end_idx: int
    score: float
    confidence: float
    matched_ref_indices: list[int] = field(default_factory=list)
    backward_jump: bool = False
    mode: str = "normal"
@dataclass(slots=True)
class AlignResult:
    committed_ref_idx: int
    candidate_ref_idx: int
    ref_time_sec: float
    confidence: float
    stable: bool
    matched_text: str = ""
    matched_pinyin: list[str] = field(default_factory=list)
    window_start_idx: int = 0
    window_end_idx: int = 0
    alignment_mode: str = "normal"
    backward_jump_detected: bool = False
    debug_score: float = 0.0
    debug_stable_run: int = 0
    debug_backward_run: int = 0
    debug_matched_count: int = 0
    debug_hyp_length: int = 0
    local_match_ratio: float = 0.0
    repeat_penalty: float = 0.0
    emitted_at_sec: float = 0.0
@dataclass(slots=True)
class SignalQuality:
    observed_at_sec: float
    rms: float
    peak: float
    vad_active: bool
    speaking_likelihood: float
    silence_run_sec: float
    clipping_ratio: float
    dropout_detected: bool
    quality_score: float
@dataclass(slots=True)
class TrackingQuality:
    overall_score: float
    observation_score: float
    temporal_consistency_score: float
    anchor_score: float
    mode: TrackingMode
    is_reliable: bool
@dataclass(slots=True)
class TrackingSnapshot:
    candidate_ref_idx: int
    committed_ref_idx: int
    candidate_ref_time_sec: float
    confidence: float
    stable: bool
    local_match_ratio: float
    repeat_penalty: float
    monotonic_consistency: float
    anchor_consistency: float
    emitted_at_sec: float
    tracking_mode: TrackingMode
    tracking_quality: TrackingQuality
    matched_text: str = ""
@dataclass(slots=True)
class ProgressEstimate:
    estimated_ref_idx: int
    estimated_ref_time_sec: float
    progress_velocity_idx_per_sec: float
    event_emitted_at_sec: float
    last_progress_at_sec: float
    progress_age_sec: float
    source_candidate_ref_idx: int
    source_committed_ref_idx: int
    tracking_mode: TrackingMode
    tracking_quality: float
    stable: bool
    confidence: float
    active_speaking: bool
    recently_progressed: bool
    user_state: UserReadState
    audio_confidence: float = 0.0
    joint_confidence: float = 0.0
    position_source: str = "text"
    audio_support_strength: float = 0.0
@dataclass(slots=True)
class ControlDecision:
    action: ControlAction
    reason: str
    target_time_sec: Optional[float] = None
    lead_sec: Optional[float] = None
    target_gain: Optional[float] = None
    replay_lockin: bool = False
    confidence: float = 0.0
    aggressiveness: str = "low"
@dataclass(slots=True)
class DeviceProfileSnapshot:
    input_device_id: str
    output_device_id: str
    input_kind: str
    output_kind: str
    input_sample_rate: int
    output_sample_rate: int
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    noise_floor_rms: float
    input_gain_hint: str
    reliability_tier: str
@dataclass(slots=True)
class LatencyCalibrationSnapshot:
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    confidence: float
    calibrated: bool
@dataclass(slots=True)
class AudioMatchSnapshot:
    estimated_ref_time_sec: float
    estimated_ref_idx_hint: int
    confidence: float
    local_similarity: float
    envelope_alignment_score: float
    onset_alignment_score: float
    band_alignment_score: float
    rhythm_consistency_score: float
    repeated_pattern_score: float
    drift_sec: float
    mode: str
    emitted_at_sec: float
    dtw_cost: float = 0.0
    dtw_path_score: float = 0.0
    dtw_coverage: float = 0.0
    coarse_candidate_rank: int = 0
    time_offset_sec: float = 0.0
@dataclass(slots=True)
class AudioBehaviorSnapshot:
    still_following_likelihood: float
    repeated_likelihood: float
    reentry_likelihood: float
    paused_likelihood: float
    confidence: float
    emitted_at_sec: float
@dataclass(slots=True)
class FusionEvidence:
    estimated_ref_time_sec: float
    estimated_ref_idx_hint: int
    text_confidence: float
    audio_confidence: float
    fused_confidence: float
    still_following_likelihood: float
    repeated_likelihood: float
    reentry_likelihood: float
    should_prevent_hold: bool
    should_prevent_seek: bool
    should_widen_reacquire_window: bool
    should_recenter_aligner_window: bool
    emitted_at_sec: float
def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=\s]+", "", text)
    return text
@dataclass(slots=True)
class Wording:
    raw_text: str = ""
    normalized_text: str = ""
    pinyins: list[str] = field(default_factory=list)
    @classmethod
    def from_text(cls, text: str) -> "Wording":
        normalized_text = _normalize_text(text)
        pinyins = lazy_pinyin(normalized_text, style=Style.TONE3)
        return cls(raw_text=text, normalized_text=normalized_text, pinyins=pinyins)
    def __len__(self) -> int:
        return len(self.pinyins)
    def __getitem__(self, key: int | slice) -> list[str]:
        return self.pinyins[key]
```

---
### 文件: `shadowing_app/tools/_bootstrap.py`

```python
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
```

---
### 文件: `shadowing_app/tools/run_shadowing.py`

```python
from __future__ import annotations
import _bootstrap
import argparse
import json
import os
import re
from pathlib import Path
import sounddevice as sd
from shadowing.audio.bluetooth_preflight import (
    BluetoothPreflightConfig,
    run_bluetooth_duplex_preflight,
    should_run_bluetooth_preflight,
)
from shadowing.audio.device_profile import normalize_device_id
from shadowing.bootstrap import build_runtime
from shadowing.llm.qwen_hotwords import extract_hotwords_with_qwen
from shadowing.realtime.capture.device_utils import pick_working_input_config
def slugify_filename_stem(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem or "lesson"
def validate_lesson_assets(lesson_dir: Path) -> None:
    manifest = lesson_dir / "lesson_manifest.json"
    ref_map = lesson_dir / "reference_map.json"
    chunks_dir = lesson_dir / "chunks"
    missing: list[str] = []
    for p in (manifest, ref_map, chunks_dir):
        if not p.exists():
            missing.append(str(p))
    if missing:
        raise FileNotFoundError(
            "Lesson assets not found. Please run preprocess first.\n" + "\n".join(missing)
        )
def load_manifest(lesson_dir: Path) -> dict:
    return json.loads((lesson_dir / "lesson_manifest.json").read_text(encoding="utf-8"))
def collect_sherpa_paths() -> dict:
    return {
        "tokens": os.getenv("SHERPA_TOKENS", ""),
        "encoder": os.getenv("SHERPA_ENCODER", ""),
        "decoder": os.getenv("SHERPA_DECODER", ""),
        "joiner": os.getenv("SHERPA_JOINER", ""),
    }
def validate_sherpa_paths(paths: dict) -> None:
    missing_keys: list[str] = []
    missing_files: list[str] = []
    env_map = {
        "tokens": "SHERPA_TOKENS",
        "encoder": "SHERPA_ENCODER",
        "decoder": "SHERPA_DECODER",
        "joiner": "SHERPA_JOINER",
    }
    for key in ("tokens", "encoder", "decoder", "joiner"):
        value = (paths.get(key) or "").strip()
        if not value:
            missing_keys.append(env_map[key])
            continue
        if not Path(value).expanduser().exists():
            missing_files.append(f"{key}: {value}")
    if missing_keys or missing_files:
        parts: list[str] = []
        if missing_keys:
            parts.append("Missing sherpa env vars: " + ", ".join(missing_keys))
        if missing_files:
            parts.append("Non-existent sherpa files:\n" + "\n".join(missing_files))
        raise FileNotFoundError("Sherpa model configuration is invalid.\n" + "\n".join(parts))
def _parse_input_device_arg(raw_value: str | None) -> int | str | None:
    if raw_value is None:
        return None
    raw = str(raw_value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw
def _parse_output_device_arg(raw_value: str | None) -> int | str | None:
    if raw_value is None:
        return None
    raw = str(raw_value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw
def _query_input_device_info(device_value: int | str | None) -> dict[str, object]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    if device_value is None:
        default_in, _ = sd.default.device
        if default_in is None or int(default_in) < 0:
            return {
                "index": None,
                "name": "unknown",
                "hostapi_name": "",
                "device_id": "",
            }
        device_value = int(default_in)
    if isinstance(device_value, int):
        dev = sd.query_devices(int(device_value))
        hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
        name = str(dev["name"])
        return {
            "index": int(device_value),
            "name": name,
            "hostapi_name": hostapi_name,
            "device_id": normalize_device_id(
                device_name=name,
                hostapi_name=hostapi_name,
                device_index=int(device_value),
            ),
        }
    target = str(device_value).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_input_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
            name = str(dev["name"])
            return {
                "index": int(idx),
                "name": name,
                "hostapi_name": hostapi_name,
                "device_id": normalize_device_id(
                    device_name=name,
                    hostapi_name=hostapi_name,
                    device_index=int(idx),
                ),
            }
    return {
        "index": None,
        "name": str(device_value),
        "hostapi_name": "",
        "device_id": normalize_device_id(device_name=str(device_value), hostapi_name=""),
    }
def _query_output_device_info(device_value: int | str | None) -> dict[str, object]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    if device_value is None:
        _, default_out = sd.default.device
        if default_out is None or int(default_out) < 0:
            return {
                "index": None,
                "name": "unknown",
                "hostapi_name": "",
                "device_id": "",
            }
        device_value = int(default_out)
    if isinstance(device_value, int):
        dev = sd.query_devices(int(device_value))
        hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
        name = str(dev["name"])
        return {
            "index": int(device_value),
            "name": name,
            "hostapi_name": hostapi_name,
            "device_id": normalize_device_id(
                device_name=name,
                hostapi_name=hostapi_name,
                device_index=int(device_value),
            ),
        }
    target = str(device_value).strip().lower()
    for idx, dev in enumerate(devices):
        if int(dev["max_output_channels"]) <= 0:
            continue
        if target in str(dev["name"]).lower():
            hostapi_name = str(hostapis[int(dev["hostapi"])]["name"])
            name = str(dev["name"])
            return {
                "index": int(idx),
                "name": name,
                "hostapi_name": hostapi_name,
                "device_id": normalize_device_id(
                    device_name=name,
                    hostapi_name=hostapi_name,
                    device_index=int(idx),
                ),
            }
    return {
        "index": None,
        "name": str(device_value),
        "hostapi_name": "",
        "device_id": normalize_device_id(device_name=str(device_value), hostapi_name=""),
    }
def _run_bluetooth_preflight_or_fail(
    *,
    input_device: int | str | None,
    output_device: int | str | None,
    input_samplerate: int,
    playback_sample_rate: int,
    preflight_duration_sec: float,
    skip_bluetooth_preflight: bool,
) -> tuple[int | str | None, int | str | None, dict[str, object]]:
    if skip_bluetooth_preflight:
        return input_device, output_device, {"ran": False}
    should_run = should_run_bluetooth_preflight(
        input_device=input_device,
        output_device=output_device,
    )
    if not should_run:
        return input_device, output_device, {"ran": False}
    result = run_bluetooth_duplex_preflight(
        BluetoothPreflightConfig(
            input_device=input_device,
            output_device=output_device,
            preferred_input_samplerate=int(input_samplerate),
            preferred_output_samplerate=int(playback_sample_rate),
            duration_sec=float(preflight_duration_sec),
        )
    )
    if not result.passed:
        notes = "\n".join(f"- {x}" for x in result.notes) if result.notes else ""
        raise RuntimeError(
            "Bluetooth headset duplex preflight failed.\n"
            f"Reason: {result.failure_reason}\n"
            f"Input: {result.input_device_name!r}\n"
            f"Output: {result.output_device_name!r}\n"
            f"{notes}"
        )
    return (
        result.input_device_index,
        result.output_device_index,
        {
            "ran": True,
            "input_device_name": result.input_device_name,
            "output_device_name": result.output_device_name,
            "input_hostapi_name": result.input_hostapi_name,
            "output_hostapi_name": result.output_hostapi_name,
            "input_family_key": result.input_device_family_key,
            "output_family_key": result.output_device_family_key,
            "samplerate": result.samplerate,
        },
    )
def _normalize_for_hotwords(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", text)
    return text
def _looks_like_bad_hotword(term: str) -> bool:
    if not term:
        return True
    n = len(term)
    if n < 4 or n > 24:
        return True
    if term[0] in "的了在和与及并就也又把被将呢啊吗呀":
        return True
    if term[-1] in "的了在和与及并就也又呢啊吗呀":
        return True
    if re.fullmatch(r"[A-Za-z]+", term):
        return True
    if re.search(r"[A-Za-z]", term):
        if not re.fullmatch(r"[A-Za-z0-9一-龥]+", term):
            return True
    return False
def _split_text_to_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;：:\n\r]+", text)
    return [p.strip() for p in parts if p.strip()]
def _split_sentence_to_clauses(text: str) -> list[str]:
    parts = re.split(r"[，,、]+", text)
    return [p.strip() for p in parts if p.strip()]
def _score_hotword(term: str, whole_sentence: str) -> float:
    score = 0.0
    n = len(term)
    if 5 <= n <= 14:
        score += 5.0
    elif 4 <= n <= 18:
        score += 3.0
    else:
        score += 1.0
    if term == whole_sentence:
        score += 0.8
    if any(k in term for k in ["华为", "座舱", "车机", "微信", "周杰伦", "支付宝", "PPT", "bug"]):
        score += 2.0
    if any(k in term for k in ["技术小组", "智能座舱", "原型车", "红尾灯", "语音助手", "晚高峰"]):
        score += 2.0
    if re.search(r"\d", term):
        score += 0.8
    if _looks_like_bad_hotword(term):
        score -= 10.0
    return score
def _dedupe_by_containment(terms: list[str], max_terms: int) -> list[str]:
    kept: list[str] = []
    for term in terms:
        if any(term in existed for existed in kept if existed != term):
            continue
        kept.append(term)
        if len(kept) >= max_terms:
            break
    return kept
def _build_hotwords_from_lesson_text_local(
    lesson_text: str,
    *,
    max_terms: int = 20,
) -> list[str]:
    normalized_full = _normalize_for_hotwords(lesson_text)
    if not normalized_full:
        return []
    candidates: dict[str, float] = {}
    def add(term: str, whole_sentence: str = "") -> None:
        norm = _normalize_for_hotwords(term)
        if not norm or _looks_like_bad_hotword(norm):
            return
        score = _score_hotword(norm, _normalize_for_hotwords(whole_sentence or norm))
        old = candidates.get(norm)
        if old is None or score > old:
            candidates[norm] = score
    sentences = _split_text_to_sentences(lesson_text)
    for sent in sentences:
        sent_norm = _normalize_for_hotwords(sent)
        if not sent_norm:
            continue
        if 6 <= len(sent_norm) <= 20:
            add(sent_norm, sent_norm)
        clauses = _split_sentence_to_clauses(sent)
        for clause in clauses:
            clause_norm = _normalize_for_hotwords(clause)
            if 4 <= len(clause_norm) <= 16:
                add(clause_norm, sent_norm)
    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    ranked_terms = [k for k, _ in ranked]
    ranked_terms = _dedupe_by_containment(ranked_terms, max_terms=max_terms)
    return ranked_terms[:max_terms]
def _merge_hotwords(
    auto_terms: list[str],
    user_terms_raw: str,
    *,
    max_terms: int = 32,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    def add(term: str) -> None:
        norm = _normalize_for_hotwords(term)
        if not norm or _looks_like_bad_hotword(norm) or norm in seen:
            return
        seen.add(norm)
        merged.append(norm)
    for term in auto_terms:
        add(term)
    if user_terms_raw.strip():
        for term in re.split(r"[,，;\n]+", user_terms_raw):
            add(term)
    merged = sorted(merged, key=lambda x: (-len(x), x))
    merged = _dedupe_by_containment(merged, max_terms=max_terms)
    return merged[:max_terms]
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run shadowing realtime pipeline")
    parser.add_argument("--text-file", type=str, required=True)
    parser.add_argument("--lesson-base-dir", type=str, default="assets/lessons")
    parser.add_argument("--asr", type=str, default="sherpa", choices=["fake", "sherpa"])
    parser.add_argument("--output-device", type=str, default=None)
    parser.add_argument("--input-device", type=str, default=None)
    parser.add_argument("--input-samplerate", type=int, default=None)
    parser.add_argument(
        "--capture-backend",
        type=str,
        default="sounddevice",
        choices=["sounddevice", "soundcard"],
    )
    parser.add_argument("--bluetooth-offset-sec", type=float, default=0.28)
    parser.add_argument("--playback-latency", type=str, default="low")
    parser.add_argument("--playback-blocksize", type=int, default=512)
    parser.add_argument("--aligner-debug", action="store_true")
    parser.add_argument("--asr-debug-feed", action="store_true")
    parser.add_argument("--asr-debug-feed-every", type=int, default=20)
    parser.add_argument("--skip-bluetooth-preflight", action="store_true")
    parser.add_argument("--preflight-duration-sec", type=float, default=6.0)
    parser.add_argument("--tick-sleep-sec", type=float, default=0.02)
    parser.add_argument("--profile-path", type=str, default="runtime/device_profiles.json")
    parser.add_argument("--session-dir", type=str, default="runtime/latest_session")
    parser.add_argument("--event-logging", action="store_true")
    parser.add_argument("--startup-grace-sec", type=float, default=3.2)
    parser.add_argument("--low-confidence-hold-sec", type=float, default=2.2)
    parser.add_argument("--hotwords", type=str, default="")
    parser.add_argument("--hotwords-score", type=float, default=1.8)
    parser.add_argument("--disable-auto-hotwords", action="store_true")
    parser.add_argument("--print-hotwords", action="store_true")
    parser.add_argument(
        "--hotwords-source",
        type=str,
        default="qwen",
        choices=["qwen", "local", "none"],
        help="热词来源：qwen / local / none",
    )
    parser.add_argument(
        "--qwen-api-key",
        type=str,
        default=os.getenv("DASHSCOPE_API_KEY", ""),
        help="DashScope API Key，默认读环境变量 DASHSCOPE_API_KEY",
    )
    parser.add_argument(
        "--qwen-model",
        type=str,
        default=os.getenv("QWEN_CHAT_MODEL", "qwen-plus"),
        help="Qwen 模型名，默认 qwen-plus",
    )
    parser.add_argument("--qwen-max-hotwords", type=int, default=24, help="Qwen 提取热词最大数量")
    parser.add_argument("--force-bluetooth-long-session-mode", action="store_true")
    return parser
def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    text_path = Path(args.text_file).expanduser().resolve()
    if not text_path.exists():
        raise FileNotFoundError(f"Text file not found: {text_path}")
    lesson_text = text_path.read_text(encoding="utf-8").strip()
    if not lesson_text:
        raise ValueError(f"Text file is empty: {text_path}")
    lesson_id = slugify_filename_stem(text_path.stem)
    lesson_base_dir = Path(args.lesson_base_dir).resolve()
    lesson_dir = lesson_base_dir / lesson_id
    validate_lesson_assets(lesson_dir)
    manifest = load_manifest(lesson_dir)
    playback_sample_rate = int(manifest["sample_rate_out"])
    parsed_input_device = _parse_input_device_arg(args.input_device)
    parsed_output_device = _parse_output_device_arg(args.output_device)
    rec_cfg = pick_working_input_config(
        preferred_device=parsed_input_device if isinstance(parsed_input_device, int) else None,
        preferred_name_substring=parsed_input_device if isinstance(parsed_input_device, str) else None,
        preferred_rates=(
            [args.input_samplerate, 48000, 44100, 16000]
            if args.input_samplerate is not None
            else [48000, 44100, 16000]
        ),
    ) or {
        "device": parsed_input_device,
        "samplerate": args.input_samplerate or 48000,
    }
    if args.input_samplerate is not None:
        rec_cfg["samplerate"] = args.input_samplerate
    effective_input_device = rec_cfg["device"]
    effective_input_samplerate = int(rec_cfg["samplerate"])
    sherpa_paths = collect_sherpa_paths()
    if args.asr == "sherpa":
        validate_sherpa_paths(sherpa_paths)
    effective_input_device, effective_output_device, preflight_meta = _run_bluetooth_preflight_or_fail(
        input_device=effective_input_device,
        output_device=parsed_output_device,
        input_samplerate=effective_input_samplerate,
        playback_sample_rate=playback_sample_rate,
        preflight_duration_sec=float(args.preflight_duration_sec),
        skip_bluetooth_preflight=bool(args.skip_bluetooth_preflight),
    )
    input_info = _query_input_device_info(effective_input_device)
    output_info = _query_output_device_info(effective_output_device)
    if bool(preflight_meta.get("ran", False)):
        if str(preflight_meta.get("input_device_name", "")).strip():
            input_info["name"] = str(preflight_meta["input_device_name"])
        if str(preflight_meta.get("output_device_name", "")).strip():
            output_info["name"] = str(preflight_meta["output_device_name"])
        preflight_hostapi = str(preflight_meta.get("input_hostapi_name", "")).strip()
        if preflight_hostapi:
            input_info["hostapi_name"] = preflight_hostapi
            if not str(output_info.get("hostapi_name", "")).strip():
                output_info["hostapi_name"] = preflight_hostapi
    input_device_name = str(input_info.get("name", "unknown"))
    output_device_name = str(output_info.get("name", "unknown"))
    hostapi_name = str(input_info.get("hostapi_name", "") or output_info.get("hostapi_name", "") or "").strip()
    input_device_id = str(input_info.get("device_id", "")).strip()
    output_device_id = str(output_info.get("device_id", "")).strip()
    bluetooth_mode = bool(
        should_run_bluetooth_preflight(
            input_device=effective_input_device,
            output_device=effective_output_device,
        )
    )
    auto_hotwords: list[str] = []
    if not args.disable_auto_hotwords and args.hotwords_source != "none":
        if args.hotwords_source == "qwen":
            if args.qwen_api_key.strip():
                auto_hotwords = extract_hotwords_with_qwen(
                    lesson_text=lesson_text,
                    api_key=args.qwen_api_key.strip(),
                    model=args.qwen_model.strip(),
                    max_terms=int(args.qwen_max_hotwords),
                )
                if not auto_hotwords:
                    auto_hotwords = _build_hotwords_from_lesson_text_local(
                        lesson_text,
                        max_terms=min(20, int(args.qwen_max_hotwords)),
                    )
            else:
                auto_hotwords = _build_hotwords_from_lesson_text_local(
                    lesson_text,
                    max_terms=min(20, int(args.qwen_max_hotwords)),
                )
        elif args.hotwords_source == "local":
            auto_hotwords = _build_hotwords_from_lesson_text_local(
                lesson_text,
                max_terms=min(20, int(args.qwen_max_hotwords)),
            )
    merged_hotwords = _merge_hotwords(
        auto_terms=auto_hotwords,
        user_terms_raw=str(args.hotwords or ""),
        max_terms=max(16, min(32, int(args.qwen_max_hotwords))),
    )
    hotwords_str = "\n".join(merged_hotwords)
    if args.print_hotwords and merged_hotwords:
        for term in merged_hotwords:
    runtime = build_runtime(
        {
            "lesson_base_dir": str(lesson_base_dir),
            "playback": {
                "sample_rate": playback_sample_rate,
                "channels": 1,
                "device": effective_output_device,
                "latency": args.playback_latency,
                "blocksize": int(args.playback_blocksize),
                "bluetooth_output_offset_sec": float(args.bluetooth_offset_sec),
            },
            "capture": {
                "backend": str(args.capture_backend),
                "device_sample_rate": effective_input_samplerate,
                "target_sample_rate": 16000,
                "channels": 1,
                "device": effective_input_device,
                "dtype": "float32",
                "blocksize": 0,
                "latency": "low",
            },
            "asr": {
                "mode": args.asr,
                "tokens": sherpa_paths.get("tokens", ""),
                "encoder": sherpa_paths.get("encoder", ""),
                "decoder": sherpa_paths.get("decoder", ""),
                "joiner": sherpa_paths.get("joiner", ""),
                "sample_rate": 16000,
                "emit_partial_interval_sec": 0.08,
                "enable_endpoint": True,
                "debug_feed": bool(args.asr_debug_feed),
                "debug_feed_every_n_chunks": int(args.asr_debug_feed_every),
                "num_threads": 2,
                "provider": "cpu",
                "feature_dim": 80,
                "decoding_method": "greedy_search",
                "rule1_min_trailing_silence": 1.2,
                "rule2_min_trailing_silence": 0.8,
                "rule3_min_utterance_length": 12.0,
                "hotwords": hotwords_str,
                "hotwords_score": float(args.hotwords_score),
                "min_meaningful_text_len": 2,
                "endpoint_min_interval_sec": 0.35,
                "reset_on_empty_endpoint": False,
                "preserve_stream_on_partial_only": True,
                "force_reset_after_empty_endpoints": 999999999,
                "info_logging": True,
                "log_hotwords_on_start": True,
                "log_hotwords_preview_on_start": True,
                "hotwords_preview_limit": 12,
            },
            "alignment": {
                "window_back": 8,
                "window_ahead": 40,
                "stable_hits": 2,
                "min_confidence": 0.60,
                "debug": bool(args.aligner_debug),
            },
            "control": {
                "target_lead_sec": 0.18,
                "hold_if_lead_sec": 1.05,
                "resume_if_lead_sec": 0.36,
                "seek_if_lag_sec": -2.60,
                "min_confidence": 0.70,
                "seek_cooldown_sec": 2.20,
                "gain_following": 0.52,
                "gain_transition": 0.72,
                "gain_soft_duck": 0.36,
                "startup_grace_sec": float(args.startup_grace_sec),
                "low_confidence_hold_sec": float(args.low_confidence_hold_sec),
                "guide_play_sec": 3.20,
                "no_progress_hold_min_play_sec": 5.80,
                "progress_stale_sec": 1.45,
                "hold_trend_sec": 1.00,
                "tracking_quality_hold_min": 0.60,
                "tracking_quality_seek_min": 0.84,
                "resume_from_hold_speaking_lead_slack_sec": 0.72,
                "disable_seek": False,
                "bluetooth_long_session_target_lead_sec": 0.38,
                "bluetooth_long_session_hold_if_lead_sec": 1.35,
                "bluetooth_long_session_resume_if_lead_sec": 0.30,
                "bluetooth_long_session_seek_if_lag_sec": -3.20,
                "bluetooth_long_session_seek_cooldown_sec": 3.20,
                "bluetooth_long_session_progress_stale_sec": 1.75,
                "bluetooth_long_session_hold_trend_sec": 1.15,
                "bluetooth_long_session_tracking_quality_hold_min": 0.58,
                "bluetooth_long_session_tracking_quality_seek_min": 0.88,
                "bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec": 0.82,
                "bluetooth_long_session_gain_following": 0.50,
                "bluetooth_long_session_gain_transition": 0.66,
                "bluetooth_long_session_gain_soft_duck": 0.32,
            },
            "runtime": {
                "audio_queue_maxsize": 150,
                "asr_event_queue_maxsize": 64,
                "loop_interval_sec": float(args.tick_sleep_sec),
            },
            "signal": {
                "min_vad_rms": 0.006,
                "vad_noise_multiplier": 2.8,
            },
            "adaptation": {
                "profile_path": str(Path(args.profile_path).expanduser().resolve()),
            },
            "session": {
                "session_dir": str(Path(args.session_dir).expanduser().resolve()),
                "event_logging": bool(args.event_logging),
            },
            "device_context": {
                "input_device_name": input_device_name,
                "output_device_name": output_device_name,
                "input_device_id": input_device_id,
                "output_device_id": output_device_id,
                "hostapi_name": hostapi_name,
                "input_sample_rate": int(effective_input_samplerate),
                "output_sample_rate": int(playback_sample_rate),
                "noise_floor_rms": 0.0025,
                "bluetooth_mode": bluetooth_mode,
                "bluetooth_long_session_mode": bool(args.force_bluetooth_long_session_mode),
                "preflight_ran": bool(preflight_meta.get("ran", False)),
            },
            "debug": {
                "enabled": False,
            },
        }
    )
    runtime.run(lesson_id)
if __name__ == "__main__":
    main()
```

