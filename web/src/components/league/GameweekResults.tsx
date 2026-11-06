/**
 * /{c}/gameweeks/ (Results, plan §3 V4): one gameweek at a time.
 *
 *   picker      previous / select / next; the choice is kept in the URL
 *               (#gw9), so a gameweek can be linked to
 *   scoreboard  status, picks right, profit, season total
 *   chips       "Rearranged" (played > 4 days from the rest of its
 *               gameweek) and "Backfilled" (predicted after it was played),
 *               each explained once above the list
 *   cards       every prediction with its result, ✓/✗ and stake
 *   V4          profit per gameweek, the chosen one highlighted; tap or
 *               click a bar to jump to that gameweek. Scrolls sideways on
 *               a phone, starting at the chosen gameweek.
 *
 * Server-rendered at the latest gameweek, so the page reads fine before
 * (or without) hydration.
 */

import { useEffect, useId, useMemo, useState } from "react";

import { rearranged } from "../../lib/fixtures";
import { kickoffRange, signed } from "../../lib/format";
import type { Bet, GameweekSummary } from "../../lib/schema";
import PlotFigure from "../charts/PlotFigure";
import ScrollChart from "../charts/ScrollChart";
import { gameweekProfit } from "../charts/specs";
import FixtureCard, { FixtureList } from "../fixtures/FixtureCard";
import ScoreStrip, { toneOf, type ScoreItem } from "../kpi/ScoreStrip";
import styles from "./GameweekResults.module.css";

export type ResultBet = Pick<
  Bet,
  | "gameweek"
  | "kickoff"
  | "home"
  | "away"
  | "prediction"
  | "homeProb"
  | "drawProb"
  | "awayProb"
  | "result"
  | "profit"
  | "won"
  | "settled"
  | "backfilled"
>;

interface Props {
  league: string;
  leagueName: string;
  bets: ResultBet[];
  gameweeks: GameweekSummary[];
}

const STATUS = { pending: "Pending", partial: "In progress", complete: "Complete" } as const;

