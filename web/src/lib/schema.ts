/**
 * Schemas for the JSON the pipeline writes into web/src/data
 * (src/export_web.py and src/backtest.py). They're the contract between
 * the Python export and this site: data.ts parses every file against them
 * at build time, so a shape change in the pipeline fails the build (and
 * CI) instead of rendering a broken page.
 *
 * Objects are strict: an unknown key fails too, so a renamed field shows
 * up as both "missing" and "unrecognised" rather than silently vanishing.
 * When the export gains a field, add it here.
 *
 * Nullable fields follow the export's empty cases, not just today's data:
 * e.g. a competition with no settled bets yet has a reduced stats object
 * (StatsEmpty), and a backtest with no test seasons has overall: null.
 */

import { z } from "zod";

// ============================================================
// SHARED
// ============================================================

/** Export time, with its UTC offset: "2026-11-05T11:47:35+00:00". */
const Generated = z.iso.datetime({ offset: true });

/** A kick-off in UK wall-clock time, no offset: "2026-11-06T20:00:00". */
const Kickoff = z.iso.datetime({ local: true });

/** A match date as football-data.co.uk writes it: "06/11/2026". */
const DayMonthYear = z.string().regex(/^\d{2}\/\d{2}\/\d{4}$/, "expected dd/mm/yyyy");

/** An ISO date: "2026-11-02". */
const IsoDate = z.iso.date();

/** A season label: "26-27". */
const Season = z.string().regex(/^\d{2}-\d{2}$/, "expected a season like 26-27");

/** backtest.json's display label for a season: "2022/23". */
const SeasonName = z.string().regex(/^\d{4}\/\d{2}$/, "expected a season like 2022/23");

/** A 90-minute result or pick. */
export const Outcome = z.enum(["H", "D", "A"]);

/** A competition code from the registry: "E0", "SP1", "CL"... */
const Div = z.string().min(1);

/** Percentages as the export rounds them (0-100). */
const Percent = z.number().min(0).max(100);

const Count = z.number().int().nonnegative();

// ============================================================
// leagues.json
// ============================================================

export const Competition = z.strictObject({
  div: Div,
  slug: z.string().regex(/^[a-z0-9]+$/),
  name: z.string(),
  country: z.string().nullable(),
  kind: z.enum(["league", "cup"]),
  promotedElo: z.number().nullable(),
});

export const LeaguesFile = z.strictObject({
  generated: Generated,
  default: Div,
  competitions: z.array(Competition).min(1),
});

// ============================================================
// predictions.json
// ============================================================

const Probabilities = {
  homeProb: Percent,
  drawProb: Percent,
  awayProb: Percent,
};

export const Fixture = z.strictObject({
  div: Div,
  gameweek: Count,
  date: DayMonthYear,
  time: z.string(),
  kickoff: Kickoff,
  home: z.string(),
  away: z.string(),
  prediction: Outcome,
  ...Probabilities,
  homeElo: z.number(),
  awayElo: z.number(),
  eloGap: z.number(),
  result: Outcome.nullable(),
  settled: z.boolean(),
});

export const PredictionsFile = z.strictObject({
  generated: Generated,
  fixtures: z.array(Fixture),
});

// ============================================================
// bets.json
// ============================================================

export const Bet = z.strictObject({
  div: Div,
  gameweek: Count,
  date: DayMonthYear,
  time: z.string(),
  kickoff: Kickoff,
  home: z.string(),
  away: z.string(),
  prediction: Outcome,
  ...Probabilities,
  result: Outcome.nullable(),
  /** Stake-1 profit; null until settled, or when unpriced. */
  profit: z.number().nullable(),
  won: z.boolean().nullable(),
  settled: z.boolean(),
  /** Predicted after the match was played (scored point-in-time). */
  backfilled: z.boolean(),
});

export const BetsFile = z.strictObject({
  generated: Generated,
  bets: z.array(Bet),
});

// ============================================================
// stats.json
// ============================================================

export const CalibrationBin = z.strictObject({
  label: z.string(),
  bets: Count,
  avgProb: Percent,
  hitRate: Percent,
});

export const PickSummary = z.strictObject({
  pick: Outcome,
  label: z.string(),
  bets: Count,
  hits: Count,
  hitRate: Percent.nullable(),
  profit: z.number(),
});

export const BankrollPoint = z.strictObject({
  div: Div,
  kickoff: Kickoff,
  gameweek: Count,
  match: z.string(),
  profit: z.number(),
  cumulative: z.number(),
});

