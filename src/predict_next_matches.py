import pandas as pd
import numpy as np

from collections import defaultdict
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

from team_names import load_alias_map, normalize_team_names


# ============================================================
# CONFIGURATION
# ============================================================

HOME_ADVANTAGE = 130
UPDATE_SIZE = 35

FEATURES = [
    "EloDiff",
    "XGDDiffLast5",
    "GoalsPerGameDiff"
]


# ============================================================
# ELO
# ============================================================

def expected_result(r_home, r_away):

    return 1 / (
        1 +
        10 ** (
            -(r_home + HOME_ADVANTAGE - r_away) / 400
        )
    )


def new_rating(old_rating, actual_score, expected_score):

    return old_rating + UPDATE_SIZE * (
        actual_score - expected_score
    )


def build_elo_feature(matches):

    elos = {}

    def get_elo(team):

        if team not in elos:
            elos[team] = 1500

        return elos[team]

    home_elo_feature = []
    away_elo_feature = []
    elo_diff_feature = []

    for _, current_match in matches.iterrows():

        home_team = current_match["HomeTeam"]
        away_team = current_match["AwayTeam"]

        home_elo = get_elo(home_team)
        away_elo = get_elo(away_team)

        home_elo_feature.append(home_elo)
        away_elo_feature.append(away_elo)
        elo_diff_feature.append(home_elo - away_elo)

        expected = expected_result(home_elo, away_elo)

        if current_match["FTR"] == "H":
            new_home_elo = new_rating(home_elo, 1, expected)
            new_away_elo = new_rating(away_elo, 0, 1 - expected)

        elif current_match["FTR"] == "D":
            new_home_elo = new_rating(home_elo, 0.5, expected)
            new_away_elo = new_rating(away_elo, 0.5, 1 - expected)

        else:
            new_home_elo = new_rating(home_elo, 0, expected)
            new_away_elo = new_rating(away_elo, 1, 1 - expected)

        elos[home_team] = new_home_elo
        elos[away_team] = new_away_elo

    matches["HomeElo"] = home_elo_feature
    matches["AwayElo"] = away_elo_feature
    matches["EloDiff"] = elo_diff_feature

    return elos


# ============================================================
# GOALS PER GAME
# ============================================================

def calculate_season_stats(previous_matches, team):

    if len(previous_matches) == 0:

        return {
            "games": 0,
            "points": 0,
            "ppg": 0,
            "goals_pg": 0,
            "goals_against_pg": 0,
            "gd_pg": 0
        }

    games = len(previous_matches)

    points = 0
    goals_for = 0
    goals_against = 0

    for match in previous_matches:

        if match["HomeTeam"] == team:

            goals_for += match["FTHG"]
            goals_against += match["FTAG"]

            if match["FTR"] == "H":
                points += 3
            elif match["FTR"] == "D":
                points += 1

        else:

            goals_for += match["FTAG"]
            goals_against += match["FTHG"]

            if match["FTR"] == "A":
                points += 3
            elif match["FTR"] == "D":
                points += 1

    return {
        "games": games,
        "points": points,
        "ppg": points / games,
        "goals_pg": goals_for / games,
        "goals_against_pg": goals_against / games,
        "gd_pg": (goals_for - goals_against) / games
    }


def build_goals_per_game_feature(matches):

    season_history = defaultdict(lambda: defaultdict(list))

    home_goals_pg = []
    away_goals_pg = []

    for _, current_match in matches.iterrows():

        season = current_match["Season"]

        home_team = current_match["HomeTeam"]
        away_team = current_match["AwayTeam"]

        home_previous = season_history[season][home_team]
        away_previous = season_history[season][away_team]

        home_stats = calculate_season_stats(home_previous, home_team)
        away_stats = calculate_season_stats(away_previous, away_team)

        home_goals_pg.append(home_stats["goals_pg"])
        away_goals_pg.append(away_stats["goals_pg"])

        # Add AFTER calculating features
        season_history[season][home_team].append(current_match)
        season_history[season][away_team].append(current_match)

    matches["HomeGoalsPerGame"] = home_goals_pg
    matches["AwayGoalsPerGame"] = away_goals_pg

    matches["GoalsPerGameDiff"] = (
        matches["HomeGoalsPerGame"]
        -
        matches["AwayGoalsPerGame"]
    )


