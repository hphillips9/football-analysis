import io
import time
import urllib.error
import urllib.request

import pandas as pd

import competitions
from bet_schema import ODDS_COLUMNS, add_missing_columns
from team_names import load_alias_map

SEASON_URL = "https://www.football-data.co.uk/mmz4281/{code}/{fd_uk}.csv"
LOCAL_PATH = "data/raw/{div}/results_{season}.csv"
BETS_PATH = "data/raw/Bets.csv"
KEY_COLUMNS = ["Date", "HomeTeam", "AwayTeam"]

STAKE = 1
ODDS_COLUMN = {"H": "SKBH", "D": "SKBD", "A": "SKBA"}
FALLBACK_ODDS_COLUMN = {"H": "AvgH", "D": "AvgD", "A": "AvgA"}
ODDS_SOURCES = {"SKB": ODDS_COLUMN, "Avg": FALLBACK_ODDS_COLUMN}
_OUTCOMES = ["H", "D", "A"]  # the order of ODDS_COLUMNS

# What settlement needs from a results file (MatchId where a source has one)
SETTLE_COLUMNS = [
    "MatchId", "Date", "HomeTeam", "AwayTeam", "FTR",
    *ODDS_COLUMN.values(), *FALLBACK_ODDS_COLUMN.values(),
]

# A result settles a bet if it's within this of the bet's date
SETTLE_DATE_TOLERANCE = pd.Timedelta(days=1)

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; football-analysis)"}
RETRY_DELAYS = (5, 20, 60)  # seconds between the 4 attempts