export const NotableBet = z.strictObject({
  div: Div,
  gameweek: Count,
  date: DayMonthYear,
  match: z.string(),
  pick: Outcome,
  result: Outcome,
  pickProb: Percent,
  /** Null for an unpriced bet (no odds, e.g. the Champions League before P6-03): misses still count. */
  profit: z.number().nullable(),
});

export const GameweekSummary = z.strictObject({
  gameweek: Count,
  bets: Count,
  settled: Count,
  hits: Count,
  hitRate: Percent.nullable(),
  profit: z.number().nullable(),
  cumulativeProfit: z.number().nullable(),
  status: z.enum(["pending", "partial", "complete"]),
});

/** Fields every stats object has, settled bets or not. */
const statsBase = {
  totalBets: Count,
  backfilledBets: Count,
  settledBets: Count,
  pendingBets: Count,
  calibration: z.array(CalibrationBin),
  byPick: z.array(PickSummary),
  bankroll: z.array(BankrollPoint),
  bestBets: z.array(NotableBet),
  worstBets: z.array(NotableBet),
};

/** The headline numbers, present once any bet has settled. */
const statsResults = {
  asOf: IsoDate,
  backfilledGameweeks: z.array(Count).nullable(),
  wins: Count,
  losses: Count,
  hitRate: Percent,
  baselineHitRate: Percent,
  edge: z.number(),
  /** Mean negative log of the probability given to the actual result (lower is better). */
  logLoss: z.number().nonnegative(),
  /** Settled bets with odds: profit, staked and ROI count only these (0 for an unpriced cup). */
  pricedBets: Count,
  profit: z.number(),
  staked: z.number(),
  roi: z.number(),
};

/** No settled bets yet: no headline numbers. */
const statsEmpty = {
  asOf: z.null(),
  backfilledGameweeks: z.null(),
  settledBets: z.literal(0),
};

// overall drops byGameweek (gameweek numbers differ by league)
export const OverallStats = z.union([
  z.strictObject({ ...statsBase, ...statsResults }),
  z.strictObject({ ...statsBase, ...statsEmpty }),
]);

const competitionExtra = { name: z.string(), byGameweek: z.array(GameweekSummary) };

export const CompetitionStats = z.union([
  z.strictObject({ ...statsBase, ...statsResults, ...competitionExtra }),
  z.strictObject({ ...statsBase, ...statsEmpty, ...competitionExtra }),
]);

export const StatsFile = z.strictObject({
  generated: Generated,
  overall: OverallStats,
  byCompetition: z.record(Div, CompetitionStats),
});

// ============================================================
// elo.json / elo_history.json
// ============================================================

export const RatedClub = z.strictObject({
  /** Its league's Div, or "X:<country>" for a club outside the modelled leagues. */
  div: Div,
  team: z.string(),
  /** Rating within its own league (what predictions use); null outside the modelled leagues. */
  elo: z.number().nullable(),
  /** Rating on the shared scale across leagues. */
  rating: z.number(),
  country: z.string(),
  modelled: z.boolean(),
});

export const EloFile = z.strictObject({
  generated: Generated,
  teams: z.array(RatedClub),
  /** Each league's latest offset on the shared scale (E0 = 0). */
  offsets: z.record(Div, z.number()),
});

export const RatingSeries = z.strictObject({
  team: z.string(),
  div: Div,
  /** [date, rating] after each match day. */
  points: z.array(z.tuple([IsoDate, z.number()])),
});

export const OffsetPoint = z.strictObject({
  date: IsoDate,
  season: Season,
  div: Div,
  offset: z.number(),
});

export const EloHistoryFile = z.strictObject({
  generated: Generated,
  from: IsoDate,
  series: z.array(RatingSeries),
  offsets: z.array(OffsetPoint),
});

// ============================================================
// table.json
// ============================================================

const standingBase = {
  team: z.string(),
  played: Count,
  won: Count,
  drawn: Count,
  lost: Count,
  points: Count,
  position: z.number().int().positive(),
};

export const Standing = z.strictObject({
  ...standingBase,
  gf: Count,
  ga: Count,
  gd: z.number().int(),
});

/** If every prediction comes true: points only. */
export const PredictedStanding = z.strictObject({
  ...standingBase,
  currentPosition: z.number().int().positive(),
  movement: z.number().int(),
});

/** Expected points / goals, rounded for display (gf/ga/gd to 0.1). */
export const ProjectedStanding = z.strictObject({
  ...standingBase,
  gf: z.number(),
  ga: z.number(),
  gd: z.number(),
  currentPosition: z.number().int().positive(),
  movement: z.number().int(),
});

