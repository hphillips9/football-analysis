"""
Pull the next round of every enabled competition from the
football-data.org API and write them to data/raw/Future_Fixtures.csv
for predict_next_matches.

The API key is read from the FOOTBALL_DATA_API_KEY environment variable
(a GitHub Actions secret in CI). Locally it can live in a .env file at
the repo root, which is git-ignored:

    FOOTBALL_DATA_API_KEY=your-key-here
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

import competitions
from fetch_results import results_path
from team_names import load_alias_map, normalize_team_names

API_URL = "https://api.football-data.org/v4/competitions/{fd_org}/matches"
API_KEY_VAR = "FOOTBALL_DATA_API_KEY"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

OUTPUT_PATH = "data/raw/Future_Fixtures.csv"
BETS_PATH = "data/raw/Bets.csv"

UK_TIMEZONE = "Europe/London"
UPCOMING_STATUSES = {"SCHEDULED", "TIMED"}
# Not finished yet, but kicked off or about to (POSTPONED etc. excluded)
UNPLAYED_STATUSES = UPCOMING_STATUSES | {"IN_PLAY", "PAUSED"}

# A matchday with at least this many unplayed games is a proper round;
# fewer means stragglers (rearranged games from an earlier round)
MIN_ROUND_SIZE = 5

RETRY_DELAYS = (5, 20, 60)  # seconds between the 4 attempts

# Free tier allows 10 requests a minute
REQUEST_GAP = 6.5  # seconds between competitions

FRAME_COLUMNS = [
    "Gameweek", "Status", "Kickoff", "Div", "Date", "Time", "HomeTeam", "AwayTeam",
]


def api_key():
    """The football-data.org key from the environment or .env, else None."""

    key = os.environ.get(API_KEY_VAR)

    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == API_KEY_VAR:
                key = value.strip().strip("\"'")

    return key or None


def _get_matches(key, div):
    """Every match of ``div``'s current season, retrying transient
    failures. Raises ConnectionError if it still can't after every attempt."""

    url = API_URL.format(fd_org=competitions.get(div)["fd_org"])
    last_error = None

    for delay in (0, *RETRY_DELAYS):

        if delay:
            print(f"  retrying in {delay}s ...")
            time.sleep(delay)

        try:
            request = urllib.request.Request(url, headers={"X-Auth-Token": key})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)["matches"]

        except urllib.error.HTTPError as error:
            last_error = error
            print(f"  football-data.org -> {error}")
            # A bad key won't fix itself; rate limits (429) and 5xx might
            if error.code in (400, 401, 403, 404):
                break

        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last_error = error
            print(f"  football-data.org -> {error}")

    raise ConnectionError(f"could not fetch {div} fixtures: {last_error}")


def _to_frame(matches, div):

    rows = []

    for match in matches:

        kickoff = pd.Timestamp(match["utcDate"]).tz_convert(UK_TIMEZONE)

        rows.append({
            "Gameweek": match["matchday"],
            "Status": match["status"],
            "Kickoff": kickoff,
            "Div": div,
            "Date": kickoff.strftime("%d/%m/%Y"),
            "Time": kickoff.strftime("%H:%M"),
            "HomeTeam": match["homeTeam"]["name"],
            "AwayTeam": match["awayTeam"]["name"],
        })

    return pd.DataFrame(rows, columns=FRAME_COLUMNS)


def _already_bet(fixtures, bets_path):

    try:
        bets = pd.read_csv(bets_path)
    except FileNotFoundError:
        return pd.Series(False, index=fixtures.index)

    key = ["Div", "Date", "HomeTeam", "AwayTeam"]
    recorded = set(map(tuple, bets[key].replace(load_alias_map()).to_numpy()))

    return pd.Series(
        [tuple(row) in recorded for row in fixtures[key].to_numpy()],
        index=fixtures.index,
    )


