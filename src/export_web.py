"""
Write the tidy JSON files the website reads.

    python src/export_web.py

Reads data/processed/all_matches.csv, data/raw/Bets.csv and produces:

    web/src/data/predictions.json  - each competition's upcoming gameweek
    web/src/data/bets.json         - every bet, with result and profit
    web/src/data/stats.json        - headline numbers, calibration, by-gameweek,
                                     as {overall, byCompetition: {E0: ...}}
    web/src/data/elo.json          - current Elo ratings: each league's own
                                     (``elo``) and on the scale shared by
                                     every league (``rating``), plus clubs
                                     from outside the leagues seen in Europe
    web/src/data/elo_history.json  - shared-scale ratings over the last
                                     year, and each league's offset over time
    web/src/data/table.json       - current standings + projected final table,
                                     as {byCompetition: {E0: ...}}
    web/src/data/leagues.json      - the competitions the pipeline runs
    web/src/data/run_status.json   - how each competition fared in the run
                                     (run_status.py), for the stale badge
    web/src/data/cups.json         - each cup's league-phase table (current +
                                     projected) and knockout ties (with each
                                     tie's progression probability and its
                                     walk-forward Brier score, P6-02), as
                                     {byCompetition: {CL: ...}}

Every competition in competitions.ENABLED is exported, and each
prediction, bet and rating carries its ``div``. The model behind the
projected tables is trained on every competition, as the live
predictions are.

A cup (the Champions League) has no Gameweek: its bets' Round (MD1..MD8,
KO_PLAYOFF, R16...) becomes a round number, so it sorts and charts like
one - league-phase matchdays 1-8, then one number per knockout leg
(CUP_ROUND_START; web/src/lib/routes.ts roundLabel names them).

Runs as part of run_week.py so CI keeps the site's data current.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import competitions
from bet_schema import add_missing_columns
from team_names import load_alias_map
from predict_next_matches import (
    build_elo_feature,
    build_history,
    train_models,
    predict_fixtures,
    HOME_ADVANTAGE,
)
from dixon_coles import fit_dixon_coles, expected_goals
from elo import EUROPE_HOME_ADVANTAGE, is_cup, shared_scale
from european import KNOCKOUT_STAGES, _club_names, read_teams, results_for_elo
from champions_league import (
    KNOCKOUT, STAGE_ORDER, TWO_LEGGED, club_leagues, fixture_list_path,
)
from load_data import read_matches
from team_names import load_id_map
from tie_progression import (
    advance_probability, backtest_ties, bootstrap_against_coin, brier,
    leg_probabilities, season_models,
)

ROOT = Path(__file__).resolve().parents[1]

MATCHES_PATH = ROOT / "data" / "processed" / "all_matches.csv"
STATUS_PATH = ROOT / "data" / "processed" / "run_status.json"
BETS_PATH = ROOT / "data" / "raw" / "Bets.csv"
OUT_DIR = ROOT / "web" / "src" / "data"

PROB_COLS = ["HomeProb", "DrawProb", "AwayProb"]

# Calibration buckets on the model's probability for its own pick
CALIB_EDGES = [0, 40, 45, 50, 55, 60, 100]

# The competition the home page selects first
DEFAULT_DIV = "E0"

# How far back elo_history.json goes
HISTORY_DAYS = 365

# A cup's round numbers: league-phase matchday N is N; each knockout leg
# follows on (play-off legs 9-10, round of 16 11-12, ... final 17)
CUP_ROUND_START = {"KO_PLAYOFF": 9, "R16": 11, "QF": 13, "SF": 15, "FINAL": 17}

# League-phase places: 1-8 go to the round of 16, 9-24 to the play-off
LEAGUE_PHASE_ZONES = {"direct": 8, "playoff": 24}


# ============================================================
# LOADERS
# ============================================================

def load_matches(cups=False):
    """all_matches.csv: the league rows, plus the cup rows with ``cups``."""

    matches = read_matches(MATCHES_PATH, cups=cups)

    return matches.sort_values(
        ["MatchDateTime", "HomeTeam", "AwayTeam"]
    ).reset_index(drop=True)


def cup_rounds(bets):
    """
    Each cup bet's round number from its Round: "MD5" -> 5, a knockout
    leg CUP_ROUND_START + leg - 1 ("R16" second leg -> 12), the leg being
    the tie's kick-off order (same season, round and pair of clubs).
    """

    rounds = bets["Round"].astype("string")
    numbers = pd.Series(pd.NA, index=bets.index, dtype="Int64")

    matchday = rounds.str.fullmatch(r"MD\d+").fillna(False)
    numbers[matchday] = rounds[matchday].str[2:].astype(int)

    knockout = rounds.isin(CUP_ROUND_START).fillna(False)
    if knockout.any():
        ko = bets[knockout]
        pair = ko.apply(lambda r: "|".join(sorted((r["HomeTeam"], r["AwayTeam"]))), axis=1)
        leg = ko.groupby([ko["Season"], rounds[knockout], pair])["Kickoff"].rank(method="first")
        numbers[knockout] = rounds[knockout].map(CUP_ROUND_START).astype(int) + leg.astype(int) - 1

    unknown = numbers.isna()
    if unknown.any():
        raise ValueError(
            f"Cup bet round(s) {sorted(rounds[unknown].fillna('<empty>').unique())} have no "
            f"round number; add them to CUP_ROUND_START"
        )

    return numbers.astype(int)


def load_bets(div=None):
    """
    Bets.csv, of competition ``div`` only when given, in kickoff order.
    A cup's bets get their round number as Gameweek (cup_rounds).
    """

    bets = add_missing_columns(pd.read_csv(BETS_PATH))

    # Before sorting, so other competitions' rows can't reorder this
    # one's same-kickoff bets
    if div is not None:
        bets = bets[bets["Div"] == div].reset_index(drop=True)

    alias_map = load_alias_map()
    bets["HomeTeam"] = bets["HomeTeam"].replace(alias_map)
    bets["AwayTeam"] = bets["AwayTeam"].replace(alias_map)

    bets["Kickoff"] = pd.to_datetime(
        bets["Date"] + " " + bets["Time"], dayfirst=True
    )
    bets["Won"] = bets["PredictedResult"] == bets["ActualResult"]
    bets["PickProb"] = bets[PROB_COLS].max(axis=1)

    if div is not None and is_cup(div) and len(bets):
        bets["Gameweek"] = cup_rounds(bets)

    return bets.sort_values("Kickoff").reset_index(drop=True)


def current_elos(matches, div=None, ratings=None):
    """
    Elo ratings, restricted to the teams in the current season (of
    competition ``div`` only, when given). Pass ``ratings`` to skip
    rebuilding them from ``matches``.
    """

    if ratings is None:
        ratings = build_elo_feature(matches.copy())

    if div is not None:
        matches = matches[matches["Div"] == div]

    latest_season = matches.sort_values("MatchDateTime")["Season"].iloc[-1]
    current = matches[matches["Season"] == latest_season]
    teams = set(current["HomeTeam"]) | set(current["AwayTeam"])

    return {
        team: round(rating)
        for team, rating in ratings.items()
        if team in teams
    }


# ============================================================
# PREDICTIONS
# ============================================================

def build_predictions(bets, elos, home_advantage=HOME_ADVANTAGE):
    """One competition's fixtures for the gameweek to feature: the earliest
    one with unsettled bets, or failing that the most recent on record.
    ``home_advantage`` goes into eloGap (none for a cup final)."""

    if bets.empty:
        return []

    unsettled = bets[bets["ActualResult"].isna()]

    if not unsettled.empty:
        gameweek = int(unsettled["Gameweek"].min())
    else:
        gameweek = int(bets["Gameweek"].max())

    rows = bets[bets["Gameweek"] == gameweek]

    fixtures = []

    for _, row in rows.iterrows():

        home_elo = elos.get(row["HomeTeam"], 1500)
        away_elo = elos.get(row["AwayTeam"], 1500)
        advantage = 0 if row.get("Round") == "FINAL" else home_advantage

        fixtures.append({
            "div": row["Div"],
            "gameweek": gameweek,
            "date": row["Date"],
            "time": row["Time"],
            "kickoff": row["Kickoff"].isoformat(),
            "home": row["HomeTeam"],
            "away": row["AwayTeam"],
            "prediction": row["PredictedResult"],
            "homeProb": _num(row["HomeProb"]),
            "drawProb": _num(row["DrawProb"]),
            "awayProb": _num(row["AwayProb"]),
            "homeElo": home_elo,
            "awayElo": away_elo,
            "eloGap": round(home_elo + advantage - away_elo),
            "result": _str(row["ActualResult"]),
            "settled": bool(pd.notna(row["ActualResult"])),
        })

    return fixtures


# ============================================================
# BETS
# ============================================================

def build_bets(bets):

    records = []

    for _, row in bets.iterrows():

        settled = bool(pd.notna(row["ActualResult"]))

        records.append({
            "div": row["Div"],
            "gameweek": int(row["Gameweek"]),
            "date": row["Date"],
            "time": row["Time"],
            "kickoff": row["Kickoff"].isoformat(),
            "home": row["HomeTeam"],
            "away": row["AwayTeam"],
            "prediction": row["PredictedResult"],
            "homeProb": _num(row["HomeProb"]),
            "drawProb": _num(row["DrawProb"]),
            "awayProb": _num(row["AwayProb"]),
            "result": _str(row["ActualResult"]),
            "profit": _num(row["Profit"]) if settled else None,
            "won": bool(row["Won"]) if settled else None,
            "settled": settled,
            "backfilled": bool(row["Backfilled"] == 1),
        })

    return records


# ============================================================
# STATS
# ============================================================

def build_stats(bets):

    # Unpriced bets (Bet = 0, no Profit) count towards hit rate and
    # calibration, but not towards profit, stake or the bankroll
    settled = bets[bets["ActualResult"].notna()].copy()
    priced = settled[settled["Profit"].notna()]

    if settled.empty:
        return {
            "asOf": None,
            "totalBets": int(len(bets)),
            "backfilledBets": 0,
            "backfilledGameweeks": None,
            "settledBets": 0,
            "pendingBets": int(bets["ActualResult"].isna().sum()),
            "calibration": [],
            "byGameweek": [],
            "byPick": [],
            "bankroll": [],
            "bestBets": [],
            "worstBets": [],
        }

    stake = priced["Bet"].fillna(1)
    wins = int(settled["Won"].sum())
    profit = float(priced["Profit"].sum())
    staked = float(stake.sum())

    baseline_hit = float((settled["ActualResult"] == "H").mean())
    hit_rate = wins / len(settled)

    # Mean negative log of the probability given to what happened
    outcome_prob = pd.Series(
        [
            row[col] for row, col in zip(
                settled[PROB_COLS].to_dict("records"),
                settled["ActualResult"].map(dict(zip("HDA", PROB_COLS))),
            )
        ],
        dtype=float,
    )
    log_loss = float(-np.log((outcome_prob / 100).clip(1e-15, 1)).mean())

    # Cumulative profit, one point per settled bet in kickoff order
    running = 0.0
    bankroll = []
    for _, row in priced.sort_values("Kickoff").iterrows():
        running += float(row["Profit"])
        bankroll.append({
            "div": row["Div"],
            "kickoff": row["Kickoff"].isoformat(),
            "gameweek": int(row["Gameweek"]),
            "match": f'{row["HomeTeam"]} v {row["AwayTeam"]}',
            "profit": round(float(row["Profit"]), 2),
            "cumulative": round(running, 2),
        })

    # Calibration on the model's probability for its own pick
    buckets = pd.cut(settled["PickProb"], bins=CALIB_EDGES, right=False)
    calibration = []
    for interval, group in settled.groupby(buckets, observed=True):
        calibration.append({
            "label": f"{int(interval.left)}-{int(interval.right)}%",
            "bets": int(len(group)),
            "avgProb": round(float(group["PickProb"].mean()), 1),
            "hitRate": round(float(group["Won"].mean()) * 100, 1),
        })

    # Per gameweek - every gameweek on record, settled or not, with a
    # running cumulative profit through the settled ones
    by_gameweek = []
    running_gw = 0.0
    for gameweek in sorted(bets["Gameweek"].dropna().unique()):
        group = bets[bets["Gameweek"] == gameweek]
        done = group[group["ActualResult"].notna()]

        gw_profit = round(float(done["Profit"].sum()), 2) if len(done) else None
        if gw_profit is not None:
            running_gw += gw_profit

        if len(done) == 0:
            status = "pending"
        elif len(done) == len(group):
            status = "complete"
        else:
            status = "partial"

        by_gameweek.append({
            "gameweek": int(gameweek),
            "bets": int(len(group)),
            "settled": int(len(done)),
            "hits": int(done["Won"].sum()) if len(done) else 0,
            "hitRate": (
                round(float(done["Won"].mean()) * 100, 1) if len(done) else None
            ),
            "profit": gw_profit,
            "cumulativeProfit": (
                round(running_gw, 2) if gw_profit is not None else None
            ),
            "status": status,
        })

    # How the model's picks split, and how each does
    outcome_labels = {"H": "Home", "D": "Draw", "A": "Away"}
    by_pick = []
    for outcome, label in outcome_labels.items():
        picks = settled[settled["PredictedResult"] == outcome]
        by_pick.append({
            "pick": outcome,
            "label": label,
            "bets": int(len(picks)),
            "hits": int(picks["Won"].sum()),
            "hitRate": (
                round(float(picks["Won"].mean()) * 100, 1)
                if len(picks) else None
            ),
            "profit": round(float(picks["Profit"].sum()), 2),
        })

    # Biggest wins, and the most confident misses
    best_bets = [
        _bet_summary(row)
        for _, row in priced[priced["Won"]]
        .sort_values("Profit", ascending=False)
        .head(3)
        .iterrows()
    ]
    worst_bets = [
        _bet_summary(row)
        for _, row in settled[~settled["Won"]]
        .sort_values("PickProb", ascending=False)
        .head(3)
        .iterrows()
    ]

    backfilled = bets[bets["Backfilled"] == 1]

    return {
        "asOf": settled["Kickoff"].max().date().isoformat(),
        "totalBets": int(len(bets)),
        # Predictions made after the match, point-in-time (bet_schema)
        "backfilledBets": int(len(backfilled)),
        "backfilledGameweeks": (
            [int(backfilled["Gameweek"].min()), int(backfilled["Gameweek"].max())]
            if len(backfilled) else None
        ),
        "settledBets": int(len(settled)),
        "pendingBets": int(bets["ActualResult"].isna().sum()),
        "wins": wins,
        "losses": int(len(settled) - wins),
        "hitRate": round(hit_rate * 100, 1),
        "baselineHitRate": round(baseline_hit * 100, 1),
        "edge": round((hit_rate - baseline_hit) * 100, 1),
        "logLoss": round(log_loss, 3),
        # Bets with odds: profit, staked and ROI count only these
        "pricedBets": int(len(priced)),
        "profit": round(profit, 2),
        "staked": round(staked, 2),
        "roi": round(profit / staked * 100, 1) if staked else 0.0,
        "calibration": calibration,
        "byGameweek": by_gameweek,
        "byPick": by_pick,
        "bankroll": bankroll,
        "bestBets": best_bets,
        "worstBets": worst_bets,
    }


# ============================================================
# LEAGUE TABLE
# ============================================================

def _blank_row(team):
    return {
        "team": team, "played": 0, "won": 0, "drawn": 0, "lost": 0,
        "gf": 0, "ga": 0, "points": 0,
    }


def _award(rows, home, away, outcome, home_goals=None, away_goals=None):

    rows[home]["played"] += 1
    rows[away]["played"] += 1

    if home_goals is not None:
        rows[home]["gf"] += home_goals
        rows[home]["ga"] += away_goals
        rows[away]["gf"] += away_goals
        rows[away]["ga"] += home_goals

    if outcome == "H":
        rows[home]["won"] += 1
        rows[away]["lost"] += 1
        rows[home]["points"] += 3
    elif outcome == "A":
        rows[away]["won"] += 1
        rows[home]["lost"] += 1
        rows[away]["points"] += 3
    else:
        rows[home]["drawn"] += 1
        rows[away]["drawn"] += 1
        rows[home]["points"] += 1
        rows[away]["points"] += 1


def _rank(rows):

    ordered = sorted(
        rows,
        key=lambda r: (
            -r["points"],
            -(r["gf"] - r["ga"]),
            -r["gf"],
            r["team"],
        ),
    )

    for position, row in enumerate(ordered, start=1):
        row["position"] = position
        row["gd"] = row["gf"] - row["ga"]

    return ordered


def _current_season(matches):
    ordered = matches.sort_values("MatchDateTime")
    season = ordered["Season"].iloc[-1]
    played = ordered[ordered["Season"] == season]
    teams = sorted(set(played["HomeTeam"]) | set(played["AwayTeam"]))
    return season, played, teams


def current_standings(matches):
    """The league table so far, from played matches this season."""

    _, played, teams = _current_season(matches)
    rows = {team: _blank_row(team) for team in teams}

    for _, match in played.iterrows():
        _award(
            rows, match["HomeTeam"], match["AwayTeam"], match["FTR"],
            int(match["FTHG"]), int(match["FTAG"]),
        )

    return _rank(rows.values())


def predicted_standings(matches, bets):
    """
    The table if the model's recorded pick for every match played so far
    this season had been the actual result. No goal difference - picks are
    results, not scores - so ties break on the real table's order.
    """

    _, played, teams = _current_season(matches)
    played_pairs = set(zip(played["HomeTeam"], played["AwayTeam"]))

    season_bets = bets[
        bets.apply(
            lambda row: (row["HomeTeam"], row["AwayTeam"]) in played_pairs,
            axis=1,
        )
        & bets["PredictedResult"].notna()
    ]

    real_order = {
        row["team"]: row["position"] for row in current_standings(matches)
    }

    rows = {team: _blank_row(team) for team in teams}
    for _, bet in season_bets.iterrows():
        _award(
            rows, bet["HomeTeam"], bet["AwayTeam"], bet["PredictedResult"]
        )

    ordered = sorted(
        rows.values(),
        key=lambda r: (-r["points"], real_order[r["team"]]),
    )
    for position, row in enumerate(ordered, start=1):
        row["position"] = position
        row.pop("gf", None)
        row.pop("ga", None)

    return ordered


def projected_table(matches, history=None, trained=None):
    """
    Projected final table: current standings plus, for every fixture not
    yet played this season, each team's *expected* points from the model's
    probabilities (3 x P(win) + 1 x P(draw)) and *expected* goals from a
    Dixon-Coles goal model, so goal difference projects forward too instead
    of freezing at its current value. Nothing here feeds back into the
    prediction model itself - it's a display-only addition for this table.
    Expected wins/draws/losses/goals are rounded for display.

    ``matches`` is one competition; the models are trained on ``history``
    (default: the same matches), e.g. every competition, as for the
    live predictions. Pass ``trained`` (from ``train_history``) to reuse
    models already fitted on ``history``.
    """

    if trained is None:
        trained = train_history(matches if history is None else history)
    models, elos, team_history = trained

    # Display-only extra: if the goal model can't be fitted, goal difference
    # just stays at its current value rather than failing the whole export.
    try:
        dc_model, dc_known_teams = fit_dixon_coles(matches)
    except Exception as exc:
        print(f"Skipping projected goal difference - Dixon-Coles fit failed: {exc}")
        dc_model, dc_known_teams = None, set()

    _, played, teams = _current_season(matches)
    played_pairs = set(zip(played["HomeTeam"], played["AwayTeam"]))

    remaining = pd.DataFrame([
        {"Date": "", "Time": "", "HomeTeam": home, "AwayTeam": away}
        for home in teams
        for away in teams
        if home != away and (home, away) not in played_pairs
    ])
    if "Div" in matches.columns:
        remaining.insert(0, "Div", matches["Div"].iloc[0])

    scored = predict_fixtures(remaining, models, elos, team_history)

    rows = {row["team"]: dict(row) for row in current_standings(matches)}
    for row in rows.values():
        row.pop("position", None)
        row.pop("gd", None)
        row["points"] = float(row["points"])
        row["gf"] = float(row["gf"])
        row["ga"] = float(row["ga"])
        for key in ("won", "drawn", "lost"):
            row[key] = float(row[key])

    for _, fixture in scored.iterrows():
        home, away = fixture["HomeTeam"], fixture["AwayTeam"]
        p_home = fixture["HomeProb"] / 100
        p_draw = fixture["DrawProb"] / 100
        p_away = fixture["AwayProb"] / 100

        rows[home]["played"] += 1
        rows[away]["played"] += 1
        rows[home]["points"] += 3 * p_home + p_draw
        rows[away]["points"] += 3 * p_away + p_draw
        rows[home]["won"] += p_home
        rows[away]["won"] += p_away
        rows[home]["drawn"] += p_draw
        rows[away]["drawn"] += p_draw
        rows[home]["lost"] += p_away
        rows[away]["lost"] += p_home

        home_goals, away_goals = (
            expected_goals(dc_model, dc_known_teams, home, away)
            if dc_model is not None else (None, None)
        )
        if home_goals is not None:
            rows[home]["gf"] += home_goals
            rows[home]["ga"] += away_goals
            rows[away]["gf"] += away_goals
            rows[away]["ga"] += home_goals

    ranked = _rank(rows.values())  # on exact expected points/goals

    for row in ranked:
        row["points"] = round(row["points"])
        row["gf"] = round(row["gf"], 1)
        row["ga"] = round(row["ga"], 1)
        row["gd"] = round(row["gd"], 1)
        for key in ("won", "drawn", "lost"):
            row[key] = round(row[key])

    return ranked, len(remaining)


def train_history(history, european=None):
    """The models, Elo ratings and team history to score fixtures with."""

    rows, elos, team_history = build_history(history, european=european)
    return train_models(rows), elos, team_history


def build_table(matches, bets, history=None, trained=None):

    current = current_standings(matches)
    predicted = predicted_standings(matches, bets)
    projected, remaining = projected_table(matches, history, trained)

    current_position = {row["team"]: row["position"] for row in current}
    for table in (predicted, projected):
        for row in table:
            was = current_position[row["team"]]
            row["currentPosition"] = was
            row["movement"] = was - row["position"]

    season, played, _ = _current_season(matches)

    return {
        "season": season,
        "playedFixtures": int(len(played)),
        "remainingFixtures": int(remaining),
        "current": current,
        "predicted": predicted,
        "projected": projected,
    }


# ============================================================
# CUPS: LEAGUE PHASE AND KNOCKOUTS
# ============================================================

KNOCKOUT_ROUNDS = [stage for stage in STAGE_ORDER if stage in KNOCKOUT]


def cup_fixture_list(div, season):
    """
    FotMob's whole-season fixture list for a cup (played or not), with
    canonical club names, UTC kick-offs and each match's Stage; None if
    there's no list on file.
    """

    path = fixture_list_path(div, season)
    if not path.exists():
        return None

    fixtures = pd.read_csv(path, dtype={"MatchId": str, "Round": str})
    if fixtures.empty:
        return None

    names = _club_names(fixtures, load_id_map(), read_teams())
    for side in ("Home", "Away"):
        fixtures[f"{side}Id"] = fixtures[f"{side}Id"].astype(int)
        fixtures[f"{side}Team"] = fixtures[f"{side}Id"].map(names)

    fixtures["KickoffUTC"] = pd.to_datetime(fixtures["Kickoff"], utc=True)
    fixtures["Stage"] = [
        "LEAGUE_PHASE" if r.isdigit() else KNOCKOUT_STAGES.get(r) for r in fixtures["Round"]
    ]

    return fixtures


def _plays_abroad(cup_matches):
    """Clubs whose latest home European tie was at a neutral venue (champions_league.resolve_fixtures)."""

    home_ties = cup_matches[cup_matches["Stage"] != "FINAL"]
    latest = home_ties.sort_values("MatchDateTime").drop_duplicates("HomeTeam", keep="last")

    return set(latest.loc[latest["Neutral"] == 1, "HomeTeam"])


def _rank_league_phase(rows):
    """UEFA's league-phase order: points, goal difference, goals, away goals, wins, away wins."""

    ordered = sorted(
        rows,
        key=lambda r: (
            -r["points"], -(r["gf"] - r["ga"]), -r["gf"],
            -r["awayGf"], -r["won"], -r["awayWon"], r["team"],
        ),
    )

    for position, row in enumerate(ordered, start=1):
        row["position"] = position
        row["gd"] = row["gf"] - row["ga"]
        row.pop("awayGf")
        row.pop("awayWon")

    return ordered


