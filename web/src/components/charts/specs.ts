/**
 * Chart specs shared by the pages (plan §3 table). Each returns a ChartSpec
 * for PlotFigure; data goes in through the closure, so a page's island does
 *
 *   const spec = useMemo(() => runningProfit(points), [points]);
 *   <PlotFigure spec={spec} height={220} compactHeight={80} ... />
 *
 * Specs use ctx.Plot (loaded lazily) and never import Plot values.
 * Profit/loss is always shown with a sign; grey is fill only, never text.
 */

import { signed } from "../../lib/format";
import type { BankrollPoint, CalibrationBin, GameweekSummary } from "../../lib/schema";
import type { ChartSpec } from "./PlotFigure";

/** A naive UK kick-off as a Date whose UTC fields are the UK time (plot with type "utc"). */
const wallClock = (kickoff: string) => new Date(`${kickoff}Z`);

const shortDate = (d: Date) => d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

// ============================================================
// V2: running profit
// ============================================================

/**
 * Cumulative stake-1 profit, bet by bet: a step line over a light area in
 * the league colour. Compact (phone): an 80 px sparkline without axes; the
 * island shows the final value as large text beside it.
 */
export function runningProfit(points: readonly BankrollPoint[]): ChartSpec {
  const rows = points.map((p) => ({ ...p, date: wallClock(p.kickoff) }));

  return ({ Plot, width, height, compact, colors, style }) =>
    Plot.plot({
      width,
      height,
      style,
      marginTop: compact ? 6 : 12,
      marginBottom: compact ? 6 : 28,
      marginLeft: compact ? 0 : 44,
      marginRight: compact ? 0 : 12,
      x: { type: "utc", axis: compact ? null : "bottom", label: null, tickFormat: shortDate, ticks: 5 },
      y: { axis: compact ? null : "left", label: null, grid: !compact, tickFormat: (d: number) => signed(d, 0), nice: true },
      marks: [
        // y1/y2, not y: areaY stacks points that share an x (bets with the same kick-off)
        Plot.areaY(rows, { x: "date", y1: 0, y2: "cumulative", curve: "step-after", fill: colors.league, fillOpacity: 0.14 }),
        Plot.ruleY([0], { stroke: colors.muted, strokeOpacity: 0.6 }),
        Plot.lineY(rows, { x: "date", y: "cumulative", curve: "step-after", stroke: colors.league, strokeWidth: 2 }),
        Plot.dot(
          rows,
          Plot.pointerX({ x: "date", y: "cumulative", r: 4, fill: colors.league, stroke: colors.surface, strokeWidth: 2 }),
        ),
        Plot.tip(
          rows,
          Plot.pointerX({
            x: "date",
            y: "cumulative",
            title: (d: (typeof rows)[number]) =>
              `${d.match}\nGameweek ${d.gameweek} · ${shortDate(d.date)}\nThis bet ${signed(d.profit)} · total ${signed(d.cumulative)}`,
          }),
        ),
      ],
    });
}

// ============================================================
// V4 / V5: profit per gameweek
// ============================================================

type SettledGameweek = GameweekSummary & { profit: number; cumulativeProfit: number };

const settledGameweeks = (gameweeks: readonly GameweekSummary[]) =>
  gameweeks.filter((g): g is SettledGameweek => g.profit != null && g.cumulativeProfit != null);

const gameweekTip = (d: SettledGameweek) =>
  `Gameweek ${d.gameweek}\n${d.hits} of ${d.settled} right\n${signed(d.profit)}u (season ${signed(d.cumulativeProfit)}u)`;

/** x and y for a chart with a column per gameweek (numbers, not "GW9", so 38 of them fit). */
function gameweekScales(rows: readonly SettledGameweek[], compact: boolean) {
  return {
    x: { type: "band" as const, domain: rows.map((r) => r.gameweek), label: null, padding: 0.25 },
    y: { label: null, grid: true, nice: true, ticks: compact ? 4 : 6, tickFormat: (d: number) => signed(d, 0) },
  };
}

