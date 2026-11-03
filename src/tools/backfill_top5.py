"""
One-off: give SP1, D1, I1 and F1 the same raw files the Premier League
has, so load_data can build them (P1-03).

    python src/tools/backfill_top5.py           # show what would be written
    python src/tools/backfill_top5.py --apply   # write it

For each league and season 21-22 to 26-27:

    football-data.co.uk <Div>.csv           -> data/raw/<Div>/results_<s>.csv
    data/raw/top5/<Div>/fotmob_<s>.csv      -> data/raw/<Div>/fotmob_<s>.csv
    data/raw/top5/<Div>/understat_<s>.csv   -> data/raw/<Div>/understat_<s>.csv

The results are downloaded in full; the top5/ copies are trimmed to
notebook 18's columns. The xG caches are copied, not moved (top5/ stays
as notebooks 18/19 expect it), and converted to load_data's cache
columns. Files already at a destination are left alone, so it's safe to
re-run.
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fetch_results import REQUEST_HEADERS, season_url  # noqa: E402
from load_data import FOTMOB_CACHE_COLUMNS, RAW_DIR  # noqa: E402

DIVS = ["SP1", "D1", "I1", "F1"]
SEASONS = ["21-22", "22-23", "23-24", "24-25", "25-26", "26-27"]
TOP5 = RAW_DIR / "top5"
DOWNLOAD_GAP = 1.0  # seconds between football-data.co.uk requests

UNDERSTAT_COLUMNS = {
    "team_home": "HomeTeam",
    "team_away": "AwayTeam",
    "xg_home": "HomeXG",
    "xg_away": "AwayXG",
}


def download_results(div, season, dest):
    """Save football-data.co.uk's CSV byte for byte, as E0's files are."""

    url = season_url(div, season)
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)

    with urllib.request.urlopen(request, timeout=30) as response:
        dest.write_bytes(response.read())

    time.sleep(DOWNLOAD_GAP)


def convert_fotmob(src, dest):
    """nb 18's cache (MatchId, UtcTime, ..., Score) -> load_data's columns."""

    cache = pd.read_csv(src, dtype={"MatchId": str})
    cache["Date"] = cache["UtcTime"].str[:10]
    cache[FOTMOB_CACHE_COLUMNS].to_csv(dest, index=False)


def convert_understat(src, dest):
    """nb 18's cache (date, team_home, ...) -> load_data's columns."""

    cache = pd.read_csv(src)
    cache.rename(columns=UNDERSTAT_COLUMNS)[list(UNDERSTAT_COLUMNS.values())].to_csv(
        dest, index=False
    )


def planned_jobs():

    jobs = []

    for div in DIVS:
        for season in SEASONS:
            dest_dir = RAW_DIR / div
            jobs += [
                ("download", (div, season), dest_dir / f"results_{season}.csv"),
                ("fotmob", TOP5 / div / f"fotmob_{season}.csv", dest_dir / f"fotmob_{season}.csv"),
                ("understat", TOP5 / div / f"understat_{season}.csv", dest_dir / f"understat_{season}.csv"),
            ]

    return [job for job in jobs if not job[2].exists()]


def main():

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually write the files.")
    args = parser.parse_args()

    jobs = planned_jobs()

    if not jobs:
        print("Nothing to do - every file is already in place.")
        return

    for kind, src, dest in jobs:
        label = season_url(*src) if kind == "download" else src.relative_to(ROOT)
        print(f"{kind:9}  {label}  ->  {dest.relative_to(ROOT)}")

    if not args.apply:
        print(f"\n{len(jobs)} file(s). Dry run - re-run with --apply to write them.")
        return

    for kind, src, dest in jobs:

        dest.parent.mkdir(parents=True, exist_ok=True)

        if kind == "download":
            download_results(*src, dest)
        elif kind == "fotmob":
            convert_fotmob(src, dest)
        else:
            convert_understat(src, dest)

    print(f"\nWrote {len(jobs)} file(s).")


if __name__ == "__main__":
    main()
