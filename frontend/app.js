const els = {
  raceForm: document.querySelector("#race-form"),
  comparisonForm: document.querySelector("#comparison-form"),
  loadRace: document.querySelector("#load-race"),
  season: document.querySelector("#season"),
  event: document.querySelector("#event"),
  track: document.querySelector("#track"),
  sessionA: document.querySelector("#session-a"),
  sessionB: document.querySelector("#session-b"),
  team: document.querySelector("#team"),
  driverA: document.querySelector("#driver-a"),
  driverB: document.querySelector("#driver-b"),
  status: document.querySelector("#status"),
  raceTitle: document.querySelector("#race-title"),
  raceSummary: document.querySelector("#race-summary-text"),
  raceWinner: document.querySelector("#race-winner"),
  raceTime: document.querySelector("#race-time"),
  fastestLap: document.querySelector("#fastest-lap"),
  raceLaps: document.querySelector("#race-laps"),
  standings: document.querySelector("#standings"),
  positionChart: document.querySelector("#position-chart"),
  positionTooltip: document.querySelector("#position-tooltip"),
  paceViolinChart: document.querySelector("#pace-violin-chart"),
  paceViolinTooltip: document.querySelector("#pace-violin-tooltip"),
  teamPaceChart: document.querySelector("#team-pace-chart"),
  teamPaceTooltip: document.querySelector("#team-pace-tooltip"),
  sector1Chart: document.querySelector("#sector1-chart"),
  sector2Chart: document.querySelector("#sector2-chart"),
  sector3Chart: document.querySelector("#sector3-chart"),
  paceTrendChart: document.querySelector("#pace-trend-chart"),
  paceTrendTooltip: document.querySelector("#pace-trend-tooltip"),
  stintTimelineChart: document.querySelector("#stint-timeline-chart"),
  stintTooltip: document.querySelector("#stint-tooltip"),
  pitStopChart: document.querySelector("#pit-stop-chart"),
  pitStopTooltip: document.querySelector("#pit-stop-tooltip"),
  raceInsightTables: document.querySelector("#race-insight-tables"),
  title: document.querySelector("#selection-title"),
  summary: document.querySelector("#summary-text"),
  totalDelta: document.querySelector("#total-delta"),
  referenceLap: document.querySelector("#reference-lap"),
  comparedLap: document.querySelector("#compared-lap"),
  validity: document.querySelector("#validity"),
  sectors: document.querySelector("#sector-bars"),
  context: document.querySelector("#context-list"),
  fingerprint: document.querySelector("#fingerprint"),
  dataScope: document.querySelector("#data-scope"),
  sectionMetrics: document.querySelector("#section-metrics"),
  traceLegend: document.querySelector("#trace-legend"),
  detections: document.querySelector("#detections"),
  detail: document.querySelector("#finding-detail"),
  trace: document.querySelector("#trace-canvas"),
  traceTooltip: document.querySelector("#trace-tooltip"),
  map: document.querySelector("#map-canvas"),
};

let referenceDrivers = [];
let comparedDrivers = [];
let currentPayload = null;
let currentRace = null;
let currentFilter = "all";
let positionHoverLap = null;
let traceHoverIndex = null;
let paceViolinHoverIndex = null;
let paceTrendHoverIndex = null;
let stintHoverIndex = null;
let pitStopHoverIndex = null;
let teamPaceHoverIndex = null;
let findingTelemetryHoverIndex = null;

init();

async function init() {
  wireEvents();
  await loadSeasons();
}

function wireEvents() {
  els.season.addEventListener("change", loadEvents);
  els.event.addEventListener("change", handleEventChange);
  els.sessionA.addEventListener("change", loadComparisonEntries);
  els.sessionB.addEventListener("change", loadComparisonEntries);
  els.team.addEventListener("change", renderDrivers);
  els.raceForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadRaceSummary();
  });
  els.comparisonForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runAnalysis();
  });
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
      button.classList.add("active");
      currentFilter = button.dataset.filter;
      renderDetections(currentPayload);
    });
  });
  window.addEventListener("resize", () => {
    if (currentRace) renderRaceCharts(currentRace);
    if (currentPayload) renderCharts(currentPayload);
  });
  els.positionChart.addEventListener("mousemove", updatePositionHover);
  els.positionChart.addEventListener("mouseleave", clearPositionHover);
  els.trace.addEventListener("mousemove", updateTraceHover);
  els.trace.addEventListener("mouseleave", clearTraceHover);
  els.paceViolinChart.addEventListener("mousemove", updatePaceViolinHover);
  els.paceViolinChart.addEventListener("mouseleave", clearPaceViolinHover);
  els.paceTrendChart.addEventListener("mousemove", updatePaceTrendHover);
  els.paceTrendChart.addEventListener("mouseleave", clearPaceTrendHover);
  els.stintTimelineChart.addEventListener("mousemove", updateStintHover);
  els.stintTimelineChart.addEventListener("mouseleave", clearStintHover);
  els.pitStopChart.addEventListener("mousemove", updatePitStopHover);
  els.pitStopChart.addEventListener("mouseleave", clearPitStopHover);
  els.teamPaceChart.addEventListener("mousemove", updateTeamPaceHover);
  els.teamPaceChart.addEventListener("mouseleave", clearTeamPaceHover);
}

async function loadSeasons() {
  setStatus("Loading seasons...");
  try {
    const data = await api("/api/seasons");
    fillSelect(els.season, data.seasons.map((year) => ({ value: year, label: year })));
    await loadEvents();
  } catch (error) {
    setError(error);
  }
}

async function loadEvents() {
  setStatus("Loading events...");
  clearSelect(els.event);
  clearSelect(els.sessionA);
  clearSelect(els.sessionB);
  try {
    const data = await api(`/api/events?year=${encodeURIComponent(els.season.value)}`);
    fillSelect(els.event, data.events.map((event) => ({ value: event.name, label: `${event.round}. ${event.name}` })));
    els.event._events = data.events;
    handleEventChange();
    setStatus("Race list loaded. Choose a race and load the summary.");
  } catch (error) {
    setError(error);
  }
}

function handleEventChange() {
  renderTrack();
  loadSessions();
}

function renderTrack() {
  const selected = (els.event._events || []).find((event) => event.name === els.event.value);
  els.track.value = selected ? [selected.location, selected.country].filter(Boolean).join(", ") || selected.name : "--";
}

function loadSessions() {
  const selected = (els.event._events || []).find((event) => event.name === els.event.value);
  const sessions = selected?.sessions?.length ? selected.sessions : defaultSessions();
  const options = sessions.map((session) => ({ value: session.name, label: session.name }));
  fillSelect(els.sessionA, options);
  fillSelect(els.sessionB, options);
  if ([...els.sessionA.options].some((option) => option.value === "Qualifying")) {
    els.sessionA.value = "Qualifying";
  }
  if ([...els.sessionB.options].some((option) => option.value === "Race")) {
    els.sessionB.value = "Race";
  }
  clearComparisonControls();
}

async function loadComparisonEntries() {
  if (!els.season.value || !els.event.value || !els.sessionA.value || !els.sessionB.value) return;
  setStatus("Loading drivers and cars for the selected comparison sessions...");
  try {
    const referenceParams = new URLSearchParams({ year: els.season.value, event: els.event.value, session: els.sessionA.value });
    const comparedParams = new URLSearchParams({ year: els.season.value, event: els.event.value, session: els.sessionB.value });
    const [referenceData, comparedData] = await Promise.all([
      api(`/api/session-entries?${referenceParams}`),
      api(`/api/session-entries?${comparedParams}`),
    ]);
    referenceDrivers = referenceData.drivers || [];
    comparedDrivers = comparedData.drivers || [];
    const teams = [...new Set([...referenceDrivers, ...comparedDrivers].map((driver) => driver.team).filter(Boolean))].sort();
    fillSelect(els.team, [{ value: "all", label: "All teams" }, ...teams.map((team) => ({ value: team, label: team }))]);
    renderDrivers();
    setStatus("Race loaded. Choose comparison drivers or inspect the race summary.");
  } catch (error) {
    setError(error);
  }
}

async function loadRaceSummary() {
  if (!els.season.value || !els.event.value) return;
  setStatus("Loading race summary, standings, and lap positions...");
  els.loadRace.disabled = true;
  try {
    const params = new URLSearchParams({ year: els.season.value, event: els.event.value });
    currentRace = await api(`/api/race-summary?${params}`);
    renderRaceSummary(currentRace);
    await loadComparisonEntries();
  } catch (error) {
    setError(error);
  } finally {
    els.loadRace.disabled = false;
  }
}

function clearComparisonControls() {
  referenceDrivers = [];
  comparedDrivers = [];
  fillSelect(els.team, [{ value: "all", label: "Load race first" }]);
  clearSelect(els.driverA);
  clearSelect(els.driverB);
}

function renderDrivers() {
  const team = els.team.value;
  const referenceOptions = referenceDrivers.filter((driver) => team === "all" || driver.team === team).map((driver) => ({
    value: driver.code,
    label: `${driver.code}${driver.team ? ` · ${driver.team}` : ""}`,
  }));
  const comparedOptions = comparedDrivers.filter((driver) => team === "all" || driver.team === team).map((driver) => ({
    value: driver.code,
    label: `${driver.code}${driver.team ? ` · ${driver.team}` : ""}`,
  }));
  fillSelect(els.driverA, referenceOptions);
  fillSelect(els.driverB, comparedOptions);
  if (comparedOptions[1]) els.driverB.value = comparedOptions[1].value;
}

async function runAnalysis() {
  if (!els.driverA.value) return;
  setStatus("Loading FastF1 data and comparing best laps. This can take a moment on first load...");
  els.comparisonForm.querySelector("button").disabled = true;
  try {
    const params = new URLSearchParams({
      year: els.season.value,
      event: els.event.value,
      session_a: els.sessionA.value,
      session_b: els.sessionB.value,
      driver_a: els.driverA.value,
      driver_b: els.driverB.value || els.driverA.value,
    });
    currentPayload = await api(`/api/compare-best-laps?${params}`);
    renderDashboard(currentPayload);
    setStatus("Analysis complete.");
  } catch (error) {
    setError(error);
  } finally {
    els.comparisonForm.querySelector("button").disabled = false;
  }
}

function renderRaceSummary(race) {
  const winner = race.winner || {};
  const fastest = race.fastestLap || {};
  els.raceTitle.textContent = `${race.year || ""} ${race.event || ""}`;
  els.raceSummary.textContent = `${race.location || "Track"}${race.country ? `, ${race.country}` : ""}. ${race.classifiedDrivers || 0} classified drivers${race.lapCount ? ` over ${race.lapCount} laps` : ""}.`;
  els.raceWinner.textContent = winner.driver ? `${winner.driver}${winner.team ? ` · ${winner.team}` : ""}` : "--";
  els.raceTime.textContent = race.raceTime || winner.status || "--";
  els.fastestLap.textContent = fastest.driver ? `${fastest.driver} L${fastest.lap} ${clock(fastest.time)}` : "--";
  els.raceLaps.textContent = race.lapCount || "--";
  renderStandings(race.standings || []);
  renderRaceCharts(race);
  renderRaceInsightTables(race.raceInsights || {});
}