/**
 * V4: stake-1 profit per settled gameweek, a bar in profit or loss colour
 * with its value. `highlight` dims the others (the selected gameweek on the
 * Results page). On a phone it sits in a ScrollChart at ~40 px a gameweek.
 */
export function gameweekProfit(gameweeks: readonly GameweekSummary[], highlight?: number): ChartSpec {
  const rows = settledGameweeks(gameweeks);
  const dims = highlight != null && rows.some((r) => r.gameweek === highlight);

  return ({ Plot, width, height, compact, colors, style }) => {
    const fill = (d: SettledGameweek) => (d.profit >= 0 ? colors.pos : colors.neg);
    const opacity = (d: SettledGameweek) => (!dims || d.gameweek === highlight ? 1 : 0.35);
    const label = (d: SettledGameweek) => signed(d.profit, 1);

    return Plot.plot({
      width,
      height,
      style,
      marginTop: 20,
      marginBottom: 26,
      marginLeft: compact ? 30 : 40,
      marginRight: 4,
      insetTop: 12,
      insetBottom: 14,
      ...gameweekScales(rows, compact),
      marks: [
        Plot.barY(rows, { x: "gameweek", y: "profit", fill, fillOpacity: opacity }),
        Plot.ruleY([0], { stroke: colors.text, strokeOpacity: 0.5 }),
        Plot.text(
          rows.filter((r) => r.profit >= 0),
          { x: "gameweek", y: "profit", text: label, dy: -8, fill: colors.text, fillOpacity: opacity },
        ),
        Plot.text(
          rows.filter((r) => r.profit < 0),
          { x: "gameweek", y: "profit", text: label, dy: 9, fill: colors.text, fillOpacity: opacity },
        ),
        Plot.tip(rows, Plot.pointerX({ x: "gameweek", y: "profit", title: gameweekTip })),
      ],
    });
  };
}

/**
 * V5: each gameweek's profit (light bars) under the season's running total
 * (a line in the league colour, labelled at each gameweek).
 */
export function seasonProfit(gameweeks: readonly GameweekSummary[]): ChartSpec {
  const rows = settledGameweeks(gameweeks);

  return ({ Plot, width, height, compact, colors, style }) =>
    Plot.plot({
      width,
      height,
      style,
      marginTop: 22,
      marginBottom: 26,
      marginLeft: compact ? 30 : 40,
      marginRight: 16,
      insetTop: 14,
      insetBottom: 6,
      ...gameweekScales(rows, compact),
      marks: [
        Plot.barY(rows, {
          x: "gameweek",
          y: "profit",
          fill: (d: SettledGameweek) => (d.profit >= 0 ? colors.pos : colors.neg),
          fillOpacity: 0.45,
        }),
        Plot.ruleY([0], { stroke: colors.text, strokeOpacity: 0.5 }),
        Plot.lineY(rows, { x: "gameweek", y: "cumulativeProfit", stroke: colors.league, strokeWidth: 2.5, curve: "monotone-x" }),
        Plot.dot(rows, { x: "gameweek", y: "cumulativeProfit", fill: colors.league, stroke: colors.surface, strokeWidth: 1.5, r: 3.5 }),
        Plot.text(rows, {
          x: "gameweek",
          y: "cumulativeProfit",
          text: (d: SettledGameweek) => signed(d.cumulativeProfit, 1),
          dy: -12,
          fill: colors.text,
          fontWeight: 700,
          stroke: colors.surface,
          strokeWidth: 3,
          paintOrder: "stroke",
        }),
        Plot.tip(rows, Plot.pointerX({ x: "gameweek", y: "cumulativeProfit", title: gameweekTip })),
      ],
    });
}

// ============================================================
// V6: bet by bet
// ============================================================

/**
 * V6: the running total after every settled bet (x = bet number). Desktop
 * marks each bet as a win or loss dot; compact drops the dots and labels
 * the first, lowest, highest and latest points instead (plan §3).
 */
