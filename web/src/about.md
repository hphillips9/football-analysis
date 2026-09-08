# About

A model that predicts Premier League results, updated automatically every
gameweek. This page is how it works and how well it has done.

```js
import { signed, resultName } from "./components/charts.js";
const stats = await FileAttachment("data/stats.json").json();
const backtest = await FileAttachment("data/backtest.json").json();
```

## How a prediction is made

**The data.** Match results and bookmaker odds come from
[football-data.co.uk](https://www.football-data.co.uk/); expected-goals (xG)
figures for every match come from [Understat](https://understat.com/). Five past
seasons plus the current one, about 1,900 matches.

**The rating.** Each team has an **Elo rating**, starting at 1500. After a match
the winner takes points from the loser — up to 35, scaled by how surprising the
result was — and a draw nudges the higher-rated team down. Ratings carry across
seasons. Home advantage is a flat **+130** added to the home team's rating.

**The features.** Three numbers go into the model for each match:

| Feature | What it is |
|---|---|
| Elo gap | home Elo + 130 − away Elo |
| xG difference, last 5 | each team's (xG for − xG against) over its last five games, home minus away |
| Goals per game difference | same idea, season-to-date actual goals |

**The model.** A logistic regression maps those three features to Home / Draw /
Away probabilities, wrapped in probability calibration so a stated 60% really
means 60%. It is retrained on all available history each run.

**Each gameweek.** The upcoming fixtures are pasted in, the model scores them,
and every pick is recorded as a 1-unit flat-stake bet at the best available
price (Sky Bet, or the market average if that's missing). Results and profit are
filled in automatically once the games are played.

**The projected table** on the [League Table](/table) page scores every fixture
not yet played by expected points — 3 × P(win) + 1 × P(draw) — and adds them to
the current standings.

## How it scored on past seasons

Each season was predicted by a model trained **only on the seasons before it**.
"Baseline" is the accuracy of just predicting a home win every time.

<div class="grid grid-cols-3">
  <div class="card"><h2>Accuracy</h2><span class="big">${backtest.overall.accuracy}%</span>over ${backtest.overall.matches} matches</div>
  <div class="card"><h2>Edge over baseline</h2><span class="big">${signed(backtest.overall.edge, 1)}</span>baseline ${backtest.overall.baselineAccuracy}%</div>
  <div class="card"><h2>Log loss</h2><span class="big">${backtest.overall.logLoss}</span>lower is better</div>
</div>

```js
Plot.plot({
  width,
  height: 260,
  x: { label: null, padding: 0.4 },
  y: { label: "accuracy (%)", domain: [0, 65], grid: true },
  marks: [
    Plot.barY(backtest.seasons, {
      x: "season", y: "accuracy", fill: "#2563eb", fillOpacity: 0.85, tip: true,
      title: (d) => `${d.season}: ${d.accuracy}%  ·  baseline ${d.baselineAccuracy}%  ·  log loss ${d.logLoss}\ntrained on ${d.trainedOn}`,
    }),
    Plot.tickY(backtest.seasons, { x: "season", y: "baselineAccuracy", stroke: "#dc2626", strokeWidth: 3 }),
    Plot.text(backtest.seasons, { x: "season", y: "accuracy", text: (d) => `${d.accuracy}%`, dy: -6, fontSize: 11 }),
  ],
})
```

Red tick is that season's always-home baseline.

```js
Inputs.table(backtest.seasons, {
  columns: ["season", "matches", "trainedOn", "accuracy", "baselineAccuracy", "edge", "logLoss"],
  header: { trainedOn: "Trained on", accuracy: "Acc %", baselineAccuracy: "Base %", edge: "Edge", logLoss: "Log loss" },
  align: { accuracy: "right", baselineAccuracy: "right", edge: "right", logLoss: "right" },
})
```

## Is it well calibrated?

When the model says its pick has a 55% chance, does it come up about 55% of the
time? Points on the dashed line are perfectly calibrated. Dot size is the number
of bets in that band, so small dots are just noise.

```js
Plot.plot({
  width,
  height: 320,
  x: { label: "model probability for its pick (%)", domain: [30, 80] },
  y: { label: "actual hit rate (%)", domain: [0, 100], grid: true },
  marks: [
    Plot.line([[30, 30], [80, 80]], { strokeDasharray: "4,4", strokeOpacity: 0.5 }),
    Plot.dot(stats.calibration, {
      x: "avgProb", y: "hitRate", r: (d) => Math.sqrt(d.bets) * 4, fill: "#2563eb", fillOpacity: 0.7,
      tip: true, title: (d) => `${d.label}: ${d.hitRate}% over ${d.bets} bets`,
    }),
  ],
})
```

## Which outcomes it backs

```js
Inputs.table(stats.byPick, {
  columns: ["label", "bets", "hits", "hitRate", "profit"],
  header: { label: "Pick", hitRate: "Hit rate %", profit: "P/L" },
  format: { profit: (x) => signed(x), hitRate: (x) => (x == null ? "—" : x) },
  align: { bets: "right", hits: "right", hitRate: "right", profit: "right" },
})
```

The model **almost never predicts a draw** — a well-known weakness of three-way
football models, and the main thing left to improve. Venue-specific form and a
few other features were tried and didn't help.

## How it stays up to date

A scheduled job fetches new results twice a week, settles the outstanding bets,
rebuilds the dataset and refreshes this site. Predictions for the next gameweek
are generated when the fixture list is added. Everything — the model, the data,
this page — is in [one repository](https://github.com/hphillips9/football-analysis).

<div class="small note">Site data updated ${new Date(stats.generated).toLocaleString()}. Season backtest updated ${new Date(backtest.generated).toLocaleString()}.</div>