function renderStandings(standings) {
  els.standings.innerHTML = standings
    .map((item) => `<tr>
      <td>${item.position ?? "--"}</td>
      <td><strong>${escapeHtml(item.driver || "--")}</strong>${item.fullName ? `<span>${escapeHtml(item.fullName)}</span>` : ""}</td>
      <td>${escapeHtml(item.team || "--")}</td>
      <td>${item.grid ?? "--"}</td>
      <td>${escapeHtml(item.time || item.status || "--")}</td>
      <td>${isFiniteNumber(item.points) ? item.points : "--"}</td>
    </tr>`)
    .join("");
}

function renderDashboard(payload) {
  const report = payload.report;
  const selection = payload.selection || {};
  els.title.textContent = `${selection.year || ""} ${selection.event || ""} · ${selection.session || ""}`;
  els.summary.textContent = report.summary || "Comparison complete.";
  els.totalDelta.textContent = seconds(report.total_delta_seconds);
  els.referenceLap.textContent = lapLabel(report.reference);
  els.comparedLap.textContent = lapLabel(report.compared);
  els.validity.textContent = `${report.reference_validity.classification} / ${report.compared_validity.classification}`;
  renderSectors(report);
  renderContext(report);
  renderFingerprint(payload.performance_profile, report);
  renderDataScope(payload.data_scope);
  renderSectionMetrics(payload.section_metrics || []);
  renderTraceLegend(report);
  renderDetections(payload);
  renderCharts(payload);
}

function renderSectors(report) {
  const values = report.sector_deltas_seconds || [];
  const max = Math.max(0.001, ...values.map((value) => Math.abs(value || 0)));
  const legend = renderDeltaLegend(report);
  const rows = values
    .map((value, index) => {
      const width = Math.max(4, (Math.abs(value || 0) / max) * 100);
      const cls = value > 0 ? "loss" : "";
      const winner = deltaWinnerLabel(value, report);
      return `<div class="sector-row">
        <strong>S${index + 1}</strong>
        <div class="sector-track"><div class="sector-fill ${cls}" style="width:${width}%"></div></div>
        <span><b>${escapeHtml(winner)}</b>${seconds(value)}</span>
      </div>`;
    })
    .join("");
  els.sectors.innerHTML = `${legend}${rows}`;
}

function renderContext(report) {
  const weather = report.weather_context || {};
  const weatherItems = Object.entries(weather)
    .filter(([key]) => key !== "Time")
    .slice(0, 6)
    .map(([key, value]) => `${key}: ${value}`);
  const items = [...(report.tyre_context || []), ...weatherItems, "FastF1 does not expose steering angle, brake pressure, tyre wear percentage, fuel load, wheelspin, lockup, or real G-force."];
  els.context.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderFingerprint(profile, report) {
  if (!profile) {
    els.fingerprint.innerHTML = "";
    return;
  }
  const buckets = [
    ["Straights", profile.straight_time_delta_seconds],
    ["Braking", profile.braking_time_delta_seconds],
    ["Low-speed", profile.low_speed_corner_delta_seconds],
    ["Medium-speed", profile.medium_speed_corner_delta_seconds],
    ["High-speed", profile.high_speed_corner_delta_seconds],
    ["DRS", profile.drs_time_delta_seconds],
  ];
  const max = Math.max(0.001, ...buckets.map(([, value]) => Math.abs(value || 0)));
  const rows = buckets
    .map(([label, value]) => {
      const width = Math.max(3, (Math.abs(value || 0) / max) * 100);
      const cls = value > 0 ? "loss" : "gain";
      const winner = deltaWinnerLabel(value, report);
      return `<div class="fingerprint-row">
        <span>${escapeHtml(label)}</span>
        <div class="fingerprint-track"><i class="${cls}" style="width:${width}%"></i></div>
        <strong class="${cls}"><em>${escapeHtml(winner)}</em>${seconds(value)}</strong>
      </div>`;
    })
    .join("");
  const summary = [
    profile.average_corner_exit_speed_delta_kmh !== null ? `Avg corner exit ${signed(profile.average_corner_exit_speed_delta_kmh, " km/h")}` : null,
    profile.average_full_throttle_delta_m !== null ? `Full throttle ${signed(profile.average_full_throttle_delta_m, " m")}` : null,
    `DRS active ${signed(profile.average_drs_distance_delta_m || 0, " m")}`,
  ].filter(Boolean);
  const stronger = listBlock("Stronger indicators", profile.stronger_indicators || []);
  const weaker = listBlock("Weaker indicators", profile.weaker_indicators || []);
  els.fingerprint.innerHTML = `${renderDeltaLegend(report)}${rows}<div class="fingerprint-summary">${summary.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>${stronger}${weaker}`;
}

function renderDeltaLegend(report) {
  const reference = lapShort(report.reference);
  const compared = lapShort(report.compared);
  return `<div class="delta-legend" aria-label="Delta legend">
    <span><i class="gain"></i>${escapeHtml(compared)} gains</span>
    <span><i class="loss"></i>${escapeHtml(reference)} gains</span>
    <small>Delta = compared minus reference</small>
  </div>`;
}

function deltaWinnerLabel(value, report) {
  if (!isFiniteNumber(value) || Math.abs(value) < 0.001) return "Even";
  return value > 0 ? lapShort(report.reference) : lapShort(report.compared);
}

function renderDataScope(scope) {
  if (!scope) {
    els.dataScope.innerHTML = "";
    return;
  }
  const groups = [
    ["Direct", scope.direct || []],
    ["Derived", scope.derived || []],
    ["Heuristic", scope.heuristic || []],
    ["Excluded", scope.excluded || []],
  ];
  els.dataScope.innerHTML = groups
    .map(([label, items]) => `<div class="scope-group">
      <strong>${escapeHtml(label)}</strong>
      <p>${escapeHtml(items.join(", "))}</p>
    </div>`)
    .join("");
}

function renderSectionMetrics(metrics) {
  els.sectionMetrics.innerHTML = metrics
    .map((metric) => {
      const gear = metric.reference_gear_mode && metric.compared_gear_mode ? `${metric.reference_gear_mode} → ${metric.compared_gear_mode}` : "--";
      return `<tr>
        <td>${escapeHtml(metric.label)}</td>
        <td>${escapeHtml(metric.section_type)}</td>
        <td class="${metric.time_delta_seconds > 0 ? "loss-text" : "gain-text"}">${seconds(metric.time_delta_seconds)}</td>
        <td>${signed(metric.exit_speed_delta_kmh, " km/h")}</td>
        <td>${signed(metric.maximum_speed_delta_kmh, " km/h")}</td>
        <td>${signed(metric.brake_active_distance_delta_m, " m")}</td>
        <td>${signed(metric.drs_active_distance_delta_m, " m")}</td>
        <td>${escapeHtml(gear)}</td>
        <td><span class="tag">${escapeHtml(metric.confidence)}</span></td>
        <td class="metric-note">${escapeHtml(metric.note || "")}</td>
      </tr>`;
    })
    .join("");
}

function renderTraceLegend(report) {
  const labels = telemetryLabels(report);
  els.traceLegend.innerHTML = `<span><i class="ref"></i>${escapeHtml(labels.reference)}</span>
    <span><i class="cmp"></i>${escapeHtml(labels.compared)}</span>
    <span><i class="delta"></i>Delta time</span>`;
}

function renderDetections(payload) {
  if (!payload) return;
  const report = payload.report;
  const detections = (payload.report.detections || []).filter((detection) => {
    if (currentFilter === "loss") return detection.time_impact_seconds > 0.035;
    if (currentFilter === "gain") return detection.time_impact_seconds < -0.035;
    if (currentFilter === "heuristic") return detection.evidence_kind === "heuristic";
    return true;
  });

  els.detections.innerHTML = detections
    .map((detection, index) => {
      const direction = detection.time_impact_seconds > 0 ? "loss" : "gain";
      const heuristic = detection.evidence_kind === "heuristic" ? `<span class="tag heuristic">heuristic</span>` : "";
      const comparison = driverComparison(detection, report);
      return `<button class="finding" type="button" data-index="${index}">
        <span class="finding-top">
          <span class="finding-kind">${escapeHtml(detection.difference_type)}</span>
          <span class="impact ${direction}">${seconds(detection.time_impact_seconds)}</span>
        </span>
        <span>${escapeHtml(detection.section)}</span>
        <span class="driver-verdict">
          <strong>${escapeHtml(comparison.better)}</strong> better · <span>${escapeHtml(comparison.worse)}</span> losing
        </span>
        <span class="tags">
          <span class="tag">${escapeHtml(detection.confidence)} confidence</span>
          <span class="tag">${escapeHtml(detection.evidence_kind)}</span>
          ${heuristic}
        </span>
      </button>`;
    })
    .join("");

  [...els.detections.querySelectorAll(".finding")].forEach((button, index) => {
    button.addEventListener("click", () => {
      els.detections.querySelectorAll(".finding").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderFindingDetail(detections[index], payload);
    });
  });

  const first = els.detections.querySelector(".finding");
  if (first) first.classList.add("active");
  if (detections[0]) renderFindingDetail(detections[0], payload);
  else els.detail.textContent = "No findings match this filter.";
}

function renderFindingDetail(detection, payload) {
  const comparison = driverComparison(detection, payload.report);
  const labels = telemetryLabels(payload.report);
  els.detail.innerHTML = `<h4>${escapeHtml(detection.difference_type)}</h4>
    <div class="driver-comparison">
      <div>
        <span>Better in this section</span>
        <strong>${escapeHtml(comparison.better)}</strong>
      </div>
      <div>
        <span>Losing time here</span>
        <strong>${escapeHtml(comparison.worse)}</strong>
      </div>
    </div>
    <p><strong>${escapeHtml(detection.section)}</strong> · ${seconds(detection.time_impact_seconds)} · ${escapeHtml(detection.confidence)} confidence</p>
    <p>${escapeHtml(detection.what_happened)}</p>
    <div class="finding-telemetry-head">
      <strong>Telemetry for this finding</strong>
      <span>${Math.round(detection.start_distance)} m to ${Math.round(detection.end_distance)} m</span>
    </div>
    <div class="telemetry-legend">
      <span><i class="ref"></i>${escapeHtml(labels.reference)}</span>
      <span><i class="cmp"></i>${escapeHtml(labels.compared)}</span>
      <span><i class="delta"></i>Delta time</span>
    </div>
    <div class="chart-surface finding-telemetry-surface">
      <canvas id="finding-telemetry" class="finding-telemetry" width="620" height="360"></canvas>
      <div id="finding-telemetry-tooltip" class="chart-tooltip" hidden></div>
    </div>
    <ul>${(detection.evidence || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    <p>${escapeHtml(detection.interpretation)}</p>`;
  findingTelemetryHoverIndex = null;
  const canvas = document.querySelector("#finding-telemetry");
  drawFindingTelemetry(canvas, payload.telemetry, detection, payload);
  canvas.addEventListener("mousemove", updateFindingTelemetryHover);
  canvas.addEventListener("mouseleave", clearFindingTelemetryHover);
}

function renderCharts(payload) {
  drawTrace(payload.telemetry, payload.sections || []);
  drawMap(payload.telemetry, payload.report.detections || []);
}

function renderRaceCharts(race) {
  drawPositionChart(race);
  const insights = race?.raceInsights || {};
  drawPaceViolin(insights.driverPace || []);
  drawHorizontalRanking(els.teamPaceChart, insights.teamPace || [], {
    labelKey: "team",
    valueKey: "averagePace",
    meta: (item) => `${clock(item.averagePace)} avg · ${item.drivers?.join("/") || ""}`,
    empty: "Team pace unavailable for this race.",
    color: css("--ref"),
  });
  drawHorizontalRanking(els.sector1Chart, insights.fastestSectors?.sector1 || [], sectorChartOptions("time"));
  drawHorizontalRanking(els.sector2Chart, insights.fastestSectors?.sector2 || [], sectorChartOptions("time"));
  drawHorizontalRanking(els.sector3Chart, insights.fastestSectors?.sector3 || [], sectorChartOptions("time"));
  drawPaceTrend(insights.lapTimeTrend || [], insights.fuelPaceProxy || []);
  drawStintTimeline(insights.driverStints || [], race?.standings || [], race?.lapCount || 0);
  drawPitStopViolin(insights.pitStops || []);
}

function sectorChartOptions(valueKey) {
  return {
    labelKey: "driver",
    valueKey,
    meta: (item) => `L${item.lap ?? "--"} · ${clock(item.time)}${item.compound ? ` · ${item.compound}` : ""}`,
    empty: "Sector timing unavailable for this race.",
    color: css("--cmp"),
  };
}

function renderRaceInsightTables(insights) {
  const stints = (insights.driverStints || []).slice(0, 30);
  const pits = insights.pitStops || [];
  const tyres = insights.tyreCompounds || [];
  const notes = insights.notes || [];
  els.raceInsightTables.innerHTML = `
    <div class="insight-block">
      <h4>Tyre Compound Pace</h4>
      <table class="compact-table">
        <thead><tr><th>Compound</th><th>Avg</th><th>Best</th><th>Laps</th></tr></thead>
        <tbody>${tyres.map((item) => `<tr><td>${escapeHtml(item.compound)}</td><td>${clock(item.averagePace)}</td><td>${clock(item.bestLapTime)}</td><td>${item.lapCount}</td></tr>`).join("") || emptyRow(4)}</tbody>
      </table>
    </div>
    <div class="insight-block">
      <h4>Driver Stints</h4>
      <table class="compact-table">
        <thead><tr><th>Driver</th><th>Stint</th><th>Tyre</th><th>Laps</th><th>Avg</th></tr></thead>
        <tbody>${stints.map((item) => `<tr><td>${escapeHtml(item.driver)}</td><td>${item.stint}</td><td>${escapeHtml(item.compound || "--")}</td><td>${item.startLap ?? "--"}-${item.endLap ?? "--"}</td><td>${clock(item.averagePace)}</td></tr>`).join("") || emptyRow(5)}</tbody>
      </table>
    </div>
    <div class="insight-block">
      <h4>Pit Stops</h4>
      <table class="compact-table">
        <thead><tr><th>Driver</th><th>Lap</th><th>Tyre</th><th>Lane</th></tr></thead>
        <tbody>${pits.map((item) => `<tr><td>${escapeHtml(item.driver)}</td><td>${item.lap ?? "--"}</td><td>${escapeHtml([item.compoundBefore, item.compoundAfter].filter(Boolean).join(" → ") || "--")}</td><td>${item.pitLaneTime ? `${item.pitLaneTime.toFixed(2)} s` : "--"}</td></tr>`).join("") || emptyRow(4)}</tbody>
      </table>
    </div>
    <ul class="insight-notes">${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>`;
}

function emptyRow(columns) {
  return `<tr><td colspan="${columns}">No data available.</td></tr>`;
}

function drawStintTimeline(stints, standings, lapCount) {
  const canvas = els.stintTimelineChart;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);
  const items = stints.filter((item) => isFiniteNumber(item.startLap) && isFiniteNumber(item.endLap));
  if (!items.length) {
    drawEmpty(ctx, "Tyre stint timeline unavailable for this race.");
    return;
  }

  const drivers = orderedStintDrivers(items, standings);
  const maxLap = Math.max(lapCount || 0, ...items.map((item) => item.endLap));
  const pad = { left: 58, right: 20, top: 34, bottom: 38 };
  const rowH = Math.max(17, (h - pad.top - pad.bottom) / drivers.length);
  const barH = Math.max(9, Math.min(18, rowH * 0.58));
  const hitboxes = [];

  ctx.strokeStyle = "#d8dfdc";
  ctx.fillStyle = "#63706c";
  ctx.font = "12px Inter, sans-serif";
  ctx.strokeRect(pad.left, pad.top, w - pad.left - pad.right, h - pad.top - pad.bottom);
  for (let lap = 1; lap <= maxLap; lap += Math.max(1, Math.ceil(maxLap / 8))) {
    const x = scale(lap, 1, maxLap, pad.left, w - pad.right);
    ctx.fillStyle = "#63706c";
    ctx.fillText(String(lap), Math.min(w - pad.right - 12, x - 4), h - 12);
    ctx.strokeStyle = "#edf1ef";
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, h - pad.bottom);
    ctx.stroke();
  }

  drivers.forEach((driver, driverIndex) => {
    const y = pad.top + driverIndex * rowH + rowH * 0.5;
    ctx.fillStyle = "#26312e";
    ctx.fillText(driver, 12, y + 4);
    items
      .filter((item) => item.driver === driver)
      .forEach((stint) => {
        const x1 = scale(stint.startLap, 1, maxLap, pad.left, w - pad.right);
        const x2 = scale(stint.endLap + 1, 1, maxLap + 1, pad.left, w - pad.right);
        const width = Math.max(3, x2 - x1);
        const y1 = y - barH / 2;
        const compound = String(stint.compound || "UNKNOWN").toUpperCase();
        ctx.fillStyle = tyreColor(compound);
        ctx.fillRect(x1, y1, width, barH);
        ctx.strokeStyle = "rgba(38, 49, 46, 0.32)";
        ctx.strokeRect(x1, y1, width, barH);
        if (width > 28) {
          ctx.fillStyle = compound === "HARD" ? "#17211e" : "#ffffff";
          ctx.font = "11px Inter, sans-serif";
          ctx.fillText(`${stint.laps}L`, x1 + 5, y1 + barH - 4);
          ctx.font = "12px Inter, sans-serif";
        }
        hitboxes.push({ x1, x2, y1, y2: y1 + barH, stint });
      });
  });

  drawTyreLegend(ctx, pad.left + 8, pad.top - 16, w - pad.left - pad.right - 16);
  canvas._stintTimelinePlot = { hitboxes, stints: items, standings, lapCount: maxLap, pad };
  if (stintHoverIndex !== null && hitboxes[stintHoverIndex]) {
    drawStintHover(ctx, hitboxes[stintHoverIndex]);
  }
}