export function betByBet(points: readonly BankrollPoint[]): ChartSpec {
  const rows = points.map((p, i) => ({ ...p, n: i + 1 }));
  type Row = (typeof rows)[number];

  const extremes = rows.length
    ? [
        rows[0]!,
        rows.reduce((a, b) => (b.cumulative < a.cumulative ? b : a)),
        rows.reduce((a, b) => (b.cumulative > a.cumulative ? b : a)),
        rows.at(-1)!,
      ].filter((r, i, all) => all.indexOf(r) === i)
    : [];

  return ({ Plot, width, height, compact, colors, style }) =>
    Plot.plot({
      width,
      height,
      style,
      marginTop: 20,
      marginBottom: 34,
      marginLeft: compact ? 30 : 40,
      marginRight: compact ? 16 : 16,
      x: { label: "bet number", labelAnchor: "right", labelArrow: "none", ticks: compact ? 4 : 8, tickFormat: "d" },
      y: { label: null, grid: true, nice: true, tickFormat: (d: number) => signed(d, 0) },
      marks: [
        Plot.ruleY([0], { stroke: colors.text, strokeOpacity: 0.5 }),
        Plot.lineY(rows, { x: "n", y: "cumulative", curve: "step-after", stroke: colors.league, strokeWidth: 2 }),
        compact
          ? Plot.text(extremes, {
              x: "n",
              y: "cumulative",
              text: (d: Row) => signed(d.cumulative, 1),
              dy: -10,
              fill: colors.text,
              fontWeight: 700,
              stroke: colors.surface,
              strokeWidth: 3,
              paintOrder: "stroke",
            })
          : Plot.dot(rows, { x: "n", y: "cumulative", r: 2.5, fill: (d: Row) => (d.profit >= 0 ? colors.pos : colors.neg) }),
        Plot.dot(rows, Plot.pointerX({ x: "n", y: "cumulative", r: 5, fill: colors.league, stroke: colors.surface, strokeWidth: 2 })),
        Plot.tip(
          rows,
          Plot.pointerX({
            x: "n",
            y: "cumulative",
            title: (d: Row) => `Bet ${d.n}: ${d.match}\nGameweek ${d.gameweek}\n${signed(d.profit)}u → ${signed(d.cumulative)}u`,
          }),
        ),
      ],
    });
}

// ============================================================
// V7: calibration
// ============================================================

/**
 * V7: for each probability band, the model's average probability for its
 * pick (x) against how often the pick came up (y); dot area = bets in the
 * band. Points on the dashed diagonal are perfectly calibrated.
 */
export function calibration(bins: readonly CalibrationBin[]): ChartSpec {
  const lo = Math.min(30, ...bins.map((b) => Math.floor(b.avgProb / 5) * 5 - 5));
  const hi = Math.max(80, ...bins.map((b) => Math.ceil(b.avgProb / 5) * 5 + 5));

  return ({ Plot, width, height, compact, colors, style }) =>
    Plot.plot({
      width,
      height,
      style,
      marginTop: 30,
      marginBottom: 40,
      marginLeft: compact ? 38 : 46,
      marginRight: 12,
      x: { domain: [lo, hi], label: "model's probability for its pick (%)", labelAnchor: "center", labelArrow: "none" },
      y: { domain: [0, 100], label: "how often it came up (%)", labelArrow: "none", grid: true },
      r: { range: compact ? [2, 12] : [3, 18] },
      marks: [
        Plot.line(
          [
            [lo, lo],
            [hi, hi],
          ],
          { stroke: colors.muted, strokeDasharray: "4,4" },
        ),
        Plot.dot(bins, { x: "avgProb", y: "hitRate", r: "bets", fill: colors.league, fillOpacity: 0.7, stroke: colors.league }),
        Plot.tip(
          bins,
          Plot.pointer({
            x: "avgProb",
            y: "hitRate",
            title: (d: CalibrationBin) => `${d.label} band: ${d.bets} bets\nModel said ${d.avgProb}% on average\nCame up ${d.hitRate}%`,
          }),
        ),
      ],
    });
}

// ============================================================
// Diverging bars (V8, V9)
// ============================================================

interface DivergingRow {
  label: string;
  value: number;
  /** Shown at the bar's end. */
  text: string;
  /** Tip text. */
  title: string;
}

