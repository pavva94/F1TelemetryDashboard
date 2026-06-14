from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .align import align_laps
from .models import ComparisonReport, Detection, LapData, LapValidity, Section
from .sections import make_sections


ABNORMAL_TRACK_STATUS = {"2", "4", "5", "6", "7"}


def analyze_laps(reference: LapData, compared: LapData, weather_context: dict[str, Any] | None = None) -> ComparisonReport:
    aligned = align_laps(reference.telemetry, compared.telemetry)
    sections = make_sections(aligned)
    detections: list[Detection] = []

    detections.extend(_time_gain_loss_detections(aligned, sections))
    for section in sections:
        part = _slice(aligned, section)
        if part.empty:
            continue
        detections.extend(_brake_detections(part, section))
        detections.extend(_speed_throttle_detections(part, section))
        detections.extend(_gear_drs_line_detections(part, section))
        detections.extend(_anomaly_detections(part, section))

    detections.sort(key=lambda item: (item.severity != "High", -abs(item.time_impact_seconds)))

    total_delta = _delta(compared.metadata.lap_time_seconds, reference.metadata.lap_time_seconds)
    sector_deltas = tuple(_delta(cmp, ref) for cmp, ref in zip(compared.metadata.sector_times_seconds, reference.metadata.sector_times_seconds))
    tyre_context = _tyre_context(reference, compared)
    ref_validity = validate_lap(reference)
    cmp_validity = validate_lap(compared)
    summary = _summary(total_delta, sector_deltas, detections, tyre_context, ref_validity, cmp_validity)

    return ComparisonReport(
        reference=reference.metadata,
        compared=compared.metadata,
        total_delta_seconds=total_delta,
        sector_deltas_seconds=sector_deltas,
        reference_validity=ref_validity,
        compared_validity=cmp_validity,
        weather_context=weather_context or {},
        tyre_context=tyre_context,
        detections=detections[:40],
        summary=summary,
    )


def validate_lap(lap: LapData) -> LapValidity:
    warnings: list[str] = []
    meta = lap.metadata
    if meta.deleted:
        warnings.append("Lap is marked deleted.")
    if meta.is_accurate is False:
        warnings.append("FastF1 marks this lap as not accurate.")
    if meta.pit_in or meta.pit_out:
        warnings.append("Lap includes pit-in or pit-out behavior.")
    if meta.track_status and any(code in str(meta.track_status) for code in ABNORMAL_TRACK_STATUS):
        warnings.append(f"TrackStatus {meta.track_status} may indicate flags, safety car, VSC, or other disruption.")

    missing = [channel for channel in ["Speed", "Throttle", "Brake", "nGear", "RPM", "DRS", "Distance", "Time"] if channel not in lap.telemetry.columns]
    if missing:
        warnings.append(f"Missing telemetry channels: {', '.join(missing)}.")
    if len(lap.telemetry) < 50:
        warnings.append("Telemetry has very few samples.")
    if lap.telemetry.isna().mean(numeric_only=False).max() > 0.2:
        warnings.append("Telemetry has a high missing-data rate.")

    if not warnings:
        return LapValidity("Clean", [])
    if len(warnings) <= 2 and not meta.deleted:
        return LapValidity("Probably clean", warnings)
    if meta.deleted or meta.pit_in or meta.pit_out:
        return LapValidity("Invalid for direct comparison", warnings)
    return LapValidity("Context affected", warnings)


def _time_gain_loss_detections(aligned: pd.DataFrame, sections: list[Section]) -> list[Detection]:
    output: list[Detection] = []
    for section in sections:
        part = _slice(aligned, section)
        if part.empty:
            continue
        local_delta = _local_delta(part)
        if abs(local_delta) < 0.035:
            continue
        output.append(
            Detection(
                section=section.label,
                difference_type="Time gain/loss",
                start_distance=section.start_distance,
                end_distance=section.end_distance,
                time_impact_seconds=local_delta,
                severity=_severity(local_delta),
                confidence=_confidence(abs(local_delta), 0.08, 0.16),
                evidence_kind="computed",
                what_happened=_gain_loss_text(local_delta, section),
                evidence=[
                    f"Delta at section start: {_fmt_seconds(float(part['delta_time'].iloc[0]))}",
                    f"Delta at section end: {_fmt_seconds(float(part['delta_time'].iloc[-1]))}",
                    f"Local impact: {_fmt_seconds(local_delta)}",
                ],
                interpretation=_primary_reason(part, local_delta),
            )
        )
    return output


