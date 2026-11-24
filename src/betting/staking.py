"""
Value bets and stake sizing (P8-04).

A value bet backs whichever outcome the probabilities say the price is
too generous on: edge = p * odds - 1. ``value_selection`` picks at most
one outcome per match (the largest edge) subject to an edge threshold,
an odds band and, optionally, the sharp-line check p_model > q.

Staking plans turn the chosen bets into stakes for ``simulate()``:

    strategy = value_strategy(rule, plan=kelly_plan(0.25))
    simulate(oos, strategy, source="avg", bankroll=100)

    flat_plan(1.0)              1 unit a bet
    edge_plan(10.0)             10 units x edge (1 unit at a 10% edge)
    percent_plan(0.01)          1% of the bankroll a bet
    kelly_plan(0.25)            quarter Kelly, capped per bet and per week
"""

import numpy as np
import pandas as pd

from betting.simulate import N_BOOT, SEED, single

OUTCOMES = ["H", "D", "A"]


# ============================================================
# SELECTION
# ============================================================

def value_selection(p, odds, min_edge=0.0, odds_range=(1.0, np.inf), sharp=None):
    """
    The value bet in each match: the outcome with the largest edge
    ``p * odds - 1`` among those that pass the filters, or none.

    ``p``, ``odds``: (n, 3) arrays in H, D, A order (NaN odds = no price).
    ``odds_range``: (low, high), inclusive. ``sharp``: optional (n, 3)
    boolean array an outcome must also be True in (e.g. p_model > q).

    Returns (selection index 0-2 or -1, edge of the selection or NaN).
    """

    p = np.asarray(p, dtype=float)
    odds = np.asarray(odds, dtype=float)

    with np.errstate(invalid="ignore"):
        edge = p * odds - 1
        ok = np.isfinite(edge) & (odds > 1) & (odds >= odds_range[0]) & (odds <= odds_range[1])
        ok &= edge >= min_edge
    if sharp is not None:
        ok &= np.asarray(sharp, dtype=bool)

    masked = np.where(ok, edge, -np.inf)
    sel = masked.argmax(axis=1)
    has = ok.any(axis=1)

    return np.where(has, sel, -1), np.where(has, masked[np.arange(len(p)), sel], np.nan)


def kelly_fraction(p, odds):
    """Full-Kelly share of bankroll for a single bet: (p*o - 1) / (o - 1), floored at 0."""

    p, odds = np.asarray(p, dtype=float), np.asarray(odds, dtype=float)

    return np.clip((p * odds - 1) / (odds - 1), 0, None)


# ============================================================
# STAKING PLANS
# ============================================================
# A plan maps one week's chosen bets (arrays p, odds, edge) and the
# bankroll at the start of the week to stakes.

def flat_plan(units=1.0):
    def plan(p, odds, edge, bankroll):
        return np.full(len(p), units)
    plan.label = f"flat {units:g}u"
    return plan


def edge_plan(units_per_edge=10.0, cap=None):
    def plan(p, odds, edge, bankroll):
        stakes = units_per_edge * np.clip(edge, 0, None)
        return np.minimum(stakes, cap) if cap is not None else stakes
    plan.label = f"{units_per_edge:g}u x edge"
    return plan


def percent_plan(share=0.01):
    def plan(p, odds, edge, bankroll):
        return np.full(len(p), share * max(bankroll or 0.0, 0.0))
    plan.label = f"{share:.0%} of bankroll"
    return plan


def kelly_plan(fraction=0.25, bet_cap=0.05, week_cap=0.20):
    """
    ``fraction`` x Kelly per bet, each bet capped at ``bet_cap`` of the
    bankroll, and the week's total scaled down to at most ``week_cap``
    of it (a week's bets are placed together, so they share a bankroll).
    """

    def plan(p, odds, edge, bankroll):
        bank = max(bankroll or 0.0, 0.0)
        share = np.minimum(fraction * kelly_fraction(p, odds), bet_cap)
        total = share.sum()
        if total > week_cap:
            share = share * week_cap / total
        return share * bank
    plan.label = f"{fraction:g} Kelly (cap {bet_cap:.0%}/bet, {week_cap:.0%}/week)"
    return plan


# ============================================================
# STRATEGY
# ============================================================

def value_strategy(rule, plan=None, p_columns=("pH", "pD", "pA")):
    """
    A ``simulate()`` strategy: each week, ``rule(week)`` returns
    (selection index, edge) per match (see value_selection), the bet is a
    single on that outcome, and ``plan`` sets the stakes (flat 1u by
    default). ``p_columns`` are the probabilities Kelly sizes with.
    """

    plan = plan or flat_plan(1.0)

    def strategy(week, bankroll):
        sel, edge = rule(week)
        chosen = np.flatnonzero(sel >= 0)
        if len(chosen) == 0:
            return []
        p = week[list(p_columns)].to_numpy(dtype=float)[chosen, sel[chosen]]
        odds = week[["oH", "oD", "oA"]].to_numpy(dtype=float)[chosen, sel[chosen]]
        stakes = plan(p, odds, edge[chosen], bankroll)
        keys = week["MatchKey"].to_numpy()
        return [
            single(keys[i], OUTCOMES[sel[i]], float(s))
            for i, s in zip(chosen, stakes) if s > 0
        ]

    return strategy


# ============================================================
# RISK
# ============================================================

def ruin_probability(weeks, start, level=0.2, multiplicative=True, n=N_BOOT, seed=SEED):
    """
    Share of bootstrap bankroll paths that fall to ``level`` x ``start``
    or below. Weeks are resampled with replacement (same length as the
    run). ``multiplicative``: resample weekly growth factors (stakes are
    a share of the bankroll); otherwise weekly profits in units, added to
    ``start`` (flat / unit stakes).
    """

    if multiplicative:
        live = weeks[weeks["bankroll_start"] > 0]
        growth = (live["bankroll_end"] / live["bankroll_start"]).to_numpy(dtype=float)
        if len(growth) == 0:
            return np.nan
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(growth), size=(n, len(growth)))
        paths = start * np.cumprod(np.clip(growth[idx], 0, None), axis=1)
    else:
        profit = weeks["profit"].to_numpy(dtype=float)
        if len(profit) == 0:
            return np.nan
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(profit), size=(n, len(profit)))
        paths = start + np.cumsum(profit[idx], axis=1)

    return float((paths.min(axis=1) <= level * start).mean())


def bankroll_stats(result, level=0.2, multiplicative=True):
    """Final bankroll, max drawdown (units and % of peak), worst week, risk of ruin."""

    weeks = result.weeks
    start = result.start_bankroll
    path = np.concatenate([[start], weeks["bankroll_end"].to_numpy(dtype=float)])
    peak = np.maximum.accumulate(path)

    staked = weeks["staked"].sum()

    return {
        "bets": int(len(result.bets)),
        "staked": float(staked),
        "roi": float(weeks["profit"].sum() / staked * 100) if staked else np.nan,
        "final_bankroll": float(path[-1]),
        "min_bankroll": float(path.min()),
        "max_drawdown": float((peak - path).max()),
        "max_drawdown_pct": float(((peak - path) / peak).max() * 100),
        "worst_week": float(weeks["profit"].min()) if len(weeks) else np.nan,
        "risk_of_ruin": ruin_probability(weeks, start, level, multiplicative) * 100,
    }


def bankroll_path(result):
    """Bankroll at the end of each week, indexed by (Season, BetWeek)."""

    return pd.Series(
        result.weeks["bankroll_end"].to_numpy(dtype=float),
        index=pd.MultiIndex.from_frame(result.weeks[["Season", "BetWeek"]]),
    )
