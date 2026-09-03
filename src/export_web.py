"""
Write the tidy JSON files the website reads.

    python src/export_web.py

Reads data/processed/all_matches.csv, data/raw/Bets.csv and produces:

    web/src/data/predictions.json  - the upcoming gameweek's picks
    web/src/data/bets.json         - every bet, with result and profit
    web/src/data/stats.json        - headline numbers, calibration, by-gameweek

Runs as part of run_week.py so CI keeps the site's data current.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from team_names import load_alias_map
from predict_next_matches import build_elo_feature, HOME_ADVANTAGE

ROOT = Path(__file__).resolve().parents[1]

MATCHES_PATH = ROOT / "data" / "processed" / "all_matches.csv"
BETS_PATH = ROOT / "data" / "raw" / "Bets.csv"
OUT_DIR = ROOT / "web" / "src" / "data"

PROB_COLS = ["HomeProb", "DrawProb", "AwayProb"]

# Calibration buckets on the model's probability for its own pick
CALIB_EDGES = [0, 40, 45, 50, 55, 60, 100]


# ============================================================
# LOADERS
# ============================================================

def load_matches():

    matches = pd.read_csv(MATCHES_PATH)
    matches["MatchDateTime"] = pd.to_datetime(matches["MatchDateTime"])

    return matches.sort_values("MatchDateTime").reset_index(drop=True)


def load_bets():

    bets = pd.read_csv(BETS_PATH)

    alias_map = load_alias_map()
    bets["HomeTeam"] = bets["HomeTeam"].replace(alias_map)
    bets["AwayTeam"] = bets["AwayTeam"].replace(alias_map)

    bets["Kickoff"] = pd.to_datetime(
        bets["Date"] + " " + bets["Time"], dayfirst=True
    )
    bets["Won"] = bets["PredictedResult"] == bets["ActualResult"]
    bets["PickProb"] = bets[PROB_COLS].max(axis=1)

    return bets.sort_values("Kickoff").reset_index(drop=True)


def current_elos(matches):

    ratings = build_elo_feature(matches.copy())

    return {team: round(rating) for team, rating in ratings.items()}


# ============================================================
# PREDICTIONS
# ============================================================

def build_predictions(bets, elos):
    """The gameweek to feature: the earliest one with unsettled bets, or
    failing that the most recent gameweek on record."""

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

    return {
        "gameweek": gameweek,
        "fixtures": fixtures,
    }


# ============================================================
# BETS
# ============================================================

def build_bets(bets):

    records = []

    for _, row in bets.iterrows():

        settled = bool(pd.notna(row["ActualResult"]))

        records.append({
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
        })

    return records


# ============================================================
# STATS
# ============================================================

def build_stats(bets):

    settled = bets[
        bets["ActualResult"].notna() & bets["Profit"].notna()
    ].copy()

    if settled.empty:
        return {
            "asOf": None,
            "totalBets": int(len(bets)),
            "settledBets": 0,
            "pendingBets": int(bets["ActualResult"].isna().sum()),
            "calibration": [],
            "byGameweek": [],
            "byPick": [],
            "bankroll": [],
            "bestBets": [],
            "worstBets": [],
        }

    stake = settled["Bet"].fillna(1)
    wins = int(settled["Won"].sum())
    profit = float(settled["Profit"].sum())
    staked = float(stake.sum())

    baseline_hit = float((settled["ActualResult"] == "H").mean())
    hit_rate = wins / len(settled)

    # Cumulative profit, one point per settled bet in kickoff order
    running = 0.0
    bankroll = []
    for _, row in settled.sort_values("Kickoff").iterrows():
        running += float(row["Profit"])
        bankroll.append({
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

    # Per gameweek
    by_gameweek = []
    for gameweek, group in settled.groupby("Gameweek"):
        by_gameweek.append({
            "gameweek": int(gameweek),
            "bets": int(len(group)),
            "hits": int(group["Won"].sum()),
            "profit": round(float(group["Profit"].sum()), 2),
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
        for _, row in settled[settled["Won"]]
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

    return {
        "asOf": settled["Kickoff"].max().date().isoformat(),
        "totalBets": int(len(bets)),
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
# HELPERS
# ============================================================

def _bet_summary(row):
    return {
        "gameweek": int(row["Gameweek"]),
        "date": row["Date"],
        "match": f'{row["HomeTeam"]} v {row["AwayTeam"]}',
        "pick": row["PredictedResult"],
        "result": row["ActualResult"],
        "pickProb": round(float(row["PickProb"]), 1),
        "profit": round(float(row["Profit"]), 2),
    }


def _num(value):
    return None if pd.isna(value) else round(float(value), 2)


def _str(value):
    return None if pd.isna(value) else str(value)


def _write(name, payload):

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    print(f"Wrote {path.relative_to(ROOT)}")


# ============================================================
# MAIN
# ============================================================

def export_web():

    matches = load_matches()
    bets = load_bets()
    elos = current_elos(matches)

    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    _write("predictions.json", {
        "generated": generated,
        **build_predictions(bets, elos),
    })

    _write("bets.json", {
        "generated": generated,
        "bets": build_bets(bets),
    })

    _write("stats.json", {
        "generated": generated,
        **build_stats(bets),
    })

    elo_table = sorted(
        (
            {"team": team, "elo": rating}
            for team, rating in elos.items()
        ),
        key=lambda row: row["elo"],
        reverse=True,
    )
    _write("elo.json", {
        "generated": generated,
        "teams": elo_table,
    })


if __name__ == "__main__":
    export_web()
