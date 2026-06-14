from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

Confidence = Literal["High", "Medium", "Low"]
Severity = Literal["High", "Medium", "Low", "Info"]
EvidenceKind = Literal["direct", "computed", "heuristic", "context"]


@dataclass(frozen=True)
class LapMetadata:
    driver: str
    lap_number: int
    lap_time_seconds: float | None = None
    sector_times_seconds: tuple[float | None, float | None, float | None] = (None, None, None)
    compound: str | None = None
    tyre_life: float | None = None
    fresh_tyre: bool | None = None
    stint: int | None = None
    track_status: str | None = None
    is_accurate: bool | None = None
    deleted: bool | None = None
    pit_in: bool = False
    pit_out: bool = False


@dataclass
class LapData:
    metadata: LapMetadata
    telemetry: pd.DataFrame


@dataclass
class LapValidity:
    classification: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class Section:
    label: str
    start_distance: float
    end_distance: float
    section_type: str

    @property
    def length(self) -> float:
        return self.end_distance - self.start_distance


@dataclass
class Detection:
    section: str
    difference_type: str
    start_distance: float
    end_distance: float
    time_impact_seconds: float
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    what_happened: str
    evidence: list[str]
    interpretation: str


@dataclass
class ComparisonReport:
    reference: LapMetadata
    compared: LapMetadata
    total_delta_seconds: float | None
    sector_deltas_seconds: tuple[float | None, float | None, float | None]
    reference_validity: LapValidity
    compared_validity: LapValidity
    weather_context: dict[str, Any]
    tyre_context: list[str]
    detections: list[Detection]
    summary: str

