/**
 * The site's signature (plan §3 V1, §6): one bar split between a home win,
 * a draw and an away win. The pick's segment is solid, the others tinted;
 * the bar fills left to right when it appears (off under reduced motion).
 * Settled matches outline the segment that happened.
 *
 * Plain HTML/CSS - no JS needed, so it renders straight from Astro as well
 * as inside islands. Exposed to screen readers as one image with the
 * numbers in words.
 */

import type { CSSProperties } from "react";

import type { Outcome } from "../../lib/schema";
import { wholePercents } from "./probabilities";
import styles from "./ProbabilityStrip.module.css";

/** Narrower segments than this (in %) show no label. */
const LABEL_MIN = 9;

const OUTCOMES: Outcome[] = ["H", "D", "A"];

export interface ProbabilityStripProps {
  /** Probabilities in %, as exported (homeProb / drawProb / awayProb). */
  home: number;
  draw: number;
  away: number;
  pick: Outcome;
  /** What happened, once settled. */
  result?: Outcome | null;
  /** Team names, for the accessible description. */
  homeTeam?: string;
  awayTeam?: string;
  /** Position in a list: staggers the fill animation. */
  index?: number;
  size?: "regular" | "large";
}

export function describeOdds({
  home,
  draw,
  away,
  pick,
  result,
  homeTeam = "Home",
  awayTeam = "Away",
}: ProbabilityStripProps): string {
  const pct = wholePercents({ H: home, D: draw, A: away });
  const name: Record<Outcome, string> = { H: homeTeam, D: "a draw", A: awayTeam };
  const outcomeText: Record<Outcome, string> = { H: `${homeTeam} won`, D: "a draw", A: `${awayTeam} won` };

  let text = `${homeTeam} ${pct.H}%, draw ${pct.D}%, ${awayTeam} ${pct.A}%. Pick: ${name[pick]}.`;
  if (result) text += ` Result: ${outcomeText[result]}, pick ${result === pick ? "right" : "wrong"}.`;
  return text;
}

export default function ProbabilityStrip(props: ProbabilityStripProps) {
  const { home, draw, away, pick, result, index = 0, size = "regular" } = props;
  const exact: Record<Outcome, number> = { H: home, D: draw, A: away };
  const pct = wholePercents(exact);

  return (
    <span
      className={styles.strip}
      data-size={size}
      style={{ "--i": index } as CSSProperties}
      role="img"
      aria-label={describeOdds(props)}
    >
      {OUTCOMES.map((o) => (
        <span
          key={o}
          className={styles.seg}
          data-outcome={o}
          data-pick={o === pick || undefined}
          data-result={o === result || undefined}
          style={{ flexGrow: Math.max(exact[o], 0) }}
        >
          {pct[o] >= LABEL_MIN ? pct[o] : ""}
        </span>
      ))}
    </span>
  );
}
