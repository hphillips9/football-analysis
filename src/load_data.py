import os
import re
import glob
import time
import argparse
import warnings
from pathlib import Path

import pandas as pd
import penaltyblog as pb
import requests

from team_names import load_alias_map, normalize_team_names

# The football-data result files carry ~200 bookmaker-odds columns, so
# pandas warns every time we add one more. The width is expected here.
warnings.simplefilter("ignore", pd.errors.PerformanceWarning)


# ============================================================
# PATHS / CONFIG
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = ROOT / "data" / "raw"
FOTMOB_CACHE_DIR = RAW_DIR / "fotmob"
UNDERSTAT_CACHE_DIR = RAW_DIR / "understat"
OUTPUT_PATH = ROOT / "data" / "processed" / "all_matches.csv"

UNDERSTAT_COMPETITION = "ENG Premier League"

# FotMob's xG is Opta's - the same numbers BBC and Sky show
FOTMOB_API = "https://www.fotmob.com/api/data"
FOTMOB_LEAGUE_ID = 47  # Premier League
FOTMOB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}
FOTMOB_DELAY = 0.6  # seconds between match requests
# Opta revises xG for a day or two after full time, so matches this
# recent are re-fetched on every refresh rather than kept from the cache
FOTMOB_REFETCH_DAYS = 3
FOTMOB_CACHE_COLUMNS = [
    "MatchId", "Date", "HomeTeam", "AwayTeam", "HomeXG", "AwayXG"
]

# EPL25-26.csv -> ("25", "26")
SEASON_FILE_RE = re.compile(r"EPL(\d{2})-(\d{2})\.csv$", re.IGNORECASE)

XG_COLUMNS = ["Season", "HomeTeam", "AwayTeam", "HomeXG", "AwayXG"]


# ============================================================
# SEASON DISCOVERY
# ============================================================

def discover_seasons(raw_dir=RAW_DIR):
    """
    Map season label -> full season string, derived from the EPL*.csv
    result files that are actually present.

        {"21-22": "2021-2022", ..., "26-27": "2026-2027"}

    Understat takes the string as is; FotMob wants "2021/2022".

    Insertion order is chronological, so the last entry is the
    current season.
    """

    seasons = {}

    for path in sorted(glob.glob(str(raw_dir / "EPL*.csv"))):

        match = SEASON_FILE_RE.search(os.path.basename(path))

        if not match:
            continue

        start_yy, end_yy = match.groups()

        # Assumes 21st century - fine until 2100
        seasons[f"{start_yy}-{end_yy}"] = f"20{start_yy}-20{end_yy}"

    return seasons


# ============================================================
# LOAD EXISTING MATCH DATA
# ============================================================

def load_result_files(raw_dir=RAW_DIR):
    """
    Concatenate every EPL*.csv result file into one chronologically
    sorted frame with Season, Gameweek and MatchDateTime columns.
    """

    frames = []

    for path in sorted(glob.glob(str(raw_dir / "EPL*.csv"))):

        match = SEASON_FILE_RE.search(os.path.basename(path))

        if not match:
            continue

        label = f"{match.group(1)}-{match.group(2)}"

        df = pd.read_csv(path)

        frames.append(df.assign(Season=label))

    if not frames:
        raise FileNotFoundError(
            f"No EPL*.csv result files found in {raw_dir}"
        )

    matches = pd.concat(frames, ignore_index=True)

    # Season first, matching the historical column order
    matches = matches[["Season"] + [c for c in matches.columns if c != "Season"]]

    matches = matches.assign(
        MatchDateTime=pd.to_datetime(
            matches["Date"] + " " + matches["Time"],
            dayfirst=True
        )
    )

    matches = (
        matches
        .sort_values(["MatchDateTime", "HomeTeam", "AwayTeam"])
        .reset_index(drop=True)
        .copy()
    )

    return add_gameweek(matches)


# ============================================================
# GAMEWEEK
# ============================================================

def add_gameweek(matches):
    """
    Label every match with its gameweek (1-38).

    For each team, its gameweek is the running count of matches it has
    played that season. The two sides of a fixture normally agree; where a
    postponement makes them differ, take the larger so a rescheduled game
    carries the number of when it was actually played.
    """

    matches = (
        matches
        .sort_values(["MatchDateTime", "HomeTeam", "AwayTeam"])
        .reset_index(drop=True)
        .copy()
    )

    # One row per team appearance, in chronological order, so a running
    # count per team spans both home and away games
    appearances = pd.concat([
        pd.DataFrame({
            "match": matches.index,
            "Season": matches["Season"],
            "Team": matches["HomeTeam"],
            "side": "home",
        }),
        pd.DataFrame({
            "match": matches.index,
            "Season": matches["Season"],
            "Team": matches["AwayTeam"],
            "side": "away",
        }),
    ]).sort_values("match")

    appearances["n"] = (
        appearances.groupby(["Season", "Team"]).cumcount() + 1
    )

    home_n = appearances[appearances["side"] == "home"].set_index("match")["n"]
    away_n = appearances[appearances["side"] == "away"].set_index("match")["n"]

    matches["Gameweek"] = (
        pd.concat([home_n, away_n], axis=1).max(axis=1).astype(int)
    )

    lead = ["Season", "Gameweek"]
    return matches[lead + [c for c in matches.columns if c not in lead]]


# ============================================================
# PER-SEASON XG CACHE
# ============================================================

def _load_xg_seasons(
    source,
    fetch_season,
    seasons,
    cache_dir,
    refresh_current=True,
    verbose=False
):
    """
    Return combined xG from one source for every season in ``seasons``.

    ``fetch_season(season, cache_path)`` scrapes one season (it may read
    ``cache_path`` to fetch only what is new). Historical seasons never
    change, so they are scraped once and then read from ``cache_dir``.
    The current (last) season is re-scraped on every run unless
    ``refresh_current`` is False. A failed scrape falls back to the
    cached copy when one exists.
    """

    cache_dir.mkdir(parents=True, exist_ok=True)

    labels = list(seasons)
    current_label = labels[-1] if labels else None

    frames = []

    for label in labels:

        cache_path = cache_dir / f"{label}.csv"
        is_current = label == current_label

        want_fresh = (is_current and refresh_current) or not cache_path.exists()

        if want_fresh:

            try:
                season_df = fetch_season(seasons[label], cache_path)
                season_df.to_csv(cache_path, index=False)

                if verbose:
                    print(
                        f"Fetched {source} {label} "
                        f"({len(season_df)} games) -> {cache_path.name}"
                    )

            except Exception as exc:

                if cache_path.exists():
                    print(
                        f"WARNING: {source} fetch failed for {label} "
                        f"({exc}); using cached copy."
                    )
                    season_df = pd.read_csv(cache_path)
                else:
                    print(
                        f"WARNING: {source} fetch failed for {label} "
                        f"({exc}); no cache available, skipping its xG "
                        f"for this season."
                    )
                    continue

        else:
            season_df = pd.read_csv(cache_path)

            if verbose:
                print(
                    f"Loaded {source} {label} from cache "
                    f"({len(season_df)} games)"
                )

        season_df = season_df[["HomeTeam", "AwayTeam", "HomeXG", "AwayXG"]].copy()
        season_df.insert(0, "Season", label)
        frames.append(season_df)

    if not frames:
        return pd.DataFrame(columns=XG_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)

    return combined.drop_duplicates(
        subset=["Season", "HomeTeam", "AwayTeam"]
    )


# ============================================================
# FOTMOB (OPTA) XG - PRIMARY SOURCE
# ============================================================

def _fotmob_get(session, endpoint, params):

    response = session.get(
        f"{FOTMOB_API}/{endpoint}", params=params, timeout=30
    )
    response.raise_for_status()

    return response.json()


def _fotmob_match_xg(session, match_id):
    """(home xG, away xG) for one FotMob match, or (None, None)."""

    details = _fotmob_get(session, "matchDetails", {"matchId": match_id})

    try:
        stats = details["content"]["stats"]["Periods"]["All"]["stats"][0]["stats"]
    except (KeyError, IndexError, TypeError):
        return None, None

    for stat in stats:
        if stat.get("key") == "expected_goals":
            home_xg, away_xg = stat["stats"]
            return float(home_xg), float(away_xg)

    return None, None