export const LeagueTable = z.strictObject({
  name: z.string(),
  season: Season,
  playedFixtures: Count,
  remainingFixtures: Count,
  current: z.array(Standing),
  predicted: z.array(PredictedStanding),
  projected: z.array(ProjectedStanding),
});

export const TableFile = z.strictObject({
  generated: Generated,
  byCompetition: z.record(Div, LeagueTable),
});

// ============================================================
// cups.json
// ============================================================

/** A club's league that season: a Div, or "X:<country>" outside the modelled leagues; null if unknown. */
const ClubLeague = z.string().nullable();

export const CupStanding = z.strictObject({
  ...standingBase,
  gf: Count,
  ga: Count,
  gd: z.number().int(),
  league: ClubLeague,
});

/** Expected points for the remaining matchdays added on (no goal model). */
export const CupProjectedStanding = z.strictObject({
  ...standingBase,
  league: ClubLeague,
  currentPosition: z.number().int().positive(),
  movement: z.number().int(),
});

export const LeaguePhase = z.strictObject({
  season: Season,
  matchdays: Count,
  playedFixtures: Count,
  remainingFixtures: Count,
  /** Last place that goes straight to the round of 16 (8), and the last into the play-off (24). */
  zones: z.strictObject({ direct: Count, playoff: Count }),
  current: z.array(CupStanding),
  projected: z.array(CupProjectedStanding),
});

const Score = z.tuple([Count, Count]);

export const KnockoutStage = z.enum(["KO_PLAYOFF", "R16", "QF", "SF", "FINAL"]);

export const TieLeg = z.strictObject({
  /** 1 or 2; null for the one-off final. */
  leg: z.number().int().min(1).max(2).nullable(),
  date: IsoDate,
  home: z.string(),
  away: z.string(),
  /** The 90-minute score; null until played. */
  score: Score.nullable(),
  /** The score after extra time, when there was some. */
  extraTime: Score.nullable(),
  penaltyWinner: z.string().nullable(),
  /** The model's call, when it made one for this leg. */
  prediction: z
    .strictObject({ pick: Outcome, homeProb: Percent, drawProb: Percent, awayProb: Percent })
    .nullable(),
});

const Probability = z.number().min(0).max(1);

export const Tie = z.strictObject({
  /** First-leg home side first. */
  teams: z.tuple([z.string(), z.string()]),
  /**
   * P(teams[0] goes through), display only, never a bet (P6-02). `before`: before the first leg (out of
   * sample once it's played); `afterFirstLeg`: given its score (two-legged ties). Null when it can't be worked out.
   */
  progression: z.strictObject({ before: Probability, afterFirstLeg: Probability.nullable() }).nullable(),
  legs: z.array(TieLeg).min(1),
  /** Goals over the legs played, extra time included, in `teams` order. */
  aggregate: Score.nullable(),
  winner: z.string().nullable(),
  decidedBy: z.enum(["aggregate", "90 minutes", "extra time", "penalties"]).nullable(),
});

export const Knockouts = z.strictObject({
  season: Season,
  /** False when this season's draw isn't made yet and these are last season's ties. */
  current: z.boolean(),
  /** Brier score of `progression.before` over completed ties, walk-forward (coin flip = 0.25). */
  progressionScore: z
    .strictObject({
      ties: Count,
      from: Season,
      to: Season,
      brier: z.number().min(0).max(1),
      brierCi: z.tuple([z.number(), z.number()]),
      tiesAfterFirstLeg: Count,
      brierAfterFirstLeg: z.number().min(0).max(1).nullable(),
    })
    .nullable(),
  /** In bracket order: tie i of a round is fed by ties 2i and 2i+1 of the one before. */
  rounds: z.array(z.strictObject({ stage: KnockoutStage, ties: z.array(Tie) })),
});

export const CupData = z.strictObject({
  name: z.string(),
  season: Season,
  leaguePhase: LeaguePhase.nullable(),
  knockouts: Knockouts.nullable(),
});

export const CupsFile = z.strictObject({
  generated: Generated,
  byCompetition: z.record(Div, CupData),
});

// ============================================================
// backtest.json
// ============================================================

export const BacktestGameweek = z.strictObject({
  gameweek: Count,
  bets: Count,
  hits: Count,
  profit: z.number(),
  cumulativeProfit: z.number(),
});

