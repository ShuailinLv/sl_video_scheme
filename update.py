shadowing_app/src/shadowing/training/datasets/build_bulk_runtime_frame_dump.py
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from shadowing.audio.reference_audio_features import ReferenceAudioFeatures
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.training.datasets.build_runtime_frame_dump import (
    DumpConfig,
    OfflineRuntimeLabeler,
    _load_reference_audio_features_from_json,
    load_reference_map,
    read_wav,
)


@dataclass(slots=True)
class BulkDumpConfig:
    sample_rate: int = 16000
    tick_sec: float = 0.03
    chunk_sec: float = 0.03
    target_lead_sec: float = 0.18
    use_synthetic_text_progress: bool = True

    # split
    split_strategy: str = "by_lesson_hash"  # by_lesson_hash / none
    train_ratio: float = 0.80
    valid_ratio: float = 0.10
    test_ratio: float = 0.10

    # save
    save_per_lesson: bool = True
    merge_all: bool = True


def _stable_hash01(text: str) -> float:
    h = 2166136261
    for ch in str(text):
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return float(h % 1_000_000) / 1_000_000.0


def _infer_split(lesson_id: str, cfg: BulkDumpConfig) -> str:
    if cfg.split_strategy == "none":
        return "all"
    x = _stable_hash01(lesson_id)
    train_cut = float(cfg.train_ratio)
    valid_cut = float(cfg.train_ratio + cfg.valid_ratio)
    if x < train_cut:
        return "train"
    if x < valid_cut:
        return "valid"
    return "test"


def _find_lesson_dirs(lessons_dir: Path) -> list[Path]:
    out: list[Path] = []
    if not lessons_dir.exists():
        return out
    for p in sorted(lessons_dir.iterdir()):
        if not p.is_dir():
            continue
        if (p / "reference_map.json").exists():
            out.append(p)
    return out


def _pick_wav_file(lesson_dir: Path) -> Path | None:
    preferred = [
        lesson_dir / "reference.wav",
        lesson_dir / "lesson.wav",
        lesson_dir / "tts.wav",
        lesson_dir / "audio.wav",
    ]
    for p in preferred:
        if p.exists():
            return p

    chunks_dir = lesson_dir / "chunks"
    if chunks_dir.exists() and chunks_dir.is_dir():
        wavs = sorted(chunks_dir.glob("*.wav"))
        if len(wavs) == 1:
            return wavs[0]

    wavs = sorted(lesson_dir.glob("*.wav"))
    if wavs:
        return wavs[0]
    return None


def _load_ref_audio_features_for_lesson(
    lesson_id: str,
    lesson_dir: Path,
    store_base_dir: Path | None,
) -> ReferenceAudioFeatures:
    if store_base_dir is not None:
        store = ReferenceAudioStore(str(store_base_dir))
        if store.exists(lesson_id):
            return store.load(lesson_id)

    candidate = lesson_dir / "reference_audio_features.json"
    if candidate.exists():
        data = json.loads(candidate.read_text(encoding="utf-8"))
        return _load_reference_audio_features_from_json(data)

    raise FileNotFoundError(
        f"reference_audio_features.json not found for lesson={lesson_id}. "
        f"Tried store_base_dir={store_base_dir} and lesson_dir={lesson_dir}"
    )


def _make_dump_config(args: argparse.Namespace) -> DumpConfig:
    return DumpConfig(
        sample_rate=int(args.sample_rate),
        tick_sec=float(args.tick_sec),
        chunk_sec=float(args.chunk_sec),
        target_lead_sec=float(args.target_lead_sec),
        use_synthetic_text_progress=not bool(args.no_synthetic_text_progress),
    )


def _make_bulk_config(args: argparse.Namespace) -> BulkDumpConfig:
    train_ratio = float(args.train_ratio)
    valid_ratio = float(args.valid_ratio)
    test_ratio = float(args.test_ratio)
    total = train_ratio + valid_ratio + test_ratio
    if total <= 0:
        raise ValueError("train_ratio + valid_ratio + test_ratio must be > 0")
    train_ratio /= total
    valid_ratio /= total
    test_ratio /= total
    return BulkDumpConfig(
        sample_rate=int(args.sample_rate),
        tick_sec=float(args.tick_sec),
        chunk_sec=float(args.chunk_sec),
        target_lead_sec=float(args.target_lead_sec),
        use_synthetic_text_progress=not bool(args.no_synthetic_text_progress),
        split_strategy=str(args.split_strategy),
        train_ratio=float(train_ratio),
        valid_ratio=float(valid_ratio),
        test_ratio=float(test_ratio),
        save_per_lesson=not bool(args.no_save_per_lesson),
        merge_all=not bool(args.no_merge_all),
    )