def build_league_phase(div, cup_matches, fixtures, season, trained, domestic):
    """
    A cup's league-phase table: the standings so far, and projected to
    the last matchday by adding each remaining fixture's expected points
    (3 x P(win) + P(draw)) from the cup's model, as projected_table does
    for a league (no goal model, so no projected goal difference). None
    when the season has no league phase on record.
    """

    played = cup_matches[
        (cup_matches["Div"] == div)
        & (cup_matches["Season"] == season)
        & (cup_matches["Stage"] == "LEAGUE_PHASE")
    ]
    planned = (
        fixtures[fixtures["Stage"] == "LEAGUE_PHASE"]
        if fixtures is not None else pd.DataFrame(columns=["MatchId", "HomeTeam", "AwayTeam", "Round"])
    )

    if played.empty and planned.empty:
        return None

    teams = sorted(
        set(played["HomeTeam"]) | set(played["AwayTeam"])
        | set(planned["HomeTeam"]) | set(planned["AwayTeam"])
    )

    # Each club's league that season ("X:<country>" outside the modelled ones)
    league_of = {}
    if not planned.empty:
        by_id = club_leagues(
            set(planned["HomeId"]) | set(planned["AwayId"]), season, domestic=domestic
        )
        for side in ("Home", "Away"):
            league_of.update(zip(planned[f"{side}Team"], planned[f"{side}Id"].map(by_id)))
    for side in ("Home", "Away"):
        league_of.update(zip(played[f"{side}Team"], played[f"{side}League"]))

    def blank(team):
        return {**_blank_row(team), "awayGf": 0, "awayWon": 0}

    rows = {team: blank(team) for team in teams}
    for match in played.itertuples():
        _award(rows, match.HomeTeam, match.AwayTeam, match.FTR, int(match.FTHG), int(match.FTAG))
        rows[match.AwayTeam]["awayGf"] += int(match.FTAG)
        rows[match.AwayTeam]["awayWon"] += int(match.FTR == "A")

    current = _rank_league_phase([dict(r) for r in rows.values()])
    current_position = {row["team"]: row["position"] for row in current}

    remaining = planned[~planned["MatchId"].isin(set(played["MatchId"].astype(str)))]

    projected = {
        row["team"]: {
            key: float(row[key]) for key in ("played", "won", "drawn", "lost", "points")
        }
        for row in current
    }

    if not remaining.empty:
        models, elos, team_history = trained
        abroad = _plays_abroad(cup_matches)
        local = remaining["KickoffUTC"].dt.tz_convert("Europe/London")
        frame = pd.DataFrame({
            "Div": div,
            "Date": local.dt.strftime("%d/%m/%Y").to_numpy(),
            "Time": local.dt.strftime("%H:%M").to_numpy(),
            "HomeTeam": remaining["HomeTeam"].to_numpy(),
            "AwayTeam": remaining["AwayTeam"].to_numpy(),
            "HomeLeague": remaining["HomeTeam"].map(league_of).to_numpy(),
            "AwayLeague": remaining["AwayTeam"].map(league_of).to_numpy(),
            "Neutral": remaining["HomeTeam"].isin(abroad).astype(int).to_numpy(),
            "Stage": "LEAGUE_PHASE",
        })
        scored = predict_fixtures(frame, models, elos, team_history)

        for fixture in scored.itertuples():
            p_home, p_draw, p_away = (
                fixture.HomeProb / 100, fixture.DrawProb / 100, fixture.AwayProb / 100
            )
            home, away = projected[fixture.HomeTeam], projected[fixture.AwayTeam]
            home["played"] += 1
            away["played"] += 1
            home["points"] += 3 * p_home + p_draw
            away["points"] += 3 * p_away + p_draw
            home["won"] += p_home
            away["won"] += p_away
            home["drawn"] += p_draw
            away["drawn"] += p_draw
            home["lost"] += p_away
            away["lost"] += p_home

    # Exact expected points, ties on today's order
    ranked = sorted(projected, key=lambda team: (-projected[team]["points"], current_position[team]))
    projected_rows = [
        {
            "team": team,
            "league": league_of.get(team),
            **{key: round(value) for key, value in projected[team].items()},
            "position": position,
            "currentPosition": current_position[team],
            "movement": current_position[team] - position,
        }
        for position, team in enumerate(ranked, start=1)
    ]

    for row in current:
        row["league"] = league_of.get(row["team"])

    rounds = pd.to_numeric(planned["Round"], errors="coerce").dropna()
    matchdays = int(rounds.max()) if len(rounds) else int(
        played["Round"].str[2:].astype(int).max()
    )

    return {
        "season": season,
        "matchdays": matchdays,
        "playedFixtures": int(len(played)),
        "remainingFixtures": int(len(remaining)),
        "zones": LEAGUE_PHASE_ZONES,
        "current": current,
        "projected": projected_rows,
    }