def _brake_detections(part: pd.DataFrame, section: Section) -> list[Detection]:
    ref = _event_bounds(part, "ref_Brake", threshold=0.5, above=True)
    cmp = _event_bounds(part, "cmp_Brake", threshold=0.5, above=True)
    if not ref or not cmp:
        return []

    output: list[Detection] = []
    start_diff = cmp[0] - ref[0]
    end_diff = cmp[1] - ref[1]
    dist_diff = (cmp[1] - cmp[0]) - (ref[1] - ref[0])
    impact = _local_delta(part)

    if abs(start_diff) > 8:
        output.append(_detection(
            section,
            "Earlier braking" if start_diff < 0 else "Later braking",
            impact,
            "direct",
            [
                f"Brake start: {_fmt_m(abs(start_diff))} {'earlier' if start_diff < 0 else 'later'}",
                f"Reference brake start: {_fmt_m(ref[0])}",
                f"Compared brake start: {_fmt_m(cmp[0])}",
                f"Minimum speed difference: {_fmt_kmh(part['cmp_Speed'].min() - part['ref_Speed'].min())}",
            ],
            "Later braking is only positive if minimum speed, exit speed, and throttle application are not compromised. Brake pressure is not available.",
            confidence=_confidence(abs(start_diff), 12, 25),
        ))

    if abs(end_diff) > 8:
        output.append(_detection(
            section,
            "Earlier brake release" if end_diff < 0 else "Later brake release",
            impact,
            "direct",
            [
                f"Brake release: {_fmt_m(abs(end_diff))} {'earlier' if end_diff < 0 else 'later'}",
                f"Reference brake end: {_fmt_m(ref[1])}",
                f"Compared brake end: {_fmt_m(cmp[1])}",
            ],
            "This describes brake-on continuation only; FastF1 does not provide brake pressure or steering angle.",
            confidence=_confidence(abs(end_diff), 12, 25),
        ))

    if abs(dist_diff) > 12:
        output.append(_detection(
            section,
            "Longer braking zone" if dist_diff > 0 else "Shorter braking zone",
            impact,
            "direct",
            [
                f"Braking distance difference: {_fmt_m(abs(dist_diff))} {'longer' if dist_diff > 0 else 'shorter'}",
                f"Reference braking distance: {_fmt_m(ref[1] - ref[0])}",
                f"Compared braking distance: {_fmt_m(cmp[1] - cmp[0])}",
            ],
            "Brake state is boolean in FastF1, so this is duration/distance only, not brake-pressure modulation.",
            confidence=_confidence(abs(dist_diff), 18, 35),
        ))

    return output


