# The Model

Brian rates every team with an **Elo** number (updated after each match, home
advantage +130) and combines the Elo gap with two expected-goals features —
recent xG difference and season goals-per-game difference — in a calibrated
logistic regression that outputs Home / Draw / Away probabilities.

```js
const stats = await FileAttachment("data/stats.json").json();
const eloFile = await FileAttachment("data/elo.json").json();
const elo = eloFile.teams;
const backtest = await FileAttachment("data/backtest.json").json();
```

## How it scored on past seasons

Each season below was predicted by a model trained **only on the seasons before
it**, then checked against what actually happened. "Baseline" is the accuracy you
would get by predicting a home win every single time.

<div class="grid grid-cols-3">
  <div class="card">
    <h2>Accuracy</h2>
    <span class="big">${backtest.overall.accuracy}%</span>
    ${backtest.overall.matches} matches, ${backtest.overall.baselineAccuracy}% baseline
  </div>
  <div class="card">
    <h2>Edge over baseline</h2>
    <span class="big">+${backtest.overall.edge}</span>
  </div>
  <div class="card">
    <h2>Log loss</h2>
    <span class="big">${backtest.overall.logLoss}</span>
    lower is better
  </div>
</div>

```js
Plot.plot({
  width,
  height: 260,
  marginBottom: 40,
  x: { label: null },
  y: { label: "accuracy (%)", domain: [0, 65], grid: true },
  marks: [
    Plot.barY(backtest.seasons, {
      x: "season",
      y: "accuracy",
      fill: "currentColor",
      fillOpacity: 0.85,
      tip: true,
      title: (d) => `${d.season}: ${d.accuracy}%  (trained on ${d.trainedOn})`,
    }),
    Plot.tickY(backtest.seasons, {
      x: "season",
      y: "baselineAccuracy",
      stroke: "red",
      strokeWidth: 2,
    }),
    Plot.text(backtest.seasons, {
      x: "season",
      y: "accuracy",
      text: (d) => `${d.accuracy}%`,
      dy: -6,
      fontSize: 11,
    }),
  ],
});
```

Red tick = the always-home baseline for that season.

```js
Inputs.table(backtest.seasons, {
  columns: ["season", "matches", "trainedOn", "accuracy", "baselineAccuracy", "edge", "logLoss"],
  header: {
    trainedOn: "Trained on", accuracy: "Acc %", baselineAccuracy: "Base %",
    edge: "Edge", logLoss: "Log loss",
  },
});
```

## Is it calibrated?

Does a stated 55% actually come up ~55% of the time? Points on the dashed line
are perfectly calibrated; above it the model is under-confident, below it
over-confident.

```js
Plot.plot({
  width,
  height: 320,
  x: { label: "model probability for its pick (%)", domain: [30, 80] },
  y: { label: "actual hit rate (%)", domain: [0, 100], grid: true },
  marks: [
    Plot.line([[30, 30], [80, 80]], { strokeDasharray: "4,4", strokeOpacity: 0.5 }),
    Plot.dot(stats.calibration, {
      x: "avgProb",
      y: "hitRate",
      r: (d) => Math.sqrt(d.bets) * 4,
      fill: "currentColor",
      tip: true,
      title: (d) => `${d.label}: ${d.hitRate}% over ${d.bets} bets`,
    }),
  ],
});
```

Dot size is the number of bets in that band, so small dots are noise.

## Which outcomes does it back?

```js
Inputs.table(stats.byPick, {
  columns: ["label", "bets", "hits", "hitRate", "profit"],
  header: { label: "Pick", hitRate: "Hit rate %", profit: "P/L" },
  format: { profit: (x) => (x >= 0 ? "+" : "") + x.toFixed(2) },
});
```

The model almost never predicts a draw — a known weakness of 3-way football
models, and the main thing left on the table.

## Current Elo ratings

```js
Plot.plot({
  width,
  height: elo.length * 20 + 40,
  marginLeft: 170,
  x: { label: "Elo", domain: [d3.min(elo, (d) => d.elo) - 20, d3.max(elo, (d) => d.elo) + 20] },
  y: { label: null, domain: elo.map((d) => d.team) },
  marks: [
    Plot.ruleX([1500], { strokeOpacity: 0.3 }),
    Plot.barX(elo, { x: "elo", y: "team", fill: "currentColor", fillOpacity: 0.8, tip: true }),
    Plot.text(elo, { x: "elo", y: "team", text: (d) => d.elo, dx: 14, fontSize: 11 }),
  ],
});
```

<div class="small note">Last updated ${new Date(stats.generated).toLocaleString()}.</div>
