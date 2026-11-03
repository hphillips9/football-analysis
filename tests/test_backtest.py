"""
Tests for backtest.json: the §3.4 shape (docs/multi-league-plan.md), on
synthetic two-league data and on the committed file.

    python tests/test_backtest.py     (or pytest tests/)
"""

import itertools
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import backtest
from load_data import add_gameweek

SEASON_FIELDS = {
    "season", "matches", "trainedOn", "trainSeasons", "accuracy", "logLoss",
    "baselineAccuracy", "edge", "profit", "roi", "byGameweek",
}
OVERALL_FIELDS = {
    "matches", "accuracy", "logLoss", "baselineAccuracy", "edge", "profit", "roi",
}


def check_shape(payload):
    """Raise AssertionError unless ``payload`` has backtest.json's shape."""

    assert set(payload) == {
        "generated", "model", "pooled", "competitions", "seasons", "overall",
    }
    assert set(payload["model"]) == {"features", "leagueIndicators", "trainFrom"}

    sections = [payload["pooled"], *payload["competitions"].values()]
    for section in sections:
        assert {"seasons", "overall"} <= set(section)
        for row in section["seasons"]:
            assert set(row) == SEASON_FIELDS
        if section["overall"] is not None:
            assert set(section["overall"]) == OVERALL_FIELDS

    for div, section in payload["competitions"].items():
        assert isinstance(section["name"], str) and section["name"]

    # The deprecated top level is the Premier League's figures
    e0 = payload["competitions"].get("E0", {"seasons": [], "overall": None})
    assert payload["seasons"] == e0["seasons"]
    assert payload["overall"] == e0["overall"]


def _league(div, seed):

    rng = np.random.default_rng(seed)
    teams = [f"{div} {name}" for name in "ABCDEF"]
    rows = []

    for season, start in [("21-22", "2021-08-14"), ("22-23", "2022-08-13"), ("23-24", "2023-08-12")]:
        for week, (home, away) in enumerate(itertools.permutations(teams, 2)):
            goals = rng.integers(0, 4, size=2)
            kickoff = pd.Timestamp(start) + pd.Timedelta(days=3 * week)
            rows.append({
                "Div": div,
                "Season": season,
                "Date": kickoff.strftime("%d/%m/%Y"),
                "Time": "15:00",
                "MatchDateTime": kickoff,
                "HomeTeam": home,
                "AwayTeam": away,
                "FTHG": goals[0],
                "FTAG": goals[1],
                "FTR": "H" if goals[0] > goals[1] else "A" if goals[0] < goals[1] else "D",
                "HomeXG": round(rng.uniform(0.3, 2.5), 2),
                "AwayXG": round(rng.uniform(0.3, 2.5), 2),
                "AvgH": 2.2, "AvgD": 3.3, "AvgA": 3.4,
            })

    return pd.DataFrame(rows)


def test_two_leagues_give_pooled_and_per_competition_sections():
    matches = add_gameweek(pd.concat([_league("E0", 1), _league("SP1", 2)], ignore_index=True))

    saved = backtest.MIN_SEASON_MATCHES
    backtest.MIN_SEASON_MATCHES = 20

    try:
        with tempfile.TemporaryDirectory() as tmp:
            matches_path = Path(tmp) / "all_matches.csv"
            out_path = Path(tmp) / "backtest.json"
            matches.to_csv(matches_path, index=False)

            backtest.run_backtest(matches_path, out_path)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        backtest.MIN_SEASON_MATCHES = saved

    check_shape(payload)

    assert payload["model"]["leagueIndicators"] == ["League_SP1"]
    assert payload["model"]["trainFrom"] == "21-22"
    assert list(payload["competitions"]) == ["E0", "SP1"]
    assert payload["competitions"]["SP1"]["name"] == "La Liga"

    pooled = payload["pooled"]["overall"]["matches"]
    per_league = sum(c["overall"]["matches"] for c in payload["competitions"].values())
    assert pooled == per_league == 2 * 2 * 30  # 2 test seasons x 2 leagues x 30 games


def test_committed_backtest_json_has_the_shape():
    check_shape(json.loads((ROOT / "web" / "src" / "data" / "backtest.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
