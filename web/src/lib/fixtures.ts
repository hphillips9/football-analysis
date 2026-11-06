/**
 * Small helpers over fixtures for the fixture pages (/, /matchday/, /{c}/).
 */

import type { Outcome } from "./schema";

interface Probable {
  prediction: Outcome;
  homeProb: number;
  drawProb: number;
  awayProb: number;
}

/** The model's probability for its own pick, in %. */
export function pickProb(f: Probable): number {
  return f.prediction === "H" ? f.homeProb : f.prediction === "D" ? f.drawProb : f.awayProb;
}

/** The pick with the highest probability (first one on a tie); undefined for none. */
export function mostConfident<T extends Probable>(fixtures: readonly T[]): T | undefined {
  return fixtures.reduce<T | undefined>((best, f) => (!best || pickProb(f) > pickProb(best) ? f : best), undefined);
}

export interface Day<T> {
  /** "2026-11-06" (UK date, as exported). */
  date: string;
  fixtures: T[];
}

/** Fixtures grouped by kick-off date, in kick-off order. */
export function byDay<T extends { kickoff: string }>(fixtures: readonly T[]): Day<T>[] {
  const days = new Map<string, T[]>();

  for (const f of [...fixtures].sort((a, b) => a.kickoff.localeCompare(b.kickoff))) {
    const date = f.kickoff.slice(0, 10);
    days.set(date, [...(days.get(date) ?? []), f]);
  }

  return [...days].map(([date, list]) => ({ date, fixtures: list }));
}

const NUMBER_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];

/** "seven" for 7, "12" for 12 (house style: words up to ten). */
export function numberWord(n: number): string {
  return NUMBER_WORDS[n] ?? String(n);
}

const DAY_MS = 86_400_000;

/**
 * Games played more than 4 days from the rest of their gameweek: the
 * league's official matchday stays, so a rearranged game sits in its
 * original gameweek even when it's played weeks later. Same rule as the
 * Observable Gameweeks page (distance from the gameweek's median kick-off).
 * Returns the indexes into `games`.
 */
export function rearranged(games: readonly { kickoff: string }[]): Set<number> {
  const times = games.map((g) => Date.parse(`${g.kickoff}Z`));
  const sorted = [...times].sort((a, b) => a - b);
  if (!sorted.length) return new Set();

  const mid = sorted.length >> 1;
  const median = sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;

  return new Set(times.flatMap((t, i) => (Math.abs(t - median) > 4 * DAY_MS ? [i] : [])));
}
