"""
Tests for the Champions League path (P5-01): CL rows in the match
history leave every league feature unchanged, CL rows get shared-scale
Elo and CL-only form, football-data.org fixtures pair with FotMob's
clubs, and a neutral venue is scored both ways round.

    python tests/test_champions_league.py     (or pytest tests/)
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import champions_league as cl
from elo import entrant_rating, shared_scale
from european import load_european
from features import _as_european, build_future_features, build_history
from load_data import CUP_KICKOFF, build_cup_rows, read_matches
from model import EUROPEAN as EUROPEAN_KEY
from model import (
    EUROPEAN_FEATURES, POOLED, european_columns, league_columns, model_features,
    predict_fixtures, train_european_model, train_models,
)
from test_european import _write_world
from test_features import FEATURE_COLUMNS, POOLED

# CL rows: the synthetic E0 and SP1 clubs meeting in midweek. Both
# leagues reuse the same four names, so "Arsenal" is two clubs - the
# CL rows say which through HomeLeague/AwayLeague, as the real ones do.
CL_FIXTURES = [
    # (date, home, home league, away, away league, FTHG, FTAG, xG home, xG away)
    ("2021-09-15", "Arsenal", "E0", "Chelsea", "SP1", 2, 0, 1.9, 0.4),
    ("2021-09-15", "Everton", "SP1", "Fulham", "E0", 1, 1, 1.1, 1.0),
    ("2021-10-20", "Chelsea", "SP1", "Arsenal", "E0", 0, 3, 0.5, 2.6),
    ("2021-10-20", "Fulham", "E0", "Everton", "SP1", 2, 1, 1.7, 0.9),
    ("2022-03-09", "Arsenal", "E0", "Everton", "SP1", 1, 2, 1.2, 1.4),
    ("2022-10-12", "Chelsea", "SP1", "Fulham", "E0", 4, 1, 2.8, 0.7),
]


def _cl_rows():

    rows = []

    for n, (day, home, home_league, away, away_league, hg, ag, hxg, axg) in enumerate(CL_FIXTURES):
        rows.append({
            "Div": "CL",
            "Season": "21-22" if day < "2022-07-01" else "22-23",
            "MatchDateTime": pd.Timestamp(f"{day} {CUP_KICKOFF}"),
            "Stage": "LEAGUE_PHASE", "Round": "MD1", "Leg": pd.NA, "Neutral": 0,
            "MatchId": str(9000 + n),
            "HomeTeam": home, "AwayTeam": away,
            "HomeLeague": home_league, "AwayLeague": away_league,
            "FTHG": hg, "FTAG": ag,
            "FTR": "H" if hg > ag else "A" if hg < ag else "D",
            "HomeXG": hxg, "AwayXG": axg,
        })

    return pd.DataFrame(rows)


CL = _cl_rows()
WITH_CL = pd.concat([POOLED, CL], ignore_index=True)


def _league_features(frame):
    """Each league row's features, keyed so row order can't hide a change."""

    leagues = frame[frame["Div"] != "CL"]
    return (
        leagues.sort_values(["Div", "MatchDateTime", "HomeTeam"])
        [["Div", "MatchDateTime", "HomeTeam", "AwayTeam", *FEATURE_COLUMNS]]
        .reset_index(drop=True)
    )


# ============================================================
# NO LEAKAGE INTO LEAGUE FEATURES
# ============================================================

def test_league_features_unchanged_with_cl_rows():
    european = _as_european(CL)

    without, without_elos, _ = build_history(POOLED, european=european)
    with_cl, with_elos, _ = build_history(WITH_CL, european=european)

    pd.testing.assert_frame_equal(
        _league_features(with_cl), _league_features(without), check_exact=True
    )
    assert dict(with_elos) == dict(without_elos)

    # The CL rows on their own (no European results passed) rate the
    # leagues exactly as the same results passed as ``european``
    implied, _, _ = build_history(WITH_CL)
    pd.testing.assert_frame_equal(
        _league_features(implied), _league_features(without), check_exact=True
    )

    # ...and they do move the league Elo (E2a), so the checks have teeth
    alone, _, _ = build_history(POOLED)
    assert not _league_features(alone)["EloDiff"].equals(_league_features(without)["EloDiff"])


def test_cl_form_comes_from_cl_matches_only():
    built, _, _ = build_history(WITH_CL)
    cl_rows = built[built["Div"] == "CL"].reset_index(drop=True)

    # The first CL match: both sides have weeks of league games behind
    # them, but no CL games yet
    first = cl_rows.iloc[0]
    assert (first["XGDDiffLast5"], first["GoalsPerGameDiff"]) == (0, 0)

    # The third CL match (Chelsea v Arsenal): each side's one CL game
    third = cl_rows.iloc[2]
    assert third["HomeGoalsPerGame"] == 0  # Chelsea lost 2-0
    assert third["AwayGoalsPerGame"] == 2  # Arsenal won 2-0
    assert round(third["XGDDiffLast5"], 6) == round((0.4 - 1.9) - (1.9 - 0.4), 6)


def test_cl_elo_is_the_shared_rating_going_in():
    built, elos, _ = build_history(WITH_CL)
    cl_rows = built[built["Div"] == "CL"].reset_index(drop=True)

    domestic = POOLED.sort_values(["MatchDateTime", "HomeTeam", "AwayTeam"]).reset_index(drop=True)
    expected = shared_scale(domestic, _as_european(CL))["european"]

    assert cl_rows["MatchId"].tolist() == expected["MatchId"].tolist()
    assert cl_rows["HomeElo"].tolist() == expected["HomeElo"].tolist()
    assert (cl_rows["EloDiff"] == cl_rows["HomeElo"] - cl_rows["AwayElo"]).all()
    assert elos.shared  # cup fixtures are rated from these


def test_cl_fixture_uses_shared_rating_and_cl_form():
    _, elos, history = build_history(WITH_CL)
    fixture = pd.DataFrame([{
        "Div": "CL", "Date": "19/10/2022", "Time": "20:00",
        "HomeTeam": "Arsenal", "AwayTeam": "Chelsea",
        "HomeLeague": "E0", "AwayLeague": "SP1",
    }])

    row = build_future_features(fixture, elos, history).iloc[0]

    assert row["EloDiff"] == elos.shared["Arsenal"] - elos.shared["Chelsea"]
    # 22-23 so far: only Chelsea has played a CL game (4-1 v Fulham)
    assert row["GoalsPerGameDiff"] == 0 - 4


def test_new_club_starts_at_its_country_baseline():
    _, elos, history = build_history(WITH_CL)
    fixture = pd.DataFrame([{
        "Div": "CL", "Date": "19/10/2022", "Time": "20:00",
        "HomeTeam": "Arsenal", "AwayTeam": "Newcomers FC",
        "HomeLeague": "E0", "AwayLeague": "X:AZE",
    }])

    row = build_future_features(fixture, elos, history).iloc[0]

    assert row["EloDiff"] == elos.shared["Arsenal"] - entrant_rating("AZE", "22-23")
    assert entrant_rating("AZE", "22-23") < 1500  # below the anchor league


# ============================================================
# NEUTRAL VENUE
# ============================================================

def test_neutral_probabilities_mirror():
    forward = {"H": 0.5, "D": 0.3, "A": 0.2}
    reverse = {"H": 0.4, "D": 0.25, "A": 0.35}

    both = cl.neutral_probabilities(forward, reverse)
    assert both == {"H": (0.5 + 0.35) / 2, "D": (0.3 + 0.25) / 2, "A": (0.2 + 0.4) / 2}
    assert abs(sum(both.values()) - 1) < 1e-12

    flipped = cl.neutral_probabilities(reverse, forward)
    assert (flipped["H"], flipped["D"], flipped["A"]) == (both["A"], both["D"], both["H"])


def test_neutral_fixture_scored_both_ways_round():
    history, elos, team_history = build_history(WITH_CL)
    models = train_models(history[history["Div"] != "CL"])
    # Six synthetic CL rows can't fit a calibrated model; any fitted
    # European model shows the symmetry, so fit one on league rows
    models[EUROPEAN_KEY] = train_european_model(history[history["Div"] != "CL"])

    final = pd.DataFrame([{
        "Div": "CL", "Date": "31/05/2023", "Time": "20:00", "Neutral": 1,
        "HomeTeam": "Arsenal", "AwayTeam": "Chelsea",
        "HomeLeague": "E0", "AwayLeague": "SP1",
    }])
    swapped = final.assign(
        HomeTeam="Chelsea", AwayTeam="Arsenal", HomeLeague="SP1", AwayLeague="E0"
    )

    ab = predict_fixtures(final, models, elos, team_history).iloc[0]
    ba = predict_fixtures(swapped, models, elos, team_history).iloc[0]
    a_at_home = predict_fixtures(final.assign(Neutral=0), models, elos, team_history).iloc[0]
    b_at_home = predict_fixtures(swapped.assign(Neutral=0), models, elos, team_history).iloc[0]

    # Probabilities are rounded to 0.1
    assert abs(ab["HomeProb"] - ba["AwayProb"]) <= 0.1
    assert abs(ab["DrawProb"] - ba["DrawProb"]) <= 0.1
    assert abs(ab["HomeProb"] - (a_at_home["HomeProb"] + b_at_home["AwayProb"]) / 2) <= 0.1
    assert abs(ab["DrawProb"] - (a_at_home["DrawProb"] + b_at_home["DrawProb"]) / 2) <= 0.1


# ============================================================
# THE CL'S EUROPEAN MODEL (notebook 22, setup (c))
# ============================================================

def test_european_model_trains_on_european_rows_only():
    history, _, _ = build_history(WITH_CL)
    # Enough European rows to fit: the CL rows plus league rows relabelled EL
    europe = pd.concat([
        history[history["Div"] == "CL"],
        history[history["Div"] == "SP1"].assign(Div="EL", Stage="LEAGUE_PHASE"),
    ], ignore_index=True)
    leagues = history[history["Div"] != "CL"]

    with_europe = train_models(pd.concat([leagues, europe], ignore_index=True))
    alone = train_models(leagues)

    assert set(with_europe) == set(alone) | {EUROPEAN_KEY}
    assert model_features(with_europe[EUROPEAN_KEY]) == EUROPEAN_FEATURES

    # The league models are exactly the ones trained without European rows
    for key in alone:
        X = league_columns(leagues)[model_features(alone[key])]
        np.testing.assert_array_equal(with_europe[key].predict_proba(X), alone[key].predict_proba(X))


def test_european_columns():
    frame = pd.DataFrame({"Div": ["CL", "EL", "ECL", "CL"], "Stage": ["LEAGUE_PHASE", "R16", "FINAL", "SF"]})
    cols = european_columns(frame)

    assert cols["Comp_EL"].tolist() == [0, 1, 0, 0]
    assert cols["Comp_ECL"].tolist() == [0, 0, 1, 0]
    assert cols["Knockout"].tolist() == [0, 1, 1, 1]


def test_cl_fixture_goes_to_the_european_model():
    _, elos, team_history = build_history(WITH_CL)
    calls = []

    class Recorder:
        feature_names_in_ = np.array(EUROPEAN_FEATURES)
        classes_ = np.array(["A", "D", "H"])

        def predict_proba(self, X):
            calls.append(list(X.columns))
            return np.tile([0.3, 0.3, 0.4], (len(X), 1))

    fixture = pd.DataFrame([{
        "Div": "CL", "Date": "19/10/2022", "Time": "20:00", "Stage": "R16",
        "HomeTeam": "Arsenal", "AwayTeam": "Chelsea", "HomeLeague": "E0", "AwayLeague": "SP1",
    }])
    out = predict_fixtures(fixture, {EUROPEAN_KEY: Recorder()}, elos, team_history)

    assert calls == [EUROPEAN_FEATURES]
    assert out.at[0, "HomeProb"] == 40.0


# ============================================================
# CL BETS
# ============================================================

def test_add_bets_keeps_a_cup_round_and_fills_league_rounds():
    from bet_schema import COLUMN_ORDER
    from predict_next_matches import add_bets

    predictions = pd.DataFrame([
        {"Div": "CL", "Gameweek": pd.NA, "Round": "MD5", "MatchId": "6106339", "Date": "24/11/2026",
         "Time": "17:45", "HomeTeam": "Galatasaray", "AwayTeam": "Aston Villa", "Prediction": "A",
         "HomeProb": 14.9, "DrawProb": 24.9, "AwayProb": 60.2},
        {"Div": "E0", "Gameweek": 13, "Round": pd.NA, "MatchId": pd.NA, "Date": "28/11/2026",
         "Time": "15:00", "HomeTeam": "Everton", "AwayTeam": "Fulham", "Prediction": "H",
         "HomeProb": 45.0, "DrawProb": 27.0, "AwayProb": 28.0},
    ])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Bets.csv"
        pd.DataFrame(columns=COLUMN_ORDER).to_csv(path, index=False)
        assert add_bets(predictions, bets_path=path) == 2
        bets = pd.read_csv(path, dtype={"Round": str, "MatchId": str})

    assert bets["Round"].tolist() == ["MD5", "13"]
    assert bets.at[0, "MatchId"] == "6106339" and pd.isna(bets.at[0, "Gameweek"])


def test_backfill_leaves_cup_bets_alone():
    from backfill_bet_probs import backfill
    from bet_schema import COLUMN_ORDER

    bets = pd.DataFrame([
        {"Season": "26-27", "Div": "E0", "Round": "13", "Gameweek": 13, "Date": "28/11/2026",
         "Time": "15:00", "HomeTeam": "Everton", "AwayTeam": "Fulham", "PredictedResult": "H",
         "HomeProb": 45.0, "DrawProb": 27.0, "AwayProb": 28.0},
        # No gameweek by design
        {"Season": "26-27", "Div": "CL", "Round": "MD5", "MatchId": "6106339", "Date": "24/11/2026",
         "Time": "17:45", "HomeTeam": "Galatasaray", "AwayTeam": "Aston Villa", "PredictedResult": "A",
         "HomeProb": 14.9, "DrawProb": 24.9, "AwayProb": 60.2},
    ]).reindex(columns=COLUMN_ORDER)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Bets.csv"
        bets.to_csv(path, index=False)
        # Nothing to do, so the match history (a path that doesn't exist) is never read
        out = backfill(bets_path=path, matches_path=Path(tmp) / "missing.csv")

    assert out.loc[out["Div"] == "CL", "Gameweek"].isna().all()
    assert out.loc[out["Div"] == "CL", "Round"].tolist() == ["MD5"]


# ============================================================
# STAGES AND FIXTURE PAIRING
# ============================================================

def test_fd_org_stages():
    assert cl.fd_org_round("LEAGUE_STAGE", 5) == ("LEAGUE_PHASE", "MD5", None)
    assert cl.fd_org_round("GROUP_STAGE", 2) == ("GROUP", "MD2", None)
    assert cl.fd_org_round("PLAYOFFS", 1) == ("KO_PLAYOFF", "KO_PLAYOFF", 1)
    assert cl.fd_org_round("LAST_16", 2) == ("R16", "R16", 2)
    assert cl.fd_org_round("FINAL", None) == ("FINAL", "FINAL", None)

    orders = [
        cl.round_order(*cl.fd_org_round(stage, day))
        for stage, day in [("LEAGUE_STAGE", 8), ("PLAYOFFS", 1), ("PLAYOFFS", 2),
                           ("LAST_16", 1), ("SEMI_FINALS", 2), ("FINAL", None)]
    ]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)

    try:
        cl.fd_org_round("THIRD_PLACE", 1)
        raise AssertionError("expected an unknown stage to raise")
    except ValueError as exc:
        assert "THIRD_PLACE" in str(exc)


def _pairing_frames():
    # football-data.org ids 1-2 are known (modelled clubs); 3-5 aren't
    fd = pd.DataFrame({
        "Day": ["d1", "d1", "d2", "d3"],
        "FdHomeId": [1, 3, 4, 5],
        "FdAwayId": [3, 2, 1, 4],
    })
    fotmob = pd.DataFrame({
        "Day": ["d1", "d1", "d2", "d3"],
        "HomeId": [101, 103, 104, 105],
        "AwayId": [103, 102, 101, 104],
        "MatchId": ["m1", "m2", "m3", "m4"],
    }, index=[10, 11, 12, 13])
    return fd, fotmob, {1: 101, 2: 102}


def test_pairing_learns_clubs_outside_the_modelled_leagues():
    fd, fotmob, known = _pairing_frames()

    pairs, learned = cl.pair_matches(fd, fotmob, known)

    assert pairs == {0: 10, 1: 11, 2: 12, 3: 13}
    # 3 from d1, 4 from d2; then 5 v 4 on d3 pairs through the learned 4
    assert learned == {1: 101, 2: 102, 3: 103, 4: 104, 5: 105}


def test_pairing_leaves_out_a_match_fotmob_lacks():
    fd, fotmob, known = _pairing_frames()

    pairs, _ = cl.pair_matches(fd, fotmob.drop(index=12), known)

    assert 2 not in pairs  # d2 isn't in FotMob's list
    assert pairs[3] == 13  # d3: the last match left that day on both sides


def test_resolve_fixtures_names_leagues_and_neutral():
    with tempfile.TemporaryDirectory() as tmp:
        world = _write_world(Path(tmp))

        fd = cl.fd_org_frame([
            {"status": "TIMED", "utcDate": "2025-02-18T20:00:00Z", "stage": "PLAYOFFS",
             "matchday": 2, "homeTeam": {"id": 50, "name": "PSV"},
             "awayTeam": {"id": 109, "name": "Juventus FC"}},
            {"status": "TIMED", "utcDate": "2025-02-19T17:45:00Z", "stage": "LEAGUE_STAGE",
             "matchday": 8, "homeTeam": {"id": 60, "name": "FC Shakhtar Donetsk"},
             "awayTeam": {"id": 109, "name": "Juventus FC"}},
            # not drawn yet: left out
            {"status": "TIMED", "utcDate": "2025-05-31T19:00:00Z", "stage": "FINAL",
             "matchday": None, "homeTeam": {"id": None, "name": None},
             "awayTeam": {"id": None, "name": None}},
        ])
        fotmob = pd.DataFrame([
            {"MatchId": "7001", "Kickoff": "2025-02-18T20:00:00Z", "Round": "playoff",
             "HomeId": 8640, "AwayId": 9885, "HomeTeam": "PSV Eindhoven", "AwayTeam": "Juventus"},
            {"MatchId": "7002", "Kickoff": "2025-02-19T17:45:00Z", "Round": "8",
             "HomeId": 6069, "AwayId": 9885, "HomeTeam": "Shakhtar Donetsk", "AwayTeam": "Juventus"},
        ])
        european_rows = load_european(**world)

        fixtures = cl.resolve_fixtures(
            fd, fotmob, "24-25", known={109: 9885}, domestic=world["domestic"],
            european_rows=european_rows, reference_path=world["reference_path"],
            teams_path=world["teams_path"],
        )

    assert len(fixtures) == 2
    assert fixtures["MatchId"].tolist() == ["7001", "7002"]
    assert fixtures["HomeTeam"].tolist() == ["PSV Eindhoven", "Shakhtar Donetsk"]
    assert fixtures["HomeLeague"].tolist() == ["X:NED", "X:UKR"]
    assert fixtures["AwayLeague"].tolist() == ["I1", "I1"]
    assert fixtures["Stage"].tolist() == ["KO_PLAYOFF", "LEAGUE_PHASE"]
    assert fixtures["Leg"].iloc[0] == 2 and pd.isna(fixtures["Leg"].iloc[1])
    # Shakhtar's last home European match was played abroad
    assert fixtures["Neutral"].tolist() == [0, 1]


# ============================================================
# CL ROWS IN ALL_MATCHES
# ============================================================

def test_cup_rows_carry_the_90_minute_result():
    with tempfile.TemporaryDirectory() as tmp:
        world = _write_world(Path(tmp))
        rows = build_cup_rows(world.pop("domestic"), ["CL"], **world)

    psv = rows[rows["MatchId"] == "4723905"].iloc[0]
    # 3-1 after extra time, 2-1 at 90 minutes
    assert (psv["FTHG"], psv["FTAG"], psv["FTR"]) == (2, 1, "H")
    assert (psv["AETHG"], psv["AETAG"]) == (3, 1)
    assert (psv["Div"], psv["Stage"], psv["Leg"]) == ("CL", "KO_PLAYOFF", 2)
    assert pd.isna(psv["Gameweek"]) and pd.isna(psv["Time"])
    assert psv["MatchDateTime"].strftime("%H:%M") == CUP_KICKOFF
    assert psv["Date"] == pd.Timestamp(psv["MatchDateTime"]).strftime("%d/%m/%Y")


def test_read_matches_leaves_cup_rows_out_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "all_matches.csv"
        leagues = POOLED.assign(Gameweek=1)
        both = pd.concat([leagues, CL], ignore_index=True)
        both["Gameweek"] = both["Gameweek"].astype("Int64")
        both.to_csv(path, index=False)

        default = read_matches(path)
        everything = read_matches(path, cups=True)

    assert len(default) == len(POOLED) and set(default["Div"]) == {"E0", "SP1"}
    assert default["Gameweek"].dtype == int
    assert len(everything) == len(POOLED) + len(CL)
    assert everything.loc[everything["Div"] == "CL", "MatchId"].tolist() == CL["MatchId"].tolist()


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
