"""
Elo ratings: the update rule, the pre-match Elo feature for a match
history, and a team's Elo going into an upcoming fixture.
"""

from collections import defaultdict

import competitions


# ============================================================
# CONFIGURATION
# ============================================================

HOME_ADVANTAGE = 130
UPDATE_SIZE = 35

# Where a promoted team (not in the league the season before) restarts,
# rather than at the 1500 average or a stale rating from an old stint:
# each competition's ``promoted_elo`` in competitions.py, tested per
# league in notebook 20. None carries the old rating over (the original
# behaviour). PROMOTED_ELO is the value for a code the registry doesn't
# know (e.g. E1 in notebook 19).
PROMOTED_ELO = None

# build_elo_feature's default: take each competition's value from the
# registry. Pass a number (or None) to use it everywhere instead, or a
# {Div: value} dict.
FROM_REGISTRY = "registry"

# Every league's average rating (B_L). The same for all leagues until
# league-strength offsets arrive (docs/multi-league-plan.md, Phase 4).
LEAGUE_BASE_ELO = 1500


# ============================================================
# SCOPE
# ============================================================

# Which matches a team's ratings and form are built from:
#   "competition"  only matches in the same competition (Div), so one
#                  league's results never leak into another's features
#   "all"          every match on record, whatever the competition
SCOPES = ("competition", "all")
DEFAULT_SCOPE = "competition"


def scope_key(div, team, scope=DEFAULT_SCOPE):
    """The key a team's history is kept under for ``scope``."""

    if scope == "competition":
        return (div, team)

    if scope == "all":
        return team

    raise ValueError(f"Unknown scope {scope!r}. Known: {', '.join(SCOPES)}")


def match_div(match):
    """A match row's Div ("" for an old single-league frame without one)."""

    return match.get("Div", "")


def promoted_start(div, promoted_elo=FROM_REGISTRY):
    """The Elo a promoted club in ``div`` restarts at, or None to carry over."""

    if isinstance(promoted_elo, dict):
        return promoted_elo.get(div)

    if promoted_elo == FROM_REGISTRY:
        return competitions.COMPETITIONS.get(div, {}).get("promoted_elo", PROMOTED_ELO)

    return promoted_elo


def _ratings_by_team(ratings, scope):
    """
    One rating per team from ratings kept by scope key. Under
    "competition" a club in more than one competition reports its
    league rating rather than a cup one.
    """

    if scope == "all":
        return dict(ratings)

    by_team = {}

    for (div, team), rating in ratings.items():

        is_cup = competitions.COMPETITIONS.get(div, {}).get("kind") == "cup"

        if team not in by_team or not is_cup:
            by_team[team] = rating

    return by_team


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


def build_elo_feature(matches, promoted_elo=FROM_REGISTRY, scope=DEFAULT_SCOPE):
    """
    Pre-match Elo for every row of ``matches`` (chronological). Returns
    the end-of-history ratings, one per team.

    Under ``scope="competition"`` each competition (Div) is rated on its
    own; ``"all"`` pools every match.

    A team's first match of a season resets it to its competition's
    promoted start (see promoted_start) if it didn't play the season
    before in that competition (every team in the first season on record
    starts at LEAGUE_BASE_ELO). Done at the first match rather than at
    the season start so a history cut off mid-season still works.
    ``promoted_elo=None`` turns this off everywhere (the original
    behaviour).
    """

    elos = {}  # scope key -> rating

    divs = (
        matches["Div"] if "Div" in matches.columns and scope == "competition"
        else None
    )

    # group -> {season: the season before it}, per competition under
    # "competition", over the whole frame under "all"
    previous_season = {}

    for group, frame in (matches.groupby(divs) if divs is not None else [(None, matches)]):
        seasons = sorted(frame["Season"].unique())
        previous_season[group] = dict(zip(seasons[1:], seasons[:-1]))

    # (group, season) -> teams that have played in it so far
    seen = defaultdict(set)

    def get_elo(team, div, season):

        key = scope_key(div, team, scope)
        group = div if divs is not None else None
        previous = previous_season.get(group, {})

        if key not in seen[(group, season)]:

            seen[(group, season)].add(key)

            promoted = (
                season in previous
                and key not in seen[(group, previous[season])]
            )

            start = promoted_start(div, promoted_elo) if promoted else None

            if start is not None:
                elos[key] = start

        if key not in elos:
            elos[key] = LEAGUE_BASE_ELO

        return elos[key]

    home_elo_feature = []
    away_elo_feature = []
    elo_diff_feature = []

    for _, current_match in matches.iterrows():

        home_team = current_match["HomeTeam"]
        away_team = current_match["AwayTeam"]
        div = match_div(current_match)

        home_elo = get_elo(home_team, div, current_match["Season"])
        away_elo = get_elo(away_team, div, current_match["Season"])

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

        elos[scope_key(div, home_team, scope)] = new_home_elo
        elos[scope_key(div, away_team, scope)] = new_away_elo

    matches["HomeElo"] = home_elo_feature
    matches["AwayElo"] = away_elo_feature
    matches["EloDiff"] = elo_diff_feature

    return _ratings_by_team(elos, scope)


def fixture_elo(team, season, elos, team_matches, seasons_on_record, div=""):
    """
    A team's Elo going into a fixture in ``season`` of competition
    ``div``, given the matches it has played (in the fixture's scope) and
    the seasons on record there. Applies the same promoted-team reset as
    build_elo_feature to a team yet to play this season - e.g. a promoted
    side before its first game of a new season.
    """

    played_in = {m["Season"] for m in team_matches}
    earlier = [s for s in seasons_on_record if s < season]

    promoted = season not in played_in and earlier and earlier[-1] not in played_in

    start = promoted_start(div) if promoted else None

    if start is not None:
        return start

    return elos.get(team, LEAGUE_BASE_ELO)