function orderedStintDrivers(stints, standings) {
  const byDriver = new Set(stints.map((item) => item.driver));
  const ordered = standings
    .map((item) => item.driver)
    .filter((driver) => driver && byDriver.has(driver));
  [...byDriver]
    .filter((driver) => !ordered.includes(driver))
    .sort()
    .forEach((driver) => ordered.push(driver));
  return ordered;
}

function tyreColor(compound) {
  const colors = {
    SOFT: "#d23b3b",
    MEDIUM: "#d6a51d",
    HARD: "#f4f6f4",
    INTERMEDIATE: "#2fa665",
    WET: "#2f5fca",
    UNKNOWN: "#8c9894",
  };
  return colors[compound] || colors.UNKNOWN;
}

function drawTyreLegend(ctx, x, y, maxWidth) {
  const compact = maxWidth < 560;
  const items = compact
    ? [
        ["SOFT", "S"],
        ["MEDIUM", "M"],
        ["HARD", "H"],
        ["INTERMEDIATE", "INT"],
        ["WET", "W"],
      ]
    : [
        ["SOFT", "SOFT"],
        ["MEDIUM", "MEDIUM"],
        ["HARD", "HARD"],
        ["INTERMEDIATE", "INTER"],
        ["WET", "WET"],
      ];
  ctx.save();
  ctx.font = "11px Inter, sans-serif";
  const itemW = compact ? 52 : 86;
  items.forEach(([compound, label], index) => {
    const itemX = x + index * itemW;
    ctx.fillStyle = tyreColor(compound);
    ctx.fillRect(itemX, y, 18, 9);
    ctx.strokeStyle = "rgba(38, 49, 46, 0.35)";
    ctx.strokeRect(itemX, y, 18, 9);
    ctx.fillStyle = "#63706c";
    ctx.fillText(label, itemX + 23, y + 9);
  });
  ctx.restore();
}

function updateStintHover(event) {
  const plot = els.stintTimelineChart._stintTimelinePlot;
  if (!plot?.hitboxes?.length) return;
  const rect = els.stintTimelineChart.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const index = plot.hitboxes.findIndex((box) => x >= box.x1 && x <= box.x2 && y >= box.y1 - 3 && y <= box.y2 + 3);
  if (index === -1) {
    stintHoverIndex = null;
    els.stintTooltip.hidden = true;
    drawStintTimeline(plot.stints, plot.standings, plot.lapCount);
    return;
  }
  stintHoverIndex = index;
  drawStintTimeline(plot.stints, plot.standings, plot.lapCount);
  renderStintTooltip(event, plot.hitboxes[index].stint);
}

function clearStintHover() {
  stintHoverIndex = null;
  els.stintTooltip.hidden = true;
  const insights = currentRace?.raceInsights || {};
  if (insights.driverStints) drawStintTimeline(insights.driverStints, currentRace?.standings || [], currentRace?.lapCount || 0);
}

function renderStintTooltip(event, stint) {
  const rows = [
    ["Driver", stint.driver],
    ["Compound", stint.compound || "--"],
    ["Lap range", `${stint.startLap}-${stint.endLap}`],
    ["Stint length", `${stint.laps} laps`],
    ["Average pace", clock(stint.averagePace)],
    ["Best lap", clock(stint.bestLapTime)],
  ];
  els.stintTooltip.innerHTML = rows
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const panelRect = els.stintTimelineChart.closest(".chart-surface").getBoundingClientRect();
  const tipWidth = 250;
  const maxLeft = Math.max(10, panelRect.width - tipWidth - 10);
  const maxTop = Math.max(10, panelRect.height - 178);
  const left = Math.min(Math.max(10, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(10, event.clientY - panelRect.top + 14), maxTop);
  els.stintTooltip.style.left = `${left}px`;
  els.stintTooltip.style.top = `${top}px`;
  els.stintTooltip.hidden = false;
}

function drawStintHover(ctx, box) {
  ctx.save();
  ctx.strokeStyle = "#17211e";
  ctx.lineWidth = 2;
  ctx.strokeRect(box.x1 - 1, box.y1 - 1, box.x2 - box.x1 + 2, box.y2 - box.y1 + 2);
  ctx.restore();
}

function drawPitStopViolin(pitStops) {
  const canvas = els.pitStopChart;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);
  const teams = pitStopTeams(pitStops);
  if (!teams.length) {
    drawEmpty(ctx, "Pit stop timing unavailable for this race.");
    return;
  }

  const allTimes = teams.flatMap((team) => team.stops.map((stop) => stop.pitLaneTime).filter(isFiniteNumber));
  const minTime = Math.max(0, Math.min(...allTimes) - 1.0);
  const maxTime = Math.max(...allTimes) + 1.0;
  const pad = { left: 54, right: 18, top: 38, bottom: 74 };
  const plotW = w - pad.left - pad.right;
  const columnW = plotW / teams.length;
  const hitboxes = [];

  ctx.fillStyle = "#26312e";
  ctx.font = "700 13px Inter, sans-serif";
  ctx.fillText("Pit stop lane time by team", pad.left, 20);
  ctx.strokeStyle = "#d8dfdc";
  ctx.fillStyle = "#63706c";
  ctx.font = "12px Inter, sans-serif";
  ctx.strokeRect(pad.left, pad.top, plotW, h - pad.top - pad.bottom);

  const step = Math.max(1, (maxTime - minTime) / 5);
  for (let time = minTime; time <= maxTime + 0.001; time += step) {
    const y = scale(time, minTime, maxTime, h - pad.bottom, pad.top);
    ctx.fillStyle = "#63706c";
    ctx.fillText(`${time.toFixed(1)}s`, 10, y + 4);
    ctx.strokeStyle = "#edf1ef";
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.stroke();
  }

  teams.forEach((team, index) => {
    const times = team.stops.map((stop) => stop.pitLaneTime).filter(isFiniteNumber).sort((a, b) => a - b);
    const x = pad.left + columnW * index + columnW / 2;
    const maxHalf = Math.max(5, columnW * 0.34);
    const bins = densityBins(times, minTime, maxTime, 18);
    const maxDensity = Math.max(...bins.map((bin) => bin.count), 1);

    ctx.beginPath();
    bins.forEach((bin, binIndex) => {
      const y = scale(bin.center, minTime, maxTime, h - pad.bottom, pad.top);
      const half = Math.max(2, (bin.count / maxDensity) * maxHalf);
      if (binIndex === 0) ctx.moveTo(x - half, y);
      else ctx.lineTo(x - half, y);
    });
    [...bins].reverse().forEach((bin) => {
      const y = scale(bin.center, minTime, maxTime, h - pad.bottom, pad.top);
      const half = Math.max(2, (bin.count / maxDensity) * maxHalf);
      ctx.lineTo(x + half, y);
    });
    ctx.closePath();
    ctx.fillStyle = "rgba(10, 124, 134, 0.18)";
    ctx.fill();
    ctx.strokeStyle = css("--ref");
    ctx.lineWidth = 1.5;
    ctx.stroke();

    team.stops.forEach((stop, stopIndex) => {
      const jitter = ((stopIndex % 5) - 2) * Math.min(5, maxHalf / 5);
      const y = scale(stop.pitLaneTime, minTime, maxTime, h - pad.bottom, pad.top);
      ctx.fillStyle = css("--cmp");
      ctx.beginPath();
      ctx.arc(x + jitter, y, 2.6, 0, Math.PI * 2);
      ctx.fill();
    });

    const avgY = scale(team.average, minTime, maxTime, h - pad.bottom, pad.top);
    ctx.strokeStyle = css("--loss");
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x - maxHalf, avgY);
    ctx.lineTo(x + maxHalf, avgY);
    ctx.stroke();

    ctx.save();
    ctx.translate(x - 4, h - 48);
    ctx.rotate(-Math.PI / 4);
    ctx.fillStyle = "#26312e";
    ctx.fillText(team.team, 0, 0);
    ctx.restore();

    hitboxes.push({
      team,
      x1: pad.left + columnW * index,
      x2: pad.left + columnW * (index + 1),
      y1: pad.top,
      y2: h - pad.bottom,
      x,
      avgY,
      maxHalf,
    });
  });

  canvas._pitStopPlot = { pitStops, teams, hitboxes };
  if (pitStopHoverIndex !== null && hitboxes[pitStopHoverIndex]) {
    drawPitStopHover(ctx, hitboxes[pitStopHoverIndex]);
  }
}

function pitStopTeams(pitStops) {
  const groups = new Map();
  (pitStops || [])
    .filter((stop) => stop.team && isFiniteNumber(stop.pitLaneTime))
    .forEach((stop) => {
      if (!groups.has(stop.team)) groups.set(stop.team, []);
      groups.get(stop.team).push(stop);
    });
  return [...groups.entries()]
    .map(([team, stops]) => {
      const times = stops.map((stop) => stop.pitLaneTime).filter(isFiniteNumber).sort((a, b) => a - b);
      return {
        team,
        stops: stops.sort((a, b) => (a.pitLaneTime || 999) - (b.pitLaneTime || 999)),
        average: average(times),
        median: median(times),
        best: times[0],
        worst: times[times.length - 1],
      };
    })
    .sort((a, b) => a.average - b.average);
}

function updatePitStopHover(event) {
  const plot = els.pitStopChart._pitStopPlot;
  if (!plot?.hitboxes?.length) return;
  const rect = els.pitStopChart.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const index = plot.hitboxes.findIndex((box) => x >= box.x1 && x <= box.x2 && y >= box.y1 && y <= box.y2 + 44);
  if (index === -1) {
    pitStopHoverIndex = null;
    els.pitStopTooltip.hidden = true;
    drawPitStopViolin(plot.pitStops);
    return;
  }
  pitStopHoverIndex = index;
  drawPitStopViolin(plot.pitStops);
  renderPitStopTooltip(event, plot.hitboxes[index].team);
}

function clearPitStopHover() {
  pitStopHoverIndex = null;
  els.pitStopTooltip.hidden = true;
  const insights = currentRace?.raceInsights || {};
  if (insights.pitStops) drawPitStopViolin(insights.pitStops);
}

function renderPitStopTooltip(event, team) {
  const stopRows = team.stops.map((stop) => {
    const tyre = [stop.compoundBefore, stop.compoundAfter].filter(Boolean).join(" → ") || "--";
    return `<div><span>${escapeHtml(stop.driver)} L${stop.lap ?? "--"}</span><strong>${num(stop.pitLaneTime, 2)} s · ${escapeHtml(tyre)}</strong></div>`;
  });
  els.pitStopTooltip.innerHTML = `
    <div><span>Team</span><strong>${escapeHtml(team.team)}</strong></div>
    <div><span>Average</span><strong>${num(team.average, 2)} s</strong></div>
    <div><span>Median</span><strong>${num(team.median, 2)} s</strong></div>
    <div><span>Best / worst</span><strong>${num(team.best, 2)} s / ${num(team.worst, 2)} s</strong></div>
    ${stopRows.join("")}`;

  const panelRect = els.pitStopChart.closest(".chart-surface").getBoundingClientRect();
  const tipWidth = 300;
  const maxLeft = Math.max(10, panelRect.width - tipWidth - 10);
  const maxTop = Math.max(10, panelRect.height - 300);
  const left = Math.min(Math.max(10, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(10, event.clientY - panelRect.top + 14), maxTop);
  els.pitStopTooltip.style.left = `${left}px`;
  els.pitStopTooltip.style.top = `${top}px`;
  els.pitStopTooltip.hidden = false;
}

function drawPitStopHover(ctx, box) {
  ctx.save();
  ctx.fillStyle = "rgba(10, 124, 134, 0.08)";
  ctx.fillRect(box.x1 + 1, box.y1, box.x2 - box.x1 - 2, box.y2 - box.y1);
  ctx.strokeStyle = "#17211e";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(box.x1 + 1, box.y1, box.x2 - box.x1 - 2, box.y2 - box.y1);
  ctx.strokeStyle = css("--loss");
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(box.x - box.maxHalf, box.avgY);
  ctx.lineTo(box.x + box.maxHalf, box.avgY);
  ctx.stroke();
  ctx.restore();
}

function drawPaceViolin(drivers) {
  const canvas = els.paceViolinChart;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);
  const data = drivers.filter((driver) => driver.laps?.length).slice(0, 20);
  if (!data.length) {
    drawEmpty(ctx, "Driver pace distribution unavailable for this race.");
    return;
  }

  const allTimes = data.flatMap((driver) => driver.laps.map((lap) => lap.time).filter(isFiniteNumber));
  const minTime = Math.min(...allTimes) - 0.2;
  const maxTime = Math.max(...allTimes) + 0.2;
  const pad = { left: 54, right: 18, top: 26, bottom: 72 };
  const plotW = w - pad.left - pad.right;
  const columnW = plotW / data.length;
  const hitboxes = [];

  ctx.strokeStyle = "#d8dfdc";
  ctx.fillStyle = "#63706c";
  ctx.font = "12px Inter, sans-serif";
  ctx.strokeRect(pad.left, pad.top, plotW, h - pad.top - pad.bottom);
  for (let tick = minTime; tick <= maxTime; tick += Math.max(0.5, (maxTime - minTime) / 6)) {
    const y = scale(tick, minTime, maxTime, h - pad.bottom, pad.top);
    ctx.fillText(clock(tick), 8, y + 4);
    ctx.strokeStyle = "#edf1ef";
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.stroke();
  }

  data.forEach((driver, index) => {
    const times = driver.laps.map((lap) => lap.time).filter(isFiniteNumber).sort((a, b) => a - b);
    const x = pad.left + columnW * index + columnW / 2;
    const maxHalf = Math.max(5, columnW * 0.35);
    const bins = densityBins(times, minTime, maxTime, 22);
    const maxDensity = Math.max(...bins.map((bin) => bin.count), 1);

    ctx.beginPath();
    bins.forEach((bin, binIndex) => {
      const y = scale(bin.center, minTime, maxTime, h - pad.bottom, pad.top);
      const half = Math.max(2, (bin.count / maxDensity) * maxHalf);
      if (binIndex === 0) ctx.moveTo(x - half, y);
      else ctx.lineTo(x - half, y);
    });
    [...bins].reverse().forEach((bin) => {
      const y = scale(bin.center, minTime, maxTime, h - pad.bottom, pad.top);
      const half = Math.max(2, (bin.count / maxDensity) * maxHalf);
      ctx.lineTo(x + half, y);
    });
    ctx.closePath();
    ctx.fillStyle = "rgba(10, 124, 134, 0.18)";
    ctx.fill();
    ctx.strokeStyle = css("--ref");
    ctx.lineWidth = 1.5;
    ctx.stroke();

    const avgY = scale(driver.averagePace, minTime, maxTime, h - pad.bottom, pad.top);
    const bestY = scale(driver.bestLapTime, minTime, maxTime, h - pad.bottom, pad.top);
    const stdTopY = isFiniteNumber(driver.stdDev) ? scale(driver.averagePace - driver.stdDev, minTime, maxTime, h - pad.bottom, pad.top) : null;
    const stdBottomY = isFiniteNumber(driver.stdDev) ? scale(driver.averagePace + driver.stdDev, minTime, maxTime, h - pad.bottom, pad.top) : null;
    if (stdTopY !== null && stdBottomY !== null && driver.stdDev > 0) {
      ctx.fillStyle = "rgba(185, 45, 43, 0.08)";
      ctx.fillRect(x - maxHalf * 0.72, stdTopY, maxHalf * 1.44, stdBottomY - stdTopY);
      ctx.strokeStyle = "rgba(185, 45, 43, 0.45)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x - maxHalf * 0.62, stdTopY);
      ctx.lineTo(x + maxHalf * 0.62, stdTopY);
      ctx.moveTo(x - maxHalf * 0.62, stdBottomY);
      ctx.lineTo(x + maxHalf * 0.62, stdBottomY);
      ctx.stroke();
    }
    ctx.strokeStyle = css("--cmp");
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x - maxHalf, avgY);
    ctx.lineTo(x + maxHalf, avgY);
    ctx.stroke();
    ctx.fillStyle = css("--gain");
    ctx.beginPath();
    ctx.arc(x, bestY, 3, 0, Math.PI * 2);
    ctx.fill();

    ctx.save();
    ctx.translate(x - 4, h - 48);
    ctx.rotate(-Math.PI / 4);
    ctx.fillStyle = "#26312e";
    ctx.fillText(driver.driver, 0, 0);
    ctx.restore();

    hitboxes.push({
      driver,
      x1: pad.left + columnW * index,
      x2: pad.left + columnW * (index + 1),
      y1: pad.top,
      y2: h - pad.bottom,
      x,
      avgY,
      bestY,
      maxHalf,
    });
  });

  canvas._paceViolinPlot = { drivers, data, hitboxes };
  if (paceViolinHoverIndex !== null && hitboxes[paceViolinHoverIndex]) {
    drawPaceViolinHover(ctx, hitboxes[paceViolinHoverIndex], h);
  }
}

