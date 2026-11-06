/**
 * /about/: the backtest for one competition at a time (the Observable
 * page's "Pick a competition" select drove both of these parts):
 *
 *   How it scored        accuracy / edge / log loss strip, V10, per-season table
 *   Would it have made   profit / ROI strip, V11 small multiples (a swipe
 *   money?               carousel on a phone), one shared y-scale
 *
 * Each part has its own select, both bound to the same choice, so the
 * second section doesn't depend on scrolling back up. The choice sets
 * data-league on the island, so charts and legends take that league's
 * colour.
 *
 * The seasons' gameweek-by-gameweek profit (V11's data) comes from a JSON
 * block in the page (lib/pageData.ts), not props.
 */

import type { ColumnDef } from "@tanstack/react-table";
import { useId, useMemo, useState } from "react";

import { signed } from "../../lib/format";
import { usePageData } from "../../lib/pageData";
import { leagueAttr } from "../../theme/themes";
import Carousel from "../carousel/Carousel";
import Legend from "../charts/Legend";
import PlotFigure from "../charts/PlotFigure";
import {
  backtestAccuracy,
  backtestSeasonProfit,
  seasonScale,
  type BacktestGameweekRow,
} from "../charts/specs";
import ScoreStrip, { toneOf, type ScoreItem } from "../kpi/ScoreStrip";
import DataTable from "../table/DataTable";
import Money from "./Money";
import styles from "./Method.module.css";

export interface Numbers {
  matches: number;
  accuracy: number;
  baselineAccuracy: number;
  edge: number;
  logLoss: number;
  profit: number;
  roi: number;
}

export interface SeasonRow extends Numbers {
  season: string;
  trainedOn: string;
}

export interface BacktestCompetition {
  div: string;
  name: string;
  overall: Numbers | null;
  seasons: SeasonRow[];
}

/** div → season → flat [gameweek, bets, hits, profit, cumulativeProfit, ...]. */
export type GameweekData = Record<string, Record<string, number[]>>;

interface Props {
  competitions: BacktestCompetition[];
  initial: string;
  /** Id of the page's JSON block with GameweekData. */
  dataId: string;
}

const count = (n: number) => n.toLocaleString("en-GB");
const pct = (n: number) => `${n}%`;

const seasonColumns: ColumnDef<SeasonRow, any>[] = [
  { accessorKey: "season", header: "Season" },
  { accessorKey: "matches", header: "Matches", meta: { align: "end", priority: "extra" }, cell: (c) => count(c.getValue<number>()) },
  { accessorKey: "trainedOn", header: "Trained on", enableSorting: false, meta: { priority: "extra" } },
  { accessorKey: "accuracy", header: "Acc", meta: { label: "Accuracy", align: "end" }, cell: (c) => pct(c.getValue<number>()) },
  { accessorKey: "baselineAccuracy", header: "Base", meta: { label: "Always home", align: "end", priority: "extra" }, cell: (c) => pct(c.getValue<number>()) },
  { accessorKey: "edge", header: "Edge", meta: { label: "Edge (points)", align: "end" }, cell: (c) => signed(c.getValue<number>(), 1) },
  { accessorKey: "logLoss", header: "Log loss", meta: { align: "end", priority: "extra" } },
  { accessorKey: "profit", header: "Profit", meta: { label: "Profit (units)", align: "end", priority: "extra" }, cell: (c) => <Money value={c.getValue<number>()} unit="u" /> },
  { accessorKey: "roi", header: "ROI", meta: { label: "ROI", align: "end" }, cell: (c) => <Money value={c.getValue<number>()} digits={1} unit="%" /> },
];

function unpack(flat: number[] | undefined): BacktestGameweekRow[] {
  const rows: BacktestGameweekRow[] = [];
  if (!flat) return rows;
  for (let i = 0; i + 4 < flat.length; i += 5) {
    rows.push({ gameweek: flat[i]!, bets: flat[i + 1]!, hits: flat[i + 2]!, profit: flat[i + 3]!, cumulativeProfit: flat[i + 4]! });
  }
  return rows;
}

