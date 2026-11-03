---
title: Gameweeks
---

```js
import { probabilityBars, resultName, signed } from "../components/charts.js";
const leagues = await FileAttachment("../data/leagues.json").json();
const comp = leagues.competitions.find((c) => c.slug === observable.params.comp);
const stats = (await FileAttachment("../data/stats.json").json()).byCompetition[comp.div];
const bets = (await FileAttachment("../data/bets.json").json()).bets.filter((b) => b.div === comp.div);
```

# ${comp.name} gameweeks

Every gameweek's predictions and how they turned out.

```js
const allGameweeks = Array.from(new Set(bets.map((b) => b.gameweek))).sort((a, b) => a - b);
const gw = view(Inputs.select(allGameweeks, { label: "Gameweek", value: allGameweeks.at(-1) }));
```

```js
const gwBets = bets.filter((b) => b.gameweek === gw);
// A game more than 4 days from the rest of its gameweek was rearranged
const gwMedian = d3.median(gwBets, (b) => new Date(b.kickoff));
const rearranged = (b) => Math.abs(new Date(b.kickoff) - gwMedian) > 4 * 864e5;
const gwStat = stats.byGameweek.find((g) => g.gameweek === gw) ?? { status: "pending", bets: gwBets.length, settled: 0 };
const gwFixtures = gwBets.map((b) => ({
  home: b.home, away: b.away, kickoff: b.kickoff, prediction: b.prediction,
  homeProb: b.homeProb, drawProb: b.drawProb, awayProb: b.awayProb,
  result: b.result, settled: b.settled,
}));
```

<div class="grid grid-cols-4">
  <div class="card"><h2>Status</h2><span class="big" style="text-transform: capitalize">${gwStat.status}</span>${gwStat.settled}/${gwStat.bets} settled</div>
  <div class="card"><h2>Correct</h2><span class="big">${gwStat.settled ? `${gwStat.hits}/${gwStat.settled}` : "—"}</span>${gwStat.hitRate != null ? gwStat.hitRate + "%" : ""}</div>
  <div class="card"><h2>Profit</h2><span class="big">${gwStat.profit != null ? signed(gwStat.profit) + " u" : "—"}</span></div>
  <div class="card"><h2>Running total</h2><span class="big">${gwStat.cumulativeProfit != null ? signed(gwStat.cumulativeProfit) + " u" : "—"}</span></div>
</div>

## Predictions

${gwBets.some(rearranged)
  ? html`<p class="small">Gameweeks are the league's official matchdays, so a rearranged game stays in its original gameweek even when it's played days or weeks later. Those are marked "rearranged" below.</p>`
  : ""}

${gwBets.some((b) => b.backfilled)
  ? html`<p class="small">This gameweek was predicted after it was played, by a model trained only on the matches before it kicked off, because ${comp.name} joined the model mid-season.</p>`
  : ""}

```js
probabilityBars(gwFixtures, { width })
```

```js
Inputs.table(
  gwBets.map((b) => ({
    "Kick-off": new Date(b.kickoff),
    Match: `${b.home} v ${b.away}`,
    Pick: resultName[b.prediction],
    "Model %": Math.max(b.homeProb, b.drawProb, b.awayProb),
    "H / D / A": `${b.homeProb} / ${b.drawProb} / ${b.awayProb}`,
    Result: b.settled ? resultName[b.result] : "—",
    Outcome: b.settled ? (b.won ? "✅ won" : "❌ lost") : "",
    Note: rearranged(b) ? "rearranged" : "",
    "P/L": b.settled ? signed(b.profit) : "",
  })),
  {
    sort: "Kick-off",
    format: { "Kick-off": (d) => d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) },
    align: { "Model %": "right", "P/L": "right" },
    layout: "auto",
  }
)
```

## Where each gameweek landed

```js
const gwDone = stats.byGameweek.filter((g) => g.profit != null);
const gwLast = Math.max(10, ...stats.byGameweek.map((g) => g.gameweek));
```

```js
gwDone.length
  ? Plot.plot({
      width,
      height: 240,
      x: { label: "gameweek", tickFormat: "d", ticks: d3.range(1, gwLast + 1), domain: [0.5, gwLast + 0.5] },
      y: { label: "profit (u)", grid: true },
      marks: [
        Plot.ruleY([0]),
        Plot.rectY(gwDone, {
          x1: (d) => d.gameweek - 0.35,
          x2: (d) => d.gameweek + 0.35,
          y: "profit",
          fill: (d) => (d.profit >= 0 ? "#16a34a" : "#dc2626"),
          fillOpacity: (d) => (d.gameweek === gw ? 1 : 0.45),
          tip: true,
          title: (d) => `GW${d.gameweek}: ${d.hits}/${d.settled} correct, ${signed(d.profit)}u`,
        }),
        Plot.text(gwDone, {
          x: "gameweek", y: "profit", text: (d) => signed(d.profit, 1), dy: (d) => (d.profit >= 0 ? -6 : 12), fontSize: 10,
        }),
      ],
    })
  : html`<p class="small">No gameweek settled yet.</p>`
```