def _speed_throttle_detections(part: pd.DataFrame, section: Section) -> list[Detection]:
    output: list[Detection] = []
    impact = _local_delta(part)
    ref_min = float(part["ref_Speed"].min())
    cmp_min = float(part["cmp_Speed"].min())
    min_diff = cmp_min - ref_min
    if abs(min_diff) > 4:
        output.append(_detection(
            section,
            "Lower minimum corner speed" if min_diff < 0 else "Higher minimum corner speed",
            impact,
            "direct",
            [f"Reference minimum speed: {_fmt_kmh(ref_min)}", f"Compared minimum speed: {_fmt_kmh(cmp_min)}", f"Difference: {_fmt_kmh(min_diff)}"],
            "Minimum speed is directly measured from FastF1 speed telemetry.",
            confidence=_confidence(abs(min_diff), 5, 9),
        ))

    entry_speed_diff = _mean_at(part, 0.08, "cmp_Speed") - _mean_at(part, 0.08, "ref_Speed")
    exit_speed_diff = _mean_at(part, 0.92, "cmp_Speed") - _mean_at(part, 0.92, "ref_Speed")
    if abs(exit_speed_diff) > 4:
        output.append(_detection(
            section,
            "Lower exit speed" if exit_speed_diff < 0 else "Higher exit speed",
            impact,
            "direct",
            [f"Entry speed difference: {_fmt_kmh(entry_speed_diff)}", f"Exit speed difference: {_fmt_kmh(exit_speed_diff)}", f"Acceleration estimate difference: {_fmt(part['accel_diff'].mean(), 'm/s^2')}"],
            "Exit speed and approximate acceleration are useful for identifying whether loss carries onto the following straight.",
            confidence=_confidence(abs(exit_speed_diff), 5, 10),
        ))

    ref_throttle = _event_bounds(part, "ref_Throttle", threshold=10, above=True)
    cmp_throttle = _event_bounds(part, "cmp_Throttle", threshold=10, above=True)
    if ref_throttle and cmp_throttle:
        start_diff = cmp_throttle[0] - ref_throttle[0]
        if abs(start_diff) > 10:
            output.append(_detection(
                section,
                "Earlier throttle" if start_diff < 0 else "Later throttle",
                impact,
                "direct",
                [f"Throttle start: {_fmt_m(abs(start_diff))} {'earlier' if start_diff < 0 else 'later'}", f"Exit speed difference: {_fmt_kmh(exit_speed_diff)}"],
                "Throttle timing is directly measured, but the reason for delay remains contextual.",
                confidence=_confidence(abs(start_diff), 15, 30),
            ))

    ref_full = _event_bounds(part, "ref_Throttle", threshold=90, above=True)
    cmp_full = _event_bounds(part, "cmp_Throttle", threshold=90, above=True)
    if ref_full and cmp_full:
        full_diff = cmp_full[0] - ref_full[0]
        if abs(full_diff) > 12:
            output.append(_detection(
                section,
                "Earlier full throttle" if full_diff < 0 else "Delayed full throttle",
                impact,
                "direct",
                [f"Full throttle point: {_fmt_m(abs(full_diff))} {'earlier' if full_diff < 0 else 'later'}", f"Exit speed difference: {_fmt_kmh(exit_speed_diff)}"],
                "Delayed full throttle is a high-value direct signal for corner-exit performance.",
                confidence=_confidence(abs(full_diff), 18, 35),
            ))
            if full_diff > 12 and (exit_speed_diff < -4 or min_diff < -4) and impact > 0.04:
                output.append(_detection(
                    section,
                    "Possible traction or instability-like phase heuristic",
                    impact,
                    "heuristic",
                    [
                        f"Full throttle was reached {_fmt_m(full_diff)} later.",
                        f"Minimum speed difference: {_fmt_kmh(min_diff)}",
                        f"Exit speed difference: {_fmt_kmh(exit_speed_diff)}",
                        f"Acceleration estimate difference: {_fmt(part['accel_diff'].mean(), 'm/s^2')}",
                    ],
                    "Possible poor traction, lower confidence, or instability-like behavior inferred from delayed full throttle, weaker exit speed, and time loss. FastF1 cannot confirm wheelspin, oversteer, or steering behavior.",
                    confidence="Low",
                ))

    has_hesitation = _has_throttle_hesitation(part, "cmp_Throttle")
    if has_hesitation:
        output.append(_detection(
            section,
            "Throttle hesitation",
            impact,
            "direct",
            ["Compared lap throttle rises, drops, and rises again within the section.", f"Exit speed difference: {_fmt_kmh(exit_speed_diff)}"],
            "This may indicate lower confidence or possible instability-like behavior, but FastF1 cannot confirm oversteer or wheelspin.",
            confidence="Medium",
        ))
        if exit_speed_diff < -4 and impact > 0.04:
            output.append(_detection(
                section,
                "Possible traction or instability-like phase heuristic",
                impact,
                "heuristic",
                [
                    "Throttle was interrupted after initial application.",
                    f"Exit speed difference: {_fmt_kmh(exit_speed_diff)}",
                    f"Acceleration estimate difference: {_fmt(part['accel_diff'].mean(), 'm/s^2')}",
                ],
                "Possible poor traction or instability-like behavior inferred from throttle interruption, weaker acceleration, and time loss. FastF1 cannot confirm wheelspin, oversteer, or steering behavior.",
                confidence="Low",
            ))

    coasting_distance = _condition_distance(part, (part["cmp_Throttle"] < 8) & (part["cmp_Brake"] < 0.5))
    if coasting_distance > 30:
        output.append(_detection(
            section,
            "Coasting",
            impact,
            "direct",
            [f"Compared lap coasting distance: {_fmt_m(coasting_distance)}", "Coasting means low throttle with brake inactive."],
            "This may be lift-and-coast, traffic, or a cornering phase; context is needed before assigning cause.",
            confidence="Medium",
        ))

    overlap_distance = _condition_distance(part, (part["cmp_Throttle"] > 10) & (part["cmp_Brake"] > 0.5))
    if overlap_distance > 15:
        output.append(_detection(
            section,
            "Brake-throttle overlap",
            impact,
            "direct",
            [f"Compared lap overlap distance: {_fmt_m(overlap_distance)}"],
            "Overlap may reflect driving style, car stabilization, data artifact, or inefficiency depending on context.",
            confidence="Medium",
        ))

    if _early_lift(part):
        output.append(_detection(
            section,
            "Early lift",
            impact,
            "direct",
            ["Compared lap throttle drops before the main braking zone while brake remains inactive."],
            "This can be performance loss, lift-and-coast, traffic, or preparation for a braking zone.",
            confidence="Medium",
        ))

    if min_diff < -4 and exit_speed_diff < -4 and _mean(part, "line_deviation") > 2.5 and impact > 0.04:
        output.append(_detection(
            section,
            "Possible missed apex heuristic",
            impact,
            "heuristic",
            [f"Average X/Y path deviation: {_fmt_m(_mean(part, 'line_deviation'))}", f"Minimum speed difference: {_fmt_kmh(min_diff)}", f"Exit speed difference: {_fmt_kmh(exit_speed_diff)}"],
            "Possible missed apex inferred from path, speed, and delta data. This is approximate, not confirmed steering behavior.",
            confidence="Low",
        ))

    return output


