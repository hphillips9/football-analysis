"""
Would strategy X have made money? Replays oos_predictions.csv week by
week through a strategy and settles its bets.

    from betting.simulate import load_oos, simulate, summarise, flat_argmax

    oos = load_oos()
    result = simulate(oos, flat_argmax, source="avg")
    summarise(result)                      # overall + per season
    compare(oos, flat_argmax)              # avg and max side by side

A strategy is a function ``(week, bankroll) -> list[Bet]``. ``week`` is
one betting week's matches with the result columns removed and the
chosen source's prices added as ``o<sel>`` (opening, e.g. oH, oO,
oAHH) and ``c<sel>`` (closing, for reference only). ``bankroll`` is the
bankroll at the start of the week, or None when the simulation runs
without one (flat staking).

A Bet is a list of legs and a stake. A single is a one-leg bet; an
accumulator wins only if every leg does, at the product of the legs'
odds. A leg on a match without a result (void / postponed) counts at
odds 1.0. A bet with an unpriced leg isn't placed (counted as
"unpriced").
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from betting.market import AH_CLOSING_LINE, AH_LINE, SELECTIONS, prices

ROOT = Path(__file__).resolve().parents[2]
OOS_PATH = ROOT / "data" / "processed" / "oos_predictions.csv"

N_BOOT = 5000
SEED = 42

# Kept from strategies: they'd give the result away
RESULT_COLUMNS = ["FTR", "FTHG", "FTAG"]

# Betting weeks start on Tuesday (pandas weekday 1)
TUESDAY = 1


# ============================================================
# BETTING WEEKS
# ============================================================

def bet_week(datetimes, starts=(TUESDAY,)):
    """
    The betting week (window) each kick-off falls in, labelled by the
    window's first day ("YYYY-MM-DD"). Default: Tuesday-Monday. With
    several start weekdays the week splits, e.g. ``(1, 4)`` gives
    Tuesday-Thursday (midweek) and Friday-Monday (weekend).
    """

    dates = pd.to_datetime(pd.Series(datetimes)).dt.normalize()
    starts = sorted(set(starts))
    weekday = dates.dt.weekday

    # Days back to the most recent window start on or before each date
    back = pd.Series(7, index=dates.index)
    for start in starts:
        back = np.minimum(back, (weekday - start) % 7)

    return (dates - pd.to_timedelta(back, unit="D")).dt.strftime("%Y-%m-%d").to_numpy()


# ============================================================
# BETS
# ============================================================

@dataclass(frozen=True)
class Leg:
    match: str          # MatchKey
    selection: str      # H/D/A (1X2), O/U (OU25), H/A (AH)
    market: str = "1X2"


@dataclass
class Bet:
    legs: list
    stake: float

    def __post_init__(self):
        self.legs = [leg if isinstance(leg, Leg) else Leg(*leg) for leg in self.legs]


def single(match, selection, stake, market="1X2"):
    return Bet([Leg(match, selection, market)], stake)


def leg_return(row, leg, odds):
    """
    What one unit on ``leg`` returns, given the match ``row`` and the
    leg's ``odds``: ``odds`` for a win, 0 for a loss, 1 for a void or
    push, halfway for a half win / half loss (quarter AH lines).
    """

    if pd.isna(row["FTR"]) or pd.isna(row["FTHG"]) or pd.isna(row["FTAG"]):
        return 1.0

    if leg.market == "1X2":
        return odds if row["FTR"] == leg.selection else 0.0

    goals = row["FTHG"] + row["FTAG"]

    if leg.market == "OU25":
        won = goals > 2.5 if leg.selection == "O" else goals < 2.5
        return odds if won else 0.0

    if leg.market == "AH":
        line = row[AH_LINE]
        if pd.isna(line):
            return 1.0
        margin = row["FTHG"] - row["FTAG"]
        if leg.selection == "A":
            margin, line = -margin, -line
        # A quarter line is half the stake on each neighbouring line
        halves = [line - 0.25, line + 0.25] if (line * 4) % 2 == 1 else [line]
        returns = [
            odds if margin + h > 0 else 1.0 if margin + h == 0 else 0.0
            for h in halves
        ]
        return float(np.mean(returns))

    raise ValueError(f"Unknown market {leg.market!r}")


# ============================================================
# SIMULATION
# ============================================================

@dataclass
class Result:
    source: str
    bets: pd.DataFrame       # one row per placed bet
    legs: pd.DataFrame       # one row per leg of a placed bet
    weeks: pd.DataFrame      # one row per betting week
    start_bankroll: float = None
    ruin_level: float = 0.0
    unpriced: int = 0
    params: dict = field(default_factory=dict)


def load_oos(path=OOS_PATH):

    oos = pd.read_csv(path, low_memory=False, float_precision="round_trip")
    oos["MatchDateTime"] = pd.to_datetime(oos["MatchDateTime"])

    return oos


def _with_prices(frame, source):
    """``frame`` plus o<sel> / c<sel> columns from ``source``."""

    out = frame.copy()
    for market, selections in SELECTIONS.items():
        for sel in selections:
            name = _price_column(Leg("", sel, market))
            out["o" + name], out["c" + name] = prices(frame, source, market, sel)

    return out


def _price_column(leg):
    """The o<...> / c<...> suffix for a leg: H, D, A, O, U, AHH, AHA."""

    if leg.market == "AH":
        return "AH" + leg.selection
    return leg.selection


def simulate(oos, strategy, source="avg", bankroll=None, ruin_level=0.01, week_starts=None):
    """
    Run ``strategy`` over ``oos`` week by week at ``source``'s opening
    prices.

    ``bankroll``: None for flat staking (stakes are whatever the strategy
    says, no limit), or a starting bankroll: each week's stakes are then
    scaled down if they'd exceed it, and betting stops once it falls to
    ``ruin_level`` of the start. ``week_starts`` re-buckets the weeks
    (see bet_week); default uses oos's BetWeek.
    """

    frame = _with_prices(oos, source)
    if week_starts is not None:
        frame["BetWeek"] = bet_week(frame["MatchDateTime"], week_starts)

    frame = frame.sort_values(["MatchDateTime", "Div", "HomeTeam"])
    by_key = frame.set_index("MatchKey")
    if not by_key.index.is_unique:
        raise ValueError("MatchKey isn't unique")

    hidden = [c for c in RESULT_COLUMNS if c in frame.columns]

    bet_rows, leg_rows, week_rows = [], [], []
    unpriced = 0
    current = bankroll
    ruined = False

    for (season, week), matches in frame.groupby(["Season", "BetWeek"], sort=False):

        start = current
        placed = []

        if not ruined:
            for bet in strategy(matches.drop(columns=hidden), current) or []:
                if bet.stake <= 0 or not bet.legs:
                    continue
                rows = [by_key.loc[leg.match] for leg in bet.legs]
                odds = [row["o" + _price_column(leg)] for row, leg in zip(rows, bet.legs)]
                if any(pd.isna(o) or o <= 1 for o in odds):
                    unpriced += 1
                    continue
                placed.append((bet, rows, odds))

        # Can't stake more than the bankroll
        total = sum(bet.stake for bet, _, _ in placed)
        scale = 1.0
        if bankroll is not None and total > current > 0:
            scale = current / total

        week_profit = 0.0
        week_staked = 0.0

        for bet, rows, odds in placed:

            stake = bet.stake * scale
            returns = []
            for row, leg, o in zip(rows, bet.legs, odds):
                r = leg_return(row, leg, o)
                returns.append(r)
                closing = row["c" + _price_column(leg)]
                if leg.market == "AH" and row[AH_CLOSING_LINE] != row[AH_LINE]:
                    closing = np.nan  # different line: prices don't compare
                leg_rows.append({
                    "bet": len(bet_rows),
                    "MatchKey": leg.match,
                    "market": leg.market,
                    "selection": leg.selection,
                    "odds": o,
                    "closing": closing,
                    "clv": np.log(o / closing) if pd.notna(closing) and closing > 0 else np.nan,
                    "return": r,
                })

            payout = stake * float(np.prod(returns))
            profit = payout - stake
            week_profit += profit
            week_staked += stake

            bet_rows.append({
                "Season": season,
                "BetWeek": week,
                "settled": max(row["MatchDateTime"] for row in rows),
                "legs": len(bet.legs),
                "stake": stake,
                "odds": float(np.prod(odds)),
                "payout": payout,
                "profit": profit,
                "won": payout > stake,
                "lost": payout < stake,
            })

        if bankroll is not None:
            current = start + week_profit
            if current <= ruin_level * bankroll:
                ruined = True

        week_rows.append({
            "Season": season,
            "BetWeek": week,
            "bets": len(placed),
            "staked": week_staked,
            "profit": week_profit,
            "bankroll_start": start,
            "bankroll_end": current,
        })

    return Result(
        source=source,
        bets=pd.DataFrame(bet_rows, columns=[
            "Season", "BetWeek", "settled", "legs", "stake", "odds",
            "payout", "profit", "won", "lost",
        ]),
        legs=pd.DataFrame(leg_rows, columns=[
            "bet", "MatchKey", "market", "selection", "odds", "closing", "clv", "return",
        ]),
        weeks=pd.DataFrame(week_rows),
        start_bankroll=bankroll,
        ruin_level=ruin_level,
        unpriced=unpriced,
    )


# ============================================================
# METRICS
# ============================================================

def _longest_losing_run(bets):

    longest = run = 0
    for lost in bets.sort_values("settled")["lost"]:
        run = run + 1 if lost else 0
        longest = max(longest, run)

    return longest


def _max_drawdown(weekly_profit):
    """Largest peak-to-trough fall in cumulative profit (units, >= 0)."""

    cumulative = np.concatenate([[0.0], np.cumsum(weekly_profit)])

    return float((np.maximum.accumulate(cumulative) - cumulative).max())


def bootstrap_roi(weeks, n=N_BOOT, seed=SEED):
    """
    ROI (profit / staked) with a 95% CI from resampling betting weeks
    (not bets: a week's bets share a bankroll and accas share legs).
    Weeks without a stake still count as weeks.
    """

    profit = weeks["profit"].to_numpy(dtype=float)
    staked = weeks["staked"].to_numpy(dtype=float)

    if staked.sum() == 0:
        return {"mean": np.nan, "ci": (np.nan, np.nan)}

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(weeks), size=(n, len(weeks)))
    boot_staked = staked[idx].sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = profit[idx].sum(axis=1) / boot_staked
    boot = boot[boot_staked > 0]

    low, high = np.percentile(boot, [2.5, 97.5])

    return {"mean": float(boot.mean()), "ci": (float(low), float(high))}


def risk_of_ruin(weeks, ruin_level, n=N_BOOT, seed=SEED):
    """
    Share of bankroll paths that hit ``ruin_level`` of the start when
    the weekly growth factors (bankroll_end / bankroll_start) are
    resampled with replacement - fixed-fraction staking assumed.
    """

    live = weeks[weeks["bankroll_start"] > 0]
    growth = (live["bankroll_end"] / live["bankroll_start"]).to_numpy(dtype=float)

    if len(growth) == 0:
        return np.nan

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(growth), size=(n, len(growth)))
    paths = np.cumprod(np.clip(growth[idx], 0, None), axis=1)

    return float((paths.min(axis=1) <= ruin_level).mean())


def _metrics(result, bets, legs, weeks):

    staked = bets["stake"].sum()
    profit = bets["profit"].sum()
    roi = bootstrap_roi(weeks)

    out = {
        "bets": int(len(bets)),
        "legs": int(len(legs)),
        "staked": round(float(staked), 2),
        "profit": round(float(profit), 2),
        "roi": round(float(profit / staked) * 100, 2) if staked else np.nan,
        "roi_ci_low": round(roi["ci"][0] * 100, 2),
        "roi_ci_high": round(roi["ci"][1] * 100, 2),
        "hit_rate": round(float(bets["won"].mean()) * 100, 1) if len(bets) else np.nan,
        "avg_odds": round(float(bets["odds"].mean()), 3) if len(bets) else np.nan,
        "clv": round(float(legs["clv"].mean()) * 100, 2) if legs["clv"].notna().any() else np.nan,
        "max_drawdown": round(_max_drawdown(weeks["profit"].to_numpy()), 2),
        "longest_losing_run": _longest_losing_run(bets),
        "weeks": int(len(weeks)),
        "weeks_in_profit": int((weeks["profit"] > 0).sum()),
    }

    if result.start_bankroll is not None and len(weeks):
        out["final_bankroll"] = round(float(weeks["bankroll_end"].iloc[-1]), 2)
        out["risk_of_ruin"] = round(
            risk_of_ruin(weeks, result.ruin_level) * 100, 1
        )

    return out


def summarise(result):
    """
    Metrics overall and per season. ROI, hit rate and CLV are percentages;
    CLV is the mean of log(taken odds / closing odds) per leg.
    """

    legs = result.legs.assign(
        Season=result.bets["Season"].reindex(result.legs["bet"]).to_numpy()
    )

    rows = []
    for season, weeks in result.weeks.groupby("Season"):
        rows.append({
            "season": season,
            **_metrics(
                result,
                result.bets[result.bets["Season"] == season],
                legs[legs["Season"] == season],
                weeks,
            ),
        })

    overall = {"season": "overall", **_metrics(result, result.bets, legs, result.weeks)}
    overall["seasons_in_profit"] = int(sum(r["profit"] > 0 for r in rows))
    overall["seasons"] = len(rows)
    overall["unpriced"] = result.unpriced

    return pd.DataFrame(rows + [overall]).set_index("season")


def compare(oos, strategy, sources=("avg", "max"), **kwargs):
    """summarise() for each odds source, side by side (source as the outer column)."""

    return pd.concat(
        {source: summarise(simulate(oos, strategy, source=source, **kwargs)) for source in sources},
        axis=1,
    )


# ============================================================
# REFERENCE STRATEGY
# ============================================================

def flat_argmax(week, bankroll, stake=1.0):
    """1 unit on the model's most likely result in every match (backtest.py's bet)."""

    # Columns in classes_ order (A, D, H) so ties go the way argmax does there
    proba = week[["pA", "pD", "pH"]].to_numpy()
    picks = np.array(["A", "D", "H"])[proba.argmax(axis=1)]

    return [single(key, pick, stake) for key, pick in zip(week["MatchKey"], picks)]
