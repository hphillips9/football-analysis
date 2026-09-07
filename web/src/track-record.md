# Track Record

Every prediction is a 1-unit flat-stake bet at the best available price.

```js
const stats = await FileAttachment("data/stats.json").json();
const betsFile = await FileAttachment("data/bets.json").json();
const bets = betsFile.bets;
```

<div class="grid grid-cols-4">
  <div class="card"><h2>Settled bets</h2><span class="big">${stats.settledBets}</span>${stats.pendingBets} pending</div>
  <div class="card"><h2>Record</h2><span class="big">${stats.wins}–${stats.losses}</span>${stats.hitRate}% hit rate</div>
  <div class="card"><h2>Profit</h2><span class="big">${stats.profit >= 0 ? "+" : ""}${stats.profit} u</span></div>
  <div class="card"><h2>ROI</h2><span class="big">${stats.roi >= 0 ? "+" : ""}${stats.roi}%</span></div>
</div>

## Cumulative P/L

```js
Plot.plot({
  width,
  height: 340,
  x: { type: "utc", label: null },
  y: { label: "units", grid: true },
  marks: [
    Plot.ruleY([0]),
    Plot.areaY(stats.bankroll, {
      x: (d) => new Date(d.kickoff),
      y: "cumulative",
      curve: "step-after",
      fillOpacity: 0.12,
    }),
    Plot.lineY(stats.bankroll, {
      x: (d) => new Date(d.kickoff),
      y: "cumulative",
      curve: "step-after",
      strokeWidth: 2,
    }),
    Plot.dot(stats.bankroll, {
      x: (d) => new Date(d.kickoff),
      y: "cumulative",
      fill: "currentColor",
      r: 2.5,
      tip: true,
      title: (d) =>
        `${d.match}\nGW${d.gameweek}  ${d.profit >= 0 ? "+" : ""}${d.profit}u  →  ${d.cumulative}u`,
    }),
  ],
});
```

## Profit by gameweek

```js
Plot.plot({
  width,
  height: 220,
  x: { label: "gameweek", tickFormat: "d" },
  y: { label: "units", grid: true },
  marks: [
    Plot.ruleY([0]),
    Plot.barY(stats.byGameweek, {
      x: "gameweek",
      y: "profit",
      fill: (d) => (d.profit >= 0 ? "#16a34a" : "#dc2626"),
      tip: true,
      title: (d) => `GW${d.gameweek}: ${d.hits}/${d.bets} correct, ${d.profit >= 0 ? "+" : ""}${d.profit}u`,
    }),
  ],
});
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Best bets</h2>
    ${htl.html`<ul>${stats.bestBets.map((b) => htl.html`<li>${b.match} — picked ${b.pick}, ${b.pickProb}% → <b>+${b.profit}u</b></li>`)}</ul>`}
  </div>
  <div class="card">
    <h2>Most confident misses</h2>
    ${htl.html`<ul>${stats.worstBets.map((b) => htl.html`<li>${b.match} — picked ${b.pick} at ${b.pickProb}%, finished ${b.result}</li>`)}</ul>`}
  </div>
</div>

## Every bet

```js
const gwPick = view(
  Inputs.select(
    ["all", ...new Set(bets.map((b) => b.gameweek))],
    { label: "Gameweek", value: "all" }
  )
);
```

```js
const shown = gwPick === "all" ? bets : bets.filter((b) => b.gameweek === gwPick);
```

```js
Inputs.table(shown, {
  columns: ["gameweek", "date", "home", "away", "prediction", "homeProb", "drawProb", "awayProb", "result", "profit"],
  header: {
    gameweek: "GW", home: "Home", away: "Away", prediction: "Pick",
    homeProb: "H%", drawProb: "D%", awayProb: "A%", result: "FT", profit: "P/L",
  },
  format: {
    profit: (x) => (x == null ? "—" : (x >= 0 ? "+" : "") + x.toFixed(2)),
  },
  align: { profit: "right", homeProb: "right", drawProb: "right", awayProb: "right" },
});
```
