"use strict";

const C = { teal: "#57d8c3", gold: "#efb45b", red: "#ed7d76", blue: "#7ab6ff", muted: "#96aabd", grid: "#294357", text: "#f3f5ee" };
const state = { matches: [], atlas: null, players: null, report: null, manifest: null, scenarioModel: null,
  replayCache: {}, trace: [], match: null, selected: 0, loadToken: 0, scenarioChoice: [4, 0],
  playerType: "batters", timer: null, charts: {} };
const $ = id => document.getElementById(id);
const BUILD_VERSION = document.documentElement.dataset.build || "";
const fmt = n => new Intl.NumberFormat("en-US").format(n);
const pct = n => `${(n * 100).toFixed(1)}%`;
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const shortTeam = name => ({ "Royal Challengers Bengaluru": "RCB", "Chennai Super Kings": "CSK", "Mumbai Indians": "MI", "Kolkata Knight Riders": "KKR", "Sunrisers Hyderabad": "SRH", "Punjab Kings": "PBKS", "Delhi Capitals": "DC", "Rajasthan Royals": "RR", "Gujarat Titans": "GT", "Lucknow Super Giants": "LSG" }[name] || name);

async function fetchJson(path) {
  const url = BUILD_VERSION ? `${path}?v=${BUILD_VERSION}` : path;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

function chart(id) {
  if (!state.charts[id]) state.charts[id] = echarts.init($(id), null, { renderer: "canvas" });
  return state.charts[id];
}

const axisLabel = { color: C.muted, fontSize: 11 };
const splitLine = { show: true, lineStyle: { color: C.grid, opacity: .55 } };
const tooltipBase = { backgroundColor: "#122d3e", borderColor: "#427080", confine: true,
  textStyle: { color: C.text, fontSize: 12 },
  extraCssText: "box-shadow:0 14px 30px #0008;border-radius:8px;max-width:min(260px,calc(100vw - 70px));white-space:normal;" };

function bootMetrics() {
  $("metricMatches").textContent = fmt(state.manifest.matches);
  $("metricBalls").textContent = fmt(state.manifest.deliveries);
  $("metricReplays").textContent = fmt(state.matches.filter(m => m.eligible).length);
  $("metricBrier").textContent = state.report.chase.calibrated_logistic.brier.toFixed(4);
}

function setupMatchControls() {
  const seasons = [...new Set(state.matches.map(m => m.season))].sort((a, b) => b - a);
  $("seasonSelect").innerHTML = seasons.map(y => `<option value="${y}">${y}</option>`).join("");
  const teams = [...new Set(state.matches.flatMap(m => [m.team1, m.team2]))].sort();
  $("teamSelect").innerHTML = '<option value="all">All teams</option>' + teams.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
  $("seasonSelect").addEventListener("change", updateMatchList);
  $("teamSelect").addEventListener("change", updateMatchList);
  $("matchSelect").addEventListener("change", () => loadMatch(Number($("matchSelect").value)));
  $("ballSlider").addEventListener("input", event => selectMoment(Number(event.target.value)));
  $("playButton").addEventListener("click", togglePlayback);
  updateMatchList();
}

function clearMatchView(title, description) {
  state.match = null;
  state.trace = [];
  state.selected = 0;
  $("errorBanner").hidden = true;
  $("matchDate").textContent = "MATCH REPLAY";
  $("matchTitle").textContent = title;
  $("matchSub").textContent = description;
  $("matchResult").textContent = "—";
  $("matchTarget").textContent = "—";
  $("momentOver").textContent = "—";
  $("momentScore").textContent = "—";
  $("momentEvent").textContent = "Choose a match to inspect its deliveries.";
  $("momentProbability").textContent = "—";
  $("momentBarFill").style.width = "0%";
  $("momentSwing").textContent = "—";
  $("ballSlider").max = 0;
  $("ballSlider").value = 0;
  $("playButton").disabled = true;
  $("turningPoints").innerHTML = "";
  chart("replayChart").clear();
  renderScenario();
}

function updateMatchList() {
  stopPlayback();
  const year = Number($("seasonSelect").value);
  const team = $("teamSelect").value;
  const choices = state.matches.filter(m => m.eligible && m.season === year && (team === "all" || m.team1 === team || m.team2 === team));
  $("matchSelect").innerHTML = choices.map(m => `<option value="${m.id}">${escapeHtml(m.date)} · ${escapeHtml(shortTeam(m.team1))} vs ${escapeHtml(shortTeam(m.team2))}${m.stage ? ` · ${escapeHtml(m.stage)}` : ""}</option>`).join("");
  if (!choices.length) {
    state.loadToken++;
    clearMatchView("No standard chase in this filter", "Try another team or season.");
    return;
  }
  const preferred = choices.find(m => m.id === 1535465) || choices[0];
  $("matchSelect").value = preferred.id;
  loadMatch(preferred.id);
}

async function loadMatch(id) {
  stopPlayback();
  const match = state.matches.find(m => m.id === id);
  if (!match) return;
  const token = ++state.loadToken;
  clearMatchView("Loading match…", "Fetching the season replay.");
  state.match = match;
  const year = String(match.season);
  try {
    if (!state.replayCache[year]) state.replayCache[year] = await fetchJson(`./data/replays/${year}.json`);
  } catch (error) {
    if (token === state.loadToken) {
      clearMatchView("Replay unavailable", "Try selecting the match again.");
      $("errorBanner").hidden = false;
      $("errorBanner").textContent = `Could not load ${year} replay data: ${error.message}`;
    }
    return;
  }
  if (token !== state.loadToken) return;
  state.trace = state.replayCache[year][String(id)] || [];
  if (!state.trace.length) {
    clearMatchView("Replay unavailable", "This match has no replay data.");
    $("errorBanner").hidden = false;
    $("errorBanner").textContent = `No replay found for match ${id}.`;
    return;
  }
  $("errorBanner").hidden = true;
  $("matchDate").textContent = `${match.date} · ${match.stage || `SEASON ${match.season}`} · #${match.id}`.toUpperCase();
  $("matchTitle").textContent = `${match.team1}  vs  ${match.team2}`;
  $("matchSub").textContent = `${match.venue || "Venue unlisted"} · ${match.batting} chasing`;
  $("matchResult").textContent = match.winner ? `${shortTeam(match.winner)} won` : "No result";
  $("matchTarget").textContent = `Target ${match.target} · Chase ${match.chase_runs}`;
  $("ballSlider").max = Math.max(0, state.trace.length - 1);
  $("playButton").disabled = false;
  renderReplay();
  renderTurningPoints();
  let informativeMoment = 0;
  let nearestEvenChance = Infinity;
  for (let i = 0; i < state.trace.length - 1; i++) {
    if (state.trace[i][1] < 6) continue;
    const distance = Math.abs(state.trace[i][4] - 0.5);
    if (distance < nearestEvenChance) {
      informativeMoment = i;
      nearestEvenChance = distance;
    }
  }
  selectMoment(informativeMoment);
}

function overText(legal) { return `${Math.floor(legal / 6)}.${legal % 6}`; }

function renderReplay() {
  const trace = state.trace;
  const logistic = trace.map((p, i) => [p[1] / 6, +(p[4] * 100).toFixed(1), i]);
  const boosted = trace.map((p, i) => [p[1] / 6, +(p[5] * 100).toFixed(1), i]);
  const wickets = trace.map((p, i) => p[9] ? [p[1] / 6, +(p[4] * 100).toFixed(1), i] : null).filter(Boolean);
  const sixes = trace.map((p, i) => p[8] >= 6 ? [p[1] / 6, +(p[4] * 100).toFixed(1), i] : null).filter(Boolean);
  const option = {
    animationDuration: 350, grid: { left: 44, right: 20, top: 35, bottom: 47 },
    tooltip: { ...tooltipBase, trigger: "axis", axisPointer: { type: "cross", lineStyle: { color: "#7da9b7" } },
      formatter: params => {
        const entry = params.find(x => x.seriesName === "Calibrated logistic") || params[0];
        const point = trace[entry.data[2]];
        return `<b>After ${overText(point[1])} overs · ${point[2]}/${point[3]}</b><br>${escapeHtml(point[6])} facing ${escapeHtml(point[7])}<br><span style="color:${C.teal}">●</span> Logistic ${pct(point[4])}<br><span style="color:${C.gold}">●</span> Boosted ${pct(point[5])}`;
      } },
    xAxis: { type: "value", min: 0, max: state.match.overs, name: "Overs", nameLocation: "middle", nameGap: 28,
      nameTextStyle: { color: C.muted }, axisLabel: { ...axisLabel, formatter: v => v.toFixed(0) },
      axisLine: { lineStyle: { color: C.grid } }, splitLine },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { ...axisLabel, formatter: v => `${v}%` },
      axisLine: { show: false }, splitLine },
    series: [
      { id: "logistic", name: "Calibrated logistic", type: "line", data: logistic, showSymbol: false, lineStyle: { width: 3, color: C.teal }, itemStyle: { color: C.teal }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "#57d8c32f" }, { offset: 1, color: "#57d8c300" }]) } },
      { id: "boosted", name: "Boosted model", type: "line", data: boosted, showSymbol: false, lineStyle: { width: 1.8, color: C.gold, type: "dashed" }, itemStyle: { color: C.gold } },
      { id: "wickets", name: "Wicket", type: "scatter", data: wickets, symbol: "diamond", symbolSize: 11, itemStyle: { color: C.red, borderColor: "#fff", borderWidth: 1 }, z: 5 },
      { id: "sixes", name: "Six or more", type: "scatter", data: sixes, symbolSize: 8, itemStyle: { color: C.gold }, z: 4 },
    ],
  };
  const instance = chart("replayChart");
  instance.setOption(option, true);
  instance.off("click");
  instance.on("click", params => { if (params.data && Number.isInteger(params.data[2])) selectMoment(params.data[2]); });
}