const backtestNumbers = {
  matches: Count,
  accuracy: Percent,
  logLoss: z.number().positive(),
  baselineAccuracy: Percent,
  edge: z.number(),
  profit: z.number(),
  roi: z.number(),
};

export const BacktestSeason = z.strictObject({
  season: SeasonName,
  ...backtestNumbers,
  /** "2021/22" or "2021/22-2024/25". */
  trainedOn: z.string(),
  trainSeasons: Count,
  byGameweek: z.array(BacktestGameweek),
});

export const BacktestSection = z.strictObject({
  seasons: z.array(BacktestSeason),
  overall: z.strictObject(backtestNumbers).nullable(),
});

export const BacktestFile = z.strictObject({
  generated: Generated,
  model: z.strictObject({
    features: z.array(z.string()),
    leagueIndicators: z.array(z.string()),
    ownModel: z.array(Div),
    trainFrom: Season,
  }),
  pooled: BacktestSection,
  competitions: z.record(Div, BacktestSection.extend({ name: z.string() })),
});

// ============================================================
// run_status.json
// ============================================================

/**
 * How each competition fared in the last pipeline run (src/run_status.py).
 * Outcome values are open strings ("ok", "stale", "failed", "partial"...)
 * so a new one in the pipeline doesn't stop the build; isStale() decides
 * what counts. Keys may include codes the site has no pages for (EL, ECL).
 */
export const CompetitionRun = z.strictObject({
  results: z.string().nullable(),
  xg: z.string().nullable(),
  predicted: Count,
  error: z.string().nullable(),
});

export const RunStatusFile = z.strictObject({
  generated: Generated,
  competitions: z.record(Div, CompetitionRun),
});

// ============================================================
// TYPES (inferred - never written by hand)
// ============================================================

export type Outcome = z.infer<typeof Outcome>;
export type Competition = z.infer<typeof Competition>;
export type Leagues = z.infer<typeof LeaguesFile>;
export type Fixture = z.infer<typeof Fixture>;
export type Predictions = z.infer<typeof PredictionsFile>;
export type Bet = z.infer<typeof Bet>;
export type Bets = z.infer<typeof BetsFile>;
export type OverallStats = z.infer<typeof OverallStats>;
export type CompetitionStats = z.infer<typeof CompetitionStats>;
export type Stats = z.infer<typeof StatsFile>;
export type GameweekSummary = z.infer<typeof GameweekSummary>;
export type BankrollPoint = z.infer<typeof BankrollPoint>;
export type CalibrationBin = z.infer<typeof CalibrationBin>;
export type PickSummary = z.infer<typeof PickSummary>;
export type RatedClub = z.infer<typeof RatedClub>;
export type Elo = z.infer<typeof EloFile>;
export type RatingSeries = z.infer<typeof RatingSeries>;
export type OffsetPoint = z.infer<typeof OffsetPoint>;
export type EloHistory = z.infer<typeof EloHistoryFile>;
export type LeagueTable = z.infer<typeof LeagueTable>;
export type Table = z.infer<typeof TableFile>;
export type BacktestSection = z.infer<typeof BacktestSection>;
export type BacktestSeason = z.infer<typeof BacktestSeason>;
export type Backtest = z.infer<typeof BacktestFile>;
export type CompetitionRun = z.infer<typeof CompetitionRun>;
export type RunStatus = z.infer<typeof RunStatusFile>;
export type LeaguePhase = z.infer<typeof LeaguePhase>;
export type CupStanding = z.infer<typeof CupStanding>;
export type CupProjectedStanding = z.infer<typeof CupProjectedStanding>;
export type KnockoutStage = z.infer<typeof KnockoutStage>;
export type Tie = z.infer<typeof Tie>;
export type TieLeg = z.infer<typeof TieLeg>;
export type Knockouts = z.infer<typeof Knockouts>;
export type CupData = z.infer<typeof CupData>;

/**
 * True when the last run couldn't bring a competition up to date: its
 * results weren't fetched (the ones on file were used) or a step failed.
 * Partial xG alone isn't stale - every match still has a result.
 */
export function isStale(run: CompetitionRun | undefined): boolean {
  if (!run) return false;
  return run.results === "stale" || run.results === "failed" || run.error !== null;
}

/** Stats with headline numbers (at least one settled bet). */
export type StatsWithResults<S extends OverallStats | CompetitionStats> = Extract<S, { asOf: string }>;

/** True once a stats object has settled bets, and so wins, hitRate, roi... */
export function hasResults<S extends OverallStats | CompetitionStats>(stats: S): stats is StatsWithResults<S> {
  return stats.asOf !== null;
}