def _score(home, away):
    return None if pd.isna(home) or pd.isna(away) else [int(home), int(away)]


def _bracket_order(rounds):
    """
    Order each round's ties so tie i of a round is fed by ties 2i and 2i+1
    of the round before (one tie for the play-off -> round of 16), working
    back from the latest round; ties no later tie claims go last, by date.
    """

    stages = [stage for stage in KNOCKOUT_ROUNDS if rounds.get(stage)]

    for later, earlier in zip(reversed(stages), list(reversed(stages))[1:]):

        unplaced = list(rounds[earlier])
        ordered = []

        for tie in rounds[later]:
            for team in tie["teams"]:
                feeder = next((t for t in unplaced if team in t["teams"]), None)
                if feeder is not None:
                    ordered.append(feeder)
                    unplaced.remove(feeder)

        rounds[earlier] = ordered + unplaced

    return rounds


def build_knockouts(div, cup_matches, fixtures, bets, season, progression=None):
    """
    A cup's knockout ties: each tie's legs (90-minute score, extra time,
    the penalty winner), aggregate and winner, plus the model's
    prediction where a bet was made. ``season``'s ties once its draw is
    made; until then the latest season that has some (last season's
    bracket), so the page has something to show - ``current`` says which.
    None when no season has any.

    ``progression`` (a TieProgression) adds each tie's chance of going
    through and the Brier score; without it they're None.
    """

    cup = cup_matches[cup_matches["Div"] == div]
    played = cup[cup["Stage"].isin(KNOCKOUT)]
    planned = (
        fixtures[fixtures["Stage"].isin(KNOCKOUT)] if fixtures is not None else None
    )

    has_current = (played["Season"] == season).any() or (
        planned is not None and not planned.empty
    )
    if has_current:
        shown = season
    elif not played.empty:
        shown = played["Season"].max()
    else:
        return None

    played = played[played["Season"] == shown]

    predictions = {}
    for bet in bets.itertuples():
        if pd.notna(bet.MatchId):
            predictions[str(bet.MatchId).split(".")[0]] = {
                "pick": bet.PredictedResult,
                "homeProb": _num(bet.HomeProb),
                "drawProb": _num(bet.DrawProb),
                "awayProb": _num(bet.AwayProb),
            }

    legs = [
        {
            "stage": match.Stage,
            "matchId": str(match.MatchId),
            "date": match.MatchDateTime.strftime("%Y-%m-%d"),
            "home": match.HomeTeam,
            "away": match.AwayTeam,
            "score": _score(match.FTHG, match.FTAG),
            "extraTime": _score(match.AETHG, match.AETAG),
            "penaltyWinner": _str(match.PenWinner),
            "tieWinner": _str(match.TieWinner),
        }
        for match in played.itertuples()
    ]

    if shown == season and planned is not None:
        seen = {leg["matchId"] for leg in legs}
        local = planned["KickoffUTC"].dt.tz_convert("Europe/London")
        for match, kickoff in zip(planned.itertuples(), local):
            if match.MatchId not in seen:
                legs.append({
                    "stage": match.Stage, "matchId": match.MatchId,
                    "date": kickoff.strftime("%Y-%m-%d"),
                    "home": match.HomeTeam, "away": match.AwayTeam,
                    "score": None, "extraTime": None,
                    "penaltyWinner": None, "tieWinner": None,
                })

    ties = {}
    for leg in sorted(legs, key=lambda l: (l["date"], l["matchId"])):
        key = (leg["stage"], frozenset((leg["home"], leg["away"])))
        ties.setdefault(key, []).append(leg)

    rounds = {}
    for (stage, _), tie_legs in ties.items():

        first = tie_legs[0]
        teams = [first["home"], first["away"]]
        done = [leg for leg in tie_legs if leg["score"] is not None]

        aggregate = None
        if done:
            aggregate = [0, 0]
            for leg in done:
                goals = leg["extraTime"] or leg["score"]
                side = 0 if leg["home"] == teams[0] else 1
                aggregate[side] += goals[0]
                aggregate[1 - side] += goals[1]

        winner = next((leg["tieWinner"] for leg in reversed(done) if leg["tieWinner"]), None)
        decider = done[-1] if done and winner else None

        rounds.setdefault(stage, []).append({
            "teams": teams,
            "progression": progression.tie(stage, tie_legs) if progression else None,
            "legs": [
                {
                    "leg": (number if stage in TWO_LEGGED else None),
                    "date": leg["date"],
                    "home": leg["home"],
                    "away": leg["away"],
                    "score": leg["score"],
                    "extraTime": leg["extraTime"],
                    "penaltyWinner": leg["penaltyWinner"],
                    "prediction": predictions.get(leg["matchId"]),
                }
                for number, leg in enumerate(tie_legs, start=1)
            ],
            "aggregate": aggregate,
            "winner": winner,
            "decidedBy": (
                None if decider is None
                else "penalties" if decider["penaltyWinner"]
                else "extra time" if decider["extraTime"]
                else "aggregate" if stage in TWO_LEGGED
                else "90 minutes"
            ),
        })

    rounds = _bracket_order(rounds)

    return {
        "season": shown,
        "current": bool(shown == season),
        "progressionScore": progression.score() if progression else None,
        "rounds": [
            {"stage": stage, "ties": rounds[stage]}
            for stage in KNOCKOUT_ROUNDS if stage in rounds
        ],
    }


def build_cup(div, cup_matches, bets, season, trained, domestic, rows=None):
    """cups.json's entry for one cup. ``rows``: build_history's feature
    rows behind ``trained``, for the ties' progression probabilities."""

    fixtures = cup_fixture_list(div, season)
    progression = (
        TieProgression(div, rows, trained, cup_matches) if rows is not None else None
    )

    return {
        "name": competitions.get(div)["name"],
        "season": season,
        "leaguePhase": build_league_phase(div, cup_matches, fixtures, season, trained, domestic),
        "knockouts": build_knockouts(div, cup_matches, fixtures, bets, season, progression),
    }


class TieProgression:
    """
    Each knockout tie's chance of going through (plan §4B.9, display
    only; tie_progression.py has the method), for build_knockouts:

    - ``before``: P(teams[0] goes through) before the first leg. Once the
      first leg is played it's out of sample: scored by the European model
      trained on the seasons before the tie's, on the first leg's
      pre-match features (the second leg = the first, sides swapped).
      Until then both legs are scored by the live model.
    - ``afterFirstLeg``: given the first leg's score, with the second leg
      scored out of sample if played, else by the live model. Two-legged
      ties only.

    ``score()``: the Brier score of ``before`` (and ``afterFirstLeg``)
    over every completed tie with a season before it on record, and the
    bootstrap 95% CI of ``before``'s.
    """

    def __init__(self, div, rows, trained, cup_matches):
        self.div = div
        self.rows = rows
        self.trained = trained
        self.cup_matches = cup_matches
        self._models = {}
        cup = rows[rows["Div"] == div]
        self.by_id = cup.set_index(cup["MatchId"].astype(str))

    def _model(self, season):
        if season not in self._models:
            self._models[season] = season_models(self.rows, [season]).get(season)
        return self._models[season]

    def _live(self, stage, legs):
        """The live model's H/D/A for unplayed ``legs`` (build_knockouts' leg dicts)."""

        models, elos, team_history = self.trained

        cup = self.cup_matches[self.cup_matches["Div"] == self.div]
        latest = cup[cup["Season"] == cup["Season"].max()]
        league_of = {}
        for side in ("Home", "Away"):
            league_of.update(zip(latest[f"{side}Team"], latest[f"{side}League"]))
        abroad = _plays_abroad(self.cup_matches)

        frame = pd.DataFrame({
            "Div": self.div,
            "Date": [pd.Timestamp(leg["date"]).strftime("%d/%m/%Y") for leg in legs],
            "Time": "20:00",
            "HomeTeam": [leg["home"] for leg in legs],
            "AwayTeam": [leg["away"] for leg in legs],
            "HomeLeague": [league_of.get(leg["home"]) for leg in legs],
            "AwayLeague": [league_of.get(leg["away"]) for leg in legs],
            "Neutral": [int(stage == "FINAL" or leg["home"] in abroad) for leg in legs],
            "Stage": stage,
        })
        scored = predict_fixtures(frame, models, elos, team_history)

        return (scored[PROB_COLS].to_numpy() / 100).tolist()

    def tie(self, stage, legs):
        """``{before, afterFirstLeg}`` for one tie (build_knockouts' legs, kick-off order)."""

        two_legged = stage in TWO_LEGGED
        if len(legs) != (2 if two_legged else 1):
            return None
        if any(pd.isna(leg["home"]) or pd.isna(leg["away"]) for leg in legs):
            return None

        first_played = legs[0]["score"] is not None and legs[0]["matchId"] in self.by_id.index

        first = model = None
        if first_played:
            first_row = self.by_id.loc[[legs[0]["matchId"]]]
            model = self._model(first_row["Season"].iloc[0])
            if model is None:
                return None  # no earlier season to train on

            first = leg_probabilities(model, first_row)[0]
            if two_legged:
                swapped = leg_probabilities(model, first_row, swap=True)[0]
                before = advance_probability([first, swapped])
            else:
                before = advance_probability([first])
        else:
            before = advance_probability(self._live(stage, legs))

        after = None
        if two_legged and first_played:
            second_id = legs[1]["matchId"]
            if legs[1]["score"] is not None and second_id in self.by_id.index:
                second = leg_probabilities(model, self.by_id.loc[[second_id]])[0]
            else:
                second = self._live(stage, legs[1:])[0]
            after = advance_probability([first, second], first_leg_score=legs[0]["score"])

        return {
            "before": round(before, 3),
            "afterFirstLeg": None if after is None else round(after, 3),
        }

    def score(self):
        ties = backtest_ties(self.rows, self.div)
        if ties.empty:
            return None

        after = ties.dropna(subset=["AfterFirstLeg"])
        _, low, high = bootstrap_against_coin(ties["Before"], ties["HomeWent"])

        return {
            "ties": int(len(ties)),
            "from": ties["Season"].min(),
            "to": ties["Season"].max(),
            "brier": round(brier(ties["Before"], ties["HomeWent"]), 3),
            "brierCi": [round(0.25 + low, 3), round(0.25 + high, 3)],
            "tiesAfterFirstLeg": int(len(after)),
            "brierAfterFirstLeg": (
                round(brier(after["AfterFirstLeg"], after["HomeWent"]), 3) if len(after) else None
            ),
        }


