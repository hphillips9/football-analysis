# Gameweeks

Every gameweek's predictions and how they turned out.

```js
import { probabilityBars, resultName, signed } from "./components/charts.js";
const stats = await FileAttachment("data/stats.json").json();
const predictions = await FileAttachment("data/predictions.json").json();
const bets = (await FileAttachment("data/bets.json").json()).bets;
```

```js
const allGameweeks = Array.from(new Set(bets.map((b) => b.gameweek))).sort((a, b) => a - b);
const gw = view(Inputs.select(allGameweeks, { label: "Gameweek", value: allGameweeks.at(-1) }));
```

```js
const gwBets = bets.filter((b) => b.gameweek === gw);
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

```js
probabilityBars(gwFixtures, { width })
```

```js
Inputs.table(
  gwBets.map((b) => ({
    "Kick-off": new Date(b.kickoff).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
    Match: `${b.home} v ${b.away}`,
    Pick: resultName[b.prediction],
    "Model %": Math.max(b.homeProb, b.drawProb, b.awayProb),
    "H / D / A": `${b.homeProb} / ${b.drawProb} / ${b.awayProb}`,
    Result: b.settled ? resultName[b.result] : "—",
    Outcome: b.settled ? (b.won ? "✅ won" : "❌ lost") : "",
    "P/L": b.settled ? signed(b.profit) : "",
  })),
  { sort: "Kick-off", align: { "Model %": "right", "P/L": "right" }, layout: "auto" }
)
```

## Where each gameweek landed

```js
Plot.plot({
  width,
  height: 240,
  x: { label: "gameweek", tickFormat: "d", interval: 1, domain: [0.5, Math.max(10, ...stats.byGameweek.map((g) => g.gameweek)) + 0.5] },
  y: { label: "profit (u)", grid: true },
  marks: [
    Plot.ruleY([0]),
    Plot.rectY(stats.byGameweek.filter((g) => g.profit != null), {
      x1: (d) => d.gameweek - 0.35,
      x2: (d) => d.gameweek + 0.35,
      y: "profit",
      fill: (d) => (d.profit >= 0 ? "#16a34a" : "#dc2626"),
      fillOpacity: (d) => (d.gameweek === gw ? 1 : 0.45),
      tip: true,
      title: (d) => `GW${d.gameweek}: ${d.hits}/${d.settled} correct, ${signed(d.profit)}u`,
    }),
    Plot.text(stats.byGameweek.filter((g) => g.profit != null), {
      x: "gameweek", y: "profit", text: (d) => signed(d.profit, 1), dy: (d) => (d.profit >= 0 ? -6 : 12), fontSize: 10,
    }),
  ],
})
```
