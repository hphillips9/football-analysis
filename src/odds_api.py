"""
Champions League odds from The Odds API (plan §4B.10, D2), captured onto
the bets before kickoff so they settle at a real price.

football-data.co.uk has no CL odds, so each run, if any CL bet is still
pending, unpriced and not yet kicked off, this makes ONE call to
The Odds API (h2h, UK region: 1 credit of the free tier's 500 a month)
and writes onto each matched bet:

    OddsH/D/A    Sky Bet's price where Sky Bet lists the match, else the
                 median of the UK bookmakers (exchanges left out)
    OddsSource   "SKB" or "UKMed"

A bet is priced once, at the first run after it is predicted (normally
the same run), and keeps that price - complete_bets settles against it.
Bets that miss out (no key, the match not listed, kicked off already)
stay unpriced: Bet = 0, counted for accuracy only.

Every captured price is logged with its time to data/raw/<Div>/odds_<season>.csv
(the going-forward bookmaker benchmark), and every call's credit usage
to data/raw/odds_api_usage.csv.

The key is read from ODDS_API_KEY (environment, or .env at the repo root;
a GitHub Actions secret in CI). Without one, nothing is called.
"""

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import pandas as pd

from bet_schema import ODDS_COLUMNS, add_missing_columns, write_bets
from fetch_fixtures import api_key
from load_data import RAW_DIR, competition_dir

API_KEY_VAR = "ODDS_API_KEY"
API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
BETS_PATH = "data/raw/Bets.csv"
USAGE_PATH = RAW_DIR / "odds_api_usage.csv"

# Competitions priced from The Odds API: Div -> its sport key
SPORTS = {"CL": "soccer_uefa_champs_league"}

PREFERRED_BOOKMAKER = "skybet"
# Betting exchanges: no bookmaker margin, but commission isn't in the price
EXCHANGES = {"betfair_ex_uk", "matchbook", "smarkets"}

SOURCE_PREFERRED = "SKB"
SOURCE_MEDIAN = "UKMed"

UK_TIMEZONE = ZoneInfo("Europe/London")

# Words that tell clubs nothing apart ("FK Viking" = "Viking")
_FILLER = {
    "fc", "fk", "sk", "ac", "as", "afc", "cf", "sc", "ssc", "rc", "cd", "ud",
    "sv", "bk", "if", "nk", "club", "calcio", "de",
}
# Both sides must look like the same clubs, and clearly beat the next event
MIN_SIDE_SCORE = 0.5
MIN_MARGIN = 0.3

LOG_COLUMNS = [
    "CapturedAt", "Div", "MatchId", "Date", "Time", "HomeTeam", "AwayTeam",
    "ApiHome", "ApiAway", "OddsH", "OddsD", "OddsA", "OddsSource", "Bookmakers",
]
USAGE_COLUMNS = [
    "CalledAt", "Div", "Events", "Priced", "CreditsLast", "CreditsUsed", "CreditsRemaining",
]


# ============================================================
# API
# ============================================================

def fetch_odds(key, sport):
    """
    One h2h call for ``sport`` (UK bookmakers, decimal odds): the events
    and the credit headers {"last", "used", "remaining"}.
    """

    query = urllib.parse.urlencode({
        "apiKey": key, "regions": "uk", "markets": "h2h",
        "oddsFormat": "decimal", "dateFormat": "iso",
    })

    request = urllib.request.Request(
        f"{API_URL.format(sport=sport)}?{query}",
        headers={"User-Agent": "football-analysis-pipeline"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            events = json.load(response)
            headers = response.headers
    except urllib.error.HTTPError as exc:
        # The key is in the URL - never echo it
        raise ConnectionError(f"The Odds API returned HTTP {exc.code} for {sport}") from None
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Couldn't reach The Odds API ({exc.reason})") from None

    credits = {
        name: headers.get(f"x-requests-{name}")
        for name in ("last", "used", "remaining")
    }

    return events, credits


# ============================================================
# PRICES
# ============================================================

def _h2h(bookmaker, home, away):
    """A bookmaker's [home, draw, away] price, or None if incomplete."""

    for market in bookmaker.get("markets", []):
        if market.get("key") != "h2h":
            continue
        prices = {o["name"]: o["price"] for o in market.get("outcomes", [])}
        odds = [prices.get(home), prices.get("Draw"), prices.get(away)]
        if all(isinstance(p, (int, float)) and p > 1 for p in odds):
            return [float(p) for p in odds]

    return None


def event_odds(event):
    """
    ([H, D, A], source, bookmakers) for one event: Sky Bet's price if
    listed, else the median of the UK bookmakers per outcome. None when
    no bookmaker prices all three outcomes.
    """

    home, away = event["home_team"], event["away_team"]

    books = {
        b["key"]: odds
        for b in event.get("bookmakers", [])
        if b["key"] not in EXCHANGES and (odds := _h2h(b, home, away))
    }

    if not books:
        return None

    if PREFERRED_BOOKMAKER in books:
        return books[PREFERRED_BOOKMAKER], SOURCE_PREFERRED, len(books)

    prices = [round(median(column), 2) for column in zip(*books.values())]

    return prices, SOURCE_MEDIAN, len(books)


# ============================================================
# MATCHING EVENTS TO BETS
# ============================================================

def _tokens(name):
    """Lower-case ASCII words of a club name, filler words dropped."""

    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()

    return [w for w in words if w not in _FILLER] or words


def name_score(a, b):
    """
    How alike two club names are, 0-1: the better of shared words
    ("Inter" in "Inter Milan") and spelling ("München" ~ "Munich").
    """

    ta, tb = _tokens(a), _tokens(b)

    if not ta or not tb:
        return 0.0

    shared = len(set(ta) & set(tb)) / min(len(set(ta)), len(set(tb)))
    spelling = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()

    return max(shared, spelling)


def kickoff_utc(date, time):
    """A bet's dd/mm/yyyy + HH:MM UK kickoff as a UTC datetime."""

    time = time if isinstance(time, str) and time else "00:00"
    local = datetime.strptime(f"{date} {time}", "%d/%m/%Y %H:%M")

    return local.replace(tzinfo=UK_TIMEZONE).astimezone(timezone.utc)


def _event_uk_date(event):

    start = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))

    return start.astimezone(UK_TIMEZONE).strftime("%d/%m/%Y")


