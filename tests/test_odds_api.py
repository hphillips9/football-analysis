"""
Tests for CL odds capture from The Odds API (odds_api.py) - no network.

    python tests/test_odds_api.py     (or pytest tests/)
"""

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import odds_api
from bet_schema import add_missing_columns
from test_bets import _bet, _results, _settle

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _book(key, h, d, a, home="Home", away="Away"):
    return {"key": key, "markets": [{"key": "h2h", "outcomes": [
        {"name": home, "price": h}, {"name": "Draw", "price": d}, {"name": away, "price": a},
    ]}]}


def _event(home, away, start, books=None, event_id=None):
    books = books or [_book("coral", 2.0, 3.5, 4.0), _book("betway", 2.1, 3.4, 3.8)]
    for b in books:
        names = iter([home, "Draw", away])
        for outcome in b["markets"][0]["outcomes"]:
            outcome["name"] = next(names)
    return {"id": event_id or f"{home}-{away}", "home_team": home, "away_team": away,
            "commence_time": start, "bookmakers": books}


def _cl_bet(home, away, date="24/11/2026", time="20:00", **overrides):
    return _bet(Div="CL", Gameweek=np.nan, Round="MD5", MatchId=1.0, Date=date, Time=time,
                HomeTeam=home, AwayTeam=away, **overrides)


def _price(bets, events, key="k", now=NOW):
    """price_bets on ``bets`` with a fake API; returns (file, calls, folder contents)."""

    calls = []

    def fetch(k, sport):
        calls.append(sport)
        return events, {"last": "1", "used": "7", "remaining": "493"}

    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        path = folder / "Bets.csv"
        pd.DataFrame(bets).to_csv(path, index=False)
        odds_api.price_bets(path, key=key, now=now, fetch=fetch, raw_dir=folder,
                            usage_path=folder / "usage.csv")
        log = folder / "CL" / "odds_26-27.csv"
        return (add_missing_columns(pd.read_csv(path)), calls,
                pd.read_csv(log) if log.exists() else None, pd.read_csv(folder / "usage.csv")
                if (folder / "usage.csv").exists() else None)


# ---------------------------------------------------------------- prices

def test_sky_bet_wins_when_listed():
    event = _event("A", "B", "2026-11-24T20:00:00Z", [
        _book("coral", 2.0, 3.5, 4.0), _book("skybet", 2.2, 3.3, 3.5), _book("betway", 1.9, 3.6, 4.2),
    ])
    assert odds_api.event_odds(event) == ([2.2, 3.3, 3.5], "SKB", 3)


def test_median_of_bookmakers_leaves_out_exchanges():
    event = _event("A", "B", "2026-11-24T20:00:00Z", [
        _book("coral", 2.0, 3.5, 4.0), _book("betway", 2.1, 3.4, 3.8),
        _book("ladbrokes_uk", 2.4, 3.3, 3.0), _book("smarkets", 9.0, 9.0, 9.0),
    ])
    assert odds_api.event_odds(event) == ([2.1, 3.4, 3.8], "UKMed", 3)


def test_no_complete_price_is_none():
    event = _event("A", "B", "2026-11-24T20:00:00Z", [_book("smarkets", 2.0, 3.0, 4.0)])
    assert odds_api.event_odds(event) is None


# ---------------------------------------------------------------- matching

def test_matches_fotmob_names_to_odds_api_names():
    events = [
        _event("Inter Milan", "VfB Stuttgart", "2026-11-25T20:00:00Z"),
        _event("Lille", "Bayern Munich", "2026-11-25T20:00:00Z"),
        _event("Sporting Lisbon", "Manchester United", "2026-11-25T20:00:00Z"),
        _event("Paris Saint Germain", "AS Roma", "2026-11-25T20:00:00Z"),
        _event("Shakhtar Donetsk", "Fenerbahce", "2026-11-25T20:00:00Z"),
        _event("Manchester City", "Napoli", "2026-11-25T20:00:00Z"),
        _event("ŠK Slovan Bratislava", "Real Betis", "2026-11-25T20:00:00Z"),
    ]
    bets = pd.DataFrame([
        _cl_bet("Inter", "VfB Stuttgart", "25/11/2026"),
        _cl_bet("Lille", "Bayern München", "25/11/2026"),
        _cl_bet("Sporting CP", "Manchester United", "25/11/2026"),
        _cl_bet("Paris Saint-Germain", "Roma", "25/11/2026"),
        _cl_bet("Shakhtar Donetsk", "Fenerbahçe", "25/11/2026"),
        _cl_bet("Manchester City", "Napoli", "25/11/2026"),
        _cl_bet("Slovan Bratislava", "Real Betis", "25/11/2026"),
    ])

    matched = odds_api.match_events(bets, events)

    assert {i: e["home_team"] for i, e in matched.items()} == {
        0: "Inter Milan", 1: "Lille", 2: "Sporting Lisbon", 3: "Paris Saint Germain",
        4: "Shakhtar Donetsk", 5: "Manchester City", 6: "ŠK Slovan Bratislava",
    }


