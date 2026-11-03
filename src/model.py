"""
The prediction model: which features it uses, how it's trained, and how
it scores upcoming fixtures.
"""

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

import competitions
from elo import DEFAULT_SCOPE
from features import build_future_features


FEATURES = [
    "EloDiff",
    "XGDDiffLast5",
    "GoalsPerGameDiff"
]

PROB_COLUMNS = {"H": "HomeProb", "D": "DrawProb", "A": "AwayProb"}

# One pooled model covers every league (notebook 18). A 0/1 League_<Div>
# column per league lets it shift each league's home/draw/away balance;
# the baseline league has none.
BASELINE_LEAGUE = "E0"
LEAGUE_COLUMNS = {
    div: f"League_{div}"
    for div, entry in competitions.COMPETITIONS.items()
    if entry["kind"] == "league" and div != BASELINE_LEAGUE
}


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


def league_columns(frame, divs=None):
    """
    ``frame`` plus a League_<Div> column for each league in ``divs``
    (default: every non-baseline league in the frame's Div column). A
    frame without a Div column is all baseline league.
    """

    div = frame["Div"] if "Div" in frame.columns else pd.Series(BASELINE_LEAGUE, index=frame.index)

    if divs is None:
        divs = [d for d in LEAGUE_COLUMNS if (div == d).any()]

    return frame.assign(**{
        LEAGUE_COLUMNS[d]: (div == d).astype(int) for d in divs
    })


def model_features(model):
    """The columns a trained model takes: FEATURES + its league columns."""

    return list(model.feature_names_in_)


def train_model(matches):
    """
    Fit on FEATURES plus a league column for each non-baseline league in
    ``matches`` - none for a Premier-League-only history, so that model
    is exactly the original one.
    """

    with_leagues = league_columns(matches)
    columns = FEATURES + [c for c in LEAGUE_COLUMNS.values() if c in with_leagues.columns]

    X_train = with_leagues[columns]
    y_train = matches["FTR"]

    calibrated_model = make_model()

    calibrated_model.fit(X_train, y_train)

    return calibrated_model


# ============================================================
# PREDICT FIXTURES
# ============================================================

def predict_fixtures(fixtures, model, elos, team_history, scope=DEFAULT_SCOPE):
    """
    Score ``fixtures`` (needs Date, Time, HomeTeam, AwayTeam - already
    normalised; Gameweek and Div optional, Div needed when the history
    spans several competitions) with a trained model. Returns a results
    frame with the features, the predicted result and H/D/A probabilities
    (as percentages).
    """

    features = build_future_features(fixtures, elos, team_history, scope=scope)

    columns = model_features(model)
    trained_leagues = [d for d, c in LEAGUE_COLUMNS.items() if c in columns]
    unknown = set(features["Div"]) - set(trained_leagues) - {BASELINE_LEAGUE, ""}

    if unknown:
        raise ValueError(
            f"No training data for {', '.join(sorted(unknown))} - can't predict its fixtures."
        )

    X = league_columns(features, trained_leagues)[columns]

    base_columns = ["Date", "Time", "HomeTeam", "AwayTeam"]
    if "Gameweek" in fixtures.columns:
        base_columns = ["Gameweek"] + base_columns

    results = fixtures[base_columns].copy()
    results[FEATURES] = features[FEATURES].round(2)
    results["Prediction"] = model.predict(X)

    probabilities = model.predict_proba(X)

    for i, class_name in enumerate(model.classes_):
        results[PROB_COLUMNS[class_name]] = probabilities[:, i] * 100

    results[list(PROB_COLUMNS.values())] = results[
        list(PROB_COLUMNS.values())
    ].round(1)

    return results
