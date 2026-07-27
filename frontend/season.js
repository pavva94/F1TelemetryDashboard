(() => {
  const $ = (selector) => document.querySelector(selector);
  const apiBase = String(window.FASTF1_API_BASE || "").replace(/\/$/, "");
  const state = { payload: null, schedule: [], filteredRecords: [], route: null };
  const chartInteractions = new WeakMap();
  const chartHover = new WeakMap();
  const boundCharts = new WeakSet();
  let seasonChartTooltip = null;
  let seasonLoadSequence = 0;
  const elements = {
    racePage: $("#race-page"), seasonPage: $("#season-page"), form: $("#season-filters"),
    year: $("#season-year"), start: $("#season-start-round"), end: $("#season-end-round"),
    session: $("#season-session"), conditions: $("#season-conditions"),
    valueKind: $("#season-value-kind"), reference: $("#season-reference"), level: $("#season-level"),
    rolling: $("#season-rolling"), teams: $("#season-teams"), drivers: $("#season-drivers"),
    sprints: $("#season-sprints"), classified: $("#season-classified"),
    status: $("#season-status"), progress: $("#season-progress"), content: $("#season-content"),
    freshness: $("#season-freshness"),
  };

  init();

  async function init() {
    createSeasonChartTooltip();
    wireRouting();
    wireFilters();
    applyRoute();
    if (window.FastF1Routing.route() === "season") {
      await loadSeasonOptions();
    }
    applyRoute();
  }

  function wireRouting() {
    document.querySelectorAll(".mode-navigation a").forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      const route = link.dataset.route;
      if (route === "race") {
        window.location.assign(window.FastF1Routing.rebase(sessionStorage.getItem("fastf1-race-url"), "race"));
        return;
      }
      if (state.route === "race") {
        sessionStorage.setItem("fastf1-race-url", window.FastF1Routing.url("race", new URLSearchParams(location.search)));
        window.location.assign(window.FastF1Routing.rebase(sessionStorage.getItem("fastf1-season-url"), "season"));
        return;
      }
      history.pushState({ route }, "", seasonUrl());
      applyRoute();
    }));
    window.addEventListener("popstate", applyRoute);
  }

  function applyRoute() {
    const route = window.FastF1Routing.route();
    state.route = route;
    document.body.dataset.route = route;
    elements.racePage.hidden = route !== "race";
    elements.seasonPage.hidden = route !== "season";
    document.querySelectorAll(".mode-navigation a").forEach((link) => {
      const active = link.dataset.route === route;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    if (route === "season" && !state.payload && elements.year.value) loadSeason();
  }

  function wireFilters() {
    elements.form.addEventListener("submit", (event) => { event.preventDefault(); loadSeason(); });
    elements.year.addEventListener("change", async () => {
      if (await loadSchedule()) loadSeason();
    });
    document.addEventListener("click", (event) => {
      const button = event.target.closest(".season-table th button");
      if (button) sortTable(button.closest("table"), Number(button.dataset.column));
    });
    document.querySelectorAll(".export-button").forEach((button) => button.addEventListener("click", () => exportSection(button.dataset.export)));
    window.addEventListener("resize", debounce(() => state.payload && renderCharts(), 120));
  }

  async function loadSeasonOptions() {
    try {
      const data = await getJson("/api/seasons");
      fillSelect(elements.year, data.seasons.map((year) => ({ value: year, label: year })));
      const query = new URLSearchParams(location.search);
      const requested = query.get("season");
      if (requested && [...elements.year.options].some((option) => option.value === requested)) elements.year.value = requested;
      await loadSchedule();
    } catch (error) {
      setStatus(`Unable to load seasons: ${error.message}`, true);
    }
  }

  async function loadSchedule() {
    if (!elements.year.value) return false;
    try {
      const data = await getJson(`/api/events?year=${encodeURIComponent(elements.year.value)}`);
      state.schedule = data.events || [];
      const options = state.schedule.map((event) => ({ value: event.round, label: `${event.round}. ${event.name}` }));
      fillSelect(elements.start, options);
      fillSelect(elements.end, options);
      elements.start.value = options[0]?.value || "";
      elements.end.value = options.at(-1)?.value || "";
      return true;
    } catch (error) {
      setStatus(`Unable to load the season schedule: ${error.message}`, true);
      return false;
    }
  }

  async function loadSeason() {
    if (!elements.year.value) return;
    const sequence = ++seasonLoadSequence;
    const year = elements.year.value;
    elements.progress.hidden = false;
    elements.content.hidden = true;
    setStatus(`Checking the shared ${year} season analysis cache…`);
    try {
      let result = await fetchSeasonAnalysis(year);
      if (result.preparing) {
        setStatus(`Preparing the ${year} season analysis for the first time. This calculation is shared across all visitors.`);
        result = await waitForPreparedSeason(year, sequence, result.cache);
      }
      if (sequence !== seasonLoadSequence) return;
      state.payload = result.payload;
      populateEntityFilters();
      syncUrl();
      render();
      elements.content.hidden = false;
      const meta = state.payload.meta;
      const status = meta.isComplete ? "Complete season analysis" : `Analysis includes completed rounds ${meta.completedRounds?.[0] || "—"}–${meta.availableRound || "—"}`;
      const cache = meta.cache || {};
      if (cache.stale) {
        setStatus(`Showing data through Round ${cache.lastCompletedRound || meta.availableRound || "—"}. Updated Round ${cache.latestAvailableRound || "new"} data is being prepared.`);
      } else {
        setStatus(`${status}${meta.partial ? `. Partial data: ${state.payload.errors.length} session load${state.payload.errors.length === 1 ? "" : "s"} unavailable.` : "."}`);
      }
      elements.freshness.textContent = `Generated ${formatDate(meta.generatedAt)} · ${meta.dataFreshness || "FastF1 timing data"}`;
    } catch (error) {
      if (sequence !== seasonLoadSequence) return;
      setStatus(`Season analysis failed: ${error.message}. Check the server connection, then retry.`, true);
    } finally {
      if (sequence === seasonLoadSequence) elements.progress.hidden = true;
    }
  }

  async function fetchSeasonAnalysis(year) {
    const response = await fetch(`${apiBase}/api/season/${encodeURIComponent(year)}/analysis`);
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (response.status === 202) return { preparing: true, cache: data.cache || data };
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return { preparing: false, payload: data };
  }

  async function waitForPreparedSeason(year, sequence, initial) {
    let cache = initial || {};
    while (sequence === seasonLoadSequence) {
      updatePreparationProgress(cache);
      await delay(2000);
      const response = await fetch(`${apiBase}/api/season/${encodeURIComponent(year)}/status`, { cache: "no-store" });
      const status = await response.json();
      if (!response.ok) throw new Error(status.detail || `Status request failed (${response.status})`);
      cache = status;
      if (status.status === "failed") throw new Error(status.error || "The shared cache could not be prepared.");
      if (status.status === "ready") {
        const result = await fetchSeasonAnalysis(year);
        if (!result.preparing) return result;
      }
    }
    throw new Error("Season selection changed.");
  }

  function updatePreparationProgress(cache) {
    const progress = Number(cache?.progress || 0);
    const stage = cache?.stage || "waiting for the cache generator";
    const label = elements.progress.querySelector("span");
    if (label) label.textContent = `${humanize(stage)}${progress ? ` · ${progress}%` : ""}`;
    elements.progress.style.setProperty("--progress", `${Math.max(2, progress)}%`);
  }

  function populateEntityFilters() {
    const selectedTeams = selectedValues(elements.teams);
    const selectedDrivers = selectedValues(elements.drivers);
    fillSelect(elements.teams, state.payload.entities.teams.map((team) => ({ value: team, label: team })), true);
    fillSelect(elements.drivers, state.payload.entities.drivers.map((driver) => ({ value: driver, label: driver })), true);
    selectValues(elements.teams, selectedTeams);
    selectValues(elements.drivers, selectedDrivers);
  }

  function render() {
    const payload = state.payload;
    if (!payload?.records?.length) {
      elements.content.hidden = false;
      elements.content.innerHTML = `<div class="status error">${escapeHtml(payload?.message || "No comparable completed rounds are available for this range.")}</div>`;
      return;
    }
    state.filteredRecords = filteredRecords();
    renderOverview(); renderChampionship(); renderPerformance(); renderDevelopment();
    renderTeams(); renderDrivers(); renderReliability(); renderTyres(); renderHistory();
    renderPredictions(); renderMethodology(); renderCharts();
  }

  function filteredRecords() {
    const teams = selectedValues(elements.teams);
    const drivers = selectedValues(elements.drivers);
    const condition = elements.conditions.value;
    const firstRound = Number(elements.start.value || 1);
    const lastRound = Number(elements.end.value || Number.MAX_SAFE_INTEGER);
    const allowedRounds = new Set(state.payload.events.filter((event) => condition === "all" || event.weather === condition).map((event) => event.round));
    return state.payload.records.filter((record) =>
      record.round >= firstRound && record.round <= lastRound &&
      (!teams.length || teams.includes(record.team)) &&
      (!drivers.length || drivers.includes(record.driver)) &&
      (condition === "all" || allowedRounds.has(record.round)) &&
      (elements.classified.checked || record.reliability === "classified")
    );
  }

  function renderOverview() {
    const records = state.filteredRecords;
    const driverPoints = groupSum(records, "driver", pointValue);
    const teamPoints = groupSum(records, "team", pointValue);
    const development = filteredTeams(state.payload.development);
    const reliable = state.payload.reliability.teams.filter((row) => hasTeam(row.entity));
    const conversions = state.payload.conversion.teams.filter((row) => hasTeam(row.entity));
    const momentum = state.payload.momentum.filter((row) => hasTeam(row.team));
    const consistency = driverConsistency(records);
    const improved = development.filter((row) => row.qualifyingEarlyRecent.change != null).sort((a, b) => a.qualifyingEarlyRecent.change - b.qualifyingEarlyRecent.change)[0];
    const bestQ = metricEnabled("qualifyingDeficit") ? rankDisplayedMetric(records, "team", "qualifyingDeficit")[0] : null;
    const bestR = metricEnabled(paceMetric()) ? rankDisplayedMetric(records, "team", paceMetric())[0] : null;
    const biggest = [...state.payload.changePoints].filter((row) => hasTeam(row.team)).sort((a, b) => Math.abs(b.magnitude) - Math.abs(a.magnitude))[0];
    const cards = [
      card("Drivers’ leader", driverPoints[0]?.entity, formatPoints(driverPoints[0]?.value), "Selected round range", "#championship"),
      card("Constructors’ leader", teamPoints[0]?.entity, formatPoints(teamPoints[0]?.value), "Selected round range", "#championship"),
      card("Most improved team", improved?.team, improved ? signed(improved.qualifyingEarlyRecent.change, 3, "%") : null, "First 3 vs latest 3", "#development"),
      card("Best qualifying team", bestQ?.entity, bestQ ? formatPerformance(bestQ.value) : null, elements.reference.value === "absolute" ? "Representative median time" : "Median normalized deficit", "#performance"),
      card("Best race-pace team", bestR?.entity, bestR ? formatPerformance(bestR.value) : null, `${elements.valueKind.value} median ${elements.reference.value === "absolute" ? "pace" : "deficit"}`, "#performance"),
      card("Most reliable team", reliable.sort((a, b) => (b.percentage || 0) - (a.percentage || 0))[0]?.entity, reliable[0]?.percentage == null ? null : `${Math.max(...reliable.map((row) => row.percentage || 0)).toFixed(0)}%`, "Classified finishes / starts", "#reliability"),
      card("Best points conversion", conversions[0]?.entity, conversions[0] ? signed(conversions[0].difference, 1, " pts") : null, "Actual minus model estimate", "#teams"),
      card("Strongest recent form", momentum[0]?.team, momentum[0] ? `${momentum[0].score.toFixed(0)}/100` : null, "Documented weighted index", "#predictions"),
      card("Largest performance step", biggest?.team, biggest ? signed(biggest.magnitude, 3, "%") : null, biggest ? `Near round ${biggest.round}` : null, "#development"),
      card("Most consistent driver", consistency[0]?.driver, consistency[0] ? `${consistency[0].mad.toFixed(3)}% MAD` : null, "Event pace variance", "#drivers"),
      card("Closest championship battle", driverPoints[1] ? `${driverPoints[0].entity} / ${driverPoints[1].entity}` : null, driverPoints[1] ? `${(driverPoints[0].value - driverPoints[1].value).toFixed(0)} pts` : null, "Gap between top two", "#championship"),
      card("Available evidence", `${new Set(records.map((row) => row.round)).size} rounds`, `${records.reduce((sum, row) => sum + row.cleanLaps, 0)} clean laps`, "After quality exclusions", "#methodology"),
    ];
    $("#season-summary-cards").innerHTML = cards.join("");
    $("#season-insights").innerHTML = state.payload.insights.map((insight) => `<article class="insight-card"><p>${escapeHtml(insight.statement)}</p><small>${escapeHtml(insight.confidence)} confidence · n=${insight.sampleSize} · <a href="#${escapeHtml(insight.target)}">supporting analysis</a></small></article>`).join("");
  }

  function renderChampionship() {
    const key = elements.level.value === "driver" ? "driver" : "team";
    const points = groupSum(state.filteredRecords, key, pointValue);
    $("#championship-table").innerHTML = table(
      ["Rank", key === "driver" ? "Driver" : "Team", "Points", "Wins", "Podiums", "Events"],
      points.map((item, index) => [index + 1, item.entity, item.value.toFixed(0), countResults(item.entity, key, 1), countResults(item.entity, key, 3), new Set(state.filteredRecords.filter((row) => row[key] === item.entity).map((row) => row.round)).size])
    );
    const entities = visibleEntities(key);
    const rounds = visibleRounds();
    $("#points-heatmap").innerHTML = heatmapTable(entities, rounds, (entity, round) => {
      const rows = state.filteredRecords.filter((row) => row[key] === entity && row.round === round);
      const value = rows.reduce((sum, row) => sum + pointValue(row), 0);
      const event = state.payload.events.find((item) => item.round === round);
      return `<a class="heat-cell" style="--heat:${Math.min(100, value * 4)}" href="${raceUrl(event, key === "driver" ? entity : null, key === "team" ? entity : null)}" title="${escapeHtml(event?.name)}: ${value} points">${value || "—"}</a>`;
    });
  }

  function renderPerformance() {
    const records = state.filteredRecords;
    const rankRows = [];
    visibleRounds().forEach((round) => {
      const rows = metricEnabled(paceMetric()) ? records.filter((row) => row.round === round && row[paceMetric()] != null) : [];
      const sorted = [...rows].sort((a, b) => a[paceMetric()] - b[paceMetric()]);
      sorted.forEach((row, index) => rankRows.push([round, row.event, row.driver, row.team, index + 1, row.finish ?? "—", formatPercent(row[paceMetric()]), row.cleanLaps, confidenceBadge(row.quality?.confidence)]));
    });
    $("#rank-comparison").innerHTML = table(["Round", "Event", "Driver", "Team", "Pace rank", "Finish", "Deficit", "Clean laps", "Confidence"], rankRows);
  }

  function renderDevelopment() {
    const rows = filteredTeams(state.payload.development).map((row) => [
      row.team, nullableSigned(row.qualifying.rate, "% / round"), nullableSigned(row.racePace.rate, "% / round"),
      nullablePercent(row.qualifyingEarlyRecent.early), nullablePercent(row.qualifyingEarlyRecent.recent),
      nullableSigned(row.qualifyingEarlyRecent.change, "%"), row.qualifying.events, confidenceBadge(row.qualifying.confidence),
    ]);
    $("#development-table").innerHTML = table(["Team", "Qualifying rate", "Race-pace rate", "Early Q", "Recent Q", "Change", "Events", "Confidence"], rows);
    $("#change-points").innerHTML = state.payload.changePoints.filter((row) => hasTeam(row.team)).map((row) =>
      `<article class="insight-card"><p><strong>${escapeHtml(row.team)}</strong> · ${escapeHtml(row.direction)} near round ${row.round}</p><small>${signed(row.magnitude, 3, "%")} · ${escapeHtml(row.confidence)} confidence · before ${formatPercent(row.before)}, after ${formatPercent(row.after)}</small></article>`
    ).join("") || `<p class="unavailable">No change point cleared the six-event evidence threshold in this selection.</p>`;
    $("#upgrade-analysis").innerHTML = state.payload.upgrades.length
      ? table(["Team", "Event", "Component", "Description", "Confidence", "Source"], state.payload.upgrades.map((row) => [row.team, row.event, row.component, row.description, row.confidence, `<a href="${escapeHtml(row.source)}">source</a>`]))
      : `<p class="unavailable">FastF1 has no authoritative upgrade feed. No sourced upgrade entries are configured for this season, so the model correctly withholds upgrade-impact claims.</p>`;
  }

  function renderTeams() {
    const selected = selectedValues(elements.teams);
    const visibleTeams = visibleEntities("team");
    const teams = selected.length ? selected.filter((team) => visibleTeams.includes(team)) : visibleTeams;
    const metrics = teams.map((team) => ({
      team,
      points: groupSum(state.filteredRecords.filter((row) => row.team === team), "team", pointValue)[0]?.value || 0,
      qualifying: metricEnabled("qualifyingDeficit") ? displayMetricAggregate(state.filteredRecords, team, "team", "qualifyingDeficit") : null,
      race: metricEnabled(paceMetric()) ? displayMetricAggregate(state.filteredRecords, team, "team", paceMetric()) : null,
      reliability: state.payload.reliability.teams.find((row) => row.entity === team)?.percentage,
      conversion: state.payload.conversion.teams.find((row) => row.entity === team)?.difference,
      momentum: state.payload.momentum.find((row) => row.team === team)?.score,
    }));
    const bestQ = [...metrics].filter((row) => row.qualifying != null).sort((a, b) => a.qualifying - b.qualifying)[0];
    const bestRace = [...metrics].filter((row) => row.race != null).sort((a, b) => a.race - b.race)[0];
    const bestExecution = [...metrics].filter((row) => row.conversion != null).sort((a, b) => b.conversion - a.conversion)[0];
    const analyzedTeamCount = state.payload.trackAnalysis.teamCount ?? state.payload.trackAnalysis.teamsAnalyzed?.length ?? state.payload.entities.teams.length;
    const taggedEventCount = state.payload.trackAnalysis.metadataCoverage ?? 0;
    const leaderSummary = [
      bestQ && `${bestQ.team} leads qualifying at ${nullablePerformance(bestQ.qualifying)}`,
      bestRace && `${bestRace.team} leads race pace at ${nullablePerformance(bestRace.race)}`,
      bestExecution && `${bestExecution.team} leads points conversion at ${nullableSigned(bestExecution.conversion, " pts")}`,
    ].filter(Boolean).join("; ");
    $("#team-summary").innerHTML = `
      <div class="team-summary-grid">
        <div><strong>Coverage</strong><span>${selected.length ? `${teams.length} selected team${teams.length === 1 ? "" : "s"} shown` : `All ${teams.length} teams allowed by the current filters are shown`}. The season model analyzed ${analyzedTeamCount} team${analyzedTeamCount === 1 ? "" : "s"} across ${visibleRounds().length} selected round${visibleRounds().length === 1 ? "" : "s"}.</span></div>
        <div><strong>Performance</strong><span>Qualifying and race-pace deficits measure the gap to the fastest team. Lower percentages are faster; 0.000% is the benchmark.</span></div>
        <div><strong>Track suitability</strong><span>Each circuit-type value compares a team with its own season-median race pace. Negative is stronger than usual; positive is weaker. ${taggedEventCount} event${taggedEventCount === 1 ? "" : "s"} had maintained circuit tags.</span></div>
        <div><strong>Execution</strong><span>Reliability is classified finishes divided by starts. Points vs model is actual points minus a pace-rank estimate. Recent form is a documented 0–100 momentum score.</span></div>
      </div>
      ${leaderSummary ? `<p class="team-leaders"><strong>Leaders in this view:</strong> ${escapeHtml(leaderSummary)}.</p>` : ""}
    `;
    $("#team-table").innerHTML = table(["Team", "Points", "Qualifying deficit", "Race-pace deficit", "Reliability", "Pts vs expected", "Momentum"], metrics.map((row) => [
      row.team, row.points.toFixed(0), nullablePerformance(row.qualifying), nullablePerformance(row.race),
      row.reliability == null ? "—" : `${row.reliability.toFixed(0)}%`, nullableSigned(row.conversion, " pts"), row.momentum == null ? "—" : row.momentum.toFixed(0),
    ]));
    const strengths = state.payload.trackAnalysis.strengths.filter((row) => teams.includes(row.team));
    const clusters = [...new Set(strengths.map((row) => row.cluster))];
    $("#track-heatmap").innerHTML = heatmapTable(teams, clusters, (team, cluster) => {
      const row = strengths.find((item) => item.team === team && item.cluster === cluster);
      if (!row) return "—";
      const eventLabel = `${row.events} event${row.events === 1 ? "" : "s"}`;
      return `<span class="heat-cell track-strength-cell" style="--heat:${Math.min(100, Math.abs(row.relativeStrength) * 80)}" title="${escapeHtml(`${humanize(cluster)}: ${signed(row.relativeStrength, 3, "%")} versus the team's season median. Negative is stronger. ${eventLabel}, ${row.confidence} confidence.`)}"><strong>${signed(row.relativeStrength, 3, "%")}</strong><small>${eventLabel} · ${escapeHtml(row.confidence)}</small></span>`;
    }, "Team / circuit type", humanize);
  }

  function renderDrivers() {
    const consistency = driverConsistency(state.filteredRecords);
    const rows = consistency.map((item) => {
      const driverRows = state.filteredRecords.filter((row) => row.driver === item.driver);
      const team = driverRows[0]?.team;
      const teammateRows = state.filteredRecords.filter((row) => row.team === team && row.driver !== item.driver);
      const headToHead = driverRows.filter((row) => {
        const mate = teammateRows.find((other) => other.round === row.round && other.qualifyingDeficit != null);
        return row.qualifyingDeficit != null && mate && row.qualifyingDeficit < mate.qualifyingDeficit;
      }).length;
      const comparable = driverRows.reduce((sum, row) => sum + row.cleanLaps, 0);
      return [item.driver, team, `${headToHead}/${new Set(driverRows.map((row) => row.round)).size}`, nullableSigned(teammateDelta(item.driver, team), "%"), nullablePerformance(displayMetricAggregate(state.filteredRecords, item.driver, "driver", paceMetric())), `${item.mad.toFixed(3)}%`, comparable, confidenceBadge(item.confidence)];
    });
    $("#driver-table").innerHTML = table(["Driver", "Team", "Qualifying H2H", "Median teammate delta", "Race-pace deficit", "Consistency MAD", "Comparable laps", "Confidence"], rows);
  }

  function renderReliability() {
    const teams = state.payload.reliability.teams
      .filter((row) => hasTeam(row.entity))
      .sort((a, b) => compareNullableDescending(a.percentage, b.percentage) || b.classified - a.classified || a.entity.localeCompare(b.entity));
    $("#reliability-table").innerHTML = table(["Rank", "Team", "Starts", "Classified", "Mechanical", "Incidents", "DNS", "DSQ", "Reliability", "Confidence"], teams.map((row, index) => [
      index + 1, row.entity, row.starts, row.classified, row.mechanical, row.incidents, row.dns, row.dsq, row.percentage == null ? "—" : `${row.percentage.toFixed(1)}%`, confidenceBadge(row.confidence),
    ]));
    const rounds = visibleRounds();
    const driverReliability = new Map(state.payload.reliability.drivers.map((row) => [row.entity, row]));
    const drivers = visibleEntities("driver").sort((a, b) => {
      const left = driverReliability.get(a);
      const right = driverReliability.get(b);
      return compareNullableDescending(left?.percentage, right?.percentage) || (right?.classified || 0) - (left?.classified || 0) || a.localeCompare(b);
    });
    $("#reliability-timeline").innerHTML = heatmapTable(drivers, rounds, (driver, round) => {
      const row = state.payload.reliability.timeline.find((item) => item.driver === driver && item.round === round);
      const event = state.payload.events.find((item) => item.round === round);
      return row ? `<a class="heat-cell state-${escapeHtml(row.state)}" href="${raceUrl(event, driver)}" title="${escapeHtml(row.status)}">${escapeHtml(row.state.slice(0, 3).toUpperCase())}</a>` : "—";
    }, "Driver / round");
    const pitTeams = state.payload.operations.teams
      .filter((row) => hasTeam(row.team))
      .sort((a, b) => compareNullable(a.medianPitLane, b.medianPitLane) || b.stops - a.stops || a.team.localeCompare(b.team));
    $("#pitstop-table").innerHTML = table(["Rank", "Team", "Measured stops", "Median pit-lane time", "Variation", "Confidence"], pitTeams.map((row, index) => [
      row.medianPitLane == null ? "—" : index + 1, row.team, row.stops, row.medianPitLane == null ? "—" : `${row.medianPitLane.toFixed(2)} s`, row.variation == null ? "—" : `${row.variation.toFixed(2)} s`, confidenceBadge(row.confidence),
    ]));
  }

  function renderTyres() {
    const degradation = state.payload.tyres.degradation.filter((row) => hasTeam(row.team) && hasDriver(row.driver));
    $("#degradation-table").innerHTML = table(["Round", "Event", "Driver", "Team", "Tyre-age effect", "Race-lap proxy", "Residual MAD", "Laps", "Confidence"], degradation.map((row) => [
      row.round, row.event, row.driver, row.team, `${signed(row.rate, 3, " s/lap")}`, `${signed(row.fuelProxy, 3, " s/lap")}`, `${row.residualMad.toFixed(3)} s`, row.laps, confidenceBadge(row.confidence),
    ]));
    const strategies = state.payload.tyres.strategies.filter((row) => hasTeam(row.team) && hasDriver(row.driver));
    const rounds = [...new Set(strategies.map((row) => row.round))];
    $("#strategy-heatmap").innerHTML = heatmapTable([...new Set(strategies.map((row) => row.driver))], rounds, (driver, round) => {
      const row = strategies.find((item) => item.driver === driver && item.round === round);
      const event = state.payload.events.find((item) => item.round === round);
      return row ? `<a class="heat-cell" href="${raceUrl(event, driver)}" title="${escapeHtml(row.stints.map((stint) => `${stint.compound}: ${stint.laps} laps`).join(", "))}">${escapeHtml(row.strategy)}</a>` : "—";
    }, "Driver / round");
  }

  function renderHistory() {
    const records = state.filteredRecords;
    $("#race-history").innerHTML = state.payload.events.filter((event) => event.status === "completed" && visibleRounds().includes(event.round)).map((event) => {
      const eventRows = records.filter((row) => row.round === event.round);
      const points = groupSum(eventRows, "team", pointValue)[0];
      const dnfs = eventRows.filter((row) => !["classified", "other"].includes(row.reliability)).length;
      return `<article class="race-history-card"><header><span class="round">R${event.round}</span><strong>${escapeHtml(event.name)}</strong></header><small>${escapeHtml(formatDate(event.date))} · ${escapeHtml(event.location || "")}${event.sprint ? " · Sprint" : ""}</small><dl><div><dt>Winner</dt><dd>${escapeHtml(event.winner || "—")}</dd></div><div><dt>Pole</dt><dd>${escapeHtml(event.pole || "—")}</dd></div><div><dt>Best team</dt><dd>${escapeHtml(points?.entity || "—")}</dd></div><div><dt>Conditions</dt><dd>${escapeHtml(event.weather || "unknown")}</dd></div><div><dt>DNF / DNS / DSQ</dt><dd>${dnfs}</dd></div><div><dt>Data</dt><dd>${eventRows.reduce((sum, row) => sum + row.cleanLaps, 0)} clean laps</dd></div></dl><a class="primary" href="${raceUrl(event)}">Open detailed race analysis</a></article>`;
    }).join("");
  }

  function renderPredictions() {
    $("#momentum-grid").innerHTML = state.payload.momentum.filter((row) => hasTeam(row.team)).map((row) =>
      `<article class="season-card"><span>Momentum</span><strong>${escapeHtml(row.team)} · ${row.score.toFixed(0)}</strong><small>${row.rounds.join("–") || "No recent rounds"} · ${escapeHtml(row.confidence)} confidence</small><details><summary>Components</summary>${Object.entries(row.components).map(([key, value]) => `<small>${escapeHtml(key)}: ${(value * 100).toFixed(0)}% × ${(row.weights[key] * 100).toFixed(0)}%</small>`).join("")}</details></article>`
    ).join("");
    const prediction = state.payload.prediction;
    $("#prediction-panel").innerHTML = prediction
      ? `<article class="panel"><div class="panel-head"><h3>Predicted order · ${escapeHtml(prediction.event)}</h3><span class="method-badge">prediction</span></div><p class="data-explanation"><strong>How to read:</strong> lower predicted deficit is faster. The confidence range is the plausible pace interval, not a guaranteed finishing-position range; overlapping ranges mean the model cannot clearly separate those teams. Evidence rounds are the earlier events used for the estimate.</p>${table(["Rank", "Team", "Predicted deficit", "Confidence range", "Evidence rounds", "Confidence"], prediction.teams.filter((row) => hasTeam(row.team)).map((row) => [row.rank, row.team, formatPercent(row.deficit), `${formatPercent(row.range[0])}–${formatPercent(row.range[1])}`, row.roundsUsed.join(", "), confidenceBadge(row.confidence)]))}<p class="analysis-note">Only rounds before ${prediction.targetRound} are used (${escapeHtml(prediction.leakageGuard)}). Similar circuits: ${prediction.similarCircuits?.map((item) => `${item.event} (${item.shared.join(", ")})`).join("; ") || "insufficient maintained metadata"}.</p>${renderBacktest()}</article>`
      : `<p class="unavailable">No future scheduled round exists in this selection. Historical backtest accuracy remains available in the methodology data when at least four completed rounds are present.</p>`;
  }

  function renderBacktest() {
    const backtest = state.payload.backtest;
    if (!backtest?.cases?.length) return "";
    return `<h4>Historical backtest</h4><p>Mean absolute rank error: ${backtest.meanAbsoluteRankError.toFixed(2)} across ${backtest.cases.length} team-round predictions. Every case uses only earlier rounds.</p>`;
  }

  function renderMethodology() {
    $("#methodology-content").innerHTML = `<div class="methodology-grid">${Object.entries(state.payload.methodology).map(([key, item]) =>
      `<article class="methodology-item"><h4>${escapeHtml(humanize(key))}</h4><p>${escapeHtml(item.definition)}</p>${item.formula ? `<code>${escapeHtml(item.formula)}</code>` : ""}<p><strong>Minimum:</strong> ${item.minimum ?? "documented per component"} · <strong>Limitations:</strong> ${escapeHtml(item.limitations || "See component evidence.")}</p></article>`
    ).join("")}</div><p class="analysis-note">Confidence is sample-size and coverage based: low below four representative observations, medium from four, high from eight. Every adjusted or predicted output is labelled; observed timing is never silently replaced.</p>`;
  }

  function renderCharts() {
    const key = elements.level.value === "driver" ? "driver" : "team";
    drawLineChart($("#championship-chart"), cumulativeFromRecords(key), {
      entityKey: key,
      yLabel: "Cumulative points",
      highAtTop: true,
      valueLabel: (value) => `${value.toFixed(1)} pts`,
      xLabel: (value) => `Round ${value}`,
    });
    drawLineChart($("#bump-chart"), rankFromRecords(key), {
      entityKey: key,
      yLabel: "Championship rank",
      valueLabel: (value) => `P${Math.round(value)}`,
      xLabel: (value) => `Round ${value}`,
    });
    const performanceUnit = elements.reference.value === "absolute" ? "Time (seconds)" : "Deficit (%) · lower is better";
    const performanceValue = elements.reference.value === "absolute"
      ? (value) => `${value.toFixed(3)} s`
      : (value) => `${value >= 0 ? "+" : ""}${value.toFixed(3)}%`;
    $("#qualifying-chart").setAttribute("aria-label", elements.reference.value === "absolute" ? "Representative qualifying time trend in seconds" : "Qualifying percentage deficit trend");
    $("#race-pace-chart").setAttribute("aria-label", elements.reference.value === "absolute" ? "Representative race pace trend in seconds" : "Race pace percentage deficit trend");
    drawLineChart($("#qualifying-chart"), metricEnabled("qualifyingDeficit") ? metricSeries("qualifyingDeficit", key) : [], {
      entityKey: key,
      yLabel: performanceUnit, valueLabel: performanceValue, xLabel: (value) => `Round ${value}`,
    });
    drawLineChart($("#race-pace-chart"), metricEnabled(paceMetric()) ? metricSeries(paceMetric(), key) : [], {
      entityKey: key,
      yLabel: performanceUnit, valueLabel: performanceValue, xLabel: (value) => `Round ${value}`,
    });
    drawScatter($("#pace-scatter"), elements.session.value === "combined" ? scatterData(key) : [], {
      entityKey: key,
      xLabel: "Qualifying deficit (%)", yLabel: "Race-pace deficit (%)",
      xValueLabel: (value) => `Qualifying deficit: ${value >= 0 ? "+" : ""}${value.toFixed(3)}%`,
      yValueLabel: (value) => `Race-pace deficit: ${value >= 0 ? "+" : ""}${value.toFixed(3)}%`,
    });
    drawScatter($("#conversion-chart"), state.payload.conversion.teams.filter((row) => hasTeam(row.entity)).map((row) => ({ label: row.entity, x: row.expected, y: row.actual })), {
      entityKey: "team",
      xLabel: "Expected points (model)", yLabel: "Actual points",
      xValueLabel: (value) => `${value.toFixed(1)} expected`,
      yValueLabel: (value) => `${value.toFixed(1)} actual`,
    });
  }

  function metricSeries(metric, key) {
    const entities = visibleEntities(key);
    return entities.map((entity) => {
      const byRound = [];
      visibleRounds().forEach((round) => {
        const values = state.filteredRecords.filter((row) => row[key] === entity && row.round === round && row[metric] != null).map((row) => displayMetric(row, metric));
        if (values.length) byRound.push({ x: round, y: median(values) });
      });
      const smoothed = rolling(byRound.map((point) => point.y), Number(elements.rolling.value));
      return { label: entity, points: byRound.map((point, index) => ({ x: point.x, y: smoothed[index] })) };
    }).filter((series) => series.points.length);
  }

  function cumulativeFromRecords(key) {
    const rounds = visibleRounds();
    return visibleEntities(key).map((entity) => {
      let total = 0;
      return { label: entity, points: rounds.map((round) => {
        total += state.filteredRecords.filter((row) => row[key] === entity && row.round === round).reduce((sum, row) => sum + pointValue(row), 0);
        return { x: round, y: total };
      }) };
    });
  }

  function rankFromRecords(key) {
    const cumulative = cumulativeFromRecords(key);
    const ranks = Object.fromEntries(cumulative.map((series) => [series.label, []]));
    visibleRounds().forEach((round, index) => {
      [...cumulative].sort((a, b) => b.points[index].y - a.points[index].y).forEach((series, rank) => ranks[series.label].push({ x: round, y: rank + 1 }));
    });
    return Object.entries(ranks).map(([label, points]) => ({ label, points }));
  }

  function scatterData(key) {
    return visibleEntities(key).map((entity) => ({
      label: entity,
      x: displayMetricAggregate(state.filteredRecords, entity, key, "qualifyingDeficit"),
      y: displayMetricAggregate(state.filteredRecords, entity, key, paceMetric()),
    })).filter((point) => point.x != null && point.y != null);
  }

  function drawLineChart(canvas, series, options = {}) {
    if (!canvas) return;
    const { ctx, width, height } = prepareCanvas(canvas);
    const pad = { left: 58, right: 112, top: 28, bottom: 44 };
    ctx.clearRect(0, 0, width, height);
    const points = series.flatMap((item) => item.points);
    if (!points.length) {
      disableChartInteraction(canvas);
      return drawEmpty(ctx, width, height);
    }
    const xs = points.map((point) => point.x), ys = points.map((point) => point.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    axes(ctx, width, height, pad, options.yLabel || "");
    const xScale = (value) => minX === maxX
      ? pad.left + (width - pad.left - pad.right) / 2
      : pad.left + ((value - minX) / (maxX - minX)) * (width - pad.left - pad.right);
    const yScale = (value) => {
      const normalized = ((value - minY) / (maxY - minY || 1)) * (height - pad.top - pad.bottom);
      return options.highAtTop ? height - pad.bottom - normalized : pad.top + normalized;
    };
    const interactivePoints = [];
    const endLabels = [];
    series.slice(0, 12).forEach((item, index) => {
      const colour = entityColour(item.label, options.entityKey);
      ctx.strokeStyle = colour; ctx.lineWidth = 2.5; ctx.setLineDash([]);
      ctx.beginPath();
      item.points.forEach((point, pointIndex) => {
        const x = xScale(point.x), y = yScale(point.y);
        interactivePoints.push({ label: item.label, x, y, xValue: point.x, yValue: point.y, colour });
        pointIndex ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.stroke(); ctx.setLineDash([]);
      const last = item.points.at(-1);
      if (last) endLabels.push({ label: item.label, colour, pointX: xScale(last.x), pointY: yScale(last.y), labelY: yScale(last.y) });
    });
    drawEndLabels(ctx, endLabels, width - pad.right + 9, pad.top + 4, height - pad.bottom - 3);
    ctx.fillStyle = css("--muted"); ctx.font = "11px system-ui";
    if (minX === maxX) {
      ctx.textAlign = "center";
      ctx.fillText(String(minX), xScale(minX), height - 16);
      ctx.textAlign = "left";
    } else {
      ctx.fillText(String(minX), pad.left, height - 16);
      ctx.fillText(String(maxX), width - pad.right - 18, height - 16);
    }
    ctx.fillText((options.highAtTop ? maxY : minY).toFixed(2), 8, pad.top + 4);
    ctx.fillText((options.highAtTop ? minY : maxY).toFixed(2), 8, height - pad.bottom);
    registerChartInteraction(canvas, {
      type: "line",
      points: interactivePoints,
      valueLabel: options.valueLabel || ((value) => value.toFixed(2)),
      xLabel: options.xLabel || ((value) => String(value)),
      redraw: () => drawLineChart(canvas, series, options),
    });
    drawLineHover(ctx, canvas, interactivePoints, height, pad);
  }

  function drawEndLabels(ctx, labels, x, top, bottom) {
    if (!labels.length) return;
    const gap = 13;
    const ordered = [...labels].sort((a, b) => a.labelY - b.labelY);
    ordered[0].labelY = Math.max(top, ordered[0].labelY);
    for (let index = 1; index < ordered.length; index += 1) {
      ordered[index].labelY = Math.max(ordered[index].labelY, ordered[index - 1].labelY + gap);
    }
    const overflow = ordered.at(-1).labelY - bottom;
    if (overflow > 0) ordered.forEach((item) => { item.labelY -= overflow; });
    for (let index = ordered.length - 2; index >= 0; index -= 1) {
      ordered[index].labelY = Math.min(ordered[index].labelY, ordered[index + 1].labelY - gap);
    }
    ctx.save();
    ctx.font = "10px system-ui";
    ordered.forEach((item) => {
      ctx.fillStyle = item.colour;
      ctx.beginPath(); ctx.arc(x - 4, item.labelY, 2.5, 0, Math.PI * 2); ctx.fill();
      ctx.fillText(item.label, x + 3, item.labelY + 3);
    });
    ctx.restore();
  }

  function drawScatter(canvas, points, options = {}) {
    if (!canvas) return;
    const { ctx, width, height } = prepareCanvas(canvas);
    const pad = { left: 58, right: 24, top: 28, bottom: 46 };
    ctx.clearRect(0, 0, width, height);
    if (!points.length) {
      disableChartInteraction(canvas);
      return drawEmpty(ctx, width, height);
    }
    const xs = points.map((point) => point.x), ys = points.map((point) => point.y);
    const minX = Math.min(0, ...xs), maxX = Math.max(...xs) * 1.08 || 1, minY = Math.min(0, ...ys), maxY = Math.max(...ys) * 1.08 || 1;
    axes(ctx, width, height, pad, options.yLabel || "Race-pace deficit (%)");
    ctx.fillStyle = css("--muted"); ctx.font = "11px system-ui"; ctx.fillText(options.xLabel || "Qualifying deficit (%)", width / 2 - 55, height - 10);
    const interactivePoints = [];
    points.forEach((point, index) => {
      const x = pad.left + ((point.x - minX) / (maxX - minX || 1)) * (width - pad.left - pad.right);
      const y = height - pad.bottom - ((point.y - minY) / (maxY - minY || 1)) * (height - pad.top - pad.bottom);
      const colour = entityColour(point.label, options.entityKey);
      interactivePoints.push({ ...point, xScreen: x, yScreen: y, colour });
      ctx.fillStyle = colour; ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = css("--ink"); ctx.font = "10px system-ui"; ctx.fillText(point.label, x + 8, y + 3);
    });
    registerChartInteraction(canvas, {
      type: "scatter",
      points: interactivePoints,
      xLabel: options.xValueLabel || ((value) => value.toFixed(2)),
      yLabel: options.yValueLabel || ((value) => value.toFixed(2)),
      redraw: () => drawScatter(canvas, points, options),
    });
    drawScatterHover(ctx, canvas, interactivePoints);
  }

  function createSeasonChartTooltip() {
    seasonChartTooltip = document.createElement("div");
    seasonChartTooltip.className = "season-chart-tooltip";
    seasonChartTooltip.setAttribute("role", "status");
    seasonChartTooltip.hidden = true;
    document.body.appendChild(seasonChartTooltip);
  }

  function registerChartInteraction(canvas, interaction) {
    chartInteractions.set(canvas, interaction);
    canvas.classList.add("interactive-chart");
    if (boundCharts.has(canvas)) return;
    boundCharts.add(canvas);
    canvas.addEventListener("mousemove", handleChartHover);
    canvas.addEventListener("mouseleave", clearChartHover);
  }

  function disableChartInteraction(canvas) {
    chartInteractions.delete(canvas);
    chartHover.delete(canvas);
    canvas.classList.remove("interactive-chart");
    if (seasonChartTooltip) seasonChartTooltip.hidden = true;
  }

  function handleChartHover(event) {
    const canvas = event.currentTarget;
    const interaction = chartInteractions.get(canvas);
    if (!interaction) return;
    const bounds = canvas.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    if (interaction.type === "line") {
      const nearest = interaction.points.reduce((best, point) => !best || Math.abs(point.x - x) < Math.abs(best.x - x) ? point : best, null);
      if (!nearest) return;
      chartHover.set(canvas, { type: "line", xValue: nearest.xValue });
      interaction.redraw();
      const selected = interaction.points.filter((point) => point.xValue === nearest.xValue).sort((a, b) => a.yValue - b.yValue);
      seasonChartTooltip.innerHTML = `<strong>${escapeHtml(interaction.xLabel(nearest.xValue))}</strong>${selected.slice(0, 12).map((point) => `<span><i style="--tooltip-colour:${point.colour}"></i>${escapeHtml(point.label)}<b>${escapeHtml(interaction.valueLabel(point.yValue))}</b></span>`).join("")}`;
    } else {
      const nearest = interaction.points.reduce((best, point) => {
        const distance = Math.hypot(point.xScreen - x, point.yScreen - y);
        return !best || distance < best.distance ? { point, distance } : best;
      }, null);
      if (!nearest || nearest.distance > 42) {
        clearChartHover.call(canvas, { currentTarget: canvas });
        return;
      }
      chartHover.set(canvas, { type: "scatter", label: nearest.point.label });
      interaction.redraw();
      seasonChartTooltip.innerHTML = `<strong>${escapeHtml(nearest.point.label)}</strong><span>${escapeHtml(interaction.xLabel(nearest.point.x))}</span><span>${escapeHtml(interaction.yLabel(nearest.point.y))}</span>`;
    }
    positionChartTooltip(event.clientX, event.clientY);
  }

  function clearChartHover(event) {
    const canvas = event.currentTarget || this;
    const interaction = chartInteractions.get(canvas);
    if (!interaction) return;
    chartHover.delete(canvas);
    interaction.redraw();
    seasonChartTooltip.hidden = true;
  }

  function positionChartTooltip(clientX, clientY) {
    seasonChartTooltip.hidden = false;
    const gap = 14;
    const width = seasonChartTooltip.offsetWidth;
    const height = seasonChartTooltip.offsetHeight;
    seasonChartTooltip.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, clientX + gap))}px`;
    seasonChartTooltip.style.top = `${Math.max(8, Math.min(window.innerHeight - height - 8, clientY + gap))}px`;
  }

  function drawLineHover(ctx, canvas, points, height, pad) {
    const hover = chartHover.get(canvas);
    if (!hover || hover.type !== "line") return;
    const selected = points.filter((point) => point.xValue === hover.xValue);
    if (!selected.length) return;
    ctx.save();
    ctx.strokeStyle = "rgba(22, 32, 29, .28)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(selected[0].x, pad.top); ctx.lineTo(selected[0].x, height - pad.bottom); ctx.stroke();
    ctx.setLineDash([]);
    selected.forEach((point) => {
      ctx.fillStyle = css("--panel"); ctx.strokeStyle = point.colour; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(point.x, point.y, 5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    });
    ctx.restore();
  }

  function drawScatterHover(ctx, canvas, points) {
    const hover = chartHover.get(canvas);
    if (!hover || hover.type !== "scatter") return;
    const point = points.find((item) => item.label === hover.label);
    if (!point) return;
    ctx.save();
    ctx.strokeStyle = point.colour; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(point.xScreen, point.yScreen, 10, 0, Math.PI * 2); ctx.stroke();
    ctx.restore();
  }

  function axes(ctx, width, height, pad, label) {
    ctx.strokeStyle = css("--line"); ctx.lineWidth = 1; ctx.beginPath();
    ctx.moveTo(pad.left, pad.top); ctx.lineTo(pad.left, height - pad.bottom); ctx.lineTo(width - pad.right, height - pad.bottom); ctx.stroke();
    ctx.save(); ctx.translate(14, height / 2); ctx.rotate(-Math.PI / 2); ctx.fillStyle = css("--muted"); ctx.font = "11px system-ui"; ctx.fillText(label, -label.length * 2.7, 0); ctx.restore();
  }

  function prepareCanvas(canvas) {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(320, canvas.clientWidth || canvas.width);
    const height = Math.max(260, Math.min(460, width * .52));
    canvas.width = width * ratio; canvas.height = height * ratio; canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
    return { ctx, width, height };
  }

  function drawEmpty(ctx, width, height) {
    ctx.fillStyle = css("--muted"); ctx.font = "13px system-ui"; ctx.textAlign = "center"; ctx.fillText("Insufficient comparable data for this selection", width / 2, height / 2); ctx.textAlign = "left";
  }

  function exportSection(section) {
    if (!state.payload) return;
    const rows = exportRows(section);
    if (!rows.length) return;
    const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
    const csv = [columns, ...rows.map((row) => columns.map((column) => row[column] ?? ""))].map((row) => row.map(csvCell).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${elements.year.value}-${section}.csv`; link.click(); URL.revokeObjectURL(link.href);
  }

  function exportRows(section) {
    const map = {
      overview: state.payload.insights, championship: state.filteredRecords.map(({ round, event, driver, team, points, sprintPoints, finish }) => ({ round, event, driver, team, points, sprintPoints, finish })),
      performance: state.filteredRecords.map(({ round, event, driver, team, qualifyingDeficit, racePaceDeficit, adjustedRacePaceDeficit, cleanLaps }) => ({ round, event, driver, team, qualifyingDeficit, racePaceDeficit, adjustedRacePaceDeficit, cleanLaps })),
      development: state.payload.development, teams: state.payload.conversion.teams, drivers: driverConsistency(state.filteredRecords),
      reliability: state.payload.reliability.timeline, tyres: state.payload.tyres.degradation, history: state.payload.events,
      predictions: state.payload.prediction?.teams || state.payload.momentum,
    };
    return map[section] || [];
  }

  function syncUrl() {
    if (state.route !== "season") return;
    const url = seasonUrl();
    history.replaceState({ route: "season" }, "", url);
    sessionStorage.setItem("fastf1-season-url", url);
  }

  function seasonUrl() {
    const params = new URLSearchParams({ season: elements.year.value || new Date().getFullYear() });
    return window.FastF1Routing.url("season", params);
  }

  function raceUrl(event, driver = null, team = null) {
    const params = new URLSearchParams({ year: elements.year.value, event: event?.name || "", session: "Race" });
    if (driver) params.set("driver", driver); if (team) params.set("team", team);
    return window.FastF1Routing.url("race", params);
  }

  function card(label, result, value, detail, target) {
    return `<article class="season-card"><span>${escapeHtml(label)}</span>${result ? `<strong>${escapeHtml(result)}</strong><small>${escapeHtml(value || "")}</small><small>${escapeHtml(detail || "")}</small><a href="${target}">View supporting analysis</a>` : `<strong class="unavailable">Unavailable</strong><small>Insufficient representative data.</small>`}</article>`;
  }

  function table(headers, rows) {
    if (!rows.length) return `<p class="unavailable">Insufficient comparable data for this selection.</p>`;
    const teamIndex = headers.indexOf("Team");
    return `<table class="season-table"><thead><tr>${headers.map((header, index) => `<th><button type="button" data-column="${index}" aria-label="Sort by ${escapeHtml(header)}">${escapeHtml(header)}</button></th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr style="${teamIndex >= 0 ? `--team-color:${teamColour(row[teamIndex])}` : ""}">${row.map((cell, index) => `<td>${index === teamIndex ? `<span class="team-label"><i aria-hidden="true"></i>${escapeHtml(cell)}</span>` : typeof cell === "string" && /<[^>]+>/.test(cell) ? cell : escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  function heatmapTable(entities, columns, renderer, corner = "Entity / round", columnLabel = (column) => column) {
    return `<table class="season-table"><thead><tr><th>${escapeHtml(corner)}</th>${columns.map((column) => `<th>${escapeHtml(columnLabel(column))}</th>`).join("")}</tr></thead><tbody>${entities.map((entity) => `<tr><th>${escapeHtml(entity)}</th>${columns.map((column) => `<td>${renderer(entity, column)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  function selectedValues(select) { return [...select.selectedOptions].map((option) => option.value); }
  function selectValues(select, values) { [...select.options].forEach((option) => { option.selected = values.includes(option.value); }); }
  function fillSelect(select, options, multiple = false) {
    select.innerHTML = options.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join("");
    if (!multiple && options.length) select.value = String(options[0].value);
  }
  function visibleRounds() { return [...new Set(state.filteredRecords.map((row) => row.round))].sort((a, b) => a - b); }
  function visibleEntities(key) { return [...new Set(state.filteredRecords.map((row) => row[key]).filter(Boolean))]; }
  function entityColour(entity, key) {
    if (key === "team") return teamColour(entity);
    const team = state.filteredRecords.find((row) => row.driver === entity)?.team;
    return teamColour(team);
  }
  function teamColour(team) { return window.F1Teams?.color(team) || "#6E7480"; }
  function hasTeam(team) { const selected = selectedValues(elements.teams); return !selected.length || selected.includes(team); }
  function hasDriver(driver) { const selected = selectedValues(elements.drivers); return !selected.length || selected.includes(driver); }
  function filteredTeams(rows) { return rows.filter((row) => hasTeam(row.team)); }
  function paceMetric() { return elements.valueKind.value === "adjusted" ? "adjustedRacePaceDeficit" : "racePaceDeficit"; }
  function metricEnabled(metric) {
    const session = elements.session.value;
    if (session === "sprint") return false;
    if (session === "qualifying") return metric === "qualifyingDeficit";
    if (session === "race") return metric !== "qualifyingDeficit";
    return true;
  }
  function pointValue(row) {
    const session = elements.session.value;
    if (session === "qualifying") return 0;
    if (session === "sprint") return elements.sprints.checked ? row.sprintPoints : 0;
    if (session === "race") return row.points;
    return row.points + (elements.sprints.checked ? row.sprintPoints : 0);
  }
  function displayMetric(row, metric) {
    if (elements.reference.value === "absolute") {
      const raw = metric === "qualifyingDeficit" ? "qualifyingTime" : metric === "adjustedRacePaceDeficit" ? "adjustedRacePace" : "racePace";
      return row[raw];
    }
    if (elements.reference.value === "average") {
      const all = state.filteredRecords.filter((item) => item[metric] != null).map((item) => item[metric]);
      return row[metric] - (all.length ? median(all) : 0);
    }
    return row[metric];
  }
  function displayMetricAggregate(rows, entity, key, metric) {
    const values = rows.filter((row) => row[key] === entity && row[metric] != null).map((row) => displayMetric(row, metric));
    return values.length ? median(values) : null;
  }
  function groupSum(rows, key, valueFn) {
    const sums = new Map(); rows.forEach((row) => sums.set(row[key], (sums.get(row[key]) || 0) + valueFn(row)));
    return [...sums].map(([entity, value]) => ({ entity, value })).sort((a, b) => b.value - a.value);
  }
  function rankMetric(rows, key, metric) {
    return [...new Set(rows.map((row) => row[key]))].map((entity) => ({ entity, value: metricFor(rows, entity, key, metric) })).filter((row) => row.value != null).sort((a, b) => a.value - b.value);
  }
  function rankDisplayedMetric(rows, key, metric) {
    return [...new Set(rows.map((row) => row[key]))].map((entity) => ({ entity, value: displayMetricAggregate(rows, entity, key, metric) })).filter((row) => row.value != null).sort((a, b) => a.value - b.value);
  }
  function metricFor(rows, entity, key, metric) { const values = rows.filter((row) => row[key] === entity && row[metric] != null).map((row) => row[metric]); return values.length ? median(values) : null; }
  function median(values) { const sorted = [...values].sort((a, b) => a - b); const middle = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2; }
  function compareNullable(left, right) {
    if (left == null && right == null) return 0;
    if (left == null) return 1;
    if (right == null) return -1;
    return left - right;
  }
  function compareNullableDescending(left, right) {
    if (left == null && right == null) return 0;
    if (left == null) return 1;
    if (right == null) return -1;
    return right - left;
  }
  function rolling(values, window) { return values.map((_, index) => median(values.slice(Math.max(0, index - window + 1), index + 1))); }
  function driverConsistency(records) {
    return [...new Set(records.map((row) => row.driver))].map((driver) => {
      const values = records.filter((row) => row.driver === driver && row[paceMetric()] != null).map((row) => row[paceMetric()]);
      const centre = values.length ? median(values) : 0; const mad = values.length ? median(values.map((value) => Math.abs(value - centre))) : Infinity;
      return { driver, mad, events: values.length, confidence: values.length >= 8 ? "high" : values.length >= 4 ? "medium" : "low" };
    }).filter((row) => Number.isFinite(row.mad)).sort((a, b) => a.mad - b.mad);
  }
  function teammateDelta(driver, team) {
    const deltas = []; visibleRounds().forEach((round) => {
      const own = state.filteredRecords.find((row) => row.driver === driver && row.round === round);
      const mate = state.filteredRecords.find((row) => row.team === team && row.driver !== driver && row.round === round);
      if (own?.qualifyingDeficit != null && mate?.qualifyingDeficit != null) deltas.push(own.qualifyingDeficit - mate.qualifyingDeficit);
    }); return deltas.length ? median(deltas) : null;
  }
  function countResults(entity, key, maxPosition) { return new Set(state.filteredRecords.filter((row) => row[key] === entity && row.finish && row.finish <= maxPosition).map((row) => row.round)).size; }
  function confidenceBadge(value) { return `<span class="method-badge">${escapeHtml(value || "low")}</span>`; }
  function nullablePercent(value) { return value == null ? "—" : formatPercent(value); }
  function nullablePerformance(value) { return value == null ? "—" : formatPerformance(value); }
  function formatPerformance(value) { return elements.reference.value === "absolute" ? `${value.toFixed(3)} s` : formatPercent(value); }
  function nullableSigned(value, unit) { return value == null ? "—" : signed(value, 3, unit); }
  function formatPercent(value) { return value == null ? "—" : `${value.toFixed(3)}%`; }
  function formatPoints(value) { return value == null ? null : `${value.toFixed(0)} points`; }
  function signed(value, digits = 2, unit = "") { return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}${unit}`; }
  function humanize(value) { return value.replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (char) => char.toUpperCase()); }
  function formatDate(value) { if (!value) return "date unavailable"; const date = new Date(value); return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleDateString(undefined, { dateStyle: "medium" }); }
  function setStatus(message, error = false) { elements.status.textContent = message; elements.status.classList.toggle("error", error); }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function csvCell(value) { const string = typeof value === "object" ? JSON.stringify(value) : String(value); return `"${string.replaceAll('"', '""')}"`; }
  function debounce(fn, wait) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; }
  function delay(milliseconds) { return new Promise((resolve) => setTimeout(resolve, milliseconds)); }
  function sortTable(tableElement, column) {
    const body = tableElement?.tBodies?.[0]; if (!body) return;
    const rows = [...body.rows]; const ascending = tableElement.dataset.sortColumn !== String(column) || tableElement.dataset.sortDirection !== "asc";
    rows.sort((a, b) => {
      const left = a.cells[column]?.textContent.trim() || "", right = b.cells[column]?.textContent.trim() || "";
      const leftNumber = Number.parseFloat(left.replace(/[^\d.+-]/g, "")), rightNumber = Number.parseFloat(right.replace(/[^\d.+-]/g, ""));
      const comparison = Number.isFinite(leftNumber) && Number.isFinite(rightNumber) ? leftNumber - rightNumber : left.localeCompare(right);
      return ascending ? comparison : -comparison;
    });
    rows.forEach((row) => body.appendChild(row)); tableElement.dataset.sortColumn = String(column); tableElement.dataset.sortDirection = ascending ? "asc" : "desc";
  }
  async function getJson(path) {
    const response = await fetch(`${apiBase}${path}`);
    if (!response.ok) { let message = `Request failed (${response.status})`; try { message = (await response.json()).detail || message; } catch (_) {} throw new Error(message); }
    return response.json();
  }
  function escapeHtml(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }
})();
