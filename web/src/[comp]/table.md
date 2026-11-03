---
title: League Table
---

```js
import { signed } from "../components/charts.js";
const leagues = await FileAttachment("../data/leagues.json").json();
const comp = leagues.competitions.find((c) => c.slug === observable.params.comp);
const tableFile = await FileAttachment("../data/table.json").json();
const table = tableFile.byCompetition[comp.div];
```

# ${comp.name} table

Where the table stands now, where it would be if every prediction so far had come
true, and where the model expects it to finish.

<div class="small">${table.playedFixtures} of ${table.playedFixtures + table.remainingFixtures} fixtures played · ${table.remainingFixtures} still to play.</div>

## Current standings

```js
Inputs.table(
  table.current.map((r) => ({
    "#": r.position, Team: r.team, P: r.played,
    W: r.won, D: r.drawn, L: r.lost,
    GF: r.gf, GA: r.ga, GD: signed(r.gd, 0), Pts: r.points,
  })),
  {
    sort: null, width: { Team: 200 },
    align: { P: "right", W: "right", D: "right", L: "right", GF: "right", GA: "right", GD: "right", Pts: "right" },
    rows: 20,
  }
)
```

## If every prediction had come true

The same games, but with the model's pick as the result. Movement is versus the
real table above. Only games the model made a pick for count, so in a league it
started on mid-season teams show fewer played than in the real table.

```js
const pickedGames = d3.sum(table.predicted, (r) => r.played) / 2;
const predictedDraws = d3.sum(table.predicted, (r) => r.drawn) / 2;
```

```js
pickedGames === 0
  ? html`<p class="small">None of the ${comp.name} games the model has picked have been played yet.</p>`
  : Inputs.table(
  table.predicted.map((r) => ({
    "#": r.position, Team: r.team, P: r.played,
    W: r.won, D: r.drawn, L: r.lost, Pts: r.points,
    "vs real": r.movement === 0 ? "–" : (r.movement > 0 ? `▲ ${r.movement}` : `▼ ${-r.movement}`),
  })),
  {
    sort: null, width: { Team: 200 },
    align: { P: "right", W: "right", D: "right", L: "right", Pts: "right" },
    rows: 20,
  }
)
```

${pickedGames > 0 && predictedDraws === 0
  ? html`<p>Note the <b>D</b> column: the model hasn't predicted a single draw this season, so this table has none.</p>`
  : ""}
${pickedGames > 0
  ? html`<p>Big movers show where its picks were most wrong: teams it overrated climb here, and teams it wrote off fall.</p>`
  : ""}

## Projected final table

Every fixture not yet played, scored by **expected points** — 3 × P(win) +
1 × P(draw) — added to the current standings. Goal difference also projects
forward, using a separate Dixon-Coles goal model's expected scorelines rather
than freezing at today's value.

```js
Inputs.table(
  table.projected.map((r) => ({
    "#": r.position, Team: r.team, P: r.played,
    W: r.won, D: r.drawn, L: r.lost, GD: signed(r.gd, 0), Pts: r.points,
    "vs now": r.movement === 0 ? "–" : (r.movement > 0 ? `▲ ${r.movement}` : `▼ ${-r.movement}`),
  })),
  {
    sort: null, width: { Team: 200 },
    align: { P: "right", W: "right", D: "right", L: "right", GD: "right", Pts: "right" },
    rows: 20,
  }
)
```

```js
Plot.plot({
  width,
  height: table.projected.length * 22 + 44,
  marginLeft: 190,
  x: { label: "projected places gained / lost by season's end", tickFormat: "d" },
  y: { label: null, domain: table.projected.map((d) => d.team) },
  marks: [
    Plot.ruleX([0]),
    Plot.barX(table.projected, {
      x: "movement",
      y: "team",
      fill: (d) => (d.movement > 0 ? "#16a34a" : d.movement < 0 ? "#dc2626" : "#9ca3af"),
      tip: true,
      title: (d) => `${d.team}\nnow ${d.currentPosition} → projected ${d.position}`,
    }),
    Plot.text(table.projected, {
      x: "movement", y: "team",
      text: (d) => (d.movement === 0 ? "" : (d.movement > 0 ? "+" : "") + d.movement),
      textAnchor: (d) => (d.movement >= 0 ? "start" : "end"),
      dx: (d) => (d.movement >= 0 ? 4 : -4),
      fontSize: 10,
    }),
  ],
})
```

<div class="small note">Updated ${new Date(tableFile.generated).toLocaleString()}.</div>
