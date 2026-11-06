/**
 * The site's data: every JSON file the pipeline exports, parsed against
 * schema.ts when this module is first imported - i.e. at build time, in a
 * page's frontmatter. A file that doesn't match stops the build with the
 * file and the path of each problem:
 *
 *   web/src/data/stats.json does not match the site's schema:
 *     byCompetition.E0.hitRate: Invalid input: expected number, received string
 *
 * Pages slice what they need with forLeague() and pass plain props to their
 * islands, so the full files never reach the browser.
 *
 * The files come in through the @data alias (astro.config.mjs), normally
 * web/src/data; FP_DATA_DIR points it at another folder (e.g. a broken
 * copy, to check the build fails).
 */

import type { z } from "zod";

import backtestJson from "@data/backtest.json";
import betsJson from "@data/bets.json";
import eloJson from "@data/elo.json";
import eloHistoryJson from "@data/elo_history.json";
import leaguesJson from "@data/leagues.json";
import predictionsJson from "@data/predictions.json";
import runStatusJson from "@data/run_status.json";
import statsJson from "@data/stats.json";
import tableJson from "@data/table.json";

import {
  BacktestFile,
  BetsFile,
  EloFile,
  EloHistoryFile,
  LeaguesFile,
  PredictionsFile,
  RunStatusFile,
  StatsFile,
  TableFile,
  type BacktestSection,
  type Bet,
  type Competition,
  type CompetitionRun,
  type CompetitionStats,
  type Fixture,
  type LeagueTable,
  type RatedClub,
  type RatingSeries,
} from "./schema";

/** Where the files live, for error messages. */
const SOURCE = import.meta.env.FP_DATA_DIR;

/** Thrown when an exported file doesn't match its schema. */
export class DataError extends Error {
  constructor(heading: string, problems: string[]) {
    super(`${heading}:\n  ${problems.join("\n  ")}`);
    this.name = "DataError";
  }
}

type Issue = z.core.$ZodIssue;

/**
 * One line per problem, "path: message". A union (e.g. stats with or
 * without settled bets) that matches no branch is reported through the
 * branch that came closest - fewest problems - so the message names the
 * actual field rather than just "Invalid input" on the whole object.
 */
function describe(issue: Issue, base: PropertyKey[] = []): string[] {
  const path = [...base, ...issue.path];

  if (issue.code === "invalid_union" && issue.errors.length) {
    const closest = issue.errors.reduce((best, branch) => (branch.length < best.length ? branch : best));
    return closest.flatMap((inner) => describe(inner, path));
  }

  return [`${path.map(String).join(".") || "(top level)"}: ${issue.message}`];
}

/** Parse one file's contents; throws a DataError listing every problem. */
export function parseFile<S extends z.ZodType>(file: string, schema: S, raw: unknown): z.infer<S> {
  const result = schema.safeParse(raw);

  if (!result.success) {
    throw new DataError(
      `${SOURCE}/${file} does not match the site's schema`,
      result.error.issues.flatMap((issue) => describe(issue)),
    );
  }

  return result.data;
}

// The JSON imports are typed from the files' own contents; the schemas are
// what's trusted, so each goes in as unknown.
export const leagues = parseFile("leagues.json", LeaguesFile, leaguesJson as unknown);
export const predictions = parseFile("predictions.json", PredictionsFile, predictionsJson as unknown);
export const bets = parseFile("bets.json", BetsFile, betsJson as unknown);
export const stats = parseFile("stats.json", StatsFile, statsJson as unknown);
export const elo = parseFile("elo.json", EloFile, eloJson as unknown);
export const eloHistory = parseFile("elo_history.json", EloHistoryFile, eloHistoryJson as unknown);
export const table = parseFile("table.json", TableFile, tableJson as unknown);
export const backtest = parseFile("backtest.json", BacktestFile, backtestJson as unknown);
export const runStatus = parseFile("run_status.json", RunStatusFile, runStatusJson as unknown);

