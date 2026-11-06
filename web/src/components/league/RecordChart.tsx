/**
 * The Record page's charts (plan §3), one island each so each hydrates and
 * draws only when it scrolls into view:
 *
 *   season       V5  gameweek bars + running total (scrolls on a phone)
 *   bets         V6  bet-by-bet running total
 *   calibration  V7  calibration bubbles (square on a phone)
 */

import { useMemo } from "react";

import { signed } from "../../lib/format";
import type { BankrollPoint, CalibrationBin, GameweekSummary } from "../../lib/schema";
import Legend from "../charts/Legend";
import PlotFigure from "../charts/PlotFigure";
import ScrollChart from "../charts/ScrollChart";
import { betByBet, calibration, seasonProfit } from "../charts/specs";
import styles from "./RecordChart.module.css";

type Props = { league: string; leagueName: string } & (
  | { kind: "season"; gameweeks: GameweekSummary[] }
  | { kind: "bets"; bankroll: BankrollPoint[] }
  | { kind: "calibration"; bins: CalibrationBin[] }
);

export default function RecordChart(props: Props) {
  const { league, leagueName } = props;

  const spec = useMemo(
    () =>
      props.kind === "season"
        ? seasonProfit(props.gameweeks)
        : props.kind === "bets"
          ? betByBet(props.bankroll)
          : calibration(props.bins),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.kind === "season" ? props.gameweeks : props.kind === "bets" ? props.bankroll : props.bins],
  );

  if (props.kind === "season") {
    const settled = props.gameweeks.filter((g) => g.profit != null);
    const last = settled.at(-1);
    // The legend sits outside the scroller, so it stays in view on a phone
    return (
      <>
        <ScrollChart count={settled.length} label="Profit and loss by gameweek">
          {(compact) => (
            <PlotFigure
              spec={spec}
              label={`${leagueName}: simulated profit in each of ${settled.length} gameweeks, with the running total${last?.cumulativeProfit != null ? `, now ${signed(last.cumulativeProfit)} units` : ""}`}
              height={320}
              league={league}
              compact={compact || undefined}
              scrub={false}
            />
          )}
        </ScrollChart>
        <div className={styles.legend}>
          <Legend
            items={[
              { label: "Gameweek profit", color: "var(--pos)" },
              { label: "Gameweek loss", color: "var(--neg)" },
              { label: "Running total", color: "var(--lg-chart)", shape: "line" },
            ]}
          />
        </div>
      </>
    );
  }

  if (props.kind === "bets") {
    const last = props.bankroll.at(-1);
    return (
      <PlotFigure
        spec={spec}
        label={`${leagueName}: running simulated profit after each of ${props.bankroll.length} bets${last ? `, now ${signed(last.cumulative)} units` : ""}`}
        height={300}
        compactHeight={220}
        league={league}
      />
    );
  }

  return (
    <PlotFigure
      spec={spec}
      label={`${leagueName}: calibration of the model's picks across ${props.bins.length} probability bands`}
      height={340}
      compactHeight={320}
      league={league}
      caption={
        <Legend
          items={[
            { label: "A probability band (size = bets in it)", color: "var(--lg-chart)", shape: "dot" },
            { label: "Perfect calibration", color: "var(--muted)", shape: "line" },
          ]}
        />
      }
    />
  );
}