function selectMoment(index) {
  if (!state.trace.length) return;
  state.selected = Math.max(0, Math.min(index, state.trace.length - 1));
  const p = state.trace[state.selected];
  const previous = state.selected ? state.trace[state.selected - 1][4] : p[4];
  const shift = p[4] - previous;
  $("ballSlider").value = String(state.selected);
  $("momentOver").textContent = `OVER ${overText(p[1])} · DELIVERY ${p[0]}`;
  $("momentScore").textContent = `${p[2]}/${p[3]}`;
  $("momentEvent").textContent = `${p[6]} vs ${p[7]} · ${p[8]} run${p[8] === 1 ? "" : "s"}${p[9] ? ` · ${p[9]}` : ""}`;
  $("momentProbability").textContent = pct(p[4]);
  $("momentBarFill").style.width = pct(p[4]);
  $("momentSwing").textContent = `${shift >= 0 ? "+" : ""}${(shift * 100).toFixed(1)} pp`;
  $("momentSwing").style.color = shift >= 0 ? C.teal : C.red;
  renderScenario();
}

function calibratedProbability(features) {
  const model = state.scenarioModel;
  let z = model.intercept;
  for (let i = 0; i < features.length; i++) {
    z += model.coefficients[i] * (features[i] - model.mean[i]) / model.scale[i];
  }
  const raw = 1 / (1 + Math.exp(-Math.max(-50, Math.min(50, z))));
  const xs = model.thresholds, ys = model.calibrated_values;
  if (raw <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) {
    if (raw <= xs[i]) {
      const fraction = (raw - xs[i - 1]) / (xs[i] - xs[i - 1]);
      return ys[i - 1] + fraction * (ys[i] - ys[i - 1]);
    }
  }
  return ys[ys.length - 1];
}

