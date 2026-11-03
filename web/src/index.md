---
title: This Week
---

# Football Predictor

```js
import { probabilityBars, resultName, signed } from "./components/charts.js";
const leagues = await FileAttachment("data/leagues.json").json();
const statsFile = await FileAttachment("data/stats.json").json();
const predictions = await FileAttachment("data/predictions.json").json();
const overall = statsFile.overall;
```

Every gameweek, a model rates the two teams on **Elo** and recent
**expected goals**, then gives a Home / Draw / Away probability for each match
in Europe's top five leagues. Across them it has been right **${overall.hitRate}%**
of the time this season, ${signed(overall.edge, 1)} on picking the home side every game.

<div class="grid grid-cols-4">
  <div class="card">
    <h2>All competitions</h2>
    <span class="big">${overall.wins}–${overall.losses}</span>
    ${overall.hitRate}% correct
  </div>
  <div class="card">
    <h2>vs always-home</h2>
    <span class="big">${signed(overall.edge, 1)}</span>
    ${overall.baselineHitRate}% baseline
  </div>
  <div class="card">
    <h2>Profit</h2>
    <span class="big">${signed(overall.profit)} u</span>
    1u flat stakes, ${overall.staked} placed
  </div>
  <div class="card">
    <h2>ROI</h2>
    <span class="big">${signed(overall.roi, 1)}%</span>
    ${overall.pendingBets} bets pending
  </div>
</div>

## By competition

```js
function competitionCard(c) {
  const s = statsFile.byCompetition[c.div];
  const done = s.settledBets > 0;
  return html`<div class="card">
    <h2><a href="./${c.slug}/">${c.name} →</a></h2>
    <span class="big">${done ? `${s.wins}–${s.losses}` : "—"}</span>
    ${done
      ? `${s.hitRate}% correct · ${signed(s.profit)} u · ROI ${signed(s.roi, 1)}%`
      : `first ${s.pendingBets} picks pending`}
  </div>`;
}
```

<div class="grid grid-cols-3">${leagues.competitions.map(competitionCard)}</div>

The all-competitions profit counts only bets with a recorded price; every
settled pick counts towards the hit rate. ${overall.backfilledBets
  ? `The ${overall.backfilledBets} predictions for gameweeks played before a league joined the model were made afterwards, each by a model trained only on the matches before it, so they're included too.`
  : ""}

## This week

```js
const ALL = "All competitions";
const names = leagues.competitions.map((c) => c.name);
const defaultName = leagues.competitions.find((c) => c.div === leagues.default).name;
const picked = view(Inputs.select([...names, ALL], { label: "Competition", value: defaultName }));
```

```js
const shown = picked === ALL ? leagues.competitions : leagues.competitions.filter((c) => c.name === picked);
const dayFormat = { weekday: "short", day: "numeric", month: "short" };

function fixturesFor(c) {
  const fixtures = predictions.fixtures.filter((f) => f.div === c.div);
  if (!fixtures.length) return html`<h3>${c.name}</h3><p class="small">No fixtures yet.</p>`;
  const kickoffs = fixtures.map((f) => new Date(f.kickoff));
  return html`<h3><a href="./${c.slug}/">${c.name}</a> · gameweek ${fixtures[0].gameweek}</h3>
    <p class="small">${d3.min(kickoffs).toLocaleDateString(undefined, dayFormat)} – ${d3.max(kickoffs).toLocaleDateString(undefined, dayFormat)}</p>
    ${probabilityBars(fixtures, { width })}
    ${Inputs.table(
      fixtures.map((f) => ({
        "Kick-off": new Date(f.kickoff),
        Match: `${f.home} v ${f.away}`,
        Pick: resultName[f.prediction],
        "H %": f.homeProb,
        "D %": f.drawProb,
        "A %": f.awayProb,
        Result: f.settled ? resultName[f.result] : "",
      })),
      {
        sort: "Kick-off",
        format: { "Kick-off": (d) => d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" }) },
        align: { "H %": "right", "D %": "right", "A %": "right" },
      }
    )}`;
}
```

<div>${shown.map(fixturesFor)}</div>

<div class="small note">Updated ${new Date(statsFile.generated).toLocaleString()}.</div>