def select_next_round(upcoming):
    """
    The earliest matchday with a full-ish round still to predict, plus
    any rearranged stragglers from earlier matchdays that kick off before
    that round finishes. Each keeps its own matchday as its Gameweek.
    """

    sizes = upcoming["Gameweek"].value_counts()
    rounds = sorted(sizes[sizes >= MIN_ROUND_SIZE].index)

    if not rounds:
        return upcoming

    next_round = rounds[0]
    round_end = upcoming.loc[upcoming["Gameweek"] == next_round, "Kickoff"].max()

    return upcoming[
        (upcoming["Gameweek"] == next_round)
        | ((upcoming["Gameweek"] < next_round) & (upcoming["Kickoff"] <= round_end))
    ]


def next_round(fixtures, bets_path=BETS_PATH):
    """
    One competition's next round of unpredicted fixtures, or None when
    there's nothing to predict yet - either a round we've already bet on
    is still being played, every upcoming round is already in Bets.csv,
    or the last round's results haven't all reached the results file
    (predicting then would use stale Elo / form).

    ``fixtures`` is the whole season for one Div, with normalised names.
    Each competition waits only on its own rounds.
    """

    div = fixtures["Div"].iloc[0]
    path = results_path(div)

    finished = (fixtures["Status"] == "FINISHED").sum()
    on_file = len(pd.read_csv(path))

    if on_file < finished:
        print(
            f"{div}: football-data.org lists {finished} finished match(es) but "
            f"{path} only has {on_file} - waiting for the results "
            f"before predicting."
        )
        return None

    # Only one round in play at a time: wait until every fixture we've
    # bet on is finished. A rearranged game gets a new date, so its old
    # bet no longer matches and it can't block forever.
    unplayed = fixtures[fixtures["Status"].isin(UNPLAYED_STATUSES)]
    in_progress = unplayed[_already_bet(unplayed, bets_path)]

    if not in_progress.empty:
        rounds = ", ".join(f"GW{gw}" for gw in sorted(in_progress["Gameweek"].unique()))
        print(
            f"{div}: {len(in_progress)} bet fixture(s) from {rounds} still to be "
            f"played - waiting before predicting the next round."
        )
        return None

    upcoming = fixtures[fixtures["Status"].isin(UPCOMING_STATUSES)]
    upcoming = upcoming[~_already_bet(upcoming, bets_path)]

    if upcoming.empty:
        print(f"{div}: every upcoming fixture already has a bet - nothing to predict.")
        return None

    return select_next_round(upcoming)


def _competition_round(key, div, alias_map, bets_path):
    """One competition's next round (see next_round), or None."""

    fixtures = _to_frame(_get_matches(key, div), div)

    if fixtures.empty:
        print(f"{div}: football-data.org returned no matches.")
        return None

    for side in ["HomeTeam", "AwayTeam"]:
        fixtures[side] = normalize_team_names(
            fixtures[side], alias_map, source_name="football-data.org"
        )

    return next_round(fixtures, bets_path)


def fetch_next_fixtures(output_path=OUTPUT_PATH, bets_path=BETS_PATH, divs=None, status=None):
    """
    Write the next round of every enabled competition (see next_round)
    to ``output_path``. Returns the fixtures, or None when no
    competition has anything to predict yet.

    With ``status`` (a run_status.RunStatus), a competition that fails -
    an outage or an unknown team name - is recorded there and skipped,
    and the others carry on. Without one, the failure is raised.
    """

    key = api_key()
    if key is None:
        raise RuntimeError(f"{API_KEY_VAR} is not set (environment or .env)")

    alias_map = load_alias_map()
    rounds = []

    for n, div in enumerate(divs or competitions.enabled()):

        if n:
            time.sleep(REQUEST_GAP)

        try:
            future = _competition_round(key, div, alias_map, bets_path)
        except Exception as exc:
            if status is None:
                raise
            status.fail(div, exc)
            continue

        if future is not None:
            rounds.append(future)

    if not rounds:
        return None

    future = (
        pd.concat(rounds)
        .sort_values(["Kickoff", "HomeTeam"])
        [["Gameweek", "Div", "Date", "Time", "HomeTeam", "AwayTeam"]]
    )

    future.to_csv(output_path, index=False)

    print(f"Wrote {len(future)} fixture(s) to {output_path}:")
    print(future.to_string(index=False))

    return future


if __name__ == "__main__":
    fetch_next_fixtures()
