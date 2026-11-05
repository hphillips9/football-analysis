"""
The prediction model: which features it uses, how it's trained, and how
it scores upcoming fixtures.

Each competition is predicted by one of two kinds of model, set by its
``model`` entry in competitions.py:

    "pooled"  one model shared by every "pooled" competition, trained on
              every match, with a League_<Div> indicator per league
    "own"     a model trained on that competition's matches alone

Notebook 20: pooling helps La Liga and the Bundesliga but leaves the
Premier League unchanged, and couldn't pass the Premier League's
non-inferiority gate - so E0 keeps its own model (the original one) and
the other leagues share the pooled model.

    "european" the Champions League's: trained on European matches only
              (CL + EL + ECL) with Comp_EL / Comp_ECL / Knockout columns
              - notebook 22's setup (c), chosen 2026-11-05. The league
              models never see European matches.
"""

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

import competitions
from elo import DEFAULT_SCOPE
from evaluate import walk_forward
from champions_league import neutral_probabilities
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

# train_models' key for the shared model
POOLED = "pooled"

# Competitions with a model of their own
OWN_MODEL = [
    div for div, entry in competitions.COMPETITIONS.items() if entry["model"] == "own"
]

# train_models' key for the European model, and what it's trained on
EUROPEAN = "european"
CUPS = [div for div, entry in competitions.COMPETITIONS.items() if entry["kind"] == "cup"]
KNOCKOUT_STAGES = {"KO_PLAYOFF", "R16", "QF", "SF", "FINAL"}
# The CL is the baseline competition
EUROPEAN_FEATURES = FEATURES + ["Comp_EL", "Comp_ECL", "Knockout"]


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


def _divs(frame):
    """A frame's Div column; a frame without one is all baseline league."""

    if "Div" in frame.columns:
        return frame["Div"]

    return pd.Series(BASELINE_LEAGUE, index=frame.index)


def league_columns(frame, divs=None):
    """
    ``frame`` plus a League_<Div> column for each league in ``divs``
    (default: every non-baseline league in the frame's Div column). A
    frame without a Div column is all baseline league.
    """

    div = _divs(frame)

    if divs is None:
        divs = [d for d in LEAGUE_COLUMNS if (div == d).any()]

    return frame.assign(**{
        LEAGUE_COLUMNS[d]: (div == d).astype(int) for d in divs
    })


def european_columns(frame):
    """
    ``frame`` plus the European model's columns: Comp_EL / Comp_ECL (0/1
    from Div) and Knockout (1 for a knockout tie, from Stage; 0 without
    a Stage column).
    """

    div = _divs(frame)
    stage = frame["Stage"] if "Stage" in frame.columns else pd.Series("", index=frame.index)

    return frame.assign(
        Comp_EL=(div == "EL").astype(int),
        Comp_ECL=(div == "ECL").astype(int),
        Knockout=stage.isin(KNOCKOUT_STAGES).astype(int),
    )


def train_european_model(matches):
    """Fit the European model on European matches (CL + EL + ECL rows)."""

    model = make_model()
    model.fit(european_columns(matches)[EUROPEAN_FEATURES], matches["FTR"])

    return model


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


def train_models(matches):
    """
    The models the pipeline predicts with: ``{div: model}`` for each
    OWN_MODEL competition in ``matches`` (trained on its matches alone),
    plus ``{POOLED: model}`` trained on every league match when any
    other league is present, plus ``{EUROPEAN: model}`` trained on the
    European rows (CL, EL, ECL) when there are any. A Premier-League-only
    history gives just the original Premier League model.
    """

    european = _divs(matches).isin(CUPS)
    leagues = matches[~european]
    divs = _divs(leagues)

    models = {
        div: train_model(leagues[divs == div])
        for div in OWN_MODEL
        if (divs == div).any()
    }

    if (~divs.isin(OWN_MODEL)).any():
        models[POOLED] = train_model(leagues)

    if european.any():
        models[EUROPEAN] = train_european_model(matches[european])

    return models


def walk_forward_models(matches, test_seasons):
    """
    evaluate.walk_forward for the train_models setup: out-of-sample
    probabilities from the pooled model, with each OWN_MODEL
    competition's rows replaced by its own model's. ``matches`` needs
    the FEATURES and its league_columns.
    """

    divs = _divs(matches)
    indicators = [c for c in LEAGUE_COLUMNS.values() if c in matches.columns]

    if (~divs.isin(OWN_MODEL)).any():
        proba = walk_forward(matches, make_model, FEATURES + indicators, test_seasons)
    else:
        proba = None

    for div in OWN_MODEL:

        own = matches[divs == div]
        if own.empty:
            continue

        own_proba = walk_forward(own, make_model, FEATURES, test_seasons)

        if proba is None:
            proba = own_proba.reindex(matches.index[matches["Season"].isin(test_seasons)])
        proba.loc[own_proba.index] = own_proba

    return proba


