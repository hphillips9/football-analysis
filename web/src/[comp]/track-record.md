---
title: Track Record
---

```js
import { calibrationPlot, gameweekSpan, resultName, signed } from "../components/charts.js";
const leagues = await FileAttachment("../data/leagues.json").json();
const comp = leagues.competitions.find((c) => c.slug === observable.params.comp);
const stats = (await FileAttachment("../data/stats.json").json()).byCompetition[comp.div];
const bets = (await FileAttachment("../data/bets.json").json()).bets.filter((b) => b.div === comp.div);
const settled = stats.settledBets > 0;
```

# ${comp.name} track record

Every prediction is treated as a **1-unit flat-stake bet** at the best price on
offer (Sky Bet, or the market average when that's missing). Profit is in units.

${stats.backfilledBets
  ? html`<p class="small">${comp.name} joined the model mid-season, so its predictions for ${gameweekSpan(stats.backfilledGameweeks)} (${stats.backfilledBets} matches) were made afterwards. Each gameweek was scored by a model trained only on the matches before it kicked off, exactly as a live prediction would have been, and settled at the same odds. They're marked "backfilled" below.</p>`
  : ""}

<div class="grid grid-cols-4">
  <div class="card"><h2>Settled bets</h2><span class="big">${stats.settledBets}</span>${stats.pendingBets} pending</div>
  <div class="card"><h2>Record</h2><span class="big">${settled ? `${stats.wins}–${stats.losses}` : "—"}</span>${settled ? `${stats.hitRate}% correct` : ""}</div>
  <div class="card"><h2>Profit</h2><span class="big">${settled ? `${signed(stats.profit)} u` : "—"}</span>${settled ? `on ${stats.staked} staked` : ""}</div>
  <div class="card"><h2>ROI</h2><span class="big">${settled ? `${signed(stats.roi, 1)}%` : "—"}</span></div>
</div>

## Profit and loss

Bars are each gameweek's result; the line is the running total.

```js
const gwDone = stats.byGameweek.filter((g) => g.profit != null);
const gwMax = Math.max(10, ...stats.byGameweek.map((g) => g.gameweek)) + 0.5;
```

```js
gwDone.length
  ? Plot.plot({
      width,
      height: 320,
      marginRight: 40,
      x: { label: "gameweek", tickFormat: "d", ticks: d3.range(1, gwMax), domain: [0.5, gwMax] },
      y: { label: "units", grid: true },
      marks: [
        Plot.ruleY([0]),
        Plot.rectY(gwDone, {
          x1: (d) => d.gameweek - 0.35,
          x2: (d) => d.gameweek + 0.35,
          y: "profit",
          fill: (d) => (d.profit >= 0 ? "#16a34a" : "#dc2626"),
          fillOpacity: 0.5,
          tip: true,
          title: (d) => `GW${d.gameweek}\n${d.hits}/${d.settled} correct\n${signed(d.profit)}u  (running ${signed(d.cumulativeProfit)}u)`,
        }),
        Plot.lineY(gwDone, { x: "gameweek", y: "cumulativeProfit", strokeWidth: 2, curve: "monotone-x" }),
        Plot.dot(gwDone, { x: "gameweek", y: "cumulativeProfit", fill: "currentColor", r: 3 }),
        Plot.text(gwDone, { x: "gameweek", y: "cumulativeProfit", text: (d) => signed(d.cumulativeProfit, 1), dy: -12, fontSize: 10 }),
      ],
    })
  : html`<p class="small">No gameweek settled yet.</p>`
```

## Bet by bet

```js
stats.bankroll.length
  ? Plot.plot({
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
  : html`<p class="small">No bet settled yet.</p>`
```

```js
if (settled) display(html`<div class="grid grid-cols-2">
  <div class="card">
    <h2>Biggest wins</h2>
    <ul>${stats.bestBets.map((b) => html`<li><b>${b.match}</b> — ${resultName[b.pick]} at ${b.pickProb}% → <b>${signed(b.profit)}u</b></li>`)}</ul>
  </div>
  <div class="card">
    <h2>Most confident misses</h2>
    <ul>${stats.worstBets.map((b) => html`<li><b>${b.match}</b> — ${resultName[b.pick]} at ${b.pickProb}%, finished ${resultName[b.result]}</li>`)}</ul>
  </div>
</div>`);
```

## Is it well calibrated?

When the model gives its pick a 55% chance, does it come up about 55% of the
time? Points on the dashed line are perfectly calibrated. Dot size is the number
of bets in that band, so small dots are just noise.

```js
stats.calibration.length
  ? calibrationPlot(stats.calibration, { width })
  : html`<p class="small">No bet settled yet.</p>`
```

## Every bet

```js
const gwFilter = view(Inputs.select(["all season", ...Array.from(new Set(bets.map((b) => b.gameweek))).sort((a, b) => a - b)], { label: "Gameweek", value: "all season" }));
```

```js
const shown = (gwFilter === "all season" ? bets : bets.filter((b) => b.gameweek === gwFilter))
  .slice()
  .sort((a, b) => a.gameweek - b.gameweek || a.kickoff.localeCompare(b.kickoff));
```

```js
Inputs.table(
  shown.map((b) => ({
    GW: b.gameweek,
    Date: new Date(b.kickoff),
    Match: `${b.home} v ${b.away}`,
    Pick: resultName[b.prediction],
    "H %": b.homeProb, "D %": b.drawProb, "A %": b.awayProb,
    FT: b.settled ? resultName[b.result] : "—",
    "P/L": b.settled ? signed(b.profit) : "",
    Made: b.backfilled ? "backfilled" : "live",
  })),
  {
    format: { Date: (d) => d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) },
    align: { "H %": "right", "D %": "right", "A %": "right", "P/L": "right" },
    rows: 20,
  }
)
```

<div class="small note">Updated ${new Date(leagues.generated).toLocaleString()}.</div>
