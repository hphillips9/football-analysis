"""
Tests for postponed league games: the bet follows the fixture to its new
date, a straggler doesn't hold up the next round, and the site features
the current gameweek rather than the postponed game's.

    python tests/test_postponed.py     (or pytest tests/)
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import competitions
import fetch_fixtures
from export_web import build_predictions

SEASON = competitions.CURRENT_SEASON


def _fixture(gameweek, status, when, home, away):
    kickoff = pd.Timestamp(when, tz="Europe/London")
    return {
        "Gameweek": gameweek, "Status": status, "Kickoff": kickoff, "Div": "P1",
        "Date": kickoff.strftime("%d/%m/%Y"), "Time": kickoff.strftime("%H:%M"),
        "HomeTeam": home, "AwayTeam": away,
    }


def _bet(gameweek, when, home, away, result=np.nan):
    kickoff = pd.Timestamp(when)
    return {
        "Season": SEASON, "Div": "P1", "Gameweek": gameweek, "MatchId": np.nan,
        "Date": kickoff.strftime("%d/%m/%Y"), "Time": kickoff.strftime("%H:%M"),
        "HomeTeam": home, "AwayTeam": away, "PredictedResult": "H",
        "HomeProb": 50.0, "DrawProb": 25.0, "AwayProb": 25.0,
        "ActualResult": result, "Bet": np.nan, "Profit": np.nan,
    }


def _with_bets(bets, action):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Bets.csv"
        pd.DataFrame(bets).to_csv(path, index=False)
        out = action(path)
        return out, pd.read_csv(path)


def test_rearranged_bet_moves_to_the_new_date():

    fixtures = pd.DataFrame([
        _fixture(11, "TIMED", "2027-01-14 19:00", "Estoril", "Nacional"),     # rearranged
        _fixture(11, "FINISHED", "2026-11-08 15:00", "Rio Ave", "Braga"),
        _fixture(12, "TIMED", "2026-11-28 15:00", "Arouca", "Rio Ave"),
    ])
    bets = [
        _bet(11, "2026-11-08 18:00", "Estoril", "Nacional"),
        _bet(11, "2026-11-08 15:00", "Rio Ave", "Braga", result="A"),
        _bet(12, "2026-11-28 15:00", "Arouca", "Rio Ave"),
    ]

    moved, after = _with_bets(bets, lambda p: fetch_fixtures.reschedule_bets(fixtures, p))

    assert moved == 1
    assert after.loc[0, ["Date", "Time"]].tolist() == ["14/01/2027", "19:00"]
    # Settled and unchanged bets are left alone; whole numbers stay whole
    assert after.loc[1:, "Date"].tolist() == ["08/11/2026", "28/11/2026"]
    assert after["Gameweek"].tolist() == [11, 11, 12]


def test_still_postponed_bet_is_left_alone():

    fixtures = pd.DataFrame([_fixture(11, "POSTPONED", "2026-11-08 18:00", "Estoril", "Nacional")])
    bets = [_bet(11, "2026-11-08 18:00", "Estoril", "Nacional")]

    moved, after = _with_bets(bets, lambda p: fetch_fixtures.reschedule_bets(fixtures, p))

    assert moved == 0
    assert after.loc[0, "Date"] == "08/11/2026"


def test_rearranged_straggler_does_not_block_the_next_round():

    # GW12 is finished; the GW11 game now sits in January with its bet moved
    fixtures = pd.DataFrame(
        [_fixture(11, "TIMED", "2027-01-14 19:00", "Estoril", "Nacional")]
        + [_fixture(12, "FINISHED", "2026-11-28 15:00", f"H{i}", f"A{i}") for i in range(5)]
        + [_fixture(13, "TIMED", "2026-12-05 15:00", f"A{i}", f"H{i}") for i in range(5)]
    )
    bets = [_bet(11, "2027-01-14 19:00", "Estoril", "Nacional")] + [
        _bet(12, "2026-11-28 15:00", f"H{i}", f"A{i}", result="H") for i in range(5)
    ]

    upcoming, _ = _with_bets(bets, lambda p: fetch_fixtures.next_round(fixtures, p, on_file=99))

    assert upcoming is not None
    assert set(upcoming["Gameweek"]) == {13}


def test_unfinished_latest_round_still_blocks():

    fixtures = pd.DataFrame(
        [_fixture(12, "TIMED", "2026-11-30 20:00", f"H{i}", f"A{i}") for i in range(5)]
        + [_fixture(13, "TIMED", "2026-12-05 15:00", f"A{i}", f"H{i}") for i in range(5)]
    )
    bets = [_bet(12, "2026-11-30 20:00", f"H{i}", f"A{i}") for i in range(5)]

    upcoming, _ = _with_bets(bets, lambda p: fetch_fixtures.next_round(fixtures, p, on_file=99))

    assert upcoming is None


def _site_bets(rows):
    bets = pd.DataFrame(rows)
    bets["Kickoff"] = pd.to_datetime(bets["Date"] + " " + bets["Time"], dayfirst=True)
    bets["Round"] = np.nan
    return bets.sort_values("Kickoff").reset_index(drop=True)


def test_site_features_the_current_gameweek_not_the_postponed_one():

    bets = _site_bets([
        _bet(11, "2026-11-08 18:00", "Estoril", "Nacional"),            # postponed, no new date
        _bet(11, "2026-11-08 15:00", "Rio Ave", "Braga", result="A"),
        _bet(12, "2026-11-28 15:00", "Arouca", "Rio Ave"),
        _bet(12, "2026-11-29 15:00", "Gil Vicente", "Estoril"),
    ])

    fixtures = build_predictions(bets, {})

    assert {f["gameweek"] for f in fixtures} == {12}
    assert [f["home"] for f in fixtures] == ["Arouca", "Gil Vicente"]


def test_straggler_rearranged_into_the_round_is_listed_with_it():

    bets = _site_bets([
        _bet(11, "2026-11-27 20:00", "Estoril", "Nacional"),            # moved into GW12's window
        _bet(11, "2026-11-08 15:00", "Rio Ave", "Braga", result="A"),
        _bet(12, "2026-11-28 15:00", "Arouca", "Rio Ave"),
        _bet(12, "2026-11-29 15:00", "Gil Vicente", "Braga"),
    ])

    fixtures = build_predictions(bets, {})

    assert {f["gameweek"] for f in fixtures} == {12}
    assert [f["home"] for f in fixtures] == ["Estoril", "Arouca", "Gil Vicente"]


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