# ============================================================
# XG DIFFERENCE - LAST 5
# ============================================================

def calculate_team_xgd_last5(last5, team):

    if not last5:
        return 0

    xgf = []
    xga = []

    for match in last5:

        if match["HomeTeam"] == team:
            xgf.append(match["HomeXG"])
            xga.append(match["AwayXG"])

        else:
            xgf.append(match["AwayXG"])
            xga.append(match["HomeXG"])

    # Remove missing xG values
    valid = [
        (for_xg, against_xg)
        for for_xg, against_xg in zip(xgf, xga)
        if pd.notna(for_xg) and pd.notna(against_xg)
    ]

    if not valid:
        return 0

    xgf = [x[0] for x in valid]
    xga = [x[1] for x in valid]

    return np.mean(xgf) - np.mean(xga)


def build_xgd_last5_feature(matches):

    team_history = defaultdict(list)

    xgd_last5_diff = []

    for _, current_match in matches.iterrows():

        home_team = current_match["HomeTeam"]
        away_team = current_match["AwayTeam"]

        home_last5 = team_history[home_team][-5:]
        away_last5 = team_history[away_team][-5:]

        home_xgd = calculate_team_xgd_last5(home_last5, home_team)
        away_xgd = calculate_team_xgd_last5(away_last5, away_team)

        xgd_last5_diff.append(home_xgd - away_xgd)

        # Add AFTER calculating features
        team_history[home_team].append(current_match)
        team_history[away_team].append(current_match)

    matches["XGDDiffLast5"] = xgd_last5_diff

    return team_history


# ============================================================
# MODEL
# ============================================================

def train_model(matches):

    X_train = matches[FEATURES]
    y_train = matches["FTR"]

    model = LogisticRegression(max_iter=2000, random_state=42)

    calibrated_model = CalibratedClassifierCV(
        estimator=model,
        method="sigmoid",
        cv=5
    )

    calibrated_model.fit(X_train, y_train)

    return calibrated_model


# ============================================================
# PREDICT FUTURE FIXTURES
# ============================================================

def build_future_features(future, elos, team_history):

    future_features = []

    for _, match in future.iterrows():

        home_team = match["HomeTeam"]
        away_team = match["AwayTeam"]

        home_elo = elos.get(home_team, 1500)
        away_elo = elos.get(away_team, 1500)

        elo_diff = home_elo - away_elo

        home_last5 = team_history[home_team][-5:]
        away_last5 = team_history[away_team][-5:]

        home_xgd = calculate_team_xgd_last5(home_last5, home_team)
        away_xgd = calculate_team_xgd_last5(away_last5, away_team)

        xgd_diff = home_xgd - away_xgd

        # Resets at the beginning of each season, so not
        # meaningful this early - matches notebook behaviour
        goals_per_game_diff = 0

        future_features.append({
            "EloDiff": elo_diff,
            "XGDDiffLast5": xgd_diff,
            "GoalsPerGameDiff": goals_per_game_diff
        })

    return pd.DataFrame(future_features)


PROB_COLUMNS = {"H": "HomeProb", "D": "DrawProb", "A": "AwayProb"}


def build_history(matches):
    """
    Build the chronological features on a copy of ``matches`` and return
    ``(matches, elos, team_history)`` - the end-of-history Elo ratings and
    per-team match history needed to score upcoming fixtures.
    """

    matches = matches.sort_values("MatchDateTime").reset_index(drop=True).copy()

    elos = build_elo_feature(matches)
    build_goals_per_game_feature(matches)
    team_history = build_xgd_last5_feature(matches)

    return matches, elos, team_history