function nextBallProbability(nextRuns, nextWicket) {
  const point = state.trace[state.selected];
  const runs = point[2] + nextRuns;
  const wickets = point[3] + nextWicket;
  const legal = point[1] + 1;
  const limit = state.match.overs * 6;
  if (runs >= state.match.target) return 1;
  if (wickets >= 10 || legal >= limit) return 0;
  let recentRuns = nextRuns, recentWickets = nextWicket;
  for (let i = state.selected; i >= Math.max(0, state.selected - 10); i--) {
    recentRuns += state.trace[i][8];
    recentWickets += state.trace[i][3] - (i ? state.trace[i - 1][3] : 0);
  }
  const needed = state.match.target - runs;
  const left = limit - legal;
  return calibratedProbability([
    2, state.match.target, runs, wickets, legal, left, needed,
    6 * runs / legal, 6 * needed / left, recentRuns, recentWickets,
  ]);
}

function renderScenario() {
  if (!state.trace.length || state.selected === state.trace.length - 1) {
    chart("scenarioChart").clear();
    $("scenarioEnd").hidden = false;
    $("scenarioEnd").textContent = state.trace.length
      ? "Match complete. Select an earlier delivery to explore a next-ball scenario."
      : "Choose a match to explore next-ball scenarios.";
    $("scenarioCurrent").textContent = state.trace.length ? pct(state.trace[state.selected][4]) : "—";
    $("scenarioChoice").textContent = "Next ball";
    $("scenarioProjected").textContent = "—";
    $("scenarioDelta").textContent = "—";
    $("scenarioNote").textContent = "Select an earlier delivery to explore a next-ball scenario.";
    return;
  }
  $("scenarioEnd").hidden = true;
  const mobile = window.innerWidth < 600;
  const runOptions = [0, 1, 2, 3, 4, 6];
  const current = state.trace[state.selected][4];
  const data = [];
  for (let wicket = 0; wicket <= 1; wicket++) {
    runOptions.forEach((runs, x) => {
      const probability = nextBallProbability(runs, wicket);
      const chosen = runs === state.scenarioChoice[0] && wicket === state.scenarioChoice[1];
      data.push({
        value: mobile ? [wicket, x, +(probability * 100).toFixed(1)] : [x, wicket, +(probability * 100).toFixed(1)],
        probability, runs, wicket,
        itemStyle: { borderColor: chosen ? C.text : "#0b1c2a", borderWidth: 3 },
      });
    });
  }
  const instance = chart("scenarioChart");
  instance.setOption({
    animation: false,
    grid: { left: mobile ? 55 : 92, right: 15, top: 18, bottom: mobile ? 45 : 38 },
    tooltip: { ...tooltipBase, formatter: item => {
      return (item.data.wicket ? "Wicket" : "No wicket") + " · " + item.data.runs +
        " runs<br>Chase win: " + pct(item.data.probability);
    } },
    xAxis: { type: "category", name: mobile ? "Wicket on next ball?" : "Runs on next legal ball",
      nameLocation: "middle", nameGap: 25, data: mobile ? ["No", "Yes"] : runOptions.map(String),
      nameTextStyle: { color: C.muted, fontSize: 11 }, axisLabel,
      axisLine: { lineStyle: { color: C.grid } } },
    yAxis: { type: "category", data: mobile ? runOptions.map(String) : ["No wicket", "Wicket"],
      name: mobile ? "Runs" : "", nameTextStyle: { color: C.muted, fontSize: 11 }, axisLabel,
      axisLine: { lineStyle: { color: C.grid } } },
    visualMap: { min: 0, max: 100, show: false, inRange: { color: ["#a94e54", "#735f57", "#347c83", "#57d8c3"] } },
    series: [{ type: "heatmap", data, label: { show: true, color: C.text, fontWeight: "bold", fontSize: mobile ? 10 : 11,
      formatter: item => item.data.value[2].toFixed(1) + "%" },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "#0009" } } }],
  }, true);
  instance.off("click");
  instance.on("click", item => {
    if (!item.data || !item.data.value) return;
    state.scenarioChoice = [item.data.runs, item.data.wicket];
    renderScenario();
  });
  const selected = nextBallProbability(...state.scenarioChoice);
  const delta = 100 * (selected - current);
  const displayedDelta = Math.abs(delta) < 0.05 ? 0 : delta;
  $("scenarioCurrent").textContent = pct(current);
  $("scenarioChoice").textContent = state.scenarioChoice[0] + " runs · " +
    (state.scenarioChoice[1] ? "wicket" : "no wicket");
  $("scenarioProjected").textContent = pct(selected);
  $("scenarioDelta").textContent = (displayedDelta > 0 ? "+" : "") + displayedDelta.toFixed(1) + " pp";
  $("scenarioDelta").style.color = displayedDelta >= 0 ? C.teal : C.red;
  $("scenarioNote").textContent = "One legal ball from " + state.trace[state.selected][2] + "/" +
    state.trace[state.selected][3] + " chasing " + state.match.target + ".";
}

