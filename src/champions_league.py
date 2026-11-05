"""
Champions League specifics (plan §4B.1-4B.4): stages and legs,
football-data.org's fixtures matched to FotMob's clubs, and predicting a
match at a neutral venue (the final).

Results come from FotMob (european.py: 90-minute score and xG, stage,
leg, neutral flag) and sit in all_matches.csv as Div "CL" rows
(load_data.build_cup_rows). Fixtures come from football-data.org, whose
CL feed is on the free tier:

    stage      LEAGUE_STAGE (GROUP_STAGE before 24-25), PLAYOFFS, LAST_16,
               QUARTER_FINALS, SEMI_FINALS, FINAL
    matchday   the league-phase matchday, or the leg (1/2) of a knockout
               tie; empty for the final
    score      regularTime is the 90-minute score on a match that went to
               extra time (fullTime includes it); not used, as results
               come from FotMob

football-data.org only knows the modelled leagues' clubs by id
(team_names.csv), so each fixture is paired with the same match in
FotMob's fixture list (same day, a known club on the same side) to get
FotMob's ids - the identity every CL row uses - and its match id.
"""

import pandas as pd

import competitions
from european import TEAMS_PATH, _club_names, read_teams
from load_data import OUTPUT_PATH, RAW_DIR, competition_dir
from team_names import REFERENCE_PATH, load_country_map, load_id_map

# football-data.org stage -> our Stage (plan §3.1)
FD_ORG_STAGES = {
    "GROUP_STAGE": "GROUP",
    "LEAGUE_STAGE": "LEAGUE_PHASE",
    "PLAYOFFS": "KO_PLAYOFF",
    "LAST_16": "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS": "SF",
    "FINAL": "FINAL",
}

STAGE_ORDER = ["GROUP", "LEAGUE_PHASE", "KO_PLAYOFF", "R16", "QF", "SF", "FINAL"]
TWO_LEGGED = {"KO_PLAYOFF", "R16", "QF", "SF"}
KNOCKOUT = TWO_LEGGED | {"FINAL"}

# FotMob's whole-season fixture list (played or not), saved by
# european.fetch_season next to the results cache
FIXTURE_LIST_COLUMNS = [
    "MatchId", "Kickoff", "Round", "HomeId", "AwayId", "HomeTeam", "AwayTeam",
]


def fixture_list_path(div, season, raw_dir=RAW_DIR):
    """data/raw/<Div>/fixtures_<season>.csv."""

    return competition_dir(div, raw_dir) / f"fixtures_{season}.csv"


def is_knockout(stage):

    return stage in KNOCKOUT


# ============================================================
# STAGES AND LEGS
# ============================================================

def fd_org_round(stage, matchday):
    """
    (Stage, Round, Leg) for a football-data.org stage and matchday, e.g.
    ("LEAGUE_STAGE", 5) -> ("LEAGUE_PHASE", "MD5", None) and
    ("LAST_16", 2) -> ("R16", "R16", 2).
    """

    try:
        ours = FD_ORG_STAGES[stage]
    except KeyError:
        raise ValueError(
            f"Unknown football-data.org stage {stage!r}; add it to FD_ORG_STAGES"
        ) from None

    if ours in ("GROUP", "LEAGUE_PHASE"):
        return ours, f"MD{int(matchday)}", None

    if ours in TWO_LEGGED:
        return ours, ours, int(matchday) if pd.notna(matchday) else None

    return ours, ours, None


def round_order(stage, round_, leg):
    """A sortable position for a round: league matchdays, then each knockout leg."""

    position = STAGE_ORDER.index(stage) * 100

    if round_.startswith("MD"):
        return position + int(round_[2:])

    return position + (leg or 0)


def fd_org_frame(matches, div="CL"):
    """
    football-data.org ``/competitions/CL/matches`` -> one row per match:
    status, UTC kick-off, Stage/Round/Leg, an order for its round, and
    both clubs' football-data.org ids and names.
    """

    rows = []

    for match in matches:

        stage, round_, leg = fd_org_round(match["stage"], match.get("matchday"))

        rows.append({
            "Div": div,
            "Status": match["status"],
            "KickoffUTC": pd.Timestamp(match["utcDate"]),
            "Stage": stage,
            "Round": round_,
            "Leg": leg,
            "RoundOrder": round_order(stage, round_, leg),
            "FdHomeId": (match["homeTeam"] or {}).get("id"),
            "FdAwayId": (match["awayTeam"] or {}).get("id"),
            "FdHomeTeam": (match["homeTeam"] or {}).get("name"),
            "FdAwayTeam": (match["awayTeam"] or {}).get("name"),
        })

    frame = pd.DataFrame(rows)

    # Knockout ties not drawn yet have no clubs
    if not frame.empty:
        frame = frame.dropna(subset=["FdHomeId", "FdAwayId"]).reset_index(drop=True)
        frame[["FdHomeId", "FdAwayId"]] = frame[["FdHomeId", "FdAwayId"]].astype(int)
        frame["Leg"] = frame["Leg"].astype("Int64")

    return frame


# ============================================================
# FOTMOB FIXTURE LIST
# ============================================================

def parse_fixture_list(league):
    """Every match in a FotMob ``leagues`` response, played or not."""

    rows = [
        {
            "MatchId": str(match["id"]),
            "Kickoff": match["status"]["utcTime"],
            "Round": str(match["round"]),
            "HomeId": int(match["home"]["id"]),
            "AwayId": int(match["away"]["id"]),
            "HomeTeam": match["home"]["name"],
            "AwayTeam": match["away"]["name"],
        }
        for match in league["fixtures"]["allMatches"]
        if not match["status"].get("cancelled")
    ]

    return pd.DataFrame(rows, columns=FIXTURE_LIST_COLUMNS)


def read_fixture_list(div, season, raw_dir=RAW_DIR):

    path = fixture_list_path(div, season, raw_dir)

    if not path.exists():
        raise FileNotFoundError(
            f"No FotMob fixture list at {path} - run_week's step 1 "
            f"(european.fetch_season) writes it."
        )

    return pd.read_csv(path, dtype={"MatchId": str})


# ============================================================
# PAIRING FOOTBALL-DATA.ORG WITH FOTMOB
# ============================================================

def known_fd_org_ids(reference_path=REFERENCE_PATH):
    """football-data.org id -> FotMob id for every club in team_names.csv with both."""

    reference = pd.read_csv(
        reference_path, dtype={"fotmob_id": "Int64", "football_data_org_id": "Int64"}
    ).dropna(subset=["fotmob_id", "football_data_org_id"])

    return dict(zip(
        reference["football_data_org_id"].astype(int), reference["fotmob_id"].astype(int)
    ))


def pair_matches(fd, fotmob, known):
    """
    For each football-data.org match in ``fd`` (FdHomeId, FdAwayId, Day),
    the index of the same match in ``fotmob`` (HomeId, AwayId, Day), or
    None. ``known`` maps football-data.org ids to FotMob ids.

    A match pairs with the FotMob match that day with a known club on the
    same side; the other club's id is then learned, which pairs more
    matches on the next pass (clubs from outside the modelled leagues are
    learned this way). A match whose clubs are both unknown pairs only if
    it is the one unpaired match left that day on both sides.

    Returns (pairs, learned): {fd index: fotmob index} and the
    id map grown by every pair.
    """

    known = dict(known)
    pairs = {}
    open_fd = {day: list(group.index) for day, group in fd.groupby("Day")}
    open_fm = {day: list(group.index) for day, group in fotmob.groupby("Day")}

    def learn(fd_id, fotmob_id):
        if known.get(fd_id, fotmob_id) != fotmob_id:
            raise ValueError(
                f"football-data.org club {fd_id} pairs with FotMob clubs "
                f"{known[fd_id]} and {fotmob_id}"
            )
        known[fd_id] = fotmob_id

    progress = True
    while progress:
        progress = False

        for day, fd_rows in open_fd.items():
            fm_rows = open_fm.get(day, [])

            for i in list(fd_rows):
                home = known.get(fd.at[i, "FdHomeId"])
                away = known.get(fd.at[i, "FdAwayId"])

                candidates = [
                    j for j in fm_rows
                    if (home is not None and fotmob.at[j, "HomeId"] == home)
                    or (away is not None and fotmob.at[j, "AwayId"] == away)
                ]

                if not candidates and home is None and away is None:
                    claimed = set(known.values())
                    free = [
                        j for j in fm_rows
                        if fotmob.at[j, "HomeId"] not in claimed
                        and fotmob.at[j, "AwayId"] not in claimed
                    ]
                    if len(fd_rows) == 1 and len(free) == 1:
                        candidates = free

                if len(candidates) != 1:
                    continue

                j = candidates[0]
                learn(fd.at[i, "FdHomeId"], int(fotmob.at[j, "HomeId"]))
                learn(fd.at[i, "FdAwayId"], int(fotmob.at[j, "AwayId"]))
                pairs[i] = j
                fd_rows.remove(i)
                fm_rows.remove(j)
                progress = True

    return pairs, known


# ============================================================
# FIXTURES WITH CLUB IDENTITY
# ============================================================

def club_leagues(team_ids, season, domestic=None, reference_path=REFERENCE_PATH,
                 teams_path=TEAMS_PATH):
    """
    FotMob id -> each club's league in ``season``: its Div in
    ``domestic`` (default all_matches.csv), else "X:<country>" - the
    rule european.load_european uses for HomeLeague/AwayLeague.
    """

    id_map = load_id_map(reference_path=reference_path)
    countries = load_country_map(reference_path=reference_path)
    teams = read_teams(teams_path)
    fotmob_countries = dict(zip(teams["FotMobId"], teams["Country"]))

    if domestic is None:
        domestic = pd.read_csv(OUTPUT_PATH, usecols=["Div", "Season", "HomeTeam", "AwayTeam"])

    leagues = [d for d, e in competitions.COMPETITIONS.items() if e["kind"] == "league"]
    played = domestic[(domestic["Div"].isin(leagues)) & (domestic["Season"] == season)]
    league_of = {
        team: div
        for side in ("HomeTeam", "AwayTeam")
        for div, team in zip(played["Div"], played[side])
    }

    def league(team_id):
        name = id_map.get(team_id)
        if name in league_of:
            return league_of[name]
        country = countries.get(name) if name else fotmob_countries.get(team_id)
        return f"X:{country}" if isinstance(country, str) else None

    return {team_id: league(team_id) for team_id in team_ids}


def resolve_fixtures(fd, fotmob, season, known=None, domestic=None,
                     european_rows=None, reference_path=REFERENCE_PATH,
                     teams_path=TEAMS_PATH):
    """
    football-data.org fixtures (fd_org_frame) with FotMob's identity:
    MatchId, HomeTeam/AwayTeam (the canonical name where team_names.csv
    has the club, else FotMob's, as in the CL rows of all_matches),
    HomeLeague/AwayLeague and Neutral.

    Neutral is 1 for the final, and for a home side whose latest home
    European match in ``european_rows`` (load_european) was neutral - a
    club playing its home ties abroad, such as Ukraine's since 22-23.

    Raises ValueError naming any fixture that can't be paired.
    """

    fd = fd.copy()
    fotmob = fotmob.copy()
    fd["Day"] = pd.to_datetime(fd["KickoffUTC"], utc=True).dt.strftime("%Y-%m-%d")
    fotmob["Day"] = pd.to_datetime(fotmob["Kickoff"], utc=True).dt.strftime("%Y-%m-%d")

    pairs, _ = pair_matches(fd, fotmob, known if known is not None else known_fd_org_ids(reference_path))

    unpaired = fd.index.difference(list(pairs))
    if len(unpaired):
        sample = fd.loc[unpaired[:5], ["Day", "FdHomeTeam", "FdAwayTeam"]]
        raise ValueError(
            f"{len(unpaired)} football-data.org fixture(s) not found in FotMob's "
            f"fixture list:\n{sample.to_string(index=False)}"
        )

    matched = fotmob.loc[[pairs[i] for i in fd.index]].reset_index(drop=True)
    fd = fd.reset_index(drop=True)

    names = _club_names(matched, load_id_map(reference_path=reference_path), read_teams(teams_path))
    ids = set(matched["HomeId"]) | set(matched["AwayId"])
    leagues = club_leagues(ids, season, domestic, reference_path, teams_path)

    fd["MatchId"] = matched["MatchId"].astype(str)
    fd["HomeId"] = matched["HomeId"].astype(int)
    fd["AwayId"] = matched["AwayId"].astype(int)
    fd["HomeTeam"] = fd["HomeId"].map(names)
    fd["AwayTeam"] = fd["AwayId"].map(names)
    fd["HomeLeague"] = fd["HomeId"].map(leagues)
    fd["AwayLeague"] = fd["AwayId"].map(leagues)

    plays_abroad = set()
    if european_rows is not None and len(european_rows):
        home_ties = european_rows[european_rows["Stage"] != "FINAL"]
        latest = home_ties.sort_values("Date").drop_duplicates("HomeTeam", keep="last")
        plays_abroad = set(latest.loc[latest["Neutral"] == 1, "HomeTeam"])

    fd["Neutral"] = (
        (fd["Stage"] == "FINAL") | fd["HomeTeam"].isin(plays_abroad)
    ).astype(int)

    return fd.drop(columns=["Day"])


# ============================================================
# NEUTRAL VENUE (plan §4B.4)
# ============================================================

def neutral_probabilities(forward, reverse):
    """
    H/D/A probabilities for A v B at a neutral venue from the model's
    two home-venue views: ``forward`` = A at home to B, ``reverse`` = B at
    home to A (frames or dicts with H, D, A). EloDiff has no home term -
    the model's intercept is the home advantage - so averaging the two
    orientations removes it:

        P(A win) = (P_H(A v B) + P_A(B v A)) / 2
        P(draw)  = (P_D(A v B) + P_D(B v A)) / 2
        P(B win) = (P_A(A v B) + P_H(B v A)) / 2
    """

    def column(frame, outcome):
        value = frame[outcome]
        return value.to_numpy() if hasattr(value, "to_numpy") else value

    probabilities = {
        "H": (column(forward, "H") + column(reverse, "A")) / 2,
        "D": (column(forward, "D") + column(reverse, "D")) / 2,
        "A": (column(forward, "A") + column(reverse, "H")) / 2,
    }

    if isinstance(forward, pd.DataFrame):
        return pd.DataFrame(probabilities, index=forward.index)[list(forward.columns)]

    return probabilities