def _gear_drs_line_detections(part: pd.DataFrame, section: Section) -> list[Detection]:
    output: list[Detection] = []
    impact = _local_delta(part)
    gear_diff = round(float(np.nanmedian(part["gear_diff"])))
    if abs(gear_diff) >= 1:
        output.append(_detection(
            section,
            "Different gear choice",
            impact,
            "direct",
            [f"Median gear difference: {gear_diff:+d}", f"Average RPM difference: {_fmt(part['rpm_diff'].mean(), 'rpm')}"],
            "Gear and RPM can support shift-behavior interpretation, but not engine deployment claims.",
            confidence="Medium",
        ))

    shift_distance = _shift_distance_diff(part)
    if shift_distance is not None and abs(shift_distance) > 12:
        output.append(_detection(
            section,
            "Earlier upshift" if shift_distance < 0 else "Later upshift",
            impact,
            "direct",
            [f"First upshift: {_fmt_m(abs(shift_distance))} {'earlier' if shift_distance < 0 else 'later'}"],
            "Shift point comparison is direct from nGear, with RPM as supporting evidence.",
            confidence=_confidence(abs(shift_distance), 18, 35),
        ))

    drs_diff_ratio = float((part["drs_diff"].abs() > 0.5).mean())
    if drs_diff_ratio > 0.15:
        output.append(_detection(
            section,
            "DRS difference",
            impact,
            "direct",
            [f"Different DRS state across {drs_diff_ratio:.0%} of section.", f"Top speed difference: {_fmt_kmh(part['cmp_Speed'].max() - part['ref_Speed'].max())}"],
            "DRS state is available in FastF1 and can explain straight-line speed differences.",
            confidence="High" if drs_diff_ratio > 0.4 else "Medium",
        ))

    top_speed_diff = float(part["cmp_Speed"].max() - part["ref_Speed"].max())
    if abs(top_speed_diff) > 5 and section.section_type in {"Straight", "DRS straight"}:
        output.append(_detection(
            section,
            "Top speed difference",
            impact,
            "direct",
            [f"Top speed difference: {_fmt_kmh(top_speed_diff)}", f"DRS different in {drs_diff_ratio:.0%} of section."],
            "Potential causes include DRS, exit speed, tow, throttle, weather, or context. Power-unit deployment is not confirmed by FastF1.",
            confidence=_confidence(abs(top_speed_diff), 6, 11),
        ))

    line_deviation = _mean(part, "line_deviation")
    if line_deviation > 2:
        output.append(_detection(
            section,
            "Racing line deviation",
            impact,
            "computed",
            [f"Average X/Y deviation: {_fmt_m(line_deviation)}", f"Maximum X/Y deviation: {_fmt_m(float(part['line_deviation'].max()))}"],
            "Racing-line analysis is approximate because FastF1 positions are not track-boundary or steering data.",
            confidence="Low" if line_deviation < 5 else "Medium",
        ))

    return output