/** Height for a diverging-bar chart with `rows` rows. */
export const divergingHeight = (rows: number, compact = false) => rows * (compact ? 22 : 24) + 34;

/**
 * An x domain that fits the bars plus room for the labels: a row's name
 * needs room on the far side of zero (estimated from its length), its
 * value ~44 px past the bar's end. Only as wide on each side as the data
 * needs.
 */
function divergingDomain(rows: readonly DivergingRow[], plotWidth: number, charWidth: number): [number, number] {
  const values = rows.map((r) => r.value);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  // Names of rows at or above zero sit left of it, and vice versa
  const room = (side: readonly DivergingRow[]) =>
    side.length ? Math.max(...side.map((r) => r.label.length)) * charWidth + 10 : 0;
  const leftRoom = room(rows.filter((r) => r.value >= 0));
  const rightRoom = room(rows.filter((r) => r.value < 0));
  let [left, right] = [lo || -1, hi || 1];

  // Units per px depend on the domain, so settle it in a few passes
  for (let pass = 0; pass < 6; pass++) {
    const k = (right - left) / plotWidth;
    left = Math.min(lo - 44 * k, -leftRoom * k);
    right = Math.max(hi + 44 * k, rightRoom * k);
  }
  return [left, right];
}

/**
 * Bars either side of zero, one row each, with each row's name on the far
 * side of the zero line from its bar (plan §3: no 190 px label margin), so
 * the bars get the full width at any size.
 */
function divergingBars(
  rows: readonly DivergingRow[],
  opts: { axisLabel: string; above: (c: PlotColorsLike) => [string, number]; below: (c: PlotColorsLike) => [string, number]; tickFormat?: (d: number) => string },
): ChartSpec {
  const above = rows.filter((r) => r.value >= 0);
  const below = rows.filter((r) => r.value < 0);

  return ({ Plot, width, height, compact, colors, style }) => {
    const [aboveFill, aboveOpacity] = opts.above(colors);
    const [belowFill, belowOpacity] = opts.below(colors);

    return Plot.plot({
      width,
      height,
      style,
      marginTop: 4,
      marginBottom: 32,
      marginLeft: 8,
      marginRight: 8,
      x: {
        // Archivo at 12 / 13 px averages under 6.4 / 6.9 px a character
        domain: divergingDomain(rows, width - 16, compact ? 6.4 : 6.9),
        label: opts.axisLabel,
        labelAnchor: "center",
        labelArrow: "none",
        tickFormat: opts.tickFormat ?? ((d: number) => signed(d, 0)),
        ticks: compact ? 5 : 9,
      },
      y: { axis: null, domain: rows.map((r) => r.label), padding: 0.18 },
      marks: [
        Plot.barX(above, { x: "value", y: "label", fill: aboveFill, fillOpacity: aboveOpacity }),
        Plot.barX(below, { x: "value", y: "label", fill: belowFill, fillOpacity: belowOpacity }),
        Plot.ruleX([0], { stroke: colors.text, strokeOpacity: 0.6 }),
        Plot.text(above, { x: 0, y: "label", text: "label", textAnchor: "end", dx: -6, fill: colors.text }),
        Plot.text(below, { x: 0, y: "label", text: "label", textAnchor: "start", dx: 6, fill: colors.text }),
        Plot.text(above, { x: "value", y: "label", text: "text", textAnchor: "start", dx: 4, fill: colors.muted }),
        Plot.text(below, { x: "value", y: "label", text: "text", textAnchor: "end", dx: -4, fill: colors.muted }),
        Plot.tip(rows, Plot.pointerY({ x: "value", y: "label", title: "title" })),
      ],
    });
  };
}

type PlotColorsLike = Parameters<ChartSpec>[0]["colors"];

// ============================================================
// V9: ratings against the average
// ============================================================

export interface RatingRow {
  team: string;
  elo: number;
}

/** Height for ratingVsAverage with `rows` clubs. */
export const ratingChartHeight = divergingHeight;

