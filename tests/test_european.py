"""
Tests for european.py: parsing FotMob's European fixtures and match
details (saved, trimmed JSON in tests/fixtures/fotmob/) and building
all_matches-style rows from the caches.

    python tests/test_european.py     (or pytest tests/)
"""

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import european
from team_names import REFERENCE_COLUMNS

FIXTURES = ROOT / "tests" / "fixtures" / "fotmob"


def _json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fixture(match_id, season="24-25"):
    league = _json(f"league_42_20{season[:2]}_20{season[3:]}.json")
    return next(
        row for row in european.parse_fixtures(league, season)
        if row["MatchId"] == str(match_id)
    )


def test_psv_juventus_aet_is_2_1_at_90():
    row = european.match_row(
        _fixture(4723905), _json("match_4723905_psv_juventus.json")
    )

    assert (row["FTHG90"], row["FTAG90"]) == (2, 1)
    assert (row["FTHG"], row["FTAG"], row["Reason"]) == (3, 1, "AET")
    assert (row["Stage"], row["Round"], row["Leg"]) == ("KO_PLAYOFF", "KO_PLAYOFF", 2)
    assert (row["AggHome"], row["AggAway"], row["TieWinner"]) == (4, 3, "H")
    assert row["PenWinner"] is None
    # 90-minute xG leaves out both extra-time halves
    assert (row["HomeXG90"], row["AwayXG90"]) == (1.65, 0.96)
    assert (row["HomeXGAll"], row["AwayXGAll"]) == (3.40, 1.76)


def test_liverpool_psg_lost_on_penalties():
    row = european.match_row(
        _fixture(4737562), _json("match_4737562_liverpool_psg.json")
    )

    assert (row["FTHG90"], row["FTAG90"]) == (0, 1)
    assert (row["FTHG"], row["FTAG"], row["Reason"]) == (0, 1, "Pen")
    assert (row["Stage"], row["Leg"]) == ("R16", 2)
    assert (row["AggHome"], row["AggAway"]) == (1, 1)
    assert (row["PenWinner"], row["TieWinner"]) == ("A", "A")
    assert (row["HomeXG90"], row["AwayXG90"]) == (1.45, 2.13)


def test_inter_barcelona_semi_final_is_3_3_at_90():
    row = european.match_row(
        _fixture(4737578), _json("match_4737578_inter_barcelona.json")
    )

    assert (row["FTHG90"], row["FTAG90"]) == (3, 3)
    assert (row["FTHG"], row["FTAG"], row["Reason"]) == (4, 3, "AET")
    assert (row["Stage"], row["Leg"]) == ("SF", 2)
    assert (row["AggHome"], row["AggAway"], row["TieWinner"]) == (7, 6, "H")
    assert (row["HomeXG90"], row["AwayXG90"]) == (2.03, 2.22)


def test_fixture_counts_stages_and_legs():
    new_format = european.parse_fixtures(_json("league_42_2024_2025.json"), "24-25")
    old_format = european.parse_fixtures(_json("league_42_2021_2022.json"), "21-22")

    assert len(new_format) == 189
    assert Counter(row["Stage"] for row in new_format) == {
        "LEAGUE_PHASE": 144, "KO_PLAYOFF": 16, "R16": 16, "QF": 8, "SF": 4, "FINAL": 1,
    }
    assert len(old_format) == 125
    assert Counter(row["Stage"] for row in old_format)["GROUP"] == 96

    # Two legs per knockout tie (from the bracket), none elsewhere
    legs = Counter(row["Leg"] for row in new_format)
    assert legs == {None: 145, 1: 22, 2: 22}
    assert {row["Round"] for row in new_format if row["Stage"] == "LEAGUE_PHASE"} == {
        f"MD{n}" for n in range(1, 9)
    }


def test_unknown_round_is_an_error():
    try:
        european.stage_and_round("1/32", "24-25")
        raise AssertionError("expected an unknown round to raise")
    except ValueError as exc:
        assert "1/32" in str(exc)


def test_ninety_minute_match_needs_no_events():
    details = {
        "header": {
            "teams": [{"name": "Paris Saint-Germain"}, {"name": "Inter"}],
            "status": {"scoreStr": "5 - 0", "reason": {"short": "FT"}},
        },
        "content": {"matchFacts": {"events": {"events": []}}, "stats": {}},
    }
    final = _fixture(4737579)
    row = european.match_row(final, details)

    assert (row["FTHG90"], row["FTAG90"], row["Reason"]) == (5, 0, "FT")
    assert row["TieWinner"] == "H"  # a one-match final has a winner too
    assert row["Leg"] is None and row["AggHome"] is None
    assert row["HomeXG90"] is None


def test_team_country_and_ground():
    team = european.parse_team(_json("team_10170_derby.json"))

    assert team["Country"] == "ENG"
    assert team["Venue"] == "Pride Park Stadium"
    assert round(team["VenueLat"], 3) == 52.915


