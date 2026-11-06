/**
 * /_lab: the chart specs in PlotFigure, with one league's real data.
 * (An island, because chart specs are code; the page passes plain data.)
 */

import { useMemo } from "react";

import { signed } from "../../lib/format";
import type { BankrollPoint, GameweekSummary } from "../../lib/schema";
import Legend from "../charts/Legend";
import PlotFigure from "../charts/PlotFigure";
import { gameweekProfit, ratingChartHeight, ratingVsAverage, runningProfit, type RatingRow } from "../charts/specs";
import styles from "./Lab.module.css";

interface Props {
  league: string;
  leagueName: string;
  bankroll: BankrollPoint[];
  gameweeks: GameweekSummary[];
  ratings: RatingRow[];
}

export default function LabCharts({ league, leagueName, bankroll, gameweeks, ratings }: Props) {
  const profit = useMemo(() => runningProfit(bankroll), [bankroll]);
  const latestSettled = gameweeks.filter((g) => g.profit != null).at(-1)?.gameweek;
  const perGameweek = useMemo(() => gameweekProfit(gameweeks, latestSettled), [gameweeks, latestSettled]);
  const vsAverage = useMemo(() => ratingVsAverage(ratings), [ratings]);
  const final = bankroll.at(-1)?.cumulative ?? 0;

  return (
    <div className={styles.charts}>
      <section>
        <h3>V2 · Running profit</h3>
        <p className={styles.big} data-tone={final >= 0 ? "pos" : "neg"}>
          {signed(final)}u
        </p>
        <PlotFigure
          label={`${leagueName}: simulated profit after ${bankroll.length} picks, ${signed(final)} units`}
          spec={profit}
          height={220}
          compactHeight={80}
          league={league}
        />
      </section>

      <section>
        <h3>V4 · Profit per gameweek</h3>
        <PlotFigure
          label={`${leagueName}: simulated profit per gameweek, gameweek ${latestSettled ?? "-"} highlighted`}
          spec={perGameweek}
          height={220}
          compactHeight={180}
          league={league}
          caption={
            <Legend
              items={[
                { label: "Profit", color: "var(--pos)" },
                { label: "Loss", color: "var(--neg)" },
              ]}
            />
          }
        />
      </section>

      <section>
        <h3>V9 · Elo against the average</h3>
        <PlotFigure
          label={`${leagueName}: each club's Elo rating against the 1500 average`}
          spec={vsAverage}
          height={ratingChartHeight(ratings.length)}
          compactHeight={ratingChartHeight(ratings.length, true)}
          league={league}
        />
      </section>
    </div>
  );
}
