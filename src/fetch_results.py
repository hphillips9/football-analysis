import io
import time
import urllib.error
import urllib.request

import pandas as pd

import competitions
from team_names import load_alias_map

SEASON_URL = "https://www.football-data.co.uk/mmz4281/{code}/{fd_uk}.csv"
LOCAL_PATH = "data/raw/{div}/results_{season}.csv"
BETS_PATH = "data/raw/Bets.csv"
KEY_COLUMNS = ["Date", "HomeTeam", "AwayTeam"]

STAKE = 1
ODDS_COLUMN = {"H": "SKBH", "D": "SKBD", "A": "SKBA"}
FALLBACK_ODDS_COLUMN = {"H": "AvgH", "D": "AvgD", "A": "AvgA"}

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


def fetch_all_new_results(divs=None):
    """
    fetch_new_results for every enabled competition with a
    football-data.co.uk feed. One failing download doesn't stop the
    others; raises ConnectionError at the end if any failed.
    """

    failed = []

    for div in divs or competitions.enabled():

        if competitions.get(div)["fd_uk"] is None:
            continue

        print(f"{div}:")
        try:
            fetch_new_results(div)
        except ConnectionError as exc:
            failed.append(f"{div}: {exc}")

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

        frames.append(frame.assign(Div=div))

    return pd.concat(frames, ignore_index=True)


def complete_bets(bets_path=BETS_PATH, divs=None):

    bets = pd.read_csv(bets_path)
    results = _load_current_results(divs)

    alias_map = load_alias_map()

    # Settled on (Div, HomeTeam, AwayTeam) - fine while each pairing
    # happens once a season per competition (see F7 for the CL)
    result_keys = zip(
        results["Div"],
        results["HomeTeam"].replace(alias_map),
        results["AwayTeam"].replace(alias_map)
    )

    results_by_fixture = {
        key: row
        for key, (_, row) in zip(result_keys, results.iterrows())
    }

    pending = bets.index[bets["ActualResult"].isna()]

    settled = []

    for i in pending:

        key = (
            bets.at[i, "Div"],
            alias_map.get(bets.at[i, "HomeTeam"], bets.at[i, "HomeTeam"]),
            alias_map.get(bets.at[i, "AwayTeam"], bets.at[i, "AwayTeam"])
        )

        match = results_by_fixture.get(key)

        if match is None:
            continue

        predicted = bets.at[i, "PredictedResult"]
        actual = match["FTR"]

        odds = match[ODDS_COLUMN[predicted]]

        if pd.isna(odds):
            odds = match[FALLBACK_ODDS_COLUMN[predicted]]

        bets.at[i, "ActualResult"] = actual
        bets.at[i, "Bet"] = STAKE
        bets.at[i, "Profit"] = settle_profit(predicted, actual, odds)

        settled.append(i)

    if not settled:
        print("No pending bets have results yet.")
        return bets

    bets["Bet"] = bets["Bet"].astype("Int64")
    bets.to_csv(bets_path, index=False)

    total = bets.loc[settled, "Profit"].sum()

    print(f"Settled {len(settled)} bet(s) ({total:+.2f} units):")
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