def _write_world(folder):
    """A CL cache, a team cache and a reference table in ``folder``."""

    raw_dir = folder / "raw"
    (raw_dir / "CL").mkdir(parents=True)

    psv_juve = european.match_row(
        _fixture(4723905), _json("match_4723905_psv_juventus.json")
    )
    # Shakhtar's "home" match played in Gelsenkirchen
    relocated = {
        **dict.fromkeys(european.CACHE_COLUMNS),
        "MatchId": "1", "Date": "2024-10-02", "Stage": "LEAGUE_PHASE", "Round": "MD2",
        "HomeId": 6069, "AwayId": 9885, "HomeTeam": "Shakhtar Donetsk",
        "AwayTeam": "Juventus", "FTHG90": 0, "FTAG90": 0, "FTHG": 0, "FTAG": 0,
        "Reason": "FT", "StadiumLat": 51.554, "StadiumLon": 7.068,
    }
    # Juventus at San Siro: moved, but still in Italy
    moved_at_home = {
        **relocated, "MatchId": "2", "HomeId": 9885, "AwayId": 6069,
        "HomeTeam": "Juventus", "AwayTeam": "Shakhtar Donetsk",
        "StadiumLat": 45.478, "StadiumLon": 9.124,
    }
    pd.DataFrame(
        [psv_juve, relocated, moved_at_home], columns=european.CACHE_COLUMNS
    ).to_csv(
        raw_dir / "CL" / "fotmob_24-25.csv", index=False
    )
    # COVID season: never loaded (D3)
    pd.DataFrame([relocated], columns=european.CACHE_COLUMNS).to_csv(
        raw_dir / "CL" / "fotmob_20-21.csv", index=False
    )

    teams_path = raw_dir / "fotmob_teams.csv"
    pd.DataFrame([
        {"FotMobId": 8640, "Name": "PSV Eindhoven", "Country": "NED",
         "Venue": "Philips Stadion", "VenueLat": 51.4416, "VenueLon": 5.4675},
        {"FotMobId": 6069, "Name": "Shakhtar Donetsk", "Country": "UKR",
         "Venue": "Donbass Arena", "VenueLat": 48.0207, "VenueLon": 37.8098},
        {"FotMobId": 9885, "Name": "Juventus", "Country": "ITA",
         "Venue": "Allianz Stadium", "VenueLat": 45.1096, "VenueLon": 7.6413},
    ], columns=european.TEAM_COLUMNS).to_csv(teams_path, index=False)

    reference_path = folder / "team_names.csv"
    pd.DataFrame(
        [{"canonical_name": "Juventus", "country": "ITA", "fotmob_id": 9885,
          "football_data_name": "Juventus", "fotmob_name": "Juventus"}],
        columns=REFERENCE_COLUMNS,
    ).to_csv(reference_path, index=False)

    domestic = pd.DataFrame(
        {"Div": ["I1"], "Season": ["24-25"], "HomeTeam": ["Juventus"], "AwayTeam": ["Lazio"]}
    )

    return dict(
        raw_dir=raw_dir, teams_path=teams_path,
        reference_path=reference_path, domestic=domestic,
    )


def test_load_european_rows():
    with tempfile.TemporaryDirectory() as tmp:
        matches = european.load_european(**_write_world(Path(tmp))).set_index("MatchId")

    assert list(matches.columns) == [c for c in european.COLUMNS if c != "MatchId"]
    assert len(matches) == 3  # nothing from 20-21

    psv = matches.loc["4723905"]
    assert (psv["HomeTeam"], psv["AwayTeam"]) == ("PSV Eindhoven", "Juventus")
    assert (psv["HomeLeague"], psv["AwayLeague"]) == ("X:NED", "I1")
    assert (psv["FTHG"], psv["FTAG"], psv["FTR"]) == (2, 1, "H")
    assert (psv["AETHG"], psv["AETAG"]) == (3, 1)
    assert psv["TieWinner"] == "PSV Eindhoven" and pd.isna(psv["PenWinner"])
    assert (psv["Neutral"], psv["Leg"], psv["XGSource"]) == (0, 2, "FotMob")

    shakhtar = matches.loc["1"]
    assert shakhtar["Neutral"] == 1
    assert shakhtar["HomeLeague"] == "X:UKR"
    assert pd.isna(shakhtar["AETHG"]) and pd.isna(shakhtar["XGSource"])

    assert matches.loc["2", "Neutral"] == 0


def test_load_european_needs_a_country_for_every_club():
    with tempfile.TemporaryDirectory() as tmp:
        world = _write_world(Path(tmp))
        teams = pd.read_csv(world["teams_path"])
        teams.loc[teams["FotMobId"] == 6069, "Country"] = None
        teams.to_csv(world["teams_path"], index=False)

        try:
            european.load_european(**world)
            raise AssertionError("expected a club without a country to raise")
        except ValueError as exc:
            assert "Shakhtar Donetsk" in str(exc)


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