# ============================================================
# HELPERS
# ============================================================

def _bet_summary(row):
    return {
        "div": row["Div"],
        "gameweek": int(row["Gameweek"]),
        "date": row["Date"],
        "match": f'{row["HomeTeam"]} v {row["AwayTeam"]}',
        "pick": row["PredictedResult"],
        "result": row["ActualResult"],
        "pickProb": round(float(row["PickProb"]), 1),
        "profit": _num(row["Profit"]),
    }


def _num(value):
    return None if pd.isna(value) else round(float(value), 2)


def _str(value):
    return None if pd.isna(value) else str(value)


def _write(name, payload, compact=False):

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if compact:  # long series: one line keeps the file small
            json.dump(payload, f, separators=(",", ":"))
        else:
            json.dump(payload, f, indent=2)
        f.write("\n")

    print(f"Wrote {path.relative_to(ROOT)}")


# ============================================================
# MAIN
# ============================================================

def build_leagues():
    """The competitions the pipeline runs, and which the home page picks.
    ``slug`` is the competition's path on the site (/e0/, /sp1/, ...)."""

    return {
        "default": DEFAULT_DIV,
        "competitions": [
            {
                "div": div,
                "slug": div.lower(),
                "name": competitions.get(div)["name"],
                "country": competitions.get(div)["country"],
                "kind": competitions.get(div)["kind"],
                "promotedElo": competitions.get(div)["promoted_elo"],
            }
            for div in exported()
        ],
    }


def exported():
    """The competitions the site shows: every enabled one that's predicted
    (the Europa / Conference League rows only feed the Elo)."""

    return [
        div for div in competitions.enabled()
        if competitions.get(div)["model"] is not None
    ]


def build_shared_ratings(history, european, days=HISTORY_DAYS):
    """
    The shared-scale side of the ratings (elo.shared_scale): a
    {(league, club): rating} lookup, rows for clubs from outside the
    modelled leagues that played in Europe in the last ``days``, and the
    elo_history.json payload. Empty without European results.
    """

    if european is None or european.empty:
        return {}, [], {"from": None, "series": [], "offsets": []}

    start = history["MatchDateTime"].max().normalize() - pd.Timedelta(days=days)
    scale = shared_scale(history, european, history_from=start)

    ratings = scale["ratings"]
    lookup = {
        (league, club): round(rating)
        for league, club, rating in zip(ratings["League"], ratings["Club"], ratings["Rating"])
    }

    recent = scale["history"]
    active_outsiders = set(recent.loc[recent["League"].str.startswith("X:"), "Club"])
    outsider_rows = [
        {"div": row.League, "team": row.Club, "elo": None, "rating": round(row.Rating),
         "country": row.Country, "modelled": False}
        for row in ratings.itertuples()
        if not row.Modelled and row.Club in active_outsiders
    ]

    # One point per club per day (its rating after that day's match)
    points = (
        recent.assign(Day=recent["Date"].dt.strftime("%Y-%m-%d"))
        .drop_duplicates(["Club", "League", "Day"], keep="last")
    )
    series = [
        {"team": club, "div": league,
         "points": [[day, round(rating)] for day, rating in zip(group["Day"], group["Rating"])]}
        for (club, league), group in points.groupby(["Club", "League"], sort=True)
    ]

    offsets = scale["offsets"].drop_duplicates(["Date", "Div"], keep="last")
    payload = {
        "from": start.strftime("%Y-%m-%d"),
        "series": series,
        "offsets": [
            {"date": day.strftime("%Y-%m-%d"), "season": season, "div": div, "offset": round(offset, 1)}
            for day, season, div, offset in offsets.itertuples(index=False)
        ],
    }

    return lookup, outsider_rows, payload


