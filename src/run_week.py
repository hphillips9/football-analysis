"""
Run the weekly update in one command.

    python src/run_week.py                 # results + predictions
    python src/run_week.py --no-predict    # results only

Always:

    1. Fetch last week's results into data/raw/EPL26-27.csv
    2. Settle any pending bets in data/raw/Bets.csv
    3. Rebuild data/processed/all_matches.csv (results + Understat xG)
    4. Backfill gameweek / probabilities on any Bets.csv rows missing them
    5. Pull the next round's fixtures from football-data.org, predict
       them and append the new bets to Bets.csv (skipped by --no-predict)
    6. Export web/src/data/*.json for the website

Step 5 only predicts fixtures that aren't already in Bets.csv, and waits
until the previous round's results are all on file, so it is safe to
run as often as you like.

Without a FOOTBALL_DATA_API_KEY (environment or .env) it falls back to
the fixture list pasted into data/raw/Next_Matchweek.txt.
"""

import os
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from fetch_results import fetch_new_results, complete_bets
from fetch_fixtures import api_key, fetch_next_fixtures
from future_games_parser import build_future_fixtures
from load_data import build_dataset
from predict_next_matches import (
    predict_next_matches,
    add_bets,
    print_predictions,
    PROB_COLUMNS,
)
from backfill_bet_probs import backfill
from export_web import export_web


def step(number, title):
    print()
    print("#" * 70)
    print(f"# {number}. {title}")
    print("#" * 70)


def run_week(refresh_current=True, verbose=False, predict=True):

    # The result/bet scripts use paths relative to the repo root
    os.chdir(ROOT)

    step(1, "Fetch new results")
    try:
        fetch_new_results()
    except ConnectionError as exc:
        print(f"Skipping - {exc}\nCarrying on with the results already on file.")

    step(2, "Settle pending bets")
    complete_bets()

    step(3, "Rebuild match dataset")
    build_dataset(refresh_current=refresh_current, verbose=verbose)

    step(4, "Backfill gameweek / probabilities")
    backfill()

    if predict:
        _predict_next_gameweek()
    else:
        print("\n--no-predict: skipping the next-gameweek prediction.")

    step(6, "Export website data")
    export_web()


def _predict_next_gameweek():

    step(5, "Predict next gameweek")

    try:
        if api_key():
            if fetch_next_fixtures() is None:
                return
        else:
            print("No football-data.org API key - using Next_Matchweek.txt.")
            build_future_fixtures()
    except (ConnectionError, FileNotFoundError, ValueError) as exc:
        print(f"Skipping predictions - {exc}")
        return

    results = predict_next_matches()
    add_bets(
        results[
            ["Gameweek", "Date", "Time", "HomeTeam", "AwayTeam", "Prediction"]
            + list(PROB_COLUMNS.values())
        ]
    )
    print_predictions(results)


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full xG coverage report during the rebuild."
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Use cached Understat data instead of re-scraping the current season."
    )
    parser.add_argument(
        "--no-predict",
        action="store_true",
        help="Only fetch results and settle bets - do not predict the next gameweek."
    )
    args = parser.parse_args()

    run_week(
        refresh_current=not args.no_refresh,
        verbose=args.verbose,
        predict=not args.no_predict,
    )


if __name__ == "__main__":
    main()
