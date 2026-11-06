/**
 * Display helpers, ported from the Observable site's
 * web/src/components/charts.js (signed, gameweekSpan, resultName) plus
 * the date formatting its pages did inline.
 *
 * Pages render at build time, so nothing here may depend on the machine's
 * locale or timezone (CI runs in UTC): dates are always en-GB, kick-offs
 * are shown in UK time as exported, and export timestamps are converted to
 * UK time explicitly.
 */

import type { Outcome } from "./schema";

const LOCALE = "en-GB";
const UK = "Europe/London";

/** Proper minus sign for display, not the hyphen toFixed gives. */
const MINUS = "−";

/**
 * A number with an explicit sign and fixed decimals: +1.25, −0.50, +0.00.
 * "—" when there's no value (unpriced, nothing settled yet).
 */
export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";

  const fixed = Math.abs(value).toFixed(digits);
  // A value that rounds to zero shows as +0.00, never −0.00
  const isZero = Number(fixed) === 0;

  return (value < 0 && !isZero ? MINUS : "+") + fixed;
}

/** "gameweek 7", or "gameweeks 3–9" for a range. */
export function gameweekSpan([first, last]: readonly [number, number]): string {
  return first === last ? `gameweek ${first}` : `gameweeks ${first}–${last}`;
}

export const resultName: Record<Outcome, string> = { H: "Home", D: "Draw", A: "Away" };

// ============================================================
// DATES
// ============================================================

/**
 * A naive UK kick-off ("2026-11-06T20:00:00") as a Date whose UTC fields
 * are the UK wall-clock time. Formatting it with timeZone "UTC" then shows
 * exactly the exported time, wherever the build runs.
 */
function wallClock(kickoff: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(kickoff);

  if (!match) throw new Error(`Not a kick-off time: "${kickoff}"`);

  const [, y, mo, d, h, mi] = match.map(Number);
  return new Date(Date.UTC(y!, mo! - 1, d!, h!, mi!));
}

const kickoffFormats = {
  /** "Fri 20:00" */
  short: { weekday: "short", hour: "2-digit", minute: "2-digit" },
  /** "Fri 6 Nov, 20:00" */
  long: { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" },
  /** "Fri 6 Nov" */
  day: { weekday: "short", day: "numeric", month: "short" },
  /** "Friday 6 November" (day headings) */
  dayLong: { weekday: "long", day: "numeric", month: "long" },
  /** "20:00" */
  time: { hour: "2-digit", minute: "2-digit" },
} satisfies Record<string, Intl.DateTimeFormatOptions>;

export type KickoffStyle = keyof typeof kickoffFormats;

/** A kick-off in UK time. */
export function formatKickoff(kickoff: string, style: KickoffStyle = "long"): string {
  return new Intl.DateTimeFormat(LOCALE, { ...kickoffFormats[style], timeZone: "UTC" }).format(wallClock(kickoff));
}

/** "Fri 6 Nov – Mon 9 Nov" for the first and last kick-off of a set (one day: "Fri 6 Nov"). */
export function kickoffRange(kickoffs: readonly string[]): string {
  if (kickoffs.length === 0) return "";

  const sorted = [...kickoffs].sort();
  const first = formatKickoff(sorted[0]!, "day");
  const last = formatKickoff(sorted[sorted.length - 1]!, "day");

  return first === last ? first : `${first} – ${last}`;
}

/** A football-data.co.uk date ("06/11/2026") as "6 Nov 2026". */
export function formatMatchDate(dayMonthYear: string): string {
  const [d, m, y] = dayMonthYear.split("/").map(Number);

  return new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(y!, m! - 1, d!)),
  );
}

/** An export timestamp ("2026-11-05T11:47:35+00:00") in UK time: "5 Nov 2026, 11:47". */
export function formatUpdated(generated: string): string {
  return new Intl.DateTimeFormat(LOCALE, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: UK,
  }).format(new Date(generated));
}
