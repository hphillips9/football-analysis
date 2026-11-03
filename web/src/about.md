# About

A model that predicts results in Europe's top five leagues, updated
automatically every day. This page is how it works and how well it has done.

```js
import { calibrationPlot, signed } from "./components/charts.js";
const leagues = await FileAttachment("data/leagues.json").json();
const statsFile = await FileAttachment("data/stats.json").json();
const backtest = await FileAttachment("data/backtest.json").json();
const nameOf = Object.fromEntries(leagues.competitions.map((c) => [c.div, c.name]));
const listOf = (names) => names.join(", ").replace(/, ([^,]*)$/, " and $1");
const ownModel = listOf(backtest.model.ownModel.map((div) => nameOf[div] ?? div));
const pooledLeagues = listOf(Object.keys(backtest.competitions).filter((div) => !backtest.model.ownModel.includes(div)).map((div) => nameOf[div] ?? div));
```

## How a prediction is made

**The data.** Match results and bookmaker odds come from
[football-data.co.uk](https://www.football-data.co.uk/); expected-goals (xG)
figures for every match come from [FotMob](https://www.fotmob.com/), which uses
Opta's model (the xG shown on BBC and Sky), with [Understat](https://understat.com/)
as a backup. Upcoming fixtures come from [football-data.org](https://www.football-data.org/).
Five past seasons plus the current one, over 9,000 matches across the
${listOf(leagues.competitions.map((c) => c.name))}.

**The rating.** Each team has an **Elo rating**, starting at 1500. After a match
the winner takes points from the loser — up to 35, scaled by how surprising the
result was — and a draw nudges the higher-rated team down. Ratings carry across
seasons, including for promoted teams, which come back on the rating they last
had (a team new to the data starts at 1500). Restarting promoted teams lower
was tested in every league, but the gain was too small to keep. When ratings are
updated, the home team gets a flat **+130** for home advantage. Teams from
different leagues never play each other here, so each league's ratings are on
their own scale.

**The features.** Three numbers go into the model for each match:

| Feature | What it is |
|---|---|
| Elo gap | home Elo − away Elo |
| xG difference, last 5 | each team's (xG for − xG against) over its last five games, home minus away |
| Goals per game difference | same idea, season-to-date actual goals |

The model learns home advantage for itself, so it isn't added to this feature. The
"Elo gap" shown next to each prediction does include the +130, so it reads as how
far ahead the home side is once home advantage is counted.

**The model.** A logistic regression maps those three features to Home / Draw /
Away probabilities, wrapped in probability calibration so a stated 60% really
means 60%. It is retrained on all available history each run, in two versions:

- The **${ownModel}** has its own model, trained on its matches alone.
  Pooling the leagues didn't make its predictions any better or worse, so it
  stays on the model it started with.
- The **${pooledLeagues}** share one **pooled model**, trained on every
  league's matches together, with a 0/1 indicator for each league so it can learn
  each one's own home/draw/away balance. Learning from five leagues at once made
  their predictions measurably better than one model per league.

**Each gameweek.** Upcoming fixtures are fetched automatically, the model scores
them, and every pick is recorded as a 1-unit flat-stake bet at the best available
price (Sky Bet, or the market average if that's missing). Results and profit are
filled in automatically once the games are played.

**The projected table** on each league's table page scores every fixture
not yet played by expected points — 3 × P(win) + 1 × P(draw) — and adds them to
the current standings. Its projected goal difference comes from a separate
Dixon-Coles goal model (team attack/defence ratings fit on match results,
predicting expected goals rather than win/draw/loss) — a display-only addition
for those tables, no part of the H/D/A prediction model above.

## How it scored on past seasons

Each season was predicted by a model trained **only on the seasons before it**,
with each league predicted by the model it uses live. "Baseline" is the accuracy
of just predicting a home win every time.

```js
const summary = [
  ...Object.entries(backtest.competitions).map(([div, c]) => ({ competition: c.name, ...c.overall })),
  { competition: "All five leagues", ...backtest.pooled.overall },
];
```

```js
Inputs.table(summary, {
  columns: ["competition", "matches", "accuracy", "baselineAccuracy", "edge", "logLoss", "profit", "roi"],
  header: { competition: "Competition", accuracy: "Acc %", baselineAccuracy: "Base %", edge: "Edge", logLoss: "Log loss", profit: "Profit (u)", roi: "ROI %" },
  format: { edge: (d) => signed(d, 1), profit: (d) => signed(d), roi: (d) => signed(d, 1) },
  align: { matches: "right", accuracy: "right", baselineAccuracy: "right", edge: "right", logLoss: "right", profit: "right", roi: "right" },
  sort: null,
})
```

Pick a competition to see it season by season.

```js
const backtestDiv = view(Inputs.select(Object.keys(backtest.competitions), {
  label: "Competition",
  format: (div) => backtest.competitions[div].name,
  value: leagues.default,
}));
```

```js
const chosen = backtest.competitions[backtestDiv];
```

<div class="grid grid-cols-3">
  <div class="card"><h2>Accuracy</h2><span class="big">${chosen.overall.accuracy}%</span>over ${chosen.overall.matches} matches</div>
  <div class="card"><h2>Edge over baseline</h2><span class="big">${signed(chosen.overall.edge, 1)}</span>baseline ${chosen.overall.baselineAccuracy}%</div>
  <div class="card"><h2>Log loss</h2><span class="big">${chosen.overall.logLoss}</span>lower is better</div>
</div>

```js
Plot.plot({
  width,
  height: 260,
  x: { label: null, padding: 0.4 },
  y: { label: "accuracy (%)", domain: [0, 65], grid: true },
  marks: [
    Plot.barY(chosen.seasons, {
      x: "season", y: "accuracy", fill: "#2563eb", fillOpacity: 0.85, tip: true,
      title: (d) => `${d.season}: ${d.accuracy}%  ·  baseline ${d.baselineAccuracy}%  ·  log loss ${d.logLoss}\ntrained on ${d.trainedOn}`,
    }),
    Plot.tickY(chosen.seasons, { x: "season", y: "baselineAccuracy", stroke: "#dc2626", strokeWidth: 3 }),
    Plot.text(chosen.seasons, { x: "season", y: "accuracy", text: (d) => `${d.accuracy}%`, dy: -6, fontSize: 11 }),
  ],
})
```

Red tick is that season's always-home baseline.

```js
Inputs.table(chosen.seasons, {
  columns: ["season", "matches", "trainedOn", "accuracy", "baselineAccuracy", "edge", "logLoss", "profit", "roi"],
  header: { trainedOn: "Trained on", accuracy: "Acc %", baselineAccuracy: "Base %", edge: "Edge", logLoss: "Log loss", profit: "Profit (u)", roi: "ROI %" },
  format: { profit: (d) => signed(d), roi: (d) => signed(d, 1) },
  align: { accuracy: "right", baselineAccuracy: "right", edge: "right", logLoss: "right", profit: "right", roi: "right" },
})
```

## Would it have made money?

The same backtest, but staking **1 unit on every pick** of each season, settled
at the market-average pre-match price (Sky Bet odds aren't available for past
seasons). Bars are each gameweek's result; the line is the running total. The
season charts share one scale so the seasons compare directly.

<div class="grid grid-cols-2">
  <div class="card"><h2>Profit, all ${chosen.seasons.length} seasons</h2><span class="big">${signed(chosen.overall.profit)} u</span>on ${chosen.overall.matches} units staked</div>
  <div class="card"><h2>ROI</h2><span class="big">${signed(chosen.overall.roi, 1)}%</span>${chosen.seasons.filter((s) => s.profit > 0).length} of ${chosen.seasons.length} seasons in profit</div>
</div>

```js
const seasonExtent = d3.extent(
  chosen.seasons.flatMap((s) => s.byGameweek.flatMap((g) => [g.profit, g.cumulativeProfit])).concat(0)
);
const lastGameweek = d3.max(chosen.seasons, (s) => d3.max(s.byGameweek, (g) => g.gameweek));

function seasonPnl(season, width) {
  const gws = season.byGameweek;
  return Plot.plot({
    width,
    height: 240,
    marginRight: 30,
    x: { label: "gameweek", tickFormat: "d", ticks: [1, 10, 20, 30, lastGameweek], domain: [0.5, lastGameweek + 0.5] },
    y: { label: "units", grid: true, domain: seasonExtent, nice: true },
    marks: [
      Plot.ruleY([0]),
      Plot.rectY(gws, {
        x1: (d) => d.gameweek - 0.35,
        x2: (d) => d.gameweek + 0.35,
        y: "profit",
        fill: (d) => (d.profit >= 0 ? "#16a34a" : "#dc2626"),
        fillOpacity: 0.5,
        tip: true,
        title: (d) => `GW${d.gameweek}\n${d.hits}/${d.bets} correct\n${signed(d.profit)}u  (running ${signed(d.cumulativeProfit)}u)`,
      }),
      Plot.lineY(gws, { x: "gameweek", y: "cumulativeProfit", strokeWidth: 2, curve: "monotone-x" }),
      Plot.text(gws.slice(-1), { x: "gameweek", y: "cumulativeProfit", text: (d) => signed(d.cumulativeProfit, 1), dx: 4, textAnchor: "start", fontSize: 11, fontWeight: "bold" }),
    ],
  });
}
```

<div class="grid grid-cols-2">${chosen.seasons.map((s) => html`<div class="card">
  <h2>${s.season}</h2>
  <h3>${signed(s.profit)} u · ROI ${signed(s.roi, 1)}% · ${s.accuracy}% correct</h3>
  ${resize((width) => seasonPnl(s, width))}
</div>`)}</div>

These are simulated bets, not a real record: a single bookmaker's price can be
a little worse than the market average, which would shave the returns. Each
league's track record page has the live bets.

## Is it well calibrated?

When the model says its pick has a 55% chance, does it come up about 55% of the
time? This is this season's bets so far: the live ones, plus the earlier
gameweeks of leagues that joined mid-season, which were predicted afterwards
using only the matches before each one. Points on the dashed line are perfectly
calibrated. Dot size is the number of bets in that band, so small dots are just
noise.

```js
const ALL = "all";
const statsDiv = view(Inputs.select([ALL, ...Object.keys(statsFile.byCompetition)], {
  label: "Competition",
  format: (div) => (div === ALL ? "All competitions" : statsFile.byCompetition[div].name),
  value: ALL,
}));
```

```js
const stats = statsDiv === ALL ? statsFile.overall : statsFile.byCompetition[statsDiv];
```

<div class="small">${stats.settledBets} settled bets</div>

```js
stats.calibration.length
  ? calibrationPlot(stats.calibration, { width })
  : html`<p class="small">No bet settled yet.</p>`
```

## Which outcomes it backs

For the same competition as above.

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

A scheduled job runs every morning. It fetches new results and xG, settles the
outstanding bets, rebuilds the dataset, predicts any new fixtures and refreshes
this site. Each league runs separately, so a problem fetching one doesn't hold
up the others. Everything — the model, the data, this page — is in
[one repository](https://github.com/hphillips9/football-analysis).

<div class="small note">Site data updated ${new Date(leagues.generated).toLocaleString()}. Season backtest updated ${new Date(backtest.generated).toLocaleString()}.</div>
