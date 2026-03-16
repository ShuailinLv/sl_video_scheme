from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from shadowing.preprocess.reference_builder import SegmentTimelineRecord


@dataclass(slots=True)
class AudioAssemblerConfig:
    silence_rms_threshold: float = 0.0035
    min_silence_keep_sec: float = 0.035
    max_trim_head_sec: float = 0.180
    max_trim_tail_sec: float = 0.220
    crossfade_sec: float = 0.025
    write_trimmed_segment_files: bool = False
    trimmed_segments_dirname: str = "assembled_segments"


@dataclass(slots=True)
class AssembledAudioResult:
    sample_rate: int
    assembled_audio_path: str
    total_duration_sec: float
    segment_records: list[SegmentTimelineRecord]


class AudioAssembler:
    def __init__(self, config: AudioAssemblerConfig | None = None) -> None:
        self.config = config or AudioAssemblerConfig()

    def assemble(
        self,
        *,
        output_dir: str,
        segment_records: list[SegmentTimelineRecord],
        segment_audio_paths: list[str],
        output_filename: str = "assembled_reference.wav",
    ) -> AssembledAudioResult:
        if not segment_records:
            raise ValueError("segment_records is empty")
        if not segment_audio_paths:
            raise ValueError("segment_audio_paths is empty")
        if len(segment_records) != len(segment_audio_paths):
            raise ValueError(
                f"segment_records and segment_audio_paths length mismatch: "
                f"{len(segment_records)} vs {len(segment_audio_paths)}"
            )

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        trimmed_segments_dir = output_path / self.config.trimmed_segments_dirname
        if self.config.write_trimmed_segment_files:
            trimmed_segments_dir.mkdir(parents=True, exist_ok=True)

        loaded_segments: list[tuple[np.ndarray, int]] = []
        sample_rate: int | None = None

        for audio_path in segment_audio_paths:
            audio, sr = self._load_mono_float_audio(audio_path)
            if sample_rate is None:
                sample_rate = int(sr)
            elif int(sr) != int(sample_rate):
                raise ValueError(
                    f"Inconsistent segment sample_rate: {sample_rate} vs {sr}, path={audio_path}"
                )
            loaded_segments.append((audio, int(sr)))

        assert sample_rate is not None

        updated_records: list[SegmentTimelineRecord] = []
        assembled_parts: list[np.ndarray] = []
        assembled_cursor_sec = 0.0
        previous_audio: np.ndarray | None = None

        for idx, ((audio, sr), raw_record, audio_path) in enumerate(
            zip(loaded_segments, segment_records, segment_audio_paths, strict=True)
        ):
            trimmed_audio, trim_head_sec, trim_tail_sec = self._trim_segment_audio(
                audio=audio,
                sample_rate=sr,
            )

            if trimmed_audio.size == 0:
                trimmed_audio = np.zeros((1,), dtype=np.float32)
                trim_head_sec = 0.0
                trim_tail_sec = 0.0

            crossfade_sec = 0.0
            if previous_audio is not None and previous_audio.size > 0 and trimmed_audio.size > 0:
                crossfade_sec = self._effective_crossfade_sec(
                    left_audio=previous_audio,
                    right_audio=trimmed_audio,
                    sample_rate=sr,
                )

            assembled_start_sec = assembled_cursor_sec - crossfade_sec
            assembled_start_sec = max(0.0, assembled_start_sec)

            updated_record = SegmentTimelineRecord(
                segment_id=int(raw_record.segment_id),
                text=str(raw_record.text),
                chars=list(raw_record.chars),
                pinyins=list(raw_record.pinyins),
                local_starts=[float(x) for x in raw_record.local_starts],
                local_ends=[float(x) for x in raw_record.local_ends],
                global_start_sec=float(raw_record.global_start_sec),
                sentence_id=int(raw_record.sentence_id),
                clause_id=int(raw_record.clause_id),
                trim_head_sec=float(trim_head_sec),
                trim_tail_sec=float(trim_tail_sec),
                assembled_start_sec=float(assembled_start_sec),
                assembled_end_sec=None,
            )

            if previous_audio is None or crossfade_sec <= 1e-9:
                assembled_parts.append(trimmed_audio)
                assembled_cursor_sec += float(trimmed_audio.shape[0]) / float(sr)
            else:
                mixed = self._crossfade_two_segments(
                    left_audio=assembled_parts[-1],
                    right_audio=trimmed_audio,
                    sample_rate=sr,
                    crossfade_sec=crossfade_sec,
                )
                assembled_parts[-1] = mixed
                assembled_cursor_sec = self._sum_duration_sec(assembled_parts, sr)

            updated_record.assembled_end_sec = float(assembled_cursor_sec)
            updated_records.append(updated_record)

            if self.config.write_trimmed_segment_files:
                trimmed_path = trimmed_segments_dir / f"{idx:04d}.wav"
                sf.write(
                    str(trimmed_path),
                    trimmed_audio.astype(np.float32, copy=False),
                    sr,
                    subtype="PCM_16",
                )

            previous_audio = trimmed_audio

        final_audio = self._concat_parts(assembled_parts)
        assembled_audio_path = output_path / output_filename
        sf.write(
            str(assembled_audio_path),
            final_audio.astype(np.float32, copy=False),
            sample_rate,
            subtype="PCM_16",
        )

        total_duration_sec = float(final_audio.shape[0]) / float(sample_rate)
        if updated_records:
            updated_records[-1].assembled_end_sec = float(total_duration_sec)

        return AssembledAudioResult(
            sample_rate=int(sample_rate),
            assembled_audio_path=str(assembled_audio_path),
            total_duration_sec=float(total_duration_sec),
            segment_records=updated_records,
        )

    def _load_mono_float_audio(self, audio_path: str) -> tuple[np.ndarray, int]:
        data, sr = sf.read(str(audio_path), dtype="float32", always_2d=False)
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 2:
            arr = np.mean(arr, axis=1).astype(np.float32, copy=False)
        arr = arr.reshape(-1).astype(np.float32, copy=False)
        return arr, int(sr)

    def _trim_segment_audio(
        self,
        *,
        audio: np.ndarray,
        sample_rate: int,
    ) -> tuple[np.ndarray, float, float]:
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return arr, 0.0, 0.0

        head_idx = self._detect_head_trim_index(arr, sample_rate)
        tail_idx = self._detect_tail_trim_index(arr, sample_rate)

        if tail_idx <= head_idx:
            return arr, 0.0, 0.0

        trimmed = arr[head_idx:tail_idx].astype(np.float32, copy=False)
        trim_head_sec = float(head_idx) / float(sample_rate)
        trim_tail_sec = float(arr.shape[0] - tail_idx) / float(sample_rate)
        return trimmed, trim_head_sec, trim_tail_sec

    def _detect_head_trim_index(self, audio: np.ndarray, sample_rate: int) -> int:
        max_trim_samples = int(round(self.config.max_trim_head_sec * sample_rate))
        keep_samples = int(round(self.config.min_silence_keep_sec * sample_rate))
        threshold = float(self.config.silence_rms_threshold)

        if max_trim_samples <= 0:
            return 0

        search_end = min(audio.shape[0], max_trim_samples)
        if search_end <= 0:
            return 0

        first_active = self._find_first_active_sample(audio[:search_end], threshold)
        if first_active is None:
            return 0

        trim_to = max(0, first_active - keep_samples)
        return int(min(trim_to, search_end))

    def _detect_tail_trim_index(self, audio: np.ndarray, sample_rate: int) -> int:
        max_trim_samples = int(round(self.config.max_trim_tail_sec * sample_rate))
        keep_samples = int(round(self.config.min_silence_keep_sec * sample_rate))
        threshold = float(self.config.silence_rms_threshold)

        if max_trim_samples <= 0:
            return int(audio.shape[0])

        search_start = max(0, audio.shape[0] - max_trim_samples)
        tail_region = audio[search_start:]
        if tail_region.size == 0:
            return int(audio.shape[0])

        last_active = self._find_last_active_sample(tail_region, threshold)
        if last_active is None:
            return int(audio.shape[0])

        absolute_last_active = search_start + last_active
        trim_to = min(audio.shape[0], absolute_last_active + keep_samples + 1)
        return int(max(trim_to, 1))

    def _find_first_active_sample(
        self,
        audio: np.ndarray,
        threshold: float,
    ) -> int | None:
        frame = max(32, min(512, audio.shape[0] // 8 if audio.shape[0] >= 8 else 32))
        hop = max(16, frame // 4)

        for start in range(0, max(1, audio.shape[0] - frame + 1), hop):
            win = audio[start : start + frame]
            rms = self._rms(win)
            peak = float(np.max(np.abs(win))) if win.size else 0.0
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                return int(start)
        if audio.shape[0] > 0:
            rms = self._rms(audio)
            peak = float(np.max(np.abs(audio)))
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                return 0
        return None

    def _find_last_active_sample(
        self,
        audio: np.ndarray,
        threshold: float,
    ) -> int | None:
        frame = max(32, min(512, audio.shape[0] // 8 if audio.shape[0] >= 8 else 32))
        hop = max(16, frame // 4)

        last_hit: int | None = None
        for start in range(0, max(1, audio.shape[0] - frame + 1), hop):
            win = audio[start : start + frame]
            rms = self._rms(win)
            peak = float(np.max(np.abs(win))) if win.size else 0.0
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                last_hit = int(start + win.shape[0] - 1)

        if last_hit is None and audio.shape[0] > 0:
            rms = self._rms(audio)
            peak = float(np.max(np.abs(audio)))
            if rms >= threshold or peak >= max(threshold * 2.2, 0.008):
                last_hit = int(audio.shape[0] - 1)

        return last_hit

    def _effective_crossfade_sec(
        self,
        *,
        left_audio: np.ndarray,
        right_audio: np.ndarray,
        sample_rate: int,
    ) -> float:
        desired = max(0.0, float(self.config.crossfade_sec))
        if desired <= 1e-9:
            return 0.0

        max_left = float(left_audio.shape[0]) / float(sample_rate)
        max_right = float(right_audio.shape[0]) / float(sample_rate)
        effective = min(desired, max_left * 0.35, max_right * 0.35)
        return max(0.0, effective)

    def _crossfade_two_segments(
        self,
        *,
        left_audio: np.ndarray,
        right_audio: np.ndarray,
        sample_rate: int,
        crossfade_sec: float,
    ) -> np.ndarray:
        left_arr = np.asarray(left_audio, dtype=np.float32).reshape(-1)
        right_arr = np.asarray(right_audio, dtype=np.float32).reshape(-1)

        fade_samples = int(round(crossfade_sec * sample_rate))
        if fade_samples <= 0:
            return np.concatenate([left_arr, right_arr], axis=0).astype(np.float32, copy=False)

        fade_samples = min(fade_samples, left_arr.shape[0], right_arr.shape[0])
        if fade_samples <= 0:
            return np.concatenate([left_arr, right_arr], axis=0).astype(np.float32, copy=False)

        left_keep = left_arr[:-fade_samples]
        left_fade = left_arr[-fade_samples:]
        right_fade = right_arr[:fade_samples]
        right_keep = right_arr[fade_samples:]

        fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        mixed = left_fade * fade_out + right_fade * fade_in

        return np.concatenate([left_keep, mixed, right_keep], axis=0).astype(np.float32, copy=False)

    def _concat_parts(self, parts: list[np.ndarray]) -> np.ndarray:
        if not parts:
            return np.zeros((0,), dtype=np.float32)
        if len(parts) == 1:
            return np.asarray(parts[0], dtype=np.float32).reshape(-1)
        return np.concatenate(
            [np.asarray(x, dtype=np.float32).reshape(-1) for x in parts],
            axis=0,
        ).astype(np.float32, copy=False)

    def _sum_duration_sec(self, parts: list[np.ndarray], sample_rate: int) -> float:
        total_samples = sum(int(np.asarray(x).shape[0]) for x in parts)
        return float(total_samples) / float(sample_rate)

    def _rms(self, audio: np.ndarray) -> float:
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(arr))))