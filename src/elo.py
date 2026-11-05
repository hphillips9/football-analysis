"""
Elo ratings: the update rule, the pre-match Elo feature for a match
history, and a team's Elo going into an upcoming fixture.

Given European results (CL, EL, ECL from european.py), every club is
also rated on one scale across leagues (notebook 21, variant E2a+E2b):
see the SHARED SCALE section.
"""

import math
from collections import defaultdict
from pathlib import Path

import pandas as pd

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


def build_elo_feature(matches, promoted_elo=FROM_REGISTRY, scope=DEFAULT_SCOPE,
                      european=None):
    """
    Pre-match Elo for every row of ``matches`` (chronological). Returns
    the end-of-history ratings, one per team.

    Under ``scope="competition"`` each competition (Div) is rated on its
    own; ``"all"`` pools every match.

    With ``european`` (european.load_european rows), European results
    move the ratings too - see shared_scale(). Without it, or with none
    on record, the ratings are the domestic ones alone.

    A team's first match of a season resets it to its competition's
    promoted start (see promoted_start) if it didn't play the season
    before in that competition (every team in the first season on record
    starts at LEAGUE_BASE_ELO). Done at the first match rather than at
    the season start so a history cut off mid-season still works.
    ``promoted_elo=None`` turns this off everywhere (the original
    behaviour).
    """

    if european is not None and len(european) and scope == "competition":
        result = shared_scale(matches, european, promoted_elo=promoted_elo)
        matches["HomeElo"] = result["home_elo"]
        matches["AwayElo"] = result["away_elo"]
        matches["EloDiff"] = matches["HomeElo"] - matches["AwayElo"]
        return _ratings_by_team(result["domestic"], scope)

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


# ============================================================
# SHARED SCALE (notebook 21: E2a+E2b, option A offsets)
# ============================================================
#
# Every league L sits at B_L = 1500 + O_L on one scale, with
# O_L = A_L + D_L:
#   A_L  OFFSET_SCALE * ln(C_L / C_ENG), C = UEFA's 5-year country
#        coefficient at the start of the season (O_E0 = 0 anchors it)
#   D_L  learned from European results between two modelled leagues
#        (E2b), +- OFFSET_UPDATE_SIZE * (S - E); E0's stays 0
#
# A modelled club's domestic rating r is today's Elo, except that its
# European results also move it (E2a), by EUROPE_UPDATE_SIZE * (S - E).
# On the shared scale it is r - delta + O_L, where delta re-centres the
# league: mean(r - t) - 1500 over the season's clubs, t being a club's
# European transfers so far. That removes the drift from promotion and
# relegation but keeps what a league has won in Europe. Domestic updates
# are zero-sum, so delta is one constant per league and season (exactly,
# when no league resets promoted clubs).
#
# A club from outside the modelled leagues ("X:<country>") holds a
# shared-scale rating directly: it starts at 1500 + A_country +
# ENTRANT_BONUS, is pulled towards its country's baseline between
# seasons by OUTSIDER_CARRY, and moves with every European result.
#
# European expected score:
#   1 / (1 + 10^(-(R_home + HA (1 - Neutral) - R_away) / 400)),
# HA = EUROPE_HOME_ADVANTAGE. All chosen on 22-23/23-24 in notebook 21.

OFFSET_SCALE = 150
EUROPE_HOME_ADVANTAGE = 80
EUROPE_UPDATE_SIZE = 35
OFFSET_UPDATE_SIZE = 4
ENTRANT_BONUS = 0
OUTSIDER_CARRY = 0.5

# The league that anchors the scale (O = 0, never learned)
ANCHOR_LEAGUE = "E0"
ANCHOR_COUNTRY = "ENG"

COEFFICIENTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "reference" / "uefa_country_coefficients.csv"
)

SCORES = {"H": 1.0, "D": 0.5, "A": 0.0}


def load_coefficients(path=COEFFICIENTS_PATH):
    """{(country, season): coefficient} from data/reference (P4-02)."""

    table = pd.read_csv(path)

    return {
        (country, season): coefficient
        for country, season, coefficient in zip(
            table["country"], table["season"], table["coefficient"]
        )
    }


def uefa_offset(country, season, coefficients, scale=OFFSET_SCALE):
    """
    Option A's offset for ``country`` in ``season``. A season without a
    snapshot yet uses the latest earlier one; a country UEFA doesn't list
    gets that season's lowest coefficient.
    """

    seasons = sorted({s for _, s in coefficients})
    snapshot = max([s for s in seasons if s <= season] or seasons[:1])

    coefficient = coefficients.get((country, snapshot))
    if coefficient is None:
        coefficient = min(c for (_, s), c in coefficients.items() if s == snapshot)

    return scale * math.log(coefficient / coefficients[(ANCHOR_COUNTRY, snapshot)])


def shared_scale(matches, european, promoted_elo=FROM_REGISTRY, coefficients=None,
                 history_from=None):
    """
    Rate ``matches`` (domestic, chronological, with Div, Season and
    MatchDateTime) and ``european`` (european.load_european rows) in one
    pass. A European match on day d counts after every domestic match up
    to d.

    Returns a dict:
        home_elo, away_elo  pre-match domestic ratings, one per matches row
        domestic            {(Div, club): rating} at the end
        ratings             DataFrame Club, League (Div or X:<country>),
                            Country, Modelled, Season, Rating - every club's
                            shared-scale rating at the end
        offsets             DataFrame Date, Season, Div, Offset - each
                            league's O_L after every European matchday
        history             DataFrame Date, Club, League, Rating - shared
                            rating after each match from ``history_from`` on
    """

    coefficients = coefficients or load_coefficients()
    country_of = {div: entry["country"] for div, entry in competitions.COMPETITIONS.items()}

    r = {}                         # (Div, club) -> domestic rating
    transfer = defaultdict(float)  # (Div, club) -> European transfers so far
    learned = defaultdict(float)   # Div -> D_L
    delta, a_cache = {}, {}
    outsiders = {}                 # club -> [rating, season, baseline, country]
    last_season = {}               # (Div, club) -> latest season it played

    participants = {
        key: set(group["HomeTeam"]) | set(group["AwayTeam"])
        for key, group in matches.groupby(["Div", "Season"])
    }
    leagues = sorted({div for div, _ in participants})

    def a_offset(country, season):
        key = (country, season)
        if key not in a_cache:
            a_cache[key] = uefa_offset(country, season, coefficients)
        return a_cache[key]

    def offset(div, season):
        if div == ANCHOR_LEAGUE:
            return 0.0
        return a_offset(country_of[div], season) + learned[div]

    def recentre(div, season):
        key = (div, season)
        if key not in delta:
            # The season's clubs, or (a history cut off before its first
            # domestic match) every club rated in the league so far
            clubs = participants.get(key) or {c for (d, c) in r if d == div}
            delta[key] = sum(
                r.get((div, club), LEAGUE_BASE_ELO) - transfer[(div, club)] for club in clubs
            ) / len(clubs) - LEAGUE_BASE_ELO
        return delta[key]

    def shared(div, club, season):
        return r.get((div, club), LEAGUE_BASE_ELO) - recentre(div, season) + offset(div, season)

    def outsider(club, country, season):
        base = LEAGUE_BASE_ELO + a_offset(country, season)
        state = outsiders.get(club)
        if state is None:
            state = outsiders[club] = [base + ENTRANT_BONUS, season, base, country]
        elif state[1] != season:
            state[0] = base + OUTSIDER_CARRY * (state[0] - state[2])
            state[1], state[2], state[3] = season, base, country
        return state

    # The domestic rules, exactly as build_elo_feature's (scope "competition")
    previous_season = {}
    for div, frame in matches.groupby("Div"):
        seasons = sorted(frame["Season"].unique())
        previous_season[div] = dict(zip(seasons[1:], seasons[:-1]))
    seen = defaultdict(set)

    def domestic_elo(club, div, season):
        key = (div, club)
        if key not in seen[(div, season)]:
            seen[(div, season)].add(key)
            previous = previous_season.get(div, {})
            promoted = season in previous and key not in seen[(div, previous[season])]
            start = promoted_start(div, promoted_elo) if promoted else None
            if start is not None:
                r[key] = start
        if key not in r:
            r[key] = LEAGUE_BASE_ELO
        last_season[key] = season
        return r[key]

    history_from = pd.Timestamp(history_from) if history_from is not None else None
    history, offset_rows = [], []

    def record(day, club, league, rating):
        if history_from is not None and day >= history_from:
            history.append((day, club, league, rating))

    def european_match(day, season, home, away, home_league, away_league, ftr, neutral):

        sides = []
        for club, league in ((home, home_league), (away, away_league)):
            if league.startswith("X:"):
                state = outsider(club, league[2:], season)
                sides.append((club, league, state, state[0]))
            else:
                sides.append((club, league, None, shared(league, club, season)))

        (_, _, _, rating_home), (_, _, _, rating_away) = sides
        expected = 1 / (1 + 10 ** (
            -(rating_home + EUROPE_HOME_ADVANTAGE * (1 - neutral) - rating_away) / 400
        ))
        change = SCORES[ftr] - expected

        for (club, league, state, _), sign in zip(sides, (1, -1)):
            move = sign * EUROPE_UPDATE_SIZE * change
            if state is None:
                key = (league, club)
                r[key] = r.get(key, LEAGUE_BASE_ELO) + move
                transfer[key] += move
            else:
                state[0] += move

        both_modelled = all(state is None for _, _, state, _ in sides)
        if both_modelled and home_league != away_league:
            if home_league != ANCHOR_LEAGUE:
                learned[home_league] += OFFSET_UPDATE_SIZE * change
            if away_league != ANCHOR_LEAGUE:
                learned[away_league] -= OFFSET_UPDATE_SIZE * change

        for club, league, state, _ in sides:
            record(day, club, league, state[0] if state else shared(league, club, season))

    # Within a day, load_european's order (Div, then MatchId) - as notebook 21
    european = european.sort_values("Date", kind="stable").reset_index(drop=True)
    euro_days = pd.to_datetime(european["Date"]).dt.normalize().tolist()
    euro_rows = list(zip(
        european["Season"], european["HomeTeam"], european["AwayTeam"],
        european["HomeLeague"], european["AwayLeague"], european["FTR"], european["Neutral"],
    ))
    position = 0

    def play_european_before(day):
        # every European match dated before ``day`` (None: all that are left)
        nonlocal position
        while position < len(euro_rows) and (day is None or euro_days[position] < day):
            match_day, season = euro_days[position], euro_rows[position][0]
            while position < len(euro_rows) and euro_days[position] == match_day:
                european_match(match_day, *euro_rows[position])
                position += 1
            for div in leagues:
                if (div, season) in participants:
                    offset_rows.append((match_day, season, div, offset(div, season)))

    home_elos, away_elos = [], []
    days = pd.to_datetime(matches["MatchDateTime"]).dt.normalize().tolist()

    for day, div, season, home, away, ftr in zip(
        days, matches["Div"], matches["Season"], matches["HomeTeam"],
        matches["AwayTeam"], matches["FTR"],
    ):
        play_european_before(day)

        rating_home = domestic_elo(home, div, season)
        rating_away = domestic_elo(away, div, season)
        home_elos.append(rating_home)
        away_elos.append(rating_away)

        expected = expected_result(rating_home, rating_away)
        score = SCORES[ftr]
        r[(div, home)] = new_rating(rating_home, score, expected)
        r[(div, away)] = new_rating(rating_away, 1 - score, 1 - expected)

        if history_from is not None and day >= history_from:
            record(day, home, div, shared(div, home, season))
            record(day, away, div, shared(div, away, season))

    play_european_before(None)

    rows = [
        {"Club": club, "League": div, "Country": country_of.get(div), "Modelled": True,
         "Season": season, "Rating": shared(div, club, season)}
        for (div, club), season in last_season.items()
    ]
    rows += [
        {"Club": club, "League": f"X:{state[3]}", "Country": state[3], "Modelled": False,
         "Season": state[1], "Rating": state[0]}
        for club, state in outsiders.items()
    ]

    return {
        "home_elo": home_elos,
        "away_elo": away_elos,
        "domestic": dict(r),
        "ratings": (
            pd.DataFrame(rows, columns=["Club", "League", "Country", "Modelled", "Season", "Rating"])
            .sort_values("Rating", ascending=False)
            .reset_index(drop=True)
        ),
        "offsets": pd.DataFrame(offset_rows, columns=["Date", "Season", "Div", "Offset"]),
        "history": pd.DataFrame(history, columns=["Date", "Club", "League", "Rating"]),
    }
