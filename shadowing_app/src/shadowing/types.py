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


class PlayerCommandType(str, Enum):
    START = "start"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"
    SET_GAIN = "set_gain"


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
    samples: "object"
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
    target_gain: Optional[float] = None
    replay_lockin: bool = False


@dataclass(slots=True)
class ControlFeatures:
    lead_raw: Optional[float]
    lead_ema: Optional[float]
    lead_slope: Optional[float]
    alignment_conf: float
    alignment_stable: bool
    user_speaking: bool
    recent_partial_rate: float
    recent_hold_count: int
    dynamic_target_lead: float
    suggested_gain: float
    playback_state: str