function updatePaceViolinHover(event) {
  const plot = els.paceViolinChart._paceViolinPlot;
  if (!plot?.hitboxes?.length) return;
  const rect = els.paceViolinChart.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const index = plot.hitboxes.findIndex((box) => x >= box.x1 && x <= box.x2 && y >= box.y1 && y <= box.y2 + 42);
  if (index === -1) {
    paceViolinHoverIndex = null;
    els.paceViolinTooltip.hidden = true;
    drawPaceViolin(plot.drivers);
    return;
  }
  paceViolinHoverIndex = index;
  drawPaceViolin(plot.drivers);
  renderPaceViolinTooltip(event, plot.hitboxes[index]);
}

function clearPaceViolinHover() {
  paceViolinHoverIndex = null;
  els.paceViolinTooltip.hidden = true;
  const insights = currentRace?.raceInsights || {};
  if (insights.driverPace) drawPaceViolin(insights.driverPace);
}

function renderPaceViolinTooltip(event, box) {
  const driver = box.driver;
  const rows = [
    ["Driver", driver.driver || "--"],
    ["Team", driver.team || "--"],
    ["Average pace", clock(driver.averagePace)],
    ["Median pace", clock(driver.medianPace)],
    ["Deviation", isFiniteNumber(driver.stdDev) ? `±${driver.stdDev.toFixed(3)} s` : "--"],
    ["Best lap", clock(driver.bestLapTime)],
    ["Worst lap", clock(driver.worstLapTime)],
    ["Clean laps", String(driver.lapCount ?? driver.laps?.length ?? "--")],
  ];
  els.paceViolinTooltip.innerHTML = rows
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const panelRect = els.paceViolinChart.closest(".chart-surface").getBoundingClientRect();
  const tipWidth = 270;
  const maxLeft = Math.max(10, panelRect.width - tipWidth - 10);
  const maxTop = Math.max(10, panelRect.height - 244);
  const left = Math.min(Math.max(10, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(10, event.clientY - panelRect.top + 14), maxTop);
  els.paceViolinTooltip.style.left = `${left}px`;
  els.paceViolinTooltip.style.top = `${top}px`;
  els.paceViolinTooltip.hidden = false;
}

function drawPaceViolinHover(ctx, box, height) {
  ctx.save();
  ctx.fillStyle = "rgba(10, 124, 134, 0.08)";
  ctx.fillRect(box.x1 + 1, box.y1, box.x2 - box.x1 - 2, box.y2 - box.y1);
  ctx.strokeStyle = "#17211e";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(box.x1 + 1, box.y1, box.x2 - box.x1 - 2, box.y2 - box.y1);
  ctx.strokeStyle = css("--cmp");
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(box.x - box.maxHalf, box.avgY);
  ctx.lineTo(box.x + box.maxHalf, box.avgY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#17211e";
  ctx.font = "700 12px Inter, sans-serif";
  ctx.fillText("avg", Math.min(box.x + box.maxHalf + 4, ctx.canvas.width - 34), box.avgY + 4);
  ctx.restore();
}

function densityBins(values, min, max, count) {
  const width = (max - min) / count || 1;
  const bins = Array.from({ length: count }, (_, index) => ({ center: min + width * (index + 0.5), count: 0 }));
  values.forEach((value) => {
    const index = Math.max(0, Math.min(count - 1, Math.floor((value - min) / width)));
    bins[index].count += 1;
  });
  return bins;
}

function drawHorizontalRanking(canvas, items, options) {
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);
  const data = items.filter((item) => isFiniteNumber(item[options.valueKey])).slice(0, 14);
  if (!data.length) {
    drawEmpty(ctx, options.empty);
    return;
  }
  const values = data.map((item) => item[options.valueKey]);
  const best = Math.min(...values);
  const worst = Math.max(...values);
  const showMeta = w >= 640;
  const metaW = showMeta ? Math.min(230, Math.max(170, w * 0.24)) : 0;
  const pad = { left: w < 560 ? 112 : 126, right: 18, top: 20, bottom: 18 };
  const plotRight = w - pad.right - metaW;
  const metaX = plotRight + 18;
  const rowH = Math.max(20, (h - pad.top - pad.bottom) / data.length);
  ctx.font = "12px Inter, sans-serif";
  const hitboxes = [];

  if (showMeta) {
    ctx.fillStyle = "rgba(255, 255, 255, 0.86)";
    ctx.fillRect(plotRight + 4, 0, metaW + pad.right, h);
    ctx.strokeStyle = "#e5ebe8";
    ctx.beginPath();
    ctx.moveTo(plotRight + 4, pad.top);
    ctx.lineTo(plotRight + 4, h - pad.bottom);
    ctx.stroke();
  }

  data.forEach((item, index) => {
    const y = pad.top + index * rowH + rowH * 0.25;
    const delta = item[options.valueKey] - best;
    const barW = scale(item[options.valueKey], best, worst || best + 1, plotRight - pad.left, 18);
    ctx.fillStyle = "#26312e";
    ctx.fillText(clipLabel(ctx, item[options.labelKey] || "--", pad.left - 18), 12, y + rowH * 0.45);
    ctx.fillStyle = index === 0 ? css("--gain") : options.color;
    ctx.fillRect(pad.left, y, Math.max(8, barW), Math.max(10, rowH * 0.45));
    const valueLabel = index === 0 ? clock(item[options.valueKey]) : `+${delta.toFixed(3)} s`;
    const valueX = pad.left + Math.max(12, barW) + 8;
    if (valueX > plotRight - 82) {
      ctx.save();
      ctx.textAlign = "right";
      ctx.fillStyle = "#ffffff";
      ctx.fillText(valueLabel, plotRight - 8, y + rowH * 0.35);
      ctx.restore();
    } else {
      ctx.fillStyle = "#63706c";
      ctx.fillText(valueLabel, valueX, y + rowH * 0.35);
    }
    if (showMeta) {
      ctx.fillStyle = "#63706c";
      ctx.fillText(clipLabel(ctx, options.meta(item), w - metaX - 8), metaX, y + rowH * 0.35);
    }
    hitboxes.push({ x1: pad.left, x2: pad.left + Math.max(8, barW), y1: y, y2: y + Math.max(10, rowH * 0.45), item, delta });
  });
  canvas._horizontalRankingPlot = { hitboxes, items: data, options };
  if (canvas === els.teamPaceChart && teamPaceHoverIndex !== null && hitboxes[teamPaceHoverIndex]) {
    drawRankingHover(ctx, hitboxes[teamPaceHoverIndex]);
  }
}

function updateTeamPaceHover(event) {
  const plot = els.teamPaceChart._horizontalRankingPlot;
  if (!plot?.hitboxes?.length) return;
  const rect = els.teamPaceChart.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const index = plot.hitboxes.findIndex((box) => x >= box.x1 && x <= box.x2 && y >= box.y1 - 4 && y <= box.y2 + 4);
  if (index === -1) {
    teamPaceHoverIndex = null;
    els.teamPaceTooltip.hidden = true;
    drawHorizontalRanking(els.teamPaceChart, plot.items, plot.options);
    return;
  }
  teamPaceHoverIndex = index;
  drawHorizontalRanking(els.teamPaceChart, plot.items, plot.options);
  renderTeamPaceTooltip(event, plot.hitboxes[index]);
}

function clearTeamPaceHover() {
  teamPaceHoverIndex = null;
  els.teamPaceTooltip.hidden = true;
  const insights = currentRace?.raceInsights || {};
  if (insights.teamPace) {
    drawHorizontalRanking(els.teamPaceChart, insights.teamPace, {
      labelKey: "team",
      valueKey: "averagePace",
      meta: (item) => `${clock(item.averagePace)} avg · ${item.drivers?.join("/") || ""}`,
      empty: "Team pace unavailable for this race.",
      color: css("--ref"),
    });
  }
}

function renderTeamPaceTooltip(event, box) {
  const item = box.item;
  const rows = [
    ["Team", item.team || "--"],
    ["Average pace", clock(item.averagePace)],
    ["Median pace", clock(item.medianPace)],
    ["Best lap", clock(item.bestLapTime)],
    ["Delta to best", box.delta === 0 ? "Fastest team" : `+${box.delta.toFixed(3)} s`],
    ["Drivers", (item.drivers || []).join(" / ") || "--"],
    ["Laps", String(item.lapCount ?? "--")],
  ];
  els.teamPaceTooltip.innerHTML = rows
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const panelRect = els.teamPaceChart.closest(".chart-surface").getBoundingClientRect();
  const tipWidth = 270;
  const maxLeft = Math.max(10, panelRect.width - tipWidth - 10);
  const maxTop = Math.max(10, panelRect.height - 210);
  const left = Math.min(Math.max(10, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(10, event.clientY - panelRect.top + 14), maxTop);
  els.teamPaceTooltip.style.left = `${left}px`;
  els.teamPaceTooltip.style.top = `${top}px`;
  els.teamPaceTooltip.hidden = false;
}

function drawRankingHover(ctx, box) {
  ctx.save();
  ctx.strokeStyle = "#17211e";
  ctx.lineWidth = 2;
  ctx.strokeRect(box.x1 - 1, box.y1 - 1, box.x2 - box.x1 + 2, box.y2 - box.y1 + 2);
  ctx.restore();
}

function clipLabel(ctx, value, maxWidth) {
  const text = String(value ?? "--");
  if (ctx.measureText(text).width <= maxWidth) return text;
  let clipped = text;
  while (clipped.length > 2 && ctx.measureText(`${clipped}...`).width > maxWidth) {
    clipped = clipped.slice(0, -1);
  }
  return `${clipped}...`;
}

function drawPaceTrend(trend, fuelProxy) {
  const canvas = els.paceTrendChart;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);
  const data = trend.filter((item) => isFiniteNumber(item.lap) && isFiniteNumber(item.medianTime));
  if (!data.length) {
    drawEmpty(ctx, "Race pace trend unavailable for this race.");
    return;
  }
  const pad = { left: 72, right: 28, top: 34, bottom: 46 };
  const minLap = Math.min(...data.map((item) => item.lap));
  const maxLap = Math.max(...data.map((item) => item.lap));
  const minTime = Math.min(...data.map((item) => item.bestTime)) - 0.3;
  const maxTime = Math.max(...data.map((item) => item.medianTime)) + 0.3;
  canvas._paceTrendPlot = { data, fuelProxy, minLap, maxLap, minTime, maxTime, pad };

  ctx.strokeStyle = "#d8dfdc";
  ctx.fillStyle = "#63706c";
  ctx.font = "12px Inter, sans-serif";
  ctx.strokeRect(pad.left, pad.top, w - pad.left - pad.right, h - pad.top - pad.bottom);

  const timeStep = Math.max(0.5, (maxTime - minTime) / 6);
  for (let time = minTime; time <= maxTime + 0.001; time += timeStep) {
    const y = scale(time, minTime, maxTime, h - pad.bottom, pad.top);
    ctx.fillStyle = "#63706c";
    ctx.fillText(clock(time), 10, y + 4);
    ctx.strokeStyle = "#edf1ef";
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.stroke();
  }

  for (let lap = minLap; lap <= maxLap; lap += Math.max(1, Math.ceil((maxLap - minLap) / 8))) {
    const x = scale(lap, minLap, maxLap, pad.left, w - pad.right);
    ctx.fillStyle = "#63706c";
    ctx.fillText(String(lap), x - 4, h - 12);
  }

  drawLine(ctx, data, "medianTime", minLap, maxLap, minTime, maxTime, pad, css("--ref"));
  drawLine(ctx, data, "bestTime", minLap, maxLap, minTime, maxTime, pad, css("--gain"));
  drawInlineLegend(ctx, pad.left + 12, pad.top + 18, [
    ["Median field pace", css("--ref")],
    ["Best clean lap", css("--gain")],
  ]);

  if (paceTrendHoverIndex !== null) {
    drawPaceTrendHover(ctx, canvas._paceTrendPlot, paceTrendHoverIndex);
  }
}

function drawLine(ctx, data, key, minLap, maxLap, minTime, maxTime, pad, color) {
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.3;
  data.forEach((item, index) => {
    const x = scale(item.lap, minLap, maxLap, pad.left, ctx.canvas.width - pad.right);
    const y = scale(item[key], minTime, maxTime, ctx.canvas.height - pad.bottom, pad.top);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawEmpty(ctx, message) {
  ctx.fillStyle = css("--muted");
  ctx.font = "13px Inter, sans-serif";
  ctx.fillText(message, 22, 34);
}

function drawInlineLegend(ctx, x, y, items) {
  ctx.save();
  ctx.font = "12px Inter, sans-serif";
  items.forEach(([label, color], index) => {
    const itemX = x + index * 150;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(itemX, y);
    ctx.lineTo(itemX + 20, y);
    ctx.stroke();
    ctx.fillStyle = "#26312e";
    ctx.fillText(label, itemX + 26, y + 4);
  });
  ctx.restore();
}

function updatePaceTrendHover(event) {
  const plot = els.paceTrendChart._paceTrendPlot;
  if (!plot?.data?.length) return;
  const rect = els.paceTrendChart.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const minX = plot.pad.left;
  const maxX = Math.max(minX + 1, rect.width - plot.pad.right);
  const clampedX = Math.max(minX, Math.min(maxX, x));
  const lap = scale(clampedX, minX, maxX, plot.minLap, plot.maxLap);
  paceTrendHoverIndex = nearestIndex(plot.data.map((item) => item.lap), lap);
  drawPaceTrend(plot.data, plot.fuelProxy || []);
  renderPaceTrendTooltip(event, plot, paceTrendHoverIndex);
}

function clearPaceTrendHover() {
  paceTrendHoverIndex = null;
  els.paceTrendTooltip.hidden = true;
  const insights = currentRace?.raceInsights || {};
  if (insights.lapTimeTrend) drawPaceTrend(insights.lapTimeTrend, insights.fuelPaceProxy || []);
}

function renderPaceTrendTooltip(event, plot, index) {
  const item = plot?.data?.[index];
  if (!item) return;
  const nearestProxy = nearestFuelProxyForLap(plot.fuelProxy || [], item.lap);
  const rows = [
    ["Lap", String(item.lap)],
    ["Median field pace", clock(item.medianTime)],
    ["Best clean lap", clock(item.bestTime)],
    ["Average field pace", clock(item.averageTime)],
    ["Timed laps", String(item.lapCount ?? "--")],
    ["Fuel proxy", nearestProxy ? `${nearestProxy.driver} ${signed(nearestProxy.medianDelta, " s")}` : "No driver proxy nearby"],
  ];
  els.paceTrendTooltip.innerHTML = rows
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const panelRect = els.paceTrendChart.closest(".chart-surface").getBoundingClientRect();
  const tipWidth = 260;
  const maxLeft = Math.max(10, panelRect.width - tipWidth - 10);
  const maxTop = Math.max(10, panelRect.height - 190);
  const left = Math.min(Math.max(10, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(10, event.clientY - panelRect.top + 14), maxTop);
  els.paceTrendTooltip.style.left = `${left}px`;
  els.paceTrendTooltip.style.top = `${top}px`;
  els.paceTrendTooltip.hidden = false;
}

function nearestFuelProxyForLap(proxies, lap) {
  let best = null;
  let bestDelta = Infinity;
  proxies.forEach((proxy) => {
    (proxy.points || []).forEach((point) => {
      if (!isFiniteNumber(point.lap)) return;
      const delta = Math.abs(point.lap - lap);
      if (delta < bestDelta) {
        bestDelta = delta;
        best = proxy;
      }
    });
  });
  return best;
}

function drawPaceTrendHover(ctx, plot, index) {
  const item = plot?.data?.[index];
  if (!item) return;
  const x = scale(item.lap, plot.minLap, plot.maxLap, plot.pad.left, ctx.canvas.width - plot.pad.right);
  const medianY = scale(item.medianTime, plot.minTime, plot.maxTime, ctx.canvas.height - plot.pad.bottom, plot.pad.top);
  const bestY = scale(item.bestTime, plot.minTime, plot.maxTime, ctx.canvas.height - plot.pad.bottom, plot.pad.top);
  ctx.save();
  ctx.strokeStyle = "#17211e";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, plot.pad.top);
  ctx.lineTo(x, ctx.canvas.height - plot.pad.bottom);
  ctx.stroke();
  ctx.setLineDash([]);
  [
    [medianY, css("--ref")],
    [bestY, css("--gain")],
  ].forEach(([y, color]) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });
  ctx.restore();
}

function updateTraceHover(event) {
  if (!currentPayload?.telemetry?.Distance?.length) return;
  const t = currentPayload.telemetry;
  const rect = els.trace.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const minX = 48;
  const maxX = Math.max(minX + 1, rect.width - 18);
  const clampedX = Math.max(minX, Math.min(maxX, x));
  const distance = scale(clampedX, minX, maxX, minOf(t.Distance), maxOf(t.Distance));
  traceHoverIndex = nearestIndex(t.Distance, distance);
  renderCharts(currentPayload);
  renderTraceTooltip(event, traceHoverIndex);
}

function clearTraceHover() {
  traceHoverIndex = null;
  els.traceTooltip.hidden = true;
  if (currentPayload) renderCharts(currentPayload);
}

function renderTraceTooltip(event, index) {
  const t = currentPayload?.telemetry;
  const report = currentPayload?.report;
  if (!t || index === null || !report) return;
  const labels = telemetryLabels(report);
  const distance = t.Distance[index];
  const rows = [
    ["Distance", `${Math.round(distance)} m`],
    [labels.reference, `${num(t.ref_Speed[index], 1)} km/h · Th ${num(t.ref_Throttle[index], 0)}% · Br ${onOff(t.ref_Brake[index])}`],
    [labels.compared, `${num(t.cmp_Speed[index], 1)} km/h · Th ${num(t.cmp_Throttle[index], 0)}% · Br ${onOff(t.cmp_Brake[index])}`],
    ["Gear", `${roundValue(t.ref_nGear[index])} → ${roundValue(t.cmp_nGear[index])}`],
    ["RPM", `${num(t.ref_RPM[index], 0)} → ${num(t.cmp_RPM[index], 0)}`],
    ["DRS", `${drsState(t.ref_DRS[index])} → ${drsState(t.cmp_DRS[index])}`],
    ["Delta", seconds(t.delta_time[index])],
  ];
  els.traceTooltip.innerHTML = rows
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const panelRect = els.trace.closest(".trace-panel").getBoundingClientRect();
  const tipWidth = 330;
  const maxLeft = Math.max(12, panelRect.width - tipWidth - 12);
  const maxTop = Math.max(62, panelRect.height - 220);
  const left = Math.min(Math.max(12, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(62, event.clientY - panelRect.top + 12), maxTop);
  els.traceTooltip.style.left = `${left}px`;
  els.traceTooltip.style.top = `${top}px`;
  els.traceTooltip.hidden = false;
}

function drawPositionChart(race) {
  const canvas = els.positionChart;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);

  const history = orderPositionHistory(race?.positionHistory || [], race?.standings || []);
  if (!history.length) {
    ctx.fillStyle = css("--muted");
    ctx.font = "13px Inter, sans-serif";
    ctx.fillText("Position history unavailable for this race.", 22, 34);
    return;
  }

  const allLaps = history.flatMap((driver) => driver.laps || []);
  const maxLap = Math.max(...allLaps.map((item) => item.lap));
  const maxPosition = Math.max(...allLaps.map((item) => item.position), ...history.map((driver) => driver.finalPosition || 0));
  const pad = { left: 54, right: 130, top: 24, bottom: 38 };
  const colors = ["#0a7c86", "#d23b3b", "#2f5fca", "#157f4f", "#966014", "#6f4bb3", "#c35b8d", "#2f7670", "#7f6b21", "#59636f"];
  const driverColors = new Map(history.map((driver, index) => [driver.driver, colors[index % colors.length]]));

  ctx.strokeStyle = "#d8dfdc";
  ctx.fillStyle = "#63706c";
  ctx.font = "12px Inter, sans-serif";
  ctx.strokeRect(pad.left, pad.top, w - pad.left - pad.right, h - pad.top - pad.bottom);

  for (let pos = 1; pos <= maxPosition; pos += Math.max(1, Math.ceil(maxPosition / 10))) {
    const y = scale(pos, 1, maxPosition, pad.top + 8, h - pad.bottom - 8);
    ctx.fillText(`P${pos}`, 18, y + 4);
    ctx.strokeStyle = "#edf1ef";
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.stroke();
  }

  for (let lap = 1; lap <= maxLap; lap += Math.max(1, Math.ceil(maxLap / 8))) {
    const x = scale(lap, 1, maxLap, pad.left, w - pad.right);
    ctx.fillStyle = "#63706c";
    ctx.fillText(String(lap), x - 4, h - 12);
  }
  ctx.fillText("Lap", w - pad.right - 12, h - 12);

  history.forEach((driver, index) => {
    const laps = (driver.laps || []).filter((item) => isFiniteNumber(item.lap) && isFiniteNumber(item.position));
    if (laps.length < 2) return;
    const color = colors[index % colors.length];
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    laps.forEach((item, lapIndex) => {
      const x = scale(item.lap, 1, maxLap, pad.left, w - pad.right);
      const y = scale(item.position, 1, maxPosition, pad.top + 8, h - pad.bottom - 8);
      if (lapIndex === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const last = laps[laps.length - 1];
    const x = scale(last.lap, 1, maxLap, pad.left, w - pad.right);
    const y = scale(last.position, 1, maxPosition, pad.top + 8, h - pad.bottom - 8);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
    const labelY = scale(driver.finalPosition || last.position, 1, maxPosition, pad.top + 8, h - pad.bottom - 8);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x + 4, y);
    ctx.lineTo(w - pad.right + 8, labelY);
    ctx.stroke();
    ctx.fillText(driver.driver, w - pad.right + 14, labelY + 4);
  });

  canvas._positionPlot = { race, history, minLap: 1, maxLap, maxPosition, pad, driverColors };
  if (positionHoverLap !== null) {
    drawPositionHover(ctx, canvas._positionPlot, positionHoverLap);
  }
}

function updatePositionHover(event) {
  const plot = els.positionChart._positionPlot;
  if (!plot?.history?.length) return;
  const rect = els.positionChart.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const insideX = x >= plot.pad.left && x <= rect.width - plot.pad.right;
  const insideY = y >= plot.pad.top && y <= rect.height - plot.pad.bottom;
  if (!insideX || !insideY) {
    clearPositionHover();
    return;
  }
  const lap = Math.max(plot.minLap, Math.min(plot.maxLap, Math.round(scale(x, plot.pad.left, rect.width - plot.pad.right, plot.minLap, plot.maxLap))));
  positionHoverLap = lap;
  drawPositionChart(plot.race);
  renderPositionTooltip(event, els.positionChart._positionPlot, lap);
}

function clearPositionHover() {
  positionHoverLap = null;
  if (els.positionTooltip) els.positionTooltip.hidden = true;
  if (currentRace) drawPositionChart(currentRace);
}

function renderPositionTooltip(event, plot, lap) {
  if (!els.positionTooltip || !plot) return;
  const positions = positionsAtLap(plot.history, lap);
  if (!positions.length) {
    els.positionTooltip.hidden = true;
    return;
  }
  const rows = positions.slice(0, 12).map((item) => `<div>
    <span>P${item.position}</span>
    <strong>${escapeHtml(item.driver)}${item.team ? ` · ${escapeHtml(item.team)}` : ""}</strong>
  </div>`);
  const extra = positions.length > 12 ? `<div><span>More</span><strong>${positions.length - 12} drivers not shown</strong></div>` : "";
  els.positionTooltip.innerHTML = `<div><span>Lap</span><strong>${lap}</strong></div>${rows.join("")}${extra}`;

  const panelRect = els.positionChart.closest(".position-panel").getBoundingClientRect();
  const tipWidth = 260;
  const maxLeft = Math.max(10, panelRect.width - tipWidth - 10);
  const maxTop = Math.max(10, panelRect.height - 360);
  const left = Math.min(Math.max(10, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(62, event.clientY - panelRect.top + 14), maxTop);
  els.positionTooltip.style.left = `${left}px`;
  els.positionTooltip.style.top = `${top}px`;
  els.positionTooltip.hidden = false;
}

function drawPositionHover(ctx, plot, lap) {
  const { pad, maxLap, maxPosition, driverColors } = plot;
  const w = ctx.canvas.width;
  const h = ctx.canvas.height;
  const x = scale(lap, plot.minLap, maxLap, pad.left, w - pad.right);
  const positions = positionsAtLap(plot.history, lap);
  ctx.save();
  ctx.strokeStyle = "#17211e";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, pad.top);
  ctx.lineTo(x, h - pad.bottom);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#17211e";
  ctx.font = "700 12px Inter, sans-serif";
  ctx.fillText(`Lap ${lap}`, Math.min(x + 6, w - pad.right - 44), pad.top + 16);

  positions.forEach((item) => {
    const y = scale(item.position, 1, maxPosition, pad.top + 8, h - pad.bottom - 8);
    ctx.fillStyle = driverColors.get(item.driver) || css("--ref");
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1;
    ctx.stroke();
  });
  ctx.restore();
}

function positionsAtLap(history, lap) {
  return history
    .map((driver) => {
      const entry = nearestLapPosition(driver.laps || [], lap);
      if (!entry) return null;
      return {
        driver: driver.driver,
        team: driver.team,
        position: entry.position,
        lap: entry.lap,
      };
    })
    .filter(Boolean)
    .filter((item) => isFiniteNumber(item.position))
    .sort((a, b) => a.position - b.position || String(a.driver).localeCompare(String(b.driver)));
}

function nearestLapPosition(laps, lap) {
  const exact = laps.find((item) => item.lap === lap && isFiniteNumber(item.position));
  if (exact) return exact;
  const candidates = laps.filter((item) => isFiniteNumber(item.lap) && isFiniteNumber(item.position) && item.lap <= lap);
  if (!candidates.length) return null;
  return candidates[candidates.length - 1];
}

function orderPositionHistory(history, standings) {
  const byDriver = new Map(history.map((item) => [item.driver, item]));
  const ordered = [];
  standings
    .filter((item) => item.driver)
    .sort((a, b) => (a.position || 999) - (b.position || 999))
    .forEach((standing) => {
      const driverHistory = byDriver.get(standing.driver);
      if (!driverHistory) return;
      ordered.push({ ...driverHistory, finalPosition: standing.position || finalPositionFromLaps(driverHistory.laps) });
      byDriver.delete(standing.driver);
    });
  [...byDriver.values()]
    .sort((a, b) => finalPositionFromLaps(a.laps) - finalPositionFromLaps(b.laps))
    .forEach((item) => ordered.push({ ...item, finalPosition: finalPositionFromLaps(item.laps) }));
  return ordered;
}

function finalPositionFromLaps(laps = []) {
  const valid = laps.filter((item) => isFiniteNumber(item.position));
  if (!valid.length) return 999;
  return valid[valid.length - 1].position;
}

function telemetryLabels(report) {
  return {
    reference: `Reference: ${lapShort(report.reference)}`,
    compared: `Compared: ${lapShort(report.compared)}`,
  };
}

function drawTrace(t, sections) {
  const canvas = els.trace;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);
  if (!t?.Distance?.length) return;

  const panes = [
    { y: 22, h: 128, label: "Speed km/h", min: 0, max: maxOf(t.ref_Speed, t.cmp_Speed), ref: t.ref_Speed, cmp: t.cmp_Speed },
    { y: 166, h: 84, label: "Throttle %", min: 0, max: 100, ref: t.ref_Throttle, cmp: t.cmp_Throttle },
    { y: 266, h: 58, label: "Brake", min: 0, max: 1, ref: t.ref_Brake, cmp: t.cmp_Brake },
    { y: 340, h: 58, label: "Delta s", min: minOf(t.delta_time), max: maxOf(t.delta_time), delta: t.delta_time },
  ];

  sections.forEach((section) => {
    const x1 = scale(section.start_distance, minOf(t.Distance), maxOf(t.Distance), 48, w - 18);
    const x2 = scale(section.end_distance, minOf(t.Distance), maxOf(t.Distance), 48, w - 18);
    if (section.section_type.includes("braking")) {
      ctx.fillStyle = "rgba(210, 59, 59, 0.06)";
      ctx.fillRect(x1, 18, x2 - x1, h - 30);
    }
  });

  panes.forEach((pane) => {
    drawAxis(ctx, pane, w);
    if (pane.ref) drawSeries(ctx, t.Distance, pane.ref, pane, "var-ref");
    if (pane.cmp) drawSeries(ctx, t.Distance, pane.cmp, pane, "var-cmp");
    if (pane.delta) drawSeries(ctx, t.Distance, pane.delta, pane, "var-delta");
  });

  if (traceHoverIndex !== null) {
    drawTraceHover(ctx, t, panes, traceHoverIndex, w, h);
  }
}

function drawFindingTelemetry(canvas, t, detection, payload) {
  if (!canvas || !t?.Distance?.length) return;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);

  const pad = Math.max(20, (detection.end_distance - detection.start_distance) * 0.18);
  const start = Math.max(minOf(t.Distance), detection.start_distance - pad);
  const end = Math.min(maxOf(t.Distance), detection.end_distance + pad);
  const indices = t.Distance.map((distance, index) => ({ distance, index }))
    .filter((item) => item.distance >= start && item.distance <= end)
    .map((item) => item.index);
  if (indices.length < 3) return;

  const subset = sliceTelemetry(t, indices);
  const panes = [
    { y: 18, h: 102, label: "Speed km/h", min: minOf(subset.ref_Speed, subset.cmp_Speed), max: maxOf(subset.ref_Speed, subset.cmp_Speed), ref: subset.ref_Speed, cmp: subset.cmp_Speed },
    { y: 136, h: 76, label: "Throttle %", min: 0, max: 100, ref: subset.ref_Throttle, cmp: subset.cmp_Throttle },
    { y: 226, h: 48, label: "Brake", min: 0, max: 1, ref: subset.ref_Brake, cmp: subset.cmp_Brake },
    { y: 288, h: 50, label: "Delta s", min: minOf(subset.delta_time), max: maxOf(subset.delta_time), delta: subset.delta_time },
  ];

  const x1 = scale(detection.start_distance, start, end, 52, w - 18);
  const x2 = scale(detection.end_distance, start, end, 52, w - 18);
  ctx.fillStyle = detection.time_impact_seconds > 0 ? "rgba(185, 45, 43, 0.08)" : "rgba(21, 127, 79, 0.08)";
  ctx.fillRect(x1, 14, x2 - x1, h - 28);

  panes.forEach((pane) => {
    drawAxis(ctx, pane, w);
    if (pane.ref) drawSeries(ctx, subset.Distance, pane.ref, pane, "var-ref");
    if (pane.cmp) drawSeries(ctx, subset.Distance, pane.cmp, pane, "var-cmp");
    if (pane.delta) drawSeries(ctx, subset.Distance, pane.delta, pane, "var-delta");
  });

  drawTelemetryKey(ctx, w);
  drawDistanceMarker(ctx, x1, "start", h);
  drawDistanceMarker(ctx, x2, "end", h);
  canvas._findingTelemetryPlot = { payload, detection, start, end, indices };

  if (findingTelemetryHoverIndex !== null) {
    const subsetIndex = nearestIndex(subset.Distance, t.Distance[findingTelemetryHoverIndex]);
    drawTraceHover(ctx, subset, panes, subsetIndex, w, h);
  }
}

function updateFindingTelemetryHover(event) {
  const canvas = event.currentTarget;
  const plot = canvas._findingTelemetryPlot;
  const t = plot?.payload?.telemetry;
  if (!plot || !t?.Distance?.length) return;
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const minX = 52;
  const maxX = Math.max(minX + 1, rect.width - 18);
  const clampedX = Math.max(minX, Math.min(maxX, x));
  const distance = scale(clampedX, minX, maxX, plot.start, plot.end);
  const candidates = plot.indices?.length ? plot.indices : t.Distance.map((_, index) => index);
  findingTelemetryHoverIndex = nearestIndex(candidates.map((index) => t.Distance[index]), distance);
  findingTelemetryHoverIndex = candidates[findingTelemetryHoverIndex];
  drawFindingTelemetry(canvas, t, plot.detection, plot.payload);
  renderFindingTelemetryTooltip(event, plot.payload, findingTelemetryHoverIndex);
}

function clearFindingTelemetryHover(event) {
  const canvas = event.currentTarget;
  const plot = canvas._findingTelemetryPlot;
  findingTelemetryHoverIndex = null;
  const tooltip = document.querySelector("#finding-telemetry-tooltip");
  if (tooltip) tooltip.hidden = true;
  if (plot?.payload) drawFindingTelemetry(canvas, plot.payload.telemetry, plot.detection, plot.payload);
}

function renderFindingTelemetryTooltip(event, payload, index) {
  const t = payload?.telemetry;
  const report = payload?.report;
  const tooltip = document.querySelector("#finding-telemetry-tooltip");
  if (!t || !report || !tooltip || index === null) return;
  const labels = telemetryLabels(report);
  const rows = [
    ["Distance", `${Math.round(t.Distance[index])} m`],
    [labels.reference, `${num(t.ref_Speed[index], 1)} km/h · Th ${num(t.ref_Throttle[index], 0)}% · Br ${onOff(t.ref_Brake[index])}`],
    [labels.compared, `${num(t.cmp_Speed[index], 1)} km/h · Th ${num(t.cmp_Throttle[index], 0)}% · Br ${onOff(t.cmp_Brake[index])}`],
    ["Gear", `${roundValue(t.ref_nGear[index])} → ${roundValue(t.cmp_nGear[index])}`],
    ["RPM", `${num(t.ref_RPM[index], 0)} → ${num(t.cmp_RPM[index], 0)}`],
    ["DRS", `${drsState(t.ref_DRS[index])} → ${drsState(t.cmp_DRS[index])}`],
    ["Delta", seconds(t.delta_time[index])],
  ];
  tooltip.innerHTML = rows
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const panelRect = event.currentTarget.closest(".finding-telemetry-surface").getBoundingClientRect();
  const tipWidth = 330;
  const maxLeft = Math.max(10, panelRect.width - tipWidth - 10);
  const maxTop = Math.max(10, panelRect.height - 218);
  const left = Math.min(Math.max(10, event.clientX - panelRect.left + 14), maxLeft);
  const top = Math.min(Math.max(10, event.clientY - panelRect.top + 14), maxTop);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
  tooltip.hidden = false;
}

function drawMap(t, detections) {
  const canvas = els.map;
  const ctx = fitCanvas(canvas);
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  drawBackground(ctx, w, h);
  if (!t?.ref_X?.length) return;

  const xs = [...t.ref_X, ...t.cmp_X].filter(isFiniteNumber);
  const ys = [...t.ref_Y, ...t.cmp_Y].filter(isFiniteNumber);
  const bounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  drawPath(ctx, t.ref_X, t.ref_Y, bounds, w, h, css("--ref"), 3);
  drawPath(ctx, t.cmp_X, t.cmp_Y, bounds, w, h, css("--cmp"), 3);

  detections.slice(0, 10).forEach((detection) => {
    const index = nearestIndex(t.Distance, (detection.start_distance + detection.end_distance) / 2);
    const point = mapPoint(t.cmp_X[index], t.cmp_Y[index], bounds, w, h);
    ctx.beginPath();
    ctx.fillStyle = detection.time_impact_seconds > 0 ? css("--loss") : css("--gain");
    ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
    ctx.fill();
  });

  if (traceHoverIndex !== null) {
    drawMapHoverMarker(ctx, t, bounds, w, h, traceHoverIndex);
  }
}

function drawMapHoverMarker(ctx, t, bounds, w, h, index) {
  const markers = [
    [t.ref_X, t.ref_Y, css("--ref"), "Reference"],
    [t.cmp_X, t.cmp_Y, css("--cmp"), "Compared"],
  ];
  ctx.save();
  markers.forEach(([xs, ys, color, label], markerIndex) => {
    if (!xs || !ys || !isFiniteNumber(xs[index]) || !isFiniteNumber(ys[index])) return;
    const point = mapPoint(xs[index], ys[index], bounds, w, h);
    const labelX = Math.min(w - 90, point.x + 10);
    const labelY = Math.max(18, Math.min(h - 14, point.y - 10 + markerIndex * 18));
    ctx.fillStyle = color;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(point.x, point.y, markerIndex === 0 ? 7 : 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(255, 255, 255, 0.86)";
    ctx.fillRect(labelX - 2, labelY - 11, 76, 15);
    ctx.fillStyle = "#17211e";
    ctx.font = "12px Inter, sans-serif";
    ctx.fillText(label, labelX, labelY);
  });
  ctx.restore();
}

function drawBackground(ctx, w, h) {
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#e5ebe8";
  ctx.lineWidth = 1;
  for (let y = 40; y < h; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
}

function drawAxis(ctx, pane, w) {
  ctx.strokeStyle = "#d8dfdc";
  ctx.fillStyle = "#63706c";
  ctx.font = "12px Inter, sans-serif";
  ctx.strokeRect(48, pane.y, w - 66, pane.h);
  ctx.fillText(pane.label, 14, pane.y + 16);
  ctx.textAlign = "right";
  ctx.fillText(axisValueLabel(pane.max, pane.label), w - 22, pane.y + 14);
  ctx.fillText(axisValueLabel(pane.min, pane.label), w - 22, pane.y + pane.h - 6);
  ctx.textAlign = "left";
}

function drawSeries(ctx, distance, values, pane, token) {
  const color = token === "var-ref" ? css("--ref") : token === "var-cmp" ? css("--cmp") : css("--delta");
  const minD = minOf(distance);
  const maxD = maxOf(distance);
  const minV = pane.min === pane.max ? pane.min - 1 : pane.min;
  const maxV = pane.min === pane.max ? pane.max + 1 : pane.max;
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = token === "var-delta" ? 2.5 : 2;
  values.forEach((value, index) => {
    if (!isFiniteNumber(value)) return;
    const x = scale(distance[index], minD, maxD, 48, ctx.canvas.width - 18);
    const y = scale(value, minV, maxV, pane.y + pane.h - 8, pane.y + 8);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function axisValueLabel(value, label) {
  if (!isFiniteNumber(value)) return "--";
  if (label.includes("Delta")) return `${value >= 0 ? "+" : ""}${value.toFixed(2)} s`;
  if (label.includes("Throttle")) return `${value.toFixed(0)}%`;
  if (label.includes("Brake")) return value >= 0.5 ? "1 on" : "0 off";
  return value.toFixed(0);
}

function drawTelemetryKey(ctx, w) {
  const items = [
    ["Reference", css("--ref")],
    ["Compared", css("--cmp")],
    ["Delta", css("--delta")],
  ];
  let x = Math.max(56, w - 226);
  const y = 18;
  ctx.font = "12px Inter, sans-serif";
  items.forEach(([label, color]) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 18, y);
    ctx.stroke();
    ctx.fillStyle = "#26312e";
    ctx.fillText(label, x + 24, y + 4);
    x += label === "Compared" ? 88 : 78;
  });
}

function drawTraceHover(ctx, t, panes, index, w, h) {
  const distance = t.Distance[index];
  const x = scale(distance, minOf(t.Distance), maxOf(t.Distance), 48, w - 18);
  ctx.save();
  ctx.strokeStyle = "#17211e";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, 18);
  ctx.lineTo(x, h - 20);
  ctx.stroke();
  ctx.setLineDash([]);
  panes.forEach((pane) => {
    [
      [pane.ref, css("--ref")],
      [pane.cmp, css("--cmp")],
      [pane.delta, css("--delta")],
    ].forEach(([values, color]) => {
      if (!values || !isFiniteNumber(values[index])) return;
      const minV = pane.min === pane.max ? pane.min - 1 : pane.min;
      const maxV = pane.min === pane.max ? pane.max + 1 : pane.max;
      const y = scale(values[index], minV, maxV, pane.y + pane.h - 8, pane.y + 8);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
  });
  ctx.restore();
}

function drawPath(ctx, xs, ys, bounds, w, h, color, lineWidth) {
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  xs.forEach((x, index) => {
    const point = mapPoint(x, ys[index], bounds, w, h);
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();
}

function mapPoint(x, y, bounds, w, h) {
  const pad = 28;
  return {
    x: scale(x, bounds.minX, bounds.maxX, pad, w - pad),
    y: scale(y, bounds.minY, bounds.maxY, h - pad, pad),
  };
}

function fitCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(320, Math.floor(rect.width));
  canvas.height = Math.max(260, Math.floor(rect.height));
  return canvas.getContext("2d");
}

function drawDistanceMarker(ctx, x, label, h) {
  ctx.strokeStyle = "#869691";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, 14);
  ctx.lineTo(x, h - 12);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#63706c";
  ctx.font = "12px Inter, sans-serif";
  ctx.fillText(label, x + 4, 28);
}

function sliceTelemetry(t, indices) {
  const output = {};
  Object.entries(t).forEach(([key, values]) => {
    output[key] = indices.map((index) => values[index]);
  });
  return output;
}

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function fillSelect(select, options) {
  select.innerHTML = options.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join("");
}

function clearSelect(select) {
  select.innerHTML = "";
}

function defaultSessions() {
  return ["Practice 1", "Practice 2", "Practice 3", "Sprint Shootout", "Sprint", "Qualifying", "Race"].map((name) => ({ name }));
}

function setStatus(message) {
  els.status.classList.remove("error");
  els.status.textContent = message;
}

function setError(error) {
  els.status.classList.add("error");
  els.status.textContent = error.message || String(error);
}

function lapLabel(meta) {
  if (!meta) return "--";
  return `${meta.driver} L${meta.lap_number} ${clock(meta.lap_time_seconds)}`;
}

function lapShort(meta) {
  if (!meta) return "--";
  return `${meta.driver} L${meta.lap_number}`;
}

function driverComparison(detection, report) {
  const reference = lapShort(report.reference);
  const compared = lapShort(report.compared);
  if (detection.time_impact_seconds > 0) {
    return {
      better: reference,
      worse: compared,
    };
  }
  if (detection.time_impact_seconds < 0) {
    return {
      better: compared,
      worse: reference,
    };
  }
  return {
    better: "Even",
    worse: "Even",
  };
}

function seconds(value) {
  return isFiniteNumber(value) ? `${value >= 0 ? "+" : ""}${value.toFixed(3)} s` : "--";
}

function signed(value, unit = "") {
  return isFiniteNumber(value) ? `${value >= 0 ? "+" : ""}${value.toFixed(1)}${unit}` : "--";
}

function num(value, digits = 1) {
  return isFiniteNumber(value) ? value.toFixed(digits) : "--";
}

function average(values) {
  const clean = values.filter(isFiniteNumber);
  return clean.length ? clean.reduce((sum, value) => sum + value, 0) / clean.length : null;
}

function median(values) {
  const clean = values.filter(isFiniteNumber).sort((a, b) => a - b);
  if (!clean.length) return null;
  const middle = Math.floor(clean.length / 2);
  return clean.length % 2 ? clean[middle] : (clean[middle - 1] + clean[middle]) / 2;
}

function roundValue(value) {
  return isFiniteNumber(value) ? String(Math.round(value)) : "--";
}

function onOff(value) {
  return isFiniteNumber(value) && value > 0.5 ? "on" : "off";
}

function drsState(value) {
  return isFiniteNumber(value) && value > 0 ? "active" : "off";
}

function listBlock(title, items) {
  if (!items?.length) return "";
  return `<div class="indicator-list"><strong>${escapeHtml(title)}</strong>${items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
}

function clock(value) {
  if (!isFiniteNumber(value)) return "";
  const minutes = Math.floor(value / 60);
  const secondsPart = value - minutes * 60;
  return `${minutes}:${secondsPart.toFixed(3).padStart(6, "0")}`;
}

function scale(value, inMin, inMax, outMin, outMax) {
  if (inMax === inMin) return (outMin + outMax) / 2;
  return outMin + ((value - inMin) / (inMax - inMin)) * (outMax - outMin);
}

function minOf(...arrays) {
  return Math.min(...arrays.flat().filter(isFiniteNumber));
}

function maxOf(...arrays) {
  return Math.max(...arrays.flat().filter(isFiniteNumber));
}

function nearestIndex(values, target) {
  let best = 0;
  let bestDelta = Infinity;
  values.forEach((value, index) => {
    const delta = Math.abs(value - target);
    if (delta < bestDelta) {
      best = index;
      bestDelta = delta;
    }
  });
  return best;
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
