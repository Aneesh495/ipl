// DOM-free smoke test for the static app's data loading and chart configurations.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..', 'docs');
const elements = new Map();
class Element {
  constructor(id) {
    this.id = id;
    this.value = id === 'seasonSelect' ? '2026' : id === 'teamSelect' ? 'all' : id === 'minBalls' ? '300' : id === 'phaseMetric' ? 'run_rate' : '';
    this.textContent = '';
    this.style = {};
    this.events = {};
    this.hidden = true;
    this.classList = { toggle() {} };
  }
  set innerHTML(value) { this._html = value; }
  get innerHTML() { return this._html || ''; }
  addEventListener(name, handler) { this.events[name] = handler; }
  querySelectorAll() { return []; }
}
const document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
} };
const echarts = {
  init() { return { option: null, events: {}, setOption(option) { this.option = option; },
    off(name) { delete this.events[name]; }, on(name, handler) { this.events[name] = handler; },
    clear() { this.option = null; }, dispatchAction() {}, resize() {} }; },
  graphic: { LinearGradient: class { constructor(...args) { this.args = args; } } },
};
const context = {
  document, echarts, console, Intl, setInterval, clearInterval,
  window: { addEventListener() {} },
  fetch: async input => {
    const file = path.join(root, input.replace(/^\.\//, ''));
    return { ok: fs.existsSync(file), status: fs.existsSync(file) ? 200 : 404,
      json: async () => JSON.parse(fs.readFileSync(file, 'utf8')) };
  },
};
vm.createContext(context);
const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
for (const match of source.matchAll(/\$\("([^"]+)"\)/g)) {
  assert.ok(htmlIds.has(match[1]), `Missing HTML element: ${match[1]}`);
}
assert.ok(fs.statSync(path.join(root, 'vendor', 'echarts.min.js')).size > 100000);
vm.runInContext(source + '\nglobalThis.testApi = { state, loadMatch, setPlayerType, renderPhase, calibratedProbability, nextBallProbability, selectMoment };', context);

(async () => {
  for (let i = 0; i < 50 && !context.testApi.state.report; i++) await new Promise(resolve => setTimeout(resolve, 10));
  const { state, loadMatch, setPlayerType, renderPhase, calibratedProbability, nextBallProbability, selectMoment } = context.testApi;
  assert.equal(state.manifest.matches, 1243);
  assert.equal(state.matches.length, 1243);
  assert.equal(state.match.season, 2026);
  assert.ok(state.trace.length > 100);
  assert.match(document.getElementById('matchTitle').textContent, /vs/);
  assert.equal(document.getElementById('errorBanner').hidden, true);
  for (const id of ['replayChart', 'scenarioChart', 'eraChart', 'phaseChart', 'teamChart', 'playerChart', 'reliabilityChart', 'importanceChart']) {
    assert.ok(state.charts[id]?.option?.series?.length, `${id} has a series`);
  }
  assert.equal(state.charts.scenarioChart.option.series[0].data.length, 12);
  for (const reference of state.scenarioModel.references) {
    assert.ok(Math.abs(calibratedProbability(reference.features) - reference.probability) < 1e-6);
  }
  assert.ok(nextBallProbability(4, 0) >= 0 && nextBallProbability(4, 0) <= 1);
  const firstCell = state.charts.scenarioChart.option.series[0].data[0];
  state.charts.scenarioChart.events.click({ data: firstCell });
  assert.equal(state.scenarioChoice.join(','), '0,0');
  assert.match(document.getElementById('scenarioChoice').textContent, /0 runs/);
  selectMoment(state.trace.length - 1);
  assert.equal(state.charts.scenarioChart.option, null);
  selectMoment(0);
  for (const reference of state.scenarioModel.scenario_references) {
    await loadMatch(reference.match_id);
    selectMoment(reference.selected_index);
    const actual = nextBallProbability(reference.next_runs, reference.next_wicket);
    assert.ok(Math.abs(actual - reference.probability) < 1e-6, `Scenario mismatch for ${reference.match_id}`);
  }
  assert.ok(state.charts.replayChart.option.tooltip.formatter([
    { seriesName: 'Calibrated logistic', data: state.charts.replayChart.option.series[0].data[0] }
  ]).includes('Logistic'));
  const oldMatch = state.matches.find(m => m.eligible && m.season === 2008);
  await loadMatch(oldMatch.id);
  assert.equal(state.match.season, 2008);
  assert.ok(state.trace.length > 80);
  setPlayerType('bowlers');
  assert.equal(document.getElementById('playerTitle').textContent, 'Control meets strike rate');
  document.getElementById('phaseMetric').value = 'boundary_pct';
  renderPhase();
  assert.ok(state.charts.phaseChart.option.series[0].data.length >= 50);
  assert.ok(document.getElementById('modelScoreboard').innerHTML.includes('0.1254'));
  console.log('Static app smoke: 8 charts, 2026 and 2008 replays, checked scenario math, player toggle, phase metric, model audit passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
