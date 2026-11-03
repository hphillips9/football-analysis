"""
Elo ratings: the update rule, the pre-match Elo feature for a match
history, and a team's Elo going into an upcoming fixture.
"""

from collections import defaultdict


# ============================================================
# CONFIGURATION
# ============================================================

HOME_ADVANTAGE = 130
UPDATE_SIZE = 35

# A promoted team (not in the league the season before) restarts here
# rather than at the 1500 average or a stale rating from an old stint.
# Promoted sides average ~0.8 points a game in their first season up;
# notebooks/19_championship_promoted_teams.ipynb picked this value.
# None turns the reset off everywhere (the original behaviour).
PROMOTED_ELO = None


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


def build_elo_feature(matches, promoted_elo=PROMOTED_ELO):
    """
    Pre-match Elo for every row of ``matches`` (chronological). Returns
    the end-of-history ratings.

    A team's first match of a season resets it to ``promoted_elo`` if it
    didn't play the season before (every team in the first season on
    record starts at 1500). Done at the first match rather than at the
    season start so a history cut off mid-season still works.
    ``promoted_elo=None`` turns this off (the original behaviour).
    """

    elos = {}

    seasons = sorted(matches["Season"].unique())
    previous_season = dict(zip(seasons[1:], seasons[:-1]))
    seen = defaultdict(set)  # season -> teams that have played in it so far

    def get_elo(team, season):

        if team not in seen[season]:

            seen[season].add(team)

            promoted = (
                season in previous_season
                and team not in seen[previous_season[season]]
            )

            if promoted and promoted_elo is not None:
                elos[team] = promoted_elo

        if team not in elos:
            elos[team] = 1500

        return elos[team]

    home_elo_feature = []
    away_elo_feature = []
    elo_diff_feature = []

    for _, current_match in matches.iterrows():

        home_team = current_match["HomeTeam"]
        away_team = current_match["AwayTeam"]

        home_elo = get_elo(home_team, current_match["Season"])
        away_elo = get_elo(away_team, current_match["Season"])

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


def fixture_elo(team, season, elos, team_history, seasons_on_record):
    """
    A team's Elo going into a fixture in ``season``. Applies the same
    promoted-team reset as build_elo_feature to a team yet to play this
    season - e.g. a promoted side before its first game of a new season.
    """

    played_in = {m["Season"] for m in team_history[team]}
    earlier = [s for s in seasons_on_record if s < season]

    promoted = season not in played_in and earlier and earlier[-1] not in played_in

    if promoted and PROMOTED_ELO is not None:
        return PROMOTED_ELO

    return elos.get(team, 1500)