function CompetitionSelect({
  competitions,
  value,
  onChange,
}: {
  competitions: BacktestCompetition[];
  value: string;
  onChange: (div: string) => void;
}) {
  return (
    <div className={styles.filters}>
      <label>
        <span>Competition</span>
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {competitions.map((c) => (
            <option key={c.div} value={c.div}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

export default function BacktestExplorer({ competitions, initial, dataId }: Props) {
  const [div, setDiv] = useState(initial);
  const gameweekData = usePageData<GameweekData>(dataId);
  const moneyHeading = useId();

  const chosen = competitions.find((c) => c.div === div) ?? competitions[0]!;
  const { overall, seasons, name } = chosen;

  const accuracySpec = useMemo(() => backtestAccuracy(seasons), [seasons]);

  // Every season's gameweeks, and the scale they share
  const seasonGameweeks = useMemo(
    () => seasons.map((s) => unpack(gameweekData?.[chosen.div]?.[s.season])),
    [gameweekData, chosen.div, seasons],
  );
  const scale = useMemo(() => seasonScale(seasonGameweeks), [seasonGameweeks]);
  const seasonSpecs = useMemo(() => seasonGameweeks.map((gws) => backtestSeasonProfit(gws, scale)), [seasonGameweeks, scale]);

  const scored: ScoreItem[] = overall
    ? [
        { label: `right, over ${count(overall.matches)} matches`, value: pct(overall.accuracy) },
        { label: `points better than always home (${overall.baselineAccuracy}%)`, value: signed(overall.edge, 1) },
        { label: "log loss (lower is better)", value: String(overall.logLoss) },
      ]
    : [];

  const inProfit = seasons.filter((s) => s.profit > 0).length;
  const money: ScoreItem[] = overall
    ? [
        {
          label: `profit over all ${seasons.length} seasons, on ${count(overall.matches)} units staked`,
          value: `${signed(overall.profit)}u`,
          tone: toneOf(overall.profit),
        },
        {
          label: `return on stakes · ${inProfit} of ${seasons.length} seasons in profit`,
          value: `${signed(overall.roi, 1)}%`,
          tone: toneOf(overall.roi),
        },
      ]
    : [];

  const select = <CompetitionSelect competitions={competitions} value={chosen.div} onChange={setDiv} />;

  if (!overall || seasons.length === 0) {
    return (
      <div className={styles.block} data-league={leagueAttr(chosen.div)}>
        {select}
        <p className={styles.note}>No backtest season for {name} yet.</p>
      </div>
    );
  }

  return (
    <div className={styles.explorer} data-league={leagueAttr(chosen.div)}>
      <div className={styles.block}>
        {select}
        <p className={styles.srOnly} aria-live="polite">
          Showing {name}
        </p>
        <ScoreStrip label={`${name}: backtest over ${seasons.length} seasons`} items={scored} />
        <PlotFigure
          spec={accuracySpec}
          label={`${name}: accuracy in each of ${seasons.length} backtest seasons, against always backing the home side`}
          height={260}
          compactHeight={240}
          caption={
            <Legend
              items={[
                { label: "Picks right", color: "var(--lg-chart)" },
                { label: "Always home (that season's baseline)", color: "var(--text)", shape: "line" },
              ]}
            />
          }
        />
        <DataTable
          data={seasons}
          columns={seasonColumns}
          caption={`${name}: backtest season by season`}
          getRowId={(s) => s.season}
        />
      </div>

      <section className={styles.block} aria-labelledby={moneyHeading}>
        <h2 id={moneyHeading} className={styles.h2}>
          Would it have made money?
        </h2>
        <p className={styles.prose}>
          The same backtest, but staking <b>1 unit on every pick</b> of each season, settled at the market-average
          pre-match price (Sky Bet odds aren't available for past seasons). Bars are each gameweek's result; the line is
          the running total. The season charts share one scale so the seasons compare directly.
        </p>
        {select}
        <ScoreStrip label={`${name}: backtest simulated stakes`} items={money} />
        <Carousel
          label={`${name}: simulated profit, season by season`}
          slides={seasons.map((s, i) => ({
            key: `${chosen.div}-${s.season}`,
            title: s.season,
            content: (
              <article className={styles.season}>
                <h3>{s.season}</h3>
                <p>
                  <Money value={s.profit} unit="u" /> · ROI <Money value={s.roi} digits={1} unit="%" /> · {s.accuracy}% right
                </p>
                <PlotFigure
                  spec={seasonSpecs[i]!}
                  label={`${name} ${s.season}: simulated profit per gameweek and running total, finishing ${signed(s.profit)} units`}
                  height={220}
                  compactHeight={200}
                  ready={gameweekData != null}
                />
              </article>
            ),
          }))}
        />
        <Legend
          items={[
            { label: "Gameweek profit", color: "var(--pos)" },
            { label: "Gameweek loss", color: "var(--neg)" },
            { label: "Running total", color: "var(--lg-chart)", shape: "line" },
          ]}
        />
        <p className={styles.note}>
          These are simulated bets, not a real record: a single bookmaker's price can be a little worse than the market
          average, which would shave the returns. Each league's Record tab has the live bets.
        </p>
      </section>
    </div>
  );
}