def test_other_date_or_other_clubs_dont_match():
    events = [
        _event("Arsenal", "Borussia Dortmund", "2026-11-24T20:00:00Z"),
        _event("Real Madrid", "PSV Eindhoven", "2026-11-25T20:00:00Z"),
    ]
    bets = pd.DataFrame([
        _cl_bet("Arsenal", "Borussia Dortmund", "25/11/2026"),  # wrong date
        _cl_bet("Liverpool", "Club Brugge", "25/11/2026"),      # not listed
    ])

    assert odds_api.match_events(bets, events) == {}


def test_uk_date_of_a_late_utc_kickoff():
    # 00:30 UTC on the 25th in summer is 01:30 UK on the 25th; in winter UK = UTC
    event = _event("A", "B", "2026-11-24T23:30:00Z")
    assert odds_api._event_uk_date(event) == "24/11/2026"
    assert odds_api.kickoff_utc("24/08/2026", "20:00") == datetime(2026, 8, 24, 19, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- price_bets

def test_prices_upcoming_unpriced_cl_bets_and_logs():
    events = [_event("Arsenal", "Borussia Dortmund", "2026-11-24T20:00:00Z")]
    bets = [
        _cl_bet("Arsenal", "Borussia Dortmund"),
        _cl_bet("Galatasaray", "Aston Villa", date="18/11/2026"),  # already kicked off
        _bet(),                                                     # a league bet
    ]

    out, calls, log, usage = _price(bets, events)

    assert calls == ["soccer_uefa_champs_league"]
    assert out.loc[0, ["OddsH", "OddsD", "OddsA"]].tolist() == [2.05, 3.45, 3.9]
    assert out.at[0, "OddsSource"] == "UKMed"
    assert out.loc[1:, "OddsH"].isna().all()
    assert log[["HomeTeam", "ApiAway", "OddsSource", "Bookmakers"]].values.tolist() == [
        ["Arsenal", "Borussia Dortmund", "UKMed", 2]
    ]
    assert usage[["Div", "Priced", "CreditsUsed", "CreditsRemaining"]].values.tolist() == [
        ["CL", 1, 7, 493]
    ]


def test_no_key_means_no_call_and_unpriced():
    events = [_event("Arsenal", "Borussia Dortmund", "2026-11-24T20:00:00Z")]
    original = odds_api.api_key
    odds_api.api_key = lambda var=None: None
    try:
        out, calls, log, usage = _price([_cl_bet("Arsenal", "Borussia Dortmund")], events, key=None)
    finally:
        odds_api.api_key = original

    assert calls == [] and log is None and usage is None
    assert out["OddsH"].isna().all()


def test_no_call_when_nothing_needs_pricing():
    priced = _cl_bet("Arsenal", "Borussia Dortmund", OddsH=2.0, OddsD=3.0, OddsA=4.0,
                     OddsSource="SKB")
    out, calls, _, _ = _price([priced, _bet()], [])

    assert calls == []
    assert out.at[0, "OddsSource"] == "SKB" and out.at[0, "OddsH"] == 2.0


def test_captured_price_settles_the_cl_bet():
    events = [_event("Arsenal", "Borussia Dortmund", "2026-11-24T20:00:00Z")]
    out, _, _, _ = _price([_cl_bet("Arsenal", "Borussia Dortmund", PredictedResult="H")], events)

    results = _results([
        {"MatchId": "1", "Div": "CL", "Date": "24/11/2026", "HomeTeam": "Arsenal",
         "AwayTeam": "Borussia Dortmund", "FTR": "H"},
    ])
    settled = _settle(out.to_dict("records"), results)

    assert settled.at[0, "Bet"] == 1
    assert settled.at[0, "Profit"] == 1.05
    assert settled.at[0, "OddsSource"] == "UKMed"


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
