"""
P9-03: give the domestic leagues their older seasons (10-11 .. 20-21)
for research on a longer training history. Nothing here touches the
live pipeline: the files go in data/raw/<Div>/history/, which
load_data only reads when asked (build_dataset(history_start=...)).

    python src/tools/backfill_history.py                    # coverage so far
    python src/tools/backfill_history.py --results          # football-data CSVs
    python src/tools/backfill_history.py --understat        # Understat xG (top 5, 14-15 on)
    python src/tools/backfill_history.py --fotmob           # FotMob xG (slow, resumable)
    python src/tools/backfill_history.py --fotmob --divs E0 --seasons 16-17 17-18
    python src/tools/backfill_history.py --stats --seasons 20-21 19-20 18-19 17-18 16-17

For each league and season:

    football-data.co.uk <Div>.csv  -> history/results_<s>.csv
    Understat xG                   -> history/understat_<s>.csv
    FotMob matchDetails xG         -> history/fotmob_<s>.csv

FotMob is ~300 matchDetails calls per league-season, serial, FOTMOB_DELAY
apart with load_data's 429 backoff and checkpointing - the full run is
many hours, and a re-run only requests what the cache lacks. A season
FotMob has no xG for at all is recorded in history/fotmob_none.txt after
PROBE matches come back empty, so it isn't re-scraped every run.

19-20 and 20-21 (COVID, D3) are fetched for rating and form continuity
only; they are never training or test rows.
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import competitions  # noqa: E402
import load_data  # noqa: E402
from fetch_results import REQUEST_HEADERS, season_url  # noqa: E402

SEASONS = [f"{y:02d}-{y + 1:02d}" for y in range(10, 21)]
DOWNLOAD_GAP = 1.0
# Matches tried before a season is written off as having no FotMob xG
PROBE = 15


def history_dir(div):
    return load_data.history_dir(div)


def download_results(div, season, dest):
    request = urllib.request.Request(season_url(div, season), headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        dest.write_bytes(response.read())
    time.sleep(DOWNLOAD_GAP)


def count_rows(path, columns):
    if not path.exists():
        return 0
    frame = pd.read_csv(path, encoding="latin-1")
    return int(frame[columns].notna().all(axis=1).sum())


def no_fotmob(div):
    path = history_dir(div) / "fotmob_none.txt"
    return set(path.read_text().split()) if path.exists() else set()


def mark_no_fotmob(div, season):
    path = history_dir(div) / "fotmob_none.txt"
    path.write_text("\n".join(sorted(no_fotmob(div) | {season})) + "\n")


def fotmob_has_xg(div, season):
    """
    False if the first PROBE finished matches of the season have no xG
    (FotMob doesn't carry it that far back for this league).
    """

    session = requests.Session()
    session.headers.update(load_data.FOTMOB_HEADERS)
    league = load_data._fotmob_get(
        session, "leagues",
        {"id": competitions.get(div)["fotmob"], "season": f"20{season[:2]}/20{season[3:]}"},
    )
    finished = [
        m for m in league["fixtures"]["allMatches"]
        if m["status"].get("finished") and not m["status"].get("cancelled")
    ]
    # Spread over the season: xG coverage sometimes starts mid-season
    step = max(1, len(finished) // PROBE)
    for match in finished[::step][:PROBE]:
        home, _ = load_data._fotmob_match_xg(session, match["id"])
        time.sleep(load_data.FOTMOB_DELAY)
        if home is not None:
            return True
    return False


def fetch_fotmob(div, season):
    folder = history_dir(div)
    cache = folder / f"fotmob_{season}.csv"

    if season in no_fotmob(div):
        return
    if not cache.exists() and not fotmob_has_xg(div, season):
        mark_no_fotmob(div, season)
        print(f"  {div} {season}: FotMob has no xG - skipped", flush=True)
        return

    before = count_rows(cache, ["HomeXG", "AwayXG"])
    frame = load_data._fetch_fotmob_season(
        f"20{season[:2]}-20{season[3:]}", cache, competitions.get(div)["fotmob"]
    )
    frame.to_csv(cache, index=False)
    print(f"  {div} {season}: FotMob {before} -> {len(frame)} matches with xG", flush=True)


# FotMob match stats kept for a richer xG proxy (from 16-17 on: big
# chances and box shots; FotMob's own xG starts in 20-21)
STAT_KEYS = [
    "total_shots", "ShotsOnTarget", "big_chance", "big_chance_missed_title",
    "shots_inside_box", "shots_outside_box", "shots_woodwork", "blocked_shots",
    "corners", "expected_goals",
]
STATS_COLUMNS = ["MatchId", "Date", "HomeTeam", "AwayTeam"] + [
    f"{side}_{key}" for key in STAT_KEYS for side in ("Home", "Away")
]


def _number(value):
    try:
        return float(str(value).split()[0])
    except (TypeError, ValueError, IndexError):
        return float("nan")


def match_stats(details):
    """{Home_<key>: value, Away_<key>: value} for STAT_KEYS in one matchDetails."""

    try:
        groups = details["content"]["stats"]["Periods"]["All"]["stats"]
    except (KeyError, TypeError):
        return {}

    found = {}
    for group in groups:
        for stat in group.get("stats", []):
            if stat.get("key") in STAT_KEYS and stat.get("stats") and stat["key"] not in found:
                found[stat["key"]] = stat["stats"]

    row = {}
    for key, (home, away) in found.items():
        row[f"Home_{key}"] = _number(home)
        row[f"Away_{key}"] = _number(away)
    return row


def fetch_stats(div, season):
    """
    history/fotmob_stats_<s>.csv: STATS_COLUMNS for every finished league
    match, resumable (checkpointed; a re-run only requests missing
    matches). A season whose first PROBE matches have no big-chance
    count is recorded in fotmob_stats_none.txt and skipped.
    """

    folder = history_dir(div)
    cache = folder / f"fotmob_stats_{season}.csv"
    none_path = folder / "fotmob_stats_none.txt"
    skipped = set(none_path.read_text().split()) if none_path.exists() else set()

    if season in skipped:
        return

    cached = (
        pd.read_csv(cache, dtype={"MatchId": str}) if cache.exists()
        else pd.DataFrame(columns=STATS_COLUMNS)
    )
    have = set(cached["MatchId"].astype(str))

    session = requests.Session()
    session.headers.update(load_data.FOTMOB_HEADERS)
    league = load_data._fotmob_get(
        session, "leagues",
        {"id": competitions.get(div)["fotmob"], "season": f"20{season[:2]}/20{season[3:]}"},
    )
    finished = [
        m for m in league["fixtures"]["allMatches"]
        if m["status"].get("finished") and not m["status"].get("cancelled")
        and str(m.get("round", "")).isdigit()
    ]

    rows, tried, with_chances = [], 0, 0

    def save():
        frame = pd.concat([cached, pd.DataFrame(rows)], ignore_index=True)
        frame.reindex(columns=STATS_COLUMNS).to_csv(cache, index=False)

    for match in finished:
        if str(match["id"]) in have:
            continue
        try:
            details = load_data._fotmob_get(session, "matchDetails", {"matchId": match["id"]})
        except requests.RequestException as exc:
            print(f"WARNING: FotMob match {match['id']} failed ({exc})", flush=True)
            continue
        finally:
            time.sleep(load_data.FOTMOB_DELAY)

        stats = match_stats(details)
        tried += 1
        with_chances += "Home_big_chance" in stats

        if not cache.exists() and not rows and tried >= PROBE and not with_chances:
            none_path.write_text("\n".join(sorted(skipped | {season})) + "\n")
            print(f"  {div} {season}: no FotMob big-chance stats - skipped", flush=True)
            return

        if not stats:
            continue
        rows.append({
            "MatchId": str(match["id"]),
            "Date": match["status"]["utcTime"][:10],
            "HomeTeam": match["home"]["name"],
            "AwayTeam": match["away"]["name"],
            **stats,
        })
        if len(rows) % load_data.FOTMOB_CHECKPOINT_EVERY == 0:
            save()

    if rows:
        save()
    total = len(cached) + len(rows)
    print(f"  {div} {season}: FotMob stats {len(cached)} -> {total} matches", flush=True)


def fetch_understat(div, season):
    competition = competitions.get(div)["understat"]
    if competition is None or season < "14-15":
        return
    cache = history_dir(div) / f"understat_{season}.csv"
    if cache.exists():
        return
    frame = load_data._fetch_understat_season(f"20{season[:2]}-20{season[3:]}", competition)
    frame.to_csv(cache, index=False)
    print(f"  {div} {season}: Understat {len(frame)} matches", flush=True)


def suggest_aliases(divs, seasons):
    """
    team_names.csv rows for clubs in the history files that the alias
    map doesn't know, with their FotMob name voted from the FotMob
    caches: same day (+-1, FotMob dates are UTC), against an opponent
    whose FotMob name is known. No requests.
    """

    from team_names import load_alias_map

    alias_map = load_alias_map()
    reference = pd.read_csv(ROOT / "data" / "reference" / "team_names.csv")
    fotmob_of = dict(zip(reference["canonical_name"], reference["fotmob_name"]))
    rows = []

    for div in divs:
        votes = {}
        for season in seasons:
            results_path = history_dir(div) / f"results_{season}.csv"
            if not results_path.exists():
                continue
            results = load_data._read_history_results(results_path, div)
            # FotMob names from the xG and the stats caches
            caches = [
                pd.read_csv(path)[["Date", "HomeTeam", "AwayTeam"]]
                for path in (
                    history_dir(div) / f"fotmob_{season}.csv",
                    history_dir(div) / f"fotmob_stats_{season}.csv",
                )
                if path.exists()
            ]
            fotmob = (
                pd.concat(caches, ignore_index=True).drop_duplicates() if caches
                else pd.DataFrame(columns=["Date", "HomeTeam", "AwayTeam"])
            )
            fotmob["Day"] = pd.to_datetime(fotmob["Date"])
            days = pd.to_datetime(results["Date"], dayfirst=True)

            for day, home, away in zip(days, results["HomeTeam"], results["AwayTeam"]):
                for club, opponent, side, other in (
                    (home, away, "HomeTeam", "AwayTeam"),
                    (away, home, "AwayTeam", "HomeTeam"),
                ):
                    if club in alias_map:
                        continue
                    votes.setdefault(club, {})
                    known = fotmob_of.get(alias_map.get(opponent))
                    if known is None:
                        continue
                    hit = fotmob[
                        ((fotmob["Day"] - day).abs() <= pd.Timedelta(days=1))
                        & (fotmob[other] == known)
                    ]
                    for name in hit[side]:
                        votes[club][name] = votes[club].get(name, 0) + 1

        for club, tally in sorted(votes.items()):
            best = max(tally, key=tally.get) if tally else None
            rows.append({
                "Div": div, "football_data_name": club, "fotmob_name": best,
                "votes": tally.get(best, 0), "runner_up": sorted(tally.values())[-2:-1],
            })

    return pd.DataFrame(rows)


COVERAGE_PATH = ROOT / "data" / "processed" / "history_coverage.csv"
# Share of a league-season's matches with each set of prices
ODDS_SETS = {
    "avg_open": ["AvgH", "AvgD", "AvgA"],
    "b365_open": ["B365H", "B365D", "B365A"],
    "pinnacle_open": ["PSH", "PSD", "PSA"],
    "pinnacle_close": ["PSCH", "PSCD", "PSCA"],
    "avg_close": ["AvgCH", "AvgCD", "AvgCA"],
    "shots": ["HS", "AS", "HST", "AST"],
}


def dataset_coverage(path=load_data.HISTORY_OUTPUT_PATH):
    """
    Per league-season coverage of the built history dataset: matches,
    the share with each ODDS_SETS group, and the XGSource mix (counts).
    Written to COVERAGE_PATH.
    """

    matches = load_data.read_matches(path)
    rows = []

    for (div, season), group in matches.groupby(["Div", "Season"], sort=False):
        row = {"Div": div, "Season": season, "matches": len(group)}
        for name, columns in ODDS_SETS.items():
            have = [c for c in columns if c in group.columns]
            row[name] = (
                round(group[have].apply(pd.to_numeric, errors="coerce").notna().all(axis=1).mean(), 3)
                if len(have) == len(columns) else 0.0
            )
        sources = group["XGSource"].fillna("none").value_counts()
        for source in [
            "FotMob", "football-data", "Understat",
            load_data.STATS_PROXY_SOURCE, load_data.XG_PROXY_SOURCE, "none",
        ]:
            row[f"xg_{source}"] = int(sources.get(source, 0))
        rows.append(row)

    order = {div: i for i, div in enumerate(competitions.COMPETITIONS)}
    table = pd.DataFrame(rows).sort_values(
        ["Div", "Season"], key=lambda s: s.map(order) if s.name == "Div" else s
    )
    table.to_csv(COVERAGE_PATH, index=False)

    return table


def coverage(divs, seasons):
    rows = []
    for div in divs:
        folder = history_dir(div)
        for season in seasons:
            results = folder / f"results_{season}.csv"
            rows.append({
                "Div": div, "Season": season,
                "results": count_rows(results, ["FTR"]),
                "fotmob": count_rows(folder / f"fotmob_{season}.csv", ["HomeXG", "AwayXG"]),
                "understat": count_rows(folder / f"understat_{season}.csv", ["HomeXG", "AwayXG"]),
            })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--divs", nargs="+", default=competitions.leagues())
    parser.add_argument("--seasons", nargs="+", default=SEASONS)
    parser.add_argument("--results", action="store_true")
    parser.add_argument("--understat", action="store_true")
    parser.add_argument("--fotmob", action="store_true")
    parser.add_argument(
        "--stats", action="store_true",
        help="FotMob match stats (big chances, box shots) for the richer xG proxy.",
    )
    parser.add_argument(
        "--aliases", action="store_true",
        help="Suggest team_names.csv rows for unknown clubs (from the FotMob caches).",
    )
    parser.add_argument(
        "--dataset-coverage", action="store_true",
        help="Coverage of the built all_matches_history.csv (odds, xG sources) per league-season.",
    )
    args = parser.parse_args()

    if args.dataset_coverage:
        print(dataset_coverage().to_string(index=False))
        return

    if args.aliases:
        print(suggest_aliases(args.divs, args.seasons).to_string(index=False))
        return

    for div in args.divs:
        history_dir(div).mkdir(parents=True, exist_ok=True)

        for season in args.seasons:
            try:
                if args.results:
                    dest = history_dir(div) / f"results_{season}.csv"
                    if not dest.exists():
                        download_results(div, season, dest)
                        print(f"  {div} {season}: results", flush=True)
                if args.understat:
                    fetch_understat(div, season)
                if args.fotmob:
                    fetch_fotmob(div, season)
                if args.stats:
                    fetch_stats(div, season)
            except Exception as exc:  # keep going; a re-run picks it up
                print(f"  {div} {season}: FAILED {type(exc).__name__}: {exc}", flush=True)

    print(coverage(args.divs, args.seasons).to_string(index=False))


if __name__ == "__main__":
    main()
