from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class PlaybackState(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    HOLDING = "holding"
    SEEKING = "seeking"
    FINISHED = "finished"


class ControlAction(str, Enum):
    NOOP = "noop"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"


class AsrEventType(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"
    ENDPOINT = "endpoint"


@dataclass(slots=True)
class AudioChunk:
    chunk_id: int
    sample_rate: int
    channels: int
    samples: "object"   # numpy.ndarray
    duration_sec: float
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
    tokens: List[RefToken]
    total_duration_sec: float


@dataclass(slots=True)
class LessonManifest:
    lesson_id: str
    lesson_text: str
    sample_rate_out: int
    chunk_paths: List[str]
    reference_map_path: str


@dataclass(slots=True)
class PlaybackStatus:
    state: PlaybackState
    chunk_id: int
    frame_index: int
    t_host_output_sec: float
    t_ref_sched_sec: float
    t_ref_heard_sec: float


@dataclass(slots=True)
class AsrEvent:
    event_type: AsrEventType
    text: str
    normalized_text: str
    pinyin_seq: List[str]
    emitted_at_sec: float


@dataclass(slots=True)
class AlignResult:
    committed_ref_idx: int
    candidate_ref_idx: int
    ref_time_sec: float
    confidence: float
    stable: bool
    matched_text: str = ""
    matched_pinyin: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ControlDecision:
    action: ControlAction
    reason: str
    target_time_sec: Optional[float] = None
    lead_sec: Optional[float] = None