def build_run_status(status=None):
    """
    Each competition's outcome in the pipeline run, as run_status.py
    records it: ``status`` (RunStatus.competitions) during a run, else the
    last run's file. Empty when there's neither - the site then shows no
    stale badges.
    """

    if status is None:
        try:
            status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            status = {}

    return {
        div: {
            "results": s.get("results"),
            "xg": s.get("xg"),
            "predicted": int(s.get("predicted") or 0),
            "error": s.get("error"),
        }
        for div, s in status.items()
    }


def export_web(status=None):
    """``status``: this run's RunStatus.competitions, so the site's stale
    badges describe this run (run_week writes the file only at the end)."""

    everything = load_matches(cups=True)
    if "Div" not in everything.columns:
        everything.insert(0, "Div", DEFAULT_DIV)

    cup = everything["Div"].map(is_cup)
    history = everything[~cup].reset_index(drop=True)
    cup_matches = everything[cup].reset_index(drop=True)

    # Cup rows have no gameweek, which made the column float (read_matches)
    if cup.any() and history["Gameweek"].notna().all():
        history["Gameweek"] = history["Gameweek"].astype(int)

    european = results_for_elo(history)

    # Fitted once on every competition (the cup rows train the CL's
    # European model, as in predict_next_matches.load_model), then scored
    # per competition
    ratings = build_elo_feature(history.copy(), european=european)
    # Kept: the cup ties' progression scores played legs on these rows' features
    rows, elos, team_history = build_history(
        everything if cup.any() else history, european=european
    )
    trained = (train_models(rows), elos, team_history)
    shared, outsiders, elo_history = build_shared_ratings(history, european)

    # A cup's clubs come from several leagues, so its fixtures show the
    # shared-scale rating
    shared_by_club = {club: rating for (_, club), rating in shared.items()}

    fixtures, bet_records, elo_rows = [], [], []
    by_competition, tables, cups, all_bets = {}, {}, {}, []

    for div in exported():

        name = competitions.get(div)["name"]
        bets = load_bets(div)
        all_bets.append(bets)

        if is_cup(div):
            fixtures += build_predictions(bets, shared_by_club, EUROPE_HOME_ADVANTAGE)
            bet_records += build_bets(bets)
            by_competition[div] = {"name": name, **build_stats(bets)}
            cups[div] = build_cup(
                div, cup_matches, bets, competitions.CURRENT_SEASON, trained, history, rows
            )
            continue

        matches = history[history["Div"] == div].reset_index(drop=True)
        elos = current_elos(history, div, ratings)

        fixtures += build_predictions(bets, elos)
        bet_records += build_bets(bets)
        by_competition[div] = {"name": name, **build_stats(bets)}

        elo_rows += sorted(
            (
                {"div": div, "team": team, "elo": rating,
                 "rating": shared.get((div, team), rating),
                 "country": competitions.get(div)["country"], "modelled": True}
                for team, rating in elos.items()
            ),
            key=lambda row: row["elo"],
            reverse=True,
        )

        if not matches.empty:
            tables[div] = {
                "name": name,
                **build_table(matches, bets, history, trained),
            }

    every_bet = pd.concat(all_bets, ignore_index=True)
    overall = build_stats(
        every_bet.sort_values("Kickoff", kind="stable").reset_index(drop=True)
    )
    # Gameweek numbers differ by league, so these only mean anything per
    # competition
    overall.pop("byGameweek")

    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    _write("predictions.json", {
        "generated": generated,
        "fixtures": fixtures,
    })

    _write("bets.json", {
        "generated": generated,
        "bets": bet_records,
    })

    _write("stats.json", {
        "generated": generated,
        "overall": overall,
        "byCompetition": by_competition,
    })

    _write("elo.json", {
        "generated": generated,
        "teams": elo_rows + outsiders,
        # The latest O_L per league (the shared-scale baseline is 1500 + O_L)
        "offsets": {
            row["div"]: row["offset"]
            for row in elo_history["offsets"]
        },
    })

    _write("elo_history.json", {
        "generated": generated,
        **elo_history,
    }, compact=True)

    _write("table.json", {
        "generated": generated,
        "byCompetition": tables,
    })

    _write("leagues.json", {
        "generated": generated,
        **build_leagues(),
    })

    _write("run_status.json", {
        "generated": generated,
        "competitions": build_run_status(status),
    })

    _write("cups.json", {
        "generated": generated,
        "byCompetition": cups,
    })


if __name__ == "__main__":
    export_web()
