"""
Predict the next round of fixtures and record the bets.

    python src/predict_next_matches.py

The Elo, feature and model code lives in elo.py, features.py and
model.py. Their public names are re-exported here so existing imports
(the pipeline scripts and notebooks 16-19) keep working unchanged.
"""

import pandas as pd

from bet_schema import BET_KEY, round_for, season_for
from european import results_for_elo
from team_names import load_alias_map, normalize_team_names

from elo import (  # noqa: F401 - re-exported
    HOME_ADVANTAGE,
    UPDATE_SIZE,
    PROMOTED_ELO,
    expected_result,
    new_rating,
    build_elo_feature,
)
from features import (  # noqa: F401 - re-exported
    calculate_season_stats,
    build_goals_per_game_feature,
    calculate_team_xgd_last5,
    build_xgd_last5_feature,
    build_future_features,
    build_history,
)
from model import (  # noqa: F401 - re-exported
    FEATURES,
    PROB_COLUMNS,
    make_model,
    train_model,
    train_models,
    predict_fixtures,
)


BETS_PATH = "data/raw/Bets.csv"


# ============================================================
# PREDICT THE NEXT ROUND
# ============================================================

def infer_gameweek(fixtures, matches, bets_path=BETS_PATH):
    """
    Best guess at the gameweek for a batch of upcoming fixtures.

    Dates alone don't pin a gameweek down (midweek + weekend rounds,
    postponements), so the signal used is: one more than the highest
    gameweek already seen this season - across both played matches and
    fixtures already sitting in Bets.csv. If this exact batch is already
    recorded, its stored gameweek is reused. An explicit "GW<n>" line at
    the top of Next_Matchweek.txt overrides all of this (handled in
    future_games_parser).

    Each competition counts its own gameweeks, so ``matches`` and the
    bets are narrowed to the fixtures' Div where both carry one.
    """

    if "Div" in fixtures.columns and "Div" in matches.columns:
        matches = matches[matches["Div"].isin(set(fixtures["Div"]))]

    ordered = matches.sort_values("MatchDateTime")
    latest_season = ordered["Season"].iloc[-1]
    latest_played = ordered["MatchDateTime"].max()

    counter = ordered.loc[ordered["Season"] == latest_season, "Gameweek"].max()
    counter = int(counter) if pd.notna(counter) else 0

    try:
        bets = pd.read_csv(bets_path)
        if "Div" in fixtures.columns:
            bets = bets[bets["Div"].isin(set(fixtures["Div"]))]
        bets_when = pd.to_datetime(
            bets["Date"] + " " + bets["Time"], dayfirst=True
        )

        # This exact batch already recorded -> reuse its gameweek
        recorded = fixtures.merge(
            bets[["Date", "HomeTeam", "AwayTeam", "Gameweek"]],
            on=["Date", "HomeTeam", "AwayTeam"],
            how="left",
        )["Gameweek"]

        if recorded.notna().all():
            return recorded.astype(int).to_numpy()

        # Otherwise pending bets (after the last played match) advance the count
        pending = bets.loc[bets_when > latest_played, "Gameweek"].dropna()
        if len(pending):
            counter = max(counter, int(pending.max()))

    except (FileNotFoundError, KeyError):
        pass

    return pd.Series(counter + 1, index=fixtures.index)


def load_model(matches_path="data/processed/all_matches.csv"):
    """
    Build the features over the whole match history and train on it.
    Returns ``(matches, models, elos, team_history)`` for predict_round
    (models as model.train_models gives them).
    """

    matches = pd.read_csv(matches_path)
    matches["MatchDateTime"] = pd.to_datetime(matches["MatchDateTime"])

    matches, elos, team_history = build_history(
        matches, european=results_for_elo(matches)
    )

    models = train_models(matches)

    return matches, models, elos, team_history


def predict_round(future, trained, source_name="Future_Fixtures.csv"):
    """
    Score upcoming fixtures with load_model's output. Names are
    normalised and a missing Gameweek inferred; the Div is carried
    through when the fixtures have one.
    """

    matches, models, elos, team_history = trained

    future = future.copy()

    alias_map = load_alias_map()

    future["HomeTeam"] = normalize_team_names(
        future["HomeTeam"], alias_map, source_name=source_name
    )
    future["AwayTeam"] = normalize_team_names(
        future["AwayTeam"], alias_map, source_name=source_name
    )

    if "Gameweek" not in future.columns or future["Gameweek"].isna().any():
        future["Gameweek"] = infer_gameweek(future, matches)

    results = predict_fixtures(future, models, elos, team_history)

    if "Div" in future.columns:
        results.insert(0, "Div", future["Div"].to_numpy())

    return results


def predict_next_matches(
    matches_path="data/processed/all_matches.csv",
    fixtures_path="data/raw/Future_Fixtures.csv"
):

    return predict_round(
        pd.read_csv(fixtures_path), load_model(matches_path), source_name=fixtures_path
    )

def add_bets(predictions, bets_path=BETS_PATH):

    bets = pd.read_csv(bets_path)

    predictions = predictions.rename(columns={"Prediction": "PredictedResult"})
    if "Div" not in predictions.columns:
        predictions = predictions.assign(Div="E0")

    # Carry the gameweek and probabilities through if the caller supplied them
    for column in ["Gameweek", *PROB_COLUMNS.values()]:
        if column not in predictions.columns:
            predictions[column] = pd.NA

    if "Season" not in predictions.columns:
        predictions["Season"] = season_for(predictions["Date"])
    if "Round" not in predictions.columns:
        predictions["Round"] = round_for(predictions["Gameweek"])

    key = BET_KEY

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
        return 0

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
    print(
        new_bets[["Div", "Date", "Time", "HomeTeam", "AwayTeam", "PredictedResult"]]
        .to_string(index=False)
    )

    return len(new_bets)


def print_predictions(results):

    print()
    print("=" * 110)
    print("NEXT GAMEWEEK PREDICTIONS")
    print("=" * 110)

    columns = ["Date", "Time", "HomeTeam", "AwayTeam"]
    if "Gameweek" in results.columns:
        columns = ["Gameweek"] + columns

    print(
        results[
            columns
            + FEATURES
            + ["Prediction", "HomeProb", "DrawProb", "AwayProb"]
        ].to_string(index=False)
    )


if __name__ == "__main__":

    results = predict_next_matches()
    add_bets(
        results[
            [c for c in ["Div"] if c in results.columns]
            + ["Gameweek", "Date", "Time", "HomeTeam", "AwayTeam", "Prediction"]
            + list(PROB_COLUMNS.values())
        ]
    )
    print_predictions(results)

