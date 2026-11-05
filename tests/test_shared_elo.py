"""
Tests for elo.py's shared scale (notebook 21's E2a+E2b): European
results moving club ratings and league offsets, re-centring, clubs from
outside the modelled leagues, and the neutral final.

    python tests/test_shared_elo.py     (or pytest tests/)
"""

import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from elo import (
    EUROPE_HOME_ADVANTAGE, EUROPE_UPDATE_SIZE, OFFSET_SCALE, OFFSET_UPDATE_SIZE,
    ENTRANT_BONUS, OUTSIDER_CARRY, build_elo_feature, expected_result, shared_scale,
)

# England 100, Spain 50, Scotland 25 -> Spain sits OFFSET_SCALE * ln(0.5) below
COEFFICIENTS = {
    (country, season): value
    for season in ("24-25", "25-26")
    for country, value in (("ENG", 100.0), ("ESP", 50.0), ("SCO", 25.0))
}
SPAIN = OFFSET_SCALE * math.log(0.5)
SCOTLAND = OFFSET_SCALE * math.log(0.25)


def _domestic(rows):
    return pd.DataFrame(rows, columns=["Div", "Season", "MatchDateTime", "HomeTeam", "AwayTeam", "FTR"]) \
        .assign(MatchDateTime=lambda f: pd.to_datetime(f["MatchDateTime"]))


def _european(rows):
    frame = pd.DataFrame(rows, columns=["Season", "Date", "HomeTeam", "AwayTeam",
                                        "HomeLeague", "AwayLeague", "FTR", "Neutral"])
    return frame.assign(Date=pd.to_datetime(frame["Date"]), MatchId=[str(i) for i in range(len(frame))])


DOMESTIC = _domestic([
    ("E0", "24-25", "2024-08-10", "Arsenal", "Brentford", "H"),
    ("SP1", "24-25", "2024-08-10", "Cadiz", "Deportivo", "D"),
    ("E0", "24-25", "2024-09-21", "Brentford", "Arsenal", "D"),
])


def _run(european, domestic=DOMESTIC, **kwargs):
    return shared_scale(domestic.copy(), european, coefficients=COEFFICIENTS, **kwargs)


def _expected(home, away, neutral=0):
    return 1 / (1 + 10 ** (-(home + EUROPE_HOME_ADVANTAGE * (1 - neutral) - away) / 400))


def test_no_european_results_is_todays_elo():
    old = DOMESTIC.copy()
    build_elo_feature(old)
    result = _run(_european([]))

    assert list(old["HomeElo"]) == result["home_elo"]
    assert list(old["AwayElo"]) == result["away_elo"]


def test_european_win_moves_both_clubs_and_the_offsets():
    result = _run(_european([("24-25", "2024-09-17", "Arsenal", "Cadiz", "E0", "SP1", "H", 0)]))

    # Going in: the opening-day domestic results, on the shared scale
    win = expected_result(1500, 1500)
    arsenal = 1500 + 35 * (1 - win)
    cadiz = 1500 + 35 * (0.5 - win)
    # Both leagues average 1500 domestically, so delta = 0
    expected = _expected(arsenal, cadiz + SPAIN)
    change = 1 - expected

    # E2a: Arsenal's rating for its next league match includes the win
    assert math.isclose(result["home_elo"][2], 1500 - 35 * (1 - win))  # Brentford
    assert math.isclose(result["away_elo"][2], arsenal + EUROPE_UPDATE_SIZE * change)
    assert math.isclose(result["domestic"][("SP1", "Cadiz")], cadiz - EUROPE_UPDATE_SIZE * change)

    # E2b: Spain's offset learns; England's anchors the scale
    latest = result["offsets"].drop_duplicates("Div", keep="last").set_index("Div")["Offset"]
    assert math.isclose(latest["SP1"], SPAIN - OFFSET_UPDATE_SIZE * change)
    assert latest["E0"] == 0


def test_recentring_keeps_what_a_league_won_in_europe():
    result = _run(_european([("24-25", "2024-09-17", "Arsenal", "Cadiz", "E0", "SP1", "H", 0)]))
    ratings = result["ratings"].set_index(["League", "Club"])["Rating"]

    england = ratings.loc[["E0"]].mean()
    spain = ratings.loc[["SP1"]].mean()

    # Each league averages 1500 + O_L, plus what its clubs took off the other's
    transfer = result["domestic"][("E0", "Arsenal")] + result["domestic"][("E0", "Brentford")] - 3000
    latest = result["offsets"].drop_duplicates("Div", keep="last").set_index("Div")["Offset"]
    assert math.isclose(england, 1500 + transfer / 2)
    assert math.isclose(spain, 1500 + latest["SP1"] - transfer / 2)


def test_club_outside_the_leagues_starts_at_its_country_and_carries_over():
    european = _european([
        ("24-25", "2024-09-17", "Celtic", "Brentford", "X:SCO", "E0", "D", 0),
        ("25-26", "2025-09-16", "Celtic", "Arsenal", "X:SCO", "E0", "A", 0),
    ])
    domestic = pd.concat([DOMESTIC, _domestic([
        ("E0", "25-26", "2025-08-16", "Arsenal", "Brentford", "D"),
    ])], ignore_index=True)

    result = _run(european, domestic=domestic, history_from="2024-01-01")
    celtic = result["history"][result["history"]["Club"] == "Celtic"]

    start = 1500 + SCOTLAND + ENTRANT_BONUS
    brentford = 1500 - 35 * (1 - expected_result(1500, 1500))
    after_first = start + EUROPE_UPDATE_SIZE * (0.5 - _expected(start, brentford))
    assert math.isclose(celtic["Rating"].iloc[0], after_first)

    # Next season: pulled halfway back to Scotland's baseline, then the defeat
    carried = 1500 + SCOTLAND + OUTSIDER_CARRY * (after_first - (1500 + SCOTLAND))
    final = result["ratings"].set_index("Club").loc["Celtic"]
    assert final["League"] == "X:SCO" and not final["Modelled"]
    assert final["Rating"] < carried


def test_neutral_final_has_no_home_advantage():
    venue = _run(_european([("24-25", "2024-09-17", "Arsenal", "Cadiz", "E0", "SP1", "D", 0)]))
    neutral = _run(_european([("24-25", "2024-09-17", "Arsenal", "Cadiz", "E0", "SP1", "D", 1)]))

    # A draw at home is a worse result than a draw on neutral ground
    assert neutral["domestic"][("E0", "Arsenal")] > venue["domestic"][("E0", "Arsenal")]


def test_results_for_elo_cuts_off_at_the_given_date():
    import european

    frame = _european([
        ("24-25", "2024-09-17", "Arsenal", "Cadiz", "E0", "SP1", "H", 0),
        ("24-25", "2024-10-01", "Cadiz", "Arsenal", "SP1", "E0", "H", 0),
    ])
    saved = european.load_european
    european.load_european = lambda domestic, raw_dir: frame
    try:
        cut = european.results_for_elo(DOMESTIC, before="2024-10-01 20:00")
    finally:
        european.load_european = saved

    assert list(cut["Date"].dt.strftime("%Y-%m-%d")) == ["2024-09-17"]


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
