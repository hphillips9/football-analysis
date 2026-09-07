# Premier League Football Predictor

```js
import { probabilityBars, OUTCOME, resultName, signed } from "./components/charts.js";
const stats = await FileAttachment("data/stats.json").json();
const predictions = await FileAttachment("data/predictions.json").json();
const elo = (await FileAttachment("data/elo.json").json()).teams;
```

Every gameweek, a model rates the two teams on **Elo** and recent
**expected goals**, then gives a Home / Draw / Away probability for each match.
It has been right **${stats.hitRate}%** of the time this season — ${signed(stats.edge, 1)}
on picking the home side every game.

<div class="grid grid-cols-4">
  <div class="card">
    <h2>This season</h2>
    <span class="big">${stats.wins}–${stats.losses}</span>
    ${stats.hitRate}% correct
  </div>
  <div class="card">
    <h2>vs always-home</h2>
    <span class="big">${signed(stats.edge, 1)}</span>
    ${stats.baselineHitRate}% baseline
  </div>
  <div class="card">
    <h2>Profit</h2>
    <span class="big">${signed(stats.profit)} u</span>
    1u flat stakes, ${stats.staked} placed
  </div>
  <div class="card">
    <h2>ROI</h2>
    <span class="big">${signed(stats.roi, 1)}%</span>
  </div>
</div>

## Gameweek ${predictions.gameweek}

```js
const kickoffs = predictions.fixtures.map((f) => new Date(f.kickoff));
const span = [d3.min(kickoffs), d3.max(kickoffs)];
```

<p class="small">${span[0].toLocaleDateString(undefined, {weekday: "short", day: "numeric", month: "short"})} – ${span[1].toLocaleDateString(undefined, {weekday: "short", day: "numeric", month: "short"})}</p>

```js
probabilityBars(predictions.fixtures, { width })
```

```js
Inputs.table(
  predictions.fixtures.map((f) => ({
    "Kick-off": new Date(f.kickoff).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" }),
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
    align: { "H %": "right", "D %": "right", "A %": "right", "Elo gap": "right" },
  }
)
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Cumulative profit</h2>

```js
Plot.plot({
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
```

[Full track record →](/track-record)
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

[All ratings →](/ratings)
  </div>
</div>

<div class="small note">Updated ${new Date(stats.generated).toLocaleString()}.</div>
