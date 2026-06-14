# FastF1 Lap Difference Detection

Evidence-based lap comparison using only FastF1-supported data. The tool aligns laps by distance, compares telemetry channels, detects meaningful gains/losses, and labels uncertain vehicle-behavior conclusions as heuristics.

## What It Uses

Direct FastF1 telemetry: speed, RPM, gear, throttle, brake state, DRS, X/Y/Z, time/session time/date/source.

Computed/context data: lap and sector times, distance, tyre compound/life, track status, lap validity, weather, and optional traffic fields when available.

It does not use or claim steering angle, brake pressure, tyre temperature, tyre pressure, tyre wear percentage, fuel level, wheel speed, suspension data, real G-force, yaw rate, slip angle, lockup, wheelspin, direct understeer, or direct oversteer.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Use Python 3.10 or newer. If your current virtual environment was created with Python 3.9, recreate it with a newer Python before installing.

## CLI Examples

Compare a selected lap with a driver's fastest lap:

```bash
fastf1-lapdiff compare --year 2024 --event Monza --session Q --driver LEC --lap 8
```

Compare two explicit laps:

```bash
fastf1-lapdiff compare --year 2024 --event Monza --session Q --driver LEC --reference-lap 6 --lap 8
```

Write JSON instead of Markdown:

```bash
fastf1-lapdiff compare --year 2024 --event Monza --session Q --driver LEC --lap 8 --format json
```

Create a dashboard-ready payload:

```bash
fastf1-lapdiff compare --year 2024 --event Monza --session Q --driver LEC --lap 8 --format dashboard-json --output report.json
```

## Web Dashboard

The hosted dashboard is a no-login FastAPI app. Users select a season, event, session, car/team filter, and one or two drivers. If the same driver is selected twice, the app compares that driver’s two fastest comparable laps. If two drivers are selected, it compares the fastest comparable lap for each driver.

Run locally:

```bash
python3 -m pip install -e .
fastf1-lapdiff-web
```

Then open:

```text
http://localhost:8000
```

Useful deployment notes:

- Set `FASTF1_CACHE_DIR` to a persistent writable directory so FastF1 data is cached across requests.
- Set `PORT` if your host provides a dynamic port.
- The backend routes are `/api/seasons`, `/api/events`, `/api/session-entries`, and `/api/compare-best-laps`.
- The frontend lives in `frontend/` and is served by FastAPI from the same origin, so it can be placed behind a normal website reverse proxy.

Docker:

```bash
docker build -t fastf1-lapdiff .
docker run -p 8000:8000 -e FASTF1_CACHE_DIR=/app/.fastf1-cache fastf1-lapdiff
```

## MVP Capabilities

- Distance-based telemetry alignment
- Total and sector delta calculations
- Delta-time gain/loss section ranking
- Braking point and release differences
- Minimum, entry, and exit speed differences
- Throttle start, full-throttle, hesitation, coasting, early lift, and overlap detections
- Gear, shift, RPM, DRS, top-speed, acceleration, and racing-line deviation comparisons
- Lap cleanliness validation from FastF1 context
- Weather and tyre context
- Natural-language Markdown or structured JSON reports
- Publishable FastAPI dashboard with telemetry traces, detection ranking, section detail, and X/Y path map

## Design Principle

Every detection includes evidence and confidence. Approximate path analysis and behavior interpretations are deliberately labelled as approximate or heuristic.
