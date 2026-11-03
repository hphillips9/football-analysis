---
title: This Gameweek
---

```js
import { probabilityBars, resultName, signed } from "../components/charts.js";
const leagues = await FileAttachment("../data/leagues.json").json();
const comp = leagues.competitions.find((c) => c.slug === observable.params.comp);
const stats = (await FileAttachment("../data/stats.json").json()).byCompetition[comp.div];
const fixtures = (await FileAttachment("../data/predictions.json").json()).fixtures.filter((f) => f.div === comp.div);
const elo = (await FileAttachment("../data/elo.json").json()).teams.filter((t) => t.div === comp.div);
```

# ${comp.name}

```js
const settled = stats.settledBets > 0;
```

${settled
  ? html`<p>The model has been right <b>${stats.hitRate}%</b> of the time in the ${comp.name} this season, ${signed(stats.edge, 1)} on picking the home side every game.</p>`
  : html`<p>No ${comp.name} predictions have been settled yet. The record starts once the first gameweek is played.</p>`}

<div class="grid grid-cols-4">
  <div class="card">
    <h2>This season</h2>
    <span class="big">${settled ? `${stats.wins}–${stats.losses}` : "—"}</span>
    ${settled ? `${stats.hitRate}% correct` : `${stats.pendingBets} pending`}
  </div>
  <div class="card">
    <h2>vs always-home</h2>
    <span class="big">${settled ? signed(stats.edge, 1) : "—"}</span>
    ${settled ? `${stats.baselineHitRate}% baseline` : ""}
  </div>
  <div class="card">
    <h2>Profit</h2>
    <span class="big">${settled ? `${signed(stats.profit)} u` : "—"}</span>
    ${settled ? `1u flat stakes, ${stats.staked} placed` : ""}
  </div>
  <div class="card">
    <h2>ROI</h2>
    <span class="big">${settled ? `${signed(stats.roi, 1)}%` : "—"}</span>
  </div>
</div>

```js
const kickoffs = fixtures.map((f) => new Date(f.kickoff));
const span = [d3.min(kickoffs), d3.max(kickoffs)];
const dayFormat = { weekday: "short", day: "numeric", month: "short" };
```

## ${fixtures.length ? `Gameweek ${fixtures[0].gameweek}` : "No fixtures yet"}

${fixtures.length ? html`<p class="small">${span[0].toLocaleDateString(undefined, dayFormat)} – ${span[1].toLocaleDateString(undefined, dayFormat)}</p>` : ""}

```js
if (fixtures.length) display(probabilityBars(fixtures, { width }));
```

```js
if (fixtures.length) display(Inputs.table(
  fixtures.map((f) => ({
    "Kick-off": new Date(f.kickoff),
    Match: `${f.home} v ${f.away}`,
    Pick: resultName[f.prediction],
    "H %": f.homeProb,
    "D %": f.drawProb,
    "A %": f.awayProb,
    "Elo gap": f.eloGap,
    Result: f.settled ? resultName[f.result] : "",
  })),
  {
    sort: "Kick-off",
    format: { "Kick-off": (d) => d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" }) },
    align: { "H %": "right", "D %": "right", "A %": "right", "Elo gap": "right" },
  }
));
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Cumulative profit</h2>

```js
stats.bankroll.length
  ? Plot.plot({
      width,
      height: 150,
      marginTop: 8,
      x: { type: "utc", label: null },
      y: { label: null, grid: true },
      marks: [
        Plot.ruleY([0]),
        Plot.areaY(stats.bankroll, { x: (d) => new Date(d.kickoff), y: "cumulative", curve: "step-after", fillOpacity: 0.12 }),
        Plot.lineY(stats.bankroll, { x: (d) => new Date(d.kickoff), y: "cumulative", curve: "step-after" }),
      ],
    })
  : html`<p class="small">Nothing settled yet.</p>`
```

[Full track record →](./track-record)
  </div>
  <div class="card">
    <h2>Top rated right now</h2>

```js
Plot.plot({
  width: 320,
  height: 150,
  marginLeft: 110,
  x: { axis: null },
  y: { label: null, domain: elo.slice(0, 6).map((t) => t.team) },
  marks: [
    Plot.barX(elo.slice(0, 6), { x: "elo", y: "team", fill: "#2563eb", fillOpacity: 0.85 }),
    Plot.text(elo.slice(0, 6), { x: "elo", y: "team", text: (d) => d.elo, dx: -4, textAnchor: "end", fill: "white", fontSize: 10 }),
  ],
})
```

[All ratings →](./ratings)
  </div>
</div>

<div class="small note">Updated ${new Date(leagues.generated).toLocaleString()}.</div>
