"""
The prediction model: which features it uses, how it's trained, and how
it scores upcoming fixtures.
"""

from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

from features import build_future_features


FEATURES = [
    "EloDiff",
    "XGDDiffLast5",
    "GoalsPerGameDiff"
]

PROB_COLUMNS = {"H": "HomeProb", "D": "DrawProb", "A": "AwayProb"}


# ============================================================
# MODEL
# ============================================================

def make_model():
    """The unfitted model, for evaluate.walk_forward."""

    model = LogisticRegression(max_iter=2000, random_state=42)

    return CalibratedClassifierCV(
        estimator=model,
        method="sigmoid",
        cv=5
    )


def train_model(matches):

    X_train = matches[FEATURES]
    y_train = matches["FTR"]

    calibrated_model = make_model()

    calibrated_model.fit(X_train, y_train)

    return calibrated_model


# ============================================================
# PREDICT FIXTURES
# ============================================================

def predict_fixtures(fixtures, model, elos, team_history):
    """
    Score ``fixtures`` (needs Date, Time, HomeTeam, AwayTeam - already
    normalised; Gameweek optional) with a trained model. Returns a results
    frame with the features, the predicted result and H/D/A probabilities
    (as percentages).
    """

    features = build_future_features(fixtures, elos, team_history)

    base_columns = ["Date", "Time", "HomeTeam", "AwayTeam"]
    if "Gameweek" in fixtures.columns:
        base_columns = ["Gameweek"] + base_columns

    results = fixtures[base_columns].copy()
    results[FEATURES] = features[FEATURES].round(2)
    results["Prediction"] = model.predict(features[FEATURES])

    probabilities = model.predict_proba(features[FEATURES])

    for i, class_name in enumerate(model.classes_):
        results[PROB_COLUMNS[class_name]] = probabilities[:, i] * 100

    results[list(PROB_COLUMNS.values())] = results[
        list(PROB_COLUMNS.values())
    ].round(1)

    return results
