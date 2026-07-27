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
- The backend routes are `/api/seasons`, `/api/events`, `/api/session-summary`, `/api/session-entries`, `/api/compare-best-laps`, and `/api/season-analysis`.
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

## Analysis Routes

The dashboard is a two-page analysis platform:

- `/race` preserves the original single-weekend session, standings, pace, stint, pit-stop, and lap-comparison workflow.
- `/season` builds a cacheable season dataset across completed rounds and exposes championship evolution, normalized qualifying and race pace, development, team and driver comparisons, reliability, tyres, operations, track suitability, points conversion, momentum, change detection, and leakage-safe predictions.
- The `/` URL opens Season Analysis by default. Direct `/season` and `/race` URLs remain available, and season heatmaps, tables, and race-history cards link to Race Analysis with `year`, `event`, `session`, driver, and team query context.

Season filter state is stored in URL query parameters. Direct links, refresh, browser back/forward, and return navigation therefore preserve the active season range and model choices.

## Season Data Pipeline

`src/fastf1_lapdiff/season_analytics.py` loads Race and Qualifying timing without car telemetry and normalizes each completed event. The complete chart-ready result is stored once per season as a versioned, gzip-compressed shared server cache. Cross-process file locks prevent duplicate work, stale locks are recovered, and an atomic generation pointer keeps the previous valid dataset available throughout refreshes. FastF1's disk cache remains the event-level source cache.

The public endpoints are:

```text
GET /api/seasons
GET /api/season/2024/status
GET /api/season/2024/analysis
POST /api/season/2024/refresh
```

`/api/season-analysis?year=2024` remains as a compatibility alias. Configure
`SEASON_ANALYSIS_CACHE_DIR` on persistent storage and set `SEASON_REFRESH_TOKEN`
to enable the protected refresh endpoint (send it as `X-Season-Refresh-Token`).
The current season is refreshed only when the lightweight schedule check sees a
new completed round; completed historical seasons do not expire on a short TTL.

Administrators can prepare one season or all configured seasons explicitly:

```bash
python -m fastf1_lapdiff.precompute_season --season 2026
python -m fastf1_lapdiff.precompute_season --all
```

The response explicitly separates:

- observed results and clean-lap medians;
- adjusted estimates, including tyre-age and race-lap proxy corrections;
- model estimates such as expected points;
- predictions, including the exact historical rounds used;
- quality metadata, exclusions, sample sizes, and confidence.

The page reports completed-round coverage, partial session failures, generation time, retryable errors, and unavailable metrics when evidence is below its minimum sample size. Expensive transformations run server-side and client-side chart transformations are derived from the already-normalized payload.

## Season Metrics and Models

- **Qualifying deficit:** `(representative time / fastest event representative time - 1) × 100`.
- **Observed race pace:** robust median of accurate timed laps after pit, deleted, neutralised, and MAD-outlier exclusions, normalized per event.
- **Adjusted race pace:** observed pace with fitted tyre-age and race-lap trends removed. Race lap is disclosed as a fuel/track-evolution proxy because FastF1 does not expose fuel load.
- **Development:** normalized-deficit slope per round, early-versus-recent robust medians, confidence interval, R², and approximate median-split change points.
- **Reliability:** classification from published result status, separating classified finishes, mechanical failures, incidents, DNS, and DSQ.
- **Tyre degradation:** `lap time = intercept + tyre age + race lap`, with residual MAD and lap count.
- **Expected points:** combined performance rank mapped to the points schedule and scaled by observed team classification probability. This is a transparent benchmark, not objective truth.
- **Points conversion:** actual points divided by expected points, with zero-expectation handled as undefined.
- **Momentum:** centralized documented weights in `MOMENTUM_WEIGHTS` for race pace, qualifying, points, development, reliability, and observable pit operations.
- **Prediction:** recent three-round median plus development slope, trained only on rounds strictly before the target. Historical backtests expose rank and deficit error.

Every formula, minimum sample, exclusion rule, and limitation is also available in the in-product Methodology panel.

## Maintained Metadata

`src/fastf1_lapdiff/season_metadata.py` contains categorical circuit metadata. It deliberately avoids unsupported precise measurements. Categories describe circuit clusters, general speed/downforce profile, and tyre-stress tendency and are used only for association and similar-circuit views.

Upgrade metadata uses this schema:

```python
{
    "team": "Example Team",
    "round": 7,
    "event": "Example Grand Prix",
    "component": "Floor",
    "category": "floor",
    "description": "Source-supported description",
    "source": "https://authoritative.example/report",
    "confidence": "high",
}
```

Only entries with a source are published. FastF1 does not provide an authoritative upgrade, power-unit penalty, unsafe-release, traffic, car-damage, or strategy-intent feed. The dashboard therefore withholds those claims when no sourced metadata exists and labels before/after upgrade output as association rather than causation. It also avoids presenting grid-to-finish change as pure overtaking.

## Season Analysis Limitations

- Traffic, damage, exact fuel load, race-management intent, and precise clean-air state are not directly available.
- Adjusted pace uses reproducible proxies and falls back to observed pace when fewer than five clean laps support the fit.
- Pit timing is pit-lane duration where paired FastF1 timestamps exist, not stationary wheel-change time.
- Circuit characteristics are maintained qualitative metadata, not measured telemetry values.
- Weather filtering uses session rainfall observations; no forecast service is invented for future events.
- Expected points and predictions are explicitly modelled estimates with confidence and historical leakage guards.

## Testing

The repository's dependency-light runner executes the existing race-analysis tests and all season model tests:

```bash
.venv/bin/python tests/run_tests.py
```

The season suite covers percentage deficits, rolling medians, MAD outlier rejection, lap-quality filtering, development regression, early/recent comparisons, reliability classification, degradation, expected-points conversion, change-point detection, aggregation, API routes, and strict no-future-data prediction backtests.

## Capabilities

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