def _anomaly_detections(part: pd.DataFrame, section: Section) -> list[Detection]:
    speed_drop = float(part["cmp_Speed"].max() - part["cmp_Speed"].min())
    unusual_brake = (part["cmp_Brake"] > 0.5).mean() > 0.08 and section.section_type in {"Straight", "DRS straight"}
    unusual_lift = (part["cmp_Throttle"] < 20).mean() > 0.25 and section.section_type in {"Straight", "DRS straight"}
    if not (speed_drop > 35 and (unusual_brake or unusual_lift)):
        return []
    return [_detection(
        section,
        "Traffic/anomaly warning",
        _local_delta(part),
        "context",
        [f"Speed drop within section: {_fmt_kmh(speed_drop)}", f"Brake use on straight-like section: {unusual_brake}", f"Low-throttle share on straight-like section: {unusual_lift}"],
        "This section may be traffic or context affected and should not be treated as a pure driving-performance difference.",
        confidence="Medium",
    )]


def _detection(section: Section, difference_type: str, impact: float, evidence_kind: str, evidence: list[str], interpretation: str, confidence: str) -> Detection:
    return Detection(
        section=section.label,
        difference_type=difference_type,
        start_distance=section.start_distance,
        end_distance=section.end_distance,
        time_impact_seconds=impact,
        severity=_severity(impact),
        confidence=confidence,  # type: ignore[arg-type]
        evidence_kind=evidence_kind,  # type: ignore[arg-type]
        what_happened=f"The compared lap {'lost' if impact > 0 else 'gained'} {_fmt_seconds(abs(impact))} in this section.",
        evidence=evidence,
        interpretation=interpretation,
    )


def _slice(aligned: pd.DataFrame, section: Section) -> pd.DataFrame:
    return aligned[(aligned["Distance"] >= section.start_distance) & (aligned["Distance"] <= section.end_distance)]


def _local_delta(part: pd.DataFrame) -> float:
    return float(part["delta_time"].iloc[-1] - part["delta_time"].iloc[0])


def _delta(compared: float | None, reference: float | None) -> float | None:
    if compared is None or reference is None or math.isnan(compared) or math.isnan(reference):
        return None
    return compared - reference


def _severity(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 0.15:
        return "High"
    if magnitude >= 0.07:
        return "Medium"
    if magnitude >= 0.03:
        return "Low"
    return "Info"


def _confidence(value: float, medium: float, high: float) -> str:
    if value >= high:
        return "High"
    if value >= medium:
        return "Medium"
    return "Low"


def _event_bounds(part: pd.DataFrame, channel: str, threshold: float, above: bool) -> tuple[float, float] | None:
    mask = part[channel] >= threshold if above else part[channel] < threshold
    if not bool(mask.any()):
        return None
    event = part.loc[mask, "Distance"]
    return float(event.iloc[0]), float(event.iloc[-1])


def _condition_distance(part: pd.DataFrame, mask: pd.Series) -> float:
    if not bool(mask.any()):
        return 0.0
    distances = part["Distance"].to_numpy()
    step = float(np.nanmedian(np.diff(distances))) if len(distances) > 1 else 0.0
    return float(mask.sum() * step)


def _mean(part: pd.DataFrame, channel: str) -> float:
    return float(pd.to_numeric(part[channel], errors="coerce").mean())


def _mean_at(part: pd.DataFrame, fraction: float, channel: str) -> float:
    start = float(part["Distance"].iloc[0])
    end = float(part["Distance"].iloc[-1])
    center = start + (end - start) * fraction
    width = max(10.0, (end - start) * 0.08)
    window = part[(part["Distance"] >= center - width) & (part["Distance"] <= center + width)]
    return _mean(window if not window.empty else part, channel)


def _has_throttle_hesitation(part: pd.DataFrame, channel: str) -> bool:
    throttle = part[channel].to_numpy()
    if len(throttle) < 8:
        return False
    high = throttle > 35
    drops = throttle < 15
    transitions = np.flatnonzero(high[:-2] & drops[1:-1] & high[2:]) if len(high) > 2 else []
    return len(transitions) > 0


def _early_lift(part: pd.DataFrame) -> bool:
    cmp_brake = _event_bounds(part, "cmp_Brake", 0.5, True)
    ref_brake = _event_bounds(part, "ref_Brake", 0.5, True)
    if not cmp_brake or not ref_brake:
        return False
    pre_cmp = part[(part["Distance"] < cmp_brake[0]) & (part["Distance"] > cmp_brake[0] - 80)]
    pre_ref = part[(part["Distance"] < ref_brake[0]) & (part["Distance"] > ref_brake[0] - 80)]
    return bool((pre_cmp["cmp_Throttle"] < 30).mean() > 0.25 and (pre_ref["ref_Throttle"] > 80).mean() > 0.5)


def _shift_distance_diff(part: pd.DataFrame) -> float | None:
    ref_shift = _first_upshift(part, "ref_nGear")
    cmp_shift = _first_upshift(part, "cmp_nGear")
    if ref_shift is None or cmp_shift is None:
        return None
    return cmp_shift - ref_shift


def _first_upshift(part: pd.DataFrame, channel: str) -> float | None:
    gear = np.rint(part[channel].to_numpy())
    indices = np.flatnonzero(np.diff(gear) > 0)
    if len(indices) == 0:
        return None
    return float(part["Distance"].iloc[indices[0] + 1])


def _primary_reason(part: pd.DataFrame, local_delta: float) -> str:
    speed_loss = float(part["cmp_Speed"].min() - part["ref_Speed"].min())
    exit_loss = _mean_at(part, 0.92, "cmp_Speed") - _mean_at(part, 0.92, "ref_Speed")
    throttle_delay = None
    ref_full = _event_bounds(part, "ref_Throttle", 90, True)
    cmp_full = _event_bounds(part, "cmp_Throttle", 90, True)
    if ref_full and cmp_full:
        throttle_delay = cmp_full[0] - ref_full[0]

    if local_delta > 0:
        if throttle_delay and throttle_delay > 15:
            return "Main suspected reason: delayed full throttle and weaker corner exit."
        if speed_loss < -4:
            return "Main suspected reason: lower minimum speed through the section."
        if exit_loss < -4:
            return "Main suspected reason: lower exit speed carrying onto the next section."
        return "Main suspected reason: combined telemetry differences; inspect supporting detections."
    return "The compared lap improved through this section; supporting detections identify the likely gain source."


def _gain_loss_text(local_delta: float, section: Section) -> str:
    return f"The compared lap {'lost' if local_delta > 0 else 'gained'} {_fmt_seconds(abs(local_delta))} through {section.section_type.lower()}."


def _tyre_context(reference: LapData, compared: LapData) -> list[str]:
    messages: list[str] = []
    ref = reference.metadata
    cmp = compared.metadata
    if ref.compound and cmp.compound:
        messages.append("Same tyre compound." if ref.compound == cmp.compound else f"Different tyre compounds: reference {ref.compound}, compared {cmp.compound}.")
    if ref.tyre_life is not None and cmp.tyre_life is not None:
        diff = cmp.tyre_life - ref.tyre_life
        messages.append(f"Compared lap tyre life is {diff:+.0f} laps versus reference.")
    if ref.fresh_tyre is not None and cmp.fresh_tyre is not None and ref.fresh_tyre != cmp.fresh_tyre:
        messages.append("Fresh tyre context differs between laps.")
    if not messages:
        messages.append("Tyre context unavailable.")
    messages.append("Tyre wear percentage, tyre temperature, and tyre pressure are not available from FastF1.")
    return messages


def _summary(total_delta: float | None, sector_deltas: tuple[float | None, ...], detections: list[Detection], tyre_context: list[str], ref_validity: LapValidity, cmp_validity: LapValidity) -> str:
    if total_delta is None:
        opening = "Lap-time delta is unavailable from metadata."
    else:
        opening = f"The compared lap was {_fmt_seconds(abs(total_delta))} {'slower' if total_delta > 0 else 'faster'} than the reference."
    losses = [d for d in detections if d.time_impact_seconds > 0.035]
    gains = [d for d in detections if d.time_impact_seconds < -0.035]
    biggest_loss = f" Biggest loss: {losses[0].section} ({losses[0].difference_type}, {_fmt_seconds(losses[0].time_impact_seconds)})." if losses else ""
    biggest_gain = f" Biggest gain: {gains[0].section} ({gains[0].difference_type}, {_fmt_seconds(gains[0].time_impact_seconds)})." if gains else ""
    validity = f" Validity: reference {ref_validity.classification}, compared {cmp_validity.classification}."
    sectors = [value for value in sector_deltas if value is not None]
    sector_text = f" Largest sector delta: {_fmt_seconds(max(sectors, key=abs))}." if sectors else ""
    return opening + sector_text + biggest_loss + biggest_gain + validity + " " + " ".join(tyre_context[:2])


def _fmt_seconds(value: float) -> str:
    return f"{value:+.3f} s"


def _fmt_m(value: float) -> str:
    return f"{value:.0f} m"


def _fmt_kmh(value: float) -> str:
    return f"{value:+.1f} km/h"


def _fmt(value: float, unit: str) -> str:
    return f"{value:+.1f} {unit}"
