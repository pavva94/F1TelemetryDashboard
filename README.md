# FastF1 Lap Difference Detection
[Official Website](https://www.pavesialessandro.com/F1TelemetryDashboard/index.html) · [![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/A3A423RK3Y)

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
- The backend routes are `/api/seasons`, `/api/events`, `/api/session-summary`, `/api/session-entries`, and `/api/compare-best-laps`.
- The event view includes every scheduled weekend session in race-first order. Sessions without timing data remain selectable and report `no_data_yet` rather than failing the dashboard.
- The frontend lives in `frontend/` and is served by FastAPI from the same origin, so it can be placed behind a normal website reverse proxy.

Docker:

```bash
docker build -t fastf1-lapdiff .
docker run -p 8000:8000 -e FASTF1_CACHE_DIR=/app/.fastf1-cache fastf1-lapdiff
```

## Deploy on Render

The repository includes a Render Blueprint in `render.yaml`. The default deployment serves both the dashboard and API from one Docker web service, which avoids cross-origin configuration.

1. Push the repository to a Git provider supported by Render.
2. In Render, choose **New > Blueprint** and select the repository.
3. Review the `fastf1-lapdiff` free web service and deploy it.
4. Verify `https://<service-name>.onrender.com/api/health` returns `{"status":"ok"}`.

Render provides `PORT` automatically. The Blueprint stores FastF1's runtime cache under `/tmp`; on a free service this cache is ephemeral and is lost when the instance restarts or spins down.

### Use a separately hosted frontend

The bundled frontend uses same-origin API routes by default. When it is deployed on another host, define the backend URL before loading `app.js`:

```html
<script>
  window.FASTF1_API_BASE = "https://<service-name>.onrender.com";
</script>
<script src="app.js"></script>
```

Also add an environment variable to the Render service containing the exact frontend origin (multiple origins are comma-separated):

```text
FASTF1_ALLOWED_ORIGINS=https://your-frontend.example
```

Origins should include the scheme and hostname but no path. Because this dashboard exposes only a public, read-only API, the included Render Blueprint uses `*` so static deployments can connect without extra configuration. Replace it with exact origins if the API later gains authenticated or mutating routes. Leave this variable unset when Render serves the included frontend.

## MVP Capabilities

- Distance-based telemetry alignment
- Total and sector delta calculations
- Delta-time gain/loss section ranking
- Braking point and release differences
- Minimum, entry, and exit speed differences
- Throttle start, full-throttle, hesitation, coasting, early lift, and overlap detections
- Gear, shift, RPM, DRS, top-speed, acceleration, and racing-line deviation comparisons
- Engineering section metrics for straights, braking zones, corner categories, DRS distance, brake distance, speed gain, gear mode, RPM, and exit speed
- Performance fingerprint summary that separates straight, braking, low-speed, medium-speed, high-speed, and DRS time deltas
- Dashboard evidence boundary for direct FastF1 channels, derived metrics, heuristic inferences, and excluded unavailable data
- Lap cleanliness validation from FastF1 context
- Weather and tyre context
- Natural-language Markdown or structured JSON reports
- Publishable FastAPI dashboard with telemetry traces, detection ranking, section detail, and X/Y path map

## Design Principle

Every detection includes evidence and confidence. Approximate path analysis and behavior interpretations are deliberately labelled as approximate or heuristic.
