"""
One-off: bring data/raw/Bets.csv up to the multi-competition schema
(see src/bet_schema.py).

    python src/tools/migrate_bets.py           # dry run: show the diff
    python src/tools/migrate_bets.py --apply   # back up, then write

    Gameweek,Div,Date,Time,HomeTeam,AwayTeam,PredictedResult,
    HomeProb,DrawProb,AwayProb,ActualResult,Bet,Profit
        ->
    Season,Div,Round,Gameweek,MatchId,Date,Time,HomeTeam,AwayTeam,
    PredictedResult,HomeProb,DrawProb,AwayProb,
    OddsH,OddsD,OddsA,OddsSource,ActualResult,Bet,Profit

New columns: Season from the date, Round = str(Gameweek), MatchId empty.
Settled bets get the odds they were settled at (Sky Bet, else market
average, as complete_bets does), checked by re-deriving the stored
profit from them. Where football-data has since revised the price, the
profit no longer re-derives: the recorded profit is kept and the odds
are left blank (we don't know the price it settled at), with a warning.
A missing or different result stops the migration. Every original
column must come through unchanged.

Writes a backup first (default data/raw/Bets.csv.bak) and refuses to
overwrite an existing one. Safe to re-run: an already migrated file
comes out unchanged.
"""

import argparse
import difflib
import io
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bet_schema import ODDS_COLUMNS, add_missing_columns  # noqa: E402
from backfill_bet_probs import BETS_PATH, format_bets  # noqa: E402
from fetch_results import (  # noqa: E402
    _load_current_results,
    find_result,
    settle_profit,
    settlement_odds,
)
from team_names import load_alias_map  # noqa: E402

BACKUP_PATH = BETS_PATH.with_name("Bets.csv.bak")


def migrate(bets):
    """
    The migrated frame, a list of problems (empty = safe to write) and a
    list of warnings (bets left without odds).
    """

    migrated = add_missing_columns(bets)
    problems = []
    warnings = []

    alias_map = load_alias_map()
    results = _load_current_results(sorted(migrated["Div"].unique()))
    results["_home"] = results["HomeTeam"].replace(alias_map)
    results["_away"] = results["AwayTeam"].replace(alias_map)

    to_price = migrated.index[
        migrated["ActualResult"].notna() & migrated["OddsSource"].isna()
    ]

    for i in to_price:

        bet = migrated.loc[i]
        label = f'{bet["Date"]} {bet["HomeTeam"]} v {bet["AwayTeam"]}'

        match = find_result(bet, results, alias_map)
        if match is None:
            problems.append(f"{label}: no result found")
            continue

        if match["FTR"] != bet["ActualResult"]:
            problems.append(
                f'{label}: result {match["FTR"]} != recorded {bet["ActualResult"]}'
            )
            continue

        priced = settlement_odds(match, bet["PredictedResult"])
        if priced is None:
            problems.append(f"{label}: no odds in the results file")
            continue

        odds, source = priced
        pick_odds = odds["HDA".index(bet["PredictedResult"])]
        profit = settle_profit(bet["PredictedResult"], bet["ActualResult"], pick_odds)

        if profit != bet["Profit"]:
            warnings.append(
                f'{label}: {source} odds {pick_odds} give {profit:+.2f}, recorded '
                f'{bet["Profit"]:+.2f} - price revised since; odds left blank'
            )
            continue

        migrated.loc[i, ODDS_COLUMNS] = odds
        migrated.at[i, "OddsSource"] = source

    return migrated, problems, warnings


def _as_csv(bets):
    """The file's new text, in backfill_bet_probs' format, LF line endings."""

    return format_bets(bets).to_csv(index=False, lineterminator="\n")


def check_unchanged(before, after_text):
    """Every original column, read back from the new text, is unchanged."""

    after = pd.read_csv(io.StringIO(after_text))

    for column in before.columns:
        old, new = before[column], after[column]
        if column == "Bet":
            old, new = old.astype("Int64"), new.astype("Int64")
        pd.testing.assert_series_equal(old, new, check_dtype=False)


def main():

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="Back up and write.")
    parser.add_argument("--backup", type=Path, default=BACKUP_PATH)
    args = parser.parse_args()

    before_text = BETS_PATH.read_text(encoding="utf-8")
    before = pd.read_csv(BETS_PATH)

    migrated, problems, warnings = migrate(before)

    if problems:
        print("Not migrating - these bets don't check out:")
        for problem in problems:
            print(f"  {problem}")
        sys.exit(1)

    after_text = _as_csv(migrated)
    check_unchanged(before, after_text)

    print(f"{len(before)} bet(s); columns:")
    print(f"  before: {','.join(before.columns)}")
    print(f"  after:  {','.join(pd.read_csv(io.StringIO(after_text)).columns)}")
    print(f"Season: {migrated['Season'].value_counts().to_dict()}")
    print(f"OddsSource: {migrated['OddsSource'].value_counts(dropna=False).to_dict()}")
    print("Every original column is unchanged.")
    if warnings:
        print(f"{len(warnings)} settled bet(s) left without odds:")
        for warning in warnings:
            print(f"  {warning}")

    diff = list(difflib.unified_diff(
        before_text.splitlines(), after_text.splitlines(),
        "Bets.csv (now)", "Bets.csv (migrated)", lineterm="", n=0,
    ))
    print(f"\nDiff ({sum(1 for d in diff if d.startswith('+') and not d.startswith('+++'))} line(s) change), first rows:")
    for line in diff[:9]:
        print(f"  {line}")

    if before_text == after_text:
        print("\nAlready migrated - nothing to write.")
        return

    if not args.apply:
        print("\nDry run - re-run with --apply to back up and write.")
        return

    if args.backup.exists():
        sys.exit(f"Backup {args.backup} already exists - move it away first.")

    shutil.copy2(BETS_PATH, args.backup)
    print(f"\nBacked up to {args.backup}")

    BETS_PATH.write_text(after_text, encoding="utf-8", newline="")
    print(f"Wrote {BETS_PATH}")


if __name__ == "__main__":
    main()
