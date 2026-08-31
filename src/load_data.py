import os
import re
import glob
import argparse
import warnings
from pathlib import Path

import pandas as pd
import penaltyblog as pb

from team_names import load_alias_map, normalize_team_names

# The football-data result files carry ~200 bookmaker-odds columns, so
# pandas warns every time we add one more. The width is expected here.
warnings.simplefilter("ignore", pd.errors.PerformanceWarning)


# ============================================================
# PATHS / CONFIG
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = ROOT / "data" / "raw"
UNDERSTAT_CACHE_DIR = RAW_DIR / "understat"
OUTPUT_PATH = ROOT / "data" / "processed" / "all_matches.csv"

UNDERSTAT_COMPETITION = "ENG Premier League"

# EPL25-26.csv -> ("25", "26")
SEASON_FILE_RE = re.compile(r"EPL(\d{2})-(\d{2})\.csv$", re.IGNORECASE)

UNDERSTAT_COLUMNS = ["Season", "HomeTeam", "AwayTeam", "HomeXG", "AwayXG"]


# ============================================================
# SEASON DISCOVERY
# ============================================================

def discover_seasons(raw_dir=RAW_DIR):
    """
    Map season label -> Understat season string, derived from the
    EPL*.csv result files that are actually present.

        {"21-22": "2021-2022", ..., "26-27": "2026-2027"}

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
    sorted frame with a Season column and a MatchDateTime column.
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

    return (
        matches
        .sort_values("MatchDateTime")
        .reset_index(drop=True)
        .copy()
    )


# ============================================================
# UNDERSTAT XG - WITH PER-SEASON CACHING
# ============================================================

def _fetch_understat_season(understat_season):
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
    """
    Return combined Understat xG for every season in ``seasons``.

    Historical seasons never change, so they are scraped once and then
    read from ``cache_dir``. The current (last) season is re-scraped on
    every run unless ``refresh_current`` is False. A failed scrape falls
    back to the cached copy when one exists.
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
                season_df = _fetch_understat_season(seasons[label])
                season_df.to_csv(cache_path, index=False)

                if verbose:
                    print(
                        f"Fetched Understat {label} "
                        f"({len(season_df)} games) -> {cache_path.name}"
                    )

            except Exception as exc:

                if cache_path.exists():
                    print(
                        f"WARNING: Understat fetch failed for {label} "
                        f"({exc}); using cached copy."
                    )
                    season_df = pd.read_csv(cache_path)
                else:
                    print(
                        f"WARNING: Understat fetch failed for {label} "
                        f"({exc}); no cache available, skipping xG for "
                        f"this season."
                    )
                    continue

        else:
            season_df = pd.read_csv(cache_path)

            if verbose:
                print(
                    f"Loaded Understat {label} from cache "
                    f"({len(season_df)} games)"
                )

        season_df = season_df.copy()
        season_df.insert(0, "Season", label)
        frames.append(season_df)

    if not frames:
        return pd.DataFrame(columns=UNDERSTAT_COLUMNS)

    understat = pd.concat(frames, ignore_index=True)

    return understat.drop_duplicates(
        subset=["Season", "HomeTeam", "AwayTeam"]
    )


# ============================================================
# MERGE
# ============================================================

def merge_xg(matches, understat, alias_map):
    """Left-join Understat xG onto the match history by season + teams."""

    understat = understat.copy()

    understat["HomeTeam"] = normalize_team_names(
        understat["HomeTeam"], alias_map, source_name="Understat"
    )
    understat["AwayTeam"] = normalize_team_names(
        understat["AwayTeam"], alias_map, source_name="Understat"
    )

    understat = understat.drop_duplicates(
        subset=["Season", "HomeTeam", "AwayTeam"]
    )

    return matches.merge(
        understat[UNDERSTAT_COLUMNS],
        on=["Season", "HomeTeam", "AwayTeam"],
        how="left"
    ).copy()


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
        .assign(HasXG=~missing_mask)
        .groupby("Season")
        .agg(
            Games=("HomeTeam", "size"),
            GamesWithXG=("HasXG", "sum")
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
    cache_dir=UNDERSTAT_CACHE_DIR,
    refresh_current=True,
    verbose=False
):
    """
    Rebuild ``data/processed/all_matches.csv`` from the raw result
    files plus Understat xG. Returns the resulting DataFrame.
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

    understat = fetch_understat_xg(
        seasons,
        cache_dir=cache_dir,
        refresh_current=refresh_current,
        verbose=verbose
    )

    matches = merge_xg(matches, understat, alias_map)

    if verbose:
        report(matches)
    else:
        covered = (~(matches["HomeXG"].isna() | matches["AwayXG"].isna())).mean()
        print(
            f"Built {len(matches)} matches "
            f"({covered * 100:.1f}% xG coverage)"
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
            "and Understat xG."
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
            "Use cached Understat data for every season, including the "
            "current one (no network calls if the cache is populated)."
        )
    )
    args = parser.parse_args()

    build_dataset(
        refresh_current=not args.no_refresh,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
