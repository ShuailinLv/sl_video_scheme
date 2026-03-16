from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(slots=True)
class ReferenceAudioFrameFeatures:
    time_sec: float
    envelope: float
    onset_strength: float
    voiced_ratio: float
    band_energy: list[float]
    embedding: list[float] = field(default_factory=list)


@dataclass(slots=True)
class ReferenceBoundaryHint:
    time_sec: float
    kind: str
    weight: float = 1.0


@dataclass(slots=True)
class ReferenceTokenAcousticTemplate:
    token_idx: int
    time_sec: float
    embedding: list[float] = field(default_factory=list)


@dataclass(slots=True)
class ReferenceAudioFeatures:
    lesson_id: str
    frame_hop_sec: float
    frame_size_sec: float
    sample_rate: int
    frames: list[ReferenceAudioFrameFeatures] = field(default_factory=list)
    boundaries: list[ReferenceBoundaryHint] = field(default_factory=list)
    token_time_hints_sec: list[float] = field(default_factory=list)
    token_acoustic_templates: list[ReferenceTokenAcousticTemplate] = field(default_factory=list)
    total_duration_sec: float = 0.0
