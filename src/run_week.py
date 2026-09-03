"""
Run the full weekly update in one command.

    python src/run_week.py

Steps, in order:

    1. Fetch last week's results into data/raw/EPL26-27.csv
    2. Settle any pending bets in data/raw/Bets.csv
    3. Parse data/raw/Next_Matchweek.txt into Future_Fixtures.csv
    4. Rebuild data/processed/all_matches.csv (results + Understat xG)
    5. Predict the next gameweek, append the new bets (with H/D/A
       probabilities) to Bets.csv, and backfill probabilities on any
       rows still missing them

Before running, paste the upcoming fixture list into
data/raw/Next_Matchweek.txt.
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


def step(number, title):
    print()
    print("#" * 70)
    print(f"# {number}. {title}")
    print("#" * 70)


def run_week(refresh_current=True, verbose=False):

    # The result/bet scripts use paths relative to the repo root
    os.chdir(ROOT)

    step(1, "Fetch new results")
    fetch_new_results()

    step(2, "Settle pending bets")
    complete_bets()

    step(3, "Parse next matchweek")
    try:
        build_future_fixtures()
    except (FileNotFoundError, ValueError) as exc:
        print(
            f"Skipping - {exc}\n"
            f"Keeping the existing Future_Fixtures.csv."
        )

    step(4, "Rebuild match dataset")
    build_dataset(refresh_current=refresh_current, verbose=verbose)

    step(5, "Predict next gameweek")
    results = predict_next_matches()
    add_bets(
        results[
            ["Gameweek", "Date", "Time", "HomeTeam", "AwayTeam", "Prediction"]
            + list(PROB_COLUMNS.values())
        ]
    )

    # Safety net for any bet rows added by hand without probabilities
    backfill()

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
    args = parser.parse_args()

    run_week(refresh_current=not args.no_refresh, verbose=args.verbose)


if __name__ == "__main__":
    main()
