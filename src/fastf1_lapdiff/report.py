from __future__ import annotations

import dataclasses
import json
from typing import Any

from .models import ComparisonReport, Detection, LapMetadata


def render_markdown(report: ComparisonReport, limit: int = 12) -> str:
    lines: list[str] = []
    lines.append("# Lap Comparison Summary")
    lines.append("")
    lines.append(f"Reference lap: {_lap_title(report.reference)}")
    lines.append(f"Compared lap: {_lap_title(report.compared)}")
    if report.total_delta_seconds is not None:
        lines.append(f"Total difference: {_seconds(report.total_delta_seconds)}")
    sector_text = ", ".join(
        f"S{i + 1} {_seconds(value)}" for i, value in enumerate(report.sector_deltas_seconds) if value is not None
    )
    if sector_text:
        lines.append(f"Sector differences: {sector_text}")
    lines.append(f"Reference validity: {report.reference_validity.classification}")
    lines.append(f"Compared validity: {report.compared_validity.classification}")
    for warning in report.reference_validity.warnings:
        lines.append(f"- Reference warning: {warning}")
    for warning in report.compared_validity.warnings:
        lines.append(f"- Compared warning: {warning}")
    lines.append("")
    lines.append("## Context")
    for item in report.tyre_context:
        lines.append(f"- {item}")
    if report.weather_context:
        weather = ", ".join(f"{key}: {value}" for key, value in report.weather_context.items() if key != "Time")
        lines.append(f"- Weather nearest compared lap: {weather}")
        lines.append("- Weather is context only; this tool cannot isolate weather causality from tyres, traffic, or driving.")
    lines.append("")
    lines.append("## Overall Interpretation")
    lines.append(report.summary)
    lines.append("")

    losses = [item for item in report.detections if item.time_impact_seconds > 0.035]
    gains = [item for item in report.detections if item.time_impact_seconds < -0.035]
    other = [item for item in report.detections if abs(item.time_impact_seconds) <= 0.035]

    _append_detection_group(lines, "Main Time Losses", losses[:limit])
    _append_detection_group(lines, "Main Time Gains", gains[:limit])
    _append_detection_group(lines, "Other Findings And Context", other[:limit])

    lines.append("")
    lines.append("## Data Limits")
    lines.append("FastF1 does not provide steering angle, brake pressure, tyre wear percentage, tyre temperature, tyre pressure, fuel load, wheel speed, yaw rate, slip angle, real G-force, lockup, or wheelspin channels. Any instability, traction, missed-apex, understeer-like, or oversteer-like finding is a labelled heuristic inference.")
    return "\n".join(lines)


def render_json(report: ComparisonReport) -> str:
    return json.dumps(dataclasses.asdict(report), indent=2, default=str)


def _append_detection_group(lines: list[str], title: str, detections: list[Detection]) -> None:
    lines.append(f"## {title}")
    if not detections:
        lines.append("No notable findings.")
        lines.append("")
        return

    for index, detection in enumerate(sorted(detections, key=lambda item: -abs(item.time_impact_seconds)), start=1):
        lines.append(f"{index}. {detection.section}: {detection.difference_type}")
        lines.append(f"   Time impact: {_seconds(detection.time_impact_seconds)}")
        lines.append(f"   Severity: {detection.severity}")
        lines.append(f"   Confidence: {detection.confidence}")
        lines.append(f"   Evidence kind: {detection.evidence_kind}")
        lines.append(f"   What happened: {detection.what_happened}")
        lines.append("   Evidence:")
        for evidence in detection.evidence:
            lines.append(f"   - {evidence}")
        lines.append(f"   Interpretation: {detection.interpretation}")
        lines.append("")


def _lap_title(metadata: LapMetadata) -> str:
    lap_time = f" - {_clock(metadata.lap_time_seconds)}" if metadata.lap_time_seconds is not None else ""
    return f"{metadata.driver} lap {metadata.lap_number}{lap_time}"


def _seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.3f} s"


def _clock(seconds: float) -> str:
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:06.3f}"