/** V9: each club's league Elo against the 1500 average. */
export function ratingVsAverage(clubs: readonly RatingRow[], average = 1500): ChartSpec {
  return divergingBars(
    clubs.map((c) => {
      const diff = Math.round(c.elo - average);
      return { label: c.team, value: diff, text: signed(diff, 0), title: `${c.team}: Elo ${Math.round(c.elo)} (${signed(diff, 0)})` };
    }),
    {
      axisLabel: `Elo vs the ${average} average`,
      above: (c) => [c.league, 0.85],
      below: (c) => [c.muted, 0.45],
    },
  );
}

// ============================================================
// V8: projected places gained / lost
// ============================================================

export interface MoveRow {
  team: string;
  position: number;
  currentPosition: number;
  movement: number;
}

/**
 * V8: places each club is projected to gain or lose by the season's end
 * (projected position vs now), in final-table order. Wide screens only: on
 * a phone the projected table's Δ column carries the same numbers.
 */
export function placesMoved(rows: readonly MoveRow[]): ChartSpec {
  return divergingBars(
    rows.map((r) => ({
      label: r.team,
      value: r.movement,
      text: r.movement === 0 ? "" : signed(r.movement, 0),
      title: `${r.team}\nNow ${r.currentPosition} → projected ${r.position}`,
    })),
    {
      axisLabel: "Projected places gained / lost by the season's end",
      above: (c) => [c.pos, 0.8],
      below: (c) => [c.neg, 0.8],
      tickFormat: (d: number) => (Number.isInteger(d) ? signed(d, 0) : ""),
    },
  );
}

// ============================================================
// Ratings across leagues
// ============================================================

export interface SharedRow {
  team: string;
  rating: number;
  /** Shown after the rating: league mark, or country + "*" outside the seven. */
  tag: string;
  modelled: boolean;
  league: string;
  elo: number | null;
}

/** Height for sharedRatings with `rows` clubs. */
export const sharedHeight = (rows: number, compact = false) => rows * (compact ? 34 : 24) + 44;

/**
 * Every club on the shared scale: a dot per club with a faint stem, slot 1
 * for clubs in a modelled league and slot 2 for the rest. Wide: names on a
 * left axis. Compact (phone): names above each stem, no label margin.
 */
export function sharedRatings(rows: readonly SharedRow[]): ChartSpec {
  return ({ Plot, width, height, compact, colors, style }) => {
    const min = Math.min(...rows.map((r) => r.rating));
    const max = Math.max(...rows.map((r) => r.rating));
    const start = Math.floor((min - 30) / 50) * 50;
    const fill = (d: SharedRow) => (d.modelled ? colors.series[0]! : colors.series[1]!);
    const title = (d: SharedRow) =>
      `${d.team} · ${d.league}\nRating ${d.rating}${d.elo == null ? "\nRated from European matches only" : `\nLeague Elo ${d.elo}`}`;

    return Plot.plot({
      width,
      height,
      style,
      marginTop: compact ? 18 : 6,
      marginBottom: 32,
      marginLeft: compact ? 18 : 190,
      marginRight: compact ? 8 : 90,
      // Ratings are written 1804 everywhere on the site, not 1,804
      x: { domain: [start, max + (compact ? 60 : 10)], label: "Rating (shared scale)", labelAnchor: "center", labelArrow: "none", grid: true, ticks: compact ? 4 : 8, tickFormat: (d: number) => String(d) },
      y: { domain: rows.map((r) => r.team), axis: compact ? null : "left", label: null, padding: compact ? 0.55 : 0.3 },
      marks: [
        Plot.ruleX([1500], { stroke: colors.muted, strokeDasharray: "3,3" }),
        Plot.ruleY(rows, { y: "team", x1: start, x2: "rating", stroke: colors.line, strokeWidth: 2 }),
        Plot.dot(rows, { x: "rating", y: "team", fill, r: 5, stroke: colors.surface, strokeWidth: 2 }),
        compact
          ? Plot.text(rows, { x: start, y: "team", text: (d: SharedRow) => d.team, textAnchor: "start", dy: -12, fill: colors.text })
          : null,
        Plot.text(rows, {
          x: "rating",
          y: "team",
          text: (d: SharedRow) => `${d.rating} · ${d.tag}`,
          textAnchor: "start",
          dx: 9,
          fill: colors.muted,
        }),
        Plot.tip(rows, Plot.pointerY({ x: "rating", y: "team", title })),
      ],
    });
  };
}

/**
 * End labels pushed apart so close lines don't overprint: each label sits
 * at its value, or `gap` (in data units) below the label above it.
 */
function spread<T>(items: readonly T[], value: (d: T) => number, gap: number): (T & { labelY: number })[] {
  let above: number | null = null;
  return [...items]
    .sort((a, b) => value(b) - value(a))
    .map((d) => {
      const y: number = above == null ? value(d) : Math.min(value(d), above - gap);
      above = y;
      return { ...d, labelY: y };
    });
}

/** ~14 px in data units, for a chart of this height over this data range. */
const labelGap = (values: readonly number[], height: number) =>
  ((Math.max(...values) - Math.min(...values) || 1) / Math.max(height - 40, 1)) * 14;

export interface HistoryLine {
  team: string;
  /** Categorical slot, fixed per club so colours don't move when others are added. */
  slot: number;
  points: [string, number][];
}

/**
 * Up to four clubs' shared-scale ratings over the last year, one step line
 * each in its categorical slot, labelled at its end (direct labels: the
 * light-mode slots 2-5 are under 3:1, so colour never carries identity
 * alone).
 */
export function ratingHistory(lines: readonly HistoryLine[]): ChartSpec {
  const rows = lines.flatMap((l) => l.points.map(([date, rating]) => ({ team: l.team, slot: l.slot, date: new Date(`${date}T00:00:00Z`), rating })));
  type Row = (typeof rows)[number];
  const ends = lines.map((l) => rows.filter((r) => r.team === l.team).at(-1)).filter((r): r is Row => r != null);

  return ({ Plot, width, height, compact, colors, style }) => {
    const color = (d: Row) => colors.series[d.slot % colors.series.length]!;
    return Plot.plot({
      width,
      height,
      style,
      marginTop: 12,
      marginBottom: 28,
      marginLeft: 44,
      marginRight: compact ? 12 : 180,
      x: { type: "utc", label: null, ticks: compact ? 4 : 8 },
      y: { label: null, grid: true, nice: true, tickFormat: (d: number) => String(d) },
      marks: [
        ...lines.map((l) =>
          Plot.lineY(
            rows.filter((r) => r.team === l.team),
            { x: "date", y: "rating", stroke: color, strokeWidth: 2, curve: "step-after" },
          ),
        ),
        compact
          ? null
          : Plot.text(spread(ends, (d) => d.rating, labelGap(rows.map((r) => r.rating), height)), { x: "date", y: "labelY", text: (d: Row) => `${d.team} ${d.rating}`, dx: 8, textAnchor: "start", fill: colors.text }),
        Plot.dot(ends, { x: "date", y: "rating", fill: color, r: 4, stroke: colors.surface, strokeWidth: 1.5 }),
        Plot.ruleX(rows, Plot.pointerX({ x: "date", stroke: colors.muted, strokeOpacity: 0.5 })),
        Plot.tip(
          rows,
          Plot.pointer({
            x: "date",
            y: "rating",
            title: (d: Row) => `${d.team}\n${shortDate(d.date)} ${d.date.getUTCFullYear()}: ${d.rating}`,
          }),
        ),
      ],
    });
  };
}

export interface OffsetRow {
  date: string;
  season: string;
  div: string;
  name: string;
  /** Categorical slot, fixed per league (registry order). */
  slot: number;
  offset: number;
}

/**
 * Each league's baseline below the Premier League over time, one line per
 * league per season (the coefficient part steps at a season's start).
 * Wide: end labels, spread so close leagues don't overprint. Compact: no
 * end labels; the page shows the current offsets as a table instead (the
 * relief the light-mode palette needs).
 */
export function leagueOffsets(points: readonly OffsetRow[]): ChartSpec {
  const rows = points.map((p) => ({ ...p, when: new Date(`${p.date}T00:00:00Z`) }));
  type Row = (typeof rows)[number];
  const divs = [...new Set(rows.map((r) => r.div))];
  const last = divs.map((div) => rows.filter((r) => r.div === div).at(-1)!).sort((a, b) => b.offset - a.offset);

  return ({ Plot, width, height, compact, colors, style }) => {
    const color = (d: Row) => colors.series[d.slot % colors.series.length]!;
    const lo = Math.min(...rows.map((r) => r.offset));
    const hi = Math.max(...rows.map((r) => r.offset), 0);
    // Spread end labels ~14 px apart
    const gap = ((hi - lo) / Math.max(height - 40, 1)) * 14;
    let above: number | null = null;
    const labels = last.map((d) => {
      const y: number = above == null ? d.offset : Math.min(d.offset, above - gap);
      above = y;
      return { ...d, labelY: y };
    });

    return Plot.plot({
      width,
      height,
      style,
      marginTop: 12,
      marginBottom: 28,
      marginLeft: 44,
      marginRight: compact ? 12 : 160,
      x: { type: "utc", label: null, ticks: compact ? 4 : 8 },
      y: { label: null, grid: true, nice: true, tickFormat: (d: number) => signed(d, 0) },
      marks: [
        Plot.ruleY([0], { stroke: colors.text, strokeOpacity: 0.4 }),
        ...divs.map((div) =>
          Plot.lineY(
            rows.filter((r) => r.div === div),
            { x: "when", y: "offset", z: "season", stroke: color, strokeWidth: 2 },
          ),
        ),
        compact
          ? null
          : Plot.text(labels, { x: "when", y: "labelY", text: (d: Row & { labelY: number }) => `${d.name} ${signed(d.offset, 0)}`, dx: 6, textAnchor: "start", fill: colors.text }),
        Plot.tip(
          rows,
          Plot.pointer({
            x: "when",
            y: "offset",
            title: (d: Row) => `${d.name}, ${d.season}\n${shortDate(d.when)} ${d.when.getUTCFullYear()}: ${signed(d.offset, 1)}`,
          }),
        ),
      ],
    });
  };
}

// ============================================================
// V10: backtest accuracy per season
// ============================================================

export interface AccuracyRow {
  season: string;
  accuracy: number;
  baselineAccuracy: number;
  logLoss: number;
  trainedOn: string;
}

/**
 * V10: each test season's accuracy as a bar in the league colour, labelled,
 * with that season's always-home baseline as a thick tick across it. Same
 * on a phone, with larger labels (plan §3).
 */
export function backtestAccuracy(seasons: readonly AccuracyRow[]): ChartSpec {
  const top = Math.max(65, ...seasons.map((s) => Math.ceil((s.accuracy + 6) / 5) * 5));

  return ({ Plot, width, height, compact, colors, style }) =>
    Plot.plot({
      width,
      height,
      style: { ...style, fontSize: compact ? "13px" : style.fontSize! },
      marginTop: 16,
      marginBottom: 28,
      marginLeft: compact ? 34 : 40,
      marginRight: 4,
      x: { type: "band", domain: seasons.map((s) => s.season), label: null, padding: compact ? 0.3 : 0.4 },
      y: { domain: [0, top], label: null, grid: true, ticks: 5, tickFormat: (d: number) => `${d}%` },
      marks: [
        Plot.barY(seasons, { x: "season", y: "accuracy", fill: colors.league, fillOpacity: 0.85 }),
        Plot.tickY(seasons, { x: "season", y: "baselineAccuracy", stroke: colors.text, strokeWidth: 3 }),
        Plot.text(seasons, {
          x: "season",
          y: "accuracy",
          text: (d: AccuracyRow) => `${d.accuracy}%`,
          dy: -9,
          fill: colors.text,
          fontWeight: 700,
          fontSize: compact ? 14 : 13,
        }),
        Plot.ruleY([0], { stroke: colors.text, strokeOpacity: 0.5 }),
        Plot.tip(
          seasons,
          Plot.pointerX({
            x: "season",
            y: "accuracy",
            title: (d: AccuracyRow) =>
              `${d.season}: ${d.accuracy}% right\nAlways home: ${d.baselineAccuracy}%\nLog loss ${d.logLoss}\nTrained on ${d.trainedOn}`,
          }),
        ),
      ],
    });
}