const fromHash = (gameweeks: number[]): number | undefined => {
  const n = Number(/^#gw(\d+)$/.exec(window.location.hash)?.[1]);
  return gameweeks.includes(n) ? n : undefined;
};

export default function GameweekResults({ league, leagueName, bets, gameweeks }: Props) {
  const all = useMemo(() => [...new Set(bets.map((b) => b.gameweek))].sort((a, b) => a - b), [bets]);
  const [gw, setGw] = useState(all.at(-1) ?? 0);
  const id = useId();

  // #gw9 in the URL picks the gameweek; the choice goes back into it
  useEffect(() => {
    const initial = fromHash(all);
    if (initial != null) setGw(initial);
    const onHash = () => {
      const n = fromHash(all);
      if (n != null) setGw(n);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [all]);

  const choose = (n: number) => {
    if (!all.includes(n)) return;
    setGw(n);
    history.replaceState(history.state, "", `#gw${n}`);
  };

  const shown = useMemo(
    () => bets.filter((b) => b.gameweek === gw).sort((a, b) => a.kickoff.localeCompare(b.kickoff)),
    [bets, gw],
  );
  const moved = useMemo(() => rearranged(shown), [shown]);
  const anyBackfilled = shown.some((b) => b.backfilled);
  const summary: GameweekSummary = gameweeks.find((g) => g.gameweek === gw) ?? {
    gameweek: gw,
    bets: shown.length,
    settled: 0,
    hits: 0,
    hitRate: null,
    profit: null,
    cumulativeProfit: null,
    status: "pending",
  };

  const score: ScoreItem[] = [
    { label: `${summary.settled} of ${summary.bets} settled`, value: STATUS[summary.status] },
    {
      label: summary.hitRate == null ? "picks right" : `picks right (${summary.hitRate}%)`,
      value: summary.settled ? `${summary.hits}/${summary.settled}` : "—",
    },
    {
      label: "simulated profit",
      value: summary.profit == null ? "—" : `${signed(summary.profit)}u`,
      tone: summary.profit == null ? undefined : toneOf(summary.profit),
    },
    {
      label: "season so far",
      value: summary.cumulativeProfit == null ? "—" : `${signed(summary.cumulativeProfit)}u`,
      tone: summary.cumulativeProfit == null ? undefined : toneOf(summary.cumulativeProfit),
    },
  ];

  const spec = useMemo(() => gameweekProfit(gameweeks, gw), [gameweeks, gw]);
  const settledGws = gameweeks.filter((g) => g.profit != null).map((g) => g.gameweek);
  const focus = settledGws.includes(gw) ? settledGws.indexOf(gw) : settledGws.length - 1;
  const index = all.indexOf(gw);

  return (
    <div className={styles.results}>
      <div className={styles.picker}>
        <button
          type="button"
          className={styles.step}
          onClick={() => choose(all[index - 1]!)}
          disabled={index <= 0}
          aria-label="Previous gameweek"
        >
          <svg viewBox="0 0 12 12" width="14" height="14" aria-hidden="true">
            <path d="M7.5 2 3.5 6l4 4" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        <label className={styles.select}>
          <span className={styles.srOnly}>Gameweek</span>
          <select value={gw} onChange={(e) => choose(Number(e.target.value))}>
            {all.map((n) => (
              <option key={n} value={n}>
                Gameweek {n}
              </option>
            ))}
          </select>
          <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
            <path d="M2 4.5 6 8.5 10 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </label>
        <button
          type="button"
          className={styles.step}
          onClick={() => choose(all[index + 1]!)}
          disabled={index >= all.length - 1}
          aria-label="Next gameweek"
        >
          <svg viewBox="0 0 12 12" width="14" height="14" aria-hidden="true">
            <path d="m4.5 2 4 4-4 4" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        <span className={styles.dates}>{kickoffRange(shown.map((b) => b.kickoff))}</span>
      </div>

      <p className={styles.srOnly} aria-live="polite">
        Gameweek {gw}: {STATUS[summary.status]}
        {summary.settled ? `, ${summary.hits} of ${summary.settled} right` : ""}
        {summary.profit == null ? "" : `, ${signed(summary.profit)} units`}.
      </p>

      <ScoreStrip label={`Gameweek ${gw}`} items={score} />

      <section aria-labelledby={`${id}-preds`}>
        <h2 id={`${id}-preds`} className={styles.h2}>
          Predictions
        </h2>
        {moved.size > 0 && (
          <p className={styles.note}>
            <span className={styles.chip}>Rearranged</span> Gameweeks are the league's scheduled matchdays, so a
            rearranged game stays in its original gameweek even when it's played days or weeks later.
          </p>
        )}
        {anyBackfilled && (
          <p className={styles.note}>
            <span className={styles.chip}>Backfilled</span> Predicted after it was played, by a model trained only on the
            matches before it kicked off, because this league joined the model mid-season.
          </p>
        )}
        <FixtureList label={`${leagueName}, gameweek ${gw}`}>
          {shown.map((b, i) => (
            <FixtureCard
              key={`${gw}-${b.kickoff}-${b.home}`}
              fixture={b}
              index={i}
              when="date"
              tags={[...(moved.has(i) ? ["Rearranged"] : []), ...(b.backfilled ? ["Backfilled"] : [])]}
            >
              <p>
                Simulated stake:{" "}
                {b.settled ? (
                  <b className={styles.money} data-tone={b.profit == null ? undefined : toneOf(b.profit)}>
                    {b.won ? "won" : "lost"} {signed(b.profit)}u
                  </b>
                ) : (
                  "not settled yet"
                )}
              </p>
            </FixtureCard>
          ))}
        </FixtureList>
      </section>

      <section aria-labelledby={`${id}-chart`}>
        <h2 id={`${id}-chart`} className={styles.h2}>
          Where each gameweek landed
        </h2>
        <p className={styles.lede}>Simulated profit per gameweek, one unit a pick. Tap a bar to see that gameweek.</p>
        {settledGws.length ? (
          <ScrollChart count={settledGws.length} focus={focus} label="Profit per gameweek">
            {(compact) => (
              <PlotFigure
                spec={spec}
                label={`${leagueName}: simulated profit in each of ${settledGws.length} settled gameweeks; gameweek ${gw} highlighted`}
                height={240}
                league={league}
                compact={compact || undefined}
                scrub={false}
                onPick={(d) => choose((d as GameweekSummary).gameweek)}
              />
            )}
          </ScrollChart>
        ) : (
          <p className={styles.lede}>No gameweek settled yet.</p>
        )}
      </section>
    </div>
  );
}