# ============================================================
# PREDICT FIXTURES
# ============================================================

def _model_for(models, div):
    """The model in train_models' output that predicts competition ``div``."""

    if competitions.COMPETITIONS.get(div, {}).get("model") == EUROPEAN:
        model = models.get(EUROPEAN)
    elif div in OWN_MODEL or (div == "" and BASELINE_LEAGUE in OWN_MODEL):
        model = models.get(BASELINE_LEAGUE if div == "" else div)
    else:
        model = models.get(POOLED)

    if model is None:
        raise ValueError(f"No training data for {div} - can't predict its fixtures.")

    return model


def _predict(model, features):
    """H/D/A probabilities (classes_ order) for one model's fixtures."""

    columns = model_features(model)

    if columns == EUROPEAN_FEATURES:
        X = european_columns(features)[columns]
        return pd.DataFrame(model.predict_proba(X), index=features.index, columns=model.classes_)

    trained_leagues = [d for d, c in LEAGUE_COLUMNS.items() if c in columns]
    # A cup fixture has every league column 0, like the baseline league:
    # the pooled model applied as it is (setup (a), plan §4B.7)
    cups = {d for d, e in competitions.COMPETITIONS.items() if e["kind"] == "cup"}
    unknown = set(features["Div"]) - set(trained_leagues) - {BASELINE_LEAGUE, ""} - cups

    if unknown:
        raise ValueError(
            f"No training data for {', '.join(sorted(unknown))} - can't predict its fixtures."
        )

    X = league_columns(features, trained_leagues)[columns]

    return pd.DataFrame(model.predict_proba(X), index=features.index, columns=model.classes_)


def predict_fixtures(fixtures, model, elos, team_history, scope=DEFAULT_SCOPE):
    """
    Score ``fixtures`` (needs Date, Time, HomeTeam, AwayTeam - already
    normalised; Gameweek and Div optional, Div needed when the history
    spans several competitions). A fixture with Neutral = 1 is scored
    both ways round and averaged (champions_league.neutral_probabilities);
    its features are reported for the listed orientation. ``model`` is train_models' output, each
    fixture going to its competition's model, or a single train_model
    model for every fixture. Returns a results frame with the features,
    the predicted result and H/D/A probabilities (as percentages).
    """

    def score(frame):
        features = build_future_features(frame, elos, team_history, scope=scope)
        if "Stage" in frame.columns:
            features["Stage"] = frame["Stage"].to_numpy()

        if isinstance(model, dict):
            probabilities = pd.concat([
                _predict(_model_for(model, div), group)
                for div, group in features.groupby("Div", sort=False)
            ]).loc[features.index]
        else:
            probabilities = _predict(model, features)

        return features, probabilities

    features, probabilities = score(fixtures)

    # A neutral venue (the CL final): average both orientations (plan §4B.4)
    neutral = (
        fixtures["Neutral"].fillna(0).astype(int).eq(1).to_numpy()
        if "Neutral" in fixtures.columns
        else None
    )
    if neutral is not None and neutral.any():
        swapped = fixtures[neutral].rename(columns={
            "HomeTeam": "AwayTeam", "AwayTeam": "HomeTeam",
            "HomeLeague": "AwayLeague", "AwayLeague": "HomeLeague",
        })
        _, reverse = score(swapped)
        rows = probabilities.index[neutral]
        probabilities.loc[rows] = neutral_probabilities(
            probabilities.loc[rows], reverse.set_axis(rows)
        ).to_numpy()

    base_columns = ["Date", "Time", "HomeTeam", "AwayTeam"]
    if "Gameweek" in fixtures.columns:
        base_columns = ["Gameweek"] + base_columns

    results = fixtures[base_columns].copy()
    results[FEATURES] = features[FEATURES].round(2).to_numpy()
    # The most likely outcome (ties go to the first class, as predict does)
    results["Prediction"] = probabilities.idxmax(axis=1).to_numpy()

    for class_name in probabilities.columns:
        results[PROB_COLUMNS[class_name]] = probabilities[class_name].to_numpy() * 100

    results[list(PROB_COLUMNS.values())] = results[
        list(PROB_COLUMNS.values())
    ].round(1)

    return results
