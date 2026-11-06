/**
 * One fixture (plan §3 V1, P7-01 mockup): kick-off, teams with the pick in
 * bold, the probability strip, and on tap the ratings behind it (and the
 * result, once played).
 *
 * The expand is a native <details>, so it works without JavaScript and the
 * card can be rendered straight from an Astro page. Put cards in a
 * <FixtureList> for the shared borders.
 *
 *   <FixtureList>
 *     {fixtures.map((f, i) => <FixtureCard fixture={f} index={i} />)}
 *   </FixtureList>
 */

import type { ReactNode } from "react";

import { formatKickoff, resultName } from "../../lib/format";
import type { Fixture, Outcome } from "../../lib/schema";
import styles from "./FixtureCard.module.css";
import ProbabilityStrip from "./ProbabilityStrip";

export type CardFixture = Pick<
  Fixture,
  "kickoff" | "home" | "away" | "prediction" | "homeProb" | "drawProb" | "awayProb" | "result"
> &
  Partial<Pick<Fixture, "homeElo" | "awayElo" | "eloGap">>;

export interface FixtureCardProps {
  fixture: CardFixture;
  /** Position in the list: staggers the strip's fill. */
  index?: number;
  /** "time" = 20:00 (under a day heading), "day" = Fri 20:00, "date" = Fri 6 Nov, 20:00. */
  when?: "time" | "day" | "date";
  /** Small labels next to the kick-off, e.g. "Rearranged", "Backfilled". */
  tags?: string[];
  /** Extra lines in the expanded part (e.g. the stake on the Results page). */
  children?: ReactNode;
}

const exact = (v: number) => `${Number(v.toFixed(1))}%`;

const KICKOFF_STYLE = { time: "time", day: "short", date: "long" } as const;

function pickName(f: CardFixture, pick: Outcome): string {
  return pick === "H" ? f.home : pick === "A" ? f.away : "a draw";
}

function ratingsLine(f: CardFixture): string | undefined {
  if (f.homeElo == null || f.awayElo == null || f.eloGap == null) return undefined;

  const ratings = `Ratings: ${f.home} ${Math.round(f.homeElo)}, ${f.away} ${Math.round(f.awayElo)}.`;
  if (Math.round(f.eloGap) === 0) return `${ratings} Level once home advantage is included.`;

  const ahead = f.eloGap > 0 ? f.home : f.away;
  return `${ratings} ${ahead} ahead by ${Math.abs(Math.round(f.eloGap))} including home advantage.`;
}

export default function FixtureCard({ fixture: f, index = 0, when = "time", tags = [], children }: FixtureCardProps) {
  const pick = f.prediction;
  const ratings = ratingsLine(f);
  const right = f.result ? f.result === pick : undefined;

  return (
    <li className={styles.card}>
      <details>
        <summary>
          <span className={styles.row}>
            <span className={styles.time}>
              <time dateTime={f.kickoff}>{formatKickoff(f.kickoff, KICKOFF_STYLE[when])}</time>
              {tags.map((t) => (
                <span key={t} className={styles.tag}>
                  {t}
                </span>
              ))}
            </span>
            <span className={styles.teams}>
              <span data-picked={pick === "H" || undefined}>{f.home}</span>
              <span className={styles.vs}> v </span>
              <span data-picked={pick === "A" || undefined}>{f.away}</span>
            </span>
            <span className={styles.strip}>
              <ProbabilityStrip
                home={f.homeProb}
                draw={f.drawProb}
                away={f.awayProb}
                pick={pick}
                result={f.result}
                homeTeam={f.home}
                awayTeam={f.away}
                index={index}
              />
            </span>
            {right != null && (
              <span className={styles.verdict} data-right={right}>
                {right ? "✓ Right" : "✗ Wrong"}
              </span>
            )}
            <svg className={styles.chev} viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
              <path d="M2 4.5 6 8.5 10 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
            </svg>
          </span>
        </summary>
        <div className={styles.more}>
          <p>
            Pick: <b>{pickName(f, pick)}</b>
            {f.result && (
              <>
                {" "}
                · Result: <b>{f.result === "D" ? "Draw" : `${resultName[f.result]} win`}</b>
              </>
            )}
          </p>
          <p>
            Home {exact(f.homeProb)} · draw {exact(f.drawProb)} · away {exact(f.awayProb)}
          </p>
          {ratings && <p>{ratings}</p>}
          {children}
        </div>
      </details>
    </li>
  );
}

/** The bordered list that holds FixtureCards. */
export function FixtureList({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <ul className={styles.list} aria-label={label}>
      {children}
    </ul>
  );
}
