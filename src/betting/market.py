"""
Bookmaker prices: which columns each odds source uses, and the market's
de-margined probabilities.

Football-data's opening columns (B365H, AvgH, ...) are captured before
the weekend, roughly when the daily run predicts, so they're the price
we could have taken. The closing columns (B365CH, AvgCH, ...) are
kick-off prices, used only for closing-line value.
"""

import numpy as np
import pandas as pd


# Per market, per source: (opening column, closing column) for each
# selection, in order of preference - a selection falls back to the
# next pair when the first has no price.
ODDS_SOURCES = {
    "avg": {
        "1X2": [("Avg{s}", "AvgC{s}")],
        "OU25": [("Avg{s}", "AvgC{s}")],
        "AH": [("AvgAH{s}", "AvgCAH{s}")],
    },
    "b365": {
        "1X2": [("B365{s}", "B365C{s}")],
        "OU25": [("B365{s}", "B365C{s}")],
        "AH": [("B365AH{s}", "B365CAH{s}")],
    },
    "max": {
        "1X2": [("Max{s}", "MaxC{s}")],
        "OU25": [("Max{s}", "MaxC{s}")],
        "AH": [("MaxAH{s}", "MaxCAH{s}")],
    },
    "pinnacle": {
        "1X2": [("PS{s}", "PSC{s}")],
        "OU25": [("P{s}", "PC{s}")],
        "AH": [("PAH{s}", "PCAH{s}")],
    },
    # What the live pipeline and backtest.py settle at: Sky Bet (from
    # 2026/27), else the market average
    "live": {
        "1X2": [("SKB{s}", "SKBC{s}"), ("Avg{s}", "AvgC{s}")],
        "OU25": [("Avg{s}", "AvgC{s}")],
        "AH": [("AvgAH{s}", "AvgCAH{s}")],
    },
}

# Selection codes per market, and the suffix football-data uses for them
SELECTIONS = {
    "1X2": {"H": "H", "D": "D", "A": "A"},
    "OU25": {"O": ">2.5", "U": "<2.5"},
    "AH": {"H": "H", "A": "A"},
}

# Asian-handicap line (home team's handicap), opening and closing
AH_LINE = "AHh"
AH_CLOSING_LINE = "AHCh"


def odds_columns():
    """Every odds column any source reads, plus the AH lines."""

    columns = []
    for markets in ODDS_SOURCES.values():
        for market, pairs in markets.items():
            for opening, closing in pairs:
                for suffix in SELECTIONS[market].values():
                    for col in (opening.format(s=suffix), closing.format(s=suffix)):
                        if col not in columns:
                            columns.append(col)

    return columns + [AH_LINE, AH_CLOSING_LINE]


def prices(frame, source, market, selection):
    """
    Opening and closing odds for ``selection`` in ``market`` from
    ``source``, per row of ``frame`` (NaN where none). Each row falls
    back through the source's column pairs, opening and closing
    separately.
    """

    if source not in ODDS_SOURCES:
        raise ValueError(f"Unknown odds source {source!r}; one of {sorted(ODDS_SOURCES)}")

    suffix = SELECTIONS[market][selection]
    opening = pd.Series(np.nan, index=frame.index)
    closing = pd.Series(np.nan, index=frame.index)

    for open_col, close_col in ODDS_SOURCES[source][market]:
        open_col, close_col = open_col.format(s=suffix), close_col.format(s=suffix)
        if open_col in frame.columns:
            opening = opening.fillna(frame[open_col])
        if close_col in frame.columns:
            closing = closing.fillna(frame[close_col])

    return opening, closing


# ============================================================
# DE-MARGINING
# ============================================================

def proportional(odds):
    """Implied probabilities scaled to sum to 1 (rows of ``odds``)."""

    implied = 1 / np.asarray(odds, dtype=float)

    return implied / implied.sum(axis=1, keepdims=True)


def _shin_row(implied, tol=1e-12):
    """Shin's probabilities for one row of implied probabilities."""

    booksum = implied.sum()

    def probs(z):
        return (np.sqrt(z ** 2 + 4 * (1 - z) * implied ** 2 / booksum) - z) / (2 * (1 - z))

    # sum(probs(z)) falls from booksum (z=0) towards ~0; find where it's 1
    if booksum <= 1:
        return implied / booksum

    low, high = 0.0, 0.5
    while high - low > tol:
        mid = (low + high) / 2
        if probs(mid).sum() > 1:
            low = mid
        else:
            high = mid

    p = probs((low + high) / 2)

    return p / p.sum()


def shin(odds):
    """
    Shin's (1993) de-margining, which takes more margin off longshots
    than favourites. Rows with a missing price come back NaN.
    """

    implied = 1 / np.asarray(odds, dtype=float)
    out = np.full_like(implied, np.nan)

    for i, row in enumerate(implied):
        if np.isfinite(row).all():
            out[i] = _shin_row(row)

    return out


DEMARGIN = {"proportional": proportional, "shin": shin}

# Market-probability sources: Pinnacle first (the sharpest book), then
# the market average
MARKET_PROB_SOURCES = [("pinnacle", "PS{s}", "PSC{s}"), ("avg", "Avg{s}", "AvgC{s}")]


def market_probabilities(frame, method="proportional"):
    """
    De-margined 1X2 probabilities: ``qH, qD, qA`` (opening) and ``qcH,
    qcD, qcA`` (closing), each from Pinnacle where it has all three
    prices, else the market average; ``qSource`` / ``qcSource`` say which.
    """

    demargin = DEMARGIN[method]
    out = pd.DataFrame(index=frame.index)

    for prefix, which in [("q", 1), ("qc", 2)]:
        probs = np.full((len(frame), 3), np.nan)
        source = pd.Series(pd.NA, index=frame.index, dtype="string")

        for name, *templates in MARKET_PROB_SOURCES:
            template = templates[which - 1]
            cols = [template.format(s=s) for s in "HDA"]
            if not all(c in frame.columns for c in cols):
                continue

            odds = frame[cols].to_numpy(dtype=float)
            usable = np.isfinite(odds).all(axis=1) & (odds > 1).all(axis=1) & source.isna().to_numpy()
            if usable.any():
                probs[usable] = demargin(odds[usable])
                source[usable] = name

        for i, s in enumerate("HDA"):
            out[f"{prefix}{s}"] = probs[:, i]
        out[f"{prefix}Source"] = source

    return out
