"""
Chronological, leak-free match features: season goals per game, last-5
xG difference, the same features for upcoming fixtures, and
build_history to compute them all over a match history.

Every builder takes a ``scope`` (see elo.SCOPES). The default,
"competition", keeps each Div's history separate, so pooling several
leagues in one frame leaves each league's features as they would be
on its own.
"""

import pandas as pd
import numpy as np

from collections import defaultdict

from elo import (
    DEFAULT_SCOPE,
    build_elo_feature,
    fixture_elo,
    match_div,
    scope_key,
)


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


def build_goals_per_game_feature(matches, scope=DEFAULT_SCOPE):

    season_history = defaultdict(lambda: defaultdict(list))

    home_goals_pg = []
    away_goals_pg = []

    for _, current_match in matches.iterrows():

        season = current_match["Season"]
        div = match_div(current_match)

        home_team = current_match["HomeTeam"]
        away_team = current_match["AwayTeam"]

        home_key = scope_key(div, home_team, scope)
        away_key = scope_key(div, away_team, scope)

        home_previous = season_history[season][home_key]
        away_previous = season_history[season][away_key]

        home_stats = calculate_season_stats(home_previous, home_team)
        away_stats = calculate_season_stats(away_previous, away_team)

        home_goals_pg.append(home_stats["goals_pg"])
        away_goals_pg.append(away_stats["goals_pg"])

        # Add AFTER calculating features
        season_history[season][home_key].append(current_match)
        season_history[season][away_key].append(current_match)

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


def build_xgd_last5_feature(matches, scope=DEFAULT_SCOPE):
    """
    Last-5 xG difference for every row of ``matches``. Returns each
    team's match history, keyed by elo.scope_key.
    """

    team_history = defaultdict(list)

    xgd_last5_diff = []

    for _, current_match in matches.iterrows():

        div = match_div(current_match)

        home_team = current_match["HomeTeam"]
        away_team = current_match["AwayTeam"]

        home_key = scope_key(div, home_team, scope)
        away_key = scope_key(div, away_team, scope)

        home_last5 = team_history[home_key][-5:]
        away_last5 = team_history[away_key][-5:]

        home_xgd = calculate_team_xgd_last5(home_last5, home_team)
        away_xgd = calculate_team_xgd_last5(away_last5, away_team)

        xgd_last5_diff.append(home_xgd - away_xgd)

        # Add AFTER calculating features
        team_history[home_key].append(current_match)
        team_history[away_key].append(current_match)

    matches["XGDDiffLast5"] = xgd_last5_diff

    return team_history


# ============================================================
# HISTORY
# ============================================================

def build_history(matches, scope=DEFAULT_SCOPE, european=None):
    """
    Build the chronological features on a copy of ``matches`` and return
    ``(matches, elos, team_history)`` - the end-of-history Elo ratings and
    per-team match history needed to score upcoming fixtures (with
    build_future_features and the same ``scope``). ``european`` results
    (european.results_for_elo) move the Elo too.
    """

    matches = (
        matches
        .sort_values(["MatchDateTime", "HomeTeam", "AwayTeam"])
        .reset_index(drop=True)
        .copy()
    )

    elos = build_elo_feature(matches, scope=scope, european=european)
    build_goals_per_game_feature(matches, scope=scope)
    team_history = build_xgd_last5_feature(matches, scope=scope)

    return matches, elos, team_history


# ============================================================
# UPCOMING FIXTURES
# ============================================================

def _season_label_for(date_text, default):
    """Season label ("26-27") a dd/mm/yyyy fixture date falls in, else default."""

    day = pd.to_datetime(date_text, dayfirst=True, errors="coerce")

    if pd.isna(day):
        return default

    start = day.year if day.month >= 7 else day.year - 1

    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _season_goals_per_game(team_matches, team, season):

    played = [m for m in team_matches if m["Season"] == season]

    return calculate_season_stats(played, team)["goals_pg"]


def fixture_divs(fixtures, team_history):
    """
    Each fixture's Div: its own Div column, or - for fixtures without
    one - the only competition in ``team_history``.
    """

    if "Div" in fixtures.columns:
        return fixtures["Div"]

    divs = {match_div(m) for rows in team_history.values() for m in rows}

    if len(divs) != 1:
        raise ValueError(
            "Fixtures need a Div column when the history spans several "
            f"competitions ({', '.join(sorted(divs))})."
        )

    return pd.Series(divs.pop(), index=fixtures.index)


def build_future_features(future, elos, team_history, scope=DEFAULT_SCOPE):
    """
    EloDiff, XGDDiffLast5 and GoalsPerGameDiff for upcoming fixtures,
    from build_history's ratings and team history (built with the same
    ``scope``), plus each fixture's Div.
    """

    future_features = []

    # Div -> the seasons it has on record, in order
    seasons_by_div = defaultdict(set)
    for rows in team_history.values():
        for m in rows:
            seasons_by_div[match_div(m)].add(m["Season"])
    seasons_by_div = {div: sorted(s) for div, s in seasons_by_div.items()}

    all_seasons = sorted(set().union(*seasons_by_div.values()))

    for (_, match), div in zip(future.iterrows(), fixture_divs(future, team_history)):

        home_team = match["HomeTeam"]
        away_team = match["AwayTeam"]

        home_matches = team_history[scope_key(div, home_team, scope)]
        away_matches = team_history[scope_key(div, away_team, scope)]

        seasons_on_record = (
            seasons_by_div.get(div, []) if scope == "competition" else all_seasons
        )
        latest_season = (seasons_on_record or all_seasons)[-1]

        season = _season_label_for(match.get("Date", ""), latest_season)

        home_elo = fixture_elo(home_team, season, elos, home_matches, seasons_on_record, div)
        away_elo = fixture_elo(away_team, season, elos, away_matches, seasons_on_record, div)

        elo_diff = home_elo - away_elo

        home_xgd = calculate_team_xgd_last5(home_matches[-5:], home_team)
        away_xgd = calculate_team_xgd_last5(away_matches[-5:], away_team)

        xgd_diff = home_xgd - away_xgd

        # Season-to-date, exactly as in training; 0 for a team with no games
        # yet this season (so it is 0 for everyone in a season's first round)
        goals_per_game_diff = (
            _season_goals_per_game(home_matches, home_team, season)
            - _season_goals_per_game(away_matches, away_team, season)
        )

        future_features.append({
            "Div": div,
            "EloDiff": elo_diff,
            "XGDDiffLast5": xgd_diff,
            "GoalsPerGameDiff": goals_per_game_diff
        })

    return pd.DataFrame(future_features)
