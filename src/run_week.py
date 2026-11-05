"""
Run the weekly update in one command.

    python src/run_week.py                 # results + predictions
    python src/run_week.py --no-predict    # results only

Always:

    1. Fetch last week's results into data/raw/<Div>/results_<season>.csv
       for each enabled competition, and this season's Champions League,
       Europa League and Conference League results from FotMob (they
       move the Elo ratings - see elo.py's shared scale)
    2. Settle any pending bets in data/raw/Bets.csv
    3. Rebuild data/processed/all_matches.csv (results + FotMob xG, Understat backup),
       plus the Champions League rows (Div "CL", 90-minute results) from
       the FotMob caches
    4. Backfill gameweek / probabilities on any Bets.csv rows missing them
    5. Pull each competition's next round from football-data.org, predict
       them and append the new bets to Bets.csv (skipped by --no-predict).
       The Champions League is predicted by its own European model and its
       bets carry Round + MatchId; they settle on the 90-minute result from
       the FotMob cache, unpriced (Bet = 0) until CL odds are captured
    6. Export web/src/data/*.json for the website

Step 5 only predicts fixtures that aren't already in Bets.csv, and waits
until the previous round's results are all on file, so it is safe to
run as often as you like. Each competition waits on its own rounds only.

Steps 1, 3 and 5 run competition by competition: one that fails (an
outage, an unknown team name) is skipped and the rest carry on. How each
one fared is written to data/processed/run_status.json on every run.

Without a FOOTBALL_DATA_API_KEY (environment or .env) it falls back to
the fixture list pasted into data/raw/Next_Matchweek.txt (Premier
League only).
"""

import os
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import competitions
import european
from fetch_results import fetch_all_new_results, complete_bets
from fetch_fixtures import api_key, fetch_next_fixtures
from future_games_parser import build_future_fixtures
from load_data import build_dataset
from predict_next_matches import (
    load_model,
    predict_round,
    add_bets,
    print_predictions,
    PROB_COLUMNS,
)
from backfill_bet_probs import backfill
from export_web import export_web
from run_status import RunStatus

# Next_Matchweek.txt only ever holds Premier League fixtures
FALLBACK_DIV = "E0"


def step(number, title):
    print()
    print("#" * 70)
    print(f"# {number}. {title}")
    print("#" * 70)


def run_week(refresh_current=True, verbose=False, predict=True, divs=None):

    # The result/bet scripts use paths relative to the repo root
    os.chdir(ROOT)

    divs = divs or competitions.enabled()
    status = RunStatus(list(dict.fromkeys(divs + european.EUROPEAN)))

    try:
        step(1, "Fetch new results")
        fetch_all_new_results(divs, status=status)
        fetch_european_results(status)

        step(2, "Settle pending bets")
        complete_bets(divs=divs)

        step(3, "Rebuild match dataset")
        build_dataset(divs, refresh_current=refresh_current, verbose=verbose, status=status)

        step(4, "Backfill gameweek / probabilities")
        backfill()

        if predict:
            _predict_next_round(divs, status)
        else:
            print("\n--no-predict: skipping the next-round predictions.")

        step(6, "Export website data")
        export_web()

    finally:
        print()
        status.write()

        if status.failed():
            print(f"Competitions with errors this run: {', '.join(status.failed())}")


def fetch_european_results(status):
    """
    Bring this season's European caches up to date. One that fails is
    marked stale and its cached results are used - the ratings catch up
    on the next run that gets through.
    """

    session = european._session()

    for div in european.EUROPEAN:
        try:
            cache, listed = european.fetch_season(div, competitions.CURRENT_SEASON, session=session)
            status.set(div, results="ok" if len(cache) >= listed else "stale")
            print(f"{div}: {len(cache)} of {listed} finished matches cached")
        except Exception as exc:
            status.fail(div, exc, results="stale")

    # Country and ground for any club new to Europe (load_european needs them)
    try:
        raw = european.load_cache()
        european.fetch_teams(
            set(raw["HomeId"].astype(int)) | set(raw["AwayId"].astype(int)), session=session
        )
    except Exception as exc:
        print(f"WARNING: couldn't update European club details ({exc})")


def _predict_next_round(divs, status):

    step(5, "Predict next round")

    try:
        if api_key():
            future = fetch_next_fixtures(divs=divs, status=status)
        elif FALLBACK_DIV in divs:
            print("No football-data.org API key - using Next_Matchweek.txt (Premier League only).")
            future = build_future_fixtures()
        else:
            print("No football-data.org API key, and Next_Matchweek.txt is Premier League only.")
            return
    except (ConnectionError, FileNotFoundError, ValueError) as exc:
        print(f"Skipping predictions - {exc}")
        return

    if future is None:
        return

    trained = load_model()

    # One round per competition, each on its own (D14)
    for div, fixtures in future.groupby("Div", sort=False):

        try:
            results = predict_round(fixtures, trained)
            # Cup bets also carry Round and MatchId; Bet stays empty until
            # settled, then 0 (unpriced) until CL odds are captured (P6-03)
            extra = [c for c in ("Round", "MatchId") if c in results.columns]
            added = add_bets(
                results[
                    ["Div", "Gameweek", "Date", "Time", "HomeTeam", "AwayTeam", "Prediction"]
                    + list(PROB_COLUMNS.values()) + extra
                ]
            )
            print_predictions(results)
        except Exception as exc:
            status.fail(div, exc)
            continue

        status.set(div, predicted=added)


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
        help="Use cached FotMob/Understat xG instead of re-scraping the current season."
    )
    parser.add_argument(
        "--no-predict",
        action="store_true",
        help="Only fetch results and settle bets - do not predict the next gameweek."
    )
    parser.add_argument(
        "--divs",
        nargs="+",
        metavar="DIV",
        help="Competitions to run (default: competitions.ENABLED)."
    )
    args = parser.parse_args()

    for div in args.divs or []:
        competitions.get(div)

    run_week(
        refresh_current=not args.no_refresh,
        verbose=args.verbose,
        predict=not args.no_predict,
        divs=args.divs,
    )


if __name__ == "__main__":
    main()
