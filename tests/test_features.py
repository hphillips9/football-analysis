"""
Tests for competition-scoped features and the pooled model's league
columns.

    python tests/test_features.py     (or pytest tests/)
"""

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features import build_future_features, build_history
from model import FEATURES, model_features, predict_fixtures, train_model, train_models
from model import POOLED as POOLED_KEY

FEATURE_COLUMNS = [
    "HomeElo", "AwayElo", "EloDiff",
    "HomeGoalsPerGame", "AwayGoalsPerGame", "GoalsPerGameDiff",
    "XGDDiffLast5",
]
TEAMS = ["Arsenal", "Chelsea", "Everton", "Fulham"]


def _league(div, seed, minutes):
    """Two seasons of double round-robin. Every league reuses TEAMS, the
    worst case for leakage between competitions."""

    rng = np.random.default_rng(seed)
    rows = []

    for season, start in [("21-22", "2021-08-14"), ("22-23", "2022-08-13")]:
        fixtures = list(itertools.permutations(TEAMS, 2))
        for week, (home, away) in enumerate(fixtures):
            goals = rng.integers(0, 4, size=2)
            rows.append({
                "Div": div,
                "Season": season,
                # Offset so the leagues interleave in time
                "MatchDateTime": pd.Timestamp(start) + pd.Timedelta(days=7 * week, minutes=minutes),
                "HomeTeam": home,
                "AwayTeam": away,
                "FTHG": goals[0],
                "FTAG": goals[1],
                "FTR": "H" if goals[0] > goals[1] else "A" if goals[0] < goals[1] else "D",
                "HomeXG": round(rng.uniform(0.3, 2.5), 2),
                "AwayXG": round(rng.uniform(0.3, 2.5), 2),
            })

    return pd.DataFrame(rows)


E0 = _league("E0", seed=1, minutes=0)
SP1 = _league("SP1", seed=2, minutes=90)
POOLED = pd.concat([E0, SP1], ignore_index=True)


def _e0_features(matches, scope="competition"):
    built, _, _ = build_history(matches, scope=scope)
    return built[built["Div"] == "E0"][FEATURE_COLUMNS].reset_index(drop=True)


def test_e0_features_unchanged_by_other_leagues_rows():
    pd.testing.assert_frame_equal(_e0_features(POOLED), _e0_features(E0), check_exact=True)

    # Without the scope the same frame does leak, so the check above has teeth
    assert not _e0_features(POOLED, scope="all").equals(_e0_features(E0))


def test_fixture_features_use_their_own_competition():
    fixtures = pd.DataFrame({
        "Div": ["E0", "SP1"],
        "Date": ["20/08/2022"] * 2,
        "Time": ["15:00"] * 2,
        "HomeTeam": ["Arsenal"] * 2,
        "AwayTeam": ["Chelsea"] * 2,
    })

    _, pooled_elos, pooled_history = build_history(POOLED)
    pooled = build_future_features(fixtures, pooled_elos, pooled_history)

    for div, league in [("E0", E0), ("SP1", SP1)]:
        _, elos, history = build_history(league)
        alone = build_future_features(fixtures[fixtures["Div"] == div], elos, history)
        row = pooled[pooled["Div"] == div].reset_index(drop=True)
        # Elo is reported one rating per team, so compare the form features
        pd.testing.assert_frame_equal(
            row[["XGDDiffLast5", "GoalsPerGameDiff"]],
            alone[["XGDDiffLast5", "GoalsPerGameDiff"]],
            check_exact=True,
        )

    # No Div on the fixtures is fine for one competition, ambiguous for two
    no_div = fixtures.drop(columns="Div").head(1)
    _, elos, history = build_history(E0)
    assert build_future_features(no_div, elos, history)["Div"].tolist() == ["E0"]
    try:
        build_future_features(no_div, pooled_elos, pooled_history)
        raise AssertionError("expected a ValueError for fixtures without Div")
    except ValueError:
        pass


def test_league_columns_only_for_leagues_in_training():
    e0_history, _, _ = build_history(E0)
    assert model_features(train_model(e0_history)) == FEATURES

    history, elos, team_history = build_history(POOLED)
    model = train_model(history)
    assert model_features(model) == FEATURES + ["League_SP1"]

    fixtures = pd.DataFrame({
        "Div": ["E0", "SP1"],
        "Date": ["20/08/2022"] * 2,
        "Time": ["15:00"] * 2,
        "HomeTeam": ["Arsenal"] * 2,
        "AwayTeam": ["Chelsea"] * 2,
    })
    scored = predict_fixtures(fixtures, model, elos, team_history)
    assert scored[["HomeProb", "DrawProb", "AwayProb"]].sum(axis=1).round().eq(100).all()

    try:
        predict_fixtures(fixtures.assign(Div="I1"), model, elos, team_history)
        raise AssertionError("expected a ValueError for a league with no training data")
    except ValueError:
        pass


def test_train_models_gives_e0_its_own_model_and_pools_the_rest():
    fixtures = pd.DataFrame({
        "Div": ["E0", "SP1"],
        "Date": ["20/08/2022"] * 2,
        "Time": ["15:00"] * 2,
        "HomeTeam": ["Arsenal"] * 2,
        "AwayTeam": ["Chelsea"] * 2,
    })
    probs = ["HomeProb", "DrawProb", "AwayProb"]

    history, elos, team_history = build_history(POOLED)
    models = train_models(history)
    assert set(models) == {"E0", POOLED_KEY}

    scored = predict_fixtures(fixtures, models, elos, team_history)

    # E0 is scored exactly as by a model trained on E0 alone...
    e0_only = train_model(history[history["Div"] == "E0"])
    alone = predict_fixtures(fixtures.head(1), e0_only, elos, team_history)
    assert scored.loc[[0], probs].equals(alone[probs])

    # ...and SP1 by the pooled model
    pooled = predict_fixtures(fixtures.tail(1), train_model(history), elos, team_history)
    assert scored.loc[[1], probs].equals(pooled[probs])

    # A Premier-League-only history trains just the original model
    e0_history, _, _ = build_history(E0)
    assert set(train_models(e0_history)) == {"E0"}

    # No E0 rows: no E0 model, and an E0 fixture can't fall through to the pooled one
    sp1_history, sp1_elos, sp1_team_history = build_history(SP1)
    sp1_models = train_models(sp1_history)
    assert set(sp1_models) == {POOLED_KEY}
    try:
        predict_fixtures(fixtures.head(1), sp1_models, sp1_elos, sp1_team_history)
        raise AssertionError("expected a ValueError for E0 without an E0 model")
    except ValueError:
        pass


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
