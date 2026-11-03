"""
Fill in the gameweek and the model's H/D/A probabilities for every row
in Bets.csv.

New bets get both from predict_next_matches going forward; this script
backfills the rows placed before those columns existed.

Each bet is scored point-in-time: the model is retrained and the Elo /
form features are rebuilt using only matches that kicked off *before*
that betting round, so no result leaks into its own prediction. Bets are
grouped into rounds by date (a gap of more than --round-gap-days starts a
new round), matching the way a whole gameweek is predicted at once.
Rounds and gameweeks are worked out per competition (Div), because the
leagues' calendars overlap.

Every write also brings the file up to the current schema (bet_schema).

    python src/backfill_bet_probs.py            # fill missing only
    python src/backfill_bet_probs.py --force    # recompute every row
"""

import argparse
from pathlib import Path

import pandas as pd

from bet_schema import COLUMN_ORDER, add_missing_columns, round_for
from team_names import load_alias_map, normalize_team_names
from predict_next_matches import (
    build_history,
    predict_fixtures,
    train_models,
    PROB_COLUMNS,
)

ROOT = Path(__file__).resolve().parents[1]

BETS_PATH = ROOT / "data" / "raw" / "Bets.csv"
MATCHES_PATH = ROOT / "data" / "processed" / "all_matches.csv"

PROB_COLS = list(PROB_COLUMNS.values())


def load_matches(matches_path=MATCHES_PATH):

    matches = pd.read_csv(matches_path)
    matches["MatchDateTime"] = pd.to_datetime(matches["MatchDateTime"])

    return matches


def assign_rounds(kickoffs, gap_days, divs=None):
    """
    Group kickoff datetimes into rounds separated by a gap in days.
    With ``divs``, each competition is grouped on its own and the round
    ids are (Div, n) pairs.
    """

    if divs is None:
        ordered = kickoffs.sort_values()
        new_round = ordered.diff() > pd.Timedelta(days=gap_days)

        return new_round.cumsum().reindex(kickoffs.index)

    rounds = pd.Series(index=kickoffs.index, dtype="object")

    for div, index in kickoffs.groupby(divs).groups.items():
        numbers = assign_rounds(kickoffs.loc[index], gap_days)
        rounds.loc[index] = [(div, n) for n in numbers]

    return rounds


def attach_gameweeks(bets, matches, alias_map, gap_days):
    """
    Gameweek for every bet: taken straight from all_matches where the game
    has been played, and for fixtures not yet in the results, numbered as
    rounds following the last played gameweek.
    """

    key = ["Div", "Date", "HomeTeam", "AwayTeam"]

    keyed = bets[key].copy()
    keyed["HomeTeam"] = keyed["HomeTeam"].replace(alias_map)
    keyed["AwayTeam"] = keyed["AwayTeam"].replace(alias_map)

    played = matches[key + ["Gameweek"]].drop_duplicates(subset=key)

    gameweek = keyed.merge(played, on=key, how="left")["Gameweek"]
    gameweek.index = bets.index

    for div in bets.loc[gameweek.isna(), "Div"].unique():

        in_div = bets["Div"] == div
        missing = bets.index[in_div & gameweek.isna()]

        known = gameweek[in_div].dropna()
        base = int(known.max()) if len(known) else 0
        rounds = assign_rounds(bets.loc[missing, "_kickoff"], gap_days)
        rank = {r: i for i, r in enumerate(sorted(rounds.dropna().unique()))}
        gameweek.loc[missing] = rounds.map(rank) + base + 1

    return gameweek.round().astype("Int64")


def backfill(
    bets_path=BETS_PATH,
    matches_path=MATCHES_PATH,
    gap_days=3,
    force=False,
):

    bets = pd.read_csv(bets_path)

    for column in ["Gameweek", *PROB_COLS]:
        if column not in bets.columns:
            bets[column] = pd.NA

    bets["_kickoff"] = pd.to_datetime(
        bets["Date"] + " " + bets["Time"], dayfirst=True
    )

    if force:
        prob_todo = bets.index
        gw_todo = bets.index
    else:
        prob_todo = bets.index[bets[PROB_COLS].isna().any(axis=1)]
        gw_todo = bets.index[bets["Gameweek"].isna()]

    if len(prob_todo) == 0 and len(gw_todo) == 0:
        print("Every bet already has a gameweek and probabilities - nothing to do.")
        return _write(bets, bets_path)

    matches = load_matches(matches_path)
    alias_map = load_alias_map()

    if len(gw_todo):
        bets["Gameweek"] = attach_gameweeks(bets, matches, alias_map, gap_days)
        if "Round" in bets.columns:
            bets["Round"] = bets["Round"].where(
                bets["Round"].notna(), round_for(bets["Gameweek"])
            )
        print(f"Filled gameweek on {len(gw_todo)} bet(s).")

    if len(prob_todo) == 0:
        return _write(bets, bets_path)

    bets["_round"] = assign_rounds(bets["_kickoff"], gap_days, bets["Div"])
    todo = prob_todo

    filled = 0

    for round_id, group in bets.loc[todo].groupby("_round"):

        cutoff = group["_kickoff"].min()
        history = matches[matches["MatchDateTime"] < cutoff]

        if history.empty:
            print(f"Round starting {cutoff.date()}: no prior matches, skipped.")
            continue

        history, elos, team_history = build_history(history)
        models = train_models(history)

        fixtures = group[["Div", "Date", "Time", "HomeTeam", "AwayTeam"]].copy()
        fixtures["HomeTeam"] = normalize_team_names(
            fixtures["HomeTeam"], alias_map, source_name="Bets.csv"
        )
        fixtures["AwayTeam"] = normalize_team_names(
            fixtures["AwayTeam"], alias_map, source_name="Bets.csv"
        )

        scored = predict_fixtures(fixtures, models, elos, team_history)

        for column in PROB_COLS:
            bets.loc[group.index, column] = scored[column].to_numpy()

        filled += len(group)
        print(
            f"Round starting {cutoff.date()}: scored {len(group)} bet(s) "
            f"on {len(history)} prior matches."
        )

    bets[PROB_COLS] = bets[PROB_COLS].astype(float).round(1)

    print(f"Backfilled {filled} bet(s).")

    return _write(bets, bets_path)


def format_bets(bets):
    """Bets in the current schema and column order, ready to write."""

    bets = add_missing_columns(bets)[COLUMN_ORDER]
    # Whole units, written as complete_bets writes them ("1", not "1.0")
    bets["Bet"] = bets["Bet"].astype("Int64")

    return bets


def _write(bets, bets_path):

    bets = format_bets(bets)
    bets.to_csv(bets_path, index=False)

    print(f"Wrote {bets_path}")

    return bets


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute probabilities for every bet, not just the missing ones.",
    )
    parser.add_argument(
        "--round-gap-days",
        type=int,
        default=3,
        help="A date gap larger than this starts a new betting round (default 3).",
    )
    args = parser.parse_args()

    backfill(gap_days=args.round_gap_days, force=args.force)


if __name__ == "__main__":
    main()
