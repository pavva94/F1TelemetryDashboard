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
class SectionMetrics:
    label: str
    section_type: str
    start_distance: float
    end_distance: float
    length: float
    time_delta_seconds: float
    average_speed_delta_kmh: float
    minimum_speed_delta_kmh: float
    maximum_speed_delta_kmh: float
    entry_speed_delta_kmh: float
    exit_speed_delta_kmh: float
    reference_speed_gain_kmh: float
    compared_speed_gain_kmh: float
    speed_gain_delta_kmh: float
    average_acceleration_delta_ms2: float
    average_throttle_delta_pct: float
    full_throttle_delta_m: float | None
    brake_active_distance_delta_m: float
    drs_active_distance_delta_m: float
    reference_gear_mode: int | None
    compared_gear_mode: int | None
    average_rpm_delta: float
    average_line_deviation_m: float | None
    data_kind: EvidenceKind
    confidence: Confidence
    note: str


@dataclass
class PerformanceProfile:
    straight_time_delta_seconds: float
    braking_time_delta_seconds: float
    low_speed_corner_delta_seconds: float
    medium_speed_corner_delta_seconds: float
    high_speed_corner_delta_seconds: float
    drs_time_delta_seconds: float
    average_corner_exit_speed_delta_kmh: float | None
    average_full_throttle_delta_m: float | None
    average_drs_distance_delta_m: float
    stronger_indicators: list[str] = field(default_factory=list)
    weaker_indicators: list[str] = field(default_factory=list)
    inference_notes: list[str] = field(default_factory=list)


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