def predict_fixtures(fixtures, model, elos, team_history):
    """
    Score ``fixtures`` (needs Date, Time, HomeTeam, AwayTeam - already
    normalised) with a trained model. Returns a results frame with the
    features, the predicted result and H/D/A probabilities (as percentages).
    """

    features = build_future_features(fixtures, elos, team_history)

    results = fixtures[["Date", "Time", "HomeTeam", "AwayTeam"]].copy()
    results[FEATURES] = features[FEATURES].round(2)
    results["Prediction"] = model.predict(features[FEATURES])

    probabilities = model.predict_proba(features[FEATURES])

    for i, class_name in enumerate(model.classes_):
        results[PROB_COLUMNS[class_name]] = probabilities[:, i] * 100

    results[list(PROB_COLUMNS.values())] = results[
        list(PROB_COLUMNS.values())
    ].round(1)

    return results


def predict_next_matches(
    matches_path="data/processed/all_matches.csv",
    fixtures_path="data/raw/Future_Fixtures.csv"
):

    matches = pd.read_csv(matches_path)
    matches["MatchDateTime"] = pd.to_datetime(matches["MatchDateTime"])

    matches, elos, team_history = build_history(matches)

    calibrated_model = train_model(matches)

    future = pd.read_csv(fixtures_path)

    alias_map = load_alias_map()

    future["HomeTeam"] = normalize_team_names(
        future["HomeTeam"], alias_map, source_name=fixtures_path
    )
    future["AwayTeam"] = normalize_team_names(
        future["AwayTeam"], alias_map, source_name=fixtures_path
    )

    return predict_fixtures(future, calibrated_model, elos, team_history)

def add_bets(predictions, bets_path="data/raw/Bets.csv"):

    bets = pd.read_csv(bets_path)

    predictions = predictions.rename(columns={"Prediction": "PredictedResult"})
    predictions = predictions.assign(Div="E0")

    # Carry the probabilities through if the caller supplied them
    for column in PROB_COLUMNS.values():
        if column not in predictions.columns:
            predictions[column] = pd.NA

    key = ["Div", "Date", "Time", "HomeTeam", "AwayTeam"]

    alias_map = load_alias_map()

    bets_key = bets[key].copy()
    bets_key["HomeTeam"] = bets_key["HomeTeam"].replace(alias_map)
    bets_key["AwayTeam"] = bets_key["AwayTeam"].replace(alias_map)

    existing = set(map(tuple, bets_key.to_numpy()))

    is_new = [
        tuple(row) not in existing
        for row in predictions[key].to_numpy()
    ]

    new_bets = predictions[is_new]

    if new_bets.empty:
        print("No new bets to add.")
        return

    with open(bets_path, encoding="utf-8") as f:
        needs_newline = not f.read().endswith("\n")

    # Append only, so existing rows keep their exact formatting
    with open(bets_path, "a", encoding="utf-8", newline="") as f:

        if needs_newline:
            f.write("\n")

        new_bets.reindex(columns=bets.columns).to_csv(
            f, header=False, index=False
        )

    print(f"Added {len(new_bets)} new bet(s) to {bets_path}:")
    print(new_bets[key + ["PredictedResult"]].to_string(index=False))


def print_predictions(results):

    print()
    print("=" * 110)
    print("NEXT GAMEWEEK PREDICTIONS")
    print("=" * 110)

    print(
        results[
            [
                "Date",
                "Time",
                "HomeTeam",
                "AwayTeam",
            ]
            + FEATURES
            + [
                "Prediction",
                "HomeProb",
                "DrawProb",
                "AwayProb"
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":

    results = predict_next_matches()
    add_bets(
        results[
            ["Date", "Time", "HomeTeam", "AwayTeam", "Prediction"]
            + list(PROB_COLUMNS.values())
        ]
    )
    print_predictions(results)

