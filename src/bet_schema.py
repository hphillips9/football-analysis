"""
The Bets.csv schema, shared by everything that writes the file
(add_bets, complete_bets, backfill_bet_probs).

    Season, Div, Round, Gameweek, MatchId, Date, Time, HomeTeam, AwayTeam,
    PredictedResult, HomeProb, DrawProb, AwayProb,
    OddsH, OddsD, OddsA, OddsSource, ActualResult, Bet, Profit, Backfilled

- Round is the competition's own round label: str(Gameweek) for leagues.
- MatchId is a source match id where one is known (the CL), else empty.
- OddsH/D/A + OddsSource are the prices the bet settles at, filled at
  settlement for domestic bets ("SKB" Sky Bet, else "Avg" market average)
  or at prediction time where captured.
- Bet = 0 with an empty Profit means unpriced: no odds were available.
  It still counts for accuracy, but not for profit.
- Backfilled = 1 marks a prediction made after the match was played
  (tools/backfill_season.py), scored point-in-time on earlier matches
  only. Empty for a live bet.
"""

import pandas as pd

from features import _season_label_for
import competitions


ODDS_COLUMNS = ["OddsH", "OddsD", "OddsA"]

COLUMN_ORDER = [
    "Season", "Div", "Round", "Gameweek", "MatchId",
    "Date", "Time", "HomeTeam", "AwayTeam",
    "PredictedResult", "HomeProb", "DrawProb", "AwayProb",
    *ODDS_COLUMNS, "OddsSource",
    "ActualResult", "Bet", "Profit", "Backfilled",
]

# Dedupe key for new bets - safe for two CL legs, whose dates differ
BET_KEY = ["Div", "Date", "HomeTeam", "AwayTeam"]


def season_for(dates):
    """Season label ("26-27") for each dd/mm/yyyy date."""

    return pd.Series(
        [_season_label_for(d, competitions.CURRENT_SEASON) for d in dates],
        index=getattr(dates, "index", None),
        dtype="object",
    )


def round_for(gameweeks):
    """Round label from the gameweek: "9" for 9, empty when unknown."""

    gameweeks = pd.Series(gameweeks)
    return gameweeks.astype("Int64").astype("string").astype("object").where(
        gameweeks.notna(), pd.NA
    )


def match_id(value):
    """A MatchId as text: "6106339" whether it was read as 6106339 or 6106339.0."""

    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def clean_match_ids(ids):
    """A MatchId column as text ids, empty where there's none."""

    return pd.Series(ids).map(lambda v: match_id(v) if pd.notna(v) else pd.NA).astype(object)


def add_missing_columns(bets):
    """
    Bring a Bets.csv frame up to the current schema: add any missing
    columns, fill Season from the date and Round from the gameweek, and
    put the columns in COLUMN_ORDER (extra columns go last).
    """

    bets = bets.copy()

    if "Season" not in bets.columns:
        bets["Season"] = season_for(bets["Date"])

    if "Round" not in bets.columns:
        bets["Round"] = (
            round_for(bets["Gameweek"]) if "Gameweek" in bets.columns else pd.NA
        )

    for column in COLUMN_ORDER:
        if column not in bets.columns:
            bets[column] = pd.NA

    extra = [c for c in bets.columns if c not in COLUMN_ORDER]

    return bets[COLUMN_ORDER + extra]


def write_bets(bets, bets_path):
    """Write the whole of Bets.csv, with whole numbers kept whole ("1", not "1.0")."""

    bets = bets.copy()
    # CL bets leave Gameweek empty, which makes the column float on read
    for column in ("Gameweek", "Bet", "Backfilled"):
        bets[column] = pd.to_numeric(bets[column]).round().astype("Int64")
    bets["MatchId"] = clean_match_ids(bets["MatchId"]).to_numpy()
    bets.to_csv(bets_path, index=False)
