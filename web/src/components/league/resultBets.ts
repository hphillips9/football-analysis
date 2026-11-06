/**
 * Bets cut down to what the Results / Record islands use, so each page's
 * island props (serialised into the HTML) carry no unused fields.
 */

import type { Bet } from "../../lib/schema";
import type { ResultBet } from "./GameweekResults";

export function toResultBets(bets: readonly Bet[]): ResultBet[] {
  return bets.map((b) => ({
    gameweek: b.gameweek,
    kickoff: b.kickoff,
    home: b.home,
    away: b.away,
    prediction: b.prediction,
    homeProb: b.homeProb,
    drawProb: b.drawProb,
    awayProb: b.awayProb,
    result: b.result,
    profit: b.profit,
    won: b.won,
    settled: b.settled,
    backfilled: b.backfilled,
  }));
}
