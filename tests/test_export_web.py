"""
Tests for the cup parts of the web export (P6-01): round numbers for cup
bets, the knockout bracket and the league-phase table.

    python tests/test_export_web.py     (or pytest tests/)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import export_web
from export_web import (
    _bracket_order,
    _rank_league_phase,
    build_knockouts,
    build_league_phase,
    build_stats,
    cup_rounds,
)


def _bets(rows):
    frame = pd.DataFrame(rows, columns=["Season", "Round", "HomeTeam", "AwayTeam", "Kickoff"])
    frame["Kickoff"] = pd.to_datetime(frame["Kickoff"])
    return frame


def test_cup_rounds_numbers_matchdays_and_knockout_legs():

    bets = _bets([
        ("26-27", "MD1", "A", "B", "2026-09-08 20:00"),
        ("26-27", "MD8", "C", "D", "2027-01-27 20:00"),
        ("26-27", "R16", "B", "A", "2027-03-17 20:00"),   # second leg
        ("26-27", "R16", "A", "B", "2027-03-10 20:00"),   # first leg
        ("26-27", "KO_PLAYOFF", "E", "F", "2027-02-17 20:00"),
        ("26-27", "FINAL", "A", "C", "2027-05-29 20:00"),
    ])

    assert cup_rounds(bets).tolist() == [1, 8, 12, 11, 9, 17]


def test_cup_rounds_rejects_an_unknown_round():

    bets = _bets([("26-27", "GROUP_X", "A", "B", "2026-09-08 20:00")])

    try:
        cup_rounds(bets)
    except ValueError as exc:
        assert "GROUP_X" in str(exc)
    else:
        raise AssertionError("an unknown round should fail")


def test_league_phase_ranking_breaks_ties_on_away_goals_then_wins():

    def row(team, points, gf, ga, away_gf, won, away_won=0):
        return {"team": team, "points": points, "gf": gf, "ga": ga,
                "awayGf": away_gf, "won": won, "awayWon": away_won}

    ranked = _rank_league_phase([
        row("Low away goals", 10, 8, 4, 2, 3),
        row("More points", 11, 5, 5, 0, 3),
        row("High away goals", 10, 8, 4, 5, 3),
        row("Worse GD", 10, 9, 6, 9, 3),
    ])

    assert [r["team"] for r in ranked] == [
        "More points", "High away goals", "Low away goals", "Worse GD",
    ]
    assert ranked[1]["gd"] == 4 and "awayGf" not in ranked[1]


def test_bracket_order_follows_the_next_round_back():

    def tie(a, b):
        return {"teams": [a, b]}

    rounds = {
        "QF": [tie("C", "D"), tie("G", "H"), tie("A", "B"), tie("E", "F")],
        "SF": [tie("A", "E"), tie("C", "G")],
        "FINAL": [tie("C", "A")],
    }

    ordered = _bracket_order(rounds)

    # The final's first side came through the second semi, so that semi comes first
    assert [t["teams"] for t in ordered["SF"]] == [["C", "G"], ["A", "E"]]
    assert [t["teams"] for t in ordered["QF"]] == [
        ["C", "D"], ["G", "H"], ["A", "B"], ["E", "F"],
    ]


def _cup_row(stage, leg, date, home, away, hg, ag, aet=(None, None), pens=None, winner=None):
    return {
        "Div": "CL", "Season": "25-26", "Stage": stage, "Round": stage, "Leg": leg,
        "MatchDateTime": pd.Timestamp(date), "MatchId": f"{home}-{away}-{date}",
        "HomeTeam": home, "AwayTeam": away, "FTHG": hg, "FTAG": ag,
        "FTR": "H" if hg > ag else "A" if hg < ag else "D",
        "AETHG": aet[0], "AETAG": aet[1], "PenWinner": pens, "TieWinner": winner,
        "Neutral": 0, "HomeLeague": "E0", "AwayLeague": "SP1",
    }


def test_knockouts_aggregate_extra_time_and_last_season_fallback():

    matches = pd.DataFrame([
        _cup_row("SF", 1, "2026-04-28", "A", "B", 2, 1),
        _cup_row("SF", 2, "2026-05-05", "B", "A", 2, 1, aet=(3, 1), winner="B"),
        _cup_row("SF", 1, "2026-04-29", "C", "D", 0, 0),
        _cup_row("SF", 2, "2026-05-06", "D", "C", 1, 1, aet=(1, 1), pens="C", winner="C"),
        _cup_row("FINAL", np.nan, "2026-05-30", "B", "C", 1, 0, winner="B"),
    ])
    no_bets = pd.DataFrame(columns=["MatchId", "PredictedResult", "HomeProb", "DrawProb", "AwayProb"])

    # 26-27 has no knockout ties yet, so 25-26's bracket is shown
    ko = build_knockouts("CL", matches, None, no_bets, "26-27")

    assert ko["season"] == "25-26" and ko["current"] is False
    assert [r["stage"] for r in ko["rounds"]] == ["SF", "FINAL"]

    first, second = ko["rounds"][0]["ties"]
    assert first["teams"] == ["A", "B"]
    assert first["aggregate"] == [3, 4]          # 2-1, then 3-1 to B after extra time
    assert first["winner"] == "B" and first["decidedBy"] == "extra time"
    assert [leg["leg"] for leg in first["legs"]] == [1, 2]

    assert second["aggregate"] == [1, 1]
    assert second["winner"] == "C" and second["decidedBy"] == "penalties"

    final = ko["rounds"][1]["ties"][0]
    assert final["legs"][0]["leg"] is None and final["decidedBy"] == "90 minutes"


def test_league_phase_projects_remaining_fixtures():

    played = pd.DataFrame([
        {**_cup_row("LEAGUE_PHASE", np.nan, "2026-09-08", "A", "B", 2, 0), "Season": "26-27", "MatchId": "1"},
    ])
    fixtures = pd.DataFrame({
        "MatchId": ["1", "2"],
        "Round": ["1", "2"],
        "HomeId": [1, 2],
        "AwayId": [2, 1],
        "HomeTeam": ["A", "B"],
        "AwayTeam": ["B", "A"],
        "KickoffUTC": pd.to_datetime(["2026-09-08T19:00Z", "2026-10-01T19:00Z"], utc=True),
        "Stage": ["LEAGUE_PHASE", "LEAGUE_PHASE"],
    })

    def fake_predict(frame, *args):
        out = frame[["HomeTeam", "AwayTeam"]].copy()
        out["HomeProb"], out["DrawProb"], out["AwayProb"] = 50.0, 30.0, 20.0
        return out

    saved = export_web.predict_fixtures, export_web.club_leagues
    export_web.predict_fixtures = fake_predict
    export_web.club_leagues = lambda ids, *a, **k: {1: "E0", 2: "SP1"}
    try:
        phase = build_league_phase("CL", played, fixtures, "26-27", (None, None, None), pd.DataFrame())
    finally:
        export_web.predict_fixtures, export_web.club_leagues = saved

    assert phase["playedFixtures"] == 1 and phase["remainingFixtures"] == 1
    assert [r["team"] for r in phase["current"]] == ["A", "B"]
    assert phase["current"][0]["points"] == 3 and phase["current"][0]["league"] == "E0"

    # B at home: 3 x 0.5 + 0.3 = 1.8 -> 2; A away: 3 + 3 x 0.2 + 0.3 = 3.9 -> 4
    projected = {r["team"]: r for r in phase["projected"]}
    assert projected["A"]["points"] == 4 and projected["B"]["points"] == 2
    assert projected["A"]["played"] == 2


def test_stats_log_loss_and_unpriced_bets():

    bets = pd.DataFrame({
        "Div": "CL", "Gameweek": [1, 1],
        "Kickoff": pd.to_datetime(["2026-09-08 20:00", "2026-09-08 20:00"]),
        "HomeTeam": ["A", "C"], "AwayTeam": ["B", "D"],
        "Date": "08/09/2026",
        "PredictedResult": ["H", "H"], "ActualResult": ["H", "A"],
        "HomeProb": [50.0, 60.0], "DrawProb": [30.0, 20.0], "AwayProb": [20.0, 20.0],
        "Bet": [0, 0], "Profit": [np.nan, np.nan], "Backfilled": [1, 1],
    })
    bets["Won"] = bets["PredictedResult"] == bets["ActualResult"]
    bets["PickProb"] = bets[["HomeProb", "DrawProb", "AwayProb"]].max(axis=1)

    stats = build_stats(bets)

    assert stats["logLoss"] == round(-(np.log(0.5) + np.log(0.2)) / 2, 3)
    assert stats["pricedBets"] == 0 and stats["staked"] == 0 and stats["roi"] == 0.0
    assert stats["hitRate"] == 50.0


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
