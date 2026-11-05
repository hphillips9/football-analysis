"""
Fill the European caches (P4-01): CL, EL and ECL from FotMob, 21-22 to
the current season.

    python src/tools/backfill_europe.py                 # show what's cached
    python src/tools/backfill_europe.py --apply         # fetch what's missing
    python src/tools/backfill_europe.py CL --apply      # one competition

For each competition and season:

    FotMob leagues + matchDetails  -> data/raw/<Div>/fotmob_<s>.csv
    FotMob teams (each new club)   -> data/raw/fotmob_teams.csv

About 2,300 matchDetails plus one call per club, serial and FOTMOB_DELAY
apart, so a full run takes about an hour. Don't run it alongside another
FotMob backfill. It's resumable: progress is checkpointed, and a re-run
only requests what the caches don't have yet.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import competitions  # noqa: E402
import european  # noqa: E402
from load_data import competition_dir  # noqa: E402

# Matches per CL season FotMob should list: 32 teams in groups until
# 23-24, then the 36-team league phase (P4-01 acceptance)
EXPECTED_CL = {"21-22": 125, "22-23": 125, "23-24": 125, "24-25": 189, "25-26": 189}

# Home ties this far from the club's ground are listed for review
FAR_KM = 150


def seasons():
    """21-22 to the current season, e.g. ["21-22", ..., "26-27"]."""

    first = int(european.FIRST_SEASON[:2])
    last = int(competitions.CURRENT_SEASON[:2])

    return [f"{y:02d}-{y + 1:02d}" for y in range(first, last + 1)]


def show(divs):

    print(f"{'':4} {'season':6} {'cached':>7} {'xG':>5}")

    for div in divs:
        for season in seasons():
            cache = european.read_cache(competition_dir(div) / f"fotmob_{season}.csv")
            with_xg = int((cache["HomeXG90"].notna() & cache["AwayXG90"].notna()).sum())
            print(f"{div:4} {season:6} {len(cache):7d} {with_xg:5d}")


def summary(divs):
    """Per-season counts against FotMob's lists, CL acceptance, relocated ties."""

    matches = european.load_european(divs)

    print("\nLoaded:")
    print(
        matches.groupby(["Div", "Season"])
        .agg(matches=("MatchId", "size"), xg=("XGSource", "count"),
             extra_time=("AETHG", "count"), neutral=("Neutral", "sum"))
        .to_string()
    )

    if "CL" in divs:
        counts = matches[matches["Div"] == "CL"].groupby("Season").size()
        wrong = {
            season: int(counts.get(season, 0))
            for season, expected in EXPECTED_CL.items()
            if counts.get(season, 0) != expected
        }
        print(f"\nCL 21-22 -> 25-26: {'OK' if not wrong else f'MISMATCH {wrong}'} "
              f"(expected {'/'.join(map(str, EXPECTED_CL.values()))})")

    outside = pd.concat([matches["HomeLeague"], matches["AwayLeague"]])
    print(f"\nClubs outside the modelled leagues: "
          f"{matches.loc[matches['HomeLeague'].str.startswith('X:'), 'HomeTeam'].nunique()} "
          f"({outside.str.startswith('X:').mean():.0%} of appearances)")

    relocated = matches[(matches["Neutral"] == 1) & (matches["Stage"] != "FINAL")]
    if not relocated.empty:
        print("\nHome ties played outside the home club's country "
              "(Neutral = 1) - check these look right:")
        print(relocated[["Div", "Season", "Date", "HomeTeam", "AwayTeam"]].to_string(index=False))

    # The other way round: far from home but counted as in-country
    raw = european.load_cache(divs).set_index("MatchId")
    grounds = european.read_teams().set_index("FotMobId")
    far = []
    for match in matches[(matches["Neutral"] == 0)].itertuples():
        row = raw.loc[match.MatchId]
        ground = grounds.loc[int(row["HomeId"])]
        if pd.notna(ground["VenueLat"]) and european._distance_km(
            ground["VenueLat"], ground["VenueLon"], row["StadiumLat"], row["StadiumLon"]
        ) > FAR_KM:
            far.append((match.Div, match.Season, match.Date.date(), match.HomeTeam, match.AwayTeam))
    if far:
        print(f"\nHome ties over {FAR_KM} km from the club's ground but counted as "
              f"in-country - add any that were abroad to {european.STADIUMS_PATH}:")
        print(pd.DataFrame(far, columns=["Div", "Season", "Date", "HomeTeam", "AwayTeam"])
              .to_string(index=False))


def main():

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "divs", nargs="*", default=european.EUROPEAN,
        help=f"Competition codes (default: {' '.join(european.EUROPEAN)})",
    )
    parser.add_argument("--apply", action="store_true", help="Fetch from FotMob.")
    args = parser.parse_args()

    # Club names like "Slovan Bratislava" / "Viktoria Plzeň" break the
    # Windows console's cp1252
    sys.stdout.reconfigure(encoding="utf-8")

    for div in args.divs:
        if div not in european.EUROPEAN:
            sys.exit(f"{div} isn't a European competition ({', '.join(european.EUROPEAN)})")

    show(args.divs)

    if not args.apply:
        print("\nDry run - re-run with --apply to fetch whatever is missing.")
        return

    session = european._session()

    for div in args.divs:
        for season in seasons():
            before = len(european.read_cache(competition_dir(div) / f"fotmob_{season}.csv"))
            cache, listed = european.fetch_season(div, season, session=session)
            print(f"  {div} {season}: {before} -> {len(cache)} cached "
                  f"(FotMob lists {listed} finished)")

    raw = european.load_cache(args.divs)
    team_ids = set(raw["HomeId"].astype(int)) | set(raw["AwayId"].astype(int))
    before = len(european.read_teams())
    teams = european.fetch_teams(team_ids, session=session)
    print(f"  teams: {before} -> {len(teams)}")

    summary(args.divs)


if __name__ == "__main__":
    main()