def _save_df(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _concat_or_empty(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _summary_counter(df: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in df.columns or df.empty:
        return {}
    vc = df[column].value_counts(dropna=False)
    return {str(k): int(v) for k, v in vc.items()}


def _run_one_lesson(
    *,
    lesson_dir: Path,
    lesson_id: str,
    ref_audio_store_dir: Path | None,
    dump_cfg: DumpConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ref_map_path = lesson_dir / "reference_map.json"
    if not ref_map_path.exists():
        raise FileNotFoundError(f"reference_map.json missing: {ref_map_path}")

    wav_path = _pick_wav_file(lesson_dir)
    if wav_path is None:
        raise FileNotFoundError(f"No wav found for lesson: {lesson_dir}")

    ref_map = load_reference_map(ref_map_path)
    ref_audio_features = _load_ref_audio_features_for_lesson(
        lesson_id=lesson_id,
        lesson_dir=lesson_dir,
        store_base_dir=ref_audio_store_dir,
    )
    wav, sr = read_wav(wav_path)

    labeler = OfflineRuntimeLabeler(
        ref_map=ref_map,
        ref_audio_features=ref_audio_features,
        config=dump_cfg,
    )
    frame_df, behavior_df, fusion_df, action_df = labeler.run(
        lesson_id=lesson_id,
        wav=wav,
        sample_rate=sr,
    )

    meta = {
        "lesson_id": lesson_id,
        "lesson_dir": str(lesson_dir),
        "wav_path": str(wav_path),
        "ref_map_path": str(ref_map_path),
        "n_frame_rows": int(len(frame_df)),
        "n_behavior_rows": int(len(behavior_df)),
        "n_fusion_rows": int(len(fusion_df)),
        "n_action_rows": int(len(action_df)),
        "state_name_counter": _summary_counter(frame_df, "state_name"),
        "teacher_action_counter": _summary_counter(frame_df, "teacher_action"),
        "posterior_action_counter": _summary_counter(frame_df, "posterior_best_action"),
    }
    return frame_df, behavior_df, fusion_df, action_df, meta


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build runtime-in-the-loop parquet dumps for all lessons under a lessons directory."
    )
    p.add_argument("--lessons-dir", type=str, required=True)
    p.add_argument("--out-dir", type=str, required=True)
    p.add_argument(
        "--ref-audio-store-dir",
        type=str,
        default=None,
        help="Base dir for ReferenceAudioStore. Optional. "
        "If omitted, each lesson_dir/reference_audio_features.json is used.",
    )

    p.add_argument("--sample-rate", type=int, default=16000)
    p.add_argument("--tick-sec", type=float, default=0.03)
    p.add_argument("--chunk-sec", type=float, default=0.03)
    p.add_argument("--target-lead-sec", type=float, default=0.18)
    p.add_argument("--no-synthetic-text-progress", action="store_true")

    p.add_argument("--split-strategy", type=str, default="by_lesson_hash", choices=["by_lesson_hash", "none"])
    p.add_argument("--train-ratio", type=float, default=0.80)
    p.add_argument("--valid-ratio", type=float, default=0.10)
    p.add_argument("--test-ratio", type=float, default=0.10)

    p.add_argument("--limit", type=int, default=0, help="Only process first N lessons. 0 means all.")
    p.add_argument("--lesson-id-filter", type=str, default="", help="Only process lessons whose folder name contains this substring.")
    p.add_argument("--strict", action="store_true", help="Fail immediately on a lesson error.")
    p.add_argument("--no-save-per-lesson", action="store_true")
    p.add_argument("--no-merge-all", action="store_true")
    return p


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    lessons_dir = Path(args.lessons_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    ref_audio_store_dir = (
        None if args.ref_audio_store_dir in (None, "", "none", "null")
        else Path(args.ref_audio_store_dir).expanduser().resolve()
    )

    if not lessons_dir.exists():
        raise FileNotFoundError(f"lessons_dir not found: {lessons_dir}")

    dump_cfg = _make_dump_config(args)
    bulk_cfg = _make_bulk_config(args)

    lesson_dirs = _find_lesson_dirs(lessons_dir)
    lesson_filter = str(args.lesson_id_filter or "").strip().lower()
    if lesson_filter:
        lesson_dirs = [p for p in lesson_dirs if lesson_filter in p.name.lower()]
    if int(args.limit) > 0:
        lesson_dirs = lesson_dirs[: int(args.limit)]

    if not lesson_dirs:
        raise RuntimeError(f"No lesson directories found under: {lessons_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    per_lesson_dir = out_dir / "per_lesson"
    merged_dir = out_dir / "merged"

    all_frame: list[pd.DataFrame] = []
    all_behavior: list[pd.DataFrame] = []
    all_fusion: list[pd.DataFrame] = []
    all_action: list[pd.DataFrame] = []

    split_frame: dict[str, list[pd.DataFrame]] = {"train": [], "valid": [], "test": [], "all": []}
    split_behavior: dict[str, list[pd.DataFrame]] = {"train": [], "valid": [], "test": [], "all": []}
    split_fusion: dict[str, list[pd.DataFrame]] = {"train": [], "valid": [], "test": [], "all": []}
    split_action: dict[str, list[pd.DataFrame]] = {"train": [], "valid": [], "test": [], "all": []}

    lesson_metas: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for lesson_dir in lesson_dirs:
        lesson_id = lesson_dir.name
        split_name = _infer_split(lesson_id, bulk_cfg)

        try:
            frame_df, behavior_df, fusion_df, action_df, meta = _run_one_lesson(
                lesson_dir=lesson_dir,
                lesson_id=lesson_id,
                ref_audio_store_dir=ref_audio_store_dir,
                dump_cfg=dump_cfg,
            )

            frame_df["dataset_split"] = split_name
            behavior_df["dataset_split"] = split_name
            fusion_df["dataset_split"] = split_name
            action_df["dataset_split"] = split_name

            meta["dataset_split"] = split_name
            lesson_metas.append(meta)

            if bulk_cfg.save_per_lesson:
                dst = per_lesson_dir / lesson_id
                _save_df(frame_df, dst / "frame_dump.parquet")
                _save_df(behavior_df, dst / "behavior_train.parquet")
                _save_df(fusion_df, dst / "fusion_train.parquet")
                _save_df(action_df, dst / "action_train.parquet")
                (dst / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            all_frame.append(frame_df)
            all_behavior.append(behavior_df)
            all_fusion.append(fusion_df)
            all_action.append(action_df)

            split_frame[split_name].append(frame_df)
            split_behavior[split_name].append(behavior_df)
            split_fusion[split_name].append(fusion_df)
            split_action[split_name].append(action_df)

            split_frame["all"].append(frame_df)
            split_behavior["all"].append(behavior_df)
            split_fusion["all"].append(fusion_df)
            split_action["all"].append(action_df)

        except Exception as e:
            err = {
                "lesson_id": lesson_id,
                "lesson_dir": str(lesson_dir),
                "error": repr(e),
            }
            errors.append(err)
            if args.strict:
                raise

    if bulk_cfg.merge_all:
        merged_dir.mkdir(parents=True, exist_ok=True)

        full_frame = _concat_or_empty(all_frame)
        full_behavior = _concat_or_empty(all_behavior)
        full_fusion = _concat_or_empty(all_fusion)
        full_action = _concat_or_empty(all_action)

        if not full_frame.empty:
            _save_df(full_frame, merged_dir / "frame_dump.all.parquet")
        if not full_behavior.empty:
            _save_df(full_behavior, merged_dir / "behavior_train.all.parquet")
        if not full_fusion.empty:
            _save_df(full_fusion, merged_dir / "fusion_train.all.parquet")
        if not full_action.empty:
            _save_df(full_action, merged_dir / "action_train.all.parquet")

        for split_name in ("train", "valid", "test"):
            s_frame = _concat_or_empty(split_frame[split_name])
            s_behavior = _concat_or_empty(split_behavior[split_name])
            s_fusion = _concat_or_empty(split_fusion[split_name])
            s_action = _concat_or_empty(split_action[split_name])

            if not s_frame.empty:
                _save_df(s_frame, merged_dir / f"frame_dump.{split_name}.parquet")
            if not s_behavior.empty:
                _save_df(s_behavior, merged_dir / f"behavior_train.{split_name}.parquet")
            if not s_fusion.empty:
                _save_df(s_fusion, merged_dir / f"fusion_train.{split_name}.parquet")
            if not s_action.empty:
                _save_df(s_action, merged_dir / f"action_train.{split_name}.parquet")

    summary = {
        "lessons_dir": str(lessons_dir),
        "out_dir": str(out_dir),
        "ref_audio_store_dir": None if ref_audio_store_dir is None else str(ref_audio_store_dir),
        "dump_config": asdict(dump_cfg),
        "bulk_config": asdict(bulk_cfg),
        "n_lessons_found": int(len(lesson_dirs)),
        "n_lessons_succeeded": int(len(lesson_metas)),
        "n_lessons_failed": int(len(errors)),
        "errors": errors,
        "lessons": lesson_metas,
        "aggregate": {
            "frame_rows": int(sum(x.get("n_frame_rows", 0) for x in lesson_metas)),
            "behavior_rows": int(sum(x.get("n_behavior_rows", 0) for x in lesson_metas)),
            "fusion_rows": int(sum(x.get("n_fusion_rows", 0) for x in lesson_metas)),
            "action_rows": int(sum(x.get("n_action_rows", 0) for x in lesson_metas)),
            "split_counter": {
                "train": int(sum(1 for x in lesson_metas if x.get("dataset_split") == "train")),
                "valid": int(sum(1 for x in lesson_metas if x.get("dataset_split") == "valid")),
                "test": int(sum(1 for x in lesson_metas if x.get("dataset_split") == "test")),
                "all": int(len(lesson_metas)),
            },
            "teacher_action_counter": _merge_counters(
                [x.get("teacher_action_counter", {}) for x in lesson_metas]
            ),
            "posterior_action_counter": _merge_counters(
                [x.get("posterior_action_counter", {}) for x in lesson_metas]
            ),
            "state_name_counter": _merge_counters(
                [x.get("state_name_counter", {}) for x in lesson_metas]
            ),
        },
    }

    (out_dir / "bulk_meta.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _merge_counters(items: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in items:
        for k, v in dict(d).items():
            out[str(k)] = out.get(str(k), 0) + int(v)
    return out


if __name__ == "__main__":
    main()

shadowing_app/src/shadowing/training/datasets/build_runtime_frame_dump.py
from __future__ import annotations

import argparse
import json
import math
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import soundfile as sf
except Exception:  # pragma: no cover
    sf = None

from shadowing.audio.frame_feature_extractor import (
    AudioFrameFeature,
    FrameFeatureExtractor,
)
from shadowing.audio.live_audio_matcher import LiveAudioMatcher
from shadowing.audio.reference_audio_features import ReferenceAudioFeatures
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.audio.audio_behavior_classifier import AudioBehaviorClassifier
from shadowing.fusion.evidence_fuser import EvidenceFuser
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.audio_aware_progress_estimator import AudioAwareProgressEstimator
from shadowing.realtime.sync_evidence import SyncEvidenceBuilder
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.tracking.tracking_engine import TrackingEngine
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.types import (
    ControlAction,
    PlaybackState,
    PlaybackStatus,
    RefToken,
    ReferenceMap,
)


# ============================================================================
# 配置
# ============================================================================


@dataclass(slots=True)
class DumpConfig:
    sample_rate: int = 16000
    tick_sec: float = 0.03
    chunk_sec: float = 0.03
    frame_size_sec: float = 0.025
    hop_sec: float = 0.010
    matcher_update_interval_sec: float = 0.12
    matcher_search_window_sec: float = 3.0
    matcher_match_window_sec: float = 1.8
    matcher_min_frames_for_match: int = 20
    ring_buffer_sec: float = 6.0

    # 离线 playback 模拟
    initial_playback_state: str = "playing"
    initial_playback_gain: float = 1.0
    bluetooth_output_offset_sec: float = 0.0
    target_lead_sec: float = 0.18

    # 合成“文本/进度 teacher”轨
    use_synthetic_text_progress: bool = True
    text_progress_noise_std_sec: float = 0.06
    text_progress_drop_prob: float = 0.04
    text_progress_lag_sec: float = 0.20

    # action posterior labeler
    posterior_horizon_sec: float = 1.80
    posterior_seek_grid_sec: float = 0.20

    # 输出
    save_frame_dump: bool = True
    save_behavior_table: bool = True
    save_fusion_table: bool = True
    save_action_table: bool = True


# ============================================================================
# 轻量播放状态 / 决策模拟
# ============================================================================


@dataclass(slots=True)
class SimPlayback:
    state: PlaybackState
    t_ref_heard_content_sec: float
    t_ref_emitted_content_sec: float
    t_ref_block_start_content_sec: float
    t_ref_block_end_content_sec: float
    t_host_output_sec: float
    chunk_id: int = 0
    frame_index: int = 0
    gain: float = 1.0
    generation: int = 0

    def to_status(self) -> PlaybackStatus:
        return PlaybackStatus(
            state=self.state,
            chunk_id=int(self.chunk_id),
            frame_index=int(self.frame_index),
            gain=float(self.gain),
            generation=int(self.generation),
            t_host_output_sec=float(self.t_host_output_sec),
            t_ref_block_start_content_sec=float(self.t_ref_block_start_content_sec),
            t_ref_block_end_content_sec=float(self.t_ref_block_end_content_sec),
            t_ref_emitted_content_sec=float(self.t_ref_emitted_content_sec),
            t_ref_heard_content_sec=float(self.t_ref_heard_content_sec),
        )


# ============================================================================
# 伪文本 teacher：没有日志时，靠 reference time 合成 text/progress 轨
# ============================================================================


@dataclass(slots=True)
class SyntheticProgressSnapshot:
    estimated_ref_idx: int
    estimated_ref_time_sec: float
    tracking_quality: float
    confidence: float
    joint_confidence: float
    stable: bool
    recently_progressed: bool
    active_speaking: bool
    progress_age_sec: float
    tracking_mode: Any
    position_source: str
    source_candidate_ref_idx: int
    source_committed_ref_idx: int
    user_state: Any


class SyntheticTextProgressTeacher:
    """
    没有真实 ASR / tracking 日志时，用 reference time 构一个近似 text teacher。
    它不是最终真值，只是让 fusion/action 数据有 text 分支可学。
    """

    def __init__(
        self,
        ref_map: ReferenceMap,
        *,
        lag_sec: float = 0.20,
        noise_std_sec: float = 0.06,
        drop_prob: float = 0.04,
        rng_seed: int = 20260317,
    ) -> None:
        self.ref_map = ref_map
        self.lag_sec = float(lag_sec)
        self.noise_std_sec = float(noise_std_sec)
        self.drop_prob = float(drop_prob)
        self.rng = np.random.default_rng(rng_seed)
        self._last_time_sec = -9999.0
        self._last_idx = 0

    def snapshot(
        self,
        *,
        now_sec: float,
        gt_ref_time_sec: float,
        signal_like: float,
    ) -> SyntheticProgressSnapshot | None:
        if not self.ref_map.tokens:
            return None

        if self.rng.random() < self.drop_prob:
            return None

        jitter = float(self.rng.normal(0.0, self.noise_std_sec))
        text_time = max(0.0, float(gt_ref_time_sec) - self.lag_sec + jitter)

        idx = time_to_ref_idx(self.ref_map, text_time)
        token_time = float(self.ref_map.tokens[idx].t_start)

        progressed = idx > self._last_idx
        if progressed:
            self._last_time_sec = now_sec
            self._last_idx = idx

        if self._last_time_sec > 0.0:
            progress_age_sec = max(0.0, now_sec - self._last_time_sec)
        else:
            progress_age_sec = 9999.0

        tracking_quality = float(max(0.0, min(1.0, 0.70 + 0.18 * signal_like + self.rng.normal(0.0, 0.05))))
        confidence = float(max(0.0, min(1.0, 0.68 + 0.16 * signal_like + self.rng.normal(0.0, 0.05))))
        joint_confidence = float(max(0.0, min(1.0, 0.66 + 0.18 * signal_like + self.rng.normal(0.0, 0.05))))
        stable = bool(tracking_quality >= 0.72 and confidence >= 0.68)
        recently_progressed = bool(progress_age_sec <= 0.90)
        active_speaking = bool(signal_like >= 0.45 or recently_progressed)

        # 尽量与现有运行时字段兼容
        from shadowing.types import TrackingMode, UserReadState

        if tracking_quality >= 0.76:
            tracking_mode = TrackingMode.LOCKED
        elif tracking_quality >= 0.56:
            tracking_mode = TrackingMode.WEAK_LOCKED
        else:
            tracking_mode = TrackingMode.REACQUIRING

        if recently_progressed and tracking_quality >= 0.60:
            user_state = UserReadState.FOLLOWING
        elif active_speaking:
            user_state = UserReadState.HESITATING
        else:
            user_state = UserReadState.WARMING_UP

        return SyntheticProgressSnapshot(
            estimated_ref_idx=int(idx),
            estimated_ref_time_sec=float(token_time),
            tracking_quality=float(tracking_quality),
            confidence=float(confidence),
            joint_confidence=float(joint_confidence),
            stable=bool(stable),
            recently_progressed=bool(recently_progressed),
            active_speaking=bool(active_speaking),
            progress_age_sec=float(progress_age_sec),
            tracking_mode=tracking_mode,
            position_source="text",
            source_candidate_ref_idx=int(idx),
            source_committed_ref_idx=int(idx),
            user_state=user_state,
        )


# ============================================================================
# posterior action labeler
# 这是“更像真实业务标签”的关键位置
# ============================================================================


class PosteriorActionLabeler:
    """
    给当前 tick 枚举动作，并看未来 horizon 的“后验收益”。
    当前先给一版可跑骨架：
    - 评分主要基于未来窗口内对 gt_ref_time 的对齐误差
    - hold / seek 有额外惩罚
    - 后面你可以继续把 controller 内部动态模拟做得更细
    """

    ACTIONS = ("noop", "soft_duck", "hold", "resume", "seek")

    def __init__(
        self,
        *,
        horizon_sec: float = 1.80,
        seek_grid_sec: float = 0.20,
        target_lead_sec: float = 0.18,
    ) -> None:
        self.horizon_sec = float(horizon_sec)
        self.seek_grid_sec = float(seek_grid_sec)
        self.target_lead_sec = float(target_lead_sec)

    def label(
        self,
        *,
        frame_df: pd.DataFrame,
        row_idx: int,
    ) -> dict[str, Any]:
        row = frame_df.iloc[row_idx]
        t0 = float(row["t_sec"])
        horizon_end = t0 + self.horizon_sec
        fut = frame_df[(frame_df["t_sec"] >= t0) & (frame_df["t_sec"] <= horizon_end)].copy()
        if fut.empty:
            return {
                "posterior_best_action": str(row.get("teacher_action", "noop")),
                "posterior_reward_noop": 0.0,
                "posterior_reward_soft_duck": 0.0,
                "posterior_reward_hold": 0.0,
                "posterior_reward_resume": 0.0,
                "posterior_reward_seek": 0.0,
            }

        rewards: dict[str, float] = {}
        for action in self.ACTIONS:
            rewards[action] = self._score_action(row=row, future_df=fut, action=action)

        best_action = max(rewards.items(), key=lambda kv: kv[1])[0]
        return {
            "posterior_best_action": best_action,
            "posterior_reward_noop": float(rewards["noop"]),
            "posterior_reward_soft_duck": float(rewards["soft_duck"]),
            "posterior_reward_hold": float(rewards["hold"]),
            "posterior_reward_resume": float(rewards["resume"]),
            "posterior_reward_seek": float(rewards["seek"]),
        }

    def _score_action(
        self,
        *,
        row: pd.Series,
        future_df: pd.DataFrame,
        action: str,
    ) -> float:
        gt = future_df["gt_ref_time_sec"].to_numpy(dtype=np.float32)
        teacher_fused = future_df["teacher_fused_ref_time_sec"].to_numpy(dtype=np.float32)
        playback = future_df["playback_ref_time_sec"].to_numpy(dtype=np.float32)

        if gt.size == 0:
            return 0.0

        # baseline：当前系统未来轨迹
        baseline_err = float(np.mean(np.abs(playback - self.target_lead_sec - gt)))

        # 粗略模拟 action 对未来 playback 的影响
        simulated = playback.copy()

        if action == "hold":
            simulated[:] = simulated[0]
        elif action == "soft_duck":
            simulated = simulated - 0.15
        elif action == "resume":
            simulated = simulated + 0.08
        elif action == "seek":
            target = max(0.0, float(row.get("teacher_fused_ref_time_sec", row.get("gt_ref_time_sec", 0.0))) + self.target_lead_sec)
            simulated[:] = target
        elif action == "noop":
            pass

        err = float(np.mean(np.abs(simulated - self.target_lead_sec - gt)))
        reward = -err

        # 额外业务偏好
        if action == "hold":
            active_ratio = float(np.mean(future_df["teacher_still_following"].to_numpy(dtype=np.float32) >= 0.60))
            reward -= 0.80 * active_ratio
        if action == "seek":
            repeated_ratio = float(np.mean(future_df["teacher_repeated"].to_numpy(dtype=np.float32) >= 0.55))
            reward -= 1.00 * repeated_ratio
        if action == "resume":
            paused_ratio = float(np.mean(future_df["teacher_paused"].to_numpy(dtype=np.float32) >= 0.60))
            reward -= 0.45 * paused_ratio
        if action == "soft_duck":
            reward -= 0.08
        if action == "seek":
            reward -= 0.30

        # 相对 baseline 改善
        reward += 0.65 * (baseline_err - err)
        return float(reward)


# ============================================================================
# 主离线标注器
# ============================================================================


class OfflineRuntimeLabeler:
    def __init__(
        self,
        *,
        ref_map: ReferenceMap,
        ref_audio_features: ReferenceAudioFeatures,
        config: DumpConfig,
    ) -> None:
        self.ref_map = ref_map
        self.ref_audio_features = ref_audio_features
        self.cfg = config

        self.signal_monitor = SignalQualityMonitor()
        self.feature_extractor = FrameFeatureExtractor(
            sample_rate=int(self.cfg.sample_rate),
            frame_size_sec=float(self.cfg.frame_size_sec),
            hop_sec=float(self.cfg.hop_sec),
        )

        self.live_audio_matcher = LiveAudioMatcher(
            search_window_sec=float(self.cfg.matcher_search_window_sec),
            match_window_sec=float(self.cfg.matcher_match_window_sec),
            update_interval_sec=float(self.cfg.matcher_update_interval_sec),
            min_frames_for_match=int(self.cfg.matcher_min_frames_for_match),
            ring_buffer_sec=float(self.cfg.ring_buffer_sec),
        )
        self.live_audio_matcher.reset(ref_audio_features, ref_map)

        self.audio_behavior_classifier = AudioBehaviorClassifier()
        self.evidence_fuser = EvidenceFuser()
        self.sync_builder = SyncEvidenceBuilder()

        self.controller = StateMachineController(
            policy=ControlPolicy(),
            disable_seek=False,
            debug=False,
        )
        self.controller.reset()

        # text 轨 teacher
        self.synthetic_text_teacher = SyntheticTextProgressTeacher(
            ref_map=ref_map,
            lag_sec=float(self.cfg.text_progress_lag_sec),
            noise_std_sec=float(self.cfg.text_progress_noise_std_sec),
            drop_prob=float(self.cfg.text_progress_drop_prob),
        )

        # posterior action teacher
        self.posterior_labeler = PosteriorActionLabeler(
            horizon_sec=float(self.cfg.posterior_horizon_sec),
            seek_grid_sec=float(self.cfg.posterior_seek_grid_sec),
            target_lead_sec=float(self.cfg.target_lead_sec),
        )

        self.session_id = str(uuid.uuid4())

    def run(
        self,
        *,
        lesson_id: str,
        wav: np.ndarray,
        sample_rate: int,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        mono = ensure_mono_float32(wav)
        if int(sample_rate) != int(self.cfg.sample_rate):
            mono = naive_resample(mono, src_sr=int(sample_rate), dst_sr=int(self.cfg.sample_rate))
            sample_rate = int(self.cfg.sample_rate)

        duration_sec = float(mono.shape[0] / max(1, sample_rate))
        tick_sec = float(self.cfg.tick_sec)
        chunk_n = max(1, int(round(self.cfg.chunk_sec * sample_rate)))

        sim_pb = SimPlayback(
            state=PlaybackState(self.cfg.initial_playback_state),
            t_ref_heard_content_sec=0.0,
            t_ref_emitted_content_sec=0.0,
            t_ref_block_start_content_sec=0.0,
            t_ref_block_end_content_sec=0.0,
            t_host_output_sec=0.0,
            chunk_id=0,
            frame_index=0,
            gain=float(self.cfg.initial_playback_gain),
            generation=0,
        )

        rows: list[dict[str, Any]] = []

        pos = 0
        tick_id = 0
        now_sec = 0.0

        while now_sec <= duration_sec + 1e-6:
            start = pos
            end = min(mono.shape[0], pos + chunk_n)
            pcm = mono[start:end]
            if pcm.size == 0:
                break

            observed_at_sec = float(now_sec + (pcm.shape[0] / max(1, sample_rate)))
            pcm16 = float_audio_to_pcm16_bytes(pcm)

            # 1) signal
            self.signal_monitor.feed_pcm16(pcm16, observed_at_sec)
            signal_snapshot = self.signal_monitor.snapshot(observed_at_sec)

            # 2) frame features -> matcher
            feat_frames = self.feature_extractor.process_pcm16(
                pcm16,
                observed_at_sec=observed_at_sec,
            )
            self.live_audio_matcher.feed_features(feat_frames)

            # 3) gt ref time：离线数据里，直接用“音频当前位置”
            gt_ref_time_sec = min(duration_sec, observed_at_sec)
            gt_ref_idx = time_to_ref_idx(self.ref_map, gt_ref_time_sec)

            # 4) playback timeline 粗模拟
            sim_pb = self._step_playback(
                sim_pb=sim_pb,
                now_sec=observed_at_sec,
                tick_sec=tick_sec,
                gt_ref_time_sec=gt_ref_time_sec,
            )
            playback_status = sim_pb.to_status()

            # 5) synthetic text progress
            signal_like = float(
                max(
                    signal_snapshot.speaking_likelihood,
                    0.45 if signal_snapshot.vad_active else 0.0,
                )
            )
            progress = None
            if self.cfg.use_synthetic_text_progress:
                progress = self.synthetic_text_teacher.snapshot(
                    now_sec=observed_at_sec,
                    gt_ref_time_sec=gt_ref_time_sec,
                    signal_like=signal_like,
                )

            # 6) audio_match
            text_tracking_conf = 0.0 if progress is None else float(progress.tracking_quality)
            progress_hint_ref_time_sec = None if progress is None else float(progress.estimated_ref_time_sec)

            audio_match = self.live_audio_matcher.snapshot(
                now_sec=observed_at_sec,
                progress_hint_ref_time_sec=progress_hint_ref_time_sec,
                playback_ref_time_sec=float(playback_status.t_ref_heard_content_sec),
                text_tracking_confidence=float(text_tracking_conf),
            )

            # 7) behavior
            audio_behavior = self.audio_behavior_classifier.update(
                audio_match=audio_match,
                signal_quality=signal_snapshot,
                progress=progress,
                playback_status=playback_status,
            )

            # 8) fusion
            fusion_evidence = self.evidence_fuser.fuse(
                now_sec=observed_at_sec,
                tracking=None,
                progress=progress,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
                signal_quality=signal_snapshot,
                playback_status=playback_status,
            )

            # 9) sync evidence
            sync_evidence = self.sync_builder.build(
                now_sec=observed_at_sec,
                signal_quality=signal_snapshot,
                progress=progress,
                fusion_evidence=fusion_evidence,
                bluetooth_mode=False,
                bluetooth_long_session_mode=False,
            )

            # 10) action teacher
            decision = self.controller.decide(
                playback=playback_status,
                progress=progress,
                signal_quality=signal_snapshot,
                sync_evidence=sync_evidence,
                fusion_evidence=fusion_evidence,
            )

            # 11) 记录主表一行
            row = self._build_row(
                lesson_id=lesson_id,
                tick_id=tick_id,
                t_sec=observed_at_sec,
                gt_ref_time_sec=gt_ref_time_sec,
                gt_ref_idx=gt_ref_idx,
                playback_status=playback_status,
                signal_snapshot=signal_snapshot,
                audio_match=audio_match,
                audio_behavior=audio_behavior,
                progress=progress,
                fusion_evidence=fusion_evidence,
                sync_evidence=sync_evidence,
                decision=decision,
            )
            rows.append(row)

            # 12) 下一 tick
            pos += chunk_n
            now_sec += tick_sec
            tick_id += 1

        frame_df = pd.DataFrame(rows)
        if frame_df.empty:
            raise RuntimeError("No frame dump rows were produced.")

        # 13) posterior action labels
        posterior_rows = []
        for i in range(len(frame_df)):
            posterior_rows.append(self.posterior_labeler.label(frame_df=frame_df, row_idx=i))
        posterior_df = pd.DataFrame(posterior_rows)
        frame_df = pd.concat([frame_df.reset_index(drop=True), posterior_df.reset_index(drop=True)], axis=1)

        # 14) 派生训练表
        behavior_df = build_behavior_training_table(frame_df)
        fusion_df = build_fusion_training_table(frame_df)
        action_df = build_action_training_table(frame_df)

        return frame_df, behavior_df, fusion_df, action_df

    def _step_playback(
        self,
        *,
        sim_pb: SimPlayback,
        now_sec: float,
        tick_sec: float,
        gt_ref_time_sec: float,
    ) -> SimPlayback:
        state = sim_pb.state
        cur = float(sim_pb.t_ref_heard_content_sec)

        if state == PlaybackState.PLAYING:
            nxt = cur + tick_sec
        elif state == PlaybackState.HOLDING:
            nxt = cur
        elif state == PlaybackState.SEEKING:
            nxt = cur
        elif state == PlaybackState.FINISHED:
            nxt = cur
        else:
            nxt = cur

        block_start = cur
        block_end = nxt

        return SimPlayback(
            state=state,
            t_ref_heard_content_sec=float(nxt),
            t_ref_emitted_content_sec=float(nxt),
            t_ref_block_start_content_sec=float(block_start),
            t_ref_block_end_content_sec=float(block_end),
            t_host_output_sec=float(now_sec),
            chunk_id=int(sim_pb.chunk_id),
            frame_index=int(sim_pb.frame_index + 1),
            gain=float(sim_pb.gain),
            generation=int(sim_pb.generation),
        )

    def _build_row(
        self,
        *,
        lesson_id: str,
        tick_id: int,
        t_sec: float,
        gt_ref_time_sec: float,
        gt_ref_idx: int,
        playback_status: PlaybackStatus,
        signal_snapshot,
        audio_match,
        audio_behavior,
        progress,
        fusion_evidence,
        sync_evidence,
        decision,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "lesson_id": str(lesson_id),
            "session_id": str(self.session_id),
            "tick_id": int(tick_id),
            "t_sec": float(t_sec),
            "gt_ref_time_sec": float(gt_ref_time_sec),
            "gt_ref_idx": int(gt_ref_idx),

            # playback
            "playback_state": str(playback_status.state.value),
            "playback_ref_time_sec": float(playback_status.t_ref_heard_content_sec),
            "playback_gain": float(playback_status.gain),
            "generation": int(playback_status.generation),
        }

        # signal
        row.update(
            {
                "rms": float(getattr(signal_snapshot, "rms", 0.0)),
                "peak": float(getattr(signal_snapshot, "peak", 0.0)),
                "vad_active": int(bool(getattr(signal_snapshot, "vad_active", False))),
                "speaking_likelihood": float(getattr(signal_snapshot, "speaking_likelihood", 0.0)),
                "silence_run_sec": float(getattr(signal_snapshot, "silence_run_sec", 0.0)),
                "quality_score": float(getattr(signal_snapshot, "quality_score", 0.0)),
                "dropout_detected": int(bool(getattr(signal_snapshot, "dropout_detected", False))),
            }
        )

        # audio match
        if audio_match is None:
            row.update(default_audio_match_columns())
        else:
            row.update(
                {
                    "match_conf": float(getattr(audio_match, "confidence", 0.0)),
                    "local_similarity": float(getattr(audio_match, "local_similarity", 0.0)),
                    "env_score": float(getattr(audio_match, "envelope_alignment_score", 0.0)),
                    "onset_score": float(getattr(audio_match, "onset_alignment_score", 0.0)),
                    "band_score": float(getattr(audio_match, "band_alignment_score", 0.0)),
                    "rhythm_score": float(getattr(audio_match, "rhythm_consistency_score", 0.0)),
                    "dtw_score": float(getattr(audio_match, "dtw_path_score", 0.0)),
                    "dtw_cost": float(getattr(audio_match, "dtw_cost", 0.0)),
                    "dtw_coverage": float(getattr(audio_match, "dtw_coverage", 0.0)),
                    "drift_sec": float(getattr(audio_match, "drift_sec", 0.0)),
                    "repeated_score": float(getattr(audio_match, "repeated_pattern_score", 0.0)),
                    "match_mode": str(getattr(audio_match, "mode", "tracking")),
                    "audio_ref_time_sec": float(getattr(audio_match, "estimated_ref_time_sec", 0.0)),
                    "audio_ref_idx": int(getattr(audio_match, "estimated_ref_idx_hint", 0)),
                }
            )

        # progress / text
        if progress is None:
            row.update(default_progress_columns())
        else:
            row.update(
                {
                    "tracking_mode": str(getattr(progress, "tracking_mode", "bootstrap").value),
                    "tracking_quality": float(getattr(progress, "tracking_quality", 0.0)),
                    "tracking_confidence": float(getattr(progress, "confidence", 0.0)),
                    "joint_confidence": float(getattr(progress, "joint_confidence", 0.0)),
                    "progress_age_sec": float(getattr(progress, "progress_age_sec", 9999.0)),
                    "recently_progressed": int(bool(getattr(progress, "recently_progressed", False))),
                    "active_speaking": int(bool(getattr(progress, "active_speaking", False))),
                    "stable": int(bool(getattr(progress, "stable", False))),
                    "position_source": str(getattr(progress, "position_source", "text")),
                    "text_ref_time_sec": float(getattr(progress, "estimated_ref_time_sec", 0.0)),
                    "text_ref_idx": int(getattr(progress, "estimated_ref_idx", 0)),
                    "source_candidate_ref_idx": int(getattr(progress, "source_candidate_ref_idx", 0)),
                    "source_committed_ref_idx": int(getattr(progress, "source_committed_ref_idx", 0)),
                    "user_state": str(getattr(progress, "user_state", "warming_up").value),
                }
            )

        # behavior teacher
        if audio_behavior is None:
            row.update(default_behavior_columns())
        else:
            row.update(
                {
                    "teacher_still_following": float(getattr(audio_behavior, "still_following_likelihood", 0.0)),
                    "teacher_repeated": float(getattr(audio_behavior, "repeated_likelihood", 0.0)),
                    "teacher_reentry": float(getattr(audio_behavior, "reentry_likelihood", 0.0)),
                    "teacher_paused": float(getattr(audio_behavior, "paused_likelihood", 0.0)),
                    "teacher_behavior_confidence": float(getattr(audio_behavior, "confidence", 0.0)),
                }
            )

        # fusion teacher
        if fusion_evidence is None:
            row.update(default_fusion_columns())
        else:
            audio_w = infer_audio_weight_from_fusion_row(
                text_conf=float(getattr(fusion_evidence, "text_confidence", 0.0)),
                audio_conf=float(getattr(fusion_evidence, "audio_confidence", 0.0)),
                fused_conf=float(getattr(fusion_evidence, "fused_confidence", 0.0)),
            )
            row.update(
                {
                    "teacher_fused_confidence": float(getattr(fusion_evidence, "fused_confidence", 0.0)),
                    "teacher_fusion_still_following": float(getattr(fusion_evidence, "still_following_likelihood", 0.0)),
                    "teacher_fusion_repeated": float(getattr(fusion_evidence, "repeated_likelihood", 0.0)),
                    "teacher_fusion_reentry": float(getattr(fusion_evidence, "reentry_likelihood", 0.0)),
                    "teacher_prevent_hold": int(bool(getattr(fusion_evidence, "should_prevent_hold", False))),
                    "teacher_prevent_seek": int(bool(getattr(fusion_evidence, "should_prevent_seek", False))),
                    "teacher_widen_reacquire": int(bool(getattr(fusion_evidence, "should_widen_reacquire_window", False))),
                    "teacher_recenter_aligner": int(bool(getattr(fusion_evidence, "should_recenter_aligner_window", False))),
                    "teacher_audio_weight": float(audio_w),
                    "teacher_fused_ref_time_sec": float(getattr(fusion_evidence, "estimated_ref_time_sec", 0.0)),
                    "teacher_fused_ref_idx": int(getattr(fusion_evidence, "estimated_ref_idx_hint", 0)),
                }
            )

        # sync evidence
        row.update(
            {
                "speech_conf": float(getattr(sync_evidence, "speech_confidence", 0.0)),
                "tracking_conf": float(getattr(sync_evidence, "tracking_confidence", 0.0)),
                "sync_conf": float(getattr(sync_evidence, "sync_confidence", 0.0)),
                "speech_state": str(getattr(sync_evidence, "speech_state", "none").value),
                "tracking_state": str(getattr(sync_evidence, "tracking_state", "none").value),
                "sync_state": str(getattr(sync_evidence, "sync_state", "bootstrap").value),
                "allow_seek": int(bool(getattr(sync_evidence, "allow_seek", False))),
                "startup_mode": int(bool(getattr(sync_evidence, "startup_mode", False))),
                "bluetooth_mode": int(bool(getattr(sync_evidence, "bluetooth_mode", False))),
                "bluetooth_long_session_mode": int(bool(getattr(sync_evidence, "bluetooth_long_session_mode", False))),
            }
        )

        # action teacher
        row.update(
            {
                "teacher_action": str(getattr(decision, "action", ControlAction.NOOP).value),
                "teacher_target_gain": float(getattr(decision, "target_gain", 0.0) or 0.0),
                "teacher_target_time_sec": float(getattr(decision, "target_time_sec", 0.0) or 0.0),
                "teacher_lead_sec": float(getattr(decision, "lead_sec", 0.0) or 0.0),
                "teacher_action_confidence": float(getattr(decision, "confidence", 0.0)),
                "teacher_action_reason": str(getattr(decision, "reason", "")),
            }
        )

        # controller internal features
        pressure = getattr(self.controller, "_pressure", None)
        if pressure is None:
            row.update(default_pressure_columns())
        else:
            row.update(
                {
                    "hold_pressure": float(getattr(pressure, "hold_pressure", 0.0)),
                    "resume_pressure": float(getattr(pressure, "resume_pressure", 0.0)),
                    "seek_pressure": float(getattr(pressure, "seek_pressure", 0.0)),
                    "soft_duck_pressure": float(getattr(pressure, "soft_duck_pressure", 0.0)),
                    "lead_error_ema": float(getattr(pressure, "lead_error_ema", 0.0)),
                    "lead_error_derivative_ema": float(getattr(pressure, "lead_error_derivative_ema", 0.0)),
                    "tracking_quality_ema": float(getattr(pressure, "tracking_quality_ema", 0.0)),
                    "confidence_ema": float(getattr(pressure, "confidence_ema", 0.0)),
                    "speech_confidence_ema": float(getattr(pressure, "speech_confidence_ema", 0.0)),
                }
            )

        row["lead_error_sec"] = float(row["playback_ref_time_sec"] - row["teacher_fused_ref_time_sec"] - self.cfg.target_lead_sec)

        row["position_source_audio"] = int(row["position_source"] == "audio")
        row["position_source_joint"] = int(row["position_source"] == "joint")

        row["mode_repeat"] = int(row["match_mode"] == "repeat")
        row["mode_reentry"] = int(row["match_mode"] == "reentry")
        row["mode_recovery"] = int(row["match_mode"] == "recovery")

        row["signal_conf"] = float(max(row["speaking_likelihood"], 0.45 if row["vad_active"] else 0.0))
        row["progress_recent"] = int(row["recently_progressed"])
        row["progress_active"] = int(row["active_speaking"])
        row["progress_age"] = float(row["progress_age_sec"])
        row["tracking_q"] = float(row["tracking_quality"])
        row["joint_conf"] = float(row["joint_confidence"])

        row["state_name"] = infer_state_name(row)

        return row


# ============================================================================
# 训练表构造
# ============================================================================


def build_behavior_training_table(frame_df: pd.DataFrame) -> pd.DataFrame:
    df = frame_df.copy()

    out = pd.DataFrame(
        {
            "lesson_id": df["lesson_id"],
            "session_id": df["session_id"],
            "tick_id": df["tick_id"],
            "t_sec": df["t_sec"],
            "state_name": df["state_name"],

            # features
            "match_conf": df["match_conf"],
            "local_similarity": df["local_similarity"],
            "repeated_score": df["repeated_score"],
            "drift_sec": df["drift_sec"],
            "dtw_score": df["dtw_score"],
            "dtw_coverage": df["dtw_coverage"],
            "env_score": df["env_score"],
            "onset_score": df["onset_score"],
            "band_score": df["band_score"],
            "rhythm_score": df["rhythm_score"],
            "signal_conf": df["signal_conf"],
            "silence_run_sec": df["silence_run_sec"],
            "quality_score": df["quality_score"],
            "rms": df["rms"],
            "peak": df["peak"],
            "vad_active": df["vad_active"],
            "tracking_q": df["tracking_q"],
            "joint_conf": df["joint_conf"],
            "progress_recent": df["progress_recent"],
            "progress_active": df["progress_active"],
            "progress_age": df["progress_age"],
            "position_source_audio": df["position_source_audio"],
            "position_source_joint": df["position_source_joint"],
            "mode_repeat": df["mode_repeat"],
            "mode_reentry": df["mode_reentry"],
            "mode_recovery": df["mode_recovery"],

            # prev features
            "prev_follow": df["teacher_still_following"].shift(1).fillna(0.0),
            "prev_repeat": df["teacher_repeated"].shift(1).fillna(0.0),
            "prev_reentry": df["teacher_reentry"].shift(1).fillna(0.0),
            "prev_pause": df["teacher_paused"].shift(1).fillna(0.0),

            # labels
            "still_following": df["teacher_still_following"].clip(0.0, 1.0),
            "repeated": df["teacher_repeated"].clip(0.0, 1.0),
            "reentry": df["teacher_reentry"].clip(0.0, 1.0),
            "paused": df["teacher_paused"].clip(0.0, 1.0),
            "confidence": df["teacher_behavior_confidence"].clip(0.0, 1.0),

            # diagnostics
            "gt_ref_time_sec": df["gt_ref_time_sec"],
            "audio_ref_time_sec": df["audio_ref_time_sec"],
            "text_ref_time_sec": df["text_ref_time_sec"],
        }
    )
    return out


def build_fusion_training_table(frame_df: pd.DataFrame) -> pd.DataFrame:
    df = frame_df.copy()

    out = pd.DataFrame(
        {
            "lesson_id": df["lesson_id"],
            "session_id": df["session_id"],
            "tick_id": df["tick_id"],
            "t_sec": df["t_sec"],
            "state_name": df["state_name"],

            # features
            "text_conf": df["tracking_confidence"],
            "text_tracking_q": df["tracking_quality"],
            "text_joint_conf": df["joint_confidence"],
            "text_recent": df["recently_progressed"],
            "text_active": df["active_speaking"],
            "text_progress_age": df["progress_age_sec"],

            "audio_conf": df["match_conf"],
            "audio_local_similarity": df["local_similarity"],
            "audio_repeated_score": df["repeated_score"],
            "audio_drift_sec": df["drift_sec"],
            "audio_dtw_score": df["dtw_score"],
            "audio_dtw_coverage": df["dtw_coverage"],
            "audio_mode_repeat": df["mode_repeat"],
            "audio_mode_reentry": df["mode_reentry"],
            "audio_mode_recovery": df["mode_recovery"],

            "behavior_follow": df["teacher_still_following"],
            "behavior_repeat": df["teacher_repeated"],
            "behavior_reentry": df["teacher_reentry"],
            "behavior_paused": df["teacher_paused"],
            "behavior_conf": df["teacher_behavior_confidence"],

            "signal_conf": df["signal_conf"],
            "silence_run_sec": df["silence_run_sec"],
            "quality_score": df["quality_score"],
            "vad_active": df["vad_active"],

            "disagreement_abs_sec": (df["text_ref_time_sec"] - df["audio_ref_time_sec"]).abs().fillna(0.0),
            "playback_lead_text": (df["playback_ref_time_sec"] - df["text_ref_time_sec"]).fillna(0.0),
            "playback_lead_audio": (df["playback_ref_time_sec"] - df["audio_ref_time_sec"]).fillna(0.0),

            "prev_fused_conf": df["teacher_fused_confidence"].shift(1).fillna(0.0),
            "prev_prevent_hold": df["teacher_prevent_hold"].shift(1).fillna(0),
            "prev_prevent_seek": df["teacher_prevent_seek"].shift(1).fillna(0),

            # labels
            "fused_confidence": df["teacher_fused_confidence"].clip(0.0, 1.0),
            "still_following": df["teacher_fusion_still_following"].clip(0.0, 1.0),
            "repeated": df["teacher_fusion_repeated"].clip(0.0, 1.0),
            "reentry": df["teacher_fusion_reentry"].clip(0.0, 1.0),
            "prevent_hold": df["teacher_prevent_hold"].astype(np.int64),
            "prevent_seek": df["teacher_prevent_seek"].astype(np.int64),
            "widen_reacquire": df["teacher_widen_reacquire"].astype(np.int64),
            "recenter_aligner": df["teacher_recenter_aligner"].astype(np.int64),
            "audio_weight": df["teacher_audio_weight"].clip(0.0, 1.0),

            # diagnostics
            "gt_ref_time_sec": df["gt_ref_time_sec"],
            "audio_ref_time_sec": df["audio_ref_time_sec"],
            "text_ref_time_sec": df["text_ref_time_sec"],
        }
    )
    return out


def build_action_training_table(frame_df: pd.DataFrame) -> pd.DataFrame:
    df = frame_df.copy()

    teacher_action = df["posterior_best_action"].fillna(df["teacher_action"])

    out = pd.DataFrame(
        {
            "lesson_id": df["lesson_id"],
            "session_id": df["session_id"],
            "tick_id": df["tick_id"],
            "t_sec": df["t_sec"],
            "state_name": df["state_name"],

            # features
            "playback_state_playing": (df["playback_state"] == "playing").astype(np.int64),
            "playback_state_holding": (df["playback_state"] == "holding").astype(np.int64),
            "playback_state_stopped": (df["playback_state"] == "stopped").astype(np.int64),

            "lead_error_sec": df["lead_error_sec"],
            "playback_ref_time_sec": df["playback_ref_time_sec"],
            "fused_ref_time_sec": df["teacher_fused_ref_time_sec"],
            "fused_conf": df["teacher_fused_confidence"],
            "follow_like": df["teacher_fusion_still_following"],
            "repeat_like": df["teacher_fusion_repeated"],
            "reentry_like": df["teacher_fusion_reentry"],
            "prevent_hold": df["teacher_prevent_hold"],
            "prevent_seek": df["teacher_prevent_seek"],

            "speech_conf": df["speech_conf"],
            "tracking_conf": df["tracking_conf"],
            "sync_conf": df["sync_conf"],
            "allow_seek": df["allow_seek"],
            "startup_mode": df["startup_mode"],

            "hold_pressure": df["hold_pressure"],
            "resume_pressure": df["resume_pressure"],
            "seek_pressure": df["seek_pressure"],
            "soft_duck_pressure": df["soft_duck_pressure"],
            "lead_error_ema": df["lead_error_ema"],
            "lead_error_derivative_ema": df["lead_error_derivative_ema"],
            "tracking_quality_ema": df["tracking_quality_ema"],
            "confidence_ema": df["confidence_ema"],
            "speech_confidence_ema": df["speech_confidence_ema"],

            "teacher_target_gain": df["teacher_target_gain"],
            "teacher_lead_sec": df["teacher_lead_sec"],

            "prev_action_hold": df["teacher_action"].shift(1).fillna("noop").eq("hold").astype(np.int64),
            "prev_action_resume": df["teacher_action"].shift(1).fillna("noop").eq("resume").astype(np.int64),
            "prev_action_seek": df["teacher_action"].shift(1).fillna("noop").eq("seek").astype(np.int64),

            # labels
            "noop": teacher_action.eq("noop").astype(np.int64),
            "soft_duck": teacher_action.eq("soft_duck").astype(np.int64),
            "hold": teacher_action.eq("hold").astype(np.int64),
            "resume": teacher_action.eq("resume").astype(np.int64),
            "seek": teacher_action.eq("seek").astype(np.int64),

            # bias labels
            "gain_bias": (df["teacher_target_gain"] - 0.50).fillna(0.0).clip(-1.0, 1.0),
            "seek_bias": (df["teacher_target_time_sec"] - df["teacher_fused_ref_time_sec"]).fillna(0.0).clip(-3.0, 3.0),

            # diagnostics
            "teacher_action": df["teacher_action"],
            "posterior_best_action": teacher_action,
            "gt_ref_time_sec": df["gt_ref_time_sec"],
        }
    )
    return out


# ============================================================================
# 默认列 / schema helpers
# ============================================================================


def default_audio_match_columns() -> dict[str, Any]:
    return {
        "match_conf": 0.0,
        "local_similarity": 0.0,
        "env_score": 0.0,
        "onset_score": 0.0,
        "band_score": 0.0,
        "rhythm_score": 0.0,
        "dtw_score": 0.0,
        "dtw_cost": 0.0,
        "dtw_coverage": 0.0,
        "drift_sec": 0.0,
        "repeated_score": 0.0,
        "match_mode": "tracking",
        "audio_ref_time_sec": 0.0,
        "audio_ref_idx": 0,
    }


def default_progress_columns() -> dict[str, Any]:
    return {
        "tracking_mode": "bootstrap",
        "tracking_quality": 0.0,
        "tracking_confidence": 0.0,
        "joint_confidence": 0.0,
        "progress_age_sec": 9999.0,
        "recently_progressed": 0,
        "active_speaking": 0,
        "stable": 0,
        "position_source": "text",
        "text_ref_time_sec": 0.0,
        "text_ref_idx": 0,
        "source_candidate_ref_idx": 0,
        "source_committed_ref_idx": 0,
        "user_state": "warming_up",
    }


def default_behavior_columns() -> dict[str, Any]:
    return {
        "teacher_still_following": 0.0,
        "teacher_repeated": 0.0,
        "teacher_reentry": 0.0,
        "teacher_paused": 0.0,
        "teacher_behavior_confidence": 0.0,
    }


def default_fusion_columns() -> dict[str, Any]:
    return {
        "teacher_fused_confidence": 0.0,
        "teacher_fusion_still_following": 0.0,
        "teacher_fusion_repeated": 0.0,
        "teacher_fusion_reentry": 0.0,
        "teacher_prevent_hold": 0,
        "teacher_prevent_seek": 0,
        "teacher_widen_reacquire": 0,
        "teacher_recenter_aligner": 0,
        "teacher_audio_weight": 0.0,
        "teacher_fused_ref_time_sec": 0.0,
        "teacher_fused_ref_idx": 0,
    }


def default_pressure_columns() -> dict[str, Any]:
    return {
        "hold_pressure": 0.0,
        "resume_pressure": 0.0,
        "seek_pressure": 0.0,
        "soft_duck_pressure": 0.0,
        "lead_error_ema": 0.0,
        "lead_error_derivative_ema": 0.0,
        "tracking_quality_ema": 0.0,
        "confidence_ema": 0.0,
        "speech_confidence_ema": 0.0,
    }


def infer_audio_weight_from_fusion_row(
    *,
    text_conf: float,
    audio_conf: float,
    fused_conf: float,
) -> float:
    denom = max(1e-6, float(text_conf) + float(audio_conf))
    raw = float(audio_conf) / denom
    if fused_conf < 0.10:
        return 0.0
    return float(max(0.0, min(1.0, raw)))


def infer_state_name(row: dict[str, Any]) -> str:
    if row["teacher_repeated"] >= 0.60:
        return "repeat"
    if row["teacher_reentry"] >= 0.58:
        return "reentry"
    if row["teacher_paused"] >= 0.62:
        return "pause"
    if row["teacher_still_following"] >= 0.66:
        return "following"
    if row["tracking_quality"] < 0.40:
        return "weak_tracking"
    return "transition"


# ============================================================================
# IO helpers
# ============================================================================


def load_reference_map(path: Path) -> ReferenceMap:
    data = json.loads(path.read_text(encoding="utf-8"))
    tokens = [
        RefToken(
            idx=int(x["idx"]),
            char=str(x["char"]),
            pinyin=str(x.get("pinyin", "")),
            t_start=float(x["t_start"]),
            t_end=float(x["t_end"]),
            sentence_id=int(x.get("sentence_id", 0)),
            clause_id=int(x.get("clause_id", 0)),
        )
        for x in data.get("tokens", [])
    ]
    return ReferenceMap(
        lesson_id=str(data.get("lesson_id", path.parent.name)),
        tokens=tokens,
        total_duration_sec=float(data.get("total_duration_sec", 0.0)),
    )


def time_to_ref_idx(ref_map: ReferenceMap, t_sec: float) -> int:
    if not ref_map.tokens:
        return 0
    lo = 0
    hi = len(ref_map.tokens) - 1
    t = float(t_sec)

    while lo < hi:
        mid = (lo + hi + 1) // 2
        if float(ref_map.tokens[mid].t_start) <= t:
            lo = mid
        else:
            hi = mid - 1
    return int(max(0, min(lo, len(ref_map.tokens) - 1)))


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    if sf is None:
        raise RuntimeError("soundfile is required to read wav. Please install pysoundfile.")
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    return np.asarray(audio, dtype=np.float32), int(sr)


def ensure_mono_float32(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        return np.mean(arr, axis=1).astype(np.float32, copy=False)
    raise ValueError(f"Unsupported audio shape: {arr.shape}")


def naive_resample(audio: np.ndarray, *, src_sr: int, dst_sr: int) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32).reshape(-1)
    if src_sr == dst_sr or arr.size == 0:
        return arr
    src_t = np.arange(arr.shape[0], dtype=np.float32) / float(src_sr)
    dst_n = max(1, int(round(arr.shape[0] * float(dst_sr) / float(src_sr))))
    dst_t = np.arange(dst_n, dtype=np.float32) / float(dst_sr)
    out = np.interp(dst_t, src_t, arr).astype(np.float32)
    return out


def float_audio_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    arr = np.asarray(audio, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype(np.int16).tobytes()


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================================
# CLI
# ============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build runtime-in-the-loop parquet dump for one lesson.")
    p.add_argument("--lesson-id", type=str, required=True)
    p.add_argument("--wav", type=str, required=True)
    p.add_argument("--ref-map", type=str, required=True)
    p.add_argument("--ref-audio-features", type=str, required=True)
    p.add_argument("--out-dir", type=str, required=True)

    p.add_argument("--sample-rate", type=int, default=16000)
    p.add_argument("--tick-sec", type=float, default=0.03)
    p.add_argument("--chunk-sec", type=float, default=0.03)
    p.add_argument("--target-lead-sec", type=float, default=0.18)

    p.add_argument("--no-synthetic-text-progress", action="store_true")
    return p


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    lesson_id = str(args.lesson_id)
    wav_path = Path(args.wav).expanduser().resolve()
    ref_map_path = Path(args.ref_map).expanduser().resolve()
    ref_audio_features_path = Path(args.ref_audio_features).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    if not wav_path.exists():
        raise FileNotFoundError(f"WAV not found: {wav_path}")
    if not ref_map_path.exists():
        raise FileNotFoundError(f"Reference map not found: {ref_map_path}")
    if not ref_audio_features_path.exists():
        raise FileNotFoundError(f"Reference audio features not found: {ref_audio_features_path}")

    ref_map = load_reference_map(ref_map_path)
    ref_audio_store = ReferenceAudioStore(str(ref_audio_features_path.parent.parent))
    # 这里直接 load 文件更稳妥
    ref_audio_data = json.loads(ref_audio_features_path.read_text(encoding="utf-8"))
    ref_audio_features = ref_audio_store.load(lesson_id=lesson_id) if ref_audio_store.exists(lesson_id) else _load_reference_audio_features_from_json(ref_audio_data)

    wav, sr = read_wav(wav_path)

    cfg = DumpConfig(
        sample_rate=int(args.sample_rate),
        tick_sec=float(args.tick_sec),
        chunk_sec=float(args.chunk_sec),
        target_lead_sec=float(args.target_lead_sec),
        use_synthetic_text_progress=not bool(args.no_synthetic_text_progress),
    )

    labeler = OfflineRuntimeLabeler(
        ref_map=ref_map,
        ref_audio_features=ref_audio_features,
        config=cfg,
    )

    frame_df, behavior_df, fusion_df, action_df = labeler.run(
        lesson_id=lesson_id,
        wav=wav,
        sample_rate=sr,
    )

    if cfg.save_frame_dump:
        save_parquet(frame_df, out_dir / "frame_dump.parquet")
    if cfg.save_behavior_table:
        save_parquet(behavior_df, out_dir / "behavior_train.parquet")
    if cfg.save_fusion_table:
        save_parquet(fusion_df, out_dir / "fusion_train.parquet")
    if cfg.save_action_table:
        save_parquet(action_df, out_dir / "action_train.parquet")

    meta = {
        "lesson_id": lesson_id,
        "wav": str(wav_path),
        "ref_map": str(ref_map_path),
        "ref_audio_features": str(ref_audio_features_path),
        "out_dir": str(out_dir),
        "config": asdict(cfg),
        "n_frame_rows": int(len(frame_df)),
        "n_behavior_rows": int(len(behavior_df)),
        "n_fusion_rows": int(len(fusion_df)),
        "n_action_rows": int(len(action_df)),
        "state_name_counter": frame_df["state_name"].value_counts().to_dict() if "state_name" in frame_df.columns else {},
        "teacher_action_counter": frame_df["teacher_action"].value_counts().to_dict() if "teacher_action" in frame_df.columns else {},
        "posterior_action_counter": frame_df["posterior_best_action"].value_counts().to_dict() if "posterior_best_action" in frame_df.columns else {},
    }
    save_json(meta, out_dir / "meta.json")


def _load_reference_audio_features_from_json(data: dict[str, Any]) -> ReferenceAudioFeatures:
    from shadowing.audio.reference_audio_features import (
        ReferenceAudioFrameFeatures,
        ReferenceBoundaryHint,
        ReferenceTokenAcousticTemplate,
    )

    frames = [ReferenceAudioFrameFeatures(**item) for item in data.get("frames", [])]
    boundaries = [ReferenceBoundaryHint(**item) for item in data.get("boundaries", [])]
    token_templates = [ReferenceTokenAcousticTemplate(**item) for item in data.get("token_acoustic_templates", [])]
    return ReferenceAudioFeatures(
        lesson_id=str(data["lesson_id"]),
        frame_hop_sec=float(data.get("frame_hop_sec", 0.010)),
        frame_size_sec=float(data.get("frame_size_sec", 0.025)),
        sample_rate=int(data.get("sample_rate", 16000)),
        frames=frames,
        boundaries=boundaries,
        token_time_hints_sec=[float(x) for x in data.get("token_time_hints_sec", [])],
        token_acoustic_templates=token_templates,
        total_duration_sec=float(data.get("total_duration_sec", 0.0)),
    )


if __name__ == "__main__":
    main()


shadowing/training/train_action_model.py
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset


ACTION_FEATURE_NAMES = [
    "playback_playing",
    "playback_holding",
    "playback_seeking",
    "lead_sec",
    "lead_error_sec",
    "tracking_quality",
    "confidence",
    "speech_conf",
    "progress_age_sec",
    "active_speaking",
    "recently_progressed",
    "stable",
    "speaking_recent",
    "engaged_recent",
    "fusion_still_following",
    "fusion_repeated",
    "fusion_reentry",
    "fusion_fused_conf",
    "in_startup_grace",
    "in_resume_cooldown",
    "in_seek_cooldown",
    "allow_seek",
    "bluetooth_mode",
    "bluetooth_long_session_mode",
    "tracking_state_weak",
    "tracking_state_reliable",
    "tracking_state_locked",
    "sync_state_converging",
    "sync_state_stable",
    "sync_state_degraded",
    "position_source_audio",
    "position_source_joint",
    "hold_pressure",
    "resume_pressure",
    "seek_pressure",
    "soft_duck_pressure",
    "lead_error_ema",
    "lead_error_derivative_ema",
    "tracking_quality_ema",
    "confidence_ema",
    "speech_confidence_ema",
]

ACTION_CLASS_TARGETS = ["noop", "soft_duck", "hold", "resume", "seek"]
ACTION_REG_TARGETS = ["gain_bias", "seek_bias"]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return float(v)


class ActionDataset(Dataset):
    def __init__(self, x: np.ndarray, y_cls: np.ndarray, y_reg: np.ndarray) -> None:
        self.x = torch.tensor(x, dtype=torch.float32)
        self.y_cls = torch.tensor(y_cls, dtype=torch.float32)
        self.y_reg = torch.tensor(y_reg, dtype=torch.float32)

    def __len__(self) -> int:
        return int(self.x.shape[0])

    def __getitem__(self, idx: int):
        return self.x[idx], self.y_cls[idx], self.y_reg[idx]


class ActionMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list[int], class_dim: int, reg_dim: int, dropout: float = 0.10) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        cur = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(cur, h))
            layers.append(nn.ReLU())
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            cur = h
        self.backbone = nn.Sequential(*layers)
        self.class_head = nn.Linear(cur, class_dim)
        self.reg_head = nn.Linear(cur, reg_dim)

    def forward(self, x):
        h = self.backbone(x)
        return self.class_head(h), self.reg_head(h)


class WeightedFocalBCELoss(nn.Module):
    def __init__(
        self,
        pos_weight: torch.Tensor,
        alpha_pos: torch.Tensor,
        gamma: float = 2.0,
        reduction: str = "mean",
    ) -> None:
        super().__init__()
        self.register_buffer("pos_weight", pos_weight)
        self.register_buffer("alpha_pos", alpha_pos)
        self.gamma = float(gamma)
        self.reduction = reduction

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probs = torch.sigmoid(logits)
        bce = nn.functional.binary_cross_entropy_with_logits(
            logits,
            targets,
            reduction="none",
            pos_weight=self.pos_weight,
        )
        pt = probs * targets + (1.0 - probs) * (1.0 - targets)
        alpha = self.alpha_pos * targets + (1.0 - self.alpha_pos) * (1.0 - targets)
        focal = alpha * torch.pow(torch.clamp(1.0 - pt, min=1e-6), self.gamma) * bce
        if self.reduction == "mean":
            return focal.mean()
        if self.reduction == "sum":
            return focal.sum()
        return focal


def _prepare_xy(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = df[ACTION_FEATURE_NAMES].values.astype(np.float32)
    y_cls = np.clip(df[ACTION_CLASS_TARGETS].values.astype(np.float32), 0.0, 1.0)
    y_reg = np.clip(df[ACTION_REG_TARGETS].values.astype(np.float32), -1.0, 1.0)
    return x, y_cls, y_reg


def _fit_norm(x_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


def _apply_norm(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((x - mean) / std).astype(np.float32)


def _build_bucket_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    buckets: dict[str, pd.Series] = {}
    buckets["state_name"] = df["state_name"].astype(str)

    def lead_bucket(x: float) -> str:
        x = _safe_float(x)
        if x <= -1.0:
            return "lagging"
        if x < 0.6:
            return "near_target"
        if x < 1.2:
            return "ahead_small"
        return "ahead_large"

    buckets["lead_bucket"] = df["lead_sec"].map(lead_bucket)
    buckets["playback_state"] = df["playback_state"].astype(str)
    return buckets


def _infer(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    model.eval()
    pred_cls = []
    pred_reg = []
    true_cls = []
    true_reg = []
    with torch.no_grad():
        for xb, yb_cls, yb_reg in loader:
            xb = xb.to(device)
            logits_cls, out_reg = model(xb)
            probs = torch.sigmoid(logits_cls).cpu().numpy()
            regs = torch.tanh(out_reg).cpu().numpy()
            pred_cls.append(probs)
            pred_reg.append(regs)
            true_cls.append(yb_cls.numpy())
            true_reg.append(yb_reg.numpy())
    return (
        np.concatenate(pred_cls, axis=0),
        np.concatenate(pred_reg, axis=0),
        np.concatenate(true_cls, axis=0),
        np.concatenate(true_reg, axis=0),
    )


def _action_acc(pred_cls: np.ndarray, true_cls: np.ndarray) -> float:
    return float(np.mean(pred_cls.argmax(axis=1) == true_cls.argmax(axis=1)))


def _class_metrics(pred_cls: np.ndarray, true_cls: np.ndarray) -> dict[str, Any]:
    pred_idx = pred_cls.argmax(axis=1)
    true_idx = true_cls.argmax(axis=1)
    out: dict[str, Any] = {"action_acc": float(np.mean(pred_idx == true_idx))}
    conf = {}
    for ti, tname in enumerate(ACTION_CLASS_TARGETS):
        row = {}
        for pi, pname in enumerate(ACTION_CLASS_TARGETS):
            row[pname] = int(np.sum((true_idx == ti) & (pred_idx == pi)))
        conf[tname] = row
    out["confusion_matrix"] = conf

    for name in ["hold", "resume", "seek"]:
        i = ACTION_CLASS_TARGETS.index(name)
        pred_pos = pred_idx == i
        true_pos = true_idx == i
        tp = int(np.sum(pred_pos & true_pos))
        fp = int(np.sum(pred_pos & (~true_pos)))
        fn = int(np.sum((~pred_pos) & true_pos))
        out[name] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": float(tp / max(1, tp + fp)),
            "recall": float(tp / max(1, tp + fn)),
        }
    return out


def _bucket_report(
    pred_cls: np.ndarray,
    true_cls: np.ndarray,
    pred_reg: np.ndarray,
    true_reg: np.ndarray,
    bucket_series: pd.Series,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for bucket in sorted(bucket_series.astype(str).unique().tolist()):
        mask = (bucket_series.astype(str) == bucket).values
        if int(mask.sum()) <= 0:
            continue
        out[bucket] = {
            "n": int(mask.sum()),
            "action": _class_metrics(pred_cls[mask], true_cls[mask]),
            "reg_mae": {
                "gain_bias": float(np.mean(np.abs(pred_reg[mask, 0] - true_reg[mask, 0]))),
                "seek_bias": float(np.mean(np.abs(pred_reg[mask, 1] - true_reg[mask, 1]))),
            },
        }
    return out


def _make_weights(y_cls_train: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
    pos_rate = np.clip(y_cls_train.mean(axis=0), 1e-4, 1.0 - 1e-4)
    neg_rate = 1.0 - pos_rate
    pos_weight = np.clip(neg_rate / pos_rate, 0.5, 20.0).astype(np.float32)
    alpha_pos = np.clip(1.0 - pos_rate, 0.25, 0.95).astype(np.float32)
    return torch.tensor(pos_weight), torch.tensor(alpha_pos)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--train-parquet", required=True)
    p.add_argument("--valid-parquet", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--epochs", type=int, default=24)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--hidden-dims", type=str, default="160,96")
    p.add_argument("--dropout", type=float, default=0.10)
    p.add_argument("--focal-gamma", type=float, default=2.0)
    p.add_argument("--reg-loss-weight", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed))

    train_df = pd.read_parquet(args.train_parquet).reset_index(drop=True)
    valid_df = pd.read_parquet(args.valid_parquet).reset_index(drop=True)

    x_train, y_cls_train, y_reg_train = _prepare_xy(train_df)
    x_valid, y_cls_valid, y_reg_valid = _prepare_xy(valid_df)

    mean, std = _fit_norm(x_train)
    x_train = _apply_norm(x_train, mean, std)
    x_valid = _apply_norm(x_valid, mean, std)

    train_ds = ActionDataset(x_train, y_cls_train, y_reg_train)
    valid_ds = ActionDataset(x_valid, y_cls_valid, y_reg_valid)

    train_loader = DataLoader(train_ds, batch_size=int(args.batch_size), shuffle=True, drop_last=False)
    valid_loader = DataLoader(valid_ds, batch_size=int(args.batch_size), shuffle=False, drop_last=False)

    hidden_dims = [int(x.strip()) for x in str(args.hidden_dims).split(",") if x.strip()]
    model = ActionMLP(
        input_dim=len(ACTION_FEATURE_NAMES),
        hidden_dims=hidden_dims,
        class_dim=len(ACTION_CLASS_TARGETS),
        reg_dim=len(ACTION_REG_TARGETS),
        dropout=float(args.dropout),
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    pos_weight, alpha_pos = _make_weights(y_cls_train)
    cls_criterion = WeightedFocalBCELoss(
        pos_weight=pos_weight.to(device),
        alpha_pos=alpha_pos.to(device),
        gamma=float(args.focal_gamma),
    )
    reg_criterion = nn.SmoothL1Loss()
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.lr))

    best_metric = -1.0
    best_payload: dict[str, Any] | None = None
    history = []

    valid_buckets = _build_bucket_series(valid_df)

    for epoch in range(1, int(args.epochs) + 1):
        model.train()
        running = 0.0
        n_batches = 0
        for xb, yb_cls, yb_reg in train_loader:
            xb = xb.to(device)
            yb_cls = yb_cls.to(device)
            yb_reg = yb_reg.to(device)

            optimizer.zero_grad()
            logits_cls, out_reg = model(xb)
            loss_cls = cls_criterion(logits_cls, yb_cls)
            loss_reg = reg_criterion(torch.tanh(out_reg), yb_reg)
            loss = loss_cls + float(args.reg_loss_weight) * loss_reg
            loss.backward()
            optimizer.step()

            running += float(loss.item())
            n_batches += 1

        pred_cls, pred_reg, true_cls, true_reg = _infer(model, valid_loader, device)
        action_acc = _action_acc(pred_cls, true_cls)
        reg_mae = float(np.mean(np.abs(pred_reg - true_reg)))
        score = float(action_acc - 0.15 * reg_mae)

        epoch_report = {
            "epoch": epoch,
            "train_loss": float(running / max(1, n_batches)),
            "valid_action_acc": action_acc,
            "valid_reg_mae": reg_mae,
            "valid_score": score,
            "valid_action_metrics": _class_metrics(pred_cls, true_cls),
            "bucketed": {
                name: _bucket_report(pred_cls, true_cls, pred_reg, true_reg, series)
                for name, series in valid_buckets.items()
            },
        }
        history.append(epoch_report)
        print(json.dumps(epoch_report, ensure_ascii=False))

        if score > best_metric:
            best_metric = score
            best_payload = {
                "model_type": "action_mlp",
                "input_dim": len(ACTION_FEATURE_NAMES),
                "hidden_dims": hidden_dims,
                "class_names": list(ACTION_CLASS_TARGETS),
                "reg_names": list(ACTION_REG_TARGETS),
                "feature_names": list(ACTION_FEATURE_NAMES),
                "normalization": {
                    "mean": mean.tolist(),
                    "std": std.tolist(),
                },
                "train_config": {
                    "epochs": int(args.epochs),
                    "batch_size": int(args.batch_size),
                    "lr": float(args.lr),
                    "dropout": float(args.dropout),
                    "focal_gamma": float(args.focal_gamma),
                    "reg_loss_weight": float(args.reg_loss_weight),
                    "seed": int(args.seed),
                    "cls_loss": "weighted_focal_bce",
                    "reg_loss": "smooth_l1",
                    "pos_weight": pos_weight.cpu().numpy().tolist(),
                    "alpha_pos": alpha_pos.cpu().numpy().tolist(),
                },
                "best_val_metric": float(best_metric),
                "state_dict": model.state_dict(),
            }

    if best_payload is None:
        raise RuntimeError("training failed: no checkpoint produced")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_payload, str(out_path))

    report_path = out_path.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(
            {
                "best_val_metric": float(best_metric),
                "history": history,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[saved] {out_path}")


if __name__ == "__main__":
    main()
    
shadowing_app/src/shadowing/training/train_fusion_model.py
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset


FUSION_FEATURE_NAMES = [
    "text_conf",
    "audio_conf",
    "tracking_quality",
    "progress_age_sec",
    "recently_progressed",
    "active_speaking",
    "stable",
    "still_following",
    "repeated",
    "reentry",
    "paused",
    "signal_conf",
    "signal_quality_score",
    "signal_silence",
    "dropout",
    "disagreement",
    "mode_repeat",
    "mode_reentry",
    "mode_recovery",
    "src_audio",
    "src_joint",
    "playback_vs_text",
    "playback_vs_audio",
]

FUSION_TARGET_NAMES = [
    "fused_confidence",
    "still_following",
    "repeated",
    "reentry",
    "prevent_hold",
    "prevent_seek",
    "widen_reacquire",
    "recenter_aligner",
    "audio_weight",
]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return float(v)


class TabularDataset(Dataset):
    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        self.x = torch.tensor(x, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32)

    def __len__(self) -> int:
        return int(self.x.shape[0])

    def __getitem__(self, idx: int):
        return self.x[idx], self.y[idx]


class SimpleMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list[int], output_dim: int, dropout: float = 0.10) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        cur = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(cur, h))
            layers.append(nn.ReLU())
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            cur = h
        layers.append(nn.Linear(cur, output_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


class WeightedFocalBCELoss(nn.Module):
    def __init__(
        self,
        pos_weight: torch.Tensor,
        alpha_pos: torch.Tensor,
        gamma: float = 2.0,
        reduction: str = "mean",
    ) -> None:
        super().__init__()
        self.register_buffer("pos_weight", pos_weight)
        self.register_buffer("alpha_pos", alpha_pos)
        self.gamma = float(gamma)
        self.reduction = reduction

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probs = torch.sigmoid(logits)
        bce = nn.functional.binary_cross_entropy_with_logits(
            logits,
            targets,
            reduction="none",
            pos_weight=self.pos_weight,
        )
        pt = probs * targets + (1.0 - probs) * (1.0 - targets)
        alpha = self.alpha_pos * targets + (1.0 - self.alpha_pos) * (1.0 - targets)
        focal = alpha * torch.pow(torch.clamp(1.0 - pt, min=1e-6), self.gamma) * bce
        if self.reduction == "mean":
            return focal.mean()
        if self.reduction == "sum":
            return focal.sum()
        return focal


def _prepare_xy(df: pd.DataFrame, feature_names: list[str], target_names: list[str]) -> tuple[np.ndarray, np.ndarray]:
    x = df[feature_names].values.astype(np.float32)
    y = np.clip(df[target_names].values.astype(np.float32), 0.0, 1.0)
    return x, y


def _fit_norm(x_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


def _apply_norm(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((x - mean) / std).astype(np.float32)


def _build_bucket_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    buckets: dict[str, pd.Series] = {}
    buckets["state_name"] = df["state_name"].astype(str)

    def disagreement_bucket(x: float) -> str:
        x = _safe_float(x)
        if x < 0.2:
            return "agree_strong"
        if x < 0.6:
            return "agree_soft"
        if x < 1.2:
            return "disagree_mid"
        return "disagree_hard"

    def audio_conf_bucket(x: float) -> str:
        x = _safe_float(x)
        if x < 0.35:
            return "audio_low"
        if x < 0.60:
            return "audio_mid"
        return "audio_high"

    buckets["disagreement_bucket"] = df["disagreement"].map(disagreement_bucket)
    buckets["audio_conf_bucket"] = df["audio_conf"].map(audio_conf_bucket)
    return buckets


def _mae_per_target(pred: np.ndarray, true: np.ndarray, target_names: list[str]) -> dict[str, float]:
    out = {}
    for i, name in enumerate(target_names):
        out[name] = float(np.mean(np.abs(pred[:, i] - true[:, i])))
    out["mean"] = float(np.mean(np.abs(pred - true)))
    return out


def _bucket_report(
    pred: np.ndarray,
    true: np.ndarray,
    bucket_series: pd.Series,
    target_names: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for bucket in sorted(bucket_series.astype(str).unique().tolist()):
        mask = (bucket_series.astype(str) == bucket).values
        if int(mask.sum()) <= 0:
            continue
        out[bucket] = {
            "n": int(mask.sum()),
            "mae": _mae_per_target(pred[mask], true[mask], target_names),
        }
    return out


def _infer(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    preds = []
    trues = []
    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            logits = model(xb)
            probs = torch.sigmoid(logits).cpu().numpy()
            preds.append(probs)
            trues.append(yb.numpy())
    return np.concatenate(preds, axis=0), np.concatenate(trues, axis=0)


def _make_weights(y_train: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
    pos_rate = np.clip(y_train.mean(axis=0), 1e-4, 1.0 - 1e-4)
    neg_rate = 1.0 - pos_rate
    pos_weight = np.clip(neg_rate / pos_rate, 0.5, 15.0).astype(np.float32)
    alpha_pos = np.clip(1.0 - pos_rate, 0.25, 0.92).astype(np.float32)
    return torch.tensor(pos_weight), torch.tensor(alpha_pos)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--train-parquet", required=True)
    p.add_argument("--valid-parquet", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--hidden-dims", type=str, default="128,64")
    p.add_argument("--dropout", type=float, default=0.10)
    p.add_argument("--focal-gamma", type=float, default=2.0)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed))

    train_df = pd.read_parquet(args.train_parquet).reset_index(drop=True)
    valid_df = pd.read_parquet(args.valid_parquet).reset_index(drop=True)

    x_train, y_train = _prepare_xy(train_df, FUSION_FEATURE_NAMES, FUSION_TARGET_NAMES)
    x_valid, y_valid = _prepare_xy(valid_df, FUSION_FEATURE_NAMES, FUSION_TARGET_NAMES)

    mean, std = _fit_norm(x_train)
    x_train = _apply_norm(x_train, mean, std)
    x_valid = _apply_norm(x_valid, mean, std)

    train_ds = TabularDataset(x_train, y_train)
    valid_ds = TabularDataset(x_valid, y_valid)

    train_loader = DataLoader(train_ds, batch_size=int(args.batch_size), shuffle=True, drop_last=False)
    valid_loader = DataLoader(valid_ds, batch_size=int(args.batch_size), shuffle=False, drop_last=False)

    hidden_dims = [int(x.strip()) for x in str(args.hidden_dims).split(",") if x.strip()]
    model = SimpleMLP(
        input_dim=len(FUSION_FEATURE_NAMES),
        hidden_dims=hidden_dims,
        output_dim=len(FUSION_TARGET_NAMES),
        dropout=float(args.dropout),
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    pos_weight, alpha_pos = _make_weights(y_train)
    criterion = WeightedFocalBCELoss(
        pos_weight=pos_weight.to(device),
        alpha_pos=alpha_pos.to(device),
        gamma=float(args.focal_gamma),
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.lr))

    best_metric = 1e9
    best_payload: dict[str, Any] | None = None
    history = []

    valid_buckets = _build_bucket_series(valid_df)

    for epoch in range(1, int(args.epochs) + 1):
        model.train()
        running = 0.0
        n_batches = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            running += float(loss.item())
            n_batches += 1

        pred_valid, true_valid = _infer(model, valid_loader, device)
        val_mae = float(np.mean(np.abs(pred_valid - true_valid)))

        epoch_report = {
            "epoch": epoch,
            "train_loss": float(running / max(1, n_batches)),
            "valid_mae": val_mae,
            "valid_mae_per_target": _mae_per_target(pred_valid, true_valid, FUSION_TARGET_NAMES),
            "bucketed": {
                name: _bucket_report(pred_valid, true_valid, series, FUSION_TARGET_NAMES)
                for name, series in valid_buckets.items()
            },
        }
        history.append(epoch_report)
        print(json.dumps(epoch_report, ensure_ascii=False))

        if val_mae < best_metric:
            best_metric = val_mae
            best_payload = {
                "model_type": "fusion_mlp",
                "input_dim": len(FUSION_FEATURE_NAMES),
                "hidden_dims": hidden_dims,
                "output_names": list(FUSION_TARGET_NAMES),
                "feature_names": list(FUSION_FEATURE_NAMES),
                "normalization": {
                    "mean": mean.tolist(),
                    "std": std.tolist(),
                },
                "train_config": {
                    "epochs": int(args.epochs),
                    "batch_size": int(args.batch_size),
                    "lr": float(args.lr),
                    "dropout": float(args.dropout),
                    "focal_gamma": float(args.focal_gamma),
                    "seed": int(args.seed),
                    "loss": "weighted_focal_bce",
                    "pos_weight": pos_weight.cpu().numpy().tolist(),
                    "alpha_pos": alpha_pos.cpu().numpy().tolist(),
                },
                "best_val_metric": float(best_metric),
                "state_dict": model.state_dict(),
            }

    if best_payload is None:
        raise RuntimeError("training failed: no checkpoint produced")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_payload, str(out_path))

    report_path = out_path.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(
            {
                "best_val_metric": float(best_metric),
                "history": history,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[saved] {out_path}")


if __name__ == "__main__":
    main()


shadowing_app/src/shadowing/training/train_audio_behavior_model.py
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset


BEHAVIOR_FEATURE_NAMES = [
    "match_conf",
    "local_similarity",
    "repeated_score",
    "drift_sec",
    "dtw_score",
    "dtw_coverage",
    "env_score",
    "onset_score",
    "band_score",
    "rhythm_score",
    "signal_conf",
    "silence_run_sec",
    "quality_score",
    "rms",
    "peak",
    "vad_active",
    "tracking_q",
    "joint_conf",
    "progress_recent",
    "progress_active",
    "progress_age",
    "position_source_audio",
    "position_source_joint",
    "mode_repeat",
    "mode_reentry",
    "mode_recovery",
    "prev_follow",
    "prev_repeat",
    "prev_reentry",
    "prev_pause",
]

BEHAVIOR_TARGET_NAMES = [
    "still_following",
    "repeated",
    "reentry",
    "paused",
    "confidence",
]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return float(v)


def _clip01(x: np.ndarray | float) -> np.ndarray | float:
    return np.clip(x, 0.0, 1.0)


class TabularDataset(Dataset):
    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        self.x = torch.tensor(x, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32)

    def __len__(self) -> int:
        return int(self.x.shape[0])

    def __getitem__(self, idx: int):
        return self.x[idx], self.y[idx]


class SimpleMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list[int], output_dim: int, dropout: float = 0.10) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        cur = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(cur, h))
            layers.append(nn.ReLU())
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            cur = h
        layers.append(nn.Linear(cur, output_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


class WeightedFocalBCELoss(nn.Module):
    def __init__(
        self,
        pos_weight: torch.Tensor,
        alpha_pos: torch.Tensor,
        gamma: float = 2.0,
        reduction: str = "mean",
    ) -> None:
        super().__init__()
        self.register_buffer("pos_weight", pos_weight)
        self.register_buffer("alpha_pos", alpha_pos)
        self.gamma = float(gamma)
        self.reduction = reduction

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probs = torch.sigmoid(logits)
        bce = nn.functional.binary_cross_entropy_with_logits(
            logits,
            targets,
            reduction="none",
            pos_weight=self.pos_weight,
        )
        pt = probs * targets + (1.0 - probs) * (1.0 - targets)
        alpha = self.alpha_pos * targets + (1.0 - self.alpha_pos) * (1.0 - targets)
        focal = alpha * torch.pow(torch.clamp(1.0 - pt, min=1e-6), self.gamma) * bce
        if self.reduction == "mean":
            return focal.mean()
        if self.reduction == "sum":
            return focal.sum()
        return focal


def _prepare_xy(df: pd.DataFrame, feature_names: list[str], target_names: list[str]) -> tuple[np.ndarray, np.ndarray]:
    x = df[feature_names].values.astype(np.float32)
    y = _clip01(df[target_names].values.astype(np.float32))
    return x, y


def _fit_norm(x_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


def _apply_norm(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((x - mean) / std).astype(np.float32)


def _build_bucket_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    buckets: dict[str, pd.Series] = {}
    buckets["state_name"] = df["state_name"].astype(str)

    def drift_bucket(x: float) -> str:
        x = _safe_float(x)
        if x <= -0.8:
            return "back_large"
        if x < -0.2:
            return "back_small"
        if x < 0.2:
            return "aligned"
        if x < 0.8:
            return "ahead_small"
        return "ahead_large"

    def silence_bucket(x: float) -> str:
        x = _safe_float(x)
        if x < 0.2:
            return "silence_0"
        if x < 0.7:
            return "silence_1"
        if x < 1.5:
            return "silence_2"
        return "silence_3"

    buckets["drift_bucket"] = df["drift_sec"].map(drift_bucket)
    buckets["silence_bucket"] = df["silence_run_sec"].map(silence_bucket)
    return buckets


def _mae_per_target(pred: np.ndarray, true: np.ndarray, target_names: list[str]) -> dict[str, float]:
    out = {}
    for i, name in enumerate(target_names):
        out[name] = float(np.mean(np.abs(pred[:, i] - true[:, i])))
    out["mean"] = float(np.mean(np.abs(pred - true)))
    return out


def _bucket_report(
    pred: np.ndarray,
    true: np.ndarray,
    bucket_series: pd.Series,
    target_names: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for bucket in sorted(bucket_series.astype(str).unique().tolist()):
        mask = (bucket_series.astype(str) == bucket).values
        if int(mask.sum()) <= 0:
            continue
        out[bucket] = {
            "n": int(mask.sum()),
            "mae": _mae_per_target(pred[mask], true[mask], target_names),
        }
    return out


def _infer(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    preds = []
    trues = []
    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device)
            logits = model(xb)
            probs = torch.sigmoid(logits).cpu().numpy()
            preds.append(probs)
            trues.append(yb.numpy())
    return np.concatenate(preds, axis=0), np.concatenate(trues, axis=0)


def _make_weights(y_train: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
    pos_rate = np.clip(y_train.mean(axis=0), 1e-4, 1.0 - 1e-4)
    neg_rate = 1.0 - pos_rate
    pos_weight = np.clip(neg_rate / pos_rate, 0.5, 12.0).astype(np.float32)
    alpha_pos = np.clip(1.0 - pos_rate, 0.25, 0.90).astype(np.float32)
    return torch.tensor(pos_weight), torch.tensor(alpha_pos)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--train-parquet", required=True)
    p.add_argument("--valid-parquet", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--hidden-dims", type=str, default="128,64")
    p.add_argument("--dropout", type=float, default=0.10)
    p.add_argument("--focal-gamma", type=float, default=2.0)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed))

    train_df = pd.read_parquet(args.train_parquet).reset_index(drop=True)
    valid_df = pd.read_parquet(args.valid_parquet).reset_index(drop=True)

    x_train, y_train = _prepare_xy(train_df, BEHAVIOR_FEATURE_NAMES, BEHAVIOR_TARGET_NAMES)
    x_valid, y_valid = _prepare_xy(valid_df, BEHAVIOR_FEATURE_NAMES, BEHAVIOR_TARGET_NAMES)

    mean, std = _fit_norm(x_train)
    x_train = _apply_norm(x_train, mean, std)
    x_valid = _apply_norm(x_valid, mean, std)

    train_ds = TabularDataset(x_train, y_train)
    valid_ds = TabularDataset(x_valid, y_valid)

    train_loader = DataLoader(train_ds, batch_size=int(args.batch_size), shuffle=True, drop_last=False)
    valid_loader = DataLoader(valid_ds, batch_size=int(args.batch_size), shuffle=False, drop_last=False)

    hidden_dims = [int(x.strip()) for x in str(args.hidden_dims).split(",") if x.strip()]
    model = SimpleMLP(
        input_dim=len(BEHAVIOR_FEATURE_NAMES),
        hidden_dims=hidden_dims,
        output_dim=len(BEHAVIOR_TARGET_NAMES),
        dropout=float(args.dropout),
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    pos_weight, alpha_pos = _make_weights(y_train)
    criterion = WeightedFocalBCELoss(
        pos_weight=pos_weight.to(device),
        alpha_pos=alpha_pos.to(device),
        gamma=float(args.focal_gamma),
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.lr))

    best_metric = 1e9
    best_payload: dict[str, Any] | None = None
    history = []

    valid_buckets = _build_bucket_series(valid_df)

    for epoch in range(1, int(args.epochs) + 1):
        model.train()
        running = 0.0
        n_batches = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            running += float(loss.item())
            n_batches += 1

        pred_valid, true_valid = _infer(model, valid_loader, device)
        val_mae = float(np.mean(np.abs(pred_valid - true_valid)))

        epoch_report = {
            "epoch": epoch,
            "train_loss": float(running / max(1, n_batches)),
            "valid_mae": val_mae,
            "valid_mae_per_target": _mae_per_target(pred_valid, true_valid, BEHAVIOR_TARGET_NAMES),
            "bucketed": {
                name: _bucket_report(pred_valid, true_valid, series, BEHAVIOR_TARGET_NAMES)
                for name, series in valid_buckets.items()
            },
        }
        history.append(epoch_report)
        print(json.dumps(epoch_report, ensure_ascii=False))

        if val_mae < best_metric:
            best_metric = val_mae
            best_payload = {
                "model_type": "audio_behavior_mlp",
                "input_dim": len(BEHAVIOR_FEATURE_NAMES),
                "hidden_dims": hidden_dims,
                "output_names": list(BEHAVIOR_TARGET_NAMES),
                "feature_names": list(BEHAVIOR_FEATURE_NAMES),
                "normalization": {
                    "mean": mean.tolist(),
                    "std": std.tolist(),
                },
                "train_config": {
                    "epochs": int(args.epochs),
                    "batch_size": int(args.batch_size),
                    "lr": float(args.lr),
                    "dropout": float(args.dropout),
                    "focal_gamma": float(args.focal_gamma),
                    "seed": int(args.seed),
                    "loss": "weighted_focal_bce",
                    "pos_weight": pos_weight.cpu().numpy().tolist(),
                    "alpha_pos": alpha_pos.cpu().numpy().tolist(),
                },
                "best_val_metric": float(best_metric),
                "state_dict": model.state_dict(),
            }

    if best_payload is None:
        raise RuntimeError("training failed: no checkpoint produced")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_payload, str(out_path))

    report_path = out_path.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(
            {
                "best_val_metric": float(best_metric),
                "history": history,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[saved] {out_path}")


if __name__ == "__main__":
    main()



shadowing_app/src/shadowing/training/eval_offline.py
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn


BEHAVIOR_FEATURE_NAMES = [
    "match_conf",
    "local_similarity",
    "repeated_score",
    "drift_sec",
    "dtw_score",
    "dtw_coverage",
    "env_score",
    "onset_score",
    "band_score",
    "rhythm_score",
    "signal_conf",
    "silence_run_sec",
    "quality_score",
    "rms",
    "peak",
    "vad_active",
    "tracking_q",
    "joint_conf",
    "progress_recent",
    "progress_active",
    "progress_age",
    "position_source_audio",
    "position_source_joint",
    "mode_repeat",
    "mode_reentry",
    "mode_recovery",
    "prev_follow",
    "prev_repeat",
    "prev_reentry",
    "prev_pause",
]

FUSION_FEATURE_NAMES = [
    "text_conf",
    "audio_conf",
    "tracking_quality",
    "progress_age_sec",
    "recently_progressed",
    "active_speaking",
    "stable",
    "still_following",
    "repeated",
    "reentry",
    "paused",
    "signal_conf",
    "signal_quality_score",
    "signal_silence",
    "dropout",
    "disagreement",
    "mode_repeat",
    "mode_reentry",
    "mode_recovery",
    "src_audio",
    "src_joint",
    "playback_vs_text",
    "playback_vs_audio",
]

ACTION_FEATURE_NAMES = [
    "playback_playing",
    "playback_holding",
    "playback_seeking",
    "lead_sec",
    "lead_error_sec",
    "tracking_quality",
    "confidence",
    "speech_conf",
    "progress_age_sec",
    "active_speaking",
    "recently_progressed",
    "stable",
    "speaking_recent",
    "engaged_recent",
    "fusion_still_following",
    "fusion_repeated",
    "fusion_reentry",
    "fusion_fused_conf",
    "in_startup_grace",
    "in_resume_cooldown",
    "in_seek_cooldown",
    "allow_seek",
    "bluetooth_mode",
    "bluetooth_long_session_mode",
    "tracking_state_weak",
    "tracking_state_reliable",
    "tracking_state_locked",
    "sync_state_converging",
    "sync_state_stable",
    "sync_state_degraded",
    "position_source_audio",
    "position_source_joint",
    "hold_pressure",
    "resume_pressure",
    "seek_pressure",
    "soft_duck_pressure",
    "lead_error_ema",
    "lead_error_derivative_ema",
    "tracking_quality_ema",
    "confidence_ema",
    "speech_confidence_ema",
]

ACTION_CLASS_TARGETS = ["noop", "soft_duck", "hold", "resume", "seek"]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return float(v)


class SimpleMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list[int], output_dim: int) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        cur = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(cur, h))
            layers.append(nn.ReLU())
            cur = h
        layers.append(nn.Linear(cur, output_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


class ActionMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list[int], class_dim: int, reg_dim: int) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        cur = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(cur, h))
            layers.append(nn.ReLU())
            cur = h
        self.backbone = nn.Sequential(*layers)
        self.class_head = nn.Linear(cur, class_dim)
        self.reg_head = nn.Linear(cur, reg_dim)

    def forward(self, x):
        h = self.backbone(x)
        return self.class_head(h), self.reg_head(h)


def _load_behavior_model(path: Path):
    ckpt = torch.load(str(path), map_location="cpu")
    model = SimpleMLP(
        input_dim=int(ckpt["input_dim"]),
        hidden_dims=list(ckpt["hidden_dims"]),
        output_dim=len(ckpt["output_names"]),
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


def _load_fusion_model(path: Path):
    ckpt = torch.load(str(path), map_location="cpu")
    model = SimpleMLP(
        input_dim=int(ckpt["input_dim"]),
        hidden_dims=list(ckpt["hidden_dims"]),
        output_dim=len(ckpt["output_names"]),
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


def _load_action_model(path: Path):
    ckpt = torch.load(str(path), map_location="cpu")
    model = ActionMLP(
        input_dim=int(ckpt["input_dim"]),
        hidden_dims=list(ckpt["hidden_dims"]),
        class_dim=5,
        reg_dim=2,
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


def _predict_behavior_rule(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["still_following"] = np.clip(
        0.48 * df["match_conf"] + 0.22 * df["local_similarity"] + 0.30 * df["signal_conf"],
        0.0,
        1.0,
    )
    out["repeated"] = np.clip(df["repeated_score"], 0.0, 1.0)
    out["reentry"] = np.clip(
        0.55 * df["mode_reentry"] + 0.25 * df["signal_conf"] + 0.20 * (1.0 - np.minimum(1.0, df["silence_run_sec"])),
        0.0,
        1.0,
    )
    out["paused"] = np.clip(
        0.70 * np.minimum(1.0, df["silence_run_sec"] / 1.2) + 0.20 * (1.0 - df["signal_conf"]),
        0.0,
        1.0,
    )
    out["confidence"] = np.maximum.reduce(
        [out["still_following"].values, out["repeated"].values, out["reentry"].values, 1.0 - out["paused"].values]
    )
    return out


def _predict_fusion_rule(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    audio_weight = np.clip(
        np.where(
            (df["audio_conf"] >= 0.66) & (df["disagreement"] <= 1.3) & (df["repeated"] < 0.66) & (df["paused"] < 0.78),
            0.58 + 0.24 * df["audio_conf"] - 0.14 * df["disagreement"],
            0.24 + 0.28 * df["audio_conf"] - 0.10 * df["disagreement"],
        ),
        0.0,
        1.0,
    )
    out["audio_weight"] = audio_weight
    out["fused_confidence"] = np.clip(
        (1.0 - audio_weight) * df["text_conf"]
        + audio_weight * df["audio_conf"]
        + 0.06 * df["still_following"]
        - 0.05 * df["repeated"],
        0.0,
        1.0,
    )
    out["still_following"] = np.clip(df["still_following"], 0.0, 1.0)
    out["repeated"] = np.clip(df["repeated"], 0.0, 1.0)
    out["reentry"] = np.clip(df["reentry"], 0.0, 1.0)
    out["prevent_hold"] = (((df["still_following"] >= 0.64) | (df["reentry"] >= 0.58)) & (df["paused"] < 0.80)).astype(float)
    out["prevent_seek"] = (((df["repeated"] >= 0.54) | (df["reentry"] >= 0.56) | (df["still_following"] >= 0.78))).astype(float)
    out["widen_reacquire"] = (((df["audio_conf"] >= 0.54) | (df["reentry"] >= 0.54) | (df["repeated"] >= 0.52))).astype(float)
    out["recenter_aligner"] = (((df["audio_conf"] >= 0.68) & ((df["reentry"] >= 0.52) | (df["disagreement"] >= 0.95)))).astype(float)
    return out


def _predict_action_rule(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        scores = {"noop": 0.16, "soft_duck": 0.18, "hold": 0.08, "resume": 0.06, "seek": 0.04}
        if r["in_startup_grace"] >= 0.5:
            scores["noop"] += 0.75
        else:
            is_holding = r["playback_holding"] >= 0.5
            engaged = r["engaged_recent"] >= 0.5
            if is_holding:
                if engaged and r["lead_error_sec"] >= -0.72 and r["tracking_quality"] >= 0.50:
                    scores["resume"] += 1.18
                else:
                    scores["noop"] += 0.48
            else:
                if r["lead_sec"] >= 1.05 and (not engaged) and r["fusion_repeated"] < 0.60 and r["fusion_reentry"] < 0.54:
                    scores["hold"] += 1.15
                elif (
                    r["lead_sec"] <= -2.60
                    and r["allow_seek"] >= 0.5
                    and r["fusion_repeated"] < 0.42
                    and r["fusion_reentry"] < 0.42
                    and (not engaged)
                ):
                    scores["seek"] += 1.16
                elif r["lead_sec"] >= 0.78 or r["progress_age_sec"] >= 1.40 or r["tracking_quality"] < 0.50:
                    scores["soft_duck"] += 0.98
                else:
                    scores["noop"] += 0.82

        arr = np.asarray([scores[k] for k in ACTION_CLASS_TARGETS], dtype=np.float32)
        arr = arr - np.max(arr)
        ex = np.exp(arr)
        p = ex / max(1e-8, np.sum(ex))

        gain_bias = 0.0
        if p[ACTION_CLASS_TARGETS.index("soft_duck")] >= 0.45:
            gain_bias = -0.22
        elif p[ACTION_CLASS_TARGETS.index("hold")] >= 0.45:
            gain_bias = -0.38
        elif p[ACTION_CLASS_TARGETS.index("resume")] >= 0.45:
            gain_bias = 0.18

        seek_bias = 0.0
        if p[ACTION_CLASS_TARGETS.index("seek")] >= 0.45:
            seek_bias = min(1.0, abs(float(r["lead_sec"])) / 4.0)

        rows.append(
            {
                "noop": float(p[0]),
                "soft_duck": float(p[1]),
                "hold": float(p[2]),
                "resume": float(p[3]),
                "seek": float(p[4]),
                "gain_bias": float(gain_bias),
                "seek_bias": float(seek_bias),
            }
        )
    return pd.DataFrame(rows)


def _predict_behavior_model(df: pd.DataFrame, model: nn.Module) -> pd.DataFrame:
    x = torch.tensor(df[BEHAVIOR_FEATURE_NAMES].values.astype(np.float32))
    with torch.no_grad():
        y = torch.sigmoid(model(x)).cpu().numpy()
    return pd.DataFrame(y, columns=["still_following", "repeated", "reentry", "paused", "confidence"])


def _predict_fusion_model(df: pd.DataFrame, model: nn.Module) -> pd.DataFrame:
    x = torch.tensor(df[FUSION_FEATURE_NAMES].values.astype(np.float32))
    with torch.no_grad():
        y = torch.sigmoid(model(x)).cpu().numpy()
    return pd.DataFrame(
        y,
        columns=[
            "fused_confidence",
            "still_following",
            "repeated",
            "reentry",
            "prevent_hold",
            "prevent_seek",
            "widen_reacquire",
            "recenter_aligner",
            "audio_weight",
        ],
    )


def _predict_action_model(df: pd.DataFrame, model: nn.Module) -> pd.DataFrame:
    x = torch.tensor(df[ACTION_FEATURE_NAMES].values.astype(np.float32))
    with torch.no_grad():
        cls_logits, reg_out = model(x)
        cls_probs = torch.sigmoid(cls_logits).cpu().numpy()
        reg_vals = torch.tanh(reg_out).cpu().numpy()
    out = pd.DataFrame(cls_probs, columns=ACTION_CLASS_TARGETS)
    out["gain_bias"] = reg_vals[:, 0]
    out["seek_bias"] = reg_vals[:, 1]
    return out


def _argmax_label(df: pd.DataFrame) -> np.ndarray:
    return df[ACTION_CLASS_TARGETS].values.argmax(axis=1)


def _confusion(pred_df: pd.DataFrame, true_df: pd.DataFrame) -> dict[str, dict[str, int]]:
    pred_idx = _argmax_label(pred_df)
    true_idx = _argmax_label(true_df)
    out = {}
    for ti, tname in enumerate(ACTION_CLASS_TARGETS):
        row = {}
        for pi, pname in enumerate(ACTION_CLASS_TARGETS):
            row[pname] = int(np.sum((true_idx == ti) & (pred_idx == pi)))
        out[tname] = row
    return out


def _action_metrics(pred_df: pd.DataFrame, true_df: pd.DataFrame) -> dict[str, Any]:
    pred_idx = _argmax_label(pred_df)
    true_idx = _argmax_label(true_df)
    acc = float(np.mean(pred_idx == true_idx))

    metrics: dict[str, Any] = {"action_acc": acc, "confusion_matrix": _confusion(pred_df, true_df)}
    for name in ["hold", "resume", "seek"]:
        pi = ACTION_CLASS_TARGETS.index(name)
        pred_pos = pred_idx == pi
        true_pos = true_idx == pi
        tp = int(np.sum(pred_pos & true_pos))
        fp = int(np.sum(pred_pos & (~true_pos)))
        fn = int(np.sum((~pred_pos) & true_pos))
        precision = float(tp / max(1, tp + fp))
        recall = float(tp / max(1, tp + fn))
        metrics[name] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "fp_rate": float(np.mean(pred_pos & (~true_pos))),
            "fn_rate": float(np.mean((~pred_pos) & true_pos)),
        }
    return metrics


def _prob_mae(pred_df: pd.DataFrame, true_df: pd.DataFrame, cols: list[str]) -> float:
    return float(np.mean(np.abs(pred_df[cols].values - true_df[cols].values)))


def _lead_bucket(x: float) -> str:
    if x <= -1.0:
        return "lagging"
    if x < 0.6:
        return "near_target"
    if x < 1.2:
        return "ahead_small"
    return "ahead_large"


def _bucket_eval(action_true: pd.DataFrame, action_pred: pd.DataFrame, bucket_series: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for bucket in sorted(bucket_series.astype(str).unique().tolist()):
        mask = bucket_series.astype(str) == bucket
        if int(np.sum(mask)) <= 0:
            continue
        sub_true = action_true.loc[mask].reset_index(drop=True)
        sub_pred = action_pred.loc[mask].reset_index(drop=True)
        out[bucket] = _action_metrics(sub_pred, sub_true)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--behavior-parquet", required=True)
    p.add_argument("--fusion-parquet", required=True)
    p.add_argument("--action-parquet", required=True)
    p.add_argument("--behavior-model", default="")
    p.add_argument("--fusion-model", default="")
    p.add_argument("--action-model", default="")
    p.add_argument("--output-json", default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    behavior_df = pd.read_parquet(args.behavior_parquet).reset_index(drop=True)
    fusion_df = pd.read_parquet(args.fusion_parquet).reset_index(drop=True)
    action_df = pd.read_parquet(args.action_parquet).reset_index(drop=True)

    rule_behavior = _predict_behavior_rule(behavior_df)
    rule_fusion = _predict_fusion_rule(fusion_df)
    rule_action = _predict_action_rule(action_df)

    report: dict[str, Any] = {
        "rule": {
            "behavior_mae": _prob_mae(
                rule_behavior,
                behavior_df,
                ["still_following", "repeated", "reentry", "paused", "confidence"],
            ),
            "fusion_mae": _prob_mae(
                rule_fusion,
                fusion_df,
                [
                    "fused_confidence",
                    "still_following",
                    "repeated",
                    "reentry",
                    "prevent_hold",
                    "prevent_seek",
                    "widen_reacquire",
                    "recenter_aligner",
                    "audio_weight",
                ],
            ),
            "action": _action_metrics(rule_action, action_df),
            "by_state": _bucket_eval(action_df, rule_action, action_df["state_name"]),
            "by_lead_bucket": _bucket_eval(action_df, rule_action, action_df["lead_sec"].map(_lead_bucket)),
        }
    }

    if args.behavior_model:
        model = _load_behavior_model(Path(args.behavior_model))
        pred = _predict_behavior_model(behavior_df, model)
        report.setdefault("model", {})
        report["model"]["behavior_mae"] = _prob_mae(
            pred,
            behavior_df,
            ["still_following", "repeated", "reentry", "paused", "confidence"],
        )

    if args.fusion_model:
        model = _load_fusion_model(Path(args.fusion_model))
        pred = _predict_fusion_model(fusion_df, model)
        report.setdefault("model", {})
        report["model"]["fusion_mae"] = _prob_mae(
            pred,
            fusion_df,
            [
                "fused_confidence",
                "still_following",
                "repeated",
                "reentry",
                "prevent_hold",
                "prevent_seek",
                "widen_reacquire",
                "recenter_aligner",
                "audio_weight",
            ],
        )

    if args.action_model:
        model = _load_action_model(Path(args.action_model))
        pred = _predict_action_model(action_df, model)
        report.setdefault("model", {})
        report["model"]["action"] = _action_metrics(pred, action_df)
        report["model"]["by_state"] = _bucket_eval(action_df, pred, action_df["state_name"])
        report["model"]["by_lead_bucket"] = _bucket_eval(action_df, pred, action_df["lead_sec"].map(_lead_bucket))

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)

    if args.output_json:
        Path(args.output_json).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()




shadowing_app/src/shadowing/training/eval_offline.py
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn


BEHAVIOR_FEATURE_NAMES = [
    "match_conf",
    "local_similarity",
    "repeated_score",
    "drift_sec",
    "dtw_score",
    "dtw_coverage",
    "env_score",
    "onset_score",
    "band_score",
    "rhythm_score",
    "signal_conf",
    "silence_run_sec",
    "quality_score",
    "rms",
    "peak",
    "vad_active",
    "tracking_q",
    "joint_conf",
    "progress_recent",
    "progress_active",
    "progress_age",
    "position_source_audio",
    "position_source_joint",
    "mode_repeat",
    "mode_reentry",
    "mode_recovery",
    "prev_follow",
    "prev_repeat",
    "prev_reentry",
    "prev_pause",
]

FUSION_FEATURE_NAMES = [
    "text_conf",
    "audio_conf",
    "tracking_quality",
    "progress_age_sec",
    "recently_progressed",
    "active_speaking",
    "stable",
    "still_following",
    "repeated",
    "reentry",
    "paused",
    "signal_conf",
    "signal_quality_score",
    "signal_silence",
    "dropout",
    "disagreement",
    "mode_repeat",
    "mode_reentry",
    "mode_recovery",
    "src_audio",
    "src_joint",
    "playback_vs_text",
    "playback_vs_audio",
]

ACTION_FEATURE_NAMES = [
    "playback_playing",
    "playback_holding",
    "playback_seeking",
    "lead_sec",
    "lead_error_sec",
    "tracking_quality",
    "confidence",
    "speech_conf",
    "progress_age_sec",
    "active_speaking",
    "recently_progressed",
    "stable",
    "speaking_recent",
    "engaged_recent",
    "fusion_still_following",
    "fusion_repeated",
    "fusion_reentry",
    "fusion_fused_conf",
    "in_startup_grace",
    "in_resume_cooldown",
    "in_seek_cooldown",
    "allow_seek",
    "bluetooth_mode",
    "bluetooth_long_session_mode",
    "tracking_state_weak",
    "tracking_state_reliable",
    "tracking_state_locked",
    "sync_state_converging",
    "sync_state_stable",
    "sync_state_degraded",
    "position_source_audio",
    "position_source_joint",
    "hold_pressure",
    "resume_pressure",
    "seek_pressure",
    "soft_duck_pressure",
    "lead_error_ema",
    "lead_error_derivative_ema",
    "tracking_quality_ema",
    "confidence_ema",
    "speech_confidence_ema",
]

ACTION_CLASS_TARGETS = ["noop", "soft_duck", "hold", "resume", "seek"]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return float(v)


class SimpleMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list[int], output_dim: int) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        cur = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(cur, h))
            layers.append(nn.ReLU())
            cur = h
        layers.append(nn.Linear(cur, output_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


class ActionMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list[int], class_dim: int, reg_dim: int) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        cur = input_dim
        for h in hidden_dims:
            layers.append(nn.Linear(cur, h))
            layers.append(nn.ReLU())
            cur = h
        self.backbone = nn.Sequential(*layers)
        self.class_head = nn.Linear(cur, class_dim)
        self.reg_head = nn.Linear(cur, reg_dim)

    def forward(self, x):
        h = self.backbone(x)
        return self.class_head(h), self.reg_head(h)


def _load_behavior_model(path: Path):
    ckpt = torch.load(str(path), map_location="cpu")
    model = SimpleMLP(
        input_dim=int(ckpt["input_dim"]),
        hidden_dims=list(ckpt["hidden_dims"]),
        output_dim=len(ckpt["output_names"]),
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


def _load_fusion_model(path: Path):
    ckpt = torch.load(str(path), map_location="cpu")
    model = SimpleMLP(
        input_dim=int(ckpt["input_dim"]),
        hidden_dims=list(ckpt["hidden_dims"]),
        output_dim=len(ckpt["output_names"]),
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


def _load_action_model(path: Path):
    ckpt = torch.load(str(path), map_location="cpu")
    class_dim = 5
    reg_dim = 2
    model = ActionMLP(
        input_dim=int(ckpt["input_dim"]),
        hidden_dims=list(ckpt["hidden_dims"]),
        class_dim=class_dim,
        reg_dim=reg_dim,
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


def _predict_behavior_rule(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["still_following"] = np.clip(
        0.48 * df["match_conf"] + 0.22 * df["local_similarity"] + 0.30 * df["signal_conf"],
        0.0,
        1.0,
    )
    out["repeated"] = np.clip(df["repeated_score"], 0.0, 1.0)
    out["reentry"] = np.clip(
        0.55 * df["mode_reentry"] + 0.25 * df["signal_conf"] + 0.20 * (1.0 - np.minimum(1.0, df["silence_run_sec"])),
        0.0,
        1.0,
    )
    out["paused"] = np.clip(
        0.70 * np.minimum(1.0, df["silence_run_sec"] / 1.2) + 0.20 * (1.0 - df["signal_conf"]),
        0.0,
        1.0,
    )
    out["confidence"] = np.maximum.reduce(
        [out["still_following"].values, out["repeated"].values, out["reentry"].values, 1.0 - out["paused"].values]
    )
    return out


def _predict_fusion_rule(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    audio_weight = np.clip(
        np.where(
            (df["audio_conf"] >= 0.66) & (df["disagreement"] <= 1.3) & (df["repeated"] < 0.66) & (df["paused"] < 0.78),
            0.58 + 0.24 * df["audio_conf"] - 0.14 * df["disagreement"],
            0.24 + 0.28 * df["audio_conf"] - 0.10 * df["disagreement"],
        ),
        0.0,
        1.0,
    )
    out["audio_weight"] = audio_weight
    out["fused_confidence"] = np.clip(
        (1.0 - audio_weight) * df["text_conf"]
        + audio_weight * df["audio_conf"]
        + 0.06 * df["still_following"]
        - 0.05 * df["repeated"],
        0.0,
        1.0,
    )
    out["still_following"] = np.clip(df["still_following"], 0.0, 1.0)
    out["repeated"] = np.clip(df["repeated"], 0.0, 1.0)
    out["reentry"] = np.clip(df["reentry"], 0.0, 1.0)
    out["prevent_hold"] = (((df["still_following"] >= 0.64) | (df["reentry"] >= 0.58)) & (df["paused"] < 0.80)).astype(float)
    out["prevent_seek"] = (
        ((df["repeated"] >= 0.54) | (df["reentry"] >= 0.56) | (df["still_following"] >= 0.78))
    ).astype(float)
    out["widen_reacquire"] = (
        ((df["audio_conf"] >= 0.54) | (df["reentry"] >= 0.54) | (df["repeated"] >= 0.52))
    ).astype(float)
    out["recenter_aligner"] = (
        (df["audio_conf"] >= 0.68) & ((df["reentry"] >= 0.52) | (df["disagreement"] >= 0.95))
    ).astype(float)
    return out


def _predict_action_rule(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        scores = {"noop": 0.20, "soft_duck": 0.20, "hold": 0.10, "resume": 0.05, "seek": 0.05}
        if r["in_startup_grace"] >= 0.5:
            scores["noop"] += 0.60
        else:
            is_holding = r["playback_holding"] >= 0.5
            engaged = r["engaged_recent"] >= 0.5
            if is_holding:
                if engaged and r["lead_error_sec"] >= -0.72 and r["tracking_quality"] >= 0.50:
                    scores["resume"] += 1.10
                else:
                    scores["noop"] += 0.40
            else:
                if r["lead_sec"] >= 1.05 and (not engaged) and r["fusion_repeated"] < 0.60 and r["fusion_reentry"] < 0.54:
                    scores["hold"] += 1.05
                elif (
                    r["lead_sec"] <= -2.60
                    and r["allow_seek"] >= 0.5
                    and r["fusion_repeated"] < 0.42
                    and r["fusion_reentry"] < 0.42
                    and (not engaged)
                ):
                    scores["seek"] += 1.10
                elif r["lead_sec"] >= 0.80 or r["progress_age_sec"] >= 1.45 or r["tracking_quality"] < 0.50:
                    scores["soft_duck"] += 0.90
                else:
                    scores["noop"] += 0.75

        arr = np.asarray([scores[k] for k in ACTION_CLASS_TARGETS], dtype=np.float32)
        arr = arr - np.max(arr)
        ex = np.exp(arr)
        p = ex / max(1e-8, np.sum(ex))

        gain_bias = 0.0
        if p[ACTION_CLASS_TARGETS.index("soft_duck")] >= 0.45:
            gain_bias = -0.22
        elif p[ACTION_CLASS_TARGETS.index("hold")] >= 0.45:
            gain_bias = -0.38
        elif p[ACTION_CLASS_TARGETS.index("resume")] >= 0.45:
            gain_bias = 0.18

        seek_bias = 0.0
        if p[ACTION_CLASS_TARGETS.index("seek")] >= 0.45:
            seek_bias = min(1.0, abs(float(r["lead_sec"])) / 4.0)

        rows.append(
            {
                "noop": float(p[0]),
                "soft_duck": float(p[1]),
                "hold": float(p[2]),
                "resume": float(p[3]),
                "seek": float(p[4]),
                "gain_bias": float(gain_bias),
                "seek_bias": float(seek_bias),
            }
        )
    return pd.DataFrame(rows)


def _predict_behavior_model(df: pd.DataFrame, model: nn.Module) -> pd.DataFrame:
    x = torch.tensor(df[BEHAVIOR_FEATURE_NAMES].values.astype(np.float32))
    with torch.no_grad():
        y = torch.sigmoid(model(x)).cpu().numpy()
    return pd.DataFrame(y, columns=["still_following", "repeated", "reentry", "paused", "confidence"])


def _predict_fusion_model(df: pd.DataFrame, model: nn.Module) -> pd.DataFrame:
    x = torch.tensor(df[FUSION_FEATURE_NAMES].values.astype(np.float32))
    with torch.no_grad():
        y = torch.sigmoid(model(x)).cpu().numpy()
    return pd.DataFrame(
        y,
        columns=[
            "fused_confidence",
            "still_following",
            "repeated",
            "reentry",
            "prevent_hold",
            "prevent_seek",
            "widen_reacquire",
            "recenter_aligner",
            "audio_weight",
        ],
    )


def _predict_action_model(df: pd.DataFrame, model: nn.Module) -> pd.DataFrame:
    x = torch.tensor(df[ACTION_FEATURE_NAMES].values.astype(np.float32))
    with torch.no_grad():
        cls_logits, reg_out = model(x)
        cls_probs = torch.sigmoid(cls_logits).cpu().numpy()
        reg_vals = torch.tanh(reg_out).cpu().numpy()
    out = pd.DataFrame(cls_probs, columns=ACTION_CLASS_TARGETS)
    out["gain_bias"] = reg_vals[:, 0]
    out["seek_bias"] = reg_vals[:, 1]
    return out


def _argmax_label(df: pd.DataFrame) -> np.ndarray:
    return df[ACTION_CLASS_TARGETS].values.argmax(axis=1)


def _action_metrics(pred_df: pd.DataFrame, true_df: pd.DataFrame) -> dict[str, float]:
    pred_idx = _argmax_label(pred_df)
    true_idx = _argmax_label(true_df)
    acc = float(np.mean(pred_idx == true_idx))

    metrics = {"action_acc": acc}
    for name in ["hold", "resume", "seek"]:
        pi = ACTION_CLASS_TARGETS.index(name)
        pred_pos = pred_idx == pi
        true_pos = true_idx == pi
        fp = float(np.mean(pred_pos & (~true_pos)))
        fn = float(np.mean((~pred_pos) & true_pos))
        metrics[f"{name}_fp_rate"] = fp
        metrics[f"{name}_fn_rate"] = fn
    return metrics


def _prob_mae(pred_df: pd.DataFrame, true_df: pd.DataFrame, cols: list[str]) -> float:
    return float(np.mean(np.abs(pred_df[cols].values - true_df[cols].values)))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--behavior-parquet", required=True)
    p.add_argument("--fusion-parquet", required=True)
    p.add_argument("--action-parquet", required=True)
    p.add_argument("--behavior-model", default="")
    p.add_argument("--fusion-model", default="")
    p.add_argument("--action-model", default="")
    p.add_argument("--output-json", default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    behavior_df = pd.read_parquet(args.behavior_parquet).reset_index(drop=True)
    fusion_df = pd.read_parquet(args.fusion_parquet).reset_index(drop=True)
    action_df = pd.read_parquet(args.action_parquet).reset_index(drop=True)

    rule_behavior = _predict_behavior_rule(behavior_df)
    rule_fusion = _predict_fusion_rule(fusion_df)
    rule_action = _predict_action_rule(action_df)

    report = {
        "rule": {
            "behavior_mae": _prob_mae(
                rule_behavior,
                behavior_df,
                ["still_following", "repeated", "reentry", "paused", "confidence"],
            ),
            "fusion_mae": _prob_mae(
                rule_fusion,
                fusion_df,
                [
                    "fused_confidence",
                    "still_following",
                    "repeated",
                    "reentry",
                    "prevent_hold",
                    "prevent_seek",
                    "widen_reacquire",
                    "recenter_aligner",
                    "audio_weight",
                ],
            ),
            "action": _action_metrics(rule_action, action_df),
        }
    }

    if args.behavior_model:
        model = _load_behavior_model(Path(args.behavior_model))
        pred = _predict_behavior_model(behavior_df, model)
        report.setdefault("model", {})
        report["model"]["behavior_mae"] = _prob_mae(
            pred,
            behavior_df,
            ["still_following", "repeated", "reentry", "paused", "confidence"],
        )

    if args.fusion_model:
        model = _load_fusion_model(Path(args.fusion_model))
        pred = _predict_fusion_model(fusion_df, model)
        report.setdefault("model", {})
        report["model"]["fusion_mae"] = _prob_mae(
            pred,
            fusion_df,
            [
                "fused_confidence",
                "still_following",
                "repeated",
                "reentry",
                "prevent_hold",
                "prevent_seek",
                "widen_reacquire",
                "recenter_aligner",
                "audio_weight",
            ],
        )

    if args.action_model:
        model = _load_action_model(Path(args.action_model))
        pred = _predict_action_model(action_df, model)
        report.setdefault("model", {})
        report["model"]["action"] = _action_metrics(pred, action_df)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)

    if args.output_json:
        Path(args.output_json).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()




shadowing_app/src/shadowing/realtime/control/state_machine_controller.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.sync_evidence import SyncEvidence, SyncState, TrackingState
from shadowing.types import ControlAction, ControlDecision, FusionEvidence, PlaybackState


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = pow(2.718281828459045, -x)
        return 1.0 / (1.0 + z)
    z = pow(2.718281828459045, x)
    return z / (1.0 + z)


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


class _TorchActionModel:
    """
    输出约定：
      [
        noop, soft_duck, hold, resume, seek,
        gain_bias, seek_bias
      ]

    前五个做 sigmoid，后两个做 tanh-like 压缩。
    """

    def __init__(self, model_path: str) -> None:
        self.model_path = str(model_path or "").strip()
        self.available = False
        self.output_names = [
            "noop",
            "soft_duck",
            "hold",
            "resume",
            "seek",
            "gain_bias",
            "seek_bias",
        ]
        self._torch = None
        self._model = None

        if not self.model_path:
            return
        path = Path(self.model_path)
        if not path.exists():
            return

        try:
            import torch
            import torch.nn as nn
        except Exception:
            return

        self._torch = torch

        try:
            jit_model = torch.jit.load(str(path), map_location="cpu")
            jit_model.eval()
            self._model = jit_model
            self.available = True
            return
        except Exception:
            pass

        try:
            blob = torch.load(str(path), map_location="cpu")
        except Exception:
            return

        if not isinstance(blob, dict):
            return

        input_dim = int(blob.get("input_dim", 0))
        hidden_dims = list(blob.get("hidden_dims", [64, 64]))
        state_dict = blob.get("state_dict", None)
        output_names = blob.get("output_names", None)
        if isinstance(output_names, list) and output_names:
            self.output_names = [str(x) for x in output_names]

        if input_dim <= 0 or state_dict is None:
            return

        class _MLP(nn.Module):
            def __init__(self, in_dim: int, h_dims: list[int], out_dim: int) -> None:
                super().__init__()
                layers: list[nn.Module] = []
                cur = in_dim
                for h in h_dims:
                    h = int(h)
                    if h <= 0:
                        continue
                    layers.append(nn.Linear(cur, h))
                    layers.append(nn.ReLU())
                    cur = h
                layers.append(nn.Linear(cur, out_dim))
                self.net = nn.Sequential(*layers)

            def forward(self, x):
                return self.net(x)

        out_dim = max(1, len(self.output_names))
        model = _MLP(input_dim, hidden_dims, out_dim)
        try:
            model.load_state_dict(state_dict, strict=False)
            model.eval()
            self._model = model
            self.available = True
        except Exception:
            self.available = False
            self._model = None

    def predict(self, features: list[float]) -> dict[str, float]:
        if not self.available or self._model is None or self._torch is None:
            return {}
        torch = self._torch
        try:
            x = torch.tensor([features], dtype=torch.float32)
            with torch.no_grad():
                y = self._model(x)
            vals = y.detach().cpu().numpy().reshape(-1).tolist()
        except Exception:
            return {}

        out: dict[str, float] = {}
        for i, name in enumerate(self.output_names):
            if i >= len(vals):
                break
            v = float(vals[i])
            if name in {"gain_bias", "seek_bias"}:
                out[name] = max(-1.0, min(1.0, v))
            else:
                out[name] = _sigmoid(v)
        return out


class StateMachineController:
    def __init__(
        self,
        *,
        policy: ControlPolicy,
        disable_seek: bool = False,
        debug: bool = False,
        action_model_path: str = "",
        action_model_blend: float = 0.55,
    ) -> None:
        self.policy = policy
        self.disable_seek = bool(disable_seek)
        self.debug = bool(debug)

        self.action_model_path = str(action_model_path or "").strip()
        self.action_model_blend = _clamp01(action_model_blend)
        self._action_model = _TorchActionModel(self.action_model_path)

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

        # ------- 模型增强：只调 pressure，不直接粗暴替代规则 -------
        model_out = self._predict_action_model(
            playback_state=playback.state,
            lead_sec=lead_sec,
            lead_error_sec=lead_error_sec,
            tracking_quality=tracking_quality,
            confidence=confidence,
            speech_conf=speech_conf,
            progress_age_sec=progress_age_sec,
            active_speaking=active_speaking,
            recently_progressed=recently_progressed,
            stable=stable,
            speaking_recent=speaking_recent,
            engaged_recent=engaged_recent,
            fusion_still_following=fusion_still_following,
            fusion_repeated=fusion_repeated,
            fusion_reentry=fusion_reentry,
            fusion_fused_conf=fusion_fused_conf,
            in_startup_grace=in_startup_grace,
            in_resume_cooldown=in_resume_cooldown,
            in_seek_cooldown=in_seek_cooldown,
            allow_seek=allow_seek and (not self.disable_seek),
            bluetooth_mode=bluetooth_mode,
            bluetooth_long_session_mode=bluetooth_long_session_mode,
            tracking_state=tracking_state,
            sync_state=sync_state,
            hold_pressure=self._pressure.hold_pressure,
            resume_pressure=self._pressure.resume_pressure,
            seek_pressure=self._pressure.seek_pressure,
            soft_duck_pressure=self._pressure.soft_duck_pressure,
            lead_error_ema=self._pressure.lead_error_ema,
            lead_error_derivative_ema=self._pressure.lead_error_derivative_ema,
            tracking_quality_ema=self._pressure.tracking_quality_ema,
            confidence_ema=self._pressure.confidence_ema,
            speech_confidence_ema=self._pressure.speech_confidence_ema,
            position_source=position_source,
        )
        self._apply_model_to_pressures(
            model_out=model_out,
            playback_state=playback.state,
            allow_seek=allow_seek and (not self.disable_seek),
            bluetooth_mode=bluetooth_mode,
            engaged_recent=engaged_recent,
            fusion_repeated=fusion_repeated,
            fusion_reentry=fusion_reentry,
        )

        if playback.state == PlaybackState.HOLDING and self._pressure.resume_pressure >= 1.0:
            self._last_resume_at = now
            self._pressure.hold_pressure *= 0.25
            self._pressure.resume_pressure = 0.0
            return ControlDecision(
                action=ControlAction.RESUME,
                reason="resume_on_engaged_user",
                lead_sec=lead_sec,
                target_gain=self._apply_gain_bias(
                    base_gain=self._gain_for_state(
                        PlaybackState.PLAYING,
                        following=True,
                        bluetooth_long_session_mode=bluetooth_long_session_mode,
                    ),
                    model_out=model_out,
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
                target_gain=self._apply_gain_bias(
                    base_gain=self._gain_for_state(
                        PlaybackState.HOLDING,
                        following=False,
                        bluetooth_long_session_mode=bluetooth_long_session_mode,
                    ),
                    model_out=model_out,
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
                target_gain=self._apply_gain_bias(
                    base_gain=self._gain_for_state(
                        PlaybackState.HOLDING,
                        following=False,
                        bluetooth_long_session_mode=bluetooth_long_session_mode,
                    ),
                    model_out=model_out,
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
            target_time_sec = max(
                0.0,
                user_ref - target_lead_sec + self._seek_bias_sec(model_out),
            )
            return ControlDecision(
                action=ControlAction.SEEK,
                reason="seek_only_when_clearly_derailed",
                target_time_sec=target_time_sec,
                lead_sec=lead_sec,
                target_gain=self._apply_gain_bias(
                    base_gain=self._gain_for_state(
                        PlaybackState.PLAYING,
                        following=False,
                        bluetooth_long_session_mode=bluetooth_long_session_mode,
                    ),
                    model_out=model_out,
                ),
                confidence=max(confidence, 0.30 + 0.40 * fusion_still_following),
                aggressiveness="low",
            )

        return ControlDecision(
            action=ControlAction.NOOP,
            reason="follow_user_smoothly",
            lead_sec=lead_sec,
            target_gain=self._apply_gain_bias(
                base_gain=self._gain_for_state(
                    playback.state,
                    following=following,
                    bluetooth_long_session_mode=bluetooth_long_session_mode,
                ),
                model_out=model_out,
            ),
            confidence=max(confidence, fusion_still_following * 0.56, fusion_fused_conf * 0.52),
            aggressiveness="low",
        )

    def _predict_action_model(self, **kwargs) -> dict[str, float]:
        if not self._action_model.available:
            return {}

        playback_state = str(kwargs.get("playback_state", PlaybackState.PLAYING).value)
        tracking_state = str(kwargs.get("tracking_state", TrackingState.NONE).value)
        sync_state = str(kwargs.get("sync_state", SyncState.BOOTSTRAP).value)
        position_source = str(kwargs.get("position_source", "text"))

        feats = [
            1.0 if playback_state == "playing" else 0.0,
            1.0 if playback_state == "holding" else 0.0,
            1.0 if playback_state == "seeking" else 0.0,
            float(kwargs.get("lead_sec", 0.0)),
            float(kwargs.get("lead_error_sec", 0.0)),
            float(kwargs.get("tracking_quality", 0.0)),
            float(kwargs.get("confidence", 0.0)),
            float(kwargs.get("speech_conf", 0.0)),
            float(kwargs.get("progress_age_sec", 9999.0)),
            1.0 if bool(kwargs.get("active_speaking", False)) else 0.0,
            1.0 if bool(kwargs.get("recently_progressed", False)) else 0.0,
            1.0 if bool(kwargs.get("stable", False)) else 0.0,
            1.0 if bool(kwargs.get("speaking_recent", False)) else 0.0,
            1.0 if bool(kwargs.get("engaged_recent", False)) else 0.0,
            float(kwargs.get("fusion_still_following", 0.0)),
            float(kwargs.get("fusion_repeated", 0.0)),
            float(kwargs.get("fusion_reentry", 0.0)),
            float(kwargs.get("fusion_fused_conf", 0.0)),
            1.0 if bool(kwargs.get("in_startup_grace", False)) else 0.0,
            1.0 if bool(kwargs.get("in_resume_cooldown", False)) else 0.0,
            1.0 if bool(kwargs.get("in_seek_cooldown", False)) else 0.0,
            1.0 if bool(kwargs.get("allow_seek", False)) else 0.0,
            1.0 if bool(kwargs.get("bluetooth_mode", False)) else 0.0,
            1.0 if bool(kwargs.get("bluetooth_long_session_mode", False)) else 0.0,
            1.0 if tracking_state == "weak" else 0.0,
            1.0 if tracking_state == "reliable" else 0.0,
            1.0 if tracking_state == "locked" else 0.0,
            1.0 if sync_state == "converging" else 0.0,
            1.0 if sync_state == "stable" else 0.0,
            1.0 if sync_state == "degraded" else 0.0,
            1.0 if position_source == "audio" else 0.0,
            1.0 if position_source == "joint" else 0.0,
            float(kwargs.get("hold_pressure", 0.0)),
            float(kwargs.get("resume_pressure", 0.0)),
            float(kwargs.get("seek_pressure", 0.0)),
            float(kwargs.get("soft_duck_pressure", 0.0)),
            float(kwargs.get("lead_error_ema", 0.0)),
            float(kwargs.get("lead_error_derivative_ema", 0.0)),
            float(kwargs.get("tracking_quality_ema", 0.0)),
            float(kwargs.get("confidence_ema", 0.0)),
            float(kwargs.get("speech_confidence_ema", 0.0)),
        ]
        return self._action_model.predict(feats)

    def _apply_model_to_pressures(
        self,
        *,
        model_out: dict[str, float],
        playback_state,
        allow_seek: bool,
        bluetooth_mode: bool,
        engaged_recent: bool,
        fusion_repeated: float,
        fusion_reentry: float,
    ) -> None:
        if not model_out:
            return

        b = self.action_model_blend
        noop_p = float(model_out.get("noop", 0.0))
        soft_duck_p = float(model_out.get("soft_duck", 0.0))
        hold_p = float(model_out.get("hold", 0.0))
        resume_p = float(model_out.get("resume", 0.0))
        seek_p = float(model_out.get("seek", 0.0))

        if playback_state == PlaybackState.PLAYING:
            self._pressure.soft_duck_pressure = min(
                1.2,
                (1.0 - b) * self._pressure.soft_duck_pressure + b * (soft_duck_p * 1.15),
            )
            self._pressure.hold_pressure = min(
                1.4,
                (1.0 - b) * self._pressure.hold_pressure + b * (hold_p * 1.15),
            )
            self._pressure.hold_pressure *= (1.0 - 0.18 * noop_p)
            self._pressure.soft_duck_pressure *= (1.0 - 0.12 * noop_p)

        if playback_state == PlaybackState.HOLDING:
            self._pressure.resume_pressure = min(
                1.4,
                (1.0 - b) * self._pressure.resume_pressure + b * (resume_p * 1.15),
            )

        if (
            allow_seek
            and playback_state in (PlaybackState.PLAYING, PlaybackState.HOLDING)
            and not bluetooth_mode
            and not engaged_recent
            and fusion_repeated < 0.42
            and fusion_reentry < 0.42
        ):
            self._pressure.seek_pressure = min(
                1.4,
                (1.0 - b) * self._pressure.seek_pressure + b * (seek_p * 1.15),
            )

        self._pressure.hold_pressure = max(0.0, min(1.4, self._pressure.hold_pressure))
        self._pressure.resume_pressure = max(0.0, min(1.4, self._pressure.resume_pressure))
        self._pressure.seek_pressure = max(0.0, min(1.4, self._pressure.seek_pressure))
        self._pressure.soft_duck_pressure = max(0.0, min(1.2, self._pressure.soft_duck_pressure))

    def _apply_gain_bias(self, *, base_gain: float, model_out: dict[str, float]) -> float:
        if not model_out or "gain_bias" not in model_out:
            return float(base_gain)
        bias = float(model_out["gain_bias"])
        adjusted = float(base_gain) + 0.08 * bias
        return max(0.0, min(1.0, adjusted))

    def _seek_bias_sec(self, model_out: dict[str, float]) -> float:
        if not model_out or "seek_bias" not in model_out:
            return 0.0
        return max(-0.35, min(0.35, 0.22 * float(model_out["seek_bias"])))

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

shadowing_app/src/shadowing/fusion/evidence_fuser.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from shadowing.types import FusionEvidence


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = pow(2.718281828459045, -x)
        return 1.0 / (1.0 + z)
    z = pow(2.718281828459045, x)
    return z / (1.0 + z)


class _TorchFusionModel:
    """
    输出约定：
      [
        fused_confidence,
        still_following,
        repeated,
        reentry,
        prevent_hold,
        prevent_seek,
        widen_reacquire,
        recenter_aligner,
        audio_weight
      ]
    """

    def __init__(self, model_path: str) -> None:
        self.model_path = str(model_path or "").strip()
        self.available = False
        self.output_names = [
            "fused_confidence",
            "still_following",
            "repeated",
            "reentry",
            "prevent_hold",
            "prevent_seek",
            "widen_reacquire",
            "recenter_aligner",
            "audio_weight",
        ]
        self._torch = None
        self._model = None

        if not self.model_path:
            return
        path = Path(self.model_path)
        if not path.exists():
            return

        try:
            import torch
            import torch.nn as nn
        except Exception:
            return

        self._torch = torch

        try:
            jit_model = torch.jit.load(str(path), map_location="cpu")
            jit_model.eval()
            self._model = jit_model
            self.available = True
            return
        except Exception:
            pass

        try:
            blob = torch.load(str(path), map_location="cpu")
        except Exception:
            return

        if not isinstance(blob, dict):
            return

        input_dim = int(blob.get("input_dim", 0))
        hidden_dims = list(blob.get("hidden_dims", [64, 64]))
        state_dict = blob.get("state_dict", None)
        output_names = blob.get("output_names", None)
        if isinstance(output_names, list) and output_names:
            self.output_names = [str(x) for x in output_names]

        if input_dim <= 0 or state_dict is None:
            return

        class _MLP(nn.Module):
            def __init__(self, in_dim: int, h_dims: list[int], out_dim: int) -> None:
                super().__init__()
                layers: list[nn.Module] = []
                cur = in_dim
                for h in h_dims:
                    h = int(h)
                    if h <= 0:
                        continue
                    layers.append(nn.Linear(cur, h))
                    layers.append(nn.ReLU())
                    cur = h
                layers.append(nn.Linear(cur, out_dim))
                self.net = nn.Sequential(*layers)

            def forward(self, x):
                return self.net(x)

        out_dim = max(1, len(self.output_names))
        model = _MLP(input_dim, hidden_dims, out_dim)
        try:
            model.load_state_dict(state_dict, strict=False)
            model.eval()
            self._model = model
            self.available = True
        except Exception:
            self.available = False
            self._model = None

    def predict(self, features: list[float]) -> dict[str, float]:
        if not self.available or self._model is None or self._torch is None:
            return {}
        torch = self._torch
        try:
            x = torch.tensor([features], dtype=torch.float32)
            with torch.no_grad():
                y = self._model(x)
            vals = y.detach().cpu().numpy().reshape(-1).tolist()
        except Exception:
            return {}

        out: dict[str, float] = {}
        for i, name in enumerate(self.output_names):
            if i >= len(vals):
                break
            out[name] = _sigmoid(float(vals[i]))
        return out


class EvidenceFuser:
    def __init__(
        self,
        *,
        text_priority_threshold: float = 0.74,
        audio_takeover_threshold: float = 0.66,
        disagreement_soft_sec: float = 0.42,
        disagreement_hard_sec: float = 1.20,
        model_path: str = "",
        model_blend: float = 0.75,
    ) -> None:
        self.text_priority_threshold = float(text_priority_threshold)
        self.audio_takeover_threshold = float(audio_takeover_threshold)
        self.disagreement_soft_sec = float(disagreement_soft_sec)
        self.disagreement_hard_sec = float(disagreement_hard_sec)

        self.model_path = str(model_path or "").strip()
        self.model_blend = _clamp01(model_blend)
        self._model = _TorchFusionModel(self.model_path)

    def reset(self) -> None:
        return

    def fuse(
        self,
        *,
        now_sec: float,
        tracking,
        progress,
        audio_match,
        audio_behavior,
        signal_quality,
        playback_status,
    ) -> FusionEvidence | None:
        if progress is None and audio_match is None:
            return None

        text_conf = 0.0
        text_ref_time_sec = None
        text_ref_idx = 0
        tracking_quality = 0.0
        recently_progressed = False
        active_speaking = False
        position_source = "text"
        progress_age_sec = 9999.0
        stable = False

        if progress is not None:
            tracking_quality = float(getattr(progress, "tracking_quality", 0.0))
            progress_conf = float(getattr(progress, "confidence", 0.0))
            joint_conf = float(getattr(progress, "joint_confidence", 0.0))
            stable = bool(getattr(progress, "stable", False))
            recently_progressed = bool(getattr(progress, "recently_progressed", False))
            active_speaking = bool(getattr(progress, "active_speaking", False))
            position_source = str(getattr(progress, "position_source", "text"))
            progress_age_sec = float(getattr(progress, "progress_age_sec", 9999.0))

            text_conf = _clamp01(
                0.40 * tracking_quality
                + 0.22 * progress_conf
                + 0.18 * joint_conf
                + 0.10 * (1.0 if stable else 0.0)
                + 0.10 * (1.0 if recently_progressed else 0.0)
            )
            text_ref_time_sec = float(getattr(progress, "estimated_ref_time_sec", 0.0))
            text_ref_idx = int(getattr(progress, "estimated_ref_idx", 0))
            if position_source == "audio":
                text_conf *= 0.82
            elif position_source == "joint":
                text_conf *= 0.90

        audio_conf = 0.0
        audio_ref_time_sec = None
        audio_ref_idx = 0
        repeated = 0.0
        reentry = 0.0
        still_following = 0.0
        paused = 0.0
        audio_mode = "tracking"

        if audio_match is not None:
            audio_ref_time_sec = float(getattr(audio_match, "estimated_ref_time_sec", 0.0))
            audio_ref_idx = int(getattr(audio_match, "estimated_ref_idx_hint", 0))
            audio_conf = float(getattr(audio_match, "confidence", 0.0))
            repeated = float(getattr(audio_match, "repeated_pattern_score", 0.0))
            still_following = max(still_following, audio_conf * 0.82)
            audio_mode = str(getattr(audio_match, "mode", "tracking"))

        if audio_behavior is not None:
            audio_conf = max(audio_conf, float(getattr(audio_behavior, "confidence", 0.0)) * 0.98)
            still_following = max(
                still_following,
                float(getattr(audio_behavior, "still_following_likelihood", 0.0)),
            )
            repeated = max(
                repeated,
                float(getattr(audio_behavior, "repeated_likelihood", 0.0)),
            )
            reentry = float(getattr(audio_behavior, "reentry_likelihood", 0.0))
            paused = float(getattr(audio_behavior, "paused_likelihood", 0.0))

        signal_conf = 0.0
        signal_quality_score = 0.0
        signal_silence = 0.0
        dropout = False
        if signal_quality is not None:
            signal_conf = float(
                max(
                    getattr(signal_quality, "speaking_likelihood", 0.0),
                    0.45 if getattr(signal_quality, "vad_active", False) else 0.0,
                )
            )
            signal_quality_score = float(getattr(signal_quality, "quality_score", 0.0))
            signal_silence = float(getattr(signal_quality, "silence_run_sec", 0.0))
            dropout = bool(getattr(signal_quality, "dropout_detected", False))

            if signal_conf >= 0.54:
                still_following = max(still_following, min(1.0, 0.54 + 0.32 * signal_conf))
            if dropout:
                audio_conf *= 0.92
                still_following *= 0.94
            if signal_quality_score < 0.40:
                audio_conf *= 0.95

        playback_ref_time_sec = None
        if playback_status is not None:
            playback_ref_time_sec = float(getattr(playback_status, "t_ref_heard_content_sec", 0.0))

        if text_ref_time_sec is None and audio_ref_time_sec is not None:
            fused_conf = max(audio_conf, still_following * 0.92, reentry * 0.90)
            should_prevent_hold = bool((still_following >= 0.64 or reentry >= 0.56) and paused < 0.80)
            should_prevent_seek = bool(repeated >= 0.54 or reentry >= 0.54 or still_following >= 0.78)
            should_widen_reacquire_window = bool(audio_conf >= 0.54 or reentry >= 0.54)
            should_recenter_aligner_window = bool(audio_conf >= 0.70 and reentry >= 0.52)

            model_out = self._predict_model_outputs(
                text_conf=0.0,
                audio_conf=audio_conf,
                tracking_quality=tracking_quality,
                progress_age_sec=progress_age_sec,
                recently_progressed=recently_progressed,
                active_speaking=active_speaking,
                stable=stable,
                still_following=still_following,
                repeated=repeated,
                reentry=reentry,
                paused=paused,
                signal_conf=signal_conf,
                signal_quality_score=signal_quality_score,
                signal_silence=signal_silence,
                dropout=dropout,
                disagreement=0.0,
                audio_mode=audio_mode,
                position_source=position_source,
                playback_ref_time_sec=playback_ref_time_sec,
                text_ref_time_sec=None,
                audio_ref_time_sec=audio_ref_time_sec,
            )

            fused_conf = self._blend_scalar(fused_conf, model_out.get("fused_confidence"), self.model_blend)
            still_following = self._blend_scalar(still_following, model_out.get("still_following"), self.model_blend)
            repeated = self._blend_scalar(repeated, model_out.get("repeated"), self.model_blend)
            reentry = self._blend_scalar(reentry, model_out.get("reentry"), self.model_blend)

            should_prevent_hold = self._blend_bool(should_prevent_hold, model_out.get("prevent_hold"))
            should_prevent_seek = self._blend_bool(should_prevent_seek, model_out.get("prevent_seek"))
            should_widen_reacquire_window = self._blend_bool(
                should_widen_reacquire_window,
                model_out.get("widen_reacquire"),
            )
            should_recenter_aligner_window = self._blend_bool(
                should_recenter_aligner_window,
                model_out.get("recenter_aligner"),
            )

            return FusionEvidence(
                estimated_ref_time_sec=float(audio_ref_time_sec),
                estimated_ref_idx_hint=int(max(0, audio_ref_idx)),
                text_confidence=0.0,
                audio_confidence=float(_clamp01(audio_conf)),
                fused_confidence=float(_clamp01(fused_conf)),
                still_following_likelihood=float(_clamp01(still_following)),
                repeated_likelihood=float(_clamp01(repeated)),
                reentry_likelihood=float(_clamp01(reentry)),
                should_prevent_hold=bool(should_prevent_hold),
                should_prevent_seek=bool(should_prevent_seek),
                should_widen_reacquire_window=bool(should_widen_reacquire_window),
                should_recenter_aligner_window=bool(should_recenter_aligner_window),
                emitted_at_sec=float(now_sec),
            )

        if text_ref_time_sec is None:
            return None

        disagreement = 0.0
        if audio_ref_time_sec is not None:
            disagreement = abs(float(text_ref_time_sec) - float(audio_ref_time_sec))

        # ------- 规则基线 -------
        if audio_ref_time_sec is None or text_conf >= self.text_priority_threshold:
            est_ref_time_sec = float(text_ref_time_sec)
            est_ref_idx = int(text_ref_idx)
            fused_conf = text_conf
            audio_weight_rule = 0.0
            if audio_ref_time_sec is not None:
                if disagreement <= self.disagreement_soft_sec:
                    fused_conf = min(1.0, fused_conf + 0.05)
                elif disagreement >= self.disagreement_hard_sec:
                    fused_conf = max(0.0, fused_conf - 0.05)
        else:
            audio_can_takeover = bool(
                audio_conf >= self.audio_takeover_threshold
                and (
                    reentry >= 0.58
                    or audio_mode in {"reentry", "recovery"}
                    or (text_conf < 0.50 and still_following >= 0.72)
                )
                and repeated < 0.66
                and paused < 0.78
                and disagreement <= 1.30
            )
            if audio_can_takeover:
                est_ref_time_sec = float(audio_ref_time_sec)
                est_ref_idx = int(audio_ref_idx)
                fused_conf = max(audio_conf * 0.96, still_following * 0.92, text_conf * 0.82)
                audio_weight_rule = 1.0
            else:
                w_text = max(0.22, text_conf)
                w_audio = max(0.16, audio_conf)
                if repeated >= 0.62:
                    w_audio *= 0.18
                elif paused >= 0.72:
                    w_audio *= 0.32
                elif disagreement >= self.disagreement_hard_sec and reentry < 0.60:
                    w_audio *= 0.42
                denom = max(1e-6, w_text + w_audio)
                audio_weight_rule = w_audio / denom
                est_ref_time_sec = (
                    w_text * float(text_ref_time_sec)
                    + w_audio * float(audio_ref_time_sec)
                ) / denom
                est_ref_idx = int(
                    round((w_text * float(text_ref_idx) + w_audio * float(audio_ref_idx)) / denom)
                )
                fused_conf = max(
                    text_conf,
                    audio_conf * 0.88,
                    0.60 * text_conf + 0.40 * audio_conf,
                )
                if disagreement <= self.disagreement_soft_sec:
                    fused_conf = min(1.0, fused_conf + 0.05)
                elif disagreement >= self.disagreement_hard_sec:
                    fused_conf = max(0.0, fused_conf - 0.08)

        should_prevent_hold = bool(
            (
                still_following >= 0.64
                or reentry >= 0.58
                or (active_speaking and still_following >= 0.58)
                or (recently_progressed and audio_conf >= 0.54)
                or (text_conf < 0.58 and audio_conf >= 0.60)
            )
            and repeated < 0.78
            and paused < 0.80
        )
        should_prevent_seek = bool(
            repeated >= 0.54
            or reentry >= 0.56
            or still_following >= 0.78
            or (audio_conf >= 0.62 and disagreement <= 1.10 and text_conf < 0.54)
        )
        should_recenter_aligner_window = bool(
            audio_ref_time_sec is not None
            and (
                (audio_conf >= 0.68 and text_conf < 0.56 and reentry >= 0.52)
                or (disagreement >= 0.95 and audio_conf >= 0.64 and reentry >= 0.56)
            )
        )
        should_widen_reacquire_window = bool(
            audio_ref_time_sec is not None
            and (
                audio_conf >= 0.54
                or reentry >= 0.54
                or repeated >= 0.52
                or (paused >= 0.72 and still_following < 0.58)
            )
        )

        # ------- 模型增强 -------
        model_out = self._predict_model_outputs(
            text_conf=text_conf,
            audio_conf=audio_conf,
            tracking_quality=tracking_quality,
            progress_age_sec=progress_age_sec,
            recently_progressed=recently_progressed,
            active_speaking=active_speaking,
            stable=stable,
            still_following=still_following,
            repeated=repeated,
            reentry=reentry,
            paused=paused,
            signal_conf=signal_conf,
            signal_quality_score=signal_quality_score,
            signal_silence=signal_silence,
            dropout=dropout,
            disagreement=disagreement,
            audio_mode=audio_mode,
            position_source=position_source,
            playback_ref_time_sec=playback_ref_time_sec,
            text_ref_time_sec=text_ref_time_sec,
            audio_ref_time_sec=audio_ref_time_sec,
        )

        if audio_ref_time_sec is not None and "audio_weight" in model_out:
            audio_weight = self._blend_scalar(audio_weight_rule, model_out.get("audio_weight"), self.model_blend)
            audio_weight = _clamp01(audio_weight)
            est_ref_time_sec = (1.0 - audio_weight) * float(text_ref_time_sec) + audio_weight * float(audio_ref_time_sec)
            est_ref_idx = int(round((1.0 - audio_weight) * float(text_ref_idx) + audio_weight * float(audio_ref_idx)))

        fused_conf = self._blend_scalar(fused_conf, model_out.get("fused_confidence"), self.model_blend)
        still_following = self._blend_scalar(still_following, model_out.get("still_following"), self.model_blend)
        repeated = self._blend_scalar(repeated, model_out.get("repeated"), self.model_blend)
        reentry = self._blend_scalar(reentry, model_out.get("reentry"), self.model_blend)

        should_prevent_hold = self._blend_bool(should_prevent_hold, model_out.get("prevent_hold"))
        should_prevent_seek = self._blend_bool(should_prevent_seek, model_out.get("prevent_seek"))
        should_widen_reacquire_window = self._blend_bool(
            should_widen_reacquire_window,
            model_out.get("widen_reacquire"),
        )
        should_recenter_aligner_window = self._blend_bool(
            should_recenter_aligner_window,
            model_out.get("recenter_aligner"),
        )

        return FusionEvidence(
            estimated_ref_time_sec=float(est_ref_time_sec),
            estimated_ref_idx_hint=int(max(0, est_ref_idx)),
            text_confidence=float(_clamp01(text_conf)),
            audio_confidence=float(_clamp01(audio_conf)),
            fused_confidence=float(_clamp01(fused_conf)),
            still_following_likelihood=float(_clamp01(still_following)),
            repeated_likelihood=float(_clamp01(repeated)),
            reentry_likelihood=float(_clamp01(reentry)),
            should_prevent_hold=bool(should_prevent_hold),
            should_prevent_seek=bool(should_prevent_seek),
            should_widen_reacquire_window=bool(should_widen_reacquire_window),
            should_recenter_aligner_window=bool(should_recenter_aligner_window),
            emitted_at_sec=float(now_sec),
        )

    def _predict_model_outputs(self, **kwargs: Any) -> dict[str, float]:
        if not self._model.available:
            return {}

        audio_mode = str(kwargs.get("audio_mode", "tracking"))
        position_source = str(kwargs.get("position_source", "text"))
        playback_ref_time_sec = kwargs.get("playback_ref_time_sec", None)
        text_ref_time_sec = kwargs.get("text_ref_time_sec", None)
        audio_ref_time_sec = kwargs.get("audio_ref_time_sec", None)

        mode_repeat = 1.0 if audio_mode == "repeat" else 0.0
        mode_reentry = 1.0 if audio_mode == "reentry" else 0.0
        mode_recovery = 1.0 if audio_mode == "recovery" else 0.0
        src_audio = 1.0 if position_source == "audio" else 0.0
        src_joint = 1.0 if position_source == "joint" else 0.0

        playback_vs_text = 0.0
        playback_vs_audio = 0.0
        if playback_ref_time_sec is not None and text_ref_time_sec is not None:
            playback_vs_text = float(playback_ref_time_sec) - float(text_ref_time_sec)
        if playback_ref_time_sec is not None and audio_ref_time_sec is not None:
            playback_vs_audio = float(playback_ref_time_sec) - float(audio_ref_time_sec)

        feats = [
            float(kwargs.get("text_conf", 0.0)),
            float(kwargs.get("audio_conf", 0.0)),
            float(kwargs.get("tracking_quality", 0.0)),
            float(kwargs.get("progress_age_sec", 9999.0)),
            1.0 if bool(kwargs.get("recently_progressed", False)) else 0.0,
            1.0 if bool(kwargs.get("active_speaking", False)) else 0.0,
            1.0 if bool(kwargs.get("stable", False)) else 0.0,
            float(kwargs.get("still_following", 0.0)),
            float(kwargs.get("repeated", 0.0)),
            float(kwargs.get("reentry", 0.0)),
            float(kwargs.get("paused", 0.0)),
            float(kwargs.get("signal_conf", 0.0)),
            float(kwargs.get("signal_quality_score", 0.0)),
            float(kwargs.get("signal_silence", 0.0)),
            1.0 if bool(kwargs.get("dropout", False)) else 0.0,
            float(kwargs.get("disagreement", 0.0)),
            mode_repeat,
            mode_reentry,
            mode_recovery,
            src_audio,
            src_joint,
            float(playback_vs_text),
            float(playback_vs_audio),
        ]
        return self._model.predict(feats)

    def _blend_scalar(self, rule_value: float, model_value: float | None, blend: float) -> float:
        if model_value is None:
            return _clamp01(rule_value)
        return _clamp01((1.0 - blend) * float(rule_value) + blend * float(model_value))

    def _blend_bool(self, rule_value: bool, model_value: float | None) -> bool:
        if model_value is None:
            return bool(rule_value)
        if rule_value and float(model_value) >= 0.35:
            return True
        if (not rule_value) and float(model_value) >= 0.70:
            return True
        return bool(rule_value)

shadowing_app/src/shadowing/audio/audio_behavior_classifier.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shadowing.types import AudioBehaviorSnapshot


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = pow(2.718281828459045, -x)
        return 1.0 / (1.0 + z)
    z = pow(2.718281828459045, x)
    return z / (1.0 + z)


@dataclass(slots=True)
class _BehaviorState:
    mode: str = "unknown"
    mode_run: int = 0
    last_emitted_at_sec: float = 0.0
    last_active_follow_at_sec: float = 0.0
    last_pause_like_at_sec: float = 0.0
    last_reentry_like_at_sec: float = 0.0
    last_repeat_like_at_sec: float = 0.0


class _TorchBehaviorModel:
    """
    兼容两类导出：
    1. torch.jit.trace/script 导出的 module
    2. torch.save({...}) 的 checkpoint:
       {
         "input_dim": int,
         "hidden_dims": [64, 64],
         "state_dict": ...,
         "output_names": ["still_following","repeated","reentry","paused","confidence"]
       }

    输出约定：
      [still_following, repeated, reentry, paused, confidence]，均为 logit 或近似实数。
    运行时统一过 sigmoid。
    """

    def __init__(self, model_path: str) -> None:
        self.model_path = str(model_path or "").strip()
        self.available = False
        self.output_names = [
            "still_following",
            "repeated",
            "reentry",
            "paused",
            "confidence",
        ]
        self._torch = None
        self._model = None

        if not self.model_path:
            return
        path = Path(self.model_path)
        if not path.exists():
            return

        try:
            import torch
            import torch.nn as nn
        except Exception:
            return

        self._torch = torch

        try:
            jit_model = torch.jit.load(str(path), map_location="cpu")
            jit_model.eval()
            self._model = jit_model
            self.available = True
            return
        except Exception:
            pass

        try:
            blob = torch.load(str(path), map_location="cpu")
        except Exception:
            return

        if not isinstance(blob, dict):
            return

        input_dim = int(blob.get("input_dim", 0))
        hidden_dims = list(blob.get("hidden_dims", [64, 64]))
        state_dict = blob.get("state_dict", None)
        output_names = blob.get("output_names", None)
        if isinstance(output_names, list) and output_names:
            self.output_names = [str(x) for x in output_names]

        if input_dim <= 0 or state_dict is None:
            return

        class _MLP(nn.Module):
            def __init__(self, in_dim: int, h_dims: list[int], out_dim: int) -> None:
                super().__init__()
                layers: list[nn.Module] = []
                cur = in_dim
                for h in h_dims:
                    h = int(h)
                    if h <= 0:
                        continue
                    layers.append(nn.Linear(cur, h))
                    layers.append(nn.ReLU())
                    cur = h
                layers.append(nn.Linear(cur, out_dim))
                self.net = nn.Sequential(*layers)

            def forward(self, x):
                return self.net(x)

        out_dim = max(1, len(self.output_names))
        model = _MLP(input_dim, hidden_dims, out_dim)
        try:
            model.load_state_dict(state_dict, strict=False)
            model.eval()
            self._model = model
            self.available = True
        except Exception:
            self.available = False
            self._model = None

    def predict(self, features: list[float]) -> dict[str, float]:
        if not self.available or self._model is None or self._torch is None:
            return {}
        torch = self._torch
        try:
            x = torch.tensor([features], dtype=torch.float32)
            with torch.no_grad():
                y = self._model(x)
            vals = y.detach().cpu().numpy().reshape(-1).tolist()
        except Exception:
            return {}

        out: dict[str, float] = {}
        for i, name in enumerate(self.output_names):
            if i >= len(vals):
                break
            out[name] = _sigmoid(float(vals[i]))
        return out


class AudioBehaviorClassifier:
    def __init__(
        self,
        *,
        repeat_backtrack_sec: float = 1.5,
        reentry_silence_min_sec: float = 0.45,
        smooth_alpha: float = 0.30,
        repeat_trigger_conf: float = 0.62,
        reentry_trigger_conf: float = 0.60,
        pause_trigger_silence_sec: float = 0.70,
        model_path: str = "",
        model_blend: float = 0.70,
    ) -> None:
        self.repeat_backtrack_sec = float(repeat_backtrack_sec)
        self.reentry_silence_min_sec = float(reentry_silence_min_sec)
        self.smooth_alpha = float(smooth_alpha)
        self.repeat_trigger_conf = float(repeat_trigger_conf)
        self.reentry_trigger_conf = float(reentry_trigger_conf)
        self.pause_trigger_silence_sec = float(pause_trigger_silence_sec)

        self.model_path = str(model_path or "").strip()
        self.model_blend = _clamp01(model_blend)
        self._model = _TorchBehaviorModel(self.model_path)

        self._last_snapshot: AudioBehaviorSnapshot | None = None
        self._state = _BehaviorState()

    def reset(self) -> None:
        self._last_snapshot = None
        self._state = _BehaviorState()

    def update(
        self,
        *,
        audio_match,
        signal_quality,
        progress,
        playback_status,
    ) -> AudioBehaviorSnapshot | None:
        if audio_match is None:
            return self._last_snapshot

        signal_conf = 0.0
        silence_run_sec = 0.0
        quality_score = 0.0
        rms = 0.0
        peak = 0.0
        vad_active = False
        if signal_quality is not None:
            signal_conf = float(
                max(
                    getattr(signal_quality, "speaking_likelihood", 0.0),
                    0.48 if getattr(signal_quality, "vad_active", False) else 0.0,
                )
            )
            silence_run_sec = float(getattr(signal_quality, "silence_run_sec", 0.0))
            quality_score = float(getattr(signal_quality, "quality_score", 0.0))
            rms = float(getattr(signal_quality, "rms", 0.0))
            peak = float(getattr(signal_quality, "peak", 0.0))
            vad_active = bool(getattr(signal_quality, "vad_active", False))

        match_conf = float(getattr(audio_match, "confidence", 0.0))
        local_similarity = float(getattr(audio_match, "local_similarity", 0.0))
        repeated_score = float(getattr(audio_match, "repeated_pattern_score", 0.0))
        drift_sec = float(getattr(audio_match, "drift_sec", 0.0))
        audio_mode = str(getattr(audio_match, "mode", "tracking"))
        dtw_score = float(getattr(audio_match, "dtw_path_score", 0.0))
        dtw_coverage = float(getattr(audio_match, "dtw_coverage", 0.0))
        env_score = float(getattr(audio_match, "envelope_alignment_score", 0.0))
        onset_score = float(getattr(audio_match, "onset_alignment_score", 0.0))
        band_score = float(getattr(audio_match, "band_alignment_score", 0.0))
        rhythm_score = float(getattr(audio_match, "rhythm_consistency_score", 0.0))

        still_following = _clamp01(
            0.48 * match_conf + 0.22 * local_similarity + 0.30 * signal_conf
        )
        repeated = _clamp01(repeated_score)
        reentry = 0.0
        paused = 0.0

        if signal_quality is not None:
            paused = min(1.0, max(0.0, silence_run_sec / 1.6))
            if silence_run_sec >= self.pause_trigger_silence_sec and signal_conf < 0.42:
                paused = max(paused, 0.62)

        if (
            playback_status is not None
            and silence_run_sec >= self.reentry_silence_min_sec
            and abs(
                float(getattr(audio_match, "estimated_ref_time_sec", 0.0))
                - float(getattr(playback_status, "t_ref_heard_content_sec", 0.0))
            )
            <= 0.60
            and match_conf >= 0.56
        ):
            reentry = min(1.0, 0.52 + 0.36 * match_conf)

        tracking_q = 0.0
        joint_conf = 0.0
        progress_recent = False
        progress_active = False
        position_source = "text"
        progress_age = 9999.0
        if progress is not None:
            tracking_q = float(getattr(progress, "tracking_quality", 0.0))
            joint_conf = float(getattr(progress, "joint_confidence", 0.0))
            position_source = str(getattr(progress, "position_source", "text"))
            progress_recent = bool(getattr(progress, "recently_progressed", False))
            progress_active = bool(getattr(progress, "active_speaking", False))
            progress_age = float(getattr(progress, "progress_age_sec", 9999.0))

            if tracking_q >= 0.72:
                still_following = max(still_following, 0.68)
            if joint_conf >= 0.74 and position_source in {"joint", "audio"}:
                still_following = max(still_following, 0.72)
            if progress_recent:
                paused *= 0.70
            if progress_active:
                still_following = max(still_following, 0.70)
                paused *= 0.78

        if audio_mode == "repeat":
            repeated = max(repeated, min(1.0, 0.60 + 0.24 * match_conf))
        if audio_mode == "reentry":
            reentry = max(reentry, min(1.0, 0.60 + 0.24 * match_conf))
        if audio_mode == "recovery":
            still_following = max(still_following, min(1.0, 0.58 + 0.22 * match_conf))

        if quality_score < 0.40 and signal_conf < 0.36:
            still_following *= 0.88

        rule_scores = {
            "still_following": _clamp01(still_following),
            "repeated": _clamp01(repeated),
            "reentry": _clamp01(reentry),
            "paused": _clamp01(paused),
        }

        model_scores = self._predict_model_scores(
            match_conf=match_conf,
            local_similarity=local_similarity,
            repeated_score=repeated_score,
            drift_sec=drift_sec,
            dtw_score=dtw_score,
            dtw_coverage=dtw_coverage,
            env_score=env_score,
            onset_score=onset_score,
            band_score=band_score,
            rhythm_score=rhythm_score,
            signal_conf=signal_conf,
            silence_run_sec=silence_run_sec,
            quality_score=quality_score,
            rms=rms,
            peak=peak,
            vad_active=vad_active,
            tracking_q=tracking_q,
            joint_conf=joint_conf,
            progress_recent=progress_recent,
            progress_active=progress_active,
            progress_age=progress_age,
            position_source=position_source,
            audio_mode=audio_mode,
        )

        if model_scores:
            rule_scores["still_following"] = _clamp01(
                (1.0 - self.model_blend) * rule_scores["still_following"]
                + self.model_blend * model_scores.get("still_following", rule_scores["still_following"])
            )
            rule_scores["repeated"] = _clamp01(
                (1.0 - self.model_blend) * rule_scores["repeated"]
                + self.model_blend * model_scores.get("repeated", rule_scores["repeated"])
            )
            rule_scores["reentry"] = _clamp01(
                (1.0 - self.model_blend) * rule_scores["reentry"]
                + self.model_blend * model_scores.get("reentry", rule_scores["reentry"])
            )
            rule_scores["paused"] = _clamp01(
                (1.0 - self.model_blend) * rule_scores["paused"]
                + self.model_blend * model_scores.get("paused", rule_scores["paused"])
            )

        state_mode = self._infer_mode(
            still_following=rule_scores["still_following"],
            repeated=rule_scores["repeated"],
            reentry=rule_scores["reentry"],
            paused=rule_scores["paused"],
            emitted_at_sec=float(getattr(audio_match, "emitted_at_sec", 0.0)),
        )

        if state_mode == "repeat":
            rule_scores["repeated"] = max(rule_scores["repeated"], 0.72)
            rule_scores["paused"] *= 0.82
        elif state_mode == "reentry":
            rule_scores["reentry"] = max(rule_scores["reentry"], 0.72)
            rule_scores["paused"] *= 0.72
            rule_scores["still_following"] = max(rule_scores["still_following"], 0.70)
        elif state_mode == "pause":
            rule_scores["paused"] = max(rule_scores["paused"], 0.72)
            rule_scores["repeated"] *= 0.86
        elif state_mode == "following":
            rule_scores["still_following"] = max(rule_scores["still_following"], 0.72)
            rule_scores["paused"] *= 0.68

        conf = max(
            rule_scores["still_following"],
            rule_scores["repeated"],
            rule_scores["reentry"],
            1.0 - rule_scores["paused"] if rule_scores["paused"] > 0 else 0.0,
        )
        if model_scores and "confidence" in model_scores:
            conf = _clamp01(
                0.50 * conf + 0.50 * float(model_scores["confidence"])
            )

        snap = AudioBehaviorSnapshot(
            still_following_likelihood=float(_clamp01(rule_scores["still_following"])),
            repeated_likelihood=float(_clamp01(rule_scores["repeated"])),
            reentry_likelihood=float(_clamp01(rule_scores["reentry"])),
            paused_likelihood=float(_clamp01(rule_scores["paused"])),
            confidence=float(_clamp01(conf)),
            emitted_at_sec=float(getattr(audio_match, "emitted_at_sec", 0.0)),
        )
        snap = self._smooth(snap)
        self._last_snapshot = snap
        return snap

    def _predict_model_scores(self, **kwargs: Any) -> dict[str, float]:
        if not self._model.available:
            return {}

        position_source = str(kwargs.get("position_source", "text"))
        audio_mode = str(kwargs.get("audio_mode", "tracking"))

        position_source_audio = 1.0 if position_source == "audio" else 0.0
        position_source_joint = 1.0 if position_source == "joint" else 0.0
        mode_repeat = 1.0 if audio_mode == "repeat" else 0.0
        mode_reentry = 1.0 if audio_mode == "reentry" else 0.0
        mode_recovery = 1.0 if audio_mode == "recovery" else 0.0

        prev = self._last_snapshot
        prev_follow = 0.0 if prev is None else float(prev.still_following_likelihood)
        prev_repeat = 0.0 if prev is None else float(prev.repeated_likelihood)
        prev_reentry = 0.0 if prev is None else float(prev.reentry_likelihood)
        prev_pause = 0.0 if prev is None else float(prev.paused_likelihood)

        feats = [
            float(kwargs.get("match_conf", 0.0)),
            float(kwargs.get("local_similarity", 0.0)),
            float(kwargs.get("repeated_score", 0.0)),
            float(kwargs.get("drift_sec", 0.0)),
            float(kwargs.get("dtw_score", 0.0)),
            float(kwargs.get("dtw_coverage", 0.0)),
            float(kwargs.get("env_score", 0.0)),
            float(kwargs.get("onset_score", 0.0)),
            float(kwargs.get("band_score", 0.0)),
            float(kwargs.get("rhythm_score", 0.0)),
            float(kwargs.get("signal_conf", 0.0)),
            float(kwargs.get("silence_run_sec", 0.0)),
            float(kwargs.get("quality_score", 0.0)),
            float(kwargs.get("rms", 0.0)),
            float(kwargs.get("peak", 0.0)),
            1.0 if bool(kwargs.get("vad_active", False)) else 0.0,
            float(kwargs.get("tracking_q", 0.0)),
            float(kwargs.get("joint_conf", 0.0)),
            1.0 if bool(kwargs.get("progress_recent", False)) else 0.0,
            1.0 if bool(kwargs.get("progress_active", False)) else 0.0,
            float(kwargs.get("progress_age", 9999.0)),
            position_source_audio,
            position_source_joint,
            mode_repeat,
            mode_reentry,
            mode_recovery,
            prev_follow,
            prev_repeat,
            prev_reentry,
            prev_pause,
        ]
        return self._model.predict(feats)

    def _infer_mode(
        self,
        *,
        still_following: float,
        repeated: float,
        reentry: float,
        paused: float,
        emitted_at_sec: float,
    ) -> str:
        prev = self._state.mode
        candidate = "unknown"

        if repeated >= self.repeat_trigger_conf and repeated >= reentry and repeated >= still_following:
            candidate = "repeat"
        elif reentry >= self.reentry_trigger_conf and reentry >= repeated:
            candidate = "reentry"
        elif paused >= 0.66 and still_following < 0.58:
            candidate = "pause"
        elif still_following >= 0.64:
            candidate = "following"

        if candidate == prev:
            self._state.mode_run += 1
        else:
            self._state.mode = candidate
            self._state.mode_run = 1

        if candidate == "following":
            self._state.last_active_follow_at_sec = emitted_at_sec
        elif candidate == "pause":
            self._state.last_pause_like_at_sec = emitted_at_sec
        elif candidate == "reentry":
            self._state.last_reentry_like_at_sec = emitted_at_sec
        elif candidate == "repeat":
            self._state.last_repeat_like_at_sec = emitted_at_sec

        self._state.last_emitted_at_sec = emitted_at_sec

        if candidate in {"repeat", "reentry"} and self._state.mode_run >= 1:
            return candidate
        if candidate in {"pause", "following"} and self._state.mode_run >= 2:
            return candidate

        if prev == "repeat" and (emitted_at_sec - self._state.last_repeat_like_at_sec) <= 0.35:
            return "repeat"
        if prev == "reentry" and (emitted_at_sec - self._state.last_reentry_like_at_sec) <= 0.45:
            return "reentry"
        if prev == "pause" and (emitted_at_sec - self._state.last_pause_like_at_sec) <= 0.40:
            return "pause"
        if prev == "following" and (emitted_at_sec - self._state.last_active_follow_at_sec) <= 0.35:
            return "following"

        return candidate

    def _smooth(self, current: AudioBehaviorSnapshot) -> AudioBehaviorSnapshot:
        prev = self._last_snapshot
        if prev is None:
            return current

        a = _clamp01(self.smooth_alpha)
        still_following = (1.0 - a) * prev.still_following_likelihood + a * current.still_following_likelihood
        repeated = (1.0 - a) * prev.repeated_likelihood + a * current.repeated_likelihood
        reentry = (1.0 - a) * prev.reentry_likelihood + a * current.reentry_likelihood
        paused = (1.0 - a) * prev.paused_likelihood + a * current.paused_likelihood
        conf = max(still_following, repeated, reentry, 1.0 - paused if paused > 0 else 0.0)

        return AudioBehaviorSnapshot(
            still_following_likelihood=float(_clamp01(still_following)),
            repeated_likelihood=float(_clamp01(repeated)),
            reentry_likelihood=float(_clamp01(reentry)),
            paused_likelihood=float(_clamp01(paused)),
            confidence=float(_clamp01(conf)),
            emitted_at_sec=float(current.emitted_at_sec),
        )



shadowing_app/src/shadowing/bootstrap.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shadowing.audio.audio_behavior_classifier import AudioBehaviorClassifier
from shadowing.audio.live_audio_matcher import LiveAudioMatcher
from shadowing.audio.latency_calibrator import LatencyCalibrator
from shadowing.audio.reference_audio_store import ReferenceAudioStore
from shadowing.fusion.evidence_fuser import EvidenceFuser
from shadowing.observation.signal_quality import SignalQualityMonitor
from shadowing.progress.audio_aware_progress_estimator import AudioAwareProgressEstimator
from shadowing.realtime.alignment.incremental_aligner import IncrementalAligner
from shadowing.realtime.asr.fake_asr_provider import FakeASRProvider, FakeAsrConfig
from shadowing.realtime.asr.sherpa_streaming_provider import SherpaStreamingProvider
from shadowing.realtime.capture.soundcard_recorder import SoundCardRecorder
from shadowing.realtime.capture.sounddevice_recorder import SoundDeviceRecorder
from shadowing.realtime.control.policy import ControlPolicy
from shadowing.realtime.control.state_machine_controller import StateMachineController
from shadowing.realtime.orchestrator import ShadowingOrchestrator
from shadowing.realtime.playback.sounddevice_player import PlaybackConfig, SoundDevicePlayer
from shadowing.realtime.runtime import RealtimeRuntimeConfig, ShadowingRuntime
from shadowing.telemetry.event_logger import EventLogger


def _get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    if cfg is None:
        return default
    return cfg.get(key, default)


def _as_float(v: Any, default: float) -> float:
    try:
        x = float(v)
    except Exception:
        return float(default)
    if x != x:
        return float(default)
    return float(x)


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(slots=True)
class RuntimeBundle:
    repo: Any
    player: Any
    recorder: Any
    asr: Any
    aligner: Any
    controller: Any
    orchestrator: ShadowingOrchestrator
    runtime: ShadowingRuntime


class FilesystemLessonRepository:
    """
    轻量 repo 实现，满足当前 orchestrator 的调用：

    - load_reference_map(lesson_id)
    - load_audio_chunks(lesson_id)

    依赖目录结构：
      lesson_base_dir/<lesson_id>/
        lesson_manifest.json
        reference_map.json
        chunks/*.npy    或 manifest/chunk_paths 指向音频文件

    这里优先按已经预处理好的 npy chunk 读取；如果你的 repo 里已有正式实现，
    可以直接把 build_runtime 里的 repo 替换成正式类。
    """

    def __init__(self, lesson_base_dir: str) -> None:
        self.lesson_base_dir = Path(lesson_base_dir)

    def _lesson_dir(self, lesson_id: str) -> Path:
        return self.lesson_base_dir / lesson_id

    def load_reference_map(self, lesson_id: str):
        import json

        from shadowing.types import RefToken, ReferenceMap

        lesson_dir = self._lesson_dir(lesson_id)
        p = lesson_dir / "reference_map.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        tokens = [
            RefToken(
                idx=int(x["idx"]),
                char=str(x["char"]),
                pinyin=str(x.get("pinyin", "")),
                t_start=float(x.get("t_start", 0.0)),
                t_end=float(x.get("t_end", x.get("t_start", 0.0))),
                sentence_id=int(x.get("sentence_id", 0)),
                clause_id=int(x.get("clause_id", 0)),
            )
            for x in data.get("tokens", [])
        ]
        return ReferenceMap(
            lesson_id=str(data.get("lesson_id", lesson_id)),
            tokens=tokens,
            total_duration_sec=float(data.get("total_duration_sec", 0.0)),
        )

    def load_audio_chunks(self, lesson_id: str):
        import json

        import numpy as np

        from shadowing.types import AudioChunk

        lesson_dir = self._lesson_dir(lesson_id)
        manifest_path = lesson_dir / "lesson_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        sample_rate = int(manifest.get("sample_rate_out", 44100))
        chunk_paths = manifest.get("chunk_paths", [])

        chunks: list[AudioChunk] = []
        start_time_sec = 0.0

        for i, raw_path in enumerate(chunk_paths):
            p = Path(raw_path)
            if not p.is_absolute():
                p = lesson_dir / raw_path
            if not p.exists():
                alt = lesson_dir / "chunks" / p.name
                if alt.exists():
                    p = alt

            if p.suffix.lower() == ".npy":
                samples = np.load(p).astype(np.float32, copy=False)
            else:
                # 尽量兼容 wav/mp3/flac；需要 soundfile
                import soundfile as sf

                samples, sr = sf.read(str(p), dtype="float32", always_2d=False)
                if int(sr) != sample_rate:
                    raise ValueError(
                        f"Audio chunk sample_rate mismatch: expected={sample_rate}, got={sr}, file={p}"
                    )

            arr = np.asarray(samples, dtype=np.float32)
            if arr.ndim == 1:
                channels = 1
                frame_count = arr.shape[0]
            else:
                channels = int(arr.shape[1])
                frame_count = int(arr.shape[0])

            duration_sec = frame_count / float(sample_rate)
            chunks.append(
                AudioChunk(
                    chunk_id=int(i),
                    sample_rate=int(sample_rate),
                    channels=int(channels),
                    samples=arr,
                    duration_sec=float(duration_sec),
                    start_time_sec=float(start_time_sec),
                    path=str(p),
                )
            )
            start_time_sec += duration_sec

        return chunks


def _build_repo(config: dict[str, Any]) -> Any:
    lesson_base_dir = str(_get(config, "lesson_base_dir", "assets/lessons"))
    return FilesystemLessonRepository(lesson_base_dir=lesson_base_dir)


def _build_player(config: dict[str, Any]) -> SoundDevicePlayer:
    playback_cfg = dict(_get(config, "playback", {}))
    cfg = PlaybackConfig(
        sample_rate=_as_int(_get(playback_cfg, "sample_rate", 44100), 44100),
        channels=_as_int(_get(playback_cfg, "channels", 1), 1),
        device=_get(playback_cfg, "device", None),
        latency=_get(playback_cfg, "latency", "low"),
        blocksize=_as_int(_get(playback_cfg, "blocksize", 0), 0),
        bluetooth_output_offset_sec=_as_float(
            _get(playback_cfg, "bluetooth_output_offset_sec", 0.0),
            0.0,
        ),
    )
    return SoundDevicePlayer(config=cfg)


def _build_recorder(config: dict[str, Any]) -> Any:
    capture_cfg = dict(_get(config, "capture", {}))
    backend = str(_get(capture_cfg, "backend", "sounddevice")).strip().lower()

    sample_rate_in = _as_int(_get(capture_cfg, "device_sample_rate", 48000), 48000)
    target_sample_rate = _as_int(_get(capture_cfg, "target_sample_rate", 16000), 16000)
    channels = _as_int(_get(capture_cfg, "channels", 1), 1)
    device = _get(capture_cfg, "device", None)

    if backend == "soundcard":
        return SoundCardRecorder(
            sample_rate_in=sample_rate_in,
            target_sample_rate=target_sample_rate,
            channels=channels,
            device=device,
            block_frames=_as_int(_get(capture_cfg, "block_frames", 1440), 1440),
            include_loopback=_as_bool(_get(capture_cfg, "include_loopback", False), False),
            debug_level_meter=_as_bool(_get(capture_cfg, "debug_level_meter", False), False),
            debug_level_every_n_blocks=_as_int(
                _get(capture_cfg, "debug_level_every_n_blocks", 20),
                20,
            ),
        )

    return SoundDeviceRecorder(
        sample_rate_in=sample_rate_in,
        target_sample_rate=target_sample_rate,
        channels=channels,
        device=device,
        dtype=str(_get(capture_cfg, "dtype", "float32")),
        blocksize=_as_int(_get(capture_cfg, "blocksize", 0), 0),
        latency=_get(capture_cfg, "latency", "low"),
    )


def _build_asr(config: dict[str, Any]) -> Any:
    asr_cfg = dict(_get(config, "asr", {}))
    mode = str(_get(asr_cfg, "mode", "sherpa")).strip().lower()

    if mode == "fake":
        reference_text = str(_get(asr_cfg, "reference_text", ""))
        scripted_steps = _get(asr_cfg, "scripted_steps", [])
        fake_cfg = FakeAsrConfig(
            scripted_steps=scripted_steps if isinstance(scripted_steps, list) else [],
            reference_text=reference_text,
            chars_per_sec=_as_float(_get(asr_cfg, "chars_per_sec", 4.0), 4.0),
            emit_partial_interval_sec=_as_float(
                _get(asr_cfg, "emit_partial_interval_sec", 0.12),
                0.12,
            ),
            emit_final_on_endpoint=_as_bool(
                _get(asr_cfg, "emit_final_on_endpoint", True),
                True,
            ),
            sample_rate=_as_int(_get(asr_cfg, "sample_rate", 16000), 16000),
            bytes_per_sample=_as_int(_get(asr_cfg, "bytes_per_sample", 2), 2),
            channels=_as_int(_get(asr_cfg, "channels", 1), 1),
            vad_rms_threshold=_as_float(_get(asr_cfg, "vad_rms_threshold", 0.01), 0.01),
            vad_min_active_ms=_as_float(_get(asr_cfg, "vad_min_active_ms", 30.0), 30.0),
        )
        return FakeASRProvider(config=fake_cfg)

    sherpa_cfg = {
        "tokens": str(_get(asr_cfg, "tokens", "")),
        "encoder": str(_get(asr_cfg, "encoder", "")),
        "decoder": str(_get(asr_cfg, "decoder", "")),
        "joiner": str(_get(asr_cfg, "joiner", "")),
        "num_threads": _as_int(_get(asr_cfg, "num_threads", 2), 2),
        "feature_dim": _as_int(_get(asr_cfg, "feature_dim", 80), 80),
        "decoding_method": str(_get(asr_cfg, "decoding_method", "greedy_search")),
        "provider": str(_get(asr_cfg, "provider", "cpu")),
        "rule1_min_trailing_silence": _as_float(
            _get(asr_cfg, "rule1_min_trailing_silence", 1.2),
            1.2,
        ),
        "rule2_min_trailing_silence": _as_float(
            _get(asr_cfg, "rule2_min_trailing_silence", 0.8),
            0.8,
        ),
        "rule3_min_utterance_length": _as_float(
            _get(asr_cfg, "rule3_min_utterance_length", 12.0),
            12.0,
        ),
        "hotwords": str(_get(asr_cfg, "hotwords", "")),
        "hotwords_score": _as_float(_get(asr_cfg, "hotwords_score", 1.5), 1.5),
        "min_meaningful_text_len": _as_int(
            _get(asr_cfg, "min_meaningful_text_len", 2),
            2,
        ),
        "endpoint_min_interval_sec": _as_float(
            _get(asr_cfg, "endpoint_min_interval_sec", 0.35),
            0.35,
        ),
        "force_reset_after_empty_endpoints": _as_int(
            _get(asr_cfg, "force_reset_after_empty_endpoints", 999999999),
            999999999,
        ),
        "reset_on_empty_endpoint": _as_bool(
            _get(asr_cfg, "reset_on_empty_endpoint", False),
            False,
        ),
        "preserve_stream_on_partial_only": _as_bool(
            _get(asr_cfg, "preserve_stream_on_partial_only", True),
            True,
        ),
        "log_hotwords_on_start": _as_bool(
            _get(asr_cfg, "log_hotwords_on_start", True),
            True,
        ),
        "log_hotwords_preview_on_start": _as_bool(
            _get(asr_cfg, "log_hotwords_preview_on_start", True),
            True,
        ),
        "hotwords_preview_limit": _as_int(
            _get(asr_cfg, "hotwords_preview_limit", 12),
            12,
        ),
        "info_logging": _as_bool(_get(asr_cfg, "info_logging", True), True),
    }

    return SherpaStreamingProvider(
        model_config=sherpa_cfg,
        hotwords=str(_get(asr_cfg, "hotwords", "")),
        sample_rate=_as_int(_get(asr_cfg, "sample_rate", 16000), 16000),
        emit_partial_interval_sec=_as_float(
            _get(asr_cfg, "emit_partial_interval_sec", 0.08),
            0.08,
        ),
        enable_endpoint=_as_bool(_get(asr_cfg, "enable_endpoint", True), True),
        debug_feed=_as_bool(_get(asr_cfg, "debug_feed", False), False),
        debug_feed_every_n_chunks=_as_int(
            _get(asr_cfg, "debug_feed_every_n_chunks", 20),
            20,
        ),
    )


def _build_aligner(config: dict[str, Any]) -> IncrementalAligner:
    align_cfg = dict(_get(config, "alignment", {}))
    return IncrementalAligner(
        reference_text=None,
        window_back=_as_int(_get(align_cfg, "window_back", 10), 10),
        window_ahead=_as_int(_get(align_cfg, "window_ahead", 48), 48),
        stable_hits=_as_int(_get(align_cfg, "stable_hits", 2), 2),
        min_confidence=_as_float(_get(align_cfg, "min_confidence", 0.62), 0.62),
        debug=_as_bool(_get(align_cfg, "debug", False), False),
    )


def _build_control_policy(config: dict[str, Any]) -> ControlPolicy:
    ctrl = dict(_get(config, "control", {}))
    return ControlPolicy(
        target_lead_sec=_as_float(_get(ctrl, "target_lead_sec", 0.18), 0.18),
        hold_if_lead_sec=_as_float(_get(ctrl, "hold_if_lead_sec", 1.05), 1.05),
        resume_if_lead_sec=_as_float(_get(ctrl, "resume_if_lead_sec", 0.36), 0.36),
        seek_if_lag_sec=_as_float(_get(ctrl, "seek_if_lag_sec", -2.60), -2.60),
        min_confidence=_as_float(_get(ctrl, "min_confidence", 0.70), 0.70),
        seek_cooldown_sec=_as_float(_get(ctrl, "seek_cooldown_sec", 2.20), 2.20),
        gain_following=_as_float(_get(ctrl, "gain_following", 0.52), 0.52),
        gain_transition=_as_float(_get(ctrl, "gain_transition", 0.72), 0.72),
        gain_soft_duck=_as_float(_get(ctrl, "gain_soft_duck", 0.36), 0.36),
        recover_after_seek_sec=_as_float(_get(ctrl, "recover_after_seek_sec", 0.80), 0.80),
        startup_grace_sec=_as_float(_get(ctrl, "startup_grace_sec", 3.20), 3.20),
        low_confidence_hold_sec=_as_float(_get(ctrl, "low_confidence_hold_sec", 2.20), 2.20),
        bootstrapping_sec=_as_float(_get(ctrl, "bootstrapping_sec", 2.20), 2.20),
        guide_play_sec=_as_float(_get(ctrl, "guide_play_sec", 3.20), 3.20),
        no_progress_hold_min_play_sec=_as_float(
            _get(ctrl, "no_progress_hold_min_play_sec", 5.80),
            5.80,
        ),
        speaking_recent_sec=_as_float(_get(ctrl, "speaking_recent_sec", 1.10), 1.10),
        progress_stale_sec=_as_float(_get(ctrl, "progress_stale_sec", 1.45), 1.45),
        hold_trend_sec=_as_float(_get(ctrl, "hold_trend_sec", 1.00), 1.00),
        hold_extra_lead_sec=_as_float(_get(ctrl, "hold_extra_lead_sec", 0.22), 0.22),
        low_confidence_continue_sec=_as_float(
            _get(ctrl, "low_confidence_continue_sec", 1.80),
            1.80,
        ),
        tracking_quality_hold_min=_as_float(
            _get(ctrl, "tracking_quality_hold_min", 0.60),
            0.60,
        ),
        tracking_quality_seek_min=_as_float(
            _get(ctrl, "tracking_quality_seek_min", 0.84),
            0.84,
        ),
        resume_from_hold_event_fresh_sec=_as_float(
            _get(ctrl, "resume_from_hold_event_fresh_sec", 0.60),
            0.60,
        ),
        resume_from_hold_speaking_lead_slack_sec=_as_float(
            _get(ctrl, "resume_from_hold_speaking_lead_slack_sec", 0.72),
            0.72,
        ),
        reacquire_soft_duck_sec=_as_float(_get(ctrl, "reacquire_soft_duck_sec", 2.40), 2.40),
        disable_seek=_as_bool(_get(ctrl, "disable_seek", False), False),
        bluetooth_long_session_target_lead_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_target_lead_sec", 0.38),
            0.38,
        ),
        bluetooth_long_session_hold_if_lead_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_hold_if_lead_sec", 1.35),
            1.35,
        ),
        bluetooth_long_session_resume_if_lead_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_resume_if_lead_sec", 0.30),
            0.30,
        ),
        bluetooth_long_session_seek_if_lag_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_seek_if_lag_sec", -3.20),
            -3.20,
        ),
        bluetooth_long_session_seek_cooldown_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_seek_cooldown_sec", 3.20),
            3.20,
        ),
        bluetooth_long_session_progress_stale_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_progress_stale_sec", 1.75),
            1.75,
        ),
        bluetooth_long_session_hold_trend_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_hold_trend_sec", 1.15),
            1.15,
        ),
        bluetooth_long_session_tracking_quality_hold_min=_as_float(
            _get(ctrl, "bluetooth_long_session_tracking_quality_hold_min", 0.58),
            0.58,
        ),
        bluetooth_long_session_tracking_quality_seek_min=_as_float(
            _get(ctrl, "bluetooth_long_session_tracking_quality_seek_min", 0.88),
            0.88,
        ),
        bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec=_as_float(
            _get(ctrl, "bluetooth_long_session_resume_from_hold_speaking_lead_slack_sec", 0.82),
            0.82,
        ),
        bluetooth_long_session_gain_following=_as_float(
            _get(ctrl, "bluetooth_long_session_gain_following", 0.50),
            0.50,
        ),
        bluetooth_long_session_gain_transition=_as_float(
            _get(ctrl, "bluetooth_long_session_gain_transition", 0.66),
            0.66,
        ),
        bluetooth_long_session_gain_soft_duck=_as_float(
            _get(ctrl, "bluetooth_long_session_gain_soft_duck", 0.32),
            0.32,
        ),
    )


def _build_controller(config: dict[str, Any]) -> StateMachineController:
    ctrl_cfg = dict(_get(config, "control", {}))
    policy = _build_control_policy(config)

    kwargs: dict[str, Any] = dict(
        policy=policy,
        disable_seek=_as_bool(_get(ctrl_cfg, "disable_seek", False), False),
        debug=_as_bool(_get(config.get("debug", {}), "enabled", False), False),
    )

    # 兼容你已改造过的模型版 controller；如果构造器还没加这些参数，也不报错
    extra = {
        "action_model_path": str(_get(ctrl_cfg, "action_model_path", "")),
        "action_model_blend": _as_float(_get(ctrl_cfg, "action_model_blend", 0.55), 0.55),
    }
    try:
        return StateMachineController(**kwargs, **extra)
    except TypeError:
        return StateMachineController(**kwargs)


def _build_signal_monitor(config: dict[str, Any]) -> SignalQualityMonitor:
    sig_cfg = dict(_get(config, "signal", {}))
    try:
        return SignalQualityMonitor(
            min_vad_rms=_as_float(_get(sig_cfg, "min_vad_rms", 0.006), 0.006),
            vad_noise_multiplier=_as_float(
                _get(sig_cfg, "vad_noise_multiplier", 2.8),
                2.8,
            ),
        )
    except TypeError:
        return SignalQualityMonitor()


def _build_latency_calibrator() -> LatencyCalibrator:
    return LatencyCalibrator()


def _build_profile_store(config: dict[str, Any]) -> Any | None:
    adapt_cfg = dict(_get(config, "adaptation", {}))
    profile_path = str(_get(adapt_cfg, "profile_path", "")).strip()
    if not profile_path:
        return None
    try:
        from shadowing.adaptation.profile_store import ProfileStore

        return ProfileStore(profile_path)
    except Exception:
        return None


def _build_auto_tuner() -> Any | None:
    try:
        from shadowing.adaptation.runtime_auto_tuner import RuntimeAutoTuner

        return RuntimeAutoTuner()
    except Exception:
        return None


def _build_event_logger(config: dict[str, Any]) -> EventLogger | None:
    sess_cfg = dict(_get(config, "session", {}))
    enabled = _as_bool(_get(sess_cfg, "event_logging", False), False)
    session_dir = str(_get(sess_cfg, "session_dir", "runtime/latest_session"))
    if not enabled:
        return None
    return EventLogger(session_dir=session_dir, enabled=True)


def _build_reference_audio_store(config: dict[str, Any]) -> ReferenceAudioStore | None:
    root = str(_get(config, "lesson_base_dir", "assets/lessons"))
    try:
        return ReferenceAudioStore(base_dir=root)
    except Exception:
        return None


def _build_live_audio_matcher(config: dict[str, Any]) -> LiveAudioMatcher | None:
    audio_cfg = dict(_get(config, "audio_matcher", {}))
    try:
        return LiveAudioMatcher(
            search_window_sec=_as_float(_get(audio_cfg, "search_window_sec", 3.0), 3.0),
            match_window_sec=_as_float(_get(audio_cfg, "match_window_sec", 1.8), 1.8),
            update_interval_sec=_as_float(_get(audio_cfg, "update_interval_sec", 0.12), 0.12),
            min_frames_for_match=_as_int(_get(audio_cfg, "min_frames_for_match", 20), 20),
            ring_buffer_sec=_as_float(_get(audio_cfg, "ring_buffer_sec", 6.0), 6.0),
        )
    except Exception:
        return None


def _build_audio_behavior_classifier(config: dict[str, Any]) -> AudioBehaviorClassifier | None:
    cfg = dict(_get(config, "audio_behavior", {}))
    kwargs: dict[str, Any] = dict(
        repeat_backtrack_sec=_as_float(_get(cfg, "repeat_backtrack_sec", 1.5), 1.5),
        reentry_silence_min_sec=_as_float(_get(cfg, "reentry_silence_min_sec", 0.45), 0.45),
        smooth_alpha=_as_float(_get(cfg, "smooth_alpha", 0.30), 0.30),
        repeat_trigger_conf=_as_float(_get(cfg, "repeat_trigger_conf", 0.62), 0.62),
        reentry_trigger_conf=_as_float(_get(cfg, "reentry_trigger_conf", 0.60), 0.60),
        pause_trigger_silence_sec=_as_float(_get(cfg, "pause_trigger_silence_sec", 0.70), 0.70),
    )
    extra = {
        "model_path": str(_get(cfg, "model_path", "")),
        "model_blend": _as_float(_get(cfg, "model_blend", 0.70), 0.70),
    }
    try:
        return AudioBehaviorClassifier(**kwargs, **extra)
    except TypeError:
        return AudioBehaviorClassifier(**kwargs)


def _build_evidence_fuser(config: dict[str, Any]) -> EvidenceFuser | None:
    cfg = dict(_get(config, "fusion", {}))
    kwargs: dict[str, Any] = dict(
        text_priority_threshold=_as_float(_get(cfg, "text_priority_threshold", 0.74), 0.74),
        audio_takeover_threshold=_as_float(_get(cfg, "audio_takeover_threshold", 0.66), 0.66),
        disagreement_soft_sec=_as_float(_get(cfg, "disagreement_soft_sec", 0.42), 0.42),
        disagreement_hard_sec=_as_float(_get(cfg, "disagreement_hard_sec", 1.20), 1.20),
    )
    extra = {
        "model_path": str(_get(cfg, "model_path", "")),
        "model_blend": _as_float(_get(cfg, "model_blend", 0.75), 0.75),
    }
    try:
        return EvidenceFuser(**kwargs, **extra)
    except TypeError:
        return EvidenceFuser(**kwargs)


def build_orchestrator(config: dict[str, Any]) -> ShadowingOrchestrator:
    runtime_cfg = dict(_get(config, "runtime", {}))
    session_cfg = dict(_get(config, "session", {}))
    device_context = dict(_get(config, "device_context", {}))
    debug_cfg = dict(_get(config, "debug", {}))

    repo = _build_repo(config)
    player = _build_player(config)
    recorder = _build_recorder(config)
    asr = _build_asr(config)
    aligner = _build_aligner(config)
    controller = _build_controller(config)

    signal_monitor = _build_signal_monitor(config)
    latency_calibrator = _build_latency_calibrator()
    auto_tuner = _build_auto_tuner()
    profile_store = _build_profile_store(config)
    event_logger = _build_event_logger(config)
    reference_audio_store = _build_reference_audio_store(config)
    live_audio_matcher = _build_live_audio_matcher(config)
    audio_behavior_classifier = _build_audio_behavior_classifier(config)
    evidence_fuser = _build_evidence_fuser(config)

    orchestrator = ShadowingOrchestrator(
        repo=repo,
        player=player,
        recorder=recorder,
        asr=asr,
        aligner=aligner,
        controller=controller,
        device_context={
            **device_context,
            "session_dir": str(_get(session_cfg, "session_dir", "runtime/latest_session")),
        },
        signal_monitor=signal_monitor,
        latency_calibrator=latency_calibrator,
        auto_tuner=auto_tuner,
        profile_store=profile_store,
        event_logger=event_logger,
        reference_audio_store=reference_audio_store,
        live_audio_matcher=live_audio_matcher,
        audio_behavior_classifier=audio_behavior_classifier,
        evidence_fuser=evidence_fuser,
        audio_queue_maxsize=_as_int(_get(runtime_cfg, "audio_queue_maxsize", 150), 150),
        asr_event_queue_maxsize=_as_int(_get(runtime_cfg, "asr_event_queue_maxsize", 64), 64),
        loop_interval_sec=_as_float(_get(runtime_cfg, "loop_interval_sec", 0.03), 0.03),
        debug=_as_bool(_get(debug_cfg, "enabled", False), False),
    )
    return orchestrator


def build_runtime(config: dict[str, Any]) -> ShadowingRuntime:
    runtime_cfg = dict(_get(config, "runtime", {}))
    orchestrator = build_orchestrator(config)
    runtime = ShadowingRuntime(
        orchestrator=orchestrator,
        config=RealtimeRuntimeConfig(
            tick_sleep_sec=_as_float(_get(runtime_cfg, "loop_interval_sec", 0.03), 0.03)
        ),
    )
    return runtime


def build_runtime_bundle(config: dict[str, Any]) -> RuntimeBundle:
    orchestrator = build_orchestrator(config)
    runtime_cfg = dict(_get(config, "runtime", {}))
    runtime = ShadowingRuntime(
        orchestrator=orchestrator,
        config=RealtimeRuntimeConfig(
            tick_sleep_sec=_as_float(_get(runtime_cfg, "loop_interval_sec", 0.03), 0.03)
        ),
    )
    return RuntimeBundle(
        repo=orchestrator.repo,
        player=orchestrator.player,
        recorder=orchestrator.recorder,
        asr=orchestrator.asr,
        aligner=orchestrator.aligner,
        controller=orchestrator.controller,
        orchestrator=orchestrator,
        runtime=runtime,
    )


hadowing_app/src/shadowing/training/export_runtime_config.py
hadowing_app/src/shadowing/training/export_runtime_config.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_dict(root: dict[str, Any], key: str) -> dict[str, Any]:
    value = root.get(key)
    if not isinstance(value, dict):
        value = {}
        root[key] = value
    return value


def export_runtime_config(
    *,
    config_path: str,
    out_path: str | None = None,
    audio_behavior_model_path: str = "",
    audio_behavior_model_blend: float = 0.70,
    fusion_model_path: str = "",
    fusion_model_blend: float = 0.75,
    action_model_path: str = "",
    action_model_blend: float = 0.55,
) -> dict[str, Any]:
    src = Path(config_path)
    cfg = _load_json(src)

    audio_behavior_cfg = _ensure_dict(cfg, "audio_behavior")
    fusion_cfg = _ensure_dict(cfg, "fusion")
    control_cfg = _ensure_dict(cfg, "control")

    if audio_behavior_model_path:
        audio_behavior_cfg["model_path"] = str(audio_behavior_model_path)
    audio_behavior_cfg["model_blend"] = float(audio_behavior_model_blend)

    if fusion_model_path:
        fusion_cfg["model_path"] = str(fusion_model_path)
    fusion_cfg["model_blend"] = float(fusion_model_blend)

    if action_model_path:
        control_cfg["action_model_path"] = str(action_model_path)
    control_cfg["action_model_blend"] = float(action_model_blend)

    dst = Path(out_path) if out_path else src
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[saved] {dst}")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return cfg


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, help="现有 runtime config json")
    p.add_argument("--out", default="", help="输出文件；不传则覆盖原文件")
    p.add_argument("--audio-behavior-model-path", default="")
    p.add_argument("--audio-behavior-model-blend", type=float, default=0.70)
    p.add_argument("--fusion-model-path", default="")
    p.add_argument("--fusion-model-blend", type=float, default=0.75)
    p.add_argument("--action-model-path", default="")
    p.add_argument("--action-model-blend", type=float, default=0.55)
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    export_runtime_config(
        config_path=args.config,
        out_path=args.out or None,
        audio_behavior_model_path=args.audio_behavior_model_path,
        audio_behavior_model_blend=args.audio_behavior_model_blend,
        fusion_model_path=args.fusion_model_path,
        fusion_model_blend=args.fusion_model_blend,
        action_model_path=args.action_model_path,
        action_model_blend=args.action_model_blend,
    )


if __name__ == "__main__":
    main()





# shadowing_app/src/shadowing/ml/feature_row_builder.py
from __future__ import annotations

from typing import Any


def build_fusion_feature_row(
    *,
    progress,
    signal_quality,
    audio_match,
    audio_behavior,
    playback_status,
    bluetooth_mode: bool,
) -> dict[str, float]:
    estimated_ref_time_sec = 0.0 if progress is None else float(getattr(progress, "estimated_ref_time_sec", 0.0))
    playback_ref = 0.0 if playback_status is None else float(getattr(playback_status, "t_ref_heard_content_sec", 0.0))
    lead_sec = playback_ref - estimated_ref_time_sec

    return {
        "tracking_quality": 0.0 if progress is None else float(getattr(progress, "tracking_quality", 0.0)),
        "confidence": 0.0 if progress is None else float(getattr(progress, "confidence", 0.0)),
        "stable": 0.0 if progress is None else float(bool(getattr(progress, "stable", False))),
        "progress_age_sec": 9999.0 if progress is None else float(getattr(progress, "progress_age_sec", 9999.0)),
        "joint_confidence": 0.0 if progress is None else float(getattr(progress, "joint_confidence", 0.0)),
        "audio_confidence": 0.0 if progress is None else float(getattr(progress, "audio_confidence", 0.0)),
        "audio_support_strength": 0.0 if progress is None else float(getattr(progress, "audio_support_strength", 0.0)),
        "signal_rms": 0.0 if signal_quality is None else float(getattr(signal_quality, "rms", 0.0)),
        "signal_peak": 0.0 if signal_quality is None else float(getattr(signal_quality, "peak", 0.0)),
        "vad_active": 0.0 if signal_quality is None else float(bool(getattr(signal_quality, "vad_active", False))),
        "speaking_likelihood": 0.0 if signal_quality is None else float(getattr(signal_quality, "speaking_likelihood", 0.0)),
        "silence_run_sec": 9999.0 if signal_quality is None else float(getattr(signal_quality, "silence_run_sec", 9999.0)),
        "quality_score": 0.0 if signal_quality is None else float(getattr(signal_quality, "quality_score", 0.0)),
        "audio_match_confidence": 0.0 if audio_match is None else float(getattr(audio_match, "confidence", 0.0)),
        "local_similarity": 0.0 if audio_match is None else float(getattr(audio_match, "local_similarity", 0.0)),
        "repeated_pattern_score": 0.0 if audio_match is None else float(getattr(audio_match, "repeated_pattern_score", 0.0)),
        "dtw_path_score": 0.0 if audio_match is None else float(getattr(audio_match, "dtw_path_score", 0.0)),
        "dtw_coverage": 0.0 if audio_match is None else float(getattr(audio_match, "dtw_coverage", 0.0)),
        "still_following_likelihood": 0.0 if audio_behavior is None else float(getattr(audio_behavior, "still_following_likelihood", 0.0)),
        "reentry_likelihood": 0.0 if audio_behavior is None else float(getattr(audio_behavior, "reentry_likelihood", 0.0)),
        "paused_likelihood": 0.0 if audio_behavior is None else float(getattr(audio_behavior, "paused_likelihood", 0.0)),
        "lead_sec": float(lead_sec),
        "bluetooth_mode": float(bool(bluetooth_mode)),
    }






# shadowing_app/src/shadowing/ml/fusion_infer.py
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
import torch

from shadowing.training.models.fusion_tcn import FusionTCN


class FusionPredictor:
    def __init__(
        self,
        model_path: str,
        features: list[str],
        hidden: int = 64,
        window_frames: int = 25,
    ) -> None:
        self.features = list(features)
        self.window_frames = int(window_frames)
        self.buffer: deque[list[float]] = deque(maxlen=self.window_frames)

        self.model = FusionTCN(n_features=len(self.features), hidden=hidden)
        state = torch.load(model_path, map_location="cpu")
        self.model.load_state_dict(state)
        self.model.eval()

    def _vectorize(self, row: dict[str, Any]) -> list[float]:
        return [float(row.get(f, 0.0)) for f in self.features]

    def predict(self, row: dict[str, Any]) -> dict[str, float | int]:
        self.buffer.append(self._vectorize(row))

        x = np.asarray(list(self.buffer), dtype=np.float32)
        if len(x) < self.window_frames:
            pad = np.zeros((self.window_frames - len(x), x.shape[1]), dtype=np.float32)
            x = np.concatenate([pad, x], axis=0)

        with torch.no_grad():
            inp = torch.tensor(x[None, ...], dtype=torch.float32)
            out = self.model(inp)

            mode_prob = torch.softmax(out["fusion_mode"], dim=-1)[0].numpy()
            hold_prob = torch.sigmoid(out["prevent_hold"])[0].item()
            seek_prob = torch.sigmoid(out["prevent_seek"])[0].item()
            recenter_prob = torch.sigmoid(out["recenter"])[0].item()

        return {
            "fusion_mode": int(np.argmax(mode_prob)),
            "fusion_mode_text_only_prob": float(mode_prob[0]),
            "fusion_mode_blend_prob": float(mode_prob[1]),
            "fusion_mode_audio_takeover_prob": float(mode_prob[2]),
            "prevent_hold_prob": float(hold_prob),
            "prevent_seek_prob": float(seek_prob),
            "recenter_prob": float(recenter_prob),
        }



# shadowing_app/src/shadowing/ml/matcher_infer.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np


class MatcherRanker:
    def __init__(self, model_path: str, features: list[str]) -> None:
        self.model_path = str(model_path)
        self.features = list(features)
        self.model = joblib.load(self.model_path)

    def score_row(self, row: dict[str, Any]) -> dict[str, float]:
        x = np.asarray([[float(row.get(f, 0.0)) for f in self.features]], dtype=np.float32)
        proba = self.model.predict_proba(x)[0]
        return {
            "bad": float(proba[0]),
            "weak": float(proba[1]),
            "good": float(proba[2]),
            "best": float(proba[3]),
            "rank_score": float(0.0 * proba[0] + 0.33 * proba[1] + 0.66 * proba[2] + 1.0 * proba[3]),
        }

    


# shadowing_app/training/train_fusion.py
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from shadowing.training.datasets.common_schema import FUSION_FEATURES
from shadowing.training.models.fusion_tcn import FusionTCN


class FusionDataset(Dataset):
    def __init__(self, npz_path: str):
        data = np.load(npz_path)
        self.X = torch.tensor(data["X"], dtype=torch.float32)
        self.y_mode = torch.tensor(data["fusion_mode"], dtype=torch.long)
        self.y_hold = torch.tensor(data["prevent_hold"], dtype=torch.float32)
        self.y_seek = torch.tensor(data["prevent_seek"], dtype=torch.float32)
        self.y_recenter = torch.tensor(data["recenter"], dtype=torch.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, i):
        return (
            self.X[i],
            self.y_mode[i],
            self.y_hold[i],
            self.y_seek[i],
            self.y_recenter[i],
        )


def run_epoch(model, dl, opt=None):
    ce = nn.CrossEntropyLoss()
    bce = nn.BCEWithLogitsLoss()

    is_train = opt is not None
    model.train(is_train)

    total_loss = 0.0
    total_n = 0

    for x, y_mode, y_hold, y_seek, y_recenter in dl:
        out = model(x)
        loss = (
            ce(out["fusion_mode"], y_mode)
            + 0.7 * bce(out["prevent_hold"], y_hold)
            + 0.7 * bce(out["prevent_seek"], y_seek)
            + 0.5 * bce(out["recenter"], y_recenter)
        )

        if is_train:
            opt.zero_grad()
            loss.backward()
            opt.step()

        total_loss += float(loss.item()) * len(x)
        total_n += len(x)

    return total_loss / max(1, total_n)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--out-dir", type=str, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--hidden", type=int, default=64)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ds_train = FusionDataset(str(data_dir / "train.npz"))
    ds_val = FusionDataset(str(data_dir / "val.npz"))

    dl_train = DataLoader(ds_train, batch_size=args.batch_size, shuffle=True)
    dl_val = DataLoader(ds_val, batch_size=args.batch_size, shuffle=False)

    model = FusionTCN(n_features=len(FUSION_FEATURES), hidden=args.hidden)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)

    best_val = 1e9
    best_path = out_dir / "fusion_tcn.pt"

    history = []
    for epoch in range(args.epochs):
        tr_loss = run_epoch(model, dl_train, opt=opt)
        va_loss = run_epoch(model, dl_val, opt=None)

        history.append({"epoch": epoch, "train_loss": tr_loss, "val_loss": va_loss})
        print(f"epoch={epoch} train_loss={tr_loss:.4f} val_loss={va_loss:.4f}")

        if va_loss < best_val:
            best_val = va_loss
            torch.save(model.state_dict(), best_path)

    meta = {
        "task": "fusion_tcn",
        "features": FUSION_FEATURES,
        "hidden": args.hidden,
        "best_val_loss": best_val,
        "history": history,
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()




# shadowing_app/training/train_matcher.py
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import classification_report
from xgboost import XGBClassifier

from shadowing.training.datasets.common_schema import MATCHER_FEATURES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--out-dir", type=str, required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_parquet(data_dir / "train.parquet")
    val_df = pd.read_parquet(data_dir / "val.parquet")

    X_train = train_df[MATCHER_FEATURES].fillna(0.0)
    y_train = train_df["label"].astype(int)

    X_val = val_df[MATCHER_FEATURES].fillna(0.0)
    y_val = val_df["label"].astype(int)

    model = XGBClassifier(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="multi:softprob",
        num_class=4,
        eval_metric="mlogloss",
        random_state=42,
    )
    model.fit(X_train, y_train)

    pred = model.predict(X_val)
    report = classification_report(y_val, pred, digits=4, output_dict=True)
    print(classification_report(y_val, pred, digits=4))

    joblib.dump(model, out_dir / "matcher_ranker.joblib")

    meta = {
        "task": "matcher_ranker",
        "features": MATCHER_FEATURES,
        "metrics": report,
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()






# shadowing_app/training/models/fusion_tcn.py
from __future__ import annotations

import torch
import torch.nn as nn


class TemporalBlock(nn.Module):
    def __init__(self, c_in: int, c_out: int, k: int = 3, d: int = 1):
        super().__init__()
        pad = (k - 1) * d
        self.conv1 = nn.Conv1d(c_in, c_out, kernel_size=k, padding=pad, dilation=d)
        self.act1 = nn.ReLU()
        self.conv2 = nn.Conv1d(c_out, c_out, kernel_size=k, padding=pad, dilation=d)
        self.act2 = nn.ReLU()
        self.proj = nn.Conv1d(c_in, c_out, 1) if c_in != c_out else nn.Identity()

    def forward(self, x):
        y = self.act1(self.conv1(x))
        y = self.act2(self.conv2(y))
        y = y[..., : x.shape[-1]]
        return y + self.proj(x)


class FusionTCN(nn.Module):
    def __init__(self, n_features: int, hidden: int = 64):
        super().__init__()
        self.block1 = TemporalBlock(n_features, hidden, d=1)
        self.block2 = TemporalBlock(hidden, hidden, d=2)
        self.block3 = TemporalBlock(hidden, hidden, d=4)
        self.pool = nn.AdaptiveAvgPool1d(1)

        self.head_mode = nn.Linear(hidden, 3)
        self.head_hold = nn.Linear(hidden, 1)
        self.head_seek = nn.Linear(hidden, 1)
        self.head_recenter = nn.Linear(hidden, 1)

    def forward(self, x):
        x = x.transpose(1, 2)
        h = self.block1(x)
        h = self.block2(h)
        h = self.block3(h)
        h = self.pool(h).squeeze(-1)

        return {
            "fusion_mode": self.head_mode(h),
            "prevent_hold": self.head_hold(h).squeeze(-1),
            "prevent_seek": self.head_seek(h).squeeze(-1),
            "recenter": self.head_recenter(h).squeeze(-1),
        }
    






# shadowing_app/training/datasets/build_fusion_dataset.py
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from shadowing.training.datasets.common_schema import FUSION_FEATURES


def pad_or_trim(seq: np.ndarray, T: int) -> np.ndarray:
    if len(seq) >= T:
        return seq[-T:]
    pad = np.zeros((T - len(seq), seq.shape[1]), dtype=np.float32)
    return np.concatenate([pad, seq], axis=0)


def build_windows(frame_df: pd.DataFrame, T: int = 25):
    feat = frame_df[FUSION_FEATURES].fillna(0.0).to_numpy(dtype=np.float32)

    xs = []
    y_mode = []
    y_hold = []
    y_seek = []
    y_recenter = []

    for i in range(len(frame_df)):
        x = pad_or_trim(feat[: i + 1], T)
        xs.append(x)

        row = frame_df.iloc[i]
        aq = float(row.get("audio_confidence", 0.0))
        tq = float(row.get("tracking_quality", 0.0))
        reentry = float(row.get("reentry_likelihood", 0.0))
        repeat_like = float(row.get("repeated_pattern_score", 0.0))
        disagreement = abs(float(row.get("audio_text_disagreement_sec", 0.0)))

        if aq >= 0.70 and reentry >= 0.55 and tq < 0.55:
            mode = 2
        elif aq >= 0.55 and disagreement <= 1.0:
            mode = 1
        else:
            mode = 0

        prevent_hold = int(
            float(row.get("still_following_likelihood", 0.0)) >= 0.65
            or reentry >= 0.58
        )
        prevent_seek = int(repeat_like >= 0.55 or reentry >= 0.56)
        recenter = int(aq >= 0.65 and disagreement >= 0.9)

        y_mode.append(mode)
        y_hold.append(prevent_hold)
        y_seek.append(prevent_seek)
        y_recenter.append(recenter)

    X = np.stack(xs, axis=0).astype(np.float32)
    Y = {
        "fusion_mode": np.asarray(y_mode, dtype=np.int64),
        "prevent_hold": np.asarray(y_hold, dtype=np.float32),
        "prevent_seek": np.asarray(y_seek, dtype=np.float32),
        "recenter": np.asarray(y_recenter, dtype=np.float32),
    }
    return X, Y


def save_fusion_dataset(frame_df: pd.DataFrame, out_dir: str, T: int = 25, train_ratio: float = 0.9):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    X, Y = build_windows(frame_df, T=T)

    n = len(X)
    idx = np.arange(n)
    rng = np.random.default_rng(42)
    rng.shuffle(idx)

    n_train = int(n * train_ratio)
    tr = idx[:n_train]
    va = idx[n_train:]

    np.savez_compressed(
        out / "train.npz",
        X=X[tr],
        fusion_mode=Y["fusion_mode"][tr],
        prevent_hold=Y["prevent_hold"][tr],
        prevent_seek=Y["prevent_seek"][tr],
        recenter=Y["recenter"][tr],
    )
    np.savez_compressed(
        out / "val.npz",
        X=X[va],
        fusion_mode=Y["fusion_mode"][va],
        prevent_hold=Y["prevent_hold"][va],
        prevent_seek=Y["prevent_seek"][va],
        recenter=Y["recenter"][va],
    )

    meta = {
        "task": "fusion_tcn",
        "window_frames": T,
        "frame_hop_sec": 0.1,
        "features": FUSION_FEATURES,
        "fusion_mode_meaning": {
            "0": "text_only",
            "1": "blend",
            "2": "audio_takeover",
        },
        "n_train": int(len(tr)),
        "n_val": int(len(va)),
    }
    (out / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-parquet", type=str, required=True)
    parser.add_argument("--out-dir", type=str, required=True)
    parser.add_argument("--window-frames", type=int, default=25)
    args = parser.parse_args()

    frame_df = pd.read_parquet(args.input_parquet)
    save_fusion_dataset(frame_df, args.out_dir, T=int(args.window_frames))


if __name__ == "__main__":
    main()






# shadowing_app/training/datasets/build_matcher_dataset.py
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from shadowing.training.datasets.common_schema import MATCHER_COLUMNS, MATCHER_FEATURES


def save_matcher_dataset(df: pd.DataFrame, out_dir: str, train_ratio: float = 0.9) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = df.copy()
    for col in MATCHER_COLUMNS:
        if col not in df.columns:
            if col == "behavior":
                df[col] = "unknown"
            else:
                df[col] = 0.0

    df = df[MATCHER_COLUMNS]
    df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)

    n_train = int(len(df) * train_ratio)
    train_df = df.iloc[:n_train].reset_index(drop=True)
    val_df = df.iloc[n_train:].reset_index(drop=True)

    train_df.to_parquet(out / "train.parquet", index=False)
    val_df.to_parquet(out / "val.parquet", index=False)

    meta = {
        "task": "matcher_ranker",
        "features": MATCHER_FEATURES,
        "label_meaning": {
            "0": "bad",
            "1": "weak",
            "2": "good",
            "3": "best",
        },
        "n_train": len(train_df),
        "n_val": len(val_df),
    }
    (out / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-parquet", type=str, required=True)
    parser.add_argument("--out-dir", type=str, required=True)
    args = parser.parse_args()

    df = pd.read_parquet(args.input_parquet)
    save_matcher_dataset(df, args.out_dir)


if __name__ == "__main__":
    main()




# shadowing_app/training/datasets/common_schema.py
from __future__ import annotations

MATCHER_FEATURES = [
    "confidence",
    "local_similarity",
    "envelope_alignment_score",
    "onset_alignment_score",
    "band_alignment_score",
    "rhythm_consistency_score",
    "repeated_pattern_score",
    "drift_sec",
    "dtw_cost",
    "dtw_path_score",
    "dtw_coverage",
    "coarse_candidate_rank",
    "time_offset_sec",
]

MATCHER_COLUMNS = [
    "sample_id",
    "frame_idx",
    "now_sec",
    "gt_ref_time_sec",
    "behavior",
    "pred_ref_time_sec",
    *MATCHER_FEATURES,
    "abs_error_sec",
    "label",
]

FUSION_FEATURES = [
    "tracking_quality",
    "confidence",
    "stable",
    "progress_age_sec",
    "joint_confidence",
    "audio_confidence",
    "audio_support_strength",
    "signal_rms",
    "signal_peak",
    "vad_active",
    "speaking_likelihood",
    "silence_run_sec",
    "quality_score",
    "audio_match_confidence",
    "local_similarity",
    "repeated_pattern_score",
    "dtw_path_score",
    "dtw_coverage",
    "still_following_likelihood",
    "reentry_likelihood",
    "paused_likelihood",
    "lead_sec",
    "bluetooth_mode",
]