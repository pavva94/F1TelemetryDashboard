"""Season-wide normalization and transparent F1 performance models."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from math import sqrt
from statistics import median
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .fastf1_loader import list_events
from .season_metadata import circuit_characteristics, published_upgrades


MOMENTUM_WEIGHTS = {
    "racePace": 0.30,
    "qualifying": 0.20,
    "points": 0.20,
    "development": 0.15,
    "reliability": 0.10,
    "operations": 0.05,
}

POINTS_BY_POSITION = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}
MECHANICAL_TERMS = ("engine", "gearbox", "hydraulic", "electrical", "power unit", "brakes", "mechanical", "oil", "water", "overheating")
INCIDENT_TERMS = ("accident", "collision", "spun", "damage")


@dataclass(frozen=True)
class Quality:
    sample_size: int
    excluded: int
    confidence: str
    kind: str = "observed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "sampleSize": self.sample_size,
            "excluded": self.excluded,
            "confidence": self.confidence,
            "kind": self.kind,
        }


def percentage_deficit(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference <= 0:
        return None
    return (float(value) / float(reference) - 1.0) * 100.0


def rolling_median(values: list[float | None], window: int) -> list[float | None]:
    if window <= 1:
        return list(values)
    output: list[float | None] = []
    for index in range(len(values)):
        clean = [float(value) for value in values[max(0, index - window + 1) : index + 1] if value is not None]
        output.append(float(median(clean)) if clean else None)
    return output


def reject_outliers(values: Iterable[float], threshold: float = 3.5) -> tuple[list[float], int]:
    clean = [float(value) for value in values if value is not None and np.isfinite(value)]
    if len(clean) < 4:
        return clean, 0
    centre = float(median(clean))
    mad = float(median(abs(value - centre) for value in clean))
    if mad == 0:
        kept = [value for value in clean if value == centre]
    else:
        kept = [value for value in clean if abs(0.6745 * (value - centre) / mad) <= threshold]
    return kept, len(clean) - len(kept)


def clean_race_laps(laps: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if laps is None or laps.empty or "LapTime" not in laps.columns:
        return pd.DataFrame(), {"missingTime": 0}
    clean = laps.dropna(subset=["LapTime"]).copy()
    counts: dict[str, int] = {}
    rules: list[tuple[str, Callable[[pd.DataFrame], pd.Series]]] = [
        ("deleted", lambda frame: frame["Deleted"] == True if "Deleted" in frame else pd.Series(False, index=frame.index)),  # noqa: E712
        ("inaccurate", lambda frame: frame["IsAccurate"] == False if "IsAccurate" in frame else pd.Series(False, index=frame.index)),  # noqa: E712
        ("pit", lambda frame: (frame["PitInTime"].notna() if "PitInTime" in frame else False) | (frame["PitOutTime"].notna() if "PitOutTime" in frame else False)),
        ("neutralised", lambda frame: frame["TrackStatus"].fillna("1").astype(str).map(lambda value: value not in {"1", "2"}) if "TrackStatus" in frame else pd.Series(False, index=frame.index)),
    ]
    for name, rule in rules:
        mask = rule(clean)
        if isinstance(mask, bool):
            continue
        counts[name] = int(mask.sum())
        clean = clean[~mask]
    seconds = clean["LapTime"].map(_seconds)
    valid, excluded = reject_outliers([value for value in seconds if value is not None])
    if excluded:
        low, high = min(valid), max(valid)
        clean = clean[(seconds >= low) & (seconds <= high)]
    counts["outlier"] = excluded
    return clean, counts


def classify_reliability(status: str | None) -> str:
    normalized = (status or "").lower()
    if "did not start" in normalized or normalized == "dns":
        return "dns"
    if "disqual" in normalized or normalized == "dsq":
        return "dsq"
    if any(term in normalized for term in MECHANICAL_TERMS):
        return "mechanical"
    if any(term in normalized for term in INCIDENT_TERMS):
        return "incident"
    if normalized.startswith("+") or normalized in {"finished", "lapping"}:
        return "classified"
    return "other"


def confidence_for(sample_size: int, coverage: float = 1.0) -> str:
    score = sample_size * max(0.0, min(1.0, coverage))
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def development_regression(points: list[dict[str, Any]], metric: str = "deficit") -> dict[str, Any]:
    usable = [(float(point["round"]), float(point[metric])) for point in points if point.get(metric) is not None]
    if len(usable) < 3:
        return {"rate": None, "intercept": None, "r2": None, "confidence": "low", "events": len(usable)}
    x = np.array([item[0] for item in usable], dtype=float)
    y = np.array([item[1] for item in usable], dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    prediction = intercept + slope * x
    residual = float(np.sum((y - prediction) ** 2))
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - residual / total if total else 1.0
    standard_error = sqrt(residual / max(1, len(x) - 2)) / sqrt(float(np.sum((x - x.mean()) ** 2))) if len(x) > 2 and np.sum((x - x.mean()) ** 2) else 0.0
    return {
        "rate": float(slope),
        "intercept": float(intercept),
        "r2": float(r2),
        "confidenceInterval": [float(slope - 1.96 * standard_error), float(slope + 1.96 * standard_error)],
        "confidence": confidence_for(len(usable), max(0.2, r2)),
        "events": len(usable),
    }


def early_recent(points: list[dict[str, Any]], metric: str = "deficit", window: int = 3) -> dict[str, Any]:
    usable = [float(point[metric]) for point in points if point.get(metric) is not None]
    if len(usable) < window * 2:
        return {"early": None, "recent": None, "change": None, "events": len(usable), "confidence": "low"}
    early = float(median(usable[:window]))
    recent = float(median(usable[-window:]))
    return {"early": early, "recent": recent, "change": recent - early, "events": window * 2, "confidence": confidence_for(window * 2)}


def detect_change_point(points: list[dict[str, Any]], metric: str = "deficit") -> dict[str, Any] | None:
    usable = [point for point in points if point.get(metric) is not None]
    if len(usable) < 6:
        return None
    best: dict[str, Any] | None = None
    spread = float(np.std([point[metric] for point in usable])) or 1e-9
    for split in range(3, len(usable) - 2):
        before = float(median(float(point[metric]) for point in usable[:split]))
        after = float(median(float(point[metric]) for point in usable[split:]))
        magnitude = after - before
        score = abs(magnitude) / spread * min(split, len(usable) - split)
        if best is None or score > best["score"]:
            best = {
                "round": usable[split]["round"],
                "before": before,
                "after": after,
                "magnitude": magnitude,
                "direction": "regression" if magnitude > 0 else "improvement",
                "score": score,
            }
    if not best or best["score"] < 1.5:
        return None
    best["confidence"] = confidence_for(len(usable), min(1.0, best.pop("score") / 6))
    best["metric"] = metric
    return best


def expected_points(performance_rank: int | None, reliability_probability: float = 1.0) -> float:
    if performance_rank is None:
        return 0.0
    return float(POINTS_BY_POSITION.get(int(performance_rank), 0) * max(0.0, min(1.0, reliability_probability)))


def points_conversion(actual: float, expected: float) -> float | None:
    if expected <= 0:
        return None
    return float(actual) / float(expected)


def fit_degradation(laps: pd.DataFrame) -> dict[str, Any]:
    if laps is None or laps.empty or "TyreLife" not in laps or "LapTime" not in laps:
        return {"rate": None, "confidence": "low", "laps": 0, "kind": "estimated"}
    clean, _ = clean_race_laps(laps)
    usable = clean.dropna(subset=["TyreLife", "LapTime"]).copy()
    if len(usable) < 5:
        return {"rate": None, "confidence": "low", "laps": len(usable), "kind": "estimated"}
    y = np.array([_seconds(value) for value in usable["LapTime"]], dtype=float)
    tyre = usable["TyreLife"].astype(float).to_numpy()
    lap_number = usable["LapNumber"].astype(float).to_numpy() if "LapNumber" in usable else np.arange(len(usable), dtype=float)
    matrix = np.column_stack([np.ones(len(usable)), tyre, lap_number])
    coefficients, _, _, _ = np.linalg.lstsq(matrix, y, rcond=None)
    residuals = y - matrix @ coefficients
    return {
        "rate": float(coefficients[1]),
        "fuelProxy": float(coefficients[2]),
        "residualMad": float(median(abs(value - median(residuals)) for value in residuals)),
        "confidence": confidence_for(len(usable)),
        "laps": len(usable),
        "kind": "adjusted estimate",
    }


def prediction_snapshot(team_series: dict[str, list[dict[str, Any]]], target_round: int) -> dict[str, Any]:
    """Predict using strictly pre-target observations to prevent data leakage."""
    predictions = []
    for team, points in team_series.items():
        history = [point for point in points if point["round"] < target_round and point.get("deficit") is not None]
        if not history:
            continue
        recent = history[-3:]
        model = development_regression(history)
        estimate = float(median(point["deficit"] for point in recent))
        if model["rate"] is not None:
            estimate += float(model["rate"])
        uncertainty = float(np.std([point["deficit"] for point in recent])) if len(recent) > 1 else 0.35
        predictions.append(
            {
                "team": team,
                "deficit": max(0.0, estimate),
                "range": [max(0.0, estimate - uncertainty), estimate + uncertainty],
                "confidence": confidence_for(len(history)),
                "roundsUsed": [point["round"] for point in history],
                "kind": "prediction",
            }
        )
    predictions.sort(key=lambda item: item["deficit"])
    for rank, item in enumerate(predictions, 1):
        item["rank"] = rank
    return {"targetRound": target_round, "teams": predictions, "leakageGuard": f"round < {target_round}"}


def backtest_predictions(team_series: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rounds = sorted({point["round"] for points in team_series.values() for point in points})
    cases: list[dict[str, Any]] = []
    for target_round in rounds:
        if len([round_number for round_number in rounds if round_number < target_round]) < 3:
            continue
        snapshot = prediction_snapshot(team_series, target_round)
        actual = sorted(
            [
                {"team": team, "deficit": next(point["deficit"] for point in points if point["round"] == target_round)}
                for team, points in team_series.items()
                if any(point["round"] == target_round for point in points)
            ],
            key=lambda row: row["deficit"],
        )
        actual_ranks = {row["team"]: rank for rank, row in enumerate(actual, 1)}
        actual_deficits = {row["team"]: row["deficit"] for row in actual}
        for predicted in snapshot["teams"]:
            if predicted["team"] not in actual_ranks:
                continue
            cases.append(
                {
                    "round": target_round,
                    "team": predicted["team"],
                    "predictedRank": predicted["rank"],
                    "actualRank": actual_ranks[predicted["team"]],
                    "rankError": abs(predicted["rank"] - actual_ranks[predicted["team"]]),
                    "predictedDeficit": predicted["deficit"],
                    "actualDeficit": actual_deficits[predicted["team"]],
                    "roundsUsed": predicted["roundsUsed"],
                    "confidence": predicted["confidence"],
                }
            )
    return {
        "cases": cases,
        "meanAbsoluteRankError": float(np.mean([case["rankError"] for case in cases])) if cases else None,
        "meanAbsoluteDeficitError": float(np.mean([abs(case["predictedDeficit"] - case["actualDeficit"]) for case in cases])) if cases else None,
        "leakageGuard": "Every training round is strictly less than its target round.",
    }


def estimate_upgrade_impact(
    points: list[dict[str, Any]], upgrade_round: int, metric: str = "deficit", window: int = 3
) -> dict[str, Any]:
    before = [float(point[metric]) for point in points if upgrade_round - window <= point["round"] < upgrade_round and point.get(metric) is not None]
    after = [float(point[metric]) for point in points if upgrade_round <= point["round"] < upgrade_round + window and point.get(metric) is not None]
    if len(before) < 2 or len(after) < 2:
        return {"change": None, "before": None, "after": None, "confidence": "low", "events": len(before) + len(after), "kind": "association"}
    before_value, after_value = float(median(before)), float(median(after))
    return {
        "change": after_value - before_value,
        "before": before_value,
        "after": after_value,
        "confidence": confidence_for(len(before) + len(after)),
        "events": len(before) + len(after),
        "kind": "association, not causation",
    }


def build_season_analysis(
    year: int,
    cache_dir: str | None,
    start_round: int | None = None,
    end_round: int | None = None,
    include_sprints: bool = True,
    session_loader: Callable[[int, str, str, str | None], Any] | None = None,
) -> dict[str, Any]:
    from .fastf1_loader import load_fastf1_session

    loader = session_loader or _season_session_loader
    schedule = list_events(year)
    if not schedule:
        return _empty_payload(year, "No scheduled events are available for this season.")
    first = start_round or 1
    last = end_round or max(event["round"] for event in schedule)
    selected = [event for event in schedule if first <= event["round"] <= last]
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []

    for event in selected:
        event_result = {**event, "status": "unavailable", "weather": None, "winner": None, "pole": None}
        try:
            race = loader(year, event["name"], "Race", cache_dir)
            race_rows, event_extra = _normalise_race(event, race)
            normalized.extend(race_rows)
            event_result.update(event_extra)
            event_result["status"] = "completed"
            _attach_race_models(normalized, event["round"], race)
        except Exception as exc:
            errors.append({"round": event["round"], "event": event["name"], "session": "Race", "message": str(exc)})
            event_rows.append(event_result)
            continue
        try:
            qualifying = loader(year, event["name"], "Qualifying", cache_dir)
            _attach_qualifying(normalized, event["round"], qualifying)
            event_result["pole"] = _pole_sitter(qualifying)
        except Exception as exc:
            errors.append({"round": event["round"], "event": event["name"], "session": "Qualifying", "message": str(exc)})
        if include_sprints and any("sprint" in item["name"].lower() and "qual" not in item["name"].lower() and "shootout" not in item["name"].lower() for item in event.get("sessions", [])):
            try:
                sprint = loader(year, event["name"], "Sprint", cache_dir)
                _attach_sprint_points(normalized, event["round"], sprint)
                event_result["sprint"] = True
            except Exception as exc:
                errors.append({"round": event["round"], "event": event["name"], "session": "Sprint", "message": str(exc)})
        event_rows.append(event_result)

    completed = [event for event in event_rows if event["status"] == "completed"]
    if not completed:
        payload = _empty_payload(year, "No completed race timing data could be loaded.")
        payload["events"] = event_rows
        payload["errors"] = errors
        return payload

    payload = aggregate_records(year, normalized, event_rows, errors)
    payload["meta"]["isComplete"] = bool(schedule) and max(payload["meta"]["completedRounds"]) >= max(event["round"] for event in schedule)
    payload["filters"] = {"startRound": first, "endRound": last, "includeSprints": include_sprints}
    return payload


@lru_cache(maxsize=24)
def cached_season_analysis(
    year: int,
    cache_dir: str | None,
    start_round: int | None,
    end_round: int | None,
    include_sprints: bool,
) -> dict[str, Any]:
    """Memoize normalized season payloads within the web process."""
    return build_season_analysis(year, cache_dir, start_round, end_round, include_sprints)


def aggregate_records(year: int, records: list[dict[str, Any]], events: list[dict[str, Any]], errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    completed_rounds = sorted({record["round"] for record in records})
    event_lookup = {event["round"]: event for event in events}
    drivers = sorted({record["driver"] for record in records})
    teams = sorted({record["team"] for record in records if record.get("team")})
    championship = _championship(records, drivers, teams, completed_rounds)
    performance = _performance(records, drivers, teams, completed_rounds)
    reliability = _reliability(records, drivers, teams)
    development = _development(performance["teamQualifying"], performance["teamRacePace"])
    conversion = _conversion(records, reliability)
    tyres = _tyres(records)
    operations = _operations(records)
    momentum = _momentum(teams, records, performance, reliability, operations)
    track = _track_analysis(performance["teamRacePace"], event_lookup)
    upgrades = published_upgrades(year)
    changes = [
        {"team": team, **change}
        for team, points in performance["teamCombined"].items()
        if (change := detect_change_point(points))
    ]
    next_round = max(completed_rounds) + 1
    next_event = next((event for event in events if event["round"] == next_round), None)
    prediction = prediction_snapshot(performance["teamCombined"], next_round) if next_event else None
    if prediction and next_event:
        prediction["event"] = next_event["name"]
        prediction["similarCircuits"] = _similar_circuits(next_event, events)
    backtest = backtest_predictions(performance["teamCombined"])
    upgrade_impacts = []
    for upgrade in upgrades:
        team_points = performance["teamCombined"].get(upgrade.get("team"), [])
        impact = estimate_upgrade_impact(team_points, int(upgrade.get("round") or 0))
        upgrade_impacts.append({**upgrade, "impact": impact})
    insights = _insights(championship, development, reliability, conversion, changes, momentum)
    return {
        "meta": {
            "season": year,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "completedRounds": completed_rounds,
            "availableRound": max(completed_rounds),
            "isComplete": bool(events) and max(completed_rounds) >= max(event["round"] for event in events),
            "partial": bool(errors),
            "dataFreshness": "FastF1 cache plus live Ergast/F1 timing sources at request time",
        },
        "events": events,
        "records": records,
        "entities": {"drivers": drivers, "teams": teams},
        "championship": championship,
        "performance": performance,
        "development": development,
        "reliability": reliability,
        "operations": operations,
        "tyres": tyres,
        "conversion": conversion,
        "momentum": momentum,
        "trackAnalysis": track,
        "upgrades": upgrades,
        "upgradeImpacts": upgrade_impacts,
        "changePoints": changes,
        "prediction": prediction,
        "backtest": backtest,
        "insights": insights,
        "methodology": METHODOLOGY,
        "errors": errors or [],
    }


def _season_session_loader(year: int, event: str, session_name: str, cache_dir: str | None) -> Any:
    import fastf1
    from pathlib import Path

    if cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(cache_dir)
    session = fastf1.get_session(year, event, session_name)
    session.load(laps=True, telemetry=False, weather=True, messages=False)
    return session


def _normalise_race(event: dict[str, Any], session: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = getattr(session, "results", pd.DataFrame())
    if results is None or results.empty:
        raise ValueError("Race results are not available.")
    output = []
    for _, row in results.iterrows():
        driver = _text(row, "Abbreviation") or _text(row, "DriverId")
        if not driver:
            continue
        status = _text(row, "Status")
        output.append(
            {
                "round": event["round"],
                "event": event["name"],
                "date": event.get("date"),
                "driver": driver,
                "team": _text(row, "TeamName"),
                "grid": _integer(row, "GridPosition"),
                "finish": _integer(row, "Position"),
                "status": status,
                "reliability": classify_reliability(status),
                "points": _number(row, "Points") or 0.0,
                "sprintPoints": 0.0,
                "qualifyingTime": None,
                "qualifyingDeficit": None,
                "racePace": None,
                "racePaceDeficit": None,
                "adjustedRacePace": None,
                "adjustedRacePaceDeficit": None,
                "cleanLaps": 0,
                "excludedLaps": 0,
                "stints": [],
                "pitStops": [],
                "degradation": None,
                "quality": Quality(0, 0, "low").as_dict(),
            }
        )
    winner = min(output, key=lambda item: item["finish"] or 999) if output else None
    weather = _session_weather(session)
    return output, {"winner": winner["driver"] if winner else None, "weather": weather, "date": event.get("date")}


def _attach_qualifying(records: list[dict[str, Any]], round_number: int, session: Any) -> None:
    laps = getattr(session, "laps", pd.DataFrame())
    if laps is None or laps.empty:
        return
    times: dict[str, float] = {}
    for driver, group in laps.groupby("Driver"):
        valid = group.dropna(subset=["LapTime"]).copy()
        if "Deleted" in valid:
            valid = valid[valid["Deleted"] != True]  # noqa: E712
        if not valid.empty:
            times[str(driver)] = min(_seconds(value) for value in valid["LapTime"] if _seconds(value) is not None)
    reference = min(times.values()) if times else None
    for record in records:
        if record["round"] == round_number and record["driver"] in times:
            record["qualifyingTime"] = times[record["driver"]]
            record["qualifyingDeficit"] = percentage_deficit(times[record["driver"]], reference)


def _attach_race_models(records: list[dict[str, Any]], round_number: int, session: Any) -> None:
    laps = getattr(session, "laps", pd.DataFrame())
    if laps is None or laps.empty:
        return
    pace: dict[str, float] = {}
    models: dict[str, dict[str, Any]] = {}
    grouped_clean: dict[str, pd.DataFrame] = {}
    for driver, group in laps.groupby("Driver"):
        clean, exclusions = clean_race_laps(group)
        if clean.empty:
            continue
        values, outliers = reject_outliers([_seconds(value) for value in clean["LapTime"] if _seconds(value) is not None])
        if not values:
            continue
        pace[str(driver)] = float(median(values))
        grouped_clean[str(driver)] = clean
        model = fit_degradation(clean)
        model["excluded"] = sum(exclusions.values()) + outliers
        models[str(driver)] = model
    reference = min(pace.values()) if pace else None
    adjusted_values: dict[str, float] = {}
    for driver, value in pace.items():
        model = models[driver]
        fuel_proxy = model.get("fuelProxy") or 0.0
        tyre_rate = model.get("rate") or 0.0
        group = grouped_clean[driver]
        median_lap = float(group["LapNumber"].median()) if "LapNumber" in group else 0.0
        median_tyre = float(group["TyreLife"].median()) if "TyreLife" in group else 0.0
        adjusted_values[driver] = value - fuel_proxy * median_lap - tyre_rate * median_tyre
    adjusted_reference = min(adjusted_values.values()) if adjusted_values else None
    for record in records:
        if record["round"] != round_number or record["driver"] not in pace:
            continue
        driver = record["driver"]
        group = grouped_clean[driver]
        record["racePace"] = pace[driver]
        record["racePaceDeficit"] = percentage_deficit(pace[driver], reference)
        record["adjustedRacePace"] = adjusted_values[driver]
        record["adjustedRacePaceDeficit"] = percentage_deficit(adjusted_values[driver], adjusted_reference)
        record["cleanLaps"] = len(group)
        record["excludedLaps"] = models[driver]["excluded"]
        record["degradation"] = models[driver]
        record["stints"] = _stints(group)
        record["pitStops"] = _pit_stops(group)
        record["quality"] = Quality(len(group), models[driver]["excluded"], confidence_for(len(group)), "observed + adjusted estimate").as_dict()


def _attach_sprint_points(records: list[dict[str, Any]], round_number: int, session: Any) -> None:
    results = getattr(session, "results", pd.DataFrame())
    if results is None or results.empty:
        return
    points = {_text(row, "Abbreviation"): _number(row, "Points") or 0.0 for _, row in results.iterrows()}
    for record in records:
        if record["round"] == round_number:
            record["sprintPoints"] = points.get(record["driver"], 0.0)


def _championship(records: list[dict[str, Any]], drivers: list[str], teams: list[str], rounds: list[int]) -> dict[str, Any]:
    driver_series = _cumulative_series(records, drivers, rounds, lambda row: row["driver"])
    team_series = _cumulative_series(records, teams, rounds, lambda row: row["team"])
    return {
        "drivers": driver_series,
        "constructors": team_series,
        "driverPositions": _rank_series(driver_series, rounds),
        "constructorPositions": _rank_series(team_series, rounds),
    }


def _cumulative_series(records: list[dict[str, Any]], entities: list[str], rounds: list[int], key: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    totals = {entity: 0.0 for entity in entities}
    series = {entity: [] for entity in entities}
    for round_number in rounds:
        for record in records:
            if record["round"] == round_number and key(record) in totals:
                totals[key(record)] += float(record["points"]) + float(record.get("sprintPoints", 0))
        for entity in entities:
            series[entity].append({"round": round_number, "value": totals[entity]})
    return [{"entity": entity, "points": points, "total": totals[entity]} for entity, points in series.items()]


def _rank_series(series: list[dict[str, Any]], rounds: list[int]) -> list[dict[str, Any]]:
    output = {item["entity"]: [] for item in series}
    for index, round_number in enumerate(rounds):
        order = sorted(series, key=lambda item: (-item["points"][index]["value"], item["entity"]))
        for rank, item in enumerate(order, 1):
            output[item["entity"]].append({"round": round_number, "rank": rank, "points": item["points"][index]["value"]})
    return [{"entity": entity, "points": points} for entity, points in output.items()]


def _performance(records: list[dict[str, Any]], drivers: list[str], teams: list[str], rounds: list[int]) -> dict[str, Any]:
    driver_q = _metric_series(records, drivers, "driver", "qualifyingDeficit")
    driver_r = _metric_series(records, drivers, "driver", "racePaceDeficit")
    driver_a = _metric_series(records, drivers, "driver", "adjustedRacePaceDeficit")
    team_q = _metric_series(records, teams, "team", "qualifyingDeficit", aggregate="best")
    team_r = _metric_series(records, teams, "team", "racePaceDeficit")
    team_a = _metric_series(records, teams, "team", "adjustedRacePaceDeficit")
    combined: dict[str, list[dict[str, Any]]] = {}
    for team in teams:
        q_by_round = {point["round"]: point["deficit"] for point in team_q.get(team, [])}
        r_by_round = {point["round"]: point["deficit"] for point in team_a.get(team, [])}
        combined[team] = [
            {"round": round_number, "deficit": float(median([value for value in (q_by_round.get(round_number), r_by_round.get(round_number)) if value is not None]))}
            for round_number in rounds
            if q_by_round.get(round_number) is not None or r_by_round.get(round_number) is not None
        ]
    return {
        "driverQualifying": driver_q,
        "driverRacePace": driver_r,
        "driverAdjustedRacePace": driver_a,
        "teamQualifying": team_q,
        "teamRacePace": team_r,
        "teamAdjustedRacePace": team_a,
        "teamCombined": combined,
    }


def _metric_series(records: list[dict[str, Any]], entities: list[str], entity_key: str, metric: str, aggregate: str = "median") -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        points = []
        for round_number in sorted({row["round"] for row in records}):
            values = [row[metric] for row in records if row[entity_key] == entity and row["round"] == round_number and row.get(metric) is not None]
            if not values:
                continue
            value = min(values) if aggregate == "best" else float(median(values))
            rows = [row for row in records if row[entity_key] == entity and row["round"] == round_number]
            points.append(
                {
                    "round": round_number,
                    "deficit": float(value),
                    "sampleSize": sum(row.get("cleanLaps", 0) for row in rows) or len(values),
                    "confidence": confidence_for(sum(row.get("cleanLaps", 0) for row in rows) or len(values)),
                }
            )
        output[entity] = points
    return output


def _reliability(records: list[dict[str, Any]], drivers: list[str], teams: list[str]) -> dict[str, Any]:
    return {
        "drivers": [_reliability_row(entity, [row for row in records if row["driver"] == entity]) for entity in drivers],
        "teams": [_reliability_row(entity, [row for row in records if row["team"] == entity]) for entity in teams],
        "timeline": [{"round": row["round"], "event": row["event"], "driver": row["driver"], "team": row["team"], "state": row["reliability"], "status": row["status"]} for row in records],
    }


def _reliability_row(entity: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    starts = len([row for row in rows if row["reliability"] != "dns"])
    classified = len([row for row in rows if row["reliability"] == "classified"])
    return {
        "entity": entity,
        "starts": starts,
        "classified": classified,
        "mechanical": sum(row["reliability"] == "mechanical" for row in rows),
        "incidents": sum(row["reliability"] == "incident" for row in rows),
        "dns": sum(row["reliability"] == "dns" for row in rows),
        "dsq": sum(row["reliability"] == "dsq" for row in rows),
        "percentage": classified / starts * 100 if starts else None,
        "confidence": confidence_for(starts),
    }


def _development(team_q: dict[str, list[dict[str, Any]]], team_r: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    output = []
    for team in sorted(team_q):
        output.append(
            {
                "team": team,
                "qualifying": development_regression(team_q[team]),
                "racePace": development_regression(team_r.get(team, [])),
                "qualifyingEarlyRecent": early_recent(team_q[team]),
                "racePaceEarlyRecent": early_recent(team_r.get(team, [])),
            }
        )
    return output


def _conversion(records: list[dict[str, Any]], reliability: dict[str, Any]) -> dict[str, Any]:
    team_rel = {row["entity"]: (row["percentage"] or 0) / 100 for row in reliability["teams"]}
    rows = []
    for round_number in sorted({row["round"] for row in records}):
        event_rows = [row for row in records if row["round"] == round_number]
        ranked = sorted(event_rows, key=lambda row: ((row.get("qualifyingDeficit") if row.get("qualifyingDeficit") is not None else 99) + (row.get("racePaceDeficit") if row.get("racePaceDeficit") is not None else 99)))
        for rank, row in enumerate(ranked, 1):
            expected = expected_points(rank, team_rel.get(row["team"], 1.0))
            actual = float(row["points"]) + float(row.get("sprintPoints", 0))
            rows.append(
                {
                    "round": round_number,
                    "event": row["event"],
                    "driver": row["driver"],
                    "team": row["team"],
                    "expected": expected,
                    "actual": actual,
                    "difference": actual - expected,
                    "conversion": points_conversion(actual, expected),
                    "performanceRank": rank,
                    "confidence": "medium" if row.get("racePaceDeficit") is not None and row.get("qualifyingDeficit") is not None else "low",
                    "kind": "model estimate",
                }
            )
    return {"events": rows, "teams": _sum_conversion(rows, "team"), "drivers": _sum_conversion(rows, "driver")}


def _sum_conversion(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    output = []
    for entity in sorted({row[key] for row in rows}):
        selected = [row for row in rows if row[key] == entity]
        expected = sum(row["expected"] for row in selected)
        actual = sum(row["actual"] for row in selected)
        output.append({"entity": entity, "expected": expected, "actual": actual, "difference": actual - expected, "conversion": points_conversion(actual, expected), "events": len(selected)})
    return sorted(output, key=lambda row: row["difference"], reverse=True)


def _tyres(records: list[dict[str, Any]]) -> dict[str, Any]:
    strategies = []
    degradation = []
    for row in records:
        stints = row.get("stints", [])
        if stints:
            strategies.append({"round": row["round"], "event": row["event"], "driver": row["driver"], "team": row["team"], "strategy": "-".join(str(stint.get("compound") or "?")[0] for stint in stints), "stints": stints})
        degradation_model = row.get("degradation") or {}
        if degradation_model.get("rate") is not None:
            degradation.append({"round": row["round"], "event": row["event"], "driver": row["driver"], "team": row["team"], **degradation_model})
    return {"strategies": strategies, "degradation": degradation}


def _operations(records: list[dict[str, Any]]) -> dict[str, Any]:
    stops = []
    for row in records:
        for stop in row.get("pitStops", []):
            stops.append({"round": row["round"], "event": row["event"], "driver": row["driver"], "team": row["team"], **stop})
    teams = []
    for team in sorted({row["team"] for row in records}):
        durations = [stop["duration"] for stop in stops if stop["team"] == team and stop.get("duration") is not None]
        teams.append({"team": team, "stops": len(durations), "medianPitLane": float(median(durations)) if durations else None, "variation": float(np.std(durations)) if len(durations) > 1 else None, "confidence": confidence_for(len(durations))})
    return {"pitStops": stops, "teams": teams, "strategyNote": "Strategy execution is shown through observable pit timing and points conversion; causal undercut/overcut claims are withheld without reliable traffic data."}


def _momentum(teams: list[str], records: list[dict[str, Any]], performance: dict[str, Any], reliability: dict[str, Any], operations: dict[str, Any]) -> list[dict[str, Any]]:
    rel = {row["entity"]: (row["percentage"] or 0) / 100 for row in reliability["teams"]}
    pit = {row["team"]: row["medianPitLane"] for row in operations["teams"]}
    output = []
    for team in teams:
        recent_records = sorted([row for row in records if row["team"] == team], key=lambda row: row["round"])[-6:]
        recent_rounds = sorted({row["round"] for row in recent_records})[-3:]
        points = sum(row["points"] + row.get("sprintPoints", 0) for row in recent_records if row["round"] in recent_rounds)
        q_values = [point["deficit"] for point in performance["teamQualifying"].get(team, []) if point["round"] in recent_rounds]
        r_values = [point["deficit"] for point in performance["teamRacePace"].get(team, []) if point["round"] in recent_rounds]
        dev = development_regression(performance["teamCombined"].get(team, []))
        components = {
            "racePace": 1 / (1 + (median(r_values) if r_values else 5)),
            "qualifying": 1 / (1 + (median(q_values) if q_values else 5)),
            "points": min(1.0, points / 75),
            "development": max(0.0, min(1.0, 0.5 - (dev["rate"] or 0))),
            "reliability": rel.get(team, 0),
            "operations": 1 / (1 + max(0.0, (pit.get(team) or 30) - 20) / 10),
        }
        score = sum(components[key] * weight for key, weight in MOMENTUM_WEIGHTS.items()) * 100
        output.append({"team": team, "score": score, "components": components, "weights": MOMENTUM_WEIGHTS, "rounds": recent_rounds, "confidence": confidence_for(len(recent_rounds))})
    return sorted(output, key=lambda row: row["score"], reverse=True)


def _track_analysis(team_series: dict[str, list[dict[str, Any]]], events: dict[int, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for team, points in team_series.items():
        season_values = [point["deficit"] for point in points]
        baseline = float(median(season_values)) if season_values else None
        by_cluster: dict[str, list[float]] = defaultdict(list)
        for point in points:
            metadata = circuit_characteristics(events.get(point["round"], {}).get("name", ""))
            if metadata:
                by_cluster[metadata["cluster"]].append(point["deficit"])
        for cluster, values in by_cluster.items():
            rows.append({"team": team, "cluster": cluster, "relativeStrength": (float(median(values)) - baseline) if baseline is not None else None, "events": len(values), "confidence": confidence_for(len(values)), "kind": "categorical association"})
    teams_analyzed = sorted(team_series)
    return {
        "strengths": rows,
        "teamsAnalyzed": teams_analyzed,
        "teamCount": len(teams_analyzed),
        "metadataCoverage": len([event for event in events.values() if circuit_characteristics(event.get("name", ""))]),
        "metadataKind": "maintained qualitative categories",
    }


def _similar_circuits(target: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metadata = circuit_characteristics(target["name"])
    if not metadata:
        return []
    output = []
    for event in events:
        other = circuit_characteristics(event["name"])
        if event["name"] == target["name"] or not other:
            continue
        shared = [key for key in metadata if other.get(key) == metadata[key]]
        if shared:
            output.append({"event": event["name"], "round": event["round"], "shared": shared, "similarity": len(shared) / len(metadata)})
    return sorted(output, key=lambda row: row["similarity"], reverse=True)[:4]


def _insights(championship: dict[str, Any], development: list[dict[str, Any]], reliability: dict[str, Any], conversion: dict[str, Any], changes: list[dict[str, Any]], momentum: list[dict[str, Any]]) -> list[dict[str, Any]]:
    insights = []
    if championship["drivers"]:
        leader = max(championship["drivers"], key=lambda row: row["total"])
        insights.append({"type": "championship", "statement": f"{leader['entity']} leads the selected championship range with {leader['total']:.0f} points.", "metric": leader["total"], "sampleSize": len(leader["points"]), "confidence": "high", "target": "championship"})
    improving = [row for row in development if row["qualifying"]["rate"] is not None]
    if improving:
        best = min(improving, key=lambda row: row["qualifying"]["rate"])
        insights.append({"type": "development", "statement": f"{best['team']} has the strongest qualifying-deficit trend at {best['qualifying']['rate']:+.3f}% per round.", "metric": best["qualifying"]["rate"], "sampleSize": best["qualifying"]["events"], "confidence": best["qualifying"]["confidence"], "target": "development"})
    reliable = [row for row in reliability["teams"] if row["percentage"] is not None]
    if reliable:
        best = max(reliable, key=lambda row: row["percentage"])
        insights.append({"type": "reliability", "statement": f"{best['entity']} has classified {best['percentage']:.0f}% of its starts in the selected range.", "metric": best["percentage"], "sampleSize": best["starts"], "confidence": best["confidence"], "target": "reliability"})
    if conversion["teams"]:
        best = max(conversion["teams"], key=lambda row: row["difference"])
        insights.append({"type": "conversion", "statement": f"{best['entity']} is {best['difference']:+.1f} points versus the transparent performance-rank expectation model.", "metric": best["difference"], "sampleSize": best["events"], "confidence": "medium", "target": "teams"})
    for change in changes[:2]:
        insights.append({"type": "change", "statement": f"{change['team']} shows a {change['direction']} change near round {change['round']} ({change['magnitude']:+.3f}%).", "metric": change["magnitude"], "sampleSize": 6, "confidence": change["confidence"], "target": "development"})
    if momentum:
        best = momentum[0]
        insights.append({"type": "momentum", "statement": f"{best['team']} has the strongest current-form index ({best['score']:.0f}/100).", "metric": best["score"], "sampleSize": len(best["rounds"]), "confidence": best["confidence"], "target": "predictions"})
    return insights


def _stints(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if "Stint" not in laps:
        return []
    output = []
    for stint, group in laps.dropna(subset=["Stint"]).groupby("Stint"):
        output.append({"stint": int(stint), "compound": _first(group, "Compound"), "startLap": int(group["LapNumber"].min()), "endLap": int(group["LapNumber"].max()), "laps": len(group), "medianPace": float(median(_seconds(value) for value in group["LapTime"]))})
    return output


def _pit_stops(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if "PitInTime" not in laps or "PitOutTime" not in laps:
        return []
    ordered = laps.sort_values("LapNumber")
    output = []
    pit_ins = ordered[ordered["PitInTime"].notna()]
    for _, row in pit_ins.iterrows():
        next_rows = ordered[(ordered["LapNumber"] > row["LapNumber"]) & ordered["PitOutTime"].notna()]
        duration = None
        if not next_rows.empty:
            duration = _seconds(next_rows.iloc[0]["PitOutTime"] - row["PitInTime"])
        output.append({"lap": int(row["LapNumber"]), "duration": duration})
    return output


def _pole_sitter(session: Any) -> str | None:
    results = getattr(session, "results", pd.DataFrame())
    if results is not None and not results.empty and "Position" in results:
        row = results.sort_values("Position").iloc[0]
        return _text(row, "Abbreviation")
    return None


def _session_weather(session: Any) -> str | None:
    weather = getattr(session, "weather_data", pd.DataFrame())
    if weather is None or weather.empty or "Rainfall" not in weather:
        return None
    return "wet" if weather["Rainfall"].fillna(False).astype(bool).any() else "dry"


def _first(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame:
        return None
    values = frame[column].dropna()
    return values.iloc[0] if not values.empty else None


def _text(row: pd.Series, column: str) -> str | None:
    value = row[column] if column in row else None
    return None if value is None or pd.isna(value) else str(value)


def _number(row: pd.Series, column: str) -> float | None:
    value = row[column] if column in row else None
    return None if value is None or pd.isna(value) else float(value)


def _integer(row: pd.Series, column: str) -> int | None:
    value = _number(row, column)
    return int(value) if value is not None else None


def _seconds(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value.total_seconds()) if hasattr(value, "total_seconds") else float(value)


def _empty_payload(year: int, message: str) -> dict[str, Any]:
    return {
        "meta": {"season": year, "generatedAt": datetime.now(timezone.utc).isoformat(), "completedRounds": [], "availableRound": None, "isComplete": False, "partial": True},
        "events": [],
        "records": [],
        "entities": {"drivers": [], "teams": []},
        "message": message,
        "errors": [],
        "methodology": METHODOLOGY,
    }


METHODOLOGY = {
    "qualifyingDeficit": {"definition": "Fastest valid driver lap divided by the fastest valid event lap, minus one.", "formula": "(driver time / event reference - 1) × 100", "included": "Timed, non-deleted qualifying laps", "excluded": "Deleted and untimed laps", "minimum": 1, "limitations": "Traffic and changing conditions are not adjusted."},
    "observedRacePace": {"definition": "Median clean green-flag lap time normalized to the event fastest median.", "formula": "(driver median / fastest median - 1) × 100", "included": "Accurate timed laps", "excluded": "Pit, deleted, inaccurate, neutralised and MAD-outlier laps", "minimum": 1, "limitations": "Fuel, tyre and traffic differences remain."},
    "adjustedRacePace": {"definition": "Observed median with linear tyre-age and race-lap trends removed.", "formula": "median − tyre coefficient × median tyre age − lap coefficient × median race lap", "included": "Same clean laps as observed pace", "excluded": "Same exclusions as observed pace", "minimum": 5, "limitations": "Fuel is a lap-number proxy; traffic is not reliably observable."},
    "developmentRate": {"definition": "Linear least-squares slope of normalized deficit over round.", "formula": "deficit = intercept + rate × round", "minimum": 3, "limitations": "Circuit mix can influence the slope; negative is improvement."},
    "expectedPoints": {"definition": "Points schedule applied to combined qualifying/race-pace rank and scaled by observed team classification rate.", "formula": "position points × reliability probability", "minimum": 1, "limitations": "A transparent benchmark, not objective expected value."},
    "pointsConversion": {"definition": "Actual points divided by model-estimated expected points.", "formula": "actual / expected", "minimum": 1, "limitations": "Undefined when expected points are zero."},
    "reliability": {"definition": "Classified finishes divided by starts, based on published result status.", "formula": "classified / starts × 100", "minimum": 1, "limitations": "Status text cannot identify every underlying cause."},
    "tyreDegradation": {"definition": "Linear tyre-age coefficient while controlling for race lap as a fuel/track proxy.", "formula": "lap time = intercept + tyre age + race lap", "minimum": 5, "limitations": "Fuel, traffic and weather are proxy-adjusted, not directly measured."},
    "momentum": {"definition": "Documented weighted blend of recent pace, points, development, reliability and pit operations.", "weights": MOMENTUM_WEIGHTS, "minimum": 1, "limitations": "Weights are product configuration, not physical truth."},
    "upgradeImpact": {"definition": "Before/after normalized performance association around sourced upgrade events.", "minimum": 3, "limitations": "FastF1 has no authoritative upgrade feed; only sourced configured entries are published. Association is not causation."},
    "changePoint": {"definition": "Best median split whose standardized magnitude clears a minimum evidence threshold.", "minimum": 6, "limitations": "Approximate round; circuit changes may create false signals."},
    "prediction": {"definition": "Recent median plus development slope, using only rounds before the target.", "formula": "median(last 3) + development rate", "minimum": 1, "limitations": "Categorical circuit similarity and historical pace only; clearly predictive."},
    "strategy": {"definition": "Observable pit timing and points conversion components.", "minimum": 1, "limitations": "No causal strategy rating is emitted without reliable traffic and intent data."},
}
