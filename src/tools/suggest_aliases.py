"""
Offline helper: suggest data/reference/team_names.csv rows for one or
more competitions, by matching each source's team names to
football-data.co.uk's on fixture date + score (notebook 18's voting).
Never runs as part of the pipeline - runtime lookups stay strict.

    python src/tools/suggest_aliases.py SP1 D1          # show the changes
    python src/tools/suggest_aliases.py SP1 --apply     # write them
    python src/tools/suggest_aliases.py E0 --refresh    # re-download caches

Sources, each matched to football-data's names:
    FotMob              league fixtures (name + team id), every season
    Understat           data/raw/top5/<Div>/understat_<s>.csv, if cached
    football-data.org   competition matches (name + team id), 2024-25 on
                        (the free tier refuses earlier seasons)

FotMob and football-data.org fixture lists are cached in
data/raw/<Div>/fotmob_fixtures_<s>.csv and fdorg_matches_<s>.csv.

A club already in team_names.csv (by football_data_name) keeps every
value it has; only empty cells are filled, and any disagreement is
reported as a conflict instead. New clubs get canonical_name = their
FotMob name. The run refuses to write if any alias would map to two
clubs, or a canonical name is used twice. Review the diff (and the
weakest pairings it prints) before committing.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import competitions  # noqa: E402
from fetch_fixtures import api_key  # noqa: E402
from load_data import FOTMOB_API, FOTMOB_HEADERS, competition_dir  # noqa: E402
from team_names import ALIAS_COLUMNS, ID_COLUMNS, REFERENCE_COLUMNS  # noqa: E402

REFERENCE_PATH = ROOT / "data" / "reference" / "team_names.csv"
TOP5_CACHE = ROOT / "data" / "raw" / "top5"

SEASONS = ["21-22", "22-23", "23-24", "24-25", "25-26", "26-27"]

FOTMOB_GAP = 1.5  # seconds between FotMob requests
FDORG_URL = "https://api.football-data.org/v4/competitions/{code}/matches?season={year}"
FDORG_GAP = 6.5  # free tier: 10 requests a minute
BACKOFF = (30, 90)  # seconds to wait after a 429, then give up

# Pairings with fewer votes than this are flagged for a closer look
WEAK_VOTES = 10


# ============================================================
# SOURCES -> one frame shape: day, home, away, home_id, away_id, hg, ag
# ============================================================

def _get(fetch, label):
    """Run ``fetch``, backing off on HTTP 429."""

    for delay in (0, *BACKOFF):
        if delay:
            print(f"  {label}: rate limited, waiting {delay}s")
            time.sleep(delay)
        try:
            return fetch()
        except requests.HTTPError as error:
            if error.response.status_code != 429:
                raise
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise

    raise ConnectionError(f"{label}: still rate limited")


def fotmob_fixtures(div, season, refresh=False):
    """Finished league matches for one season, from FotMob (cached)."""

    path = competition_dir(div) / f"fotmob_fixtures_{season}.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, dtype={"home_id": "Int64", "away_id": "Int64"})

    def fetch():
        response = requests.get(
            f"{FOTMOB_API}/leagues",
            params={"id": competitions.get(div)["fotmob"],
                    "season": f"20{season[:2]}/20{season[3:]}"},
            headers=FOTMOB_HEADERS, timeout=30,
        )
        response.raise_for_status()
        return response.json()

    league = _get(fetch, f"FotMob {div} {season}")
    time.sleep(FOTMOB_GAP)

    rows = []
    for match in league["fixtures"]["allMatches"]:
        status = match["status"]
        if not status.get("finished") or status.get("cancelled"):
            continue
        # Eredivisie lists its European play-offs as rounds too (F9)
        if not str(match.get("round", "")).isdigit():
            continue
        home_goals, away_goals = status["scoreStr"].split(" - ")
        rows.append({
            "day": status["utcTime"][:10],
            "home": match["home"]["name"], "away": match["away"]["name"],
            "home_id": int(match["home"]["id"]), "away_id": int(match["away"]["id"]),
            "hg": int(home_goals), "ag": int(away_goals),
        })

    frame = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    print(f"  cached {path.relative_to(ROOT)} ({len(frame)} matches)")

    return frame


def fdorg_matches(div, season, key, refresh=False):
    """Finished matches for one season from football-data.org (cached),
    or None if the free tier doesn't serve that season."""

    path = competition_dir(div) / f"fdorg_matches_{season}.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, dtype={"home_id": "Int64", "away_id": "Int64"})

    url = FDORG_URL.format(code=competitions.get(div)["fd_org"], year=f"20{season[:2]}")

    def fetch():
        request = urllib.request.Request(url, headers={"X-Auth-Token": key})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["matches"]

    try:
        matches = _get(fetch, f"football-data.org {div} {season}")
    except urllib.error.HTTPError as error:
        if error.code == 403:
            return None
        raise
    finally:
        time.sleep(FDORG_GAP)

    rows = [
        {
            "day": m["utcDate"][:10],
            "home": m["homeTeam"]["name"], "away": m["awayTeam"]["name"],
            "home_id": m["homeTeam"]["id"], "away_id": m["awayTeam"]["id"],
            "hg": m["score"]["fullTime"]["home"], "ag": m["score"]["fullTime"]["away"],
        }
        for m in matches
        if m["status"] == "FINISHED"
    ]

    frame = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    print(f"  cached {path.relative_to(ROOT)} ({len(frame)} matches)")

    return frame


def football_data_results(div, season):
    """football-data.co.uk results: the pipeline's file, else nb 18's cache."""

    for path in [
        competition_dir(div) / f"results_{season}.csv",
        TOP5_CACHE / div / f"{season}.csv",
    ]:
        if path.exists():
            frame = pd.read_csv(path).dropna(subset=["FTR"])
            return pd.DataFrame({
                "day": pd.to_datetime(frame["Date"], dayfirst=True).dt.strftime("%Y-%m-%d"),
                "home": frame["HomeTeam"], "away": frame["AwayTeam"],
                "hg": frame["FTHG"].astype(int), "ag": frame["FTAG"].astype(int),
            })

    return None


def understat_results(div, season):
    """Understat results from nb 18's cache (the pipeline's has no dates)."""

    path = TOP5_CACHE / div / f"understat_{season}.csv"
    if not path.exists():
        return None

    frame = pd.read_csv(path).dropna(subset=["goals_home", "goals_away"])
    return pd.DataFrame({
        "day": pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d"),
        "home": frame["team_home"], "away": frame["team_away"],
        "hg": frame["goals_home"].astype(int), "ag": frame["goals_away"].astype(int),
    })


# ============================================================
# VOTING (notebook 18's match_team_names)
# ============================================================

def match_team_names(fd, other):
    """
    Source name -> football-data name, by fixture voting: every pair of
    matches on the same score within a day of each other votes for its
    home and away names. Greedy one-to-one, strongest pairing first.
    Returns {source name: (football-data name, votes)}.
    """

    fd = fd.assign(day=pd.to_datetime(fd["day"]))
    other = other.assign(day=pd.to_datetime(other["day"]))

    candidates = pd.concat([
        fd.merge(
            other.assign(day=other["day"] + pd.Timedelta(days=shift)),
            on=["day", "hg", "ag"], suffixes=("_fd", ""),
        )
        for shift in (-1, 0, 1)
    ])

    votes = pd.concat([
        candidates[["home", "home_fd"]].set_axis(["source", "football_data"], axis=1),
        candidates[["away", "away_fd"]].set_axis(["source", "football_data"], axis=1),
    ]).value_counts().reset_index()

    mapping = {}
    taken = set()
    for _, row in votes.iterrows():
        if row["source"] not in mapping and row["football_data"] not in taken:
            mapping[row["source"]] = (row["football_data"], int(row["count"]))
            taken.add(row["football_data"])

    return mapping


def _ids(frame):
    """Source name -> team id (one id per name is checked by the caller)."""

    if frame is None or "home_id" not in frame:
        return {}

    pairs = pd.concat([
        frame[["home", "home_id"]].set_axis(["name", "id"], axis=1),
        frame[["away", "away_id"]].set_axis(["name", "id"], axis=1),
    ]).drop_duplicates()

    return dict(zip(pairs["name"], pairs["id"]))


# ============================================================
# SUGGEST
# ============================================================

def suggest(div, refresh=False):
    """
    One suggested row per football-data club in ``div`` (every season
    with results), plus a list of problems and the weakest pairings.
    """

    key = api_key()
    country = competitions.get(div)["country"]

    fd, sources = [], {"fotmob": [], "understat": [], "football_data_org": []}

    for season in SEASONS:
        results = football_data_results(div, season)
        if results is None:
            continue
        fd.append(results)
        sources["fotmob"].append(fotmob_fixtures(div, season, refresh))
        sources["understat"].append(understat_results(div, season))
        if key and season >= "24-25":
            sources["football_data_org"].append(fdorg_matches(div, season, key, refresh))

    fd = pd.concat(fd, ignore_index=True)
    clubs = sorted(set(fd["home"]) | set(fd["away"]))

    rows = {club: {"football_data_name": club, "country": country} for club in clubs}
    problems, pairings = [], []

    for source, frames in sources.items():

        frames = [f for f in frames if f is not None and len(f)]
        if not frames:
            continue

        frame = pd.concat(frames, ignore_index=True)
        mapping = match_team_names(fd, frame)
        ids = _ids(frame)

        unmatched = sorted((set(frame["home"]) | set(frame["away"])) - set(mapping))
        if unmatched:
            problems.append(f"{div} {source}: no football-data match for {unmatched}")

        for name, (club, votes) in mapping.items():
            rows[club][f"{source}_name"] = name
            if name in ids:
                id_column = "fotmob_id" if source == "fotmob" else "football_data_org_id"
                rows[club][id_column] = int(ids[name])
            pairings.append((votes, div, source, name, club))

        # A club renamed in a source shows up as two names for one id
        names_by_id = {}
        for name, team_id in ids.items():
            names_by_id.setdefault(team_id, []).append(name)
        for team_id, names in names_by_id.items():
            if len(names) > 1:
                problems.append(
                    f"{div} {source}: id {team_id} has several names {names} - "
                    f"add the others as aliases by hand"
                )

    return list(rows.values()), problems, pairings


def merge(reference, suggested):
    """
    Fill ``reference`` from ``suggested`` rows: existing clubs (by
    football_data_name) only gain values in empty cells; new clubs are
    added with canonical_name = their FotMob name. Returns the new frame
    and a list of conflicts.
    """

    reference = reference.copy()
    conflicts = []
    by_fd_name = {name: i for i, name in reference["football_data_name"].items()}

    for row in suggested:

        index = by_fd_name.get(row["football_data_name"])

        if index is None:
            canonical = row.get("fotmob_name") or row["football_data_name"]
            reference.loc[len(reference)] = {"canonical_name": canonical, **row}
            continue

        for column, value in row.items():
            current = reference.at[index, column]
            if pd.isna(current):
                reference.at[index, column] = value
            elif str(current) != str(value):
                conflicts.append(
                    f'{reference.at[index, "canonical_name"]}: {column} is '
                    f'{current!r}, sources suggest {value!r} (kept)'
                )

    return reference, conflicts


def check(reference):
    """Every alias and canonical name must point to exactly one club."""

    problems = []

    duplicated = reference["canonical_name"][reference["canonical_name"].duplicated()]
    for name in duplicated:
        problems.append(f"canonical_name {name!r} is used twice")

    owners = {}
    for _, row in reference.iterrows():
        for column in ALIAS_COLUMNS:
            alias = row[column]
            if pd.notna(alias):
                owners.setdefault(alias, set()).add(row["canonical_name"])
    for alias, clubs in owners.items():
        if len(clubs) > 1:
            problems.append(f"alias {alias!r} maps to {sorted(clubs)}")

    for column in ID_COLUMNS:
        ids = reference[column].dropna()
        for team_id in ids[ids.duplicated()]:
            problems.append(f"{column} {team_id} is used twice")

    return problems


def main():

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("divs", nargs="+", help="Competition codes, e.g. SP1 D1")
    parser.add_argument("--apply", action="store_true", help="Write team_names.csv.")
    parser.add_argument("--refresh", action="store_true", help="Re-download the caches.")
    args = parser.parse_args()

    before_text = REFERENCE_PATH.read_text(encoding="utf-8")
    reference = pd.read_csv(REFERENCE_PATH).reindex(columns=REFERENCE_COLUMNS)
    for column in REFERENCE_COLUMNS:
        # New, all-empty columns read as float; give them their real types
        reference[column] = reference[column].astype(
            "Int64" if column in ID_COLUMNS else object
        )

    problems, pairings = [], []
    for div in args.divs:
        print(f"{div}:")
        suggested, div_problems, div_pairings = suggest(div, args.refresh)
        reference, conflicts = merge(reference, suggested)
        problems += div_problems + conflicts
        pairings += div_pairings

    problems += check(reference)
    # Appending rows upcasts the ids to float; write them as whole numbers
    for column in ID_COLUMNS:
        reference[column] = reference[column].astype("Int64")

    print("\nWeakest pairings (votes, div, source, source name -> football-data name):")
    for votes, div, source, name, club in sorted(pairings)[:15]:
        flag = "  <- check" if votes < WEAK_VOTES else ""
        print(f"  {votes:4d}  {div:4s} {source:18s} {name!r} -> {club!r}{flag}")

    after_text = reference.to_csv(index=False, lineterminator="\n")
    added = len(reference) - len(pd.read_csv(REFERENCE_PATH))
    changed = sum(
        a != b for a, b in zip(before_text.splitlines(), after_text.splitlines())
    )
    print(f"\n{added} new club(s); {changed} existing line(s) changed (header included).")

    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  {problem}")

    if any(not p.endswith("(kept)") for p in problems):
        sys.exit("\nNot writing - resolve the problems above first.")

    if not args.apply:
        print("\nDry run - re-run with --apply to write team_names.csv.")
        return

    REFERENCE_PATH.write_text(after_text, encoding="utf-8", newline="")
    print(f"Wrote {REFERENCE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
