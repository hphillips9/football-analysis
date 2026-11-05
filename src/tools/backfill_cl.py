"""
Add a prediction to Bets.csv for every Champions League match already
played this season that has none, so the CL has a track record from the
start of the season (backfill_season.py does the same for the leagues).

    python src/tools/backfill_cl.py              # add and settle
    python src/tools/backfill_cl.py --dry-run    # print what would be added
    python src/tools/backfill_cl.py --redo       # replace earlier CL backfills

Each round (a league-phase matchday, or one leg of a knockout round) is
scored point-in-time, as the live pipeline would have: every model and
feature is built from matches played before the round's first day, with
the CL's European model (model.py) and the round's own stage, neutral
flag and clubs' leagues. Kick-off times come from FotMob's fixture list.

New rows are marked Backfilled = 1, carry Round and MatchId, and are
settled by fetch_results.complete_bets on the 90-minute result - unpriced
(Bet = 0), as no CL odds are captured yet (P6-03).
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import champions_league
import competitions
from backfill_bet_probs import BETS_PATH, MATCHES_PATH, format_bets
from european import results_for_elo
from fetch_fixtures import UK_TIMEZONE
from bet_schema import match_id
from fetch_results import complete_bets
from load_data import read_matches
from predict_next_matches import PROB_COLUMNS, build_history, predict_fixtures, train_models

DIV = "CL"
PROB_COLS = list(PROB_COLUMNS.values())


def kickoff_times(season):
    """MatchId -> (dd/mm/yyyy, HH:MM) in UK time, from FotMob's fixture list."""

    try:
        fixtures = champions_league.read_fixture_list(DIV, season)
    except FileNotFoundError:
        return {}

    kickoff = pd.to_datetime(fixtures["Kickoff"], utc=True).dt.tz_convert(UK_TIMEZONE)

    return {
        str(i): (k.strftime("%d/%m/%Y"), k.strftime("%H:%M"))
        for i, k in zip(fixtures["MatchId"], kickoff)
    }


def missing_matches(bets, history, season):
    """This season's played CL matches with no bet yet (by MatchId)."""

    played = history[(history["Div"] == DIV) & (history["Season"] == season)]
    have = {match_id(i) for i in bets.loc[bets["Div"] == DIV, "MatchId"].dropna()}

    return played[~played["MatchId"].astype(str).isin(have)]


def score_rounds(todo, history):
    """Point-in-time predictions for ``todo``, one round at a time."""

    times = kickoff_times(competitions.CURRENT_SEASON)
    scored = []

    for (stage, round_, leg), group in todo.groupby(["Stage", "Round", "Leg"], dropna=False, sort=False):

        cutoff = group["MatchDateTime"].min().normalize()
        prior = history[history["MatchDateTime"] < cutoff]
        prior, elos, team_history = build_history(
            prior, european=results_for_elo(prior, before=cutoff)
        )
        models = train_models(prior)

        fixtures = group[["Div", "HomeTeam", "AwayTeam", "Stage", "Neutral",
                          "HomeLeague", "AwayLeague", "Round", "MatchId"]].copy()
        when = [times.get(str(i)) for i in group["MatchId"]]
        fixtures["Date"] = [w[0] if w else d for w, d in zip(when, group["Date"])]
        fixtures["Time"] = [w[1] if w else "" for w in when]
        fixtures = fixtures.reset_index(drop=True)

        results = predict_fixtures(fixtures, models, elos, team_history)
        results["Round"] = fixtures["Round"].to_numpy()
        results["MatchId"] = fixtures["MatchId"].astype(str).to_numpy()
        scored.append(results)

        label = round_ if pd.isna(leg) else f"{round_} leg {int(leg)}"
        print(f"{label}: scored {len(group)} match(es) on {len(prior)} prior matches "
              f"(before {cutoff.date()}).")

    return pd.concat(scored, ignore_index=True)


def backfill_cl(redo=False, dry_run=False, bets_path=BETS_PATH, matches_path=MATCHES_PATH):

    season = competitions.CURRENT_SEASON
    bets = pd.read_csv(bets_path)

    if redo:
        drop = (bets["Div"] == DIV) & (bets["Backfilled"] == 1)
        print(f"Removing {int(drop.sum())} earlier backfilled CL prediction(s).")
        bets = bets[~drop].reset_index(drop=True)

    history = read_matches(matches_path, cups=True)
    todo = missing_matches(bets, history, season)

    if todo.empty:
        print("Every played CL match already has a prediction - nothing to do.")
        if redo and not dry_run:
            format_bets(bets).to_csv(bets_path, index=False)
        return 0

    scored = score_rounds(todo, history)

    new = pd.DataFrame({
        "Season": season,
        "Div": DIV,
        "Round": scored["Round"],
        "Gameweek": pd.NA,
        "MatchId": scored["MatchId"],
        "Date": scored["Date"],
        "Time": scored["Time"],
        "HomeTeam": scored["HomeTeam"],
        "AwayTeam": scored["AwayTeam"],
        "PredictedResult": scored["Prediction"],
        **{column: scored[column].astype(float).round(1) for column in PROB_COLS},
        "Backfilled": 1,
    })

    if dry_run:
        print(new.to_string(index=False))
        print(f"--dry-run: {len(new)} prediction(s) not written.")
        return len(new)

    bets = format_bets(pd.concat([bets, new], ignore_index=True))
    bets["Gameweek"] = bets["Gameweek"].astype("Int64")
    bets["Backfilled"] = bets["Backfilled"].astype("Int64")
    bets.to_csv(bets_path, index=False)

    print(f"Added {len(new)} backfilled CL prediction(s) to {bets_path}.")

    complete_bets(bets_path, [DIV])

    return len(new)


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redo", action="store_true", help="Replace earlier CL backfills.")
    parser.add_argument("--dry-run", action="store_true", help="Print, don't write.")
    args = parser.parse_args()

    backfill_cl(redo=args.redo, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
