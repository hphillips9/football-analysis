# League Table

```js
import { signed } from "./components/charts.js";
const table = await FileAttachment("data/table.json").json();
```

Where the table stands now, where it would be if every prediction so far had come
true, and where the model expects it to finish.

<div class="small">${table.playedFixtures} of 380 fixtures played · ${table.remainingFixtures} still to play.</div>

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
real table above.

```js
Inputs.table(
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

Note the **D** column: the model has predicted zero draws all season, so this
table has none. Big movers show where its picks were most wrong — teams it
overrated climb here, teams it wrote off fall.

## Projected final table

Every fixture not yet played, scored by **expected points** — 3 × P(win) +
1 × P(draw) — added to the current standings. Goal difference is carried from
games already played.

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

<div class="small note">Updated ${new Date(table.generated).toLocaleString()}.</div>
