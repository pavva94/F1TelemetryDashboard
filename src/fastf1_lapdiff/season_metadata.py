"""Maintainable, qualitative metadata used by season-level models.

FastF1 does not publish aerodynamic upgrade specifications or authoritative
numeric circuit-characteristic scores.  The circuit entries below are therefore
deliberately categorical rather than fabricated measurements.  They are model
inputs, not claims about precise physical values.  Upgrade entries can be added
with a source URL; unsourced entries are ignored by the public API.
"""

from __future__ import annotations

from typing import Any


CIRCUIT_CHARACTERISTICS: dict[str, dict[str, str]] = {
    "Bahrain Grand Prix": {"cluster": "traction", "speed": "mixed", "downforce": "medium", "tyre_stress": "high"},
    "Saudi Arabian Grand Prix": {"cluster": "high_speed", "speed": "high", "downforce": "medium", "tyre_stress": "medium"},
    "Australian Grand Prix": {"cluster": "mixed", "speed": "mixed", "downforce": "medium", "tyre_stress": "medium"},
    "Japanese Grand Prix": {"cluster": "high_speed", "speed": "high", "downforce": "high", "tyre_stress": "high"},
    "Chinese Grand Prix": {"cluster": "front_limited", "speed": "mixed", "downforce": "medium", "tyre_stress": "medium"},
    "Miami Grand Prix": {"cluster": "traction", "speed": "mixed", "downforce": "medium", "tyre_stress": "medium"},
    "Emilia Romagna Grand Prix": {"cluster": "mixed", "speed": "mixed", "downforce": "medium", "tyre_stress": "medium"},
    "Monaco Grand Prix": {"cluster": "low_speed", "speed": "low", "downforce": "high", "tyre_stress": "low"},
    "Canadian Grand Prix": {"cluster": "braking", "speed": "mixed", "downforce": "low", "tyre_stress": "medium"},
    "Spanish Grand Prix": {"cluster": "high_speed", "speed": "high", "downforce": "high", "tyre_stress": "high"},
    "Austrian Grand Prix": {"cluster": "braking", "speed": "high", "downforce": "medium", "tyre_stress": "medium"},
    "British Grand Prix": {"cluster": "high_speed", "speed": "high", "downforce": "high", "tyre_stress": "high"},
    "Belgian Grand Prix": {"cluster": "high_speed", "speed": "high", "downforce": "low", "tyre_stress": "high"},
    "Hungarian Grand Prix": {"cluster": "traction", "speed": "low", "downforce": "high", "tyre_stress": "high"},
    "Dutch Grand Prix": {"cluster": "high_speed", "speed": "mixed", "downforce": "high", "tyre_stress": "high"},
    "Italian Grand Prix": {"cluster": "straights", "speed": "high", "downforce": "low", "tyre_stress": "medium"},
    "Azerbaijan Grand Prix": {"cluster": "straights", "speed": "mixed", "downforce": "low", "tyre_stress": "low"},
    "Singapore Grand Prix": {"cluster": "low_speed", "speed": "low", "downforce": "high", "tyre_stress": "high"},
    "United States Grand Prix": {"cluster": "mixed", "speed": "mixed", "downforce": "high", "tyre_stress": "high"},
    "Mexico City Grand Prix": {"cluster": "altitude", "speed": "mixed", "downforce": "high", "tyre_stress": "medium"},
    "São Paulo Grand Prix": {"cluster": "mixed", "speed": "mixed", "downforce": "medium", "tyre_stress": "high"},
    "Las Vegas Grand Prix": {"cluster": "straights", "speed": "high", "downforce": "low", "tyre_stress": "low"},
    "Qatar Grand Prix": {"cluster": "high_speed", "speed": "high", "downforce": "high", "tyre_stress": "high"},
    "Abu Dhabi Grand Prix": {"cluster": "traction", "speed": "mixed", "downforce": "medium", "tyre_stress": "medium"},
}


# Schema: team, event, component, category, description, source, confidence.
# Entries without a source are intentionally rejected by ``published_upgrades``.
UPGRADE_METADATA: dict[int, list[dict[str, Any]]] = {}


def circuit_characteristics(event_name: str) -> dict[str, str] | None:
    return CIRCUIT_CHARACTERISTICS.get(event_name)


def published_upgrades(year: int) -> list[dict[str, Any]]:
    return [entry.copy() for entry in UPGRADE_METADATA.get(year, []) if entry.get("source")]
