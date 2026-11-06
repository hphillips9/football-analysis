/**
 * KPI scoreboard (plan §3 "KPIs"): one strip instead of a grid of cards,
 *
 *   41–49   45.6%      −12.38u    −13.8%
 *   won,    picks      simulated  return on
 *   lost    right      profit     stakes
 *
 * Values are pre-formatted strings; `tone` colours profit and loss, which
 * always carry their sign too (never colour alone). In a narrow container
 * (< 480 px) the items wrap into two columns.
 * Plain HTML: renders from Astro with no JS.
 */

import { signed } from "../../lib/format";
// Types only: schema.ts at runtime would pull zod into any island using this
import type { CompetitionStats, OverallStats } from "../../lib/schema";
import styles from "./ScoreStrip.module.css";

export interface ScoreItem {
  label: string;
  value: string;
  tone?: "pos" | "neg";
}

export interface ScoreStripProps {
  items: ScoreItem[];
  /** Accessible name for the group, e.g. "Season record". */
  label: string;
}

export default function ScoreStrip({ items, label }: ScoreStripProps) {
  return (
    <div className={styles.wrap}>
      <dl className={styles.strip} aria-label={label}>
      {items.map((item) => (
        <div key={item.label} className={styles.item}>
          <dt>{item.label}</dt>
          <dd data-tone={item.tone}>{item.value}</dd>
        </div>
      ))}
      </dl>
    </div>
  );
}

/** Sign → tone, for a profit-like number. */
export const toneOf = (value: number): ScoreItem["tone"] =>
  value > 0.005 ? "pos" : value < -0.005 ? "neg" : undefined;

/** The standard record strip for a league's (or the overall) stats; empty with nothing settled. */
export function recordItems(stats: CompetitionStats | OverallStats | undefined): ScoreItem[] {
  if (!stats || stats.asOf === null) return [];

  return [
    { label: "won, lost", value: `${stats.wins}–${stats.losses}` },
    { label: "picks right", value: `${stats.hitRate.toFixed(1)}%` },
    { label: "simulated profit", value: `${signed(stats.profit)}u`, tone: toneOf(stats.profit) },
    { label: "return on stakes", value: `${signed(stats.roi, 1)}%`, tone: toneOf(stats.roi) },
  ];
}
