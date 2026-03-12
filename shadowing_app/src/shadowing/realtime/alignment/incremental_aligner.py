from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from shadowing.interfaces.aligner import Aligner
from shadowing.types import AsrEvent, AsrEventType, AlignResult


@dataclass
class _RefTokenView:
    idx: int
    char: str
    pinyin: str
    t0: float


class IncrementalAligner(Aligner):
    """
    面向真人 partial 的增量对齐器。

    特点：
    - 支持轻微漏字 / 吞字
    - candidate 单调前进时可推动 committed
    - 支持 replay / rewind 搜索
    - 支持 replay lock-in：第二遍从头读时，允许 committed 切换到 replay 会话
    """

    def __init__(
        self,
        search_backoff_tokens: int = 12,
        search_ahead_tokens: int = 48,
        stable_min_advance: int = 2,
        fuzzy_missing_tolerance: int = 2,
        replay_head_tokens: int = 48,
        replay_trigger_max_chars: int = 12,
        replay_min_prefix_chars: int = 2,
        replay_min_committed_idx: int = 8,
        replay_lockin_min_run: int = 3,
        replay_lockin_confidence: float = 0.90,
    ) -> None:
        self.search_backoff_tokens = int(search_backoff_tokens)
        self.search_ahead_tokens = int(search_ahead_tokens)
        self.stable_min_advance = int(stable_min_advance)
        self.fuzzy_missing_tolerance = int(fuzzy_missing_tolerance)

        self.replay_head_tokens = int(replay_head_tokens)
        self.replay_trigger_max_chars = int(replay_trigger_max_chars)
        self.replay_min_prefix_chars = int(replay_min_prefix_chars)

        self.replay_min_committed_idx = int(replay_min_committed_idx)
        self.replay_lockin_min_run = int(replay_lockin_min_run)
        self.replay_lockin_confidence = float(replay_lockin_confidence)

        self.ref_map = None
        self.ref_tokens: list[_RefTokenView] = []

        self._committed_idx = 0
        self._candidate_idx = 0
        self._last_candidate_idx = 0
        self._last_candidate_run = 0

        self._head_norm = ""

        # replay 状态
        self._replay_active = False
        self._replay_run_len = 0
        self._replay_last_candidate = -1

    def reset(self, ref_map) -> None:
        self.ref_map = ref_map
        self.ref_tokens = []

        for i, tok in enumerate(ref_map.tokens):
            self.ref_tokens.append(
                _RefTokenView(
                    idx=i,
                    char=str(getattr(tok, "char", "")),
                    pinyin=str(getattr(tok, "pinyin", "")),
                    t0=self._extract_token_time(tok, fallback_index=i),
                )
            )

        self._committed_idx = 0
        self._candidate_idx = 0
        self._last_candidate_idx = 0
        self._last_candidate_run = 0

        self._replay_active = False
        self._replay_run_len = 0
        self._replay_last_candidate = -1

        self._head_norm = "".join(t.char for t in self.ref_tokens[: self.replay_head_tokens])

    def update(self, event: AsrEvent) -> AlignResult | None:
        if self.ref_map is None or not self.ref_tokens:
            return None

        if event.event_type not in (AsrEventType.PARTIAL, AsrEventType.FINAL):
            return None

        norm = event.normalized_text or ""
        py = event.pinyin_seq or []

        if not norm and not py:
            return None

        cand_idx, confidence, matched_text, replay_mode = self._locate_candidate(norm, py)

        stable = False

        # FINAL：只做前向提交，不做 replay 回退切换
        if event.event_type == AsrEventType.FINAL:
            self._clear_replay_if_needed(finalizing=True)
            if cand_idx >= self._committed_idx:
                self._committed_idx = cand_idx
                stable = True

        else:
            # 先处理 replay 会话
            if replay_mode and cand_idx < self._committed_idx:
                self._update_replay_state(cand_idx, confidence)

                if self._should_lockin_replay(cand_idx, confidence):
                    self._replay_active = True
                    self._committed_idx = cand_idx
                    stable = True
            else:
                # 一旦又回到 committed 后方，退出 replay 会话
                if cand_idx >= self._committed_idx:
                    self._clear_replay_if_needed(finalizing=False)

                if cand_idx > self._last_candidate_idx:
                    self._last_candidate_run += 1
                elif cand_idx == self._last_candidate_idx:
                    self._last_candidate_run += 1
                else:
                    self._last_candidate_run = 0

                if cand_idx >= self._committed_idx:
                    if confidence >= 0.70 and (cand_idx - self._committed_idx) >= self.stable_min_advance:
                        self._committed_idx = cand_idx
                        stable = True
                    elif confidence >= 0.90 and cand_idx > self._committed_idx:
                        self._committed_idx = cand_idx
                        stable = True
                    elif self._last_candidate_run >= 2 and confidence >= 0.80 and cand_idx >= self._committed_idx:
                        self._committed_idx = cand_idx
                        stable = True

        self._candidate_idx = cand_idx
        self._last_candidate_idx = cand_idx

        ref_time_sec = self._token_time(cand_idx)

        return AlignResult(
            committed_ref_idx=self._committed_idx,
            candidate_ref_idx=self._candidate_idx,
            ref_time_sec=ref_time_sec,
            confidence=confidence,
            stable=stable,
            matched_text=matched_text,
        )

    def _locate_candidate(self, norm: str, py: Sequence[str]) -> tuple[int, float, str, bool]:
        replay_mode = self._should_replay_search(norm, py)

        if replay_mode:
            start = 0
            end = min(len(self.ref_tokens) - 1, self.replay_head_tokens)
        else:
            start = max(0, self._committed_idx - self.search_backoff_tokens)
            end = min(len(self.ref_tokens) - 1, self._committed_idx + self.search_ahead_tokens)

        best_idx = self._committed_idx
        best_score = -1.0
        best_text = ""

        for i in range(start, end + 1):
            score, matched = self._score_at(i, norm, py)
            if score > best_score:
                best_score = score
                best_idx = i
                best_text = matched

        conf = max(0.0, min(1.0, best_score))
        return best_idx, conf, best_text, replay_mode

    def _should_replay_search(self, norm: str, py: Sequence[str]) -> bool:
        """
        当当前 partial 很短，并且明显像参考开头时，
        触发 replay / rewind 搜索。
        """
        if not norm:
            return False

        if self._committed_idx < self.replay_min_committed_idx:
            return False

        if len(norm) > self.replay_trigger_max_chars:
            return False

        head_prefix = self._head_norm[: max(self.replay_min_prefix_chars, min(len(norm), 8))]
        if head_prefix and norm.startswith(head_prefix[: min(len(head_prefix), len(norm))]):
            return True

        score = self._ordered_subsequence_score(norm, self._head_norm[: max(len(norm) + 4, 8)])
        return score >= 0.75

    def _update_replay_state(self, cand_idx: int, confidence: float) -> None:
        if cand_idx < 0:
            self._replay_run_len = 0
            self._replay_last_candidate = -1
            return

        if confidence < self.replay_lockin_confidence:
            self._replay_run_len = 0
            self._replay_last_candidate = cand_idx
            return

        if self._replay_last_candidate < 0:
            self._replay_run_len = 1
        elif cand_idx > self._replay_last_candidate:
            self._replay_run_len += 1
        elif cand_idx == self._replay_last_candidate:
            self._replay_run_len += 1
        else:
            self._replay_run_len = 1

        self._replay_last_candidate = cand_idx

    def _should_lockin_replay(self, cand_idx: int, confidence: float) -> bool:
        if cand_idx < 0:
            return False
        if cand_idx >= self._committed_idx:
            return False
        if confidence < self.replay_lockin_confidence:
            return False
        if self._replay_run_len < self.replay_lockin_min_run:
            return False
        return True

    def _clear_replay_if_needed(self, finalizing: bool) -> None:
        self._replay_active = False
        self._replay_run_len = 0
        self._replay_last_candidate = -1
        if finalizing:
            self._last_candidate_run = 0

    def _score_at(self, end_idx: int, norm: str, py: Sequence[str]) -> tuple[float, str]:
        if end_idx < 0 or end_idx >= len(self.ref_tokens):
            return 0.0, ""

        norm_len = len(norm)
        py_len = len(py)

        ref_window_len = max(norm_len, py_len, 1) + self.fuzzy_missing_tolerance
        start_idx = max(0, end_idx - ref_window_len + 1)
        ref_slice = self.ref_tokens[start_idx : end_idx + 1]

        ref_chars = "".join(tok.char for tok in ref_slice)
        ref_py = [tok.pinyin for tok in ref_slice]

        char_score, matched_chars = self._char_fuzzy_score(norm, ref_chars)
        py_score = self._pinyin_fuzzy_score(py, ref_py)

        if norm and py:
            score = 0.75 * char_score + 0.25 * py_score
        elif norm:
            score = char_score
        else:
            score = py_score

        return score, matched_chars

    def _char_fuzzy_score(self, user_norm: str, ref_chars: str) -> tuple[float, str]:
        if not user_norm or not ref_chars:
            return 0.0, ""

        best_score = 0.0
        best_match = ""

        min_len = max(1, len(user_norm) - self.fuzzy_missing_tolerance)
        max_len = min(len(ref_chars), len(user_norm) + self.fuzzy_missing_tolerance)

        for L in range(min_len, max_len + 1):
            cand = ref_chars[-L:]
            score = self._ordered_subsequence_score(user_norm, cand)
            if score > best_score:
                best_score = score
                best_match = cand

        return best_score, best_match

    def _pinyin_fuzzy_score(self, user_py: Sequence[str], ref_py: Sequence[str]) -> float:
        if not user_py or not ref_py:
            return 0.0

        min_len = max(1, len(user_py) - self.fuzzy_missing_tolerance)
        max_len = min(len(ref_py), len(user_py) + self.fuzzy_missing_tolerance)

        best_score = 0.0
        for L in range(min_len, max_len + 1):
            cand = ref_py[-L:]
            score = self._ordered_subsequence_score(list(user_py), list(cand))
            if score > best_score:
                best_score = score

        return best_score

    def _ordered_subsequence_score(self, a, b) -> float:
        if not a or not b:
            return 0.0

        i = 0
        j = 0
        matched = 0

        while i < len(a) and j < len(b):
            if a[i] == b[j]:
                matched += 1
                i += 1
                j += 1
            else:
                j += 1

        return matched / max(1, len(a))

    def _token_time(self, idx: int) -> float:
        idx = max(0, min(idx, len(self.ref_tokens) - 1))
        return self.ref_tokens[idx].t0

    def _extract_token_time(self, tok, fallback_index: int = 0) -> float:
        """
        兼容不同 RefToken 字段名；如果没有时间字段，就用 index 兜底，
        至少保证 t_user 单调递增，而不是一直 0.0。
        """
        for name in ("t0", "start_sec", "time_sec", "t_ref_sec", "start", "ts"):
            if hasattr(tok, name):
                try:
                    return float(getattr(tok, name))
                except Exception:
                    pass

        return float(fallback_index) * 0.08