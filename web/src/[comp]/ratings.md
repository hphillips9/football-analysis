---
title: Ratings
---

```js
import { signed } from "../components/charts.js";
const leagues = await FileAttachment("../data/leagues.json").json();
const comp = leagues.competitions.find((c) => c.slug === observable.params.comp);
const eloFile = await FileAttachment("../data/elo.json").json();
const elo = eloFile.teams
  .filter((t) => t.div === comp.div)
  .map((t, i) => ({ ...t, rank: i + 1, vsAverage: t.elo - 1500 }));
```

# ${comp.name} ratings

Every team carries an **Elo rating**. It starts at 1500, moves after every match
by up to 35 points depending on the result and how expected it was, and carries
across seasons. ${comp.promotedElo == null
  ? "A promoted team comes back on the rating it last had (a team new to the data starts at 1500)."
  : `A promoted team restarts at ${comp.promotedElo}.`}
The gap between two teams' ratings (plus a **+130 home advantage**) is the model's
single biggest input.

```js
Plot.plot({
  width,
  height: elo.length * 24 + 44,
  marginLeft: 190,
  x: { label: "Elo vs the 1500 average", tickFormat: (d) => signed(d, 0) },
  y: { label: null, domain: elo.map((d) => d.team) },
  marks: [
    Plot.ruleX([0]),
    Plot.barX(elo, {
      x: "vsAverage",
      y: "team",
      fill: (d) => (d.vsAverage >= 0 ? "#2563eb" : "#dc2626"),
      fillOpacity: 0.85,
      tip: true,
      title: (d) => `${d.team}: Elo ${d.elo}`,
    }),
    Plot.text(elo, {
      x: "vsAverage",
      y: "team",
      text: (d) => d.elo,
      textAnchor: (d) => (d.vsAverage >= 0 ? "start" : "end"),
      dx: (d) => (d.vsAverage >= 0 ? 5 : -5),
      fontSize: 11,
    }),
  ],
})
```

Bars run from a 1500-rated team; blue is above, red below. Each league's ratings
are on their own scale, so a 1700 in one league isn't directly comparable with a
1700 in another - [Ratings Across Leagues](../ratings) puts every club on one scale.

```js
Inputs.table(elo, {
  columns: ["rank", "team", "elo", "vsAverage"],
  header: { rank: "#", team: "Team", elo: "Elo", vsAverage: "vs 1500" },
  format: { vsAverage: (x) => signed(x, 0) },
  align: { elo: "right", vsAverage: "right" },
  rows: 20,
})
```

<div class="small note">Ratings after the most recent completed match. Updated ${new Date(eloFile.generated).toLocaleString()}.</div>