// ============================================================
// CROSS-FILE CHECKS
// ============================================================

const KNOWN = new Set(leagues.competitions.map((c) => c.div));

/** Every competition code the other files use must be one leagues.json lists. */
function checkDivs(): void {
  const problems: string[] = [];

  const expect = (file: string, where: string, div: string) => {
    if (!KNOWN.has(div)) problems.push(`${file}: ${where} uses "${div}", which isn't in leagues.json`);
  };

  if (!KNOWN.has(leagues.default)) problems.push(`leagues.json: default "${leagues.default}" isn't a competition`);
  predictions.fixtures.forEach((f, i) => expect("predictions.json", `fixtures.${i}.div`, f.div));
  bets.bets.forEach((b, i) => expect("bets.json", `bets.${i}.div`, b.div));
  Object.keys(stats.byCompetition).forEach((div) => expect("stats.json", `byCompetition.${div}`, div));
  Object.keys(table.byCompetition).forEach((div) => expect("table.json", `byCompetition.${div}`, div));
  elo.teams.forEach((t, i) => {
    if (!t.div.startsWith("X:")) expect("elo.json", `teams.${i}.div`, t.div);
  });

  if (problems.length) {
    throw new DataError(`The files in ${SOURCE} don't agree with each other`, problems);
  }
}

checkDivs();

// ============================================================
// SLICES
// ============================================================

/** Everything one competition's pages need. */
export interface LeagueData {
  competition: Competition;
  /** This week's fixtures, kick-off order. */
  fixtures: Fixture[];
  /** Every bet, kick-off order. */
  bets: Bet[];
  /** Undefined until the competition has bets. */
  stats: CompetitionStats | undefined;
  /** Undefined for a competition with no table (a cup, or no matches yet). */
  table: LeagueTable | undefined;
  /** Undefined for a competition the backtest doesn't cover yet. */
  backtest: (BacktestSection & { name: string }) | undefined;
  /** Clubs rated in this league, highest league Elo first. */
  ratings: RatedClub[];
  /** The league's offset on the shared scale (0 for the anchor league). */
  offset: number | undefined;
  /** Each club's shared-scale rating history. */
  history: RatingSeries[];
  /** How the last pipeline run went for it; undefined if it wasn't in the run. */
  run: CompetitionRun | undefined;
}

const byKickoff = <T extends { kickoff: string }>(a: T, b: T) => a.kickoff.localeCompare(b.kickoff);

/** All competitions, in the order leagues.json lists them (registry order). */
export const competitions: Competition[] = leagues.competitions;

/**
 * The domestic leagues among them (kind "league"): the ones with tables and
 * league Elo, and what "N leagues" counts. Cups (the Champions League) have
 * their own sections - lib/routes.ts.
 */
export const domesticLeagues: Competition[] = competitions.filter((c) => c.kind === "league");

/** The competition with this Div ("E0") or slug ("e0"). Throws if there's none. */
export function competition(divOrSlug: string): Competition {
  const found = competitions.find((c) => c.div === divOrSlug || c.slug === divOrSlug);

  if (!found) {
    throw new Error(`No competition "${divOrSlug}" in leagues.json (have ${[...KNOWN].join(", ")})`);
  }

  return found;
}

/** One competition's slice of every file. */
export function forLeague(divOrSlug: string): LeagueData {
  const comp = competition(divOrSlug);
  const div = comp.div;

  return {
    competition: comp,
    fixtures: predictions.fixtures.filter((f) => f.div === div).sort(byKickoff),
    bets: bets.bets.filter((b) => b.div === div).sort(byKickoff),
    stats: stats.byCompetition[div],
    table: table.byCompetition[div],
    backtest: backtest.competitions[div],
    ratings: elo.teams
      .filter((t) => t.div === div)
      .sort((a, b) => (b.elo ?? b.rating) - (a.elo ?? a.rating)),
    offset: elo.offsets[div],
    history: eloHistory.series.filter((s) => s.div === div),
    run: runStatus.competitions[div],
  };
}
