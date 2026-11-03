"""
Score the model season by season, training only on earlier seasons.

    python src/backtest.py

For each completed season after the first, a fresh model is trained on
every season before it and used to predict that season's matches. Writes
web/src/data/backtest.json (accuracy, log loss, always-home baseline) and
the profit a 1-unit flat bet on every pick would have made, gameweek by
gameweek.

Each competition is scored with the model the pipeline predicts it
with (model.train_models): its own, or the pooled one with a
League_<Div> column per non-baseline league. The results are reported
for all competitions together ("pooled") and per competition; the
top-level ``seasons``/``overall`` are a copy of the Premier League's,
kept for the site's about page until it moves to ``competitions``.

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

import competitions
from predict_next_matches import (
    build_elo_feature,
    build_goals_per_game_feature,
    build_xgd_last5_feature,
    FEATURES,
)
from model import BASELINE_LEAGUE, LEAGUE_COLUMNS, OWN_MODEL, league_columns, walk_forward_models

ROOT = Path(__file__).resolve().parents[1]
MATCHES_PATH = ROOT / "data" / "processed" / "all_matches.csv"
OUT_PATH = ROOT / "web" / "src" / "data" / "backtest.json"

MIN_SEASON_MATCHES = 200  # per competition: skip a season still in progress

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


def _trained_on(prior):

    if len(prior) == 1:
        return season_label(prior[0])

    return f"{season_label(prior[0])}-{season_label(prior[-1])}"


def score(matches, all_proba, seasons, test_seasons):
    """
    Per-season rows and the overall summary for the test matches in
    ``matches`` (all of them, or one competition's).
    """

    labels = list(all_proba.columns)

    rows = []
    pooled_true = []
    pooled_pred = []
    pooled_proba = []
    pooled_profit = 0.0

    for season in test_seasons:

        prior = seasons[:seasons.index(season)]
        test = matches[matches["Season"] == season]

        if test.empty:
            continue

        proba = all_proba.loc[test.index].to_numpy()
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
            "trainedOn": _trained_on(prior),
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

    overall = None
    if rows:
        overall = {
            "matches": len(pooled_true),
            "accuracy": round(accuracy_score(pooled_true, pooled_pred) * 100, 1),
            "logLoss": round(
                log_loss(pooled_true, pooled_proba, labels=labels), 3
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

    return rows, overall


def run_backtest(matches_path=MATCHES_PATH, out_path=OUT_PATH):

    matches = pd.read_csv(matches_path)
    matches["MatchDateTime"] = pd.to_datetime(matches["MatchDateTime"])
    # Tie-break same kick-offs so row order (and so the calibration CV
    # folds) doesn't shift when new matches are added
    matches = matches.sort_values(
        ["MatchDateTime", "HomeTeam", "AwayTeam"]
    ).reset_index(drop=True)

    if "Div" not in matches.columns:
        matches.insert(0, "Div", BASELINE_LEAGUE)

    build_elo_feature(matches)
    build_goals_per_game_feature(matches)
    build_xgd_last5_feature(matches)

    # A League_<Div> column for every non-baseline league in the data
    matches = league_columns(matches)
    indicators = [c for c in LEAGUE_COLUMNS.values() if c in matches.columns]

    # A season is tested once every competition in it has finished it
    seasons = sorted(matches["Season"].unique())
    smallest = matches.groupby(["Season", "Div"]).size().groupby("Season").min()
    test_seasons = [
        season for season in seasons[1:]
        if smallest[season] >= MIN_SEASON_MATCHES
    ]

    all_proba = walk_forward_models(matches, test_seasons)

    pooled_rows, pooled_overall = score(matches, all_proba, seasons, test_seasons)

    # Registry order (E0 first), then any code it doesn't know
    registry = list(competitions.COMPETITIONS)
    divs = sorted(
        matches["Div"].unique(),
        key=lambda d: registry.index(d) if d in registry else len(registry),
    )

    by_competition = {}
    for div in divs:
        rows, overall = score(matches[matches["Div"] == div], all_proba, seasons, test_seasons)
        by_competition[div] = {
            "name": competitions.COMPETITIONS.get(div, {}).get("name", div),
            "seasons": rows,
            "overall": overall,
        }

    # Deprecated: the Premier League's figures, for about.md (Phase 3)
    legacy = by_competition.get(BASELINE_LEAGUE, {"seasons": [], "overall": None})

    payload = {
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": {
            "features": FEATURES,
            "leagueIndicators": indicators,
            "ownModel": [div for div in OWN_MODEL if div in by_competition],
            "trainFrom": seasons[0],
        },
        "pooled": {"seasons": pooled_rows, "overall": pooled_overall},
        "competitions": by_competition,
        "seasons": legacy["seasons"],
        "overall": legacy["overall"],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    print(f"Wrote {out_path}")
    for div, section in [("pooled", payload["pooled"]), *by_competition.items()]:
        print(f"{div}:")
        for row in section["seasons"]:
            print(
                f"  {row['season']}: {row['accuracy']}% "
                f"(baseline {row['baselineAccuracy']}%, "
                f"log loss {row['logLoss']}, "
                f"profit {row['profit']:+.2f}u / ROI {row['roi']:+.1f}%)"
            )
        overall = section["overall"]
        if overall:
            print(
                f"  overall: {overall['accuracy']}% over "
                f"{overall['matches']} matches, log loss {overall['logLoss']}, "
                f"profit {overall['profit']:+.2f}u / ROI {overall['roi']:+.1f}%"
            )

    return payload


if __name__ == "__main__":
    run_backtest()
