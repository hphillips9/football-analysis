"""
Goals markets (P8-06): Over/Under 2.5 and Asian handicap probabilities
from a score distribution, and how to score them against the market.

A goals model gives each match a score grid P(home = i, away = j)
(independent Poisson from a pair of rates, or Dixon-Coles' grid). From
it:

    p_over(grid)                    P(more than 2.5 goals)
    margin_pmf(grid)                P(home - away = d), d = -MAX..MAX
    ah_coefficients(pmf, line)      A, B with E[return of 1u at odds o] = A*o + B
    ah_fair_probability(pmf, line)  1 / fair odds = A / (1 - B)

The AH ``line`` is the home side's handicap (football-data's ``AHh``;
-0.5 = home gives half a goal). A quarter line is half the stake on each
neighbouring line, so a bet can be half won and half pushed, which is
why AH is described by (A, B) rather than one win probability. The
"fair probability" A / (1 - B) is P(cover | not pushed), stake-weighted
over the halves; the market's de-margined two-way price estimates the
same thing, so the two compare directly.

``ah_log_loss`` scores that probability with a proper rule: each half
of the stake is a binary cover / not-cover outcome (pushed halves drop
out), weighted 1/2 on a quarter line. Its expectation is maximised by
the fair probability above.
"""

import numpy as np
from scipy.stats import poisson

# Goals per side the grid runs to (P(> 12) is ~1e-6 at a rate of 3)
MAX_GOALS = 12

GOALS = np.arange(MAX_GOALS + 1)


# ============================================================
# SCORE GRIDS
# ============================================================

def poisson_grid(home_rate, away_rate):
    """
    (n, MAX+1, MAX+1) score grids for independent Poisson goals with
    rates ``home_rate``, ``away_rate`` (arrays of length n), renormalised
    so each sums to 1.
    """

    home = poisson.pmf(GOALS[None, :], np.asarray(home_rate, dtype=float)[:, None])
    away = poisson.pmf(GOALS[None, :], np.asarray(away_rate, dtype=float)[:, None])
    grid = home[:, :, None] * away[:, None, :]

    return grid / grid.sum(axis=(1, 2), keepdims=True)


def hda(grid):
    """(n, 3) H/D/A probabilities from score grids."""

    home = np.tril(np.ones((MAX_GOALS + 1,) * 2), -1).astype(bool)  # i > j
    draw = np.eye(MAX_GOALS + 1, dtype=bool)

    return np.stack([
        grid[:, home].sum(axis=1), grid[:, draw].sum(axis=1), grid[:, home.T].sum(axis=1),
    ], axis=1)


def p_over(grid, line=2.5):
    """P(total goals > ``line``) per grid (``line`` a half-goal line)."""

    total = GOALS[:, None] + GOALS[None, :]

    return grid[:, total > line].sum(axis=1)


def margin_pmf(grid):
    """
    (n, 2*MAX+1) P(home goals - away goals = d), column d + MAX.
    """

    n = grid.shape[0]
    out = np.zeros((n, 2 * MAX_GOALS + 1))
    for d in range(-MAX_GOALS, MAX_GOALS + 1):
        out[:, d + MAX_GOALS] = np.trace(grid, offset=-d, axis1=1, axis2=2)

    return out


MARGINS = np.arange(-MAX_GOALS, MAX_GOALS + 1)


# ============================================================
# ASIAN HANDICAP
# ============================================================

def is_quarter(line):
    return np.isclose(np.mod(np.asarray(line, dtype=float) * 4, 2), 1)


def valid_line(line):
    """A line on the quarter-goal grid (football-data has the odd 1.83)."""

    line = np.asarray(line, dtype=float)

    return np.isfinite(line) & np.isclose(line * 4, np.round(line * 4))


def half_lines(line):
    """(n, 2) the two half-stake lines (equal unless ``line`` is a quarter line)."""

    line = np.asarray(line, dtype=float)
    shift = np.where(is_quarter(line), 0.25, 0.0)

    return np.stack([line - shift, line + shift], axis=1)


def ah_outcomes(margin, line, side="H"):
    """
    Per half stake: +1 covered, 0 pushed, -1 lost, for actual goal
    ``margin`` (home - away) on the home ``line``. Returns (n, 2) arrays;
    ``side`` "A" takes the other side of the same line.
    """

    margin = np.asarray(margin, dtype=float)
    if side == "A":
        margin, line = -margin, -np.asarray(line, dtype=float)

    return np.sign(margin[:, None] + half_lines(line))


def ah_coefficients(pmf, line, side="H"):
    """
    (A, B) per match with expected return of 1 unit at decimal odds o =
    A*o + B: A = expected share of the stake that wins, B = the share
    that's pushed (stake back).
    """

    pmf = np.asarray(pmf, dtype=float)
    line = np.asarray(line, dtype=float)
    if side == "A":
        pmf, line = pmf[:, ::-1], -line

    halves = half_lines(line)                                  # (n, 2)
    covered = MARGINS[None, :, None] + halves[:, None, :]      # (n, margins, 2)
    win = (covered > 0).mean(axis=2)
    push = (covered == 0).mean(axis=2)

    return (pmf * win).sum(axis=1), (pmf * push).sum(axis=1)


def ah_fair_probability(pmf, line, side="H"):
    """1 / fair odds for ``side`` on ``line``: A / (1 - B)."""

    a, b = ah_coefficients(pmf, line, side)
    with np.errstate(invalid="ignore", divide="ignore"):
        return a / (1 - b)


def ah_expected_return(pmf, line, odds, side="H"):
    """Expected return of 1 unit on ``side`` at ``odds`` (edge = this - 1)."""

    a, b = ah_coefficients(pmf, line, side)

    return a * np.asarray(odds, dtype=float) + b


def ah_log_loss(p_home, margin, line):
    """
    Per-match AH log loss of P(home covers | not pushed) = ``p_home``:
    each half stake that isn't pushed scores log p (home covered) or
    log(1 - p), weighted 1/2. Returns (loss, weight), weight = share of
    the stake not pushed; the mean loss is loss.sum() / weight.sum().
    """

    p = np.clip(np.asarray(p_home, dtype=float), 1e-15, 1 - 1e-15)
    outcome = ah_outcomes(margin, line)                        # (n, 2)

    loss = np.where(outcome > 0, -np.log(p)[:, None], np.where(outcome < 0, -np.log(1 - p)[:, None], 0.0))

    return loss.mean(axis=1), (outcome != 0).mean(axis=1)


# ============================================================
# PRICE CHECKS
# ============================================================
# A two-way book (1/o1 + 1/o2) under 1 is free money: impossible for one
# bookmaker or the market average, so those prices are bad data (25-26
# has ~50 rows where AvgAHA is the 1X2 away price). The best price across
# bookmakers can dip a little under 1, not far.

TWO_WAY_PAIRS = {
    "OU25": [("{p}>2.5", "{p}<2.5"), ("{p}C>2.5", "{p}C<2.5")],
    "AH": [("{p}AHH", "{p}AHA"), ("{p}CAHH", "{p}CAHA")],
}
BOOK_PREFIXES = {"Avg": 1.0, "B365": 1.0, "P": 1.0, "Max": 0.97}
MAX_BOOKSUM = 1.15


def clean_two_way(frame):
    """
    ``frame`` with implausible O/U 2.5 and AH price pairs set to NaN
    (either price <= 1, or a booksum outside [floor, MAX_BOOKSUM]; floor
    1.0, or 0.97 for the best price), and a count of the pairs removed
    per column pair.
    """

    out = frame.copy()
    removed = {}

    for pairs in TWO_WAY_PAIRS.values():
        for template in pairs:
            for prefix, floor in BOOK_PREFIXES.items():
                a, b = (t.format(p=prefix) for t in template)
                if a not in out.columns or b not in out.columns:
                    continue
                oa, ob = out[a].astype(float), out[b].astype(float)
                priced = oa.notna() | ob.notna()
                with np.errstate(divide="ignore", invalid="ignore"):
                    booksum = 1 / oa + 1 / ob
                ok = (oa > 1) & (ob > 1) & booksum.between(floor, MAX_BOOKSUM)
                bad = priced & ~ok
                out.loc[bad, [a, b]] = np.nan
                removed[f"{a}/{b}"] = int(bad.sum())

    return out, removed


def two_way_probability(frame, first, second):
    """Proportionally de-margined probability of the first of two prices."""

    with np.errstate(divide="ignore", invalid="ignore"):
        a, b = 1 / frame[first].astype(float), 1 / frame[second].astype(float)
        return (a / (a + b)).to_numpy()


# ============================================================
# H/D/A -> POISSON RATES (vectorised tie_progression.poisson_rates)
# ============================================================

def rates_from_hda(p_home, p_away, iterations=60):
    """
    Poisson rates (λh, λa) per match whose H and A probabilities are
    ``p_home`` and ``p_away``, by Newton's method on (log λh, log λa)
    with a numerical Jacobian. Same answer as
    tie_progression.poisson_rates, for many matches at once.
    """

    target = np.stack([np.asarray(p_home, float), np.asarray(p_away, float)], axis=1)
    x = np.tile(np.log([1.4, 1.1]), (len(target), 1))
    step = 1e-6

    def f(x):
        probs = hda(poisson_grid(np.exp(x[:, 0]), np.exp(x[:, 1])))
        return probs[:, [0, 2]] - target

    for _ in range(iterations):
        r = f(x)
        if np.abs(r).max() < 1e-10:
            break
        jac = np.empty((len(x), 2, 2))
        for k in range(2):
            dx = x.copy()
            dx[:, k] += step
            jac[:, :, k] = (f(dx) - r) / step
        delta = np.linalg.solve(jac, -r[:, :, None])[:, :, 0]
        x = np.clip(x + np.clip(delta, -1, 1), np.log(0.01), np.log(8))

    return np.exp(x[:, 0]), np.exp(x[:, 1])
