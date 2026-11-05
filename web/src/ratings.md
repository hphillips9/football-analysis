---
title: Ratings across leagues
---

```js
import { signed } from "./components/charts.js";

const leagues = await FileAttachment("./data/leagues.json").json();
const eloFile = await FileAttachment("./data/elo.json").json();
const history = await FileAttachment("./data/elo_history.json").json();

const leagueName = Object.fromEntries(leagues.competitions.map((c) => [c.div, c.name]));
const leagueOrder = leagues.competitions.map((c) => c.div);

// Categorical slots in fixed order (validated light and dark, dataviz reference palette)
const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
const SERIES = dark
  ? ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"]
  : ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"];

const clubs = eloFile.teams
  .map((t) => ({
    ...t,
    league: t.modelled ? leagueName[t.div] : `Outside the 7 (${t.country})`,
    group: t.modelled ? "In a modelled league" : "Outside the 7 leagues",
  }))
  .sort((a, b) => b.rating - a.rating)
  .map((t, i) => ({ ...t, rank: i + 1 }));
```

# Ratings across leagues

Every club on **one Elo scale**, so clubs from different leagues can be compared
directly: is Benfica better than Brighton? Each league sits at its own baseline,
`1500 + offset`, with the Premier League at 1500. The offsets start from UEFA's
country coefficients and learn from every European match between two leagues, and
a club's own European results move its rating too
([notebook 21](https://github.com/hphillips9/football-analysis/blob/main/notebooks/21_league_strength_elo.ipynb)).

Clubs from outside the seven modelled leagues (Celtic, Club Brugge, Red Star, …)
are rated from their Champions League, Europa League and Conference League
matches alone, so their ratings are **less certain**.

```js
const leagueFilter = view(Inputs.select(
  ["All leagues", ...leagueOrder, "Outside the 7"],
  { label: "League", format: (d) => leagueName[d] ?? d }
));
const topN = view(Inputs.select([25, 50, 100, "All"], { label: "Show", value: 25, format: (d) => (d === "All" ? "All clubs" : `Top ${d}`) }));
```

```js
const filtered = clubs.filter((t) =>
  leagueFilter === "All leagues" ? true
  : leagueFilter === "Outside the 7" ? !t.modelled
  : t.div === leagueFilter
);
const shown = topN === "All" ? filtered : filtered.slice(0, topN);
```

```js
Plot.plot({
  width,
  height: shown.length * 22 + 60,
  marginLeft: 200,
  marginRight: 80,
  x: { label: "Rating (shared scale)", grid: true, nice: true },
  y: { label: null, domain: shown.map((d) => d.team) },
  color: { domain: ["In a modelled league", "Outside the 7 leagues"], range: [SERIES[0], SERIES[1]], legend: true },
  marks: [
    Plot.ruleX([1500], { strokeDasharray: "3,3", strokeOpacity: 0.5 }),
    Plot.ruleY(shown, { y: "team", x1: d3.min(shown, (d) => d.rating) - 20, x2: "rating", strokeOpacity: 0.15 }),
    Plot.dot(shown, {
      x: "rating", y: "team", fill: "group", r: 5, stroke: "var(--theme-background)", strokeWidth: 2,
      tip: true,
      title: (d) => `${d.team} - ${d.league}\nRating ${d.rating}${d.modelled ? `\nLeague Elo ${d.elo}` : "\nRated from European matches only"}`,
    }),
    Plot.text(shown, {
      x: "rating", y: "team", dx: 9, textAnchor: "start", fontSize: 10, fill: "currentColor",
      text: (d) => `${d.rating} · ${d.modelled ? d.div : d.country + "*"}`,
    }),
  ],
})
```

<div class="small note">The dashed line is 1500, the Premier League's baseline. * outside the seven modelled leagues.</div>

## A club's rating over the last year

```js
const picked = view(Inputs.select(clubs.map((t) => t.team), {
  label: "Clubs (up to 4)", multiple: true, value: clubs.slice(0, 3).map((t) => t.team),
}));
```

```js
const chosen = picked.slice(0, 4);
const lines = history.series
  .filter((s) => chosen.includes(s.team))
  .flatMap((s) => s.points.map(([date, rating]) => ({ team: s.team, date: new Date(date), rating })));
const ends = chosen.map((team) => lines.filter((d) => d.team === team).at(-1)).filter(Boolean);

display(Plot.plot({
  width,
  height: 320,
  marginRight: 140,
  x: { label: null, type: "utc" },
  y: { label: "Rating (shared scale)", grid: true, nice: true },
  color: { domain: chosen, range: SERIES.slice(0, 4), legend: true },
  marks: [
    Plot.lineY(lines, { x: "date", y: "rating", stroke: "team", strokeWidth: 2, curve: "step-after" }),
    Plot.text(ends, { x: "date", y: "rating", text: (d) => `${d.team} ${d.rating}`, dx: 6, textAnchor: "start", fill: "currentColor", fontSize: 11 }),
    Plot.ruleX(lines, Plot.pointerX({ x: "date", stroke: "currentColor", strokeOpacity: 0.3 })),
    Plot.dot(lines, Plot.pointer({ x: "date", y: "rating", fill: "team", r: 4 })),
    Plot.tip(lines, Plot.pointer({ x: "date", y: "rating", title: (d) => `${d.team}\n${d.date.toISOString().slice(0, 10)}: ${d.rating}` })),
  ],
}));
```

<div class="small note">A point after each match the club played, league or European, since ${history.from}.</div>

## League offsets over time

How far each league's baseline sits below the Premier League's. They move when the
UEFA coefficients update at the start of a season and with every European match
between two of the leagues.

```js
const offsets = history.offsets.map((d) => ({ ...d, date: new Date(d.date), name: leagueName[d.div] ?? d.div }));
const lastOffsets = leagueOrder
  .map((div) => offsets.filter((d) => d.div === div).at(-1))
  .filter(Boolean);
const names = leagueOrder.map((d) => leagueName[d]);

// Spread the end labels so close leagues don't overprint (about 13px apart)
const span = d3.max(offsets, (d) => d.offset) - d3.min(offsets, (d) => d.offset);
const gap = (span / 280) * 13;
[...lastOffsets].sort((a, b) => b.offset - a.offset).reduce((above, d) => {
  d.labelY = above == null ? d.offset : Math.min(d.offset, above - gap);
  return d.labelY;
}, null);

display(Plot.plot({
  width,
  height: 340,
  marginRight: 140,
  x: { label: null, type: "utc" },
  y: { label: "Offset vs the Premier League", grid: true, tickFormat: (d) => signed(d, 0) },
  color: { domain: names, range: SERIES, legend: true },
  marks: [
    Plot.ruleY([0], { strokeOpacity: 0.3 }),
    Plot.lineY(offsets, { x: "date", y: "offset", stroke: "name", z: (d) => `${d.div} ${d.season}`, strokeWidth: 2 }),
    Plot.text(lastOffsets, { x: "date", y: "labelY", text: (d) => `${d.name} ${signed(d.offset, 0)}`, dx: 6, textAnchor: "start", fill: "currentColor", fontSize: 11 }),
    Plot.tip(offsets, Plot.pointer({ x: "date", y: "offset", title: (d) => `${d.name}, ${d.season}\n${d.date.toISOString().slice(0, 10)}: ${signed(d.offset, 1)}` })),
  ],
}));
```

<div class="small note">Each season is drawn separately: the coefficient-based part steps at the start of a season.</div>

## All clubs

```js
Inputs.table(filtered, {
  columns: ["rank", "team", "league", "rating", "elo"],
  header: { rank: "#", team: "Club", league: "League", rating: "Rating", elo: "League Elo" },
  format: { elo: (x) => (x == null ? "-" : x) },
  align: { rating: "right", elo: "right" },
  rows: 25,
})
```

<div class="small note">"League Elo" is the rating within the club's own league, the one the match predictions use (a 1500 average). Updated ${new Date(eloFile.generated).toLocaleString()}.</div>
