"""
Shared log of every betting-strategy variant tried in Phase 8.

README "Phase 8": picking the best of hundreds of backtests and calling
it a strategy is the main trap, so every variant a ticket tries goes in
``data/processed/betting_variants.csv`` and P8-07 corrects for the count.

One row per (ticket, family, variant, source, period). A ticket's rows
are replaced as a whole each time its notebook runs, so the log always
matches the latest run.

    from betting.variants import log_variants, load_variants

    log_variants(frame, ticket="P8-03")
    load_variants().groupby("ticket")["variant"].nunique()
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
VARIANTS_PATH = ROOT / "data" / "processed" / "betting_variants.csv"

COLUMNS = [
    "ticket", "family", "variant", "source", "period",
    "bets", "bets_per_week", "hit_rate", "avg_odds", "roi", "roi_ci_low", "roi_ci_high", "clv",
]


def load_variants(path=VARIANTS_PATH):

    if not Path(path).exists():
        return pd.DataFrame(columns=COLUMNS)

    return pd.read_csv(path)


def log_variants(frame, ticket, path=VARIANTS_PATH):
    """
    Replace ``ticket``'s rows in the log with ``frame`` (which needs the
    COLUMNS other than ``ticket``). Returns the full log.
    """

    missing = [c for c in COLUMNS if c != "ticket" and c not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    rows = frame.assign(ticket=ticket)[COLUMNS]
    if rows.duplicated(["family", "variant", "source", "period"]).any():
        raise ValueError("Duplicate (family, variant, source, period) rows")

    log = load_variants(path)
    log = pd.concat([log[log["ticket"] != ticket], rows], ignore_index=True)
    log.to_csv(path, index=False)

    return log


# ============================================================
# WEEKLY P&L AND CHOSEN-RULE BETS (for P8-07)
# ============================================================
# The multiple-testing correction (White's Reality Check / Hansen's SPA)
# resamples the same weeks for every variant, so it needs each variant's
# profit and stake per betting week, not just the summary row above.

WEEKS_PATH = ROOT / "data" / "processed" / "betting_variant_weeks.csv.gz"
CHOSEN_BETS_PATH = ROOT / "data" / "processed" / "betting_chosen_bets.csv"

WEEK_COLUMNS = ["ticket", "family", "variant", "source", "Week", "profit", "staked"]
BET_COLUMNS = ["ticket", "rule", "source", "Season", "Week", "Div", "MatchKey", "selection",
               "odds", "stake", "profit", "clv"]


def _replace_ticket(path, frame, ticket, columns):

    missing = [c for c in columns if c != "ticket" and c not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    rows = frame.assign(ticket=ticket)[columns]
    old = pd.read_csv(path) if Path(path).exists() else pd.DataFrame(columns=columns)
    out = pd.concat([old[old["ticket"] != ticket], rows], ignore_index=True)
    out.to_csv(path, index=False)

    return out


def log_variant_weeks(frame, ticket, path=WEEKS_PATH):
    """
    Replace ``ticket``'s weekly P&L rows: one row per (family, variant,
    source, Week) with a stake. Weeks without a bet are left out; the
    reader fills them with 0.
    """

    frame = frame[frame["staked"] > 0]
    if frame.duplicated(["family", "variant", "source", "Week"]).any():
        raise ValueError("Duplicate (family, variant, source, Week) rows")

    return _replace_ticket(path, frame, ticket, WEEK_COLUMNS)


def load_variant_weeks(path=WEEKS_PATH):

    return pd.read_csv(path)


def weekly_pnl(weeks, profit, staked=1.0):
    """Sum per-bet ``profit`` and ``staked`` by betting ``weeks`` (labels)."""

    frame = pd.DataFrame({"Week": weeks, "profit": profit, "staked": staked})

    return frame.groupby("Week", sort=False)[["profit", "staked"]].sum().reset_index()


def log_chosen_bets(frame, ticket, path=CHOSEN_BETS_PATH):
    """
    Replace ``ticket``'s individual bets for its pre-registered rule(s):
    one row per bet. An acca is one row (``Div`` = "multi", ``MatchKey``
    = its legs joined with " + "). ``clv`` = log(taken / closing), NaN
    where there is no closing price.
    """

    return _replace_ticket(path, frame, ticket, BET_COLUMNS)


def load_chosen_bets(path=CHOSEN_BETS_PATH):

    return pd.read_csv(path)
