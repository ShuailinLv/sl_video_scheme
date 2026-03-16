from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
from pypinyin import lazy_pinyin

from shadowing.interfaces.tts import TTSProvider
from shadowing.preprocess.providers.audio_assembler import (
    AudioAssembler,
    AudioAssemblerConfig,
)
from shadowing.preprocess.reference_builder import (
    ReferenceBuilder,
    SegmentTimelineRecord,
)
from shadowing.preprocess.segmenter import ShadowingSegment, ShadowingSegmenter
from shadowing.types import LessonManifest, ReferenceMap


class ElevenLabsTTSProvider(TTSProvider):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
        output_format: str = "pcm_44100",
        timeout_sec: float = 120.0,
        *,
        seed: int | None = 2025,
        continuity_context_chars_prev: int = 100,
        continuity_context_chars_next: int = 100,
        target_chars_per_segment: int = 28,
        hard_max_chars_per_segment: int = 54,
        min_chars_per_segment: int = 6,
        context_window_segments: int = 2,
        max_retries_per_segment: int = 2,
        assemble_reference_audio: bool = True,
        assembled_reference_filename: str = "assembled_reference.wav",
        silence_rms_threshold: float = 0.0035,
        min_silence_keep_sec: float = 0.035,
        max_trim_head_sec: float = 0.180,
        max_trim_tail_sec: float = 0.220,
        crossfade_sec: float = 0.025,
        write_trimmed_segment_files: bool = False,
        trimmed_segments_dirname: str = "assembled_segments",
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.timeout_sec = float(timeout_sec)
        self.seed = seed
        self.max_retries_per_segment = max(1, int(max_retries_per_segment))
        self.continuity_context_chars_prev = max(20, int(continuity_context_chars_prev))
        self.continuity_context_chars_next = max(20, int(continuity_context_chars_next))
        self.assemble_reference_audio = bool(assemble_reference_audio)
        self.assembled_reference_filename = str(assembled_reference_filename)
        self.segmenter = ShadowingSegmenter(
            target_chars_per_segment=target_chars_per_segment,
            hard_max_chars_per_segment=hard_max_chars_per_segment,
            min_chars_per_segment=min_chars_per_segment,
            context_window_segments=context_window_segments,
            context_max_chars=max(
                self.continuity_context_chars_prev,
                self.continuity_context_chars_next,
            ),
        )
        self.reference_builder = ReferenceBuilder()
        self.audio_assembler = AudioAssembler(
            AudioAssemblerConfig(
                silence_rms_threshold=float(silence_rms_threshold),
                min_silence_keep_sec=float(min_silence_keep_sec),
                max_trim_head_sec=float(max_trim_head_sec),
                max_trim_tail_sec=float(max_trim_tail_sec),
                crossfade_sec=float(crossfade_sec),
                write_trimmed_segment_files=bool(write_trimmed_segment_files),
                trimmed_segments_dirname=str(trimmed_segments_dirname),
            )
        )

    def synthesize_lesson(
        self,
        lesson_id: str,
        text: str,
        output_dir: str,
    ) -> tuple[LessonManifest, ReferenceMap]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        chunks_dir = output_path / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        alignments_dir = output_path / "alignments"
        alignments_dir.mkdir(parents=True, exist_ok=True)

        lesson_text = str(text or "").strip()
        if not lesson_text:
            raise ValueError("No valid lesson text provided.")

        segments = self.segmenter.segment_text(lesson_text)
        if not segments:
            raise ValueError("No valid segments found after segmentation.")

        chunk_paths: list[str] = []
        raw_segment_records: list[SegmentTimelineRecord] = []
        segments_manifest_records: list[dict] = []
        global_time_offset = 0.0
        total_audio_duration = 0.0
        sample_rate_out: int | None = None

        with httpx.Client(timeout=self.timeout_sec) as client:
            for seg in segments:
                response = self._request_tts_with_retries(
                    client=client,
                    segment=seg,
                )
                audio_bytes = base64.b64decode(response["audio_base64"])
                chunk_file, chunk_samplerate, chunk_duration = self._write_chunk_audio(
                    chunks_dir=chunks_dir,
                    segment_id=seg.segment_id,
                    audio_bytes=audio_bytes,
                )

                if sample_rate_out is None:
                    sample_rate_out = int(chunk_samplerate)
                elif int(sample_rate_out) != int(chunk_samplerate):
                    raise ValueError(
                        f"Inconsistent chunk sample rate: {sample_rate_out} vs {chunk_samplerate}"
                    )

                chunk_paths.append(str(chunk_file))

                alignment = response.get("alignment") or response.get("normalized_alignment")
                if not alignment:
                    raise ValueError(
                        f"No alignment returned for segment {seg.segment_id}: {seg.text!r}"
                    )

                chars = alignment.get("characters") or []
                local_starts = alignment.get("character_start_times_seconds") or []
                local_ends = alignment.get("character_end_times_seconds") or []

                if not (len(chars) == len(local_starts) == len(local_ends)):
                    raise ValueError(
                        f"Alignment length mismatch in segment {seg.segment_id}: "
                        f"{len(chars)=}, {len(local_starts)=}, {len(local_ends)=}"
                    )

                pinyins = [lazy_pinyin(ch)[0] if str(ch).strip() else "" for ch in chars]

                alignment_path = alignments_dir / f"{seg.segment_id:04d}.alignment.json"
                alignment_payload = {
                    "segment_id": int(seg.segment_id),
                    "text": str(seg.text),
                    "sentence_id": int(seg.sentence_id),
                    "clause_id": int(seg.clause_id),
                    "kind": str(seg.kind),
                    "prev_context_text": str(seg.prev_context_text),
                    "next_context_text": str(seg.next_context_text),
                    "global_start_sec": float(global_time_offset),
                    "duration_sec": float(chunk_duration),
                    "sample_rate": int(chunk_samplerate),
                    "alignment": alignment,
                }
                alignment_path.write_text(
                    json.dumps(alignment_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                alignment_end_sec = max((float(x) for x in local_ends), default=0.0)
                offset_advance_sec = alignment_end_sec if alignment_end_sec > 0.0 else float(chunk_duration)

                raw_record = SegmentTimelineRecord(
                    segment_id=int(seg.segment_id),
                    text=str(seg.text),
                    chars=[str(x) for x in chars],
                    pinyins=[str(x or "") for x in pinyins],
                    local_starts=[float(x) for x in local_starts],
                    local_ends=[float(x) for x in local_ends],
                    global_start_sec=float(global_time_offset),
                    sentence_id=int(seg.sentence_id),
                    clause_id=int(seg.clause_id),
                    trim_head_sec=0.0,
                    trim_tail_sec=0.0,
                    assembled_start_sec=None,
                    assembled_end_sec=None,
                )
                raw_segment_records.append(raw_record)

                segments_manifest_records.append(
                    {
                        "segment_id": int(seg.segment_id),
                        "sentence_id": int(seg.sentence_id),
                        "clause_id": int(seg.clause_id),
                        "kind": str(seg.kind),
                        "text": str(seg.text),
                        "prev_context_text": str(seg.prev_context_text),
                        "next_context_text": str(seg.next_context_text),
                        "audio_path": str(chunk_file),
                        "alignment_path": str(alignment_path),
                        "duration_sec": float(chunk_duration),
                        "sample_rate": int(chunk_samplerate),
                        "char_count": len(self._normalize_text(seg.text)),
                        "alignment_char_count": len(chars),
                        "global_start_sec": float(global_time_offset),
                        "global_end_sec": float(global_time_offset + offset_advance_sec),
                        "request_seed": self.seed,
                        "output_format": self.output_format,
                        "model_id": self.model_id,
                        "chars": [str(x) for x in chars],
                        "pinyins": [str(x or "") for x in pinyins],
                        "local_starts": [float(x) for x in local_starts],
                        "local_ends": [float(x) for x in local_ends],
                        "trim_head_sec": 0.0,
                        "trim_tail_sec": 0.0,
                        "assembled_start_sec": None,
                        "assembled_end_sec": None,
                    }
                )

                global_time_offset += offset_advance_sec
                total_audio_duration = global_time_offset

        final_segment_records = raw_segment_records
        final_total_duration_sec = float(total_audio_duration)
        assembled_audio_path: str | None = None

        if self.assemble_reference_audio and raw_segment_records and chunk_paths:
            assembled = self.audio_assembler.assemble(
                output_dir=str(output_path),
                segment_records=raw_segment_records,
                segment_audio_paths=chunk_paths,
                output_filename=self.assembled_reference_filename,
            )
            final_segment_records = assembled.segment_records
            final_total_duration_sec = float(assembled.total_duration_sec)
            assembled_audio_path = assembled.assembled_audio_path

            manifest_by_id = {int(x["segment_id"]): x for x in segments_manifest_records}
            for record in final_segment_records:
                item = manifest_by_id.get(int(record.segment_id))
                if item is None:
                    continue
                item["trim_head_sec"] = float(record.trim_head_sec)
                item["trim_tail_sec"] = float(record.trim_tail_sec)
                item["assembled_start_sec"] = (
                    None if record.assembled_start_sec is None else float(record.assembled_start_sec)
                )
                item["assembled_end_sec"] = (
                    None if record.assembled_end_sec is None else float(record.assembled_end_sec)
                )

        segments_manifest_path = output_path / "segments_manifest.json"
        segments_manifest_path.write_text(
            json.dumps(
                {
                    "lesson_id": lesson_id,
                    "lesson_text": lesson_text,
                    "voice_id": self.voice_id,
                    "model_id": self.model_id,
                    "output_format": self.output_format,
                    "seed": self.seed,
                    "total_duration_sec": float(final_total_duration_sec),
                    "assembled_audio_path": assembled_audio_path,
                    "segments": segments_manifest_records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        ref_map = self.reference_builder.build_from_segment_records(
            lesson_id=lesson_id,
            segment_records=final_segment_records,
            total_duration_sec=float(final_total_duration_sec),
        )

        manifest = LessonManifest(
            lesson_id=lesson_id,
            lesson_text=lesson_text,
            sample_rate_out=sample_rate_out or 44100,
            chunk_paths=chunk_paths,
            reference_map_path=str(output_path / "reference_map.json"),
            provider_name="elevenlabs",
            output_format=self.output_format,
        )
        return manifest, ref_map

    def _request_tts_with_retries(
        self,
        *,
        client: httpx.Client,
        segment: ShadowingSegment,
    ) -> dict:
        last_error: Exception | None = None
        request_plans = [
            {
                "previous_text": self._trim_context(
                    segment.prev_context_text,
                    self.continuity_context_chars_prev,
                    from_left=True,
                ),
                "next_text": self._trim_context(
                    segment.next_context_text,
                    self.continuity_context_chars_next,
                    from_left=False,
                ),
                "seed": self.seed,
            },
            {
                "previous_text": self._trim_context(segment.prev_context_text, 48, from_left=True),
                "next_text": self._trim_context(segment.next_context_text, 48, from_left=False),
                "seed": self.seed,
            },
            {
                "previous_text": "",
                "next_text": "",
                "seed": self.seed,
            },
        ]
        max_attempts = min(len(request_plans), self.max_retries_per_segment + 1)
        for i in range(max_attempts):
            plan = request_plans[i]
            try:
                return self._request_tts_with_timestamps(
                    client=client,
                    text=segment.text,
                    previous_text=plan["previous_text"],
                    next_text=plan["next_text"],
                    seed=plan["seed"],
                )
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(
            f"ElevenLabs TTS failed after retries for segment={segment.segment_id}, "
            f"text={segment.text!r}, error={last_error}"
        )

    def _write_chunk_audio(
        self,
        chunks_dir: Path,
        segment_id: int,
        audio_bytes: bytes,
    ) -> tuple[Path, int, float]:
        fmt = self.output_format.strip().lower()
        if fmt.startswith("pcm_"):
            return self._write_pcm_like_audio(chunks_dir, segment_id, audio_bytes, fmt)

        ext = self._infer_container_extension(fmt)
        chunk_file = chunks_dir / f"{segment_id:04d}.{ext}"
        chunk_file.write_bytes(audio_bytes)
        info = sf.info(str(chunk_file))
        duration_sec = float(info.duration)
        sample_rate = int(info.samplerate)
        return chunk_file, sample_rate, duration_sec

    def _write_pcm_like_audio(
        self,
        chunks_dir: Path,
        segment_id: int,
        audio_bytes: bytes,
        output_format: str,
    ) -> tuple[Path, int, float]:
        sample_rate = self._parse_pcm_sample_rate(output_format)
        chunk_file = chunks_dir / f"{segment_id:04d}.wav"
        wav_data, wav_sr = self._try_decode_as_container(audio_bytes)
        if wav_data is not None:
            wav_sr = int(wav_sr or sample_rate)
            audio_f32 = self._to_mono_float32(wav_data)
            sf.write(str(chunk_file), audio_f32, wav_sr, subtype="PCM_16")
            duration_sec = float(audio_f32.shape[0]) / float(wav_sr)
            return chunk_file, wav_sr, duration_sec

        if len(audio_bytes) % 2 != 0:
            head = audio_bytes[:16].hex()
            raise ValueError(
                "ElevenLabs returned pcm_* audio payload with odd byte length, "
                f"cannot parse as int16 PCM. segment_id={segment_id}, "
                f"bytes={len(audio_bytes)}, head={head}"
            )

        pcm_i16 = np.frombuffer(audio_bytes, dtype="<i2")
        if pcm_i16.size == 0:
            raise ValueError(f"Empty PCM audio returned for segment {segment_id}.")

        audio_f32 = (pcm_i16.astype(np.float32) / 32768.0).astype(np.float32, copy=False)
        sf.write(str(chunk_file), audio_f32, sample_rate, subtype="PCM_16")
        duration_sec = float(audio_f32.shape[0]) / float(sample_rate)
        return chunk_file, sample_rate, duration_sec

    def _try_decode_as_container(self, audio_bytes: bytes) -> tuple[np.ndarray | None, int | None]:
        try:
            bio = io.BytesIO(audio_bytes)
            data, sr = sf.read(bio, dtype="float32", always_2d=False)
            arr = np.asarray(data, dtype=np.float32)
            if arr.size == 0:
                return None, None
            return arr, int(sr)
        except Exception:
            return None, None

    def _to_mono_float32(self, audio: np.ndarray) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim == 1:
            return arr
        return np.mean(arr, axis=1).astype(np.float32, copy=False)

    def _parse_pcm_sample_rate(self, output_format: str) -> int:
        m = re.fullmatch(r"pcm_(\d+)", output_format.strip().lower())
        if not m:
            raise ValueError(f"Unsupported PCM output_format: {output_format}")
        return int(m.group(1))

    def _infer_container_extension(self, output_format: str) -> str:
        fmt = output_format.strip().lower()
        if fmt.startswith("mp3_"):
            return "mp3"
        if fmt.startswith("ulaw_"):
            return "wav"
        if fmt.startswith("pcm_"):
            return "wav"
        return "bin"

    def _request_tts_with_timestamps(
        self,
        client: httpx.Client,
        text: str,
        previous_text: str = "",
        next_text: str = "",
        seed: int | None = None,
    ) -> dict:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {
            "text": text,
            "model_id": self.model_id,
            "output_format": self.output_format,
        }
        if previous_text:
            payload["previous_text"] = previous_text
        if next_text:
            payload["next_text"] = next_text
        if seed is not None:
            payload["seed"] = int(seed)

        response = client.post(url, headers=headers, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"ElevenLabs TTS failed: status={response.status_code}, body={response.text}"
            ) from e

        data = response.json()
        if "audio_base64" not in data:
            raise RuntimeError(f"ElevenLabs response missing audio_base64: {data}")
        return data

    def _trim_context(self, text: str, max_chars: int, *, from_left: bool) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if len(raw) <= max_chars:
            return raw
        if from_left:
            return raw[-max_chars:]
        return raw[:max_chars]

    def _normalize_text(self, text: str) -> str:
        raw = str(text or "").strip()
        raw = raw.replace("\u3000", " ")
        raw = re.sub(r"\s+", "", raw)
        raw = re.sub(r"[，。！？；：、“”‘’\"'（）()\[\]【】<>\-—…,.!?;:/\\|`~@#$%^&*_+=]+", "", raw)
        return raw