def _fetch_fotmob_season(season, cache_path):
    """
    Scrape one season of FotMob xG (finished games only).

    Matches already in ``cache_path`` with xG are kept as they are, so a
    weekly refresh only requests the newly played round (plus anything
    from the last FOTMOB_REFETCH_DAYS, to pick up Opta's revisions). A
    match that fails or has no xG yet is left out and retried on the
    next run.
    """

    cached = (
        pd.read_csv(cache_path, dtype={"MatchId": str})
        if cache_path.exists()
        else pd.DataFrame(columns=FOTMOB_CACHE_COLUMNS)
    )
    cutoff = (
        pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        - pd.Timedelta(days=FOTMOB_REFETCH_DAYS)
    )
    cached = cached[
        cached["HomeXG"].notna()
        & cached["AwayXG"].notna()
        & (pd.to_datetime(cached["Date"]) < cutoff)
    ]
    have = set(cached["MatchId"])

    session = requests.Session()
    session.headers.update(FOTMOB_HEADERS)

    league = _fotmob_get(
        session,
        "leagues",
        {"id": FOTMOB_LEAGUE_ID, "season": season.replace("-", "/")}
    )

    finished = [
        m for m in league["fixtures"]["allMatches"]
        if m["status"].get("finished") and not m["status"].get("cancelled")
    ]

    rows = []

    for match in finished:

        if match["id"] in have:
            continue

        try:
            home_xg, away_xg = _fotmob_match_xg(session, match["id"])
        except requests.RequestException as exc:
            print(f"WARNING: FotMob match {match['id']} failed ({exc})")
            continue
        finally:
            time.sleep(FOTMOB_DELAY)

        if home_xg is None:
            continue

        rows.append({
            "MatchId": match["id"],
            "Date": match["status"]["utcTime"][:10],
            "HomeTeam": match["home"]["name"],
            "AwayTeam": match["away"]["name"],
            "HomeXG": home_xg,
            "AwayXG": away_xg,
        })

    if not rows:
        return cached[FOTMOB_CACHE_COLUMNS]

    return pd.concat(
        [cached, pd.DataFrame(rows)], ignore_index=True
    )[FOTMOB_CACHE_COLUMNS]


def fetch_fotmob_xg(
    seasons,
    cache_dir=FOTMOB_CACHE_DIR,
    refresh_current=True,
    verbose=False
):
    """Return combined FotMob (Opta) xG for every season in ``seasons``."""

    return _load_xg_seasons(
        "FotMob",
        _fetch_fotmob_season,
        seasons,
        cache_dir,
        refresh_current=refresh_current,
        verbose=verbose
    )


# ============================================================
# UNDERSTAT XG - BACKUP SOURCE
# ============================================================

def _fetch_understat_season(understat_season, cache_path=None):
    """Scrape one season of xG from Understat (played games only)."""

    scraper = pb.scrapers.Understat(UNDERSTAT_COMPETITION, understat_season)
    fixtures = scraper.get_fixtures()

    return (
        fixtures[["team_home", "team_away", "xg_home", "xg_away"]]
        .rename(columns={
            "team_home": "HomeTeam",
            "team_away": "AwayTeam",
            "xg_home": "HomeXG",
            "xg_away": "AwayXG"
        })
        .reset_index(drop=True)
    )


def fetch_understat_xg(
    seasons,
    cache_dir=UNDERSTAT_CACHE_DIR,
    refresh_current=True,
    verbose=False
):
    """Return combined Understat xG for every season in ``seasons``."""

    return _load_xg_seasons(
        "Understat",
        _fetch_understat_season,
        seasons,
        cache_dir,
        refresh_current=refresh_current,
        verbose=verbose
    )


# ============================================================
# MERGE
# ============================================================

def _normalise_xg(xg, alias_map, source_name):

    xg = xg.copy()

    xg["HomeTeam"] = normalize_team_names(
        xg["HomeTeam"], alias_map, source_name=source_name
    )
    xg["AwayTeam"] = normalize_team_names(
        xg["AwayTeam"], alias_map, source_name=source_name
    )

    return xg.drop_duplicates(subset=["Season", "HomeTeam", "AwayTeam"])


def merge_xg(matches, fotmob, understat, alias_map):
    """
    Left-join xG onto the match history by season + teams. FotMob (Opta)
    is used wherever it has the match; Understat fills any gaps.
    XGSource records which one each row's xG came from.
    """

    keys = ["Season", "HomeTeam", "AwayTeam"]

    fotmob = _normalise_xg(fotmob, alias_map, "FotMob")
    understat = _normalise_xg(understat, alias_map, "Understat")

    merged = (
        matches
        .merge(fotmob[XG_COLUMNS], on=keys, how="left")
        .merge(
            understat[XG_COLUMNS], on=keys, how="left",
            suffixes=("", "Understat")
        )
    )

    has_fotmob = merged["HomeXG"].notna() & merged["AwayXG"].notna()
    has_understat = (
        merged["HomeXGUnderstat"].notna() & merged["AwayXGUnderstat"].notna()
    )

    use_understat = ~has_fotmob & has_understat

    merged.loc[use_understat, "HomeXG"] = merged.loc[use_understat, "HomeXGUnderstat"]
    merged.loc[use_understat, "AwayXG"] = merged.loc[use_understat, "AwayXGUnderstat"]
    merged.loc[~has_fotmob & ~has_understat, ["HomeXG", "AwayXG"]] = float("nan")

    merged["XGSource"] = None
    merged.loc[has_fotmob, "XGSource"] = "FotMob"
    merged.loc[use_understat, "XGSource"] = "Understat"

    return merged.drop(columns=["HomeXGUnderstat", "AwayXGUnderstat"]).copy()


# ============================================================
# COVERAGE REPORT
# ============================================================

def report(matches):
    """Print xG coverage overall, by season, and list any gaps."""

    missing_mask = matches["HomeXG"].isna() | matches["AwayXG"].isna()
    missing = matches[missing_mask]
    total = len(matches)

    print()
    print("=" * 70)
    print("XG COVERAGE")
    print("=" * 70)
    print(f"Total matches:   {total}")
    print(f"Matches with xG: {total - len(missing)}")
    print(f"Missing xG:      {len(missing)}")
    print(f"Coverage:        {(total - len(missing)) / total * 100:.2f}%")

    coverage = (
        matches
        .assign(
            HasXG=~missing_mask,
            FotMob=matches["XGSource"] == "FotMob",
            Understat=matches["XGSource"] == "Understat"
        )
        .groupby("Season")
        .agg(
            Games=("HomeTeam", "size"),
            GamesWithXG=("HasXG", "sum"),
            FotMob=("FotMob", "sum"),
            Understat=("Understat", "sum")
        )
    )
    coverage["Missing"] = coverage["Games"] - coverage["GamesWithXG"]
    coverage["Coverage"] = (
        coverage["GamesWithXG"] / coverage["Games"] * 100
    ).round(2)

    print()
    print("=" * 70)
    print("XG COVERAGE BY SEASON")
    print("=" * 70)
    print(coverage)

    if len(missing) > 0:
        print()
        print("=" * 70)
        print("MISSING XG FIXTURES")
        print("=" * 70)
        print(
            missing[
                ["Season", "Date", "OriginalHomeTeam", "OriginalAwayTeam"]
            ].to_string(index=False)
        )


# ============================================================
# BUILD
# ============================================================

def build_dataset(
    raw_dir=RAW_DIR,
    output_path=OUTPUT_PATH,
    fotmob_cache_dir=FOTMOB_CACHE_DIR,
    understat_cache_dir=UNDERSTAT_CACHE_DIR,
    refresh_current=True,
    verbose=False
):
    """
    Rebuild ``data/processed/all_matches.csv`` from the raw result
    files plus FotMob (Opta) xG, with Understat filling any match
    FotMob doesn't have. Returns the resulting DataFrame.
    """

    alias_map = load_alias_map()

    matches = load_result_files(raw_dir)

    # Keep original names so the coverage report can point at gaps
    matches = matches.assign(
        OriginalHomeTeam=matches["HomeTeam"],
        OriginalAwayTeam=matches["AwayTeam"]
    )

    matches["HomeTeam"] = normalize_team_names(
        matches["HomeTeam"], alias_map, source_name="football-data.co.uk"
    )
    matches["AwayTeam"] = normalize_team_names(
        matches["AwayTeam"], alias_map, source_name="football-data.co.uk"
    )

    seasons = discover_seasons(raw_dir)

    fotmob = fetch_fotmob_xg(
        seasons,
        cache_dir=fotmob_cache_dir,
        refresh_current=refresh_current,
        verbose=verbose
    )

    understat = fetch_understat_xg(
        seasons,
        cache_dir=understat_cache_dir,
        refresh_current=refresh_current,
        verbose=verbose
    )

    matches = merge_xg(matches, fotmob, understat, alias_map)

    if verbose:
        report(matches)
    else:
        covered = (~(matches["HomeXG"].isna() | matches["AwayXG"].isna())).mean()
        backup = (matches["XGSource"] == "Understat").sum()
        print(
            f"Built {len(matches)} matches "
            f"({covered * 100:.1f}% xG coverage, "
            f"{backup} from Understat backup)"
        )

    matches = matches.drop(columns=["OriginalHomeTeam", "OriginalAwayTeam"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    matches.to_csv(output_path, index=False)

    print(f"Saved {output_path}")

    return matches


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Build data/processed/all_matches.csv from raw EPL results "
            "and FotMob xG (Understat as backup)."
        )
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full xG coverage report."
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help=(
            "Use cached FotMob/Understat data for every season, including "
            "the current one (no network calls if the caches are populated)."
        )
    )
    args = parser.parse_args()

    build_dataset(
        refresh_current=not args.no_refresh,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
