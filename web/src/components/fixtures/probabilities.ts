/**
 * Whole-number percentages for the probability strip's labels.
 */

import type { Outcome } from "../../lib/schema";

export type Probabilities = Record<Outcome, number>;

/**
 * Round home / draw / away to whole numbers that still add up to 100
 * (largest remainder), so a strip never reads "55 · 23 · 21". Ties go to
 * the earlier outcome, H before D before A. Inputs that don't sum to ~100
 * are scaled first.
 */
export function wholePercents(p: Probabilities): Probabilities {
  const keys: Outcome[] = ["H", "D", "A"];
  const total = keys.reduce((sum, k) => sum + Math.max(0, p[k]), 0);

  if (total <= 0) return { H: 0, D: 0, A: 0 };

  const exact = keys.map((k) => (Math.max(0, p[k]) / total) * 100);
  const floors = exact.map(Math.floor);
  let left = 100 - floors.reduce((a, b) => a + b, 0);

  const order = exact
    .map((value, i) => ({ i, rest: value - floors[i]! }))
    .sort((a, b) => b.rest - a.rest || a.i - b.i);

  for (const { i } of order) {
    if (left <= 0) break;
    floors[i]! += 1;
    left -= 1;
  }

  return { H: floors[0]!, D: floors[1]!, A: floors[2]! };
}
