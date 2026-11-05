"""
One-off: give a newly added league the raw files load_data needs
(P2-01: P1 and N1), downloading what isn't cached yet.

    python src/tools/backfill_league.py P1 N1           # show what would be fetched
    python src/tools/backfill_league.py P1 N1 --apply   # fetch it

For each league and season 21-22 to 26-27:

    football-data.co.uk <Div>.csv   -> data/raw/<Div>/results_<s>.csv
    FotMob matchDetails xG          -> data/raw/<Div>/fotmob_<s>.csv

A FotMob season is about 300 matchDetails calls, made serially
FOTMOB_DELAY apart with load_data's 429 backoff, so the whole backfill
takes over an hour. It's resumable: progress is checkpointed into the
cache, and a re-run only requests matches the cache doesn't have yet
(including any that failed or had no xG last time). load_data itself
treats an existing past-season cache as complete, so run this until it
reports nothing missing before building the league.
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import competitions  # noqa: E402
from fetch_results import REQUEST_HEADERS, season_url  # noqa: E402
from load_data import _fetch_fotmob_season, competition_dir  # noqa: E402

SEASONS = ["21-22", "22-23", "23-24", "24-25", "25-26", "26-27"]
DOWNLOAD_GAP = 1.0  # seconds between football-data.co.uk requests


def download_results(div, season, dest):
    """Save football-data.co.uk's CSV byte for byte (urllib follows its
    302 from www.football-data.co.uk to football-data.co.uk)."""

    request = urllib.request.Request(season_url(div, season), headers=REQUEST_HEADERS)

    with urllib.request.urlopen(request, timeout=30) as response:
        dest.write_bytes(response.read())

    time.sleep(DOWNLOAD_GAP)


def played(results_path):
    """Matches with a result in a football-data file (0 if not there yet)."""

    if not results_path.exists():
        return 0

    return int(pd.read_csv(results_path)["FTR"].notna().sum())


def cached_xg(cache_path):
    """Matches with both xG values in a FotMob cache (0 if not there yet)."""

    if not cache_path.exists():
        return 0

    cache = pd.read_csv(cache_path)
    return int((cache["HomeXG"].notna() & cache["AwayXG"].notna()).sum())


def backfill_fotmob(div, season, cache_path):

    league_id = competitions.get(div)["fotmob"]
    before = cached_xg(cache_path)

    frame = _fetch_fotmob_season(f"20{season[:2]}-20{season[3:]}", cache_path, league_id)
    frame.to_csv(cache_path, index=False)

    print(f"  {div} {season}: FotMob {before} -> {len(frame)} matches with xG")


def main():

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("divs", nargs="+", help="Competition codes, e.g. P1 N1")
    parser.add_argument("--apply", action="store_true", help="Download and scrape.")
    args = parser.parse_args()

    for div in args.divs:
        if competitions.get(div)["fotmob"] is None:
            sys.exit(f"{div} has no FotMob id in competitions.py")

    print(f"{'':4} {'season':6} {'results':>8} {'FotMob xG':>10}")
    for div in args.divs:
        for season in SEASONS:
            folder = competition_dir(div)
            print(
                f"{div:4} {season:6} "
                f"{played(folder / f'results_{season}.csv'):8d} "
                f"{cached_xg(folder / f'fotmob_{season}.csv'):10d}"
            )

    if not args.apply:
        print("\nDry run - re-run with --apply to fetch whatever is missing.")
        return

    for div in args.divs:

        folder = competition_dir(div)
        folder.mkdir(parents=True, exist_ok=True)

        for season in SEASONS:

            results_path = folder / f"results_{season}.csv"
            if not results_path.exists():
                download_results(div, season, results_path)
                print(f"  {div} {season}: results ({played(results_path)} played)")

            # Always called: it only requests matches the cache is missing
            backfill_fotmob(div, season, folder / f"fotmob_{season}.csv")


if __name__ == "__main__":
    main()
