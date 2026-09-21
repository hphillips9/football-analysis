"""
Dixon-Coles goal model utilities.

Not part of the deployed prediction model (predict_next_matches.py) -
these are used for:

  - notebooks/16_dixon_coles_features.ipynb, which tested Dixon-Coles as
    extra features for the logistic regression and found it didn't earn
    a place in the deployed model
  - export_web.py's projected league table, which uses Dixon-Coles'
    expected goals to project goal difference forward for fixtures that
    haven't been played yet (see project_goal_difference below)
"""

import warnings

import pandas as pd
from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights

# Assigning the 11 feature columns one at a time onto an already-wide
# frame (all_matches.csv) triggers this; harmless (see load_data.py).
warnings.simplefilter("ignore", pd.errors.PerformanceWarning)


MIN_DC_HISTORY = 100  # matches; fewer than this and a fit is too unstable to trust

DC_FEATURES = [
    "DCHomeProb",
    "DCDrawProb",
    "DCAwayProb",
    "DCLambda",
    "DCMu",
    "DCTotalGoals",
    "DCGoalDiff",
    "DCAttackHome",
    "DCAttackAway",
    "DCDefenseHome",
    "DCDefenseAway",
]

# Used when there's no fit to score from yet - the very first gameweek on
# record, or a newly promoted team's first few games. Roughly league-average:
# ~1.35 goals a side, neutral (average) attack/defence ratings, even odds.
DC_FALLBACK = {
    "DCHomeProb": 1 / 3,
    "DCDrawProb": 1 / 3,
    "DCAwayProb": 1 / 3,
    "DCLambda": 1.35,
    "DCMu": 1.35,
    "DCTotalGoals": 2.7,
    "DCGoalDiff": 0.0,
    "DCAttackHome": 1.0,
    "DCAttackAway": 1.0,
    "DCDefenseHome": 0.0,
    "DCDefenseAway": 0.0,
}


def _score_dixon_coles(model, params, home_team, away_team):
    """One fixture's Dixon-Coles features from an already-fitted model."""

    grid = model.predict(home_team, away_team)

    home_goals = grid.home_goal_expectation
    away_goals = grid.away_goal_expectation

    return {
        "DCHomeProb": grid.home_win,
        "DCDrawProb": grid.draw,
        "DCAwayProb": grid.away_win,
        "DCLambda": home_goals,
        "DCMu": away_goals,
        "DCTotalGoals": home_goals + away_goals,
        "DCGoalDiff": home_goals - away_goals,
        "DCAttackHome": params[f"attack_{home_team}"],
        "DCAttackAway": params[f"attack_{away_team}"],
        "DCDefenseHome": params[f"defence_{home_team}"],
        "DCDefenseAway": params[f"defence_{away_team}"],
    }


def build_dixon_coles_feature(matches, xi=0.0018):
    """
    Fit a Dixon-Coles goal model once per gameweek - on every match
    strictly before it - and score that gameweek's fixtures with it.

    Batched per gameweek rather than per match (unlike the Elo/xG
    features in predict_next_matches.py): each fit re-estimates every
    team's attack/defence rating from scratch, so refitting before every
    single row would be far too slow. Still leak-free - a gameweek's
    features only ever come from matches before it.

    A team missing from the fit's history (no matches at all yet, or a
    newly promoted side still to play its first game), too little history
    to fit on, or a fit/predict that errors out (small samples can produce
    an unstable, occasionally invalid fit) all fall back to DC_FALLBACK
    instead of taking down the whole build.

    Used for research (notebooks/16_dixon_coles_features.ipynb) - the
    deployed model doesn't call this.
    """

    columns = {name: [None] * len(matches) for name in DC_FEATURES}

    for _, group in matches.groupby(["Season", "Gameweek"], sort=False):

        cutoff = group["MatchDateTime"].min()
        history = matches[matches["MatchDateTime"] < cutoff]

        model = None
        params = None
        known_teams = set()

        if len(history) >= MIN_DC_HISTORY:

            try:
                weights = dixon_coles_weights(
                    history["MatchDateTime"], xi=xi, base_date=cutoff
                )

                model = DixonColesGoalModel(
                    history["FTHG"], history["FTAG"],
                    history["HomeTeam"], history["AwayTeam"],
                    weights=weights,
                )
                model.fit()

                params = model.get_params()
                known_teams = set(history["HomeTeam"]) | set(history["AwayTeam"])

            except Exception:
                model = None

        for index, fixture in group.iterrows():

            home_team = fixture["HomeTeam"]
            away_team = fixture["AwayTeam"]

            values = DC_FALLBACK

            if model is not None and home_team in known_teams and away_team in known_teams:
                try:
                    values = _score_dixon_coles(model, params, home_team, away_team)
                except Exception:
                    pass

            for name, value in values.items():
                columns[name][index] = value

    for name, values in columns.items():
        matches[name] = values

    return matches


# ============================================================
# LIVE / FUTURE USE - one fit on everything played so far, scoring
# fixtures that haven't happened yet. No walk-forward needed here (unlike
# build_dixon_coles_feature above): there's nothing left to leak when the
# fixture genuinely hasn't been played.
# ============================================================

def fit_dixon_coles(matches, xi=0.0018):
    """Fit a single Dixon-Coles model on every match in `matches`."""

    weights = dixon_coles_weights(
        matches["MatchDateTime"], xi=xi, base_date=matches["MatchDateTime"].max()
    )

    model = DixonColesGoalModel(
        matches["FTHG"], matches["FTAG"],
        matches["HomeTeam"], matches["AwayTeam"],
        weights=weights,
    )
    model.fit()

    return model, set(matches["HomeTeam"]) | set(matches["AwayTeam"])


# A team with very little history (a newly promoted side a handful of
# games into its season) can drive its own attack/defence rating to an
# unstable extreme - the classic small-sample MLE failure mode, since
# there's nothing to shrink the estimate back toward average. Clamping
# the resulting expected goals keeps one bad rating from producing an
# absurd projection (e.g. "1 goal scored across an entire season").
MIN_EXPECTED_GOALS = 0.5
MAX_EXPECTED_GOALS = 4.0


def expected_goals(model, known_teams, home_team, away_team):
    """
    (expected home goals, expected away goals) for a fixture, clamped to
    a plausible range, or (None, None) if either team has no history in
    the fitted model or the fit can't score this pairing for any reason.
    """

    if home_team not in known_teams or away_team not in known_teams:
        return None, None

    try:
        grid = model.predict(home_team, away_team)
        home_goals = min(max(grid.home_goal_expectation, MIN_EXPECTED_GOALS), MAX_EXPECTED_GOALS)
        away_goals = min(max(grid.away_goal_expectation, MIN_EXPECTED_GOALS), MAX_EXPECTED_GOALS)
        return home_goals, away_goals
    except Exception:
        return None, None
