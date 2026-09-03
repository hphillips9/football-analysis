"""
Run the weekly update in one command.

    python src/run_week.py                 # results + predictions
    python src/run_week.py --no-predict    # results only

Always:

    1. Fetch last week's results into data/raw/EPL26-27.csv
    2. Settle any pending bets in data/raw/Bets.csv
    3. Rebuild data/processed/all_matches.csv (results + Understat xG)
    4. Backfill gameweek / probabilities on any Bets.csv rows missing them
    5. Predict the next gameweek from Next_Matchweek.txt and append the
       new bets to Bets.csv (skipped by --no-predict)
    6. Export web/src/data/*.json for the website

Paste the upcoming fixture list into data/raw/Next_Matchweek.txt before
a prediction run. Scheduled automation runs --no-predict so it never
re-predicts a stale fixture list.
"""

import os
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from fetch_results import fetch_new_results, complete_bets
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
    fetch_new_results()

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
        build_future_fixtures()
    except (FileNotFoundError, ValueError) as exc:
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
