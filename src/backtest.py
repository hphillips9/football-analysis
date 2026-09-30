"""
Score the model season by season, training only on earlier seasons.

    python src/backtest.py

For each completed season after the first, a fresh model is trained on
every season before it and used to predict that season's matches. Writes
web/src/data/backtest.json (accuracy, log loss, always-home baseline) and
the profit a 1-unit flat bet on every pick would have made, gameweek by
gameweek.

Features (Elo gap, last-5 xG difference, season goals-per-game
difference) are built chronologically over the whole dataset, so each
row's features only use matches before it - no leakage.

Not part of run_week: re-run it when a season finishes.
"""

import json
import warnings
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

warnings.simplefilter("ignore", pd.errors.PerformanceWarning)

from predict_next_matches import (
    build_elo_feature,
    build_goals_per_game_feature,
    build_xgd_last5_feature,
    train_model,
    FEATURES,
)

ROOT = Path(__file__).resolve().parents[1]
MATCHES_PATH = ROOT / "data" / "processed" / "all_matches.csv"
OUT_PATH = ROOT / "web" / "src" / "data" / "backtest.json"

MIN_SEASON_MATCHES = 200  # skip a season still in progress

STAKE = 1
# Sky Bet prices only exist from 2026/27, so past seasons settle at the
# market average - the same fallback fetch_results uses for live bets
ODDS_COLUMN = {"H": "SKBH", "D": "SKBD", "A": "SKBA"}
FALLBACK_ODDS_COLUMN = {"H": "AvgH", "D": "AvgD", "A": "AvgA"}


def season_label(code):
    start, end = code.split("-")
    return f"20{start}/{end}"


def bet_profit(match, pick):
    """1-unit flat stake on ``pick``, settled like fetch_results.settle_profit."""

    if pick != match["FTR"]:
        return float(-STAKE)

    odds = match.get(ODDS_COLUMN[pick])
    if pd.isna(odds):
        odds = match[FALLBACK_ODDS_COLUMN[pick]]

    return round(STAKE * (odds - 1), 2)


def profit_by_gameweek(test, pred):
    """Per-gameweek bets, hits and profit, with a running total."""

    bets = test.assign(Pick=pred)
    bets["Profit"] = [bet_profit(m, m["Pick"]) for _, m in bets.iterrows()]
    bets["Hit"] = bets["Pick"] == bets["FTR"]

    out = []
    running = 0.0
    for gameweek, group in bets.groupby("Gameweek"):
        profit = group["Profit"].sum()
        running += profit
        out.append({
            "gameweek": int(gameweek),
            "bets": int(len(group)),
            "hits": int(group["Hit"].sum()),
            "profit": round(profit, 2),
            "cumulativeProfit": round(running, 2),
        })

    return bets["Profit"].sum(), out


def run_backtest():

    matches = pd.read_csv(MATCHES_PATH)
    matches["MatchDateTime"] = pd.to_datetime(matches["MatchDateTime"])
    # Tie-break same kick-offs so row order (and so the calibration CV
    # folds) doesn't shift when new matches are added
    matches = matches.sort_values(
        ["MatchDateTime", "HomeTeam", "AwayTeam"]
    ).reset_index(drop=True)

    build_elo_feature(matches)
    build_goals_per_game_feature(matches)
    build_xgd_last5_feature(matches)

    seasons = sorted(matches["Season"].unique())

    rows = []
    pooled_true = []
    pooled_pred = []
    pooled_proba = []
    pooled_labels = None
    pooled_profit = 0.0

    for index, season in enumerate(seasons):

        if index == 0:
            continue

        prior = seasons[:index]
        train = matches[matches["Season"].isin(prior)]
        test = matches[matches["Season"] == season]

        if len(test) < MIN_SEASON_MATCHES:
            continue

        model = train_model(train)
        labels = list(model.classes_)

        proba = model.predict_proba(test[FEATURES])
        pred = [labels[i] for i in proba.argmax(axis=1)]
        actual = test["FTR"].to_numpy()

        accuracy = accuracy_score(actual, pred)
        loss = log_loss(actual, proba, labels=labels)
        baseline = (actual == "H").mean()
        profit, by_gameweek = profit_by_gameweek(test, pred)
        pooled_profit += profit

        rows.append({
            "season": season_label(season),
            "matches": int(len(test)),
            "trainedOn": (
                season_label(prior[0])
                if len(prior) == 1
                else f"{season_label(prior[0])}-{season_label(prior[-1])}"
            ),
            "trainSeasons": len(prior),
            "accuracy": round(accuracy * 100, 1),
            "logLoss": round(loss, 3),
            "baselineAccuracy": round(baseline * 100, 1),
            "edge": round((accuracy - baseline) * 100, 1),
            "profit": round(profit, 2),
            "roi": round(profit / (len(test) * STAKE) * 100, 1),
            "byGameweek": by_gameweek,
        })

        pooled_true.extend(actual.tolist())
        pooled_pred.extend(pred)
        pooled_proba.extend(proba.tolist())
        pooled_labels = labels

    overall = None
    if rows:
        overall = {
            "matches": len(pooled_true),
            "accuracy": round(accuracy_score(pooled_true, pooled_pred) * 100, 1),
            "logLoss": round(
                log_loss(pooled_true, pooled_proba, labels=pooled_labels), 3
            ),
            "baselineAccuracy": round(
                (pd.Series(pooled_true) == "H").mean() * 100, 1
            ),
        }
        overall["edge"] = round(
            overall["accuracy"] - overall["baselineAccuracy"], 1
        )
        overall["profit"] = round(pooled_profit, 2)
        overall["roi"] = round(
            pooled_profit / (len(pooled_true) * STAKE) * 100, 1
        )

    payload = {
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "seasons": rows,
        "overall": overall,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")
    for row in rows:
        print(
            f"  {row['season']}: {row['accuracy']}% "
            f"(baseline {row['baselineAccuracy']}%, "
            f"log loss {row['logLoss']}, "
            f"profit {row['profit']:+.2f}u / ROI {row['roi']:+.1f}%)"
        )
    if overall:
        print(
            f"  overall: {overall['accuracy']}% over "
            f"{overall['matches']} matches, "
            f"profit {overall['profit']:+.2f}u / ROI {overall['roi']:+.1f}%"
        )


if __name__ == "__main__":
    run_backtest()