// ============================================================
// V11: backtest profit, one small multiple per season
// ============================================================

export interface BacktestGameweekRow {
  gameweek: number;
  bets: number;
  hits: number;
  profit: number;
  cumulativeProfit: number;
}

/** What the small multiples share, so the seasons compare directly. */
export interface SeasonScale {
  /** y extent over every season's bars and running totals (and 0). */
  domain: [number, number];
  /** The longest season's last gameweek. */
  lastGameweek: number;
}

/** The shared scale for a set of seasons' gameweeks. */
export function seasonScale(seasons: readonly (readonly BacktestGameweekRow[])[]): SeasonScale {
  const values = seasons.flatMap((gws) => gws.flatMap((g) => [g.profit, g.cumulativeProfit])).concat(0);
  return {
    domain: [Math.min(...values), Math.max(...values)],
    lastGameweek: Math.max(1, ...seasons.flatMap((gws) => gws.map((g) => g.gameweek))),
  };
}

/**
 * V11: one backtest season's stake-1 profit per gameweek (light bars in
 * profit or loss colour) under the running total (a line in the league
 * colour, its final value labelled). `scale` is shared by every season.
 */
export function backtestSeasonProfit(gameweeks: readonly BacktestGameweekRow[], scale: SeasonScale): ChartSpec {
  const { domain, lastGameweek } = scale;
  const ticks = [1, 10, 20, 30, lastGameweek].filter((t, i, all) => t <= lastGameweek && all.indexOf(t) === i);
  const last = gameweeks.at(-1);

  return ({ Plot, width, height, compact, colors, style }) =>
    Plot.plot({
      width,
      height,
      style,
      marginTop: 10,
      marginBottom: 26,
      marginLeft: compact ? 34 : 40,
      marginRight: compact ? 40 : 44,
      x: { domain: [0.5, lastGameweek + 0.5], ticks, tickFormat: "d", label: null },
      y: { domain, nice: true, label: null, grid: true, ticks: compact ? 4 : 5, tickFormat: (d: number) => signed(d, 0) },
      marks: [
        Plot.rectY(gameweeks, {
          x1: (d: BacktestGameweekRow) => d.gameweek - 0.35,
          x2: (d: BacktestGameweekRow) => d.gameweek + 0.35,
          y: "profit",
          fill: (d: BacktestGameweekRow) => (d.profit >= 0 ? colors.pos : colors.neg),
          fillOpacity: 0.45,
        }),
        Plot.ruleY([0], { stroke: colors.text, strokeOpacity: 0.5 }),
        Plot.lineY(gameweeks, { x: "gameweek", y: "cumulativeProfit", stroke: colors.league, strokeWidth: 2.25, curve: "monotone-x" }),
        last
          ? Plot.text([last], {
              x: "gameweek",
              y: "cumulativeProfit",
              text: (d: BacktestGameweekRow) => signed(d.cumulativeProfit, 1),
              dx: 5,
              textAnchor: "start",
              fill: colors.text,
              fontWeight: 700,
              stroke: colors.surface,
              strokeWidth: 3,
              paintOrder: "stroke",
            })
          : null,
        Plot.dot(gameweeks, Plot.pointerX({ x: "gameweek", y: "cumulativeProfit", r: 4, fill: colors.league, stroke: colors.surface, strokeWidth: 1.5 })),
        Plot.tip(
          gameweeks,
          Plot.pointerX({
            x: "gameweek",
            y: "cumulativeProfit",
            title: (d: BacktestGameweekRow) =>
              `Gameweek ${d.gameweek}\n${d.hits} of ${d.bets} right\n${signed(d.profit)}u (season ${signed(d.cumulativeProfit)}u)`,
          }),
        ),
      ],
    });
}
