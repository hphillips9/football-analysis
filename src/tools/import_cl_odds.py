"""
Price Champions League bets that have no captured odds with closing odds
copied by hand from BetExplorer's results page (the average across
bookmakers), then settle them at those prices.

    python src/tools/import_cl_odds.py data/raw/CL/closing_odds_26-27.txt
    python src/tools/import_cl_odds.py <file> --dry-run

The file is BetExplorer's results table pasted as text: a "<N>. Round"
header line per matchday (-> Round "MD<N>"), then one tab-separated line
per match: "Home - Away", score, odds 1, X, 2, date.

Only bets with no odds are touched: odds captured before kickoff by
odds_api.py (MD5 onwards) are never overwritten. Imported prices get
OddsSource = "BEAvg" (closing average, BetExplorer), so they can be told
apart from the pre-kickoff captures ("SKB" / "UKMed"). Each pasted score is
checked against the bet's settled result before anything is written.
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bet_schema import ODDS_COLUMNS, add_missing_columns, write_bets
from fetch_results import BETS_PATH, STAKE, _OUTCOMES, settle_profit
from odds_api import MIN_MARGIN, MIN_SIDE_SCORE, name_score

DIV = "CL"
SOURCE = "BEAvg"

# BetExplorer short names that share no words with FotMob's
ALIASES = {"PSG": "Paris Saint-Germain"}

ROUND_LINE = re.compile(r"^\s*(\d+)\.\s*Round")


def parse_paste(text):
    """Rows of Round, Home, Away, FTR, OddsH, OddsD, OddsA from the paste."""

    rows, round_label = [], None

    for line in text.splitlines():

        header = ROUND_LINE.match(line)
        if header:
            round_label = f"MD{header.group(1)}"
            continue

        cells = [c.strip() for c in line.split("\t") if c.strip()]
        if len(cells) < 5 or " - " not in cells[0] or round_label is None:
            continue

        home, away = (ALIASES.get(n.strip(), n.strip()) for n in cells[0].split(" - ", 1))
        home_goals, away_goals = (int(g) for g in cells[1].split(":"))
        ftr = "H" if home_goals > away_goals else "A" if away_goals > home_goals else "D"

        rows.append({
            "Round": round_label, "Home": home, "Away": away, "FTR": ftr,
            "OddsH": float(cells[2]), "OddsD": float(cells[3]), "OddsA": float(cells[4]),
        })

    return pd.DataFrame(rows)


def match_rows(bets, odds):
    """{bet index: odds row} within each round, by club names."""

    matched = {}

    for _, row in odds.iterrows():

        candidates = bets[(bets["Div"] == DIV) & (bets["Round"] == row["Round"])]
        scored = sorted(
            (
                (name_score(bet["HomeTeam"], row["Home"]) + name_score(bet["AwayTeam"], row["Away"]),
                 min(name_score(bet["HomeTeam"], row["Home"]), name_score(bet["AwayTeam"], row["Away"])),
                 i)
                for i, bet in candidates.iterrows()
            ),
            reverse=True,
        )

        if not scored:
            print(f"  No {row['Round']} bets for {row['Home']} v {row['Away']}")
            continue

        total, weakest, i = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0

        if weakest < MIN_SIDE_SCORE or total - runner_up < MIN_MARGIN:
            print(f"  No confident match for {row['Round']} {row['Home']} v {row['Away']}")
            continue

        matched[i] = row

    return matched


def import_odds(path, bets_path=BETS_PATH, dry_run=False):

    odds = parse_paste(Path(path).read_text(encoding="utf-8"))
    bets = add_missing_columns(pd.read_csv(bets_path))
    bets["OddsSource"] = bets["OddsSource"].astype(object)

    matched = match_rows(bets, odds)

    priced, kept, mismatched = [], 0, []

    for i, row in matched.items():

        if bets.loc[i, ODDS_COLUMNS].notna().any():
            kept += 1
            continue

        actual = bets.at[i, "ActualResult"]
        if pd.notna(actual) and actual != row["FTR"]:
            mismatched.append(f"{bets.at[i, 'HomeTeam']} v {bets.at[i, 'AwayTeam']}: "
                              f"bet {actual}, paste {row['FTR']}")
            continue

        bets.loc[i, ODDS_COLUMNS] = [row["OddsH"], row["OddsD"], row["OddsA"]]
        bets.at[i, "OddsSource"] = SOURCE

        if pd.notna(actual):
            predicted = bets.at[i, "PredictedResult"]
            bets.at[i, "Bet"] = STAKE
            bets.at[i, "Profit"] = settle_profit(predicted, actual, row[f"Odds{predicted}"])

        priced.append(i)

    print(f"Parsed {len(odds)} matches, matched {len(matched)} to bets.")
    print(f"  {len(priced)} priced from the paste, {kept} already had odds (kept).")
    for line in mismatched:
        print(f"  RESULT MISMATCH, skipped: {line}")

    if priced:
        summary = bets.loc[priced]
        settled = summary[summary["Profit"].notna()]
        print(f"  Settled at these odds: {len(settled)} bets, "
              f"{int((settled['Profit'] > 0).sum())} won, {settled['Profit'].sum():+.2f} units")
        print(summary.groupby("Round")["Profit"].agg(["count", "sum"]).round(2).to_string())

    if dry_run:
        print("Dry run: Bets.csv not changed.")
    elif priced:
        write_bets(bets, bets_path)
        print(f"Wrote {bets_path}")

    return bets


def main():

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", help="BetExplorer results table pasted as text")
    parser.add_argument("--dry-run", action="store_true", help="print, don't write Bets.csv")
    args = parser.parse_args()

    import_odds(args.path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
