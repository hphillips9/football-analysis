# Brian The Football Brain

Premier League match predictions from an Elo + expected-goals model.

```js
const stats = await FileAttachment("data/stats.json").json();
const predictions = await FileAttachment("data/predictions.json").json();
```

<div class="grid grid-cols-4">
  <div class="card">
    <h2>Record</h2>
    <span class="big">${stats.wins}–${stats.losses}</span>
  </div>
  <div class="card">
    <h2>Hit rate</h2>
    <span class="big">${stats.hitRate}%</span>
    ${stats.edge >= 0 ? "+" : ""}${stats.edge} vs always-home
  </div>
  <div class="card">
    <h2>Profit</h2>
    <span class="big">${stats.profit >= 0 ? "+" : ""}${stats.profit} u</span>
    on ${stats.staked} staked
  </div>
  <div class="card">
    <h2>ROI</h2>
    <span class="big">${stats.roi >= 0 ? "+" : ""}${stats.roi}%</span>
  </div>
</div>

## Gameweek ${predictions.gameweek}

```js
// One row per outcome so the bar can stack H / D / A
const fixtureProbs = predictions.fixtures.flatMap((f) => [
  { match: `${f.home} v ${f.away}`, kickoff: f.kickoff, outcome: "H", prob: f.homeProb, pick: f.prediction },
  { match: `${f.home} v ${f.away}`, kickoff: f.kickoff, outcome: "D", prob: f.drawProb, pick: f.prediction },
  { match: `${f.home} v ${f.away}`, kickoff: f.kickoff, outcome: "A", prob: f.awayProb, pick: f.prediction },
]);
```

```js
Plot.plot({
  width,
  height: predictions.fixtures.length * 34 + 46,
  marginLeft: 190,
  x: { domain: [0, 100], label: "win probability (%)", grid: true },
  y: { label: null, domain: predictions.fixtures.map((f) => `${f.home} v ${f.away}`) },
  color: {
    domain: ["H", "D", "A"],
    range: ["#2563eb", "#9ca3af", "#dc2626"],
    tickFormat: (d) => ({ H: "Home", D: "Draw", A: "Away" }[d]),
    legend: true,
  },
  marks: [
    Plot.barX(fixtureProbs, {
      y: "match",
      x: "prob",
      fill: "outcome",
      order: ["H", "D", "A"],
      tip: true,
      title: (d) => `${d.outcome === "H" ? "Home" : d.outcome === "D" ? "Draw" : "Away"} ${d.prob}%`,
    }),
    Plot.ruleX([50], { stroke: "currentColor", strokeOpacity: 0.3 }),
  ],
});
```

```js
Plot.plot({
  width,
  marginTop: 0,
  height: 90,
  x: { type: "utc", label: null },
  y: { label: "cumulative u", grid: true },
  marks: [
    Plot.ruleY([0]),
    Plot.lineY(stats.bankroll, { x: (d) => new Date(d.kickoff), y: "cumulative", curve: "step-after" }),
  ],
});
```

[See the full track record →](/track-record)

---

<div class="small note">Last updated ${new Date(stats.generated).toLocaleString()}.</div>
