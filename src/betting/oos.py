"""
Out-of-sample probabilities for betting research.

    python src/betting/oos.py [--demargin shin] [--week-starts 1 4]

Runs the production walk-forward once (backtest.prepare_matches +
model.walk_forward_models: pooled LR with league indicators, E0 on its
own model) for every completed test season plus the season in progress
(trained on every season before it), and writes
data/processed/oos_predictions.csv: one row per domestic league match
with the model's pH/pD/pA, the result, the betting week, de-margined
market probabilities and every odds column the simulator reads.

The Champions League / Europa League / Conference League use their own
model and are left out.

Not part of run_week.
"""

import argparse
import sys
import warnings
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

warnings.simplefilter("ignore", pd.errors.PerformanceWarning)

from backtest import MATCHES_PATH, prepare_matches
from betting.market import market_probabilities, odds_columns
from betting.simulate import OOS_PATH, TUESDAY, bet_week
from model import walk_forward_models

COLUMNS = [
    "Season", "Div", "MatchDateTime", "BetWeek", "MatchKey", "HomeTeam", "AwayTeam",
    "FTR", "FTHG", "FTAG", "pH", "pD", "pA", "TrainedOn",
]


def match_key(frame):
    return frame["Season"] + "|" + frame["Div"] + "|" + frame["HomeTeam"] + "|" + frame["AwayTeam"]


def build_oos(matches_path=MATCHES_PATH, demargin="proportional", week_starts=(TUESDAY,)):
    """The oos_predictions frame (see the module docstring)."""

    matches, seasons, test_seasons = prepare_matches(matches_path)

    # The season in progress too: trained on every season before it
    oos_seasons = list(test_seasons) + [
        s for s in seasons[1:] if s not in test_seasons and s > max(test_seasons, default="")
    ]

    proba = walk_forward_models(matches, oos_seasons)
    rows = matches.loc[proba.index]

    out = rows[["Season", "Div", "MatchDateTime", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"]].copy()
    out["BetWeek"] = bet_week(out["MatchDateTime"], week_starts)
    out["MatchKey"] = match_key(out)
    for cls in ["H", "D", "A"]:
        out[f"p{cls}"] = proba[cls]
    out["TrainedOn"] = [f"{seasons[0]}..{seasons[seasons.index(s) - 1]}" for s in out["Season"]]

    if not out["MatchKey"].is_unique:
        raise ValueError("MatchKey (Season|Div|HomeTeam|AwayTeam) isn't unique")

    # Odds as numbers (football-data has the odd "#" placeholder)
    odds = [c for c in odds_columns() if c in rows.columns]
    rows = rows.assign(**{c: pd.to_numeric(rows[c], errors="coerce") for c in odds})
    out = pd.concat([out[COLUMNS], market_probabilities(rows, demargin), rows[odds]], axis=1)

    return out.reset_index(drop=True)


def write_oos(oos, path=OOS_PATH):
    """Write ``oos`` as CSV, floats at full precision (so they read back equal)."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    oos.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def main(argv=None):

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--demargin", choices=["proportional", "shin"], default="proportional")
    parser.add_argument(
        "--week-starts", type=int, nargs="+", default=[TUESDAY],
        help="weekday(s) a betting window starts on (0=Mon); default 1 (Tue-Mon)",
    )
    parser.add_argument("--out", type=Path, default=OOS_PATH)
    args = parser.parse_args(argv)

    oos = build_oos(demargin=args.demargin, week_starts=args.week_starts)

    write_oos(oos, args.out)

    print(f"Wrote {args.out} ({len(oos)} rows)")
    print(oos.groupby(["Season", "Div"]).size().unstack(fill_value=0).to_string())
    print("Market probabilities from:", oos["qSource"].value_counts(dropna=False).to_dict())

    return oos


if __name__ == "__main__":
    main()
