"""
Tests for the Bets.csv schema and settlement (bet_schema, fetch_results).

    python tests/test_bets.py     (or pytest tests/)
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fetch_results
from bet_schema import COLUMN_ORDER, add_missing_columns


def _results(rows):
    """A results frame as _load_current_results returns it."""

    frame = pd.DataFrame(rows)
    for column in ["SKBH", "SKBD", "SKBA", "AvgH", "AvgD", "AvgA"]:
        if column not in frame.columns:
            frame[column] = np.nan
    frame["Season"] = frame.get("Season", "26-27")
    frame["_day"] = pd.to_datetime(frame["Date"], dayfirst=True)
    frame["_home"] = frame["HomeTeam"]
    frame["_away"] = frame["AwayTeam"]
    return frame


def _bet(**overrides):
    bet = {
        "Season": "26-27", "Div": "E0", "Gameweek": 1, "MatchId": np.nan,
        "Date": "22/08/2026", "Time": "15:00",
        "HomeTeam": "Everton", "AwayTeam": "Fulham", "PredictedResult": "H",
        "HomeProb": 50.0, "DrawProb": 25.0, "AwayProb": 25.0,
        "ActualResult": np.nan, "Bet": np.nan, "Profit": np.nan,
    }
    bet.update(overrides)
    return bet


def _settle(bets, results):
    """Run complete_bets on ``bets`` against ``results``; returns the file."""

    original = fetch_results._load_current_results
    fetch_results._load_current_results = lambda divs=None: results.copy()

    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "Bets.csv"
            pd.DataFrame(bets).to_csv(path, index=False)
            fetch_results.complete_bets(path)
            return pd.read_csv(path)
    finally:
        fetch_results._load_current_results = original


def test_add_missing_columns_fills_season_and_round():
    old = pd.DataFrame([_bet()]).drop(
        columns=["Season", "MatchId"]
    )

    new = add_missing_columns(old)

    assert list(new.columns) == COLUMN_ORDER
    assert new.at[0, "Season"] == "26-27"
    assert new.at[0, "Round"] == "1"
    assert pd.isna(new.at[0, "MatchId"])


def test_settles_within_a_day_on_the_same_div_and_season():
    results = _results([
        {"Div": "E0", "Date": "23/08/2026", "HomeTeam": "Everton",
         "AwayTeam": "Fulham", "FTR": "H", "SKBH": 2.1, "SKBD": 3.4, "SKBA": 3.6},
    ])

    out = _settle([_bet()], results)

    assert out.at[0, "ActualResult"] == "H"
    assert out.at[0, "Profit"] == 1.1
    assert out.at[0, "Bet"] == 1
    assert out.loc[0, ["OddsH", "OddsD", "OddsA"]].tolist() == [2.1, 3.4, 3.6]
    assert out.at[0, "OddsSource"] == "SKB"


def test_ignores_other_div_other_season_and_far_dates():
    common = {"HomeTeam": "Everton", "AwayTeam": "Fulham", "FTR": "A", "AvgA": 3.0}
    results = _results([
        {**common, "Div": "SP1", "Date": "22/08/2026"},
        {**common, "Div": "E0", "Date": "22/08/2026", "Season": "25-26"},
        {**common, "Div": "E0", "Date": "24/08/2026"},  # 2 days out
    ])

    out = _settle([_bet()], results)

    assert out["ActualResult"].isna().all()


def test_nearest_date_wins():
    # The same pairing twice (two CL legs), both near the bet
    common = {"Div": "E0", "HomeTeam": "Everton", "AwayTeam": "Fulham",
              "AvgH": 2.0, "AvgD": 3.0, "AvgA": 4.0}
    results = _results([
        {**common, "Date": "21/08/2026", "FTR": "A"},
        {**common, "Date": "22/08/2026", "FTR": "H"},
    ])

    out = _settle([_bet()], results)

    assert out.at[0, "ActualResult"] == "H"


def test_falls_back_to_market_average_per_pick():
    results = _results([
        {"Div": "E0", "Date": "22/08/2026", "HomeTeam": "Everton",
         "AwayTeam": "Fulham", "FTR": "D",
         "SKBH": np.nan, "SKBD": 3.2, "AvgH": 2.0, "AvgD": 3.3, "AvgA": 4.0},
    ])

    out = _settle([_bet()], results)

    assert out.at[0, "OddsSource"] == "Avg"
    assert out.at[0, "OddsH"] == 2.0
    assert out.at[0, "Profit"] == -1.0


def test_no_odds_means_unpriced():
    results = _results([
        {"Div": "E0", "Date": "22/08/2026", "HomeTeam": "Everton",
         "AwayTeam": "Fulham", "FTR": "H"},
    ])

    out = _settle([_bet()], results)

    assert out.at[0, "ActualResult"] == "H"
    assert out.at[0, "Bet"] == 0
    assert pd.isna(out.at[0, "Profit"])
    assert pd.isna(out.at[0, "OddsSource"])


def test_odds_captured_at_prediction_win():
    results = _results([
        {"Div": "E0", "Date": "22/08/2026", "HomeTeam": "Everton",
         "AwayTeam": "Fulham", "FTR": "H", "SKBH": 2.1, "SKBD": 3.4, "SKBA": 3.6},
    ])
    bet = _bet(OddsH=2.5, OddsD=3.0, OddsA=3.0, OddsSource="OddsAPI")

    out = _settle([bet], results)

    assert out.at[0, "OddsSource"] == "OddsAPI"
    assert out.at[0, "Profit"] == 1.5


def test_match_id_beats_names_and_dates():
    results = _results([
        {"MatchId": "77", "Div": "E0", "Date": "30/08/2026", "HomeTeam": "Everton",
         "AwayTeam": "Fulham", "FTR": "A", "AvgH": 2.0, "AvgD": 3.0, "AvgA": 4.0},
    ])

    out = _settle([_bet(MatchId="77")], results)

    assert out.at[0, "ActualResult"] == "A"


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