def match_events(bets, events):
    """
    {bet index: event} for the bets whose match The Odds API lists: same
    UK date, both clubs alike, and clearly the best event on that date.
    Each event goes to one bet at most.
    """

    by_date = {}
    for event in events:
        by_date.setdefault(_event_uk_date(event), []).append(event)

    matched, used = {}, set()

    for i, bet in bets.iterrows():

        scored = []
        for event in by_date.get(bet["Date"], []):
            home = name_score(bet["HomeTeam"], event["home_team"])
            away = name_score(bet["AwayTeam"], event["away_team"])
            scored.append((home + away, min(home, away), event))

        scored.sort(key=lambda s: s[0], reverse=True)

        if not scored:
            continue

        total, weakest, event = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0

        if weakest < MIN_SIDE_SCORE or total - runner_up < MIN_MARGIN:
            print(f"  No confident odds match for {bet['HomeTeam']} v {bet['AwayTeam']}")
            continue

        if event["id"] in used:
            continue

        used.add(event["id"])
        matched[i] = event

    return matched


# ============================================================
# PRICING THE BETS
# ============================================================

def unpriced_upcoming(bets, div, now):
    """Indexes of ``div``'s pending, unpriced bets that haven't kicked off."""

    pending = bets[
        (bets["Div"] == div)
        & bets["ActualResult"].isna()
        & bets[ODDS_COLUMNS].isna().all(axis=1)
    ]

    return [
        i for i, bet in pending.iterrows()
        if kickoff_utc(bet["Date"], bet["Time"]) > now
    ]


def _append_csv(rows, columns, path):

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(rows, columns=columns).to_csv(
        path, mode="a", header=not path.exists(), index=False
    )


def price_bets(bets_path=BETS_PATH, divs=None, key=None, now=None, fetch=fetch_odds,
               raw_dir=RAW_DIR, usage_path=USAGE_PATH):
    """
    Capture odds onto the pending, unpriced, upcoming bets of each
    competition in SPORTS (and ``divs``, if given). One API call per
    competition that has such bets; none at all without a key.

    Returns {div: bets priced}.
    """

    key = key or api_key(API_KEY_VAR)
    divs = [d for d in SPORTS if divs is None or d in divs]

    if not key:
        print(f"No {API_KEY_VAR} - cup bets stay unpriced.")
        return {}

    now = now or datetime.now(timezone.utc)
    bets = add_missing_columns(pd.read_csv(bets_path))
    bets["OddsSource"] = bets["OddsSource"].astype(object)

    priced = {}

    for div in divs:

        waiting = unpriced_upcoming(bets, div, now)

        if not waiting:
            print(f"{div}: no upcoming unpriced bets - no odds call.")
            continue

        events, credits = fetch(key, SPORTS[div])
        matched = match_events(bets.loc[waiting], events)
        captured_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        log = []
        for i, event in matched.items():

            found = event_odds(event)
            if found is None:
                continue

            odds, source, books = found
            bets.loc[i, ODDS_COLUMNS] = odds
            bets.at[i, "OddsSource"] = source

            bet = bets.loc[i]
            log.append([
                captured_at, div, bet["MatchId"], bet["Date"], bet["Time"],
                bet["HomeTeam"], bet["AwayTeam"], event["home_team"], event["away_team"],
                *odds, source, books,
            ])

        priced[div] = len(log)

        if log:
            season = bets.loc[waiting[0], "Season"]
            _append_csv(log, LOG_COLUMNS, competition_dir(div, raw_dir) / f"odds_{season}.csv")

        _append_csv(
            [[captured_at, div, len(events), len(log),
              credits["last"], credits["used"], credits["remaining"]]],
            USAGE_COLUMNS, usage_path,
        )

        print(
            f"{div}: priced {len(log)} of {len(waiting)} upcoming bet(s) from "
            f"{len(events)} listed match(es); The Odds API credits "
            f"used {credits['used']}, remaining {credits['remaining']}"
        )

    if any(priced.values()):
        write_bets(bets, bets_path)

    return priced
