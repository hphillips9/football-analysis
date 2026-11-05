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

import competitions
from team_names import load_alias_map, normalize_team_names

# The football-data result files carry ~200 bookmaker-odds columns, so
# pandas warns every time we add one more. The width is expected here.
warnings.simplefilter("ignore", pd.errors.PerformanceWarning)


# ============================================================
# PATHS / CONFIG
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

# Each competition keeps its files in data/raw/<Div>/:
#   results_<yy-yy>.csv    football-data.co.uk results + odds
#   fotmob_<yy-yy>.csv     FotMob xG cache
#   understat_<yy-yy>.csv  Understat xG cache (top 5 leagues only)
RAW_DIR = ROOT / "data" / "raw"
OUTPUT_PATH = ROOT / "data" / "processed" / "all_matches.csv"

# FotMob's xG is Opta's - the same numbers BBC and Sky show. League ids
# and Understat names come from competitions.py.
FOTMOB_API = "https://www.fotmob.com/api/data"
FOTMOB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}
FOTMOB_DELAY = 1.0  # seconds between match requests (keep it serial)
# FotMob rate-limits (HTTP 429) when pushed. Wait this long, doubling
# each time, before retrying; give up after FOTMOB_MAX_RETRIES.
FOTMOB_BACKOFF = 5
FOTMOB_MAX_RETRIES = 5
# Opta revises xG for a day or two after full time, so matches this
# recent are re-fetched on every refresh rather than kept from the cache
FOTMOB_REFETCH_DAYS = 3
FOTMOB_CACHE_COLUMNS = [
    "MatchId", "Date", "HomeTeam", "AwayTeam", "HomeXG", "AwayXG"
]
# Save progress this often during a long scrape, so a crash mid-backfill
# doesn't lose everything fetched so far
FOTMOB_CHECKPOINT_EVERY = 50

# results_25-26.csv -> ("25", "26")
SEASON_FILE_RE = re.compile(r"results_(\d{2})-(\d{2})\.csv$", re.IGNORECASE)

XG_COLUMNS = ["Div", "Season", "HomeTeam", "AwayTeam", "HomeXG", "AwayXG"]

# Where each match's xG comes from, first choice first (XGSource).
# football-data.co.uk's HxG/AxG (2026-27 on) is the same Opta data as
# FotMob's but frozen when first published, while FotMob is re-fetched
# until Opta's revisions settle (FOTMOB_REFETCH_DAYS) - so FotMob wins
# where it has the match and football-data fills the gaps.
XG_PRIORITY = ["FotMob", "football-data", "Understat"]


def competition_dir(div, raw_dir=RAW_DIR):
    """data/raw/<Div>/ - where one competition's raw files live."""

    return raw_dir / div


# ============================================================
# SEASON DISCOVERY
# ============================================================

def discover_seasons(div="E0", raw_dir=RAW_DIR):
    """
    Map season label -> full season string, derived from the
    results_*.csv files actually present for competition ``div``.

        {"21-22": "2021-2022", ..., "26-27": "2026-2027"}

    Understat takes the string as is; FotMob wants "2021/2022".

    Insertion order is chronological, so the last entry is the
    current season.
    """

    seasons = {}

    for path in sorted(glob.glob(str(competition_dir(div, raw_dir) / "results_*.csv"))):

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

def load_result_files(divs=None, raw_dir=RAW_DIR):
    """
    Concatenate every results_*.csv file of each competition in ``divs``
    (default: the enabled ones) into one chronologically sorted frame
    with Season, Gameweek and MatchDateTime columns.
    """

    frames = []

    for div in divs or competitions.enabled():

        for path in sorted(glob.glob(str(competition_dir(div, raw_dir) / "results_*.csv"))):

            match = SEASON_FILE_RE.search(os.path.basename(path))

            if not match:
                continue

            label = f"{match.group(1)}-{match.group(2)}"

            df = pd.read_csv(path)

            # football-data.co.uk files carry their own Div column
            if "Div" not in df.columns:
                df.insert(0, "Div", div)

            frames.append(df.assign(Season=label))

    if not frames:
        raise FileNotFoundError(
            f"No results_*.csv files found under {raw_dir} for {divs or competitions.enabled()}"
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
    played that season in that competition. The two sides of a fixture
    normally agree; where a postponement makes them differ, take the
    larger so a rescheduled game carries the number of when it was
    actually played. Cup competitions have no gameweek.
    """

    matches = (
        matches
        .sort_values(["MatchDateTime", "HomeTeam", "AwayTeam"])
        .reset_index(drop=True)
        .copy()
    )

    # Without a Div column (an old single-league frame) treat it all as one
    div = matches["Div"] if "Div" in matches.columns else pd.Series("", index=matches.index)

    # One row per team appearance, in chronological order, so a running
    # count per team spans both home and away games
    appearances = pd.concat([
        pd.DataFrame({
            "match": matches.index,
            "Div": div,
            "Season": matches["Season"],
            "Team": matches["HomeTeam"],
            "side": "home",
        }),
        pd.DataFrame({
            "match": matches.index,
            "Div": div,
            "Season": matches["Season"],
            "Team": matches["AwayTeam"],
            "side": "away",
        }),
    ]).sort_values("match")

    appearances["n"] = (
        appearances.groupby(["Div", "Season", "Team"]).cumcount() + 1
    )

    home_n = appearances[appearances["side"] == "home"].set_index("match")["n"]
    away_n = appearances[appearances["side"] == "away"].set_index("match")["n"]

    gameweek = pd.concat([home_n, away_n], axis=1).max(axis=1)

    # Codes not in the registry (e.g. E1 in notebook 19) count as leagues
    is_cup = div.map(
        lambda d: competitions.COMPETITIONS.get(d, {}).get("kind") == "cup"
    )

    if is_cup.any():
        matches["Gameweek"] = gameweek.astype("Int64").mask(is_cup)
    else:
        matches["Gameweek"] = gameweek.astype(int)

    lead = ["Season", "Gameweek"]
    return matches[lead + [c for c in matches.columns if c not in lead]]


# ============================================================
# PER-SEASON XG CACHE
# ============================================================

def _load_xg_seasons(
    source,
    fetch_season,
    div,
    seasons,
    cache_dir,
    refresh_current=True,
    verbose=False
):
    """
    Return combined xG from one source for every season in ``seasons``
    of competition ``div``.

    ``fetch_season(season, cache_path)`` scrapes one season (it may read
    ``cache_path`` to fetch only what is new). Historical seasons never
    change, so they are scraped once and then read from
    ``cache_dir/<source>_<season>.csv``. The current (last) season is
    re-scraped on every run unless ``refresh_current`` is False. A failed
    scrape falls back to the cached copy when one exists.
    """

    cache_dir.mkdir(parents=True, exist_ok=True)

    labels = list(seasons)
    current_label = labels[-1] if labels else None

    frames = []

    for label in labels:

        cache_path = cache_dir / f"{source.lower()}_{label}.csv"
        is_current = label == current_label

        want_fresh = (is_current and refresh_current) or not cache_path.exists()

        if want_fresh:

            try:
                season_df = fetch_season(seasons[label], cache_path)
                season_df.to_csv(cache_path, index=False)

                if verbose:
                    print(
                        f"Fetched {source} {div} {label} "
                        f"({len(season_df)} games) -> {cache_path.name}"
                    )

            except Exception as exc:

                if cache_path.exists():
                    print(
                        f"WARNING: {source} fetch failed for {div} {label} "
                        f"({exc}); using cached copy."
                    )
                    season_df = pd.read_csv(cache_path)
                else:
                    print(
                        f"WARNING: {source} fetch failed for {div} {label} "
                        f"({exc}); no cache available, skipping its xG "
                        f"for this season."
                    )
                    continue

        else:
            season_df = pd.read_csv(cache_path)

            if verbose:
                print(
                    f"Loaded {source} {div} {label} from cache "
                    f"({len(season_df)} games)"
                )

        season_df = season_df[["HomeTeam", "AwayTeam", "HomeXG", "AwayXG"]].copy()
        season_df.insert(0, "Season", label)
        season_df.insert(0, "Div", div)
        frames.append(season_df)

    if not frames:
        return pd.DataFrame(columns=XG_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)

    return combined.drop_duplicates(
        subset=["Div", "Season", "HomeTeam", "AwayTeam"]
    )


# ============================================================
# FOTMOB (OPTA) XG - PRIMARY SOURCE
# ============================================================

def _fotmob_get(session, endpoint, params):
    """GET one FotMob endpoint, backing off exponentially on HTTP 429."""

    for attempt in range(FOTMOB_MAX_RETRIES + 1):

        response = session.get(
            f"{FOTMOB_API}/{endpoint}", params=params, timeout=30
        )

        if response.status_code != 429 or attempt == FOTMOB_MAX_RETRIES:
            break

        wait = FOTMOB_BACKOFF * 2 ** attempt
        print(f"FotMob rate limit (429) on {endpoint}; waiting {wait}s")
        time.sleep(wait)

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


def _fetch_fotmob_season(season, cache_path, league_id):
    """
    Scrape one season of FotMob xG (finished games only) for FotMob
    league ``league_id``.

    Matches already in ``cache_path`` with xG are kept as they are, so a
    weekly refresh only requests the newly played round (plus anything
    from the last FOTMOB_REFETCH_DAYS, to pick up Opta's revisions). A
    match that fails or has no xG yet is left out and retried on the
    next run. Progress is saved to ``cache_path`` every
    FOTMOB_CHECKPOINT_EVERY matches.
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
        {"id": league_id, "season": season.replace("-", "/")}
    )

    # The Eredivisie lists its end-of-season European play-offs as rounds
    # "1/2" and "final"; football-data.co.uk doesn't, so skip non-numeric
    # rounds rather than spend requests on matches that never join
    finished = [
        m for m in league["fixtures"]["allMatches"]
        if m["status"].get("finished") and not m["status"].get("cancelled")
        and str(m.get("round", "")).isdigit()
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

        if len(rows) % FOTMOB_CHECKPOINT_EVERY == 0:
            pd.concat(
                [cached, pd.DataFrame(rows)], ignore_index=True
            )[FOTMOB_CACHE_COLUMNS].to_csv(cache_path, index=False)

    if not rows:
        return cached[FOTMOB_CACHE_COLUMNS]

    return pd.concat(
        [cached, pd.DataFrame(rows)], ignore_index=True
    )[FOTMOB_CACHE_COLUMNS]


def fetch_fotmob_xg(
    div,
    seasons,
    raw_dir=RAW_DIR,
    refresh_current=True,
    verbose=False
):
    """
    Return combined FotMob (Opta) xG for every season in ``seasons`` of
    competition ``div`` (empty if FotMob has no id for it).
    """

    league_id = competitions.get(div)["fotmob"]

    if league_id is None:
        return pd.DataFrame(columns=XG_COLUMNS)

    return _load_xg_seasons(
        "FotMob",
        lambda season, cache_path: _fetch_fotmob_season(season, cache_path, league_id),
        div,
        seasons,
        competition_dir(div, raw_dir),
        refresh_current=refresh_current,
        verbose=verbose
    )


# ============================================================
# UNDERSTAT XG - BACKUP SOURCE
# ============================================================

def _fetch_understat_season(understat_season, competition):
    """Scrape one season of xG from Understat (played games only)."""

    scraper = pb.scrapers.Understat(competition, understat_season)
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
    div,
    seasons,
    raw_dir=RAW_DIR,
    refresh_current=True,
    verbose=False
):
    """
    Return combined Understat xG for every season in ``seasons`` of
    competition ``div`` (empty if Understat doesn't cover it).
    """

    competition = competitions.get(div)["understat"]

    if competition is None:
        return pd.DataFrame(columns=XG_COLUMNS)

    return _load_xg_seasons(
        "Understat",
        lambda season, cache_path: _fetch_understat_season(season, competition),
        div,
        seasons,
        competition_dir(div, raw_dir),
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

    return xg.drop_duplicates(subset=["Div", "Season", "HomeTeam", "AwayTeam"])


def merge_xg(matches, fotmob, understat, alias_map):
    """
    Left-join xG onto the match history by competition, season and
    teams. Each row takes its xG from the first source in XG_PRIORITY
    that has both sides of it: FotMob, then football-data.co.uk's own
    HxG/AxG columns (where the results file has them), then Understat.
    XGSource records which one was used.
    """

    keys = ["Div", "Season", "HomeTeam", "AwayTeam"]

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

    # Source -> its (home, away) columns in ``merged``
    candidates = {
        "FotMob": ("HomeXG", "AwayXG"),
        "Understat": ("HomeXGUnderstat", "AwayXGUnderstat"),
    }
    if {"HxG", "AxG"} <= set(merged.columns):
        candidates["football-data"] = ("HxG", "AxG")

    home = pd.Series(float("nan"), index=merged.index)
    away = pd.Series(float("nan"), index=merged.index)
    source = pd.Series([None] * len(merged), index=merged.index, dtype=object)

    for name in XG_PRIORITY:

        if name not in candidates:
            continue

        home_col, away_col = candidates[name]
        use = (
            source.isna()
            & merged[home_col].notna()
            & merged[away_col].notna()
        )

        home[use] = merged.loc[use, home_col]
        away[use] = merged.loc[use, away_col]
        source[use] = name

    merged["HomeXG"] = home
    merged["AwayXG"] = away
    merged["XGSource"] = source

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
            FootballData=matches["XGSource"] == "football-data",
            Understat=matches["XGSource"] == "Understat"
        )
        .groupby(["Div", "Season"])
        .agg(
            Games=("HomeTeam", "size"),
            GamesWithXG=("HasXG", "sum"),
            FotMob=("FotMob", "sum"),
            FootballData=("FootballData", "sum"),
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
    print(coverage.to_string())

    if len(missing) > 0:
        print()
        print("=" * 70)
        print("MISSING XG FIXTURES")
        print("=" * 70)
        print(
            missing[
                ["Div", "Season", "Date", "OriginalHomeTeam", "OriginalAwayTeam"]
            ].to_string(index=False)
        )


# ============================================================
# BUILD
# ============================================================

def _build_competition(div, alias_map, raw_dir, refresh_current, verbose):
    """One competition's results with xG merged on (see build_dataset)."""

    matches = load_result_files([div], raw_dir)

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

    seasons = discover_seasons(div, raw_dir)

    fotmob = fetch_fotmob_xg(
        div,
        seasons,
        raw_dir=raw_dir,
        refresh_current=refresh_current,
        verbose=verbose
    )

    understat = fetch_understat_xg(
        div,
        seasons,
        raw_dir=raw_dir,
        refresh_current=refresh_current,
        verbose=verbose
    )

    return merge_xg(matches, fotmob, understat, alias_map)


def build_dataset(
    divs=None,
    raw_dir=RAW_DIR,
    output_path=OUTPUT_PATH,
    refresh_current=True,
    verbose=False,
    status=None
):
    """
    Rebuild ``data/processed/all_matches.csv`` from the raw result
    files of each competition in ``divs`` (default: the enabled ones)
    plus xG from FotMob (Opta), football-data.co.uk or Understat, in
    that order of preference. Returns the resulting DataFrame.

    Each competition is built on its own: one that fails (an unknown
    team name, a missing results file) is left out and the rest still
    build. Each one's xG outcome goes to ``status`` (a
    run_status.RunStatus) when given. Raises RuntimeError if none built.
    """

    divs = divs or competitions.enabled()

    alias_map = load_alias_map()

    frames = []

    for div in divs:

        try:
            built = _build_competition(div, alias_map, raw_dir, refresh_current, verbose)
        except Exception as exc:
            if status is None:
                print(f"{div}: FAILED - {type(exc).__name__}: {exc}; left out of the dataset.")
            else:
                status.fail(div, exc, xg="failed")
            continue

        if status is not None:
            complete = (built["HomeXG"].notna() & built["AwayXG"].notna()).all()
            status.set(div, xg="ok" if complete else "partial")

        frames.append(built)

    if not frames:
        raise RuntimeError(f"No competition could be built ({', '.join(divs)}).")

    matches = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["MatchDateTime", "HomeTeam", "AwayTeam"])
        .reset_index(drop=True)
    )

    if verbose:
        report(matches)
    else:
        covered = (~(matches["HomeXG"].isna() | matches["AwayXG"].isna())).mean()
        backup = (matches["XGSource"] != "FotMob").sum()
        print(
            f"Built {len(matches)} matches "
            f"({covered * 100:.1f}% xG coverage, "
            f"{backup} from football-data/Understat backup)"
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
            "Build data/processed/all_matches.csv from the enabled "
            "competitions' results and xG (FotMob, then football-data.co.uk, "
            "then Understat)."
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
    parser.add_argument(
        "--divs",
        nargs="+",
        metavar="DIV",
        help="Competitions to build (default: competitions.ENABLED)."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Where to write the dataset (default: {OUTPUT_PATH.relative_to(ROOT)})."
    )
    args = parser.parse_args()

    for div in args.divs or []:
        competitions.get(div)

    build_dataset(
        divs=args.divs,
        output_path=args.output,
        refresh_current=not args.no_refresh,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
