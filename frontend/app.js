const els = {
  form: document.querySelector("#selection-form"),
  season: document.querySelector("#season"),
  event: document.querySelector("#event"),
  session: document.querySelector("#session"),
  team: document.querySelector("#team"),
  driverA: document.querySelector("#driver-a"),
  driverB: document.querySelector("#driver-b"),
  status: document.querySelector("#status"),
  title: document.querySelector("#selection-title"),
  summary: document.querySelector("#summary-text"),
  totalDelta: document.querySelector("#total-delta"),
  referenceLap: document.querySelector("#reference-lap"),
  comparedLap: document.querySelector("#compared-lap"),
  validity: document.querySelector("#validity"),
  sectors: document.querySelector("#sector-bars"),
  context: document.querySelector("#context-list"),
  detections: document.querySelector("#detections"),
  detail: document.querySelector("#finding-detail"),
  trace: document.querySelector("#trace-canvas"),
  map: document.querySelector("#map-canvas"),
};

let drivers = [];
let currentPayload = null;
let currentFilter = "all";

init();

async function init() {
  wireEvents();
  await loadSeasons();
}

function wireEvents() {
  els.season.addEventListener("change", loadEvents);
  els.event.addEventListener("change", loadSessions);
  els.session.addEventListener("change", loadSessionEntries);
  els.team.addEventListener("change", renderDrivers);
  els.form.addEventListener("submit", (event) => {
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
    if (currentPayload) renderCharts(currentPayload);
  });
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
  clearSelect(els.session);
  try {
    const data = await api(`/api/events?year=${encodeURIComponent(els.season.value)}`);
    fillSelect(els.event, data.events.map((event) => ({ value: event.name, label: `${event.round}. ${event.name}` })));
    els.event._events = data.events;
    loadSessions();
  } catch (error) {
    setError(error);
  }
}

function loadSessions() {
  const selected = (els.event._events || []).find((event) => event.name === els.event.value);
  const sessions = selected?.sessions?.length ? selected.sessions : defaultSessions();
  fillSelect(els.session, sessions.map((session) => ({ value: session.name, label: session.name })));
  loadSessionEntries();
}

async function loadSessionEntries() {
  if (!els.season.value || !els.event.value || !els.session.value) return;
  setStatus("Loading drivers and cars for this session...");
  try {
    const params = new URLSearchParams({ year: els.season.value, event: els.event.value, session: els.session.value });
    const data = await api(`/api/session-entries?${params}`);
    drivers = data.drivers || [];
    fillSelect(els.team, [{ value: "all", label: "All teams" }, ...(data.teams || []).map((team) => ({ value: team, label: team }))]);
    renderDrivers();
    setStatus("Ready. Choose drivers and run analysis.");
  } catch (error) {
    setError(error);
  }
}

function renderDrivers() {
  const team = els.team.value;
  const filtered = drivers.filter((driver) => team === "all" || driver.team === team);
  const options = filtered.map((driver) => ({
    value: driver.code,
    label: `${driver.code}${driver.team ? ` · ${driver.team}` : ""}`,
  }));
  fillSelect(els.driverA, options);
  fillSelect(els.driverB, options);
  if (options[1]) els.driverB.value = options[1].value;
}

async function runAnalysis() {
  if (!els.driverA.value) return;
  setStatus("Loading FastF1 data and comparing best laps. This can take a moment on first load...");
  els.form.querySelector("button").disabled = true;
  try {
    const params = new URLSearchParams({
      year: els.season.value,
      event: els.event.value,
      session: els.session.value,
      driver_a: els.driverA.value,
      driver_b: els.driverB.value || els.driverA.value,
    });
    currentPayload = await api(`/api/compare-best-laps?${params}`);
    renderDashboard(currentPayload);
    setStatus("Analysis complete.");
  } catch (error) {
    setError(error);
  } finally {
    els.form.querySelector("button").disabled = false;
  }
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
  renderDetections(payload);
  renderCharts(payload);
}

function renderSectors(report) {
  const values = report.sector_deltas_seconds || [];
  const max = Math.max(0.001, ...values.map((value) => Math.abs(value || 0)));
  els.sectors.innerHTML = values
    .map((value, index) => {
      const width = Math.max(4, (Math.abs(value || 0) / max) * 100);
      const cls = value > 0 ? "loss" : "";
      return `<div class="sector-row">
        <strong>S${index + 1}</strong>
        <div class="sector-track"><div class="sector-fill ${cls}" style="width:${width}%"></div></div>
        <span>${seconds(value)}</span>
      </div>`;
    })
    .join("");
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
    <canvas id="finding-telemetry" class="finding-telemetry" width="620" height="360"></canvas>
    <ul>${(detection.evidence || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    <p>${escapeHtml(detection.interpretation)}</p>`;
  drawFindingTelemetry(document.querySelector("#finding-telemetry"), payload.telemetry, detection);
}

function renderCharts(payload) {
  drawTrace(payload.telemetry, payload.sections || []);
  drawMap(payload.telemetry, payload.report.detections || []);
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
}

function drawFindingTelemetry(canvas, t, detection) {
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

  drawDistanceMarker(ctx, x1, "start", h);
  drawDistanceMarker(ctx, x2, "end", h);
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
