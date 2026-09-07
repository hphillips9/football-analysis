# Track Record

Every prediction is treated as a **1-unit flat-stake bet** at the best price on
offer (Sky Bet, or the market average when that's missing). Profit is in units.

```js
import { resultName, signed } from "./components/charts.js";
const stats = await FileAttachment("data/stats.json").json();
const bets = (await FileAttachment("data/bets.json").json()).bets;
```

<div class="grid grid-cols-4">
  <div class="card"><h2>Settled bets</h2><span class="big">${stats.settledBets}</span>${stats.pendingBets} pending</div>
  <div class="card"><h2>Record</h2><span class="big">${stats.wins}–${stats.losses}</span>${stats.hitRate}% correct</div>
  <div class="card"><h2>Profit</h2><span class="big">${signed(stats.profit)} u</span>on ${stats.staked} staked</div>
  <div class="card"><h2>ROI</h2><span class="big">${signed(stats.roi, 1)}%</span></div>
</div>

## Profit and loss

Bars are each gameweek's result; the line is the running total.

```js
const gwDone = stats.byGameweek.filter((g) => g.profit != null);
```

```js
Plot.plot({
  width,
  height: 320,
  marginRight: 40,
  x: { label: "gameweek", tickFormat: "d", padding: 0.55 },
  y: { label: "units", grid: true },
  marks: [
    Plot.ruleY([0]),
    Plot.barY(gwDone, {
      x: "gameweek",
      y: "profit",
      fill: (d) => (d.profit >= 0 ? "#16a34a" : "#dc2626"),
      fillOpacity: 0.55,
      tip: true,
      title: (d) => `GW${d.gameweek}\n${d.hits}/${d.settled} correct\n${signed(d.profit)}u  (running ${signed(d.cumulativeProfit)}u)`,
    }),
    Plot.lineY(gwDone, { x: "gameweek", y: "cumulativeProfit", strokeWidth: 2, curve: "monotone-x" }),
    Plot.dot(gwDone, { x: "gameweek", y: "cumulativeProfit", fill: "currentColor", r: 3 }),
    Plot.text(gwDone, { x: "gameweek", y: "cumulativeProfit", text: (d) => signed(d.cumulativeProfit, 1), dy: -12, fontSize: 10 }),
  ],
})
```

## Bet by bet

```js
Plot.plot({
  width,
  height: 300,
  x: { label: "bet number", tickFormat: "d" },
  y: { label: "cumulative units", grid: true },
  marks: [
    Plot.ruleY([0]),
    Plot.lineY(stats.bankroll, { x: (d, i) => i + 1, y: "cumulative", curve: "step-after", strokeWidth: 2 }),
    Plot.dot(stats.bankroll, {
      x: (d, i) => i + 1,
      y: "cumulative",
      fill: (d) => (d.profit >= 0 ? "#16a34a" : "#dc2626"),
      r: 3,
      tip: true,
      title: (d) => `${d.match} · GW${d.gameweek}\n${signed(d.profit)}u  →  ${signed(d.cumulative)}u`,
    }),
  ],
})
```

<div class="grid grid-cols-2">
  <div class="card">
    <h2>Biggest wins</h2>
    ${htl.html`<ul>${stats.bestBets.map((b) => htl.html`<li><b>${b.match}</b> — ${resultName[b.pick]} at ${b.pickProb}% → <b>${signed(b.profit)}u</b></li>`)}</ul>`}
  </div>
  <div class="card">
    <h2>Most confident misses</h2>
    ${htl.html`<ul>${stats.worstBets.map((b) => htl.html`<li><b>${b.match}</b> — ${resultName[b.pick]} at ${b.pickProb}%, finished ${resultName[b.result]}</li>`)}</ul>`}
  </div>
</div>

## Every bet

```js
const gwFilter = view(Inputs.select(["all season", ...Array.from(new Set(bets.map((b) => b.gameweek))).sort((a, b) => a - b)], { label: "Gameweek", value: "all season" }));
```

```js
const shown = gwFilter === "all season" ? bets : bets.filter((b) => b.gameweek === gwFilter);
```

```js
Inputs.table(
  shown.map((b) => ({
    GW: b.gameweek,
    Date: b.date,
    Match: `${b.home} v ${b.away}`,
    Pick: resultName[b.prediction],
    "H %": b.homeProb, "D %": b.drawProb, "A %": b.awayProb,
    FT: b.settled ? resultName[b.result] : "—",
    "P/L": b.settled ? signed(b.profit) : "",
  })),
  {
    sort: "Date",
    align: { "H %": "right", "D %": "right", "A %": "right", "P/L": "right" },
    rows: 20,
  }
)
```

<div class="small note">Updated ${new Date(stats.generated).toLocaleString()}.</div>
