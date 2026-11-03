"""
Tests for team identity (team_names, tools/suggest_aliases).

    python tests/test_team_names.py     (or pytest tests/)
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "tools"))

from team_names import (
    REFERENCE_COLUMNS,
    load_alias_map,
    load_country_map,
    load_id_map,
)
from suggest_aliases import check, match_team_names, merge

REFERENCE = ROOT / "data" / "reference" / "team_names.csv"


def test_reference_has_the_schema_and_lookups():
    assert list(pd.read_csv(REFERENCE).columns) == REFERENCE_COLUMNS

    alias = load_alias_map(REFERENCE)
    assert alias["Man City"] == "Manchester City"

    assert load_id_map(reference_path=REFERENCE)[9825] == "Arsenal"
    assert load_id_map("football_data_org_id", REFERENCE)[57] == "Arsenal"
    assert load_country_map(REFERENCE)["Arsenal"] == "ENG"


def test_committed_reference_passes_its_own_checks():
    assert check(pd.read_csv(REFERENCE)) == []


def test_voting_pairs_names_on_date_and_score():
    fd = pd.DataFrame({
        "day": ["2024-08-17", "2024-08-17", "2024-08-24"],
        "home": ["Ath Bilbao", "Betis", "Getafe"],
        "away": ["Getafe", "Girona", "Ath Bilbao"],
        "hg": [1, 1, 0], "ag": [1, 2, 3],
    })
    # The other source records kick-off a day later (UTC vs local)
    other = fd.assign(
        day=["2024-08-18", "2024-08-18", "2024-08-25"],
        home=["Athletic Club", "Real Betis", "Getafe CF"],
        away=["Getafe CF", "Girona FC", "Athletic Club"],
    )

    mapping = match_team_names(fd, other)

    assert {name: club for name, (club, _) in mapping.items()} == {
        "Athletic Club": "Ath Bilbao", "Getafe CF": "Getafe",
        "Real Betis": "Betis", "Girona FC": "Girona",
    }
    assert mapping["Athletic Club"][1] == 2


def test_merge_fills_gaps_and_reports_conflicts():
    reference = pd.DataFrame(
        [{"canonical_name": "Arsenal", "football_data_name": "Arsenal",
          "fotmob_name": "Arsenal", "country": None, "fotmob_id": None}]
    ).reindex(columns=REFERENCE_COLUMNS).astype(object)

    merged, conflicts = merge(reference, [
        {"football_data_name": "Arsenal", "country": "ENG",
         "fotmob_id": 9825, "fotmob_name": "Arsenal FC"},
        {"football_data_name": "Betis", "country": "ESP",
         "fotmob_id": 8603, "fotmob_name": "Real Betis"},
    ])

    assert merged.at[0, "country"] == "ENG"
    assert merged.at[0, "fotmob_id"] == 9825
    assert merged.at[0, "fotmob_name"] == "Arsenal"  # kept, not overwritten
    assert len(conflicts) == 1 and "fotmob_name" in conflicts[0]
    assert merged.at[1, "canonical_name"] == "Real Betis"


def test_check_catches_shared_aliases_and_ids():
    reference = pd.DataFrame([
        {"canonical_name": "Inter", "football_data_name": "Inter", "fotmob_id": 1},
        {"canonical_name": "Internacional", "football_data_name": "Inter", "fotmob_id": 1},
    ]).reindex(columns=REFERENCE_COLUMNS)

    problems = check(reference)

    assert any("alias 'Inter'" in p for p in problems)
    assert any("fotmob_id 1" in p for p in problems)


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
