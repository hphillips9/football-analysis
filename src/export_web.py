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

Every competition in competitions.ENABLED is exported, and each
prediction, bet and rating carries its ``div``. The model behind the
projected tables is trained on every competition, as the live
predictions are.

Runs as part of run_week.py so CI keeps the site's data current.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

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
from elo import shared_scale
from european import results_for_elo
from load_data import read_matches

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


# ============================================================
# LOADERS
# ============================================================

def load_matches():

    matches = read_matches(MATCHES_PATH)

    return matches.sort_values(
        ["MatchDateTime", "HomeTeam", "AwayTeam"]
    ).reset_index(drop=True)


def load_bets(div=None):
    """Bets.csv, of competition ``div`` only when given, in kickoff order."""

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

def build_predictions(bets, elos):
    """One competition's fixtures for the gameweek to feature: the earliest
    one with unsettled bets, or failing that the most recent on record."""

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
            "eloGap": round(home_elo + HOME_ADVANTAGE - away_elo),
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
            # League pages only; the CL gets its own page in P6-01
            for div in competitions.leagues()
        ],
    }


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

    history = load_matches()
    if "Div" not in history.columns:
        history.insert(0, "Div", DEFAULT_DIV)

    european = results_for_elo(history)

    # Fitted once on every competition, then scored per league
    ratings = build_elo_feature(history.copy(), european=european)
    trained = train_history(history, european)
    shared, outsiders, elo_history = build_shared_ratings(history, european)

    fixtures, bet_records, elo_rows = [], [], []
    by_competition, tables, all_bets = {}, {}, []

    # CL predictions are recorded in Bets.csv but not shown until P6-01
    for div in competitions.leagues():

        name = competitions.get(div)["name"]
        matches = history[history["Div"] == div].reset_index(drop=True)
        bets = load_bets(div)
        all_bets.append(bets)

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


if __name__ == "__main__":
    export_web()
