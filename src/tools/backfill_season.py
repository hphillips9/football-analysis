"""
Add a prediction to Bets.csv for every match already played this season
that has none, so a competition switched on mid-season gets a track
record from gameweek 1.

    python src/tools/backfill_season.py               # every enabled competition
    python src/tools/backfill_season.py --div SP1 D1
    python src/tools/backfill_season.py --redo        # replace earlier backfills

Gameweeks are the official matchdays from football-data.org (one API
request per competition, so FOOTBALL_DATA_API_KEY must be set), the same
numbers live bets carry. Only matchdays before a competition's first
live bet are filled.

Each match is scored point-in-time, as the live pipeline would have
scored it: on matches that kicked off before the start of the round it
falls in. That's its own matchday's round, or for a rearranged game
played away from the rest of its matchday, the round being played around
its new date (fetch_fixtures predicts such stragglers with that round).
New rows are marked Backfilled = 1 and then settled by
fetch_results.complete_bets, at the same odds a live bet would settle at.
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import competitions
from backfill_bet_probs import BETS_PATH, MATCHES_PATH, format_bets, load_matches
from bet_schema import BET_KEY, round_for
from fetch_fixtures import REQUEST_GAP, _get_matches, _to_frame, api_key
from fetch_results import complete_bets
from predict_next_matches import (
    build_history,
    predict_fixtures,
    train_models,
    PROB_COLUMNS,
)
from team_names import load_alias_map, normalize_team_names

PROB_COLS = list(PROB_COLUMNS.values())

# A game more than this far from its matchday's median kickoff was
# rearranged, and is scored with the round being played at the time
REARRANGED_DAYS = 4


def official_matchdays(div, key, alias_map):
    """(HomeTeam, AwayTeam) -> football-data.org matchday, this season.
    Each pairing meets once a season at home, so the teams are the key."""

    fixtures = _to_frame(_get_matches(key, div), div)
    for side in ["HomeTeam", "AwayTeam"]:
        fixtures[side] = normalize_team_names(
            fixtures[side], alias_map, source_name="football-data.org"
        )

    return {
        (home, away): int(gameweek)
        for home, away, gameweek in fixtures[["HomeTeam", "AwayTeam", "Gameweek"]].to_numpy()
    }


def missing_matches(bets, matches, div, matchdays, alias_map):
    """This season's played matches in ``div`` that have no bet yet and
    whose official matchday is before its first live bet's, with
    Gameweek set to that matchday."""

    season = matches[
        (matches["Div"] == div)
        & (matches["Season"] == competitions.CURRENT_SEASON)
    ].copy()

    official = [matchdays.get(pair) for pair in zip(season["HomeTeam"], season["AwayTeam"])]
    unknown = season[[gw is None for gw in official]]
    if len(unknown):
        raise ValueError(
            f"{div}: no football-data.org matchday for "
            + ", ".join(f"{h} v {a}" for h, a in zip(unknown["HomeTeam"], unknown["AwayTeam"]))
            + " - add the names to data/reference/team_names.csv"
        )
    season["Gameweek"] = official

    live = bets[(bets["Div"] == div) & (bets["Backfilled"] != 1)]
    if len(live):
        season = season[season["Gameweek"] < live["Gameweek"].min()]

    keyed = bets.loc[bets["Div"] == div, BET_KEY].copy()
    keyed["HomeTeam"] = keyed["HomeTeam"].replace(alias_map)
    keyed["AwayTeam"] = keyed["AwayTeam"].replace(alias_map)
    existing = set(map(tuple, keyed.to_numpy()))

    is_new = [tuple(row) not in existing for row in season[BET_KEY].to_numpy()]

    return season[is_new]


def scoring_cutoffs(season):
    """
    When each match would have been predicted: the start of its round.
    A round's start is the first kickoff of its matchday's games played
    together (within REARRANGED_DAYS of the matchday's median kickoff).
    A rearranged game takes the latest round start on or before it.
    """

    median = season.groupby("Gameweek")["MatchDateTime"].transform("median")
    together = (season["MatchDateTime"] - median).abs() <= pd.Timedelta(days=REARRANGED_DAYS)

    starts = season[together].groupby("Gameweek")["MatchDateTime"].min()
    start_times = starts.sort_values()

    def cutoff(row, is_together):
        if is_together:
            return starts[row["Gameweek"]]
        earlier = start_times[start_times <= row["MatchDateTime"]]
        return earlier.iloc[-1] if len(earlier) else row["MatchDateTime"]

    return pd.Series(
        [cutoff(row, t) for (_, row), t in zip(season.iterrows(), together)],
        index=season.index,
    )


def score(todo, matches):
    """Point-in-time predictions for ``todo``, one model per cutoff."""

    scored = []

    for (div, cutoff), group in todo.groupby(["Div", "_cutoff"]):

        history, elos, team_history = build_history(
            matches[matches["MatchDateTime"] < cutoff]
        )
        models = train_models(history)

        fixtures = group[["Div", "Date", "Time", "HomeTeam", "AwayTeam"]].copy()
        predicted = predict_fixtures(fixtures, models, elos, team_history)
        predicted["Div"] = div
        predicted["Gameweek"] = group["Gameweek"].to_numpy()
        scored.append(predicted)

        rounds = ", ".join(f"GW{gw}" for gw in sorted(group["Gameweek"].unique()))
        print(
            f"{div} {rounds} (from {cutoff:%d %b %H:%M}): scored {len(group)} "
            f"match(es) on {len(history)} prior matches."
        )

    return pd.concat(scored, ignore_index=True)


def backfill_season(divs=None, redo=False, bets_path=BETS_PATH, matches_path=MATCHES_PATH):

    # Leagues only: the CL has src/tools/backfill_cl.py
    divs = competitions.leagues(divs)

    key = api_key()
    if not key:
        raise SystemExit("FOOTBALL_DATA_API_KEY is not set (env or .env).")

    bets = pd.read_csv(bets_path)
    if "Backfilled" not in bets.columns:
        bets["Backfilled"] = pd.NA

    if redo:
        drop = bets["Div"].isin(divs) & (bets["Backfilled"] == 1)
        print(f"Removing {int(drop.sum())} earlier backfilled prediction(s).")
        bets = bets[~drop].reset_index(drop=True)

    matches = load_matches(matches_path)
    alias_map = load_alias_map()

    todo = []
    for i, div in enumerate(divs):
        if i:
            time.sleep(REQUEST_GAP)  # football-data.org: 10 requests a minute
        matchdays = official_matchdays(div, key, alias_map)
        missing = missing_matches(bets, matches, div, matchdays, alias_map)
        if len(missing):
            season = matches[
                (matches["Div"] == div) & (matches["Season"] == competitions.CURRENT_SEASON)
            ].copy()
            season["Gameweek"] = [matchdays[p] for p in zip(season["HomeTeam"], season["AwayTeam"])]
            missing["_cutoff"] = scoring_cutoffs(season).loc[missing.index]
            todo.append(missing)

    if not todo:
        print("Every played gameweek already has predictions - nothing to do.")
        if redo:
            format_bets(bets).to_csv(bets_path, index=False)
        return 0

    scored = score(pd.concat(todo), matches)

    new = pd.DataFrame({
        "Season": competitions.CURRENT_SEASON,
        "Div": scored["Div"],
        "Round": round_for(scored["Gameweek"]),
        "Gameweek": scored["Gameweek"],
        "Date": scored["Date"],
        "Time": scored["Time"],
        "HomeTeam": scored["HomeTeam"],
        "AwayTeam": scored["AwayTeam"],
        "PredictedResult": scored["Prediction"],
        **{column: scored[column].astype(float).round(1) for column in PROB_COLS},
        "Backfilled": 1,
    })

    bets = format_bets(pd.concat([bets, new], ignore_index=True))
    bets["Gameweek"] = bets["Gameweek"].astype("Int64")
    bets["Backfilled"] = bets["Backfilled"].astype("Int64")
    bets.to_csv(bets_path, index=False)

    print(f"Added {len(new)} backfilled prediction(s) to {bets_path}.")

    complete_bets(bets_path, divs)

    return len(new)


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--div",
        nargs="+",
        help="Competitions to backfill (default: every enabled one).",
    )
    parser.add_argument(
        "--redo",
        action="store_true",
        help="Remove earlier backfilled predictions first and redo them.",
    )
    args = parser.parse_args()

    backfill_season(args.div, redo=args.redo)


if __name__ == "__main__":
    main()