def _download_csv(url):
    """Fetch a CSV, retrying transient failures. Raises ConnectionError
    if it still can't after every attempt."""

    last_error = None

    for delay in (0, *RETRY_DELAYS):

        if delay:
            print(f"  retrying in {delay}s ...")
            time.sleep(delay)

        try:
            request = urllib.request.Request(url, headers=REQUEST_HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                return pd.read_csv(io.BytesIO(response.read()))

        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last_error = error
            print(f"  {url} -> {error}")

    raise ConnectionError(f"could not fetch {url}: {last_error}")


def season_url(div, season=None):
    """football-data.co.uk CSV for one competition's season ("26-27" -> 2627)."""

    season = season or competitions.CURRENT_SEASON
    return SEASON_URL.format(
        code=season.replace("-", ""), fd_uk=competitions.get(div)["fd_uk"]
    )


def results_path(div, season=None):
    """Local results file for one competition's season (relative to the repo root)."""

    return LOCAL_PATH.format(div=div, season=season or competitions.CURRENT_SEASON)


def fetch_all_new_results(divs=None, status=None):
    """
    fetch_new_results for every enabled competition with a
    football-data.co.uk feed. A failure skips that competition only:
    a download that fails leaves its results "stale" (the file on disk
    is used), anything else - e.g. an unknown team name - is "failed".
    Outcomes go to ``status`` (a run_status.RunStatus) when given;
    without one, raises ConnectionError at the end if any failed.
    """

    failed = []

    for div in divs or competitions.enabled():

        if competitions.get(div)["fd_uk"] is None:
            continue

        print(f"{div}:")
        try:
            fetch_new_results(div)
        except ConnectionError as exc:
            if status is None:
                failed.append(f"{div}: {exc}")
            else:
                status.fail(div, exc, results="stale")
        except Exception as exc:
            if status is None:
                raise
            status.fail(div, exc, results="failed")
        else:
            if status is not None:
                status.set(div, results="ok")

    if failed:
        raise ConnectionError("; ".join(failed))


def fetch_new_results(div="E0", season=None):

    local_path = results_path(div, season)

    remote = _download_csv(season_url(div, season))
    local = pd.read_csv(local_path)

    existing_keys = set(
        local[KEY_COLUMNS].itertuples(index=False, name=None)
    )

    remote_keys = remote[KEY_COLUMNS].apply(tuple, axis=1)

    new_rows = remote[~remote_keys.isin(existing_keys)]

    if new_rows.empty:
        print("No new results - local file is already up to date.")
        return new_rows

    alias_map = load_alias_map()

    unknown = sorted(
        (set(new_rows["HomeTeam"]) | set(new_rows["AwayTeam"]))
        - set(alias_map)
    )

    if unknown:
        raise ValueError(
            f"Unrecognised team name(s) in new results: {unknown}. "
            f"Add them to data/reference/team_names.csv before continuing."
        )

    updated = pd.concat([local, new_rows], ignore_index=True)
    updated.to_csv(local_path, index=False)

    print(f"Added {len(new_rows)} new result(s):")
    print(
        new_rows[["Date", "HomeTeam", "AwayTeam", "FTR"]]
        .to_string(index=False)
    )

    return new_rows

def settle_profit(predicted, actual, odds):

    if pd.isna(actual):
        return None

    if predicted == actual:
        return round(STAKE * (odds - 1), 2)

    return float(-STAKE)


def _load_current_results(divs=None):
    """This season's results for every enabled competition that has a file."""

    frames = []

    for div in divs or competitions.enabled():

        try:
            frame = pd.read_csv(results_path(div))
        except FileNotFoundError:
            continue

        keep = [c for c in SETTLE_COLUMNS if c in frame.columns]
        frames.append(frame[keep].assign(Div=div, Season=competitions.CURRENT_SEASON))

    results = pd.concat(frames, ignore_index=True)
    results["_day"] = pd.to_datetime(results["Date"], dayfirst=True)

    return results


def settlement_odds(match, predicted):
    """
    The H/D/A odds a pick on ``predicted`` settles at, and their source:
    Sky Bet where it priced the pick, else the market average. None if
    neither did (the bet is then unpriced).
    """

    for source, columns in ODDS_SOURCES.items():
        if pd.notna(match.get(columns[predicted])):
            return [match.get(columns[o]) for o in "HDA"], source

    return None


def find_result(bet, results, alias_map):
    """
    The result row for one bet, or None. Matched on MatchId when both
    sides have one, else on (Div, Season, HomeTeam, AwayTeam) with the
    date within a day - the nearest date wins.
    """

    if pd.notna(bet.get("MatchId")) and "MatchId" in results.columns:
        found = results[results["MatchId"].astype(str) == str(bet["MatchId"])]
        return found.iloc[0] if len(found) else None

    home = alias_map.get(bet["HomeTeam"], bet["HomeTeam"])
    away = alias_map.get(bet["AwayTeam"], bet["AwayTeam"])
    day = pd.to_datetime(bet["Date"], dayfirst=True)

    found = results[
        (results["Div"] == bet["Div"])
        & (results["Season"] == bet["Season"])
        & (results["_home"] == home)
        & (results["_away"] == away)
    ]

    gap = (found["_day"] - day).abs()
    found = found[gap <= SETTLE_DATE_TOLERANCE]

    if found.empty:
        return None

    return found.loc[gap[found.index].idxmin()]


def complete_bets(bets_path=BETS_PATH, divs=None):

    bets = add_missing_columns(pd.read_csv(bets_path))
    # All-empty columns read as float; these take text
    for column in ["ActualResult", "OddsSource"]:
        bets[column] = bets[column].astype(object)
    results = _load_current_results(divs)

    alias_map = load_alias_map()
    results["_home"] = results["HomeTeam"].replace(alias_map)
    results["_away"] = results["AwayTeam"].replace(alias_map)

    pending = bets.index[bets["ActualResult"].isna()]

    settled = []

    for i in pending:

        match = find_result(bets.loc[i], results, alias_map)

        if match is None:
            continue

        predicted = bets.at[i, "PredictedResult"]
        actual = match["FTR"]

        bets.at[i, "ActualResult"] = actual

        # Odds captured at prediction time (CL) win over the results file
        if pd.notna(bets.at[i, ODDS_COLUMNS[_OUTCOMES.index(predicted)]]):
            odds = bets.loc[i, ODDS_COLUMNS].tolist()
            source = bets.at[i, "OddsSource"]
        else:
            priced = settlement_odds(match, predicted)
            odds, source = priced if priced else ([float("nan")] * 3, pd.NA)

        bets.loc[i, ODDS_COLUMNS] = odds
        bets.at[i, "OddsSource"] = source

        pick_odds = odds[_OUTCOMES.index(predicted)]

        if pd.isna(pick_odds):
            bets.at[i, "Bet"] = 0
            bets.at[i, "Profit"] = float("nan")
        else:
            bets.at[i, "Bet"] = STAKE
            bets.at[i, "Profit"] = settle_profit(predicted, actual, pick_odds)

        settled.append(i)

    if not settled:
        print("No pending bets have results yet.")
        return bets

    bets["Bet"] = bets["Bet"].astype("Int64")
    bets["Backfilled"] = bets["Backfilled"].astype("Int64")
    bets.to_csv(bets_path, index=False)

    total = bets.loc[settled, "Profit"].astype(float).sum()
    unpriced = int((bets.loc[settled, "Bet"] == 0).sum())

    print(f"Settled {len(settled)} bet(s) ({total:+.2f} units):")
    if unpriced:
        print(f"  {unpriced} unpriced (no odds) - counted for accuracy only")
    print(
        bets.loc[
            settled,
            ["Date", "HomeTeam", "AwayTeam",
             "PredictedResult", "ActualResult", "Profit"]
        ].to_string(index=False)
    )

    return bets


if __name__ == "__main__":
    try:
        fetch_all_new_results()
    except ConnectionError as exc:
        print(f"Skipping fetch - {exc}")
    complete_bets()