function renderTurningPoints() {
  const points = state.trace.slice(1, -1).map((p, i) => ({ index: i + 1, p, swing: p[4] - state.trace[i][4] }))
    .sort((a, b) => Math.abs(b.swing) - Math.abs(a.swing)).slice(0, 5);
  $("turningPoints").innerHTML = points.map(item => `<button type="button" class="turning-item ${item.swing < 0 ? "negative" : ""}" data-index="${item.index}"><strong>${item.swing > 0 ? "+" : ""}${(item.swing * 100).toFixed(1)} pp</strong><span>Over ${overText(item.p[1])} · ${escapeHtml(item.p[6])}${item.p[9] ? ` · ${escapeHtml(item.p[9])}` : ` · ${item.p[8]} runs`}</span></button>`).join("");
  $("turningPoints").querySelectorAll("button").forEach(button => button.addEventListener("click", () => selectMoment(Number(button.dataset.index))));
}

function stopPlayback() { if (state.timer) { clearInterval(state.timer); state.timer = null; } $("playButton").innerHTML = "▶ &nbsp;Play replay"; }
function togglePlayback() {
  if (!state.trace.length) return;
  if (state.timer) return stopPlayback();
  selectMoment(0);
  $("playButton").textContent = "Ⅱ  Pause";
  state.timer = setInterval(() => {
    if (state.selected >= state.trace.length - 1) return stopPlayback();
    selectMoment(state.selected + 1);
  }, 115);
}

function renderEra() {
  const seasons = state.atlas.seasons;
  const years = seasons.map(s => String(s.year));
  const first = seasons[0], last = seasons[seasons.length - 1];
  const delta = last.run_rate - first.run_rate;
  $("eraChange").textContent = `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`;
  $("eraNarrative").textContent = `League scoring moved from ${first.run_rate} runs per over in ${first.year} to ${last.run_rate} in ${last.year}. Average first innings scores shifted from ${first.avg_first_innings} to ${last.avg_first_innings}.`;
  chart("eraChart").setOption({
    grid: { left: 50, right: 55, top: 38, bottom: 42 }, tooltip: { ...tooltipBase, trigger: "axis" },
    legend: { data: ["Run rate", "First innings average"], top: 0, right: 0, textStyle: { color: C.muted, fontSize: 11 } },
    xAxis: { type: "category", data: years,
      axisLabel: { ...axisLabel, interval: 0,
        formatter: (value, index) => index === 0 || index === years.length - 1 || index % 4 === 0 ? value : "" },
      axisLine: { lineStyle: { color: C.grid } } },
    yAxis: [{ type: "value", min: 6, max: 12, axisLabel, splitLine }, { type: "value", min: 100, max: 220, axisLabel, splitLine: { show: false } }],
    series: [
      { name: "Run rate", type: "line", smooth: .25, data: seasons.map(s => s.run_rate), symbolSize: 5, lineStyle: { color: C.teal, width: 3 }, itemStyle: { color: C.teal } },
      { name: "First innings average", type: "line", yAxisIndex: 1, smooth: .25, data: seasons.map(s => s.avg_first_innings), symbolSize: 5, lineStyle: { color: C.gold, width: 2 }, itemStyle: { color: C.gold } },
    ]
  });
  $("phaseMetric").addEventListener("change", renderPhase);
  renderPhase();
  renderTeams();
}

function renderPhase() {
  const metric = $("phaseMetric").value;
  const years = state.atlas.seasons.map(s => String(s.year));
  const phases = ["Powerplay", "Middle", "Death"];
  const data = state.atlas.phases.map(p => [years.indexOf(String(p.year)), phases.indexOf(p.phase), p[metric]]);
  const vals = data.map(d => d[2]);
  const min = Math.floor(Math.min(...vals) * 10) / 10, max = Math.ceil(Math.max(...vals) * 10) / 10;
  chart("phaseChart").setOption({
    grid: { left: 85, right: 15, top: 20, bottom: 85 }, tooltip: { ...tooltipBase,
      formatter: x => `<b>${years[x.data[0]]} · ${phases[x.data[1]]}</b><br>${metric.replace("_", " ")}: ${x.data[2]}` },
    xAxis: { type: "category", data: years, axisLabel: { ...axisLabel, rotate: 45, interval: 1 }, axisLine: { lineStyle: { color: C.grid } } },
    yAxis: { type: "category", data: phases, axisLabel, axisLine: { lineStyle: { color: C.grid } } },
    visualMap: { min, max, calculable: true, orient: "horizontal", left: "center", bottom: 0,
      textStyle: { color: C.muted }, inRange: { color: ["#173349", "#227b81", "#efb45b"] } },
    series: [{ type: "heatmap", data, itemStyle: { borderColor: "#0b1c2a", borderWidth: 3, borderRadius: 3 }, emphasis: { itemStyle: { borderColor: C.text, borderWidth: 1 } } }]
  }, true);
}

function renderTeams() {
  const years = state.atlas.seasons.map(s => String(s.year));
  const teamTotals = {};
  state.atlas.teams.forEach(t => teamTotals[t.team] = (teamTotals[t.team] || 0) + t.played);
  const teams = Object.keys(teamTotals).sort((a, b) => teamTotals[b] - teamTotals[a]);
  const data = state.atlas.teams.map(t => [years.indexOf(String(t.year)), teams.indexOf(t.team), t.win_pct, t.played, t.wins]);
  chart("teamChart").setOption({
    grid: { left: 150, right: 10, top: 15, bottom: 85 }, tooltip: { ...tooltipBase,
      formatter: x => `<b>${escapeHtml(teams[x.data[1]])} · ${years[x.data[0]]}</b><br>${x.data[4]} wins / ${x.data[3]} matches · ${x.data[2]}%` },
    xAxis: { type: "category", data: years, axisLabel: { ...axisLabel, rotate: 45, interval: 1 }, axisLine: { lineStyle: { color: C.grid } } },
    yAxis: { type: "category", data: teams, axisLabel: { color: C.muted, fontSize: 10, formatter: shortTeam }, axisLine: { lineStyle: { color: C.grid } } },
    visualMap: { min: 0, max: 100, calculable: true, orient: "horizontal", left: "center", bottom: 0,
      textStyle: { color: C.muted }, inRange: { color: ["#a94e54", "#385872", "#4dc9b5"] } },
    series: [{ type: "heatmap", data, itemStyle: { borderColor: "#0b1c2a", borderWidth: 2 } }]
  }, true);
}

function setupPlayers() {
  $("battersTab").addEventListener("click", () => setPlayerType("batters"));
  $("bowlersTab").addEventListener("click", () => setPlayerType("bowlers"));
  $("minBalls").addEventListener("change", renderPlayers);
  renderPlayers();
}
function setPlayerType(type) {
  state.playerType = type;
  $("battersTab").classList.toggle("active", type === "batters");
  $("bowlersTab").classList.toggle("active", type === "bowlers");
  renderPlayers();
}
function renderPlayers() {
  const batting = state.playerType === "batters";
  const rows = state.players[state.playerType].filter(p => p.balls >= Number($("minBalls").value));
  $("playerKicker").textContent = batting ? "BATTING FINGERPRINTS" : "BOWLING FINGERPRINTS";
  $("playerTitle").textContent = batting ? "Power meets volume" : "Control meets strike rate";
  $("playerCaption").textContent = batting ? "Strike rate versus boundary share. Dot size tracks career runs." : "Economy versus wickets per 100 legal balls. Dot size tracks career wickets.";
  const points = rows.map(p => ({ value: [batting ? p.strike_rate : p.economy, batting ? p.boundary_pct : p.wickets_per_100, p.last, batting ? p.runs : p.wickets],
    name: p.name, player: p, symbolSize: Math.max(6, Math.min(30, Math.sqrt(batting ? p.runs : p.wickets * 16) * .38)),
    itemStyle: { color: p.last >= 2025 ? C.teal : p.last >= 2019 ? C.gold : "#6f91ae", opacity: .78, borderColor: "#d9f4ea", borderWidth: .5 } }));
  chart("playerChart").setOption({
    grid: { left: 62, right: 22, top: 22, bottom: 54 },
    tooltip: { ...tooltipBase, formatter: x => { const p = x.data.player; return `<b>${escapeHtml(p.name)}</b><br>${p.first}–${p.last} · ${fmt(p.matches)} matches<br>${batting ? `Runs: ${fmt(p.runs)} · SR: ${p.strike_rate} · boundary: ${p.boundary_pct}%` : `Wickets: ${p.wickets} · economy: ${p.economy} · W/100: ${p.wickets_per_100}`}${p.recent_context_lift != null ? `<br>Recent context lift: ${p.recent_context_lift > 0 ? "+" : ""}${p.recent_context_lift}/100` : ""}${p.recent_run_suppression != null ? `<br>Recent run suppression: ${p.recent_run_suppression > 0 ? "+" : ""}${p.recent_run_suppression}/100` : ""}`; } },
    xAxis: { type: "value", name: batting ? "Strike rate" : "Economy", nameLocation: "middle", nameGap: 31,
      nameTextStyle: { color: C.muted }, axisLabel, splitLine, scale: true },
    yAxis: { type: "value", name: batting ? "Boundary %" : "Wickets / 100 balls", nameLocation: "middle", nameGap: 47,
      nameTextStyle: { color: C.muted }, axisLabel, splitLine, scale: true },
    series: [{ type: "scatter", data: points, emphasis: { focus: "self", scale: 1.5 }, animationDuration: 300 }]
  }, true);
  const field = batting ? "recent_context_lift" : "recent_run_suppression";
  $("leaderboardTitle").textContent = batting ? "Context lift" : "Run suppression";
  $("leaderboardDescription").textContent = batting ? "Observed batter runs above next-ball expectation per 100 legal balls, with small-sample shrinkage." : "Batter runs conceded below next-ball expectation per 100 legal balls, with small-sample shrinkage.";
  const leaders = state.players[state.playerType].filter(p => p[field] != null && p.recent_balls >= 100)
    .sort((a, b) => b[field] - a[field]).slice(0, 8);
  $("leaderboard").innerHTML = leaders.map((p, i) => `<div class="leader-row"><span class="rank">${String(i + 1).padStart(2, "0")}</span><div class="name">${escapeHtml(p.name)}<small>${fmt(p.recent_balls)} recent legal balls</small></div><span class="value">${p[field] > 0 ? "+" : ""}${p[field]}</span></div>`).join("");
}

function renderAudit() {
  const report = state.report;
  const points = report.chase.reliability.map(x => [+(x.predicted * 100).toFixed(1), +(x.observed * 100).toFixed(1), x.states]);
  chart("reliabilityChart").setOption({
    grid: { left: 46, right: 22, top: 25, bottom: 45 }, tooltip: { ...tooltipBase, formatter: x => `${x.data[2]} states<br>Forecast: ${x.data[0]}%<br>Observed: ${x.data[1]}%` },
    xAxis: { type: "value", min: 0, max: 100, name: "Forecast %", nameLocation: "middle", nameGap: 27, nameTextStyle: { color: C.muted }, axisLabel, splitLine },
    yAxis: { type: "value", min: 0, max: 100, name: "Observed %", nameLocation: "middle", nameGap: 31, nameTextStyle: { color: C.muted }, axisLabel, splitLine },
    series: [{ type: "line", data: [[0, 0], [100, 100]], showSymbol: false, lineStyle: { type: "dashed", color: C.muted, width: 1 }, silent: true },
      { type: "scatter", data: points, symbolSize: x => Math.max(9, Math.min(25, Math.sqrt(x[2]) * .26)), itemStyle: { color: C.teal, borderColor: "#d3fff5", borderWidth: 1.2 } }]
  });
  const features = report.chase.feature_importance.filter(f => f.brier_increase > 0).slice(0, 7).reverse();
  chart("importanceChart").setOption({
    grid: { left: 135, right: 25, top: 20, bottom: 30 }, tooltip: { ...tooltipBase, formatter: x => `${x.name}<br>+${x.value.toFixed(4)} Brier` },
    xAxis: { type: "value", splitNumber: 2,
      axisLabel: { color: C.muted, hideOverlap: true, formatter: v => v.toFixed(2) }, splitLine },
    yAxis: { type: "category", data: features.map(f => f.feature.replaceAll("_", " ")), axisLabel: { color: C.muted, fontSize: 10 }, axisLine: { show: false } },
    series: [{ type: "bar", data: features.map(f => f.brier_increase), barWidth: 15, itemStyle: { color: C.gold, borderRadius: [0, 4, 4, 0] } }]
  });
  const logistic = report.chase.calibrated_logistic, boosted = report.chase.gradient_boosting_calibrated;
  $("modelScoreboard").innerHTML = `<div class="score-row"><span>Calibrated logistic<small>Replay model · Brier</small></span><strong>${logistic.brier.toFixed(4)}</strong></div><div class="score-row loss"><span>Calibrated boosted trees<small>2024 validation winner · Brier</small></span><strong>${boosted.brier.toFixed(4)}</strong></div><div class="score-row"><span>Logistic discrimination<small>Area under ROC curve</small></span><strong>${logistic.auc.toFixed(3)}</strong></div><div class="score-row"><span>Match-weighted Brier<small>Each match carries equal weight</small></span><strong>${logistic.match_weighted_brier.toFixed(4)}</strong></div>`;
  const ball = report.next_ball;
  $("nextBallScoreboard").innerHTML = `<div class="score-row"><span>Runs model MSE<small>Constant-mean baseline ${ball.runs_constant_baseline_mse.toFixed(3)}</small></span><strong>${ball.runs_mse.toFixed(3)}</strong></div><div class="score-row loss"><span>Runs model MAE<small>Constant-mean baseline ${ball.runs_constant_baseline_mae.toFixed(3)}</small></span><strong>${ball.runs_mae.toFixed(3)}</strong></div><div class="score-row"><span>Wicket risk Brier<small>Constant-rate baseline ${ball.wicket_constant_baseline_brier.toFixed(4)}</small></span><strong>${ball.wicket_brier.toFixed(4)}</strong></div><div class="score-row"><span>Held-period legal balls<small>2025–26</small></span><strong>${fmt(ball.test_legal_balls)}</strong></div>`;
}

async function init() {
  try {
    [state.manifest, state.matches, state.atlas, state.players, state.report, state.scenarioModel] = await Promise.all([
      fetchJson("./data/manifest.json"), fetchJson("./data/matches.json"), fetchJson("./data/atlas.json"),
      fetchJson("./data/players.json"), fetchJson("./data/report.json"), fetchJson("./data/scenario_model.json")
    ]);
    bootMetrics();
    setupMatchControls();
    renderEra();
    setupPlayers();
    renderAudit();
    window.addEventListener("resize", () => {
      Object.values(state.charts).forEach(c => c.resize());
      if (state.trace.length) renderScenario();
    });
  } catch (error) {
    $("errorBanner").hidden = false;
    $("errorBanner").textContent = `IPL Decision Lab could not load its data: ${error.message}. Serve the repository with make serve.`;
    console.error(error);
  }
}

init();
