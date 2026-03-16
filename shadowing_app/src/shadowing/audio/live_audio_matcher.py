from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

import numpy as np

from shadowing.audio.audio_feature_ring_buffer import AudioFeatureRingBuffer
from shadowing.audio.frame_feature_extractor import AudioFrameFeature
from shadowing.audio.reference_audio_features import ReferenceAudioFeatures
from shadowing.types import AudioMatchSnapshot


@dataclass(slots=True)
class _Candidate:
    idx: int
    env_score: float
    onset_score: float
    band_score: float
    embed_score: float
    stretch_factor: float
    total_score: float
    rank: int = 0


class LiveAudioMatcher:
    """
    改进点：
    1. 默认局部搜，低置信 / 大分歧时自动切 recovery 扩窗。
    2. 不再只围绕单一中心搜索，而是多中心候选 + 稀疏全局召回。
    3. 维持原接口，减少外部参数暴露。
    """

    def __init__(
        self,
        *,
        search_window_sec: float = 3.0,
        match_window_sec: float = 1.8,
        update_interval_sec: float = 0.12,
        min_frames_for_match: int = 20,
        ring_buffer_sec: float = 6.0,
    ) -> None:
        self.search_window_sec = float(search_window_sec)
        self.match_window_sec = float(match_window_sec)
        self.update_interval_sec = float(update_interval_sec)
        self.min_frames_for_match = max(8, int(min_frames_for_match))
        self.ring = AudioFeatureRingBuffer(max_duration_sec=ring_buffer_sec)

        self._stretch_factors = (0.94, 1.00, 1.06)
        self._dtw_top_k = 4
        self._dtw_band_ratio = 0.20
        self._recovery_window_sec = max(6.0, self.search_window_sec * 2.2)
        self._global_anchor_step_sec = 0.9

        self._ref_features: ReferenceAudioFeatures | None = None
        self._ref_times = np.zeros((0,), dtype=np.float32)
        self._ref_env = np.zeros((0,), dtype=np.float32)
        self._ref_onset = np.zeros((0,), dtype=np.float32)
        self._ref_band = np.zeros((0, 0), dtype=np.float32)
        self._ref_embed = np.zeros((0, 0), dtype=np.float32)
        self._boundary_times = np.zeros((0,), dtype=np.float32)
        self._global_anchor_indices = np.zeros((0,), dtype=np.int32)

        self._last_snapshot: AudioMatchSnapshot | None = None
        self._last_emit_at_sec = 0.0
        self._low_confidence_run = 0

    def reset(self, ref_features: ReferenceAudioFeatures, ref_map) -> None:
        _ = ref_map
        self._ref_features = ref_features
        self.ring.reset()
        self._last_snapshot = None
        self._last_emit_at_sec = 0.0
        self._low_confidence_run = 0

        self._ref_times = np.asarray([x.time_sec for x in ref_features.frames], dtype=np.float32)
        self._ref_env = np.asarray([x.envelope for x in ref_features.frames], dtype=np.float32)
        self._ref_onset = np.asarray([x.onset_strength for x in ref_features.frames], dtype=np.float32)

        if ref_features.frames and ref_features.frames[0].band_energy:
            self._ref_band = np.asarray([x.band_energy for x in ref_features.frames], dtype=np.float32)
        else:
            self._ref_band = np.zeros((len(ref_features.frames), 0), dtype=np.float32)

        if ref_features.frames and ref_features.frames[0].embedding:
            self._ref_embed = np.asarray([x.embedding for x in ref_features.frames], dtype=np.float32)
        else:
            self._ref_embed = np.zeros((len(ref_features.frames), 0), dtype=np.float32)

        self._boundary_times = np.asarray([float(x.time_sec) for x in ref_features.boundaries], dtype=np.float32)
        self._global_anchor_indices = self._build_global_anchor_indices()

    def feed_features(self, frames: list[AudioFrameFeature]) -> None:
        self.ring.append_many(frames)

    def snapshot(
        self,
        *,
        now_sec: float,
        progress_hint_ref_time_sec: float | None,
        playback_ref_time_sec: float | None,
        text_tracking_confidence: float,
    ) -> AudioMatchSnapshot | None:
        if self._ref_features is None or self._ref_env.size == 0:
            return None
        if self._last_snapshot is not None and (now_sec - self._last_emit_at_sec) < self.update_interval_sec:
            return self._last_snapshot

        live = self.ring.get_recent(self.match_window_sec)
        if len(live) < self.min_frames_for_match:
            return self._last_snapshot

        live_env = np.asarray([x.envelope for x in live], dtype=np.float32)
        live_onset = np.asarray([x.onset_strength for x in live], dtype=np.float32)
        live_band = (
            np.asarray([x.band_energy for x in live], dtype=np.float32)
            if live and live[0].band_energy
            else np.zeros((len(live), 0), dtype=np.float32)
        )
        live_embed = (
            np.asarray([x.embedding for x in live], dtype=np.float32)
            if live and live[0].embedding
            else np.zeros((len(live), 0), dtype=np.float32)
        )

        recovery_mode = self._should_enter_recovery(
            progress_hint_ref_time_sec=progress_hint_ref_time_sec,
            playback_ref_time_sec=playback_ref_time_sec,
            text_tracking_confidence=text_tracking_confidence,
        )

        centers = self._choose_search_centers(
            progress_hint_ref_time_sec=progress_hint_ref_time_sec,
            playback_ref_time_sec=playback_ref_time_sec,
            text_tracking_confidence=text_tracking_confidence,
            recovery_mode=recovery_mode,
        )

        candidates = self._search_candidates(
            live_env=live_env,
            live_onset=live_onset,
            live_band=live_band,
            live_embed=live_embed,
            center_time_secs=centers,
            recovery_mode=recovery_mode,
        )
        if not candidates:
            return self._last_snapshot

        best = candidates[0]
        dtw_score, dtw_cost, dtw_coverage, best_candidate_idx = self._refine_with_dtw(
            live_embed=live_embed,
            candidates=candidates,
            live_len=len(live),
        )
        if best_candidate_idx >= 0:
            best = next((c for c in candidates if c.idx == best_candidate_idx), best)

        rhythm_score = self._rhythm_consistency(live_onset, best.idx, len(live_onset))
        boundary_bonus = self._boundary_bonus(best.idx, len(live_onset))
        stretch_bonus = self._stretch_bonus(best.stretch_factor)

        local_similarity = max(
            0.0,
            min(
                1.0,
                0.22 * best.env_score
                + 0.14 * best.onset_score
                + 0.12 * best.band_score
                + 0.24 * best.embed_score
                + 0.14 * rhythm_score
                + 0.12 * dtw_score
                + 0.01 * boundary_bonus
                + 0.01 * stretch_bonus,
            ),
        )
        conf = float(max(0.0, min(1.0, 0.08 + 0.92 * local_similarity)))

        center_ref_idx = min(best.idx + max(0, len(live) // 2 - 1), len(self._ref_times) - 1)
        ref_time = float(self._ref_times[center_ref_idx])
        ref_idx_hint = self._time_to_ref_idx(ref_time)

        repeated_pattern_score = 0.0
        if progress_hint_ref_time_sec is not None:
            delta = float(progress_hint_ref_time_sec) - ref_time
            if 0.30 <= delta <= 2.60 and local_similarity >= 0.56:
                repeated_pattern_score = min(1.0, 0.35 * (delta / 2.60) + 0.65 * max(0.0, 1.0 - dtw_coverage))

        drift_sec = 0.0 if progress_hint_ref_time_sec is None else float(ref_time - progress_hint_ref_time_sec)

        mode = "tracking"
        if text_tracking_confidence < 0.42 and conf >= 0.62:
            mode = "bootstrap"
        if repeated_pattern_score >= 0.55:
            mode = "repeat"
        if (
            playback_ref_time_sec is not None
            and abs(ref_time - float(playback_ref_time_sec)) <= 0.60
            and text_tracking_confidence < 0.52
            and conf >= 0.58
        ):
            mode = "reentry"
        if recovery_mode and conf >= 0.60 and abs(drift_sec) >= 1.2:
            mode = "recovery"

        snap = AudioMatchSnapshot(
            estimated_ref_time_sec=ref_time,
            estimated_ref_idx_hint=int(ref_idx_hint),
            confidence=conf,
            local_similarity=float(local_similarity),
            envelope_alignment_score=float(best.env_score),
            onset_alignment_score=float(best.onset_score),
            band_alignment_score=float(best.band_score),
            rhythm_consistency_score=float(rhythm_score),
            repeated_pattern_score=float(repeated_pattern_score),
            drift_sec=float(drift_sec),
            mode=mode,
            emitted_at_sec=float(now_sec),
            dtw_cost=float(dtw_cost),
            dtw_path_score=float(dtw_score),
            dtw_coverage=float(dtw_coverage),
            coarse_candidate_rank=int(best.rank),
            time_offset_sec=float(drift_sec),
        )

        if conf < 0.56:
            self._low_confidence_run += 1
        else:
            self._low_confidence_run = 0

        self._last_snapshot = snap
        self._last_emit_at_sec = float(now_sec)
        return snap

    def _should_enter_recovery(
        self,
        *,
        progress_hint_ref_time_sec: float | None,
        playback_ref_time_sec: float | None,
        text_tracking_confidence: float,
    ) -> bool:
        if self._last_snapshot is None:
            return False
        if self._low_confidence_run >= 2:
            return True
        if self._last_snapshot.confidence < 0.54:
            return True
        if progress_hint_ref_time_sec is not None:
            if abs(self._last_snapshot.estimated_ref_time_sec - float(progress_hint_ref_time_sec)) >= 1.10:
                return True
        if playback_ref_time_sec is not None and text_tracking_confidence < 0.50:
            if abs(self._last_snapshot.estimated_ref_time_sec - float(playback_ref_time_sec)) >= 1.40:
                return True
        return False

    def _choose_search_centers(
        self,
        *,
        progress_hint_ref_time_sec: float | None,
        playback_ref_time_sec: float | None,
        text_tracking_confidence: float,
        recovery_mode: bool,
    ) -> list[float]:
        centers: list[float] = []

        def add(x: float | None) -> None:
            if x is None:
                return
            val = float(x)
            if any(abs(val - old) < 0.25 for old in centers):
                return
            centers.append(val)

        if progress_hint_ref_time_sec is not None:
            add(progress_hint_ref_time_sec)
        if self._last_snapshot is not None:
            add(self._last_snapshot.estimated_ref_time_sec)
        if playback_ref_time_sec is not None:
            add(playback_ref_time_sec)

        if text_tracking_confidence < 0.48 and playback_ref_time_sec is not None:
            add(float(playback_ref_time_sec) - 1.2)
            add(float(playback_ref_time_sec) + 1.0)

        if recovery_mode and self._ref_times.size > 0 and self._global_anchor_indices.size > 0:
            for idx in self._global_anchor_indices[: min(16, len(self._global_anchor_indices))]:
                add(float(self._ref_times[int(idx)]))

        if not centers:
            add(0.0)
        return centers

    def _search_candidates(
        self,
        *,
        live_env: np.ndarray,
        live_onset: np.ndarray,
        live_band: np.ndarray,
        live_embed: np.ndarray,
        center_time_secs: list[float],
        recovery_mode: bool,
    ) -> list[_Candidate]:
        ref_n = int(self._ref_env.shape[0])
        live_n = int(live_env.shape[0])
        if live_n <= 0 or ref_n < live_n or self._ref_times.size == 0:
            return []
        assert self._ref_features is not None

        radius_sec = self._recovery_window_sec if recovery_mode else self.search_window_sec
        radius_frames = max(live_n, int(round(radius_sec / max(1e-6, self._ref_features.frame_hop_sec))))

        windows: list[tuple[int, int]] = []
        for center_time_sec in center_time_secs:
            center_idx = int(np.searchsorted(self._ref_times, center_time_sec))
            center_start_idx = max(0, center_idx - live_n // 2)
            start = max(0, center_start_idx - radius_frames)
            end = min(ref_n - live_n, center_start_idx + radius_frames)
            if end >= start:
                windows.append((start, end))

        if recovery_mode and ref_n > live_n:
            step = max(8, int(round(self._global_anchor_step_sec / max(1e-6, self._ref_features.frame_hop_sec))))
            for anchor in range(0, ref_n - live_n, step):
                windows.append((anchor, min(ref_n - live_n, anchor + step)))

        windows = self._merge_windows(windows)
        scores: list[_Candidate] = []

        for stretch in self._stretch_factors:
            warped_env = self._time_warp_1d(live_env, target_len=live_n, stretch_factor=stretch)
            warped_onset = self._time_warp_1d(live_onset, target_len=live_n, stretch_factor=stretch)
            warped_band = self._time_warp_2d(live_band, target_len=live_n, stretch_factor=stretch)
            warped_embed = self._time_warp_2d(live_embed, target_len=live_n, stretch_factor=stretch)

            live_env_z = self._zscore(warped_env)
            live_onset_z = self._zscore(warped_onset)
            live_band_z = self._zscore_rows(warped_band)
            live_embed_z = self._zscore_rows(warped_embed)

            for start, end in windows:
                for idx in range(start, end + 1):
                    ref_env = self._ref_env[idx : idx + live_n]
                    ref_onset = self._ref_onset[idx : idx + live_n]
                    ref_band = self._ref_band[idx : idx + live_n] if self._ref_band.size > 0 else np.zeros((live_n, 0), dtype=np.float32)
                    ref_embed = self._ref_embed[idx : idx + live_n] if self._ref_embed.size > 0 else np.zeros((live_n, 0), dtype=np.float32)

                    env_score = self._corr(live_env_z, self._zscore(ref_env))
                    onset_score = self._corr(live_onset_z, self._zscore(ref_onset))
                    band_score = self._band_similarity(live_band_z, self._zscore_rows(ref_band))
                    embed_score = self._band_similarity(live_embed_z, self._zscore_rows(ref_embed))
                    boundary_bonus = self._boundary_bonus(idx, live_n)

                    total = 0.24 * env_score + 0.12 * onset_score + 0.14 * band_score + 0.42 * embed_score + 0.08 * boundary_bonus
                    scores.append(
                        _Candidate(
                            idx=idx,
                            env_score=float(env_score),
                            onset_score=float(onset_score),
                            band_score=float(band_score),
                            embed_score=float(embed_score),
                            stretch_factor=float(stretch),
                            total_score=float(total),
                        )
                    )

        scores.sort(key=lambda x: x.total_score, reverse=True)
        deduped: list[_Candidate] = []
        seen: set[int] = set()
        for cand in scores:
            bucket = int(cand.idx // max(4, live_n // 3))
            if bucket in seen:
                continue
            seen.add(bucket)
            deduped.append(cand)
            if len(deduped) >= max(self._dtw_top_k + 2, 8):
                break

        for i, cand in enumerate(deduped, start=1):
            cand.rank = i
        return deduped

    def _merge_windows(self, windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not windows:
            return []
        windows.sort()
        merged = [windows[0]]
        for s, e in windows[1:]:
            ls, le = merged[-1]
            if s <= le + 2:
                merged[-1] = (ls, max(le, e))
            else:
                merged.append((s, e))
        return merged

    def _build_global_anchor_indices(self) -> np.ndarray:
        if self._ref_times.size == 0:
            return np.zeros((0,), dtype=np.int32)
        total = float(self._ref_times[-1])
        step = max(0.6, self._global_anchor_step_sec)
        anchors: list[int] = []
        t = 0.0
        while t <= total:
            idx = int(np.searchsorted(self._ref_times, t))
            idx = max(0, min(idx, len(self._ref_times) - 1))
            anchors.append(idx)
            t += step
        return np.asarray(sorted(set(anchors)), dtype=np.int32)

    def _refine_with_dtw(
        self,
        *,
        live_embed: np.ndarray,
        candidates: list[_Candidate],
        live_len: int,
    ) -> tuple[float, float, float, int]:
        if live_embed.size == 0 or self._ref_embed.size == 0:
            best = candidates[0]
            return max(0.0, min(1.0, best.embed_score)), 0.0, 0.0, int(best.idx)

        best_score = -1.0
        best_cost = 1e9
        best_coverage = 0.0
        best_candidate_idx = -1

        for cand in candidates[: self._dtw_top_k]:
            lo = max(0, cand.idx - max(2, live_len // 6))
            hi = min(self._ref_embed.shape[0], cand.idx + live_len + max(2, live_len // 6))
            ref_seg = self._ref_embed[lo:hi]
            score, cost, coverage = self._constrained_dtw_similarity(live_embed, ref_seg)
            if score > best_score:
                best_score = score
                best_cost = cost
                best_coverage = coverage
                best_candidate_idx = int(cand.idx)

        return max(0.0, best_score), float(best_cost), float(best_coverage), best_candidate_idx

    def _constrained_dtw_similarity(self, live: np.ndarray, ref: np.ndarray) -> tuple[float, float, float]:
        n = int(live.shape[0])
        m = int(ref.shape[0])
        if n == 0 or m == 0:
            return 0.0, 1e9, 0.0
        band = max(2, int(round(max(n, m) * self._dtw_band_ratio)))
        dp = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
        dp[0, 0] = 0.0
        for i in range(1, n + 1):
            j0 = max(1, i - band)
            j1 = min(m, i + band + max(0, m - n))
            for j in range(j0, j1 + 1):
                cost = 1.0 - self._cosine(live[i - 1], ref[j - 1])
                dp[i, j] = cost + min(dp[i - 1, j], dp[i, j - 1], dp[i - 1, j - 1])
        end_j = int(np.argmin(dp[n, 1:])) + 1
        final_cost = float(dp[n, end_j])
        path_len = float(n + end_j)
        mean_cost = final_cost / max(1.0, path_len)
        score = max(0.0, min(1.0, 1.0 - mean_cost * 1.55))
        coverage = max(0.0, min(1.0, end_j / max(1, m)))
        return score, final_cost, coverage

    def _time_to_ref_idx(self, ref_time_sec: float) -> int:
        assert self._ref_features is not None
        hints = self._ref_features.token_time_hints_sec
        if not hints:
            return 0
        idx = bisect_right(hints, float(ref_time_sec)) - 1
        return max(0, min(idx, len(hints) - 1))

    def _rhythm_consistency(self, live_onset: np.ndarray, ref_start_idx: int, n: int) -> float:
        ref_onset = self._ref_onset[ref_start_idx : ref_start_idx + n]
        if live_onset.size <= 2 or ref_onset.size != live_onset.size:
            return 0.0
        live_peaks = np.where(live_onset >= max(1e-6, np.percentile(live_onset, 75)))[0]
        ref_peaks = np.where(ref_onset >= max(1e-6, np.percentile(ref_onset, 75)))[0]
        if live_peaks.size == 0 or ref_peaks.size == 0:
            return 0.0
        live_gaps = np.diff(live_peaks)
        ref_gaps = np.diff(ref_peaks)
        if live_gaps.size == 0 or ref_gaps.size == 0:
            return 0.55
        a = float(np.mean(live_gaps))
        b = float(np.mean(ref_gaps))
        if max(a, b) <= 1e-6:
            return 0.0
        return float(max(0.0, min(1.0, 1.0 - abs(a - b) / max(a, b))))

    def _boundary_bonus(self, ref_start_idx: int, n: int) -> float:
        if self._boundary_times.size == 0 or self._ref_times.size == 0:
            return 0.0
        center_idx = min(ref_start_idx + max(0, n // 2), len(self._ref_times) - 1)
        center_time = float(self._ref_times[center_idx])
        nearest = np.min(np.abs(self._boundary_times - center_time))
        radius = 0.24
        if nearest > radius:
            return 0.0
        return float(max(0.0, 1.0 - nearest / radius))

    def _stretch_bonus(self, stretch_factor: float) -> float:
        diff = abs(float(stretch_factor) - 1.0)
        return float(max(0.0, 1.0 - diff / 0.10))

    def _time_warp_1d(self, x: np.ndarray, *, target_len: int, stretch_factor: float) -> np.ndarray:
        if x.size == 0 or target_len <= 0:
            return np.zeros((0,), dtype=np.float32)
        src = np.asarray(x, dtype=np.float32).reshape(-1)
        src_len = src.shape[0]
        if src_len == target_len and abs(stretch_factor - 1.0) <= 1e-6:
            return src
        mid = (src_len - 1) * 0.5
        out_pos = np.arange(target_len, dtype=np.float32)
        base_pos = out_pos * (src_len - 1) / max(1, target_len - 1)
        warped_pos = mid + (base_pos - mid) / max(1e-6, stretch_factor)
        warped_pos = np.clip(warped_pos, 0.0, src_len - 1.0)
        lo = np.floor(warped_pos).astype(np.int32)
        hi = np.clip(lo + 1, 0, src_len - 1)
        frac = warped_pos - lo
        return ((1.0 - frac) * src[lo] + frac * src[hi]).astype(np.float32, copy=False)

    def _time_warp_2d(self, x: np.ndarray, *, target_len: int, stretch_factor: float) -> np.ndarray:
        arr = np.asarray(x, dtype=np.float32)
        if arr.size == 0 or target_len <= 0 or arr.ndim != 2:
            return np.zeros((target_len, 0), dtype=np.float32)
        cols = [self._time_warp_1d(arr[:, i], target_len=target_len, stretch_factor=stretch_factor) for i in range(arr.shape[1])]
        return np.stack(cols, axis=1).astype(np.float32, copy=False)

    def _corr(self, a: np.ndarray, b: np.ndarray) -> float:
        if a.size == 0 or b.size == 0 or a.size != b.size:
            return 0.0
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom <= 1e-8:
            return 0.0
        return float(max(0.0, min(1.0, (np.dot(a, b) / denom + 1.0) * 0.5)))

    def _band_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        if a.size == 0 or b.size == 0 or a.shape != b.shape:
            return 0.0
        diff = float(np.mean(np.abs(a - b)))
        return float(1.0 / (1.0 + diff))

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom <= 1e-8:
            return 0.0
        return float(max(-1.0, min(1.0, np.dot(a, b) / denom)))

    def _zscore(self, x: np.ndarray) -> np.ndarray:
        if x.size == 0:
            return x
        mu = float(np.mean(x))
        sigma = float(np.std(x))
        if sigma <= 1e-6:
            return x - mu
        return (x - mu) / sigma

    def _zscore_rows(self, x: np.ndarray) -> np.ndarray:
        if x.size == 0:
            return x
        mu = np.mean(x, axis=0, keepdims=True)
        sigma = np.std(x, axis=0, keepdims=True)
        sigma = np.where(sigma <= 1e-6, 1.0, sigma)
        return (x - mu